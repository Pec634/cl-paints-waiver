"""Admin-only, versioned event-day cash counts and organiser settlements."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

OPEN_FIELDS = [('opening_till', 'Opening till float'), ('opening_safe', 'Opening safe cash')]
CLOSE_FIELDS = [
    ('cash_sales', 'Cash takings before refunds'), ('card_sales', 'Card takings before refunds'),
    ('cash_refunds', 'Cash refunds from till'), ('card_refunds', 'Card refunds'),
    ('till_to_safe', 'Cash moved from till to safe'), ('safe_to_till', 'Cash moved from safe to till'),
    ('share_till', 'Revenue share paid from till'), ('share_safe', 'Revenue share paid from safe'),
    ('share_bank', 'Revenue share paid by bank / card transfer'),
    ('till_other_in', 'Other cash added to till'), ('till_other_out', 'Other cash removed from till'),
    ('safe_other_in', 'Other cash added to safe'), ('safe_other_out', 'Other cash removed from safe / banked'),
    ('closing_till', 'Counted closing till cash'), ('closing_safe', 'Counted closing safe cash')]
DENOMINATIONS = [(5000, '50 pounds'), (2000, '20 pounds'), (1000, '10 pounds'), (500, '5 pounds'),
                 (200, '2 pounds'), (100, '1 pound'), (50, '50p'), (20, '20p'), (10, '10p'), (5, '5p'), (2, '2p'), (1, '1p')]


def read_counts(form, field):
    counts = {}
    for pence, _ in DENOMINATIONS:
        raw = form.get(f'denom_{field}_{pence}', '0').strip()
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
            raise ValueError('Enter whole, non-negative numbers of notes and coins (up to 999,999 each).')
        counts[str(pence)] = int(raw)
    total = sum(int(pence)*count for pence, count in counts.items())
    return counts, money(Decimal(total)/100)


def float_return(values):
    counts = values.get('denominations', {})
    if 'opening_till' not in counts or 'closing_till' not in counts:
        return None
    rows = []
    for pence, label in DENOMINATIONS:
        target = counts['opening_till'].get(str(pence), 0)
        available = counts['closing_till'].get(str(pence), 0)
        keep = min(target, available)
        rows.append(dict(pence=pence, label=label, target=target, available=available,
                         keep=keep, short=max(0,target-available), surplus=available-keep))
    return dict(rows=rows, retained=Decimal(sum(r['keep']*r['pence'] for r in rows))/100,
                shortage=Decimal(sum(r['short']*r['pence'] for r in rows))/100,
                surplus=Decimal(sum(r['surplus']*r['pence'] for r in rows))/100)


def money(value, maximum='999999.99'):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 <= amount <= Decimal(maximum) or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Enter non-negative amounts with up to two decimal places.')


def totals(values):
    n = lambda field: Decimal(values.get(field, '0'))
    cash = n('cash_sales') - n('cash_refunds')
    net = cash + n('card_sales') - n('card_refunds')
    shared = n('share_till') + n('share_safe') + n('share_bank')
    due = (max(Decimal(0), net) * n('share_percent') / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    till = n('opening_till') + cash + n('safe_to_till') - n('till_to_safe') - n('share_till') + n('till_other_in') - n('till_other_out')
    safe = n('opening_safe') + n('till_to_safe') - n('safe_to_till') - n('share_safe') + n('safe_other_in') - n('safe_other_out')
    return dict(gross=n('cash_sales') + n('card_sales'), refunds=n('cash_refunds') + n('card_refunds'),
                net=net, shared=shared, share_due=due, share_remaining=due-shared, retained=net-shared,
                expected_till=till, expected_safe=safe, till_variance=n('closing_till')-till,
                safe_variance=n('closing_safe')-safe)


def define_model(db):
    class BookingCashup(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        event_index = db.Column(db.Integer, nullable=False)
        event_date = db.Column(db.String(10), nullable=False)
        revision = db.Column(db.Integer, nullable=False)
        phase = db.Column(db.String(10), nullable=False)
        data_json = db.Column(db.Text, nullable=False)
        recorded_by = db.Column(db.String(255), nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('booking_id', 'event_index', 'event_date', 'revision'),)

        @property
        def values(self):
            return json.loads(self.data_json)
    return BookingCashup


def register(app, db, Cashup, Booking, schedule, admin_required):
    def records(booking):
        return Cashup.query.filter_by(booking_id=booking.id).order_by(Cashup.recorded_at.desc(), Cashup.id.desc()).all()

    def latest_records(booking):
        found = {}
        for row in records(booking):
            found.setdefault((row.event_index, row.event_date), row)
        return list(found.values())

    @app.context_processor
    def context():
        if not session.get('admin_authenticated'):
            return {}
        return dict(booking_cashups=latest_records, cashup_totals=totals,
                    cashup_denominations=DENOMINATIONS, cashup_float_return=float_return)

    def timeline(booking):
        return [dict(at=row.recorded_at, label='Cash-up ' + ('correction' if row.values.get('correction_reason') else row.phase.lower()),
                     actor=row.recorded_by, details=f'Day {row.event_index + 1} ({row.event_date}), revision {row.revision}. ' + row.values.get('correction_reason', ''))
                for row in records(booking)]
    app.extensions['cashup_timeline'] = timeline

    @app.route('/admin/bookings/<int:booking_id>/cash-up', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_cashup(booking_id):
        booking = db.get_or_404(Booking, booking_id)
        if request.method == 'GET' and request.args.get('record'):
            saved = db.get_or_404(Cashup, request.args.get('record', type=int))
            if saved.booking_id != booking.id:
                abort(404)
            return cashup_report(booking, saved)
        events = schedule(booking)
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        selected = request.form.get('event_index', type=int) if request.method == 'POST' else request.args.get('day', 0, type=int)
        if selected is None or not 0 <= selected < len(events):
            abort(400)
        event = events[selected]
        date = event.get('date', '')
        latest = Cashup.query.filter_by(booking_id=booking.id, event_index=selected, event_date=date).order_by(Cashup.revision.desc()).first()
        if request.method == 'GET' and request.args.get('print') == '1':
            if not latest:
                abort(404)
            return cashup_report(booking, latest)
        values = latest.values if latest else {field: '0.00' for field, _ in OPEN_FIELDS + CLOSE_FIELDS}
        values.setdefault('share_percent', str(event.get('revenue_share_percent') or '0'))
        embedded = request.args.get('embed') == '1' or request.form.get('embed') == '1'
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')):
                abort(400)
            if booking.status != 'Accepted':
                abort(409, 'Cash-up requires a confirmed booking.')
            if request.form.get('event_date') != date:
                abort(409, 'This event date has changed. Reload before saving.')
            if request.form.get('version', '') != (str(latest.id) if latest else ''):
                abort(409, 'This cash-up has changed. Reload before saving.')
            action = request.form.get('action')
            if action not in ('open', 'draft', 'close', 'correct'):
                abort(400)
            try:
                if (action == 'open' and latest) or (action != 'open' and not latest):
                    raise ValueError('Save the opening checks before recording a closing cash-up.')
                if latest and latest.phase == 'Closed' and action != 'correct':
                    raise ValueError('This cash-up is closed. Use a correction with a reason.')
                if action == 'correct' and (not latest or latest.phase != 'Closed'):
                    raise ValueError('Only a closed cash-up can be corrected.')
                values = dict(values)
                for key in ('reviewed_at', 'reviewed_by', 'review_note'):
                    values.pop(key, None)
                fields = OPEN_FIELDS if action == 'open' else CLOSE_FIELDS
                breakdowns = dict(values.get('denominations', {}))
                for field, _ in fields:
                    if field in ('opening_till','opening_safe','closing_till','closing_safe') and request.form.get('count_'+field) == 'yes':
                        counts, total = read_counts(request.form, field)
                        breakdowns[field] = counts
                        values[field] = str(total)
                    else:
                        values[field] = str(money(request.form.get(field, '')))
                        breakdowns.pop(field, None)
                values['denominations'] = breakdowns
                for name in ('notes', 'recipient', 'transfer_reference', 'correction_reason', 'checked_by'):
                    text = request.form.get(name, '').strip()
                    if len(text) > (2000 if name == 'notes' else 255):
                        raise ValueError('Shorten the notes or transfer details and try again.')
                    values[name] = text
                if not values['checked_by']:
                    raise ValueError('Record the name of the person who checked the cash.')
                if action == 'correct' and not values['correction_reason']:
                    raise ValueError('Enter a reason for correcting the closed cash-up.')
                if action != 'correct':
                    values['correction_reason'] = ''
                if action == 'open':
                    if request.form.get('till_checked') != 'yes' or request.form.get('safe_checked') != 'yes':
                        raise ValueError('Confirm both opening till and safe checks, including zero counts.')
                    values['opening_checked_by'] = values['checked_by']
                    values['opening_checked_at'] = datetime.now(ZoneInfo('Europe/London')).isoformat(timespec='minutes')
                    values['event_description'] = f"{date} {event.get('start_time', '')}-{event.get('finish_time', '')}: {event.get('event_type', '')}, {event.get('event_address', '')}"
                else:
                    values['share_percent'] = str(money(request.form.get('share_percent', ''), '100'))
                    result = totals(values)
                    if result['shared'] > 0 and not values['recipient']:
                        raise ValueError('Record who received the revenue-sharing transfer.')
                    if any(money(values[field]) > 0 for field in ('till_other_in', 'till_other_out', 'safe_other_in', 'safe_other_out')) and not values['notes']:
                        raise ValueError('Explain other cash movements and banked cash in the notes.')
                    if action in ('close', 'correct'):
                        start = datetime.fromisoformat(date + 'T' + event['start_time'])
                        finish = datetime.fromisoformat(date + 'T' + event['finish_time'])
                        if finish <= start:
                            finish += timedelta(days=1)
                        if finish > datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=None):
                            raise ValueError('Close the cash-up after this event day has finished. You can save a draft now.')
                        if request.form.get('till_checked') != 'yes' or request.form.get('safe_checked') != 'yes':
                            raise ValueError('Confirm both closing till and safe checks.')
                        if (result['till_variance'] or result['safe_variance']) and not values['notes']:
                            raise ValueError('Explain any till or safe count differences in the notes.')
                        values['closing_checked_at'] = datetime.now(ZoneInfo('Europe/London')).isoformat(timespec='minutes')
                phase = 'Open' if action == 'open' else ('Draft' if action == 'draft' else 'Closed')
                row = Cashup(booking_id=booking.id, event_index=selected, event_date=date,
                             revision=latest.revision + 1 if latest else 1, phase=phase,
                             data_json=json.dumps(values), recorded_by=app.config.get('ADMIN_EMAIL') or 'CL Paints admin')
                db.session.add(row)
                db.session.commit()
                flash('Cash-up saved. Till takings and organiser transfers do not change the client payment ledger.', 'success')
                return redirect(url_for('admin_booking_cashup', booking_id=booking.id, day=selected, **({'embed':1} if embedded else {})))
            except (ValueError, InvalidOperation, KeyError) as exc:
                db.session.rollback()
                error = str(exc) or 'Check the event times and cash-up amounts.'
            except IntegrityError:
                db.session.rollback()
                abort(409, 'Another cash-up was saved. Reload before saving again.')
        response = app.make_response(render_template('admin_booking_cashup.html', booking=booking, events=events,
            selected=selected, event=event, latest=latest, values=values, result=totals(values),
            opening_fields=OPEN_FIELDS, closing_fields=CLOSE_FIELDS, history=records(booking),
            client_csrf=token, error=error, embedded=embedded))
        response.headers['Cache-Control'] = 'private, no-store'
        return response, 400 if error else 200

    def cashup_report(booking, saved):
        response = app.make_response(render_template('operational_report.html', kind='cashup', booking=booking,
            saved=saved, values=saved.values, totals=totals(saved.values),
            fields=OPEN_FIELDS+CLOSE_FIELDS, client_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32))))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.post('/admin/bookings/<int:booking_id>/cash-up/<int:record_id>/review')
    @admin_required
    def admin_cashup_review(booking_id, record_id):
        saved = db.get_or_404(Cashup, record_id)
        if saved.booking_id != booking_id:
            abort(404)
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        latest = Cashup.query.filter_by(booking_id=booking_id, event_index=saved.event_index,
            event_date=saved.event_date).order_by(Cashup.revision.desc()).first()
        if latest.id != saved.id or saved.phase != 'Closed':
            abort(409, 'Reload the latest closed cash-up before reviewing it.')
        note = request.form.get('review_note', '').strip()
        name = request.form.get('reviewed_by', '').strip()
        if not note or len(note)>1000 or not name or len(name)>200:
            abort(400, 'Enter the reviewer name and an explanation of the resolution (up to 1,000 characters).')
        values = dict(saved.values, review_note=note, reviewed_by=name,
            reviewed_at=datetime.now(ZoneInfo('Europe/London')).isoformat(timespec='minutes'))
        row = Cashup(booking_id=booking_id, event_index=saved.event_index, event_date=saved.event_date,
            revision=saved.revision+1, phase='Closed', data_json=json.dumps(values), recorded_by='CL Paints admin')
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            abort(409, 'The cash-up changed. Reload before reviewing.')
        flash('Cash-count review recorded. Any unpaid or overpaid revenue share remains outstanding.', 'success')
        return redirect(url_for('admin_booking_cashup', booking_id=booking_id, record=row.id))
