"""Append-only, non-event physical cash transfers and combined cash-sheet history."""
from datetime import datetime, timedelta
from decimal import Decimal
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from booking_cashup import CLOSE_FIELDS, DENOMINATIONS, money, read_counts

LOCATIONS = {'till': 'Till', 'safe': 'Safe', 'bank': 'Bank', 'other': 'Other cash source / use'}
PAYMENT_LOCATIONS = dict(LOCATIONS, sumup='SumUp bank account')


def define_model(db):
    class CashMovement(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
        token = db.Column(db.String(64), unique=True, nullable=False)
        kind = db.Column(db.String(20), nullable=False)
        source = db.Column(db.String(20), nullable=False)
        destination = db.Column(db.String(20), nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        opening_till = db.Column(db.Numeric(10, 2))
        opening_safe = db.Column(db.Numeric(10, 2))
        reason = db.Column(db.String(1000), nullable=False)
        checked_by = db.Column(db.String(255), nullable=False)
        recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    return CashMovement


def define_till_count_model(db):
    class TillDenominationRecord(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        kind = db.Column(db.String(10), nullable=False, index=True)
        counts_json = db.Column(db.Text, nullable=False)
        total = db.Column(db.Numeric(10, 2), nullable=False)
        expected_total = db.Column(db.Numeric(10, 2))
        cash_version = db.Column(db.String(64), nullable=False)
        checked_by = db.Column(db.String(255), nullable=False)
        note = db.Column(db.String(1000), nullable=False, default='')
        recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

        @property
        def counts(self):
            return json.loads(self.counts_json)
    return TillDenominationRecord


def register(app, db, Movement, Cashup, Setting, TillCount, admin_required, Event):
    def lock():
        key = 'cash_journal_lock'
        if not db.session.get(Setting, key):
            # A savepoint preserves the caller's transaction if another worker creates it.
            try:
                with db.session.begin_nested():
                    db.session.add(Setting(key=key, value='1'))
                    db.session.flush()
            except IntegrityError:
                pass
        Setting.query.filter_by(key=key).with_for_update().one()

    def latest_checks():
        ids = db.session.query(db.func.max(Cashup.id)).group_by(Cashup.booking_id, Cashup.event_index, Cashup.event_date)
        return Cashup.query.filter(Cashup.id.in_(ids)).all()

    def position():
        physical = []
        checks = latest_checks()
        for row in checks:
            if row.phase != 'Closed' or row.values.get('no_cash_handled'):
                continue
            first = Cashup.query.filter_by(booking_id=row.booking_id, event_index=row.event_index,
                event_date=row.event_date, phase='Closed').order_by(Cashup.id).first()
            physical.append((first.recorded_at, first.id, row))
        baseline = max(physical, key=lambda item: (item[0], item[1])) if physical else None
        opening = Movement.query.filter_by(kind='opening').order_by(Movement.id).first()
        if baseline:
            at, _, row = baseline
            till, safe = money(row.values['closing_till']), money(row.values['closing_safe'])
        elif opening:
            at, row = opening.recorded_at, None
            till, safe = opening.opening_till, opening.opening_safe
        else:
            at, row, till, safe = None, None, None, None
        physical_records = Movement.query.filter(db.or_(Movement.kind == 'opening',
            db.and_(Movement.kind.in_(('transfer', 'pitch_fee', 'cash_check')),
                db.or_(Movement.source.in_(('till', 'safe')), Movement.destination.in_(('till', 'safe'))))))
        moves = physical_records.filter(Movement.kind != 'opening')
        if at is not None:
            moves = moves.filter(Movement.recorded_at > at)
        applied = []
        for movement in moves.order_by(Movement.id).all():
            if till is None:
                raise ValueError('Record initial cash counts before adding transfers.')
            till += movement.amount * ((movement.destination == 'till') - (movement.source == 'till'))
            safe += movement.amount * ((movement.destination == 'safe') - (movement.source == 'safe'))
            applied.append(movement.id)
        last = physical_records.order_by(Movement.id.desc()).first()
        version = f'{row.id if row else 0}:{last.id if last else 0}'
        return dict(till=till, safe=safe, version=version, movement_ids=applied, baseline=row,
                    has_movements=last is not None,
                    active=any(item.phase != 'Closed' for item in checks))

    app.extensions['cash_journal_position'] = position
    app.extensions['cash_journal_lock'] = lock

    def till_view(state=None):
        state = state or position()
        target = TillCount.query.filter_by(kind='target').order_by(TillCount.id.desc()).first()
        counted = TillCount.query.filter_by(kind='count').order_by(TillCount.id.desc()).first()
        current = counted.counts if counted else None
        at = counted.recorded_at if counted else None
        source = 'Till count' if counted else ''
        fresh = bool(counted and counted.cash_version == state['version'] and not state['active'])
        baseline = state['baseline']
        if baseline and baseline.values.get('denominations', {}).get('closing_till') is not None and (not at or baseline.recorded_at > at):
            current = baseline.values['denominations']['closing_till']
            at, source = baseline.recorded_at, 'Event closing till count'
            fresh = not state['movement_ids'] and not state['active']
        safe_counts = baseline.values.get('denominations', {}).get('closing_safe') if baseline else None
        safe_fresh = safe_counts is not None and not state['active']
        if safe_fresh and state['movement_ids']:
            safe_fresh = not Movement.query.filter(Movement.id.in_(state['movement_ids']),
                db.or_(Movement.source == 'safe', Movement.destination == 'safe')).first()
        rows = []
        for pence, label in DENOMINATIONS:
            desired = (target.counts if target else {}).get(str(pence), 0)
            actual = (current or {}).get(str(pence), 0)
            safe_quantity = safe_counts.get(str(pence), 0) if safe_counts is not None else None
            rows.append(dict(pence=pence, label=label, desired=desired, actual=actual,
                safe_quantity=safe_quantity, safe_value=Decimal(safe_quantity)*pence/100 if safe_quantity is not None else None,
                short=max(0, desired-actual), surplus=max(0, actual-desired)))
        return dict(target=target, counted=counted, current=current, current_at=at, source=source, fresh=fresh, rows=rows,
            safe_fresh=safe_fresh, safe_count_at=baseline.recorded_at if safe_counts is not None else None,
            current_total=sum(Decimal(row['actual'])*row['pence']/100 for row in rows) if current is not None else None,
            short_total=sum(Decimal(row['short'])*row['pence']/100 for row in rows))

    app.extensions['till_float_view'] = till_view

    @app.post('/admin/cash-movements/till-count')
    @admin_required
    def admin_till_denominations():
        csrf = session.get('cash_journal_csrf', '')
        if not csrf or not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
            abort(400)
        Cashup.query.order_by(Cashup.id).with_for_update().first()
        lock()
        state = position()
        kind = request.form.get('kind')
        if kind not in ('target', 'count'):
            abort(400)
        try:
            previous = TillCount.query.filter_by(kind=kind).order_by(TillCount.id.desc()).first()
            if request.form.get('record_version', '') != (str(previous.id) if previous else ''):
                raise ValueError('This denomination record changed. Reload before saving again.')
            if kind == 'count' and (state['active'] or request.form.get('cash_version') != state['version']):
                raise ValueError('Cash records changed or an event sheet is open. Close the event sheet and reload before counting here.')
            counts, total = read_counts(request.form, 'till')
            checker, note = request.form.get('checked_by', '').strip(), request.form.get('note', '').strip()
            if not checker or len(checker) > 255 or len(note) > 1000:
                raise ValueError('Enter the checker name (up to 255 characters) and keep notes within 1,000 characters.')
            if kind == 'count' and state['till'] is not None and total != state['till'] and not note:
                raise ValueError('Explain the difference between the counted till and expected balance in the notes.')
            db.session.add(TillCount(kind=kind, counts_json=json.dumps(counts), total=total,
                expected_total=state['till'] if kind == 'count' else None, cash_version=state['version'], checked_by=checker, note=note))
            db.session.commit()
            flash('Default till float saved.' if kind == 'target' else 'Till denomination count saved. Expected balances and money movements were not changed.', 'success')
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash(str(exc) if not isinstance(exc, IntegrityError) else 'The count changed. Reload before saving.', 'error')
        return redirect(url_for('admin_cash_movements'))

    @app.route('/admin/cash-movements', methods=['GET', 'POST'])
    @admin_required
    def admin_cash_movements():
        closed_event = None
        linked_event = None
        if request.args.get('event_id'):
            linked_event = db.get_or_404(Event, request.args.get('event_id', type=int))
            if not app.extensions['kiosk_public_event'](linked_event):
                abort(404)
        if request.args.get('closed_event'):
            closed_event = db.get_or_404(Event, request.args.get('closed_event', type=int))
            if closed_event.status != 'Closed' or not app.extensions['kiosk_public_event'](closed_event):
                abort(404)
            linked_event = closed_event
        csrf = session.setdefault('cash_journal_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
            token = request.form.get('movement_token', '')
            if token != session.get('cash_movement_token'):
                abort(409, 'Reload the cash journal before recording a transfer.')
            Cashup.query.order_by(Cashup.id).with_for_update().first()
            lock()
            if Movement.query.filter_by(token=token).first():
                flash('This cash movement is already recorded.', 'success')
                return redirect(url_for('admin_cash_movements'))
            state = position()
            try:
                if request.form.get('version') != state['version']:
                    raise ValueError('Cash records changed. Review the latest balances before saving.')
                action = request.form.get('action')
                payment_event = None
                if action in ('pitch_fee', 'till_sheet') and request.form.get('event_id'):
                    payment_event = db.session.get(Event, request.form.get('event_id', type=int))
                    if not payment_event or not app.extensions['kiosk_public_event'](payment_event):
                        raise ValueError('Choose a valid public event for this payment.')
                bank_pitch = action in ('pitch_fee', 'till_sheet') and request.form.get('source') == 'sumup'
                if state['active'] and not bank_pitch:
                    raise ValueError('An event cash sheet is open or in draft. Record this movement on that sheet, or close it before making a non-event transfer.')
                reason, checker = request.form.get('reason', '').strip(), request.form.get('checked_by', '').strip()
                if not reason or len(reason) > 1000 or not checker or len(checker) > 255:
                    raise ValueError('Enter a reason (up to 1,000 characters) and the person recording/checking the cash (up to 255).')
                if action in ('pitch_fee', 'till_sheet'):
                    source = request.form.get('source')
                    if source not in ('till', 'sumup'):
                        raise ValueError('Choose Till or SumUp bank account.')
                    if source == 'till':
                        if state['till'] is None:
                            raise ValueError('Set initial cash balances before paying a pitch fee from the till.')
                        previous = TillCount.query.filter_by(kind='count').order_by(TillCount.id.desc()).first()
                        if request.form.get('pitch_count_version', '') != (str(previous.id) if previous else ''):
                            raise ValueError('The till count changed. Reload before recording this payment.')
                        if request.form.get('remaining_checked') != 'yes':
                            raise ValueError('Count and confirm the cash remaining in the till.')
                        used, amount = read_counts(request.form, 'pitch_used')
                        remaining, remaining_total = read_counts(request.form, 'pitch_remaining')
                        if amount <= 0 and action != 'till_sheet':
                            raise ValueError('Enter the notes and coins used to pay the pitch fee.')
                        if amount > state['till']:
                            raise ValueError('The pitch fee exceeds the expected till cash. Check the cash history first.')
                        discrepancy_note = request.form.get('discrepancy_note', '').strip()
                        if len(discrepancy_note) > 1000 or (remaining_total != state['till'] - amount and not discrepancy_note):
                            raise ValueError('Explain any difference in the remaining till count (up to 1,000 characters).')
                    else:
                        amount = money(request.form.get('amount'))
                        if amount <= 0:
                            raise ValueError('Enter a positive pitch fee.')
                    movement = Movement(token=token, kind='cash_check' if source == 'till' and amount == 0 else 'pitch_fee', source=source, destination='other',
                        amount=amount, reason=reason, checked_by=checker, event_id=payment_event.id if payment_event else None)
                elif action == 'opening':
                    if state['till'] is not None:
                        raise ValueError('A cash starting point already exists. Record a transfer rather than replacing balances.')
                    movement = Movement(token=token, kind='opening', source='other', destination='other', amount=0,
                        opening_till=money(request.form.get('opening_till')), opening_safe=money(request.form.get('opening_safe')),
                        reason=reason, checked_by=checker)
                elif action == 'transfer':
                    source, destination = request.form.get('source'), request.form.get('destination')
                    amount = money(request.form.get('amount'))
                    if state['till'] is None or amount <= 0 or source not in LOCATIONS or destination not in LOCATIONS or source == destination:
                        raise ValueError('Choose different source/destination locations and enter a positive amount.')
                    if source not in ('till', 'safe') and destination not in ('till', 'safe'):
                        raise ValueError('A cash transfer must involve the till or safe.')
                    if source in ('till', 'safe') and amount > state[source]:
                        raise ValueError('The amount exceeds the expected cash available at the source. Check the cash history first.')
                    movement = Movement(token=token, kind='transfer', source=source, destination=destination,
                        amount=amount, reason=reason, checked_by=checker)
                else:
                    abort(400)
                db.session.add(movement)
                if action in ('pitch_fee', 'till_sheet') and source == 'till':
                    db.session.flush()
                    cash_version = position()['version']
                    db.session.add(TillCount(kind='fee_used', counts_json=json.dumps(used), total=amount,
                        expected_total=state['till'], cash_version=cash_version, checked_by=checker, note=reason))
                    db.session.add(TillCount(kind='count', counts_json=json.dumps(remaining), total=remaining_total,
                        expected_total=state['till'] - amount, cash_version=cash_version, checked_by=checker,
                        note=discrepancy_note or f'Till counted after cash record #{movement.id}'))
                db.session.commit()
                flash('Till cash sheet saved. Review the float transfer guidance below.' if action == 'till_sheet' else 'Pitch fee payment recorded.' if action == 'pitch_fee' else 'Cash record saved. Booking payments and sales income were not changed.', 'success')
                if action == 'till_sheet':
                    return redirect(url_for('admin_cash_movements', show_float=1, _anchor='till-float'))
                return redirect(url_for('admin_cash_movements'))
            except (ValueError, IntegrityError) as exc:
                db.session.rollback()
                flash(str(exc) if not isinstance(exc, IntegrityError) else 'This movement was already saved. Reload the journal.', 'error')
        state = position()
        token = session.setdefault('cash_movement_token', secrets.token_urlsafe(32))
        # Keep the last submission token for retry detection; replace it only on a subsequent GET.
        if request.method == 'GET' and Movement.query.filter_by(token=token).first():
            token = session['cash_movement_token'] = secrets.token_urlsafe(32)
        history = []
        fee_counts = {}
        for used in TillCount.query.filter_by(kind='fee_used').all():
            remaining = TillCount.query.filter_by(kind='count', cash_version=used.cash_version).order_by(TillCount.id).first()
            fee_counts[int(used.cash_version.rsplit(':', 1)[1])] = dict(used=used, remaining=remaining)
        for item in Movement.query.all():
            history.append(dict(at=item.recorded_at, kind=item.kind, movement=item, sheet=None))
        for sheet in latest_checks():
            history.append(dict(at=sheet.recorded_at, kind='event', movement=None, sheet=sheet))
        for count in TillCount.query.filter(TillCount.kind.in_(('target', 'count'))).all():
            history.append(dict(at=count.recorded_at, kind='denominations', movement=None, sheet=None, count=count))
        start, end = request.args.get('start', ''), request.args.get('end', '')
        try:
            zone = ZoneInfo('Europe/London')
            if start:
                first = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=zone).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                history = [item for item in history if item['at'] >= first]
            if end:
                last = (datetime.strptime(end, '%Y-%m-%d')+timedelta(days=1)).replace(tzinfo=zone).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                history = [item for item in history if item['at'] < last]
            if start and end and start > end:
                raise ValueError()
        except ValueError:
            abort(400, 'Choose a valid date range.')
        history.sort(key=lambda item: item['at'], reverse=True)
        page = max(1, request.args.get('page', 1, type=int))
        response = app.make_response(render_template('admin_cash_movements.html', state=state,
            history=history[(page-1)*25:page*25], has_next=len(history)>page*25, page=page,
            start=start, end=end, csrf=csrf, movement_token=token, locations=PAYMENT_LOCATIONS,
            transfer_locations=LOCATIONS, cash_fields=CLOSE_FIELDS,
            till_float=till_view(state), fee_counts=fee_counts, denominations=DENOMINATIONS,
            closed_event=closed_event, linked_event=linked_event,
            event_names={event.id: event.name for event in Event.query.all()},
            payment_events=[event for event in Event.query.order_by(Event.event_date.desc(), Event.id.desc()).all()
                if app.extensions['kiosk_public_event'](event)]))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
