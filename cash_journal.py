"""Append-only, non-event physical cash transfers and combined cash-sheet history."""
from datetime import datetime, timedelta
from decimal import Decimal
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from booking_cashup import CLOSE_FIELDS, money

LOCATIONS = {'till': 'Till', 'safe': 'Safe', 'bank': 'Bank', 'other': 'Other cash source / use'}


def define_model(db):
    class CashMovement(db.Model):
        id = db.Column(db.Integer, primary_key=True)
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


def register(app, db, Movement, Cashup, Setting, admin_required):
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
        moves = Movement.query.filter_by(kind='transfer')
        if at is not None:
            moves = moves.filter(Movement.recorded_at > at)
        applied = []
        for movement in moves.order_by(Movement.id).all():
            if till is None:
                raise ValueError('Record initial cash counts before adding transfers.')
            till += movement.amount * ((movement.destination == 'till') - (movement.source == 'till'))
            safe += movement.amount * ((movement.destination == 'safe') - (movement.source == 'safe'))
            applied.append(movement.id)
        last = Movement.query.order_by(Movement.id.desc()).first()
        version = f'{row.id if row else 0}:{last.id if last else 0}'
        return dict(till=till, safe=safe, version=version, movement_ids=applied, baseline=row,
                    has_movements=last is not None,
                    active=any(item.phase != 'Closed' for item in checks))

    app.extensions['cash_journal_position'] = position
    app.extensions['cash_journal_lock'] = lock

    @app.route('/admin/cash-movements', methods=['GET', 'POST'])
    @admin_required
    def admin_cash_movements():
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
                if state['active']:
                    raise ValueError('An event cash sheet is open or in draft. Record this movement on that sheet, or close it before making a non-event transfer.')
                reason, checker = request.form.get('reason', '').strip(), request.form.get('checked_by', '').strip()
                if not reason or len(reason) > 1000 or not checker or len(checker) > 255:
                    raise ValueError('Enter a reason (up to 1,000 characters) and the person recording/checking the cash (up to 255).')
                action = request.form.get('action')
                if action == 'opening':
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
                db.session.commit()
                flash('Cash record saved. Booking payments and sales income were not changed.', 'success')
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
        for item in Movement.query.all():
            history.append(dict(at=item.recorded_at, kind=item.kind, movement=item, sheet=None))
        for sheet in latest_checks():
            history.append(dict(at=sheet.recorded_at, kind='event', movement=None, sheet=sheet))
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
            start=start, end=end, csrf=csrf, movement_token=token, locations=LOCATIONS, cash_fields=CLOSE_FIELDS))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
