"""Invoice settlement inside the cash sheet, posted atomically with its revision."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from booking_cashup import OPEN_FIELDS, CLOSE_FIELDS, money


def register(app, db, Cashup, Booking, Entry, schedule, admin_required):
    @app.context_processor
    def invoice_context():
        if request.endpoint != 'admin_booking_cashup' or not session.get('admin_authenticated'):
            return {}
        booking = db.session.get(Booking, request.view_args['booking_id'])
        return dict(invoice_payment=app.extensions['payment_summary'](booking)) if booking else {}

    @app.post('/admin/bookings/<int:booking_id>/cash-up/invoice-payment')
    @admin_required
    def admin_cashup_invoice_payment(booking_id):
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        Cashup.query.order_by(Cashup.id).with_for_update().first()
        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        index = request.form.get('event_index', type=int)
        events = schedule(booking)
        if index is None or not 0 <= index < len(events):
            abort(400)
        event = events[index]
        date = event.get('date', '')
        latest = Cashup.query.filter_by(booking_id=booking.id, event_index=index, event_date=date).order_by(Cashup.revision.desc()).first()
        if booking.status != 'Accepted' or request.form.get('event_date') != date:
            abort(409, 'Reload the confirmed event before reconciling its payment.')
        if request.form.get('version', '') != (str(latest.id) if latest else ''):
            abort(409, 'The sheet changed. Reload before reconciling payment.')
        try:
            if latest and (latest.phase == 'Closed' or latest.values.get('invoice_reconciled')):
                raise ValueError('This event payment reconciliation is already saved. Use Payments for later ledger corrections; do not record the same receipt again.')
            checker = request.form.get('invoice_checked_by', '').strip()
            reference = request.form.get('invoice_reference', '').strip()
            if not checker or len(checker) > 255 or len(reference) > 255:
                raise ValueError('Enter the checker name and keep the invoice/reference within 255 characters.')
            physical = request.form.get('cash_handled')
            if physical not in ('yes', 'no'):
                raise ValueError('Choose whether physical cash was handled for this event.')
            if physical == 'yes' and not latest:
                raise ValueError('Save the opening till and safe checks first, then reconcile the cash invoice payment.')
            payment_state = request.form.get('invoice_payment_state')
            if payment_state not in ('full', 'partial', 'unpaid', 'not_applicable'):
                raise ValueError('Choose full payment, partial payment, unpaid or no client invoice expected.')
            new_amounts = {method: money(request.form.get(field, '0')) for method, field in
                [('Cash', 'invoice_new_cash'), ('SumUp', 'invoice_new_card'), ('Bank transfer', 'invoice_new_bank')]}
            added = sum(new_amounts.values(), Decimal(0))
            summary = app.extensions['payment_summary'](booking)
            if added > summary['outstanding']:
                raise ValueError('New invoice payments exceed the booking balance. Select an existing payment instead if it was already recorded.')
            if added and not reference:
                raise ValueError('Enter an invoice number or receipt reference for new payments.')
            paid_after = summary['paid'] + added
            if payment_state == 'full' and paid_after < summary['total']:
                raise ValueError('Full payment requires the complete booking price to be recorded.')
            if payment_state == 'partial' and not Decimal(0) < paid_after < summary['total']:
                raise ValueError('Partial payment must leave a balance outstanding.')
            if payment_state == 'unpaid' and paid_after != 0:
                raise ValueError('Payments are recorded for this booking. Choose full or partial payment.')
            if payment_state == 'not_applicable' and (added or paid_after):
                raise ValueError('Payments are recorded for this booking. Choose full or partial payment.')
            raw_ids = request.form.getlist('invoice_existing_ids')
            if len(raw_ids) > 200 or any(not value.isascii() or not value.isdigit() or len(value) > 12 for value in raw_ids):
                raise ValueError('Select valid payments from this booking.')
            ids = {int(value) for value in raw_ids}
            selected = Entry.query.filter(Entry.id.in_(ids), Entry.booking_id == booking.id, Entry.kind == 'payment').all() if ids else []
            if len(selected) != len(ids):
                raise ValueError('Only payments belonging to this booking can be selected.')
            if paid_after and not selected and not added:
                raise ValueError('Select the existing payment(s) being reconciled. They will not be recorded again.')
            if request.form.get('invoice_payment_confirmed') != 'yes':
                raise ValueError('Confirm you checked the invoice payments against the bank, SumUp or cash receipt.')
            till = Decimal(0)
            safe = Decimal(0)
            movement_ids = []
            snapshots = []
            for entry in selected:
                destination = request.form.get(f'invoice_destination_{entry.id}', 'already_accounted')
                if destination not in ('already_accounted', 'safe', 'till') or (destination != 'already_accounted' and entry.method != 'Cash'):
                    raise ValueError('Only cash payments can be allocated to the till or safe.')
                if destination != 'already_accounted':
                    for previous in Cashup.query.all():
                        if entry.id in previous.values.get('invoice_cash_entry_ids', []):
                            raise ValueError('This cash receipt is already allocated on a cash sheet. Do not add it to the safe or till again.')
                    movement_ids.append(entry.id)
                    if destination == 'safe': safe += entry.amount
                    else: till += entry.amount
                snapshots.append(dict(id=entry.id, amount=str(entry.amount), method=entry.method, paid_date=entry.paid_date.isoformat(), destination=destination))
            if new_amounts['Cash']:
                destination = request.form.get('invoice_cash_destination')
                if destination not in ('safe', 'till'):
                    raise ValueError('Choose where the new cash payment was placed: till or safe.')
                if destination == 'safe': safe += new_amounts['Cash']
                else: till += new_amounts['Cash']
            if physical == 'no' and (till or safe):
                raise ValueError('Cash added to a till or safe requires physical cash checks. Save the opening checks first.')
            if physical == 'no' and latest:
                raise ValueError('Opening cash checks are already saved. Complete the existing physical cash sheet.')
            start = datetime.fromisoformat(date + 'T' + event['start_time'])
            finish = datetime.fromisoformat(date + 'T' + event['finish_time'])
            if finish <= start: finish += timedelta(days=1)
            if physical == 'no' and finish > datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=None):
                raise ValueError('Complete the reconciliation after the event has finished.')
            received_date = None
            if added:
                received_date = datetime.strptime(request.form.get('invoice_paid_date', ''), '%Y-%m-%d').date()
                if received_date > datetime.now(ZoneInfo('Europe/London')).date():
                    raise ValueError('The payment date cannot be in the future.')
            for method, amount in new_amounts.items():
                if not amount: continue
                identity = f'{booking.id}:{index}:{date}:{method}'
                entry = Entry(booking_id=booking.id, token='cashup-invoice-' + hashlib.sha256(identity.encode()).hexdigest()[:48],
                    amount=amount, kind='payment', method=method, paid_date=received_date, note=f'Cash sheet invoice payment: {reference}'[:500])
                db.session.add(entry)
                db.session.flush()
                destination = request.form.get('invoice_cash_destination') if method == 'Cash' else 'not_cash'
                if method == 'Cash': movement_ids.append(entry.id)
                snapshots.append(dict(id=entry.id, amount=str(amount), method=method, paid_date=received_date.isoformat(), destination=destination))
            values = dict(latest.values) if latest else {field: '0.00' for field, _ in OPEN_FIELDS + CLOSE_FIELDS}
            stamp = datetime.now(ZoneInfo('Europe/London')).isoformat(timespec='seconds')
            values.update(invoice_reconciled=True, invoice_payment_state=payment_state, invoice_reference=reference,
                invoice_payments=snapshots, invoice_cash_entry_ids=movement_ids, invoice_cash_till=str(till), invoice_cash_safe=str(safe),
                invoice_paid_total=str(paid_after), invoice_outstanding=str(max(Decimal(0), summary['total']-paid_after)),
                invoice_checked_by=checker, invoice_checked_at=stamp, no_cash_handled=physical == 'no')
            if physical == 'no':
                values.update(checked_by=checker, closing_checked_at=stamp, share_percent='0',
                    event_description=f"{date} {event.get('start_time')}-{event.get('finish_time')}: {event.get('event_type', '')}")
            row = Cashup(booking_id=booking.id, event_index=index, event_date=date, revision=latest.revision+1 if latest else 1,
                phase='Draft' if latest else 'Closed', data_json=json.dumps(values), recorded_by=checker)
            db.session.add(row)
            db.session.commit()
            flash('Invoice reconciliation saved. Existing payments were not duplicated. New receipts were recorded once.', 'success')
        except (ValueError, KeyError, IntegrityError) as exc:
            db.session.rollback()
            flash(str(exc) if not isinstance(exc, IntegrityError) else 'This receipt or sheet was already saved. Reload before retrying.', 'error')
        return redirect(url_for('admin_booking_cashup', booking_id=booking.id, day=index,
            **({'embed': 1} if request.form.get('embed') == '1' else {})))
