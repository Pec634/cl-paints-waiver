"""Read existing financial records for the consolidated income report."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import url_for

from booking_cashup import money
from sumup_invoice_sync import PREFIX as INVOICE_ENTRY_PREFIX


UK = ZoneInfo('Europe/London')
CASHUP_FIELDS = (
    ('cash_sales', 'payment', 'Cash', 'Manual cash takings'),
    ('card_sales', 'payment', 'Card', 'Manual card takings'),
    ('cash_refunds', 'refund', 'Cash', 'Manual cash refunds'),
    ('card_refunds', 'refund', 'Card', 'Manual card refunds'),
)


def _row(day, source, kind, method, reference, description, amount, url, **details):
    return dict(date=day, source=source, kind=kind, method=method, reference=reference,
                description=description, amount=amount, url=url, **details)


def _date_range(query, column, start, end, include_undated=False):
    if start is not None:
        query = query.filter((column >= start) | column.is_(None) if include_undated else column >= start)
    if end is not None:
        query = query.filter((column <= end) | column.is_(None) if include_undated else column <= end)
    return query


def _uk_date(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(UK).date()


def _utc_midnight(day):
    return datetime.combine(day, time.min, UK).astimezone(timezone.utc).replace(tzinfo=None)


def _datetime_range(query, column, start, end, include_undated=False):
    if start is not None:
        lower = column >= _utc_midnight(start)
        query = query.filter(lower | column.is_(None) if include_undated else lower)
    if end is not None and end < date.max:
        upper = column < _utc_midnight(end + timedelta(days=1))
        query = query.filter(upper | column.is_(None) if include_undated else upper)
    return query


def _booking_rows(db, Booking, Entry, start, end):
    entries = db.session.query(Entry, Booking).join(Booking, Booking.id == Entry.booking_id).filter(
        Entry.kind.in_(('payment', 'refund')), Entry.amount > 0)
    for entry, booking in _date_range(entries, Entry.paid_date, start, end):
        if entry.token.startswith(INVOICE_ENTRY_PREFIX):
            label = 'Verified SumUp invoice'
        elif entry.token.startswith('sumup-'):
            label = 'Verified SumUp checkout'
        elif entry.token.startswith('cashup-invoice-'):
            label = 'Cash-up invoice'
        else:
            label = 'Booking'
        reference = f'{booking.public_reference} / {entry.id}'
        yield _row(entry.paid_date, 'booking', entry.kind, entry.method, reference,
                   f'{label} {entry.kind}', entry.amount, url_for('admin_payments', booking_id=booking.id))


def _pos_rows(db, Sale, Refund, start, end):
    paid_at = db.func.coalesce(Sale.paid_at, Sale.created_at)
    sales = Sale.query.filter(Sale.status == 'Paid', Sale.amount > 0)
    for sale in _datetime_range(sales, paid_at, start, end):
        description = f'SumUp transaction {sale.transaction_code}' if sale.transaction_code else 'Till sale'
        yield _row(_uk_date(sale.paid_at or sale.created_at), 'pos', 'payment', sale.method,
                   sale.reference, description, sale.amount, url_for('pos_sale', sale_id=sale.id))

    refunds = db.session.query(Refund, Sale).join(Sale, Sale.id == Refund.sale_id).filter(
        Refund.status == 'Refunded', Refund.amount > 0)
    for refund, sale in _datetime_range(refunds, Refund.completed_at, start, end, include_undated=True):
        yield _row(_uk_date(refund.completed_at), 'pos', 'refund', refund.method, f'REF-{refund.id}',
                   f'Till refund for {sale.reference}', refund.amount, url_for('pos_sale', sale_id=sale.id))


def _cashup_rows(db, Booking, Cashup, start, end):
    latest = db.session.query(Cashup.booking_id, Cashup.event_index, Cashup.event_date,
                              db.func.max(Cashup.revision).label('revision')).filter(Cashup.phase == 'Closed')
    latest = _date_range(latest, Cashup.event_date, start.isoformat() if start else None,
                         end.isoformat() if end else None)
    latest = latest.group_by(Cashup.booking_id, Cashup.event_index, Cashup.event_date).subquery()
    checks = db.session.query(Cashup, Booking).join(latest, db.and_(Cashup.booking_id == latest.c.booking_id,
        Cashup.event_index == latest.c.event_index, Cashup.event_date == latest.c.event_date,
        Cashup.revision == latest.c.revision)).join(Booking, Booking.id == Cashup.booking_id)
    for record, booking in checks:
        values = record.values
        if values.get('no_cash_handled'):
            continue
        day = date.fromisoformat(record.event_date)
        reference = f'{booking.public_reference} / Day {record.event_index + 1}'
        url = url_for('admin_booking_cashup', booking_id=booking.id, record=record.id)
        # The POS and booking ledgers already hold the cash-up's linked transactions.
        for field, kind, method, description in CASHUP_FIELDS:
            amount = money(values.get(field, '0'))
            if amount:
                yield _row(day, 'cashup', kind, method, reference, description, amount, url)


def _creates_rows(Creates, start, end):
    orders = Creates.query.filter(Creates.paid > 0)
    for order in _date_range(orders, Creates.paid_date, start, end, include_undated=True):
        method = 'Card' if order.provider_id else 'Unknown'
        yield _row(order.paid_date, 'creates', 'payment', method, order.number,
                   'CL Creates order receipt', order.paid, url_for('creates_order', order_id=order.id),
                   entity_id=order.id)


def _moodboard_rows(Moodboard, start, end):
    orders = Moodboard.query.filter(Moodboard.paid.is_(True), Moodboard.amount > 0)
    for order in _date_range(orders, Moodboard.paid_date, start, end, include_undated=True):
        yield _row(order.paid_date, 'moodboard', 'payment', 'Card', f'MB-{order.id}',
                   'Moodboard order receipt', order.amount,
                   url_for('admin_moodboard_orders', event_id=order.event_id), entity_id=order.id)


def load_sources(db, Booking, Entry, Sale, Refund, Cashup, Creates, Moodboard, start, end, source):
    """Yield selected receipts and refunds, retaining undated records for reconciliation."""
    if source in ('', 'booking'):
        yield from _booking_rows(db, Booking, Entry, start, end)
    if source in ('', 'pos'):
        yield from _pos_rows(db, Sale, Refund, start, end)
    if source in ('', 'cashup'):
        yield from _cashup_rows(db, Booking, Cashup, start, end)
    if source in ('', 'creates'):
        yield from _creates_rows(Creates, start, end)
    if source in ('', 'moodboard'):
        yield from _moodboard_rows(Moodboard, start, end)
