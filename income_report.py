"""Owner-facing receipts and refunds, with a UK tax-year export."""
import csv
import io
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from income_sources import load_sources


UK = ZoneInfo('Europe/London')
ZERO = Decimal('0.00')
SOURCES = {'booking': 'Booking payments', 'pos': 'Till sales', 'cashup': 'Event cash-up',
           'creates': 'CL Creates', 'moodboard': 'Moodboard orders', 'other': 'Other income'}
METHODS = ('Card', 'Cash', 'Bank transfer', 'Cheque', 'Other', 'Unknown')
KINDS = {'payment': 'Payment', 'refund': 'Refund'}
SORTS = {'newest': 'Newest first', 'oldest': 'Oldest first', 'highest': 'Highest amount',
         'lowest': 'Lowest amount', 'source': 'Income source', 'method': 'Payment method',
         'reference': 'Reference'}
PAGE_SIZE = 50


def define_model(db):
    class IncomeReceipt(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        token = db.Column(db.String(64), unique=True, nullable=False)
        source = db.Column(db.String(20), nullable=False)
        order_id = db.Column(db.Integer)
        kind = db.Column(db.String(10), nullable=False)
        paid_date = db.Column(db.Date, nullable=False, index=True)
        amount = db.Column(db.Numeric(12, 2), nullable=False)
        method = db.Column(db.String(30), nullable=False)
        reference = db.Column(db.String(120), nullable=False)
        description = db.Column(db.String(300), nullable=False)
        recorded_by = db.Column(db.String(255), nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        voided_at = db.Column(db.DateTime)
        voided_by = db.Column(db.String(255))
        void_reason = db.Column(db.String(300))
        __table_args__ = (db.Index('ix_income_receipt_order', 'source', 'order_id'),)

    return IncomeReceipt


def tax_year(day):
    return day.year if (day.month, day.day) >= (4, 6) else day.year - 1


def read_day(value):
    if not value:
        return None
    day = date.fromisoformat(value)
    if day.isoformat() != value or not 1900 <= day.year <= 9998:
        raise ValueError('Enter a valid date.')
    return day


def period(filters):
    year = filters['tax_year']
    if year in ('all', 'undated'):
        return None, None
    if year == 'custom':
        try:
            start, end = read_day(filters['start']), read_day(filters['end'])
        except ValueError:
            raise ValueError('Enter valid dates for the custom range.') from None
        if start and end and start > end:
            raise ValueError('The start date must be on or before the end date.')
        return start, end
    if not (year.isascii() and year.isdecimal() and len(year) == 4 and 1900 <= int(year) <= 9997):
        raise ValueError('Choose a valid tax year.')
    return date(int(year), 4, 6), date(int(year) + 1, 4, 5)


def normalize_method(value):
    key = (value or '').strip().casefold()
    if key in ('sumup', 'card', 'card payment', 'online card'):
        return 'Card'
    if key in ('transfer', 'bank', 'bank transfer', 'bacs', 'bank payment'):
        return 'Bank transfer'
    if key in ('', 'unknown', 'not recorded'):
        return 'Unknown'
    return next((method for method in METHODS if key == method.casefold()), 'Other')


def csv_text(value):
    """Keep text entered by admins inert in spreadsheet software."""
    value = str(value or '')
    if value[:1] in ('\t', '\r', '\n') or value.lstrip()[:1] in ('=', '+', '-', '@'):
        return "'" + value
    return value


def register(app, db, Receipt, Booking, Entry, Sale, Refund, Cashup, Creates, Moodboard, admin_required):
    retail_models = {'creates': Creates, 'moodboard': Moodboard}

    def allocation_totals():
        return db.session.query(Receipt.source, Receipt.order_id, db.func.sum(Receipt.amount)).filter(
            Receipt.order_id.is_not(None), Receipt.voided_at.is_(None))

    def allocated_to(source, order_id):
        row = allocation_totals().filter(Receipt.source == source, Receipt.order_id == order_id).group_by(
            Receipt.source, Receipt.order_id).first()
        return row[2] if row else ZERO

    app.extensions['income_allocated_creates'] = lambda order_id: allocated_to('creates', order_id)

    def historical_remaining(source, order_id, lock=False):
        Model = retail_models[source]
        orders = Model.query.filter_by(id=order_id)
        if lock and db.engine.dialect.name == 'sqlite':
            # SQLite ignores SELECT FOR UPDATE. Take its writer lock before reading the available amount.
            db.session.execute(db.update(Model).where(Model.id == order_id).values(paid=Model.paid))
        order = (orders.with_for_update() if lock else orders).first_or_404()
        amount = (order.paid if source == 'creates' else order.amount if order.paid else ZERO)
        return ZERO if order.paid_date else amount - allocated_to(source, order.id)

    def adjust_undated(rows):
        order_rows = [row for row in rows if row['date'] is None and row.get('entity_id') is not None]
        if not order_rows:
            return rows
        allocated = {(source, order_id): amount for source, order_id, amount in
                     allocation_totals().group_by(Receipt.source, Receipt.order_id)}
        for row in order_rows:
            key = row['source'], row['entity_id']
            row['amount'] = max(ZERO, row['amount'] - allocated.get(key, ZERO))
            row['reconcile_url'] = url_for('admin_income_record', source=key[0], order_id=key[1])
        return [row for row in rows if row['amount'] > ZERO]

    def recorded_rows(start, end, source):
        if source and source not in ('other', *retail_models):
            return
        query = Receipt.query.filter(Receipt.voided_at.is_(None))
        if source:
            query = query.filter_by(source=source)
        if start:
            query = query.filter(Receipt.paid_date >= start)
        if end:
            query = query.filter(Receipt.paid_date <= end)
        for item in query:
            description = item.description
            if item.source == 'creates':
                description = f'Order O-{item.order_id:06d}. {description}'
            elif item.source == 'moodboard':
                description = f'Moodboard order #{item.order_id}. {description}'
            yield dict(date=item.paid_date, source=item.source, kind=item.kind, method=item.method,
                       reference=item.reference, description=description, amount=item.amount,
                       url=url_for('admin_income_receipt', receipt_id=item.id))

    def report_data():
        current = tax_year(datetime.now(UK).date())
        filters = dict(tax_year=request.args.get('tax_year', str(current)),
                       **{key: request.args.get(key, '').strip() for key in ('start', 'end', 'source', 'method', 'kind', 'q')},
                       sort=request.args.get('sort', 'newest'))
        filters['q'] = filters['q'][:120]
        rows, undated, error = [], [], ''
        try:
            start, end = period(filters)
            if (filters['source'] not in ('', *SOURCES) or filters['method'] not in ('', *METHODS)
                    or filters['kind'] not in ('', *KINDS) or filters['sort'] not in SORTS):
                raise ValueError('Choose a valid filter or sort option.')
        except ValueError as exc:
            error = str(exc)
        else:
            for key, value in (('start', start), ('end', end)):
                filters[key] = value.isoformat() if value else ''
            source = filters['source']
            records = adjust_undated(list(load_sources(db, Booking, Entry, Sale, Refund, Cashup,
                                                      Creates, Moodboard, start, end, source)))
            if filters['tax_year'] != 'undated':
                records.extend(recorded_rows(start, end, source))
            for row in records:
                row['method'] = normalize_method(row['method'])
                if filters['method'] and row['method'] != filters['method']:
                    continue
                if filters['kind'] and row['kind'] != filters['kind']:
                    continue
                row['source'] = SOURCES[row['source']]
                row['kind'] = KINDS[row['kind']]
                haystack = ' '.join((row['reference'], row['description'], row['source'], row['method']))
                if filters['q'].casefold() not in haystack.casefold():
                    continue
                if row['date'] is None:
                    undated.append(row)
                elif filters['tax_year'] != 'undated':
                    rows.append(row)
            if filters['tax_year'] == 'undated':
                rows = undated
            rows.sort(key=lambda row: (row['date'] or date.min, row['reference']), reverse=True)
            sort = filters['sort']
            if sort == 'oldest':
                rows.sort(key=lambda row: row['date'] or date.min)
            elif sort in ('lowest', 'highest'):
                rows.sort(key=lambda row: row['amount'], reverse=sort == 'highest')
            elif sort != 'newest':
                rows.sort(key=lambda row: row[sort].casefold())
        selected_year = int(filters['tax_year']) if not error and filters['tax_year'].isdigit() else current
        years = sorted(set(range(current - 9, current + 1)) | {selected_year}, reverse=True)
        tax_years = [(str(year), f'{year} to {year + 1}') for year in years]
        tax_years.extend((('custom', 'Custom dates'), ('all', 'All dated receipts'), ('undated', 'Needs a date')))
        received = sum((row['amount'] for row in rows if row['kind'] == 'Payment'), ZERO)
        refunds = sum((row['amount'] for row in rows if row['kind'] == 'Refund'), ZERO)
        return dict(filters=filters, tax_years=tax_years, sources=[('', 'All sources'), *SOURCES.items()],
                    methods=[('', 'All methods'), *((method, method) for method in METHODS)],
                    kinds=[('', 'Payments and refunds'), *KINDS.items()], sorts=SORTS.items(),
                    rows=rows, totals=dict(received=received, refunds=refunds, net=received-refunds, count=len(rows)),
                    undated_count=len(undated), undated_total=sum((row['amount'] for row in undated), ZERO), error=error)

    def filter_url(endpoint, filters, **updates):
        params = dict(filters, **updates)
        if params['tax_year'] != 'custom':
            params.pop('start', None)
            params.pop('end', None)
        return url_for(endpoint, **{key: value for key, value in params.items() if value})

    @app.get('/admin/income')
    @admin_required
    def admin_income():
        data = report_data()
        page_count = max(1, (data['totals']['count'] + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, request.args.get('page', 1, type=int)), page_count)
        filters = data['filters']
        data.update(rows=data['rows'][(page - 1) * PAGE_SIZE:page * PAGE_SIZE], page=page, page_count=page_count,
                    previous_url=filter_url('admin_income', filters, page=page - 1) if page > 1 else None,
                    next_url=filter_url('admin_income', filters, page=page + 1) if page < page_count else None,
                    export_url=filter_url('admin_income_export', filters),
                    undated_url=filter_url('admin_income', filters, tax_year='undated'),
                    manual_url=url_for('admin_income_record'))
        response = make_response(render_template('admin_income.html', **data), 400 if data['error'] else 200)
        response.cache_control.no_store = True
        return response

    @app.get('/admin/income/export.csv')
    @admin_required
    def admin_income_export():
        data = report_data()
        if data['error']:
            abort(400, description=data['error'])
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(('Payment date', 'Income source', 'Type', 'Payment method', 'Reference', 'Description',
                         'Amount (GBP)', 'Signed amount (GBP)'))
        for row in data['rows']:
            signed = -row['amount'] if row['kind'] == 'Refund' else row['amount']
            writer.writerow((row['date'] or '', row['source'], row['kind'], row['method'],
                             csv_text(row['reference']), csv_text(row['description']), f"{row['amount']:.2f}", f'{signed:.2f}'))
        response = make_response('\ufeff' + output.getvalue())
        response.headers.update({'Content-Type': 'text/csv; charset=utf-8',
                                 'Content-Disposition': 'attachment; filename="cl-paints-income.csv"'})
        response.cache_control.no_store = True
        return response

    @app.route('/admin/income/record', methods=['GET', 'POST'])
    @admin_required
    def admin_income_record():
        source = request.args.get('source', 'other')
        order_id = request.args.get('order_id', type=int)
        if (source == 'other' and order_id is not None) or (source != 'other' and (source not in retail_models or not order_id)):
            abort(400)
        today = datetime.now(UK).date()
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        key = f'income_receipt_{source}_{order_id or 0}'
        entry_token = session.setdefault(key, secrets.token_urlsafe(32))
        error = ''
        method = 'Card' if source == 'moodboard' else ''
        fields = dict(paid_date='' if order_id else today.isoformat(), amount='', reference='', description='', method=method, kind='payment')
        if request.method == 'POST':
            if not secrets.compare_digest(csrf.encode(), request.form.get('csrf_token', '').encode()):
                abort(400)
            token = request.form.get('entry_token', '')
            if token and Receipt.query.filter_by(token=token).first():
                return redirect(url_for('admin_income', tax_year='all'))
            if not secrets.compare_digest(entry_token.encode(), token.encode()):
                abort(400, description='Reload the form before recording another receipt.')
            fields.update({field: request.form.get(field, '').strip() for field in fields})
            try:
                paid_date = read_day(fields['paid_date'])
                if not paid_date or paid_date > today:
                    raise ValueError('Enter the date the payment or refund actually took place.')
                try:
                    amount = Decimal(fields['amount'])
                    if (not amount.is_finite() or not ZERO < amount <= Decimal('9999999999.99')
                            or amount != amount.quantize(Decimal('.01'))):
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise ValueError('Enter a positive amount with up to two decimal places.') from None
                if fields['kind'] not in KINDS or fields['method'] not in METHODS:
                    raise ValueError('Choose a payment type and method.')
                if not 1 <= len(fields['reference']) <= 120 or not 1 <= len(fields['description']) <= 300:
                    raise ValueError('Enter an evidence reference and description within the character limits.')
                if source != 'other':
                    remaining = historical_remaining(source, order_id, lock=True)
                    if fields['kind'] != 'payment' or amount > remaining:
                        raise ValueError(f'The remaining amount to date for this order is £{max(ZERO, remaining):,.2f}.')
                db.session.add(Receipt(token=token, source=source, order_id=order_id, kind=fields['kind'],
                    paid_date=paid_date, amount=amount, method=fields['method'], reference=fields['reference'],
                    description=fields['description'], recorded_by=app.config.get('ADMIN_EMAIL') or 'CL Paints admin'))
                db.session.commit()
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)
            except IntegrityError:
                db.session.rollback()
                if not Receipt.query.filter_by(token=token).first():
                    raise
                return redirect(url_for('admin_income', tax_year='all'))
            else:
                session.pop(key, None)
                flash('Income record saved.', 'success')
                return redirect(url_for('admin_income', tax_year=tax_year(paid_date), source=source))
        remaining = None
        if source != 'other':
            remaining = historical_remaining(source, order_id)
        recent = Receipt.query.filter_by(source=source, order_id=order_id).order_by(Receipt.id.desc()).limit(10).all()
        response = make_response(render_template('admin_income_record.html', csrf=csrf, today=today.isoformat(),
            fields=fields, entry_token=entry_token, error=error, methods=METHODS, source=SOURCES[source],
            remaining=remaining, order_id=order_id, recent=recent), 400 if error else 200)
        response.cache_control.no_store = True
        return response

    @app.route('/admin/income/receipts/<int:receipt_id>', methods=['GET', 'POST'])
    @admin_required
    def admin_income_receipt(receipt_id):
        record = db.get_or_404(Receipt, receipt_id)
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        error = ''
        if request.method == 'POST':
            if not secrets.compare_digest(csrf.encode(), request.form.get('csrf_token', '').encode()):
                abort(400)
            reason = request.form.get('reason', '').strip()
            if not 1 <= len(reason) <= 300:
                error = 'Enter a correction reason of up to 300 characters.'
            else:
                Receipt.query.filter_by(id=receipt_id, voided_at=None).update(dict(voided_at=datetime.utcnow(),
                    voided_by=app.config.get('ADMIN_EMAIL') or 'CL Paints admin', void_reason=reason))
                db.session.commit()
                return redirect(url_for('admin_income_receipt', receipt_id=receipt_id))
        response = make_response(render_template('admin_income_receipt.html', csrf=csrf, error=error, record=record,
            source=SOURCES[record.source], kind=KINDS[record.kind]), 400 if error else 200)
        response.cache_control.no_store = True
        return response
