"""Public-event loyalty and audited responsibility transfers."""
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from functools import wraps
from io import BytesIO
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, send_file
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError


def define_models(db):
    class LoyaltyEventCode(db.Model):
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), primary_key=True)
        token = db.Column(db.String(64), unique=True, nullable=False)

    class LoyaltyBalance(db.Model):
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), primary_key=True)
        points = db.Column(db.Integer, nullable=False, default=0)

    class LoyaltyVisit(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        status = db.Column(db.String(20), nullable=False, default='point')
        scanned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        confirmed_at = db.Column(db.DateTime)
        moodboard_id = db.Column(db.Integer, db.ForeignKey('moodboard_image.id'))
        __table_args__ = (db.UniqueConstraint('participant_id', 'event_id', name='uq_loyalty_person_event'),)

    class MemberCustodian(db.Model):
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        waiver_id = db.Column(db.Integer, db.ForeignKey('waiver.id'), nullable=False)

    class MemberTransfer(db.Model):
        id = db.Column(db.String(64), primary_key=True)
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
        from_client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        to_client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        target_waiver_id = db.Column(db.Integer, db.ForeignKey('waiver.id'))
        code_hash = db.Column(db.String(64), nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        attempts = db.Column(db.Integer, nullable=False, default=0)
        completed_at = db.Column(db.DateTime)
    return LoyaltyEventCode, LoyaltyBalance, LoyaltyVisit, MemberCustodian, MemberTransfer


def register_loyalty(app, db, models, Account, Waiver, Participant, Event, Booking,
                     EventImage, Image, current_client, admin_required, send_email, schedule):
    EventCode, Balance, Visit, Custodian, Transfer = models
    bp = Blueprint('loyalty', __name__)
    def now():
        return datetime.utcnow()
    def today():
        # UK event dates, including daylight saving time.
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Europe/London')).date()
    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))
    def check():
        if not hmac.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400)
    def client_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            account = current_client()
            if not account:
                if request.method == 'GET' and request.endpoint == 'loyalty.scan':
                    session['loyalty_scan_token'] = kwargs['token']
                return redirect(url_for('client.login'))
            return view(account, *args, **kwargs)
        return wrapped
    def valid_waiver(waiver):
        return waiver and not waiver.is_archived and waiver.status != 'Superseded' and waiver.expiry_date.date() >= today()
    def owns_waiver(account, waiver):
        return waiver and waiver.responsible_email.strip().casefold() == account.email.casefold()
    def owns_member(account, person):
        owner = db.session.get(Custodian, person.id)
        return owner.client_id == account.id if owner else owns_waiver(account, person.waiver)
    def current_waiver(person):
        owner = db.session.get(Custodian, person.id)
        return db.session.get(Waiver, owner.waiver_id) if owner else person.waiver
    def members(account):
        original = Participant.query.join(Waiver).filter(func.lower(func.trim(Waiver.responsible_email)) == account.email).all()
        transferred = Participant.query.join(Custodian, Custodian.participant_id == Participant.id).filter(Custodian.client_id == account.id).all()
        return [p for p in {p.id: p for p in original + transferred}.values() if owns_member(account, p)]
    def public_event(event):
        if not event:
            return False
        if not event.booking_id:
            return True  # Events created directly are public-event records.
        booking = db.session.get(Booking, event.booking_id)
        days = schedule(booking) if booking else []
        index = (event.booking_day_number or 1) - 1
        return booking and booking.status == 'Accepted' and 0 <= index < len(days) and days[index].get('publicity_type') == 'Public'
    def open_event(event):
        return public_event(event) and event.status in ['Open', 'Closing Soon'] and event.event_date == today()
    app.extensions['kiosk_public_event'] = public_event

    @bp.get('/admin/check-in')
    @admin_required
    def check_in():
        from record_ids import reference_record_id
        events = [event for event in Event.query.order_by(Event.event_date.desc()).all() if public_event(event)]
        event_id = request.args.get('event_id', type=int)
        event = db.session.get(Event, event_id) if event_id else None
        if event_id and not public_event(event): abort(404)
        query = request.args.get('q', '').strip()
        if len(query) > 100: abort(400)
        people = []
        if query:
            member_id = reference_record_id(query.upper(), 'L')
            waiver_id = reference_record_id(query.upper(), 'W')
            if member_id:
                person = db.session.get(Participant, member_id)
                if person and person.loyalty_reference == query.upper(): people = [person]
            else:
                waiver = db.session.get(Waiver, waiver_id) if waiver_id else Waiver.query.filter_by(waiver_reference=query).first()
                if waiver and (not waiver_id or waiver.public_reference == query.upper()):
                    originals = Participant.query.filter_by(waiver_id=waiver.id).all()
                    transferred = Participant.query.join(Custodian, Custodian.participant_id == Participant.id).filter(Custodian.waiver_id == waiver.id).all()
                    people = [person for person in {p.id:p for p in originals+transferred}.values() if current_waiver(person).id == waiver.id]
        rows = []
        for person in people:
            waiver = current_waiver(person)
            balance = db.session.get(Balance, person.id)
            visit = Visit.query.filter_by(participant_id=person.id, event_id=event.id).first() if event else None
            correction = db.session.get(app.extensions['loyalty_correction_model'], visit.id) if visit else None
            rows.append(dict(person=person, waiver=waiver, valid=valid_waiver(waiver), points=balance.points if balance else 0,
                visit=visit, corrected=bool(correction)))
        return render_template('admin_check_in.html', events=events, event=event, query=query, rows=rows,
            event_open=open_event(event) if event else False)
    def digest(value):
        return hmac.new(str(app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()
    @app.context_processor
    def loyalty_context():
        if request.endpoint in ['client.rewards', 'client.account'] or (request.endpoint and request.endpoint.startswith('loyalty.') and request.path.startswith('/client/')):
            account = current_client()
            people = members(account) if account else []
            return dict(client_account=account, loyalty_members=people, loyalty_balances={p.id: (db.session.get(Balance, p.id).points if db.session.get(Balance, p.id) else 0) for p in people}, client_csrf=csrf())
        return {}

    @bp.get('/client/waivers')
    @client_required
    def waivers(account):
        records = Waiver.query.filter(func.lower(func.trim(Waiver.responsible_email)) == account.email).order_by(Waiver.signed_date.desc()).all()
        return render_template('client/waivers.html', waivers=records, transfers=Transfer.query.filter_by(to_client_id=account.id, completed_at=None).filter(Transfer.expires_at > now()).all())

    @bp.get('/client/waivers/new')
    @client_required
    def new_waiver(account):
        return render_template('waiver.html', current_event=None, account_waiver=True,
            responsible_account=account, client_csrf=csrf(), moodboard_images=[],
            large_moodboard_images=[], small_moodboard_images=[])

    @bp.get('/client/waivers/<int:waiver_id>')
    @client_required
    def waiver_detail(account, waiver_id):
        waiver = db.session.get(Waiver, waiver_id)
        if not owns_waiver(account, waiver):
            abort(404)
        return render_template('client/waiver_detail.html', waiver=waiver)

    @bp.route('/client/loyalty/scan/<token>', methods=['GET', 'POST'])
    @client_required
    def scan(account, token):
        record = EventCode.query.filter_by(token=token).first()
        event = db.session.get(Event, record.event_id) if record else None
        if not open_event(event):
            abort(410, 'This loyalty code is unavailable. Scan the code at an open public event on its event date.')
        people = [p for p in members(account) if valid_waiver(current_waiver(p))]
        if request.method == 'POST':
            check()
            ids = set(request.form.getlist('member_id', type=int))
            allowed = {p.id for p in people}
            if not ids or not ids <= allowed:
                abort(400)
            newly_claimed = []
            with db.session.no_autoflush:
                for person_id in ids:
                    if not Visit.query.filter_by(participant_id=person_id, event_id=event.id).first():
                        balance = db.session.get(Balance, person_id)
                        points = balance.points if balance else 0
                        design = request.form.get(f'design_{person_id}', type=int)
                        if points == 3 and not EventImage.query.filter_by(event_id=event.id, image_id=design).first():
                            db.session.rollback()
                            flash('Choose an event moodboard design for each member claiming their free paint.', 'error')
                            return redirect(url_for('loyalty.scan', token=token))
                        if balance is None:
                            db.session.add(Balance(participant_id=person_id, points=1))
                        else:
                            updated = Balance.query.filter_by(participant_id=person_id, points=points).update({'points': 0 if points == 3 else points + 1}, synchronize_session=False)
                            if not updated:
                                db.session.rollback()
                                abort(409)
                        db.session.add(Visit(participant_id=person_id, event_id=event.id, client_id=account.id,
                            status='free' if points == 3 else 'point', confirmed_at=now(), moodboard_id=design if points == 3 else None))
                        newly_claimed.append(person_id)
            try:
                db.session.commit()
                for visit in Visit.query.filter(Visit.participant_id.in_(newly_claimed), Visit.event_id == event.id).all():
                    person = db.session.get(Participant, visit.participant_id)
                    details = (f'{person.first_name} {person.last_name}: free face paint claimed at {event.name}. Points reset for the next cycle.' if visit.status == 'free' else f'{person.first_name} {person.last_name}: one loyalty point earned at {event.name}. Current balance: {db.session.get(Balance, person.id).points}/3.')
                    app.extensions['client_reward_notice'](account.email, account.first_name, person.loyalty_reference, details)
                flash('Selected members checked in: points awarded or free paints claimed. Show your confirmation to CL Paints.', 'success')
            except IntegrityError:
                db.session.rollback()
                flash('A member has already checked in. Refresh and check their status.', 'error')
            return redirect(url_for('loyalty.scan', token=token))
        visits = {v.participant_id: v for v in Visit.query.filter_by(event_id=event.id).filter(Visit.participant_id.in_([p.id for p in people])).all()}
        images = Image.query.join(EventImage, EventImage.image_id == Image.id).filter(EventImage.event_id == event.id).all()
        return render_template('client/loyalty_scan.html', event=event, people=people, visits=visits, images=images)

    @bp.route('/admin/events/<int:event_id>/loyalty', methods=['GET', 'POST'])
    @admin_required
    def event_admin(event_id):
        event = db.session.get(Event, event_id)
        if not public_event(event):
            abort(404)
        record = db.session.get(EventCode, event_id)
        if request.method == 'POST':
            check()
            if request.form.get('action') == 'generate':
                if not record:
                    db.session.add(EventCode(event_id=event_id, token=secrets.token_urlsafe(32)))
                    try:
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                return redirect(url_for('loyalty.event_admin', event_id=event_id))
            abort(400)
        visits = db.session.query(Visit, Participant, Balance).join(Participant, Participant.id == Visit.participant_id).join(Balance, Balance.participant_id == Visit.participant_id).filter(Visit.event_id == event_id).order_by(Visit.scanned_at.desc()).all()
        images = Image.query.join(EventImage, EventImage.image_id == Image.id).filter(EventImage.event_id == event_id).all()
        return render_template('admin_loyalty_event.html', event=event, record=record, visits=visits, images=images, client_csrf=csrf(), scan_open=open_event(event))

    @bp.get('/admin/events/<int:event_id>/loyalty/qr')
    @admin_required
    def qr(event_id):
        import qrcode
        import qrcode.image.svg
        record = db.session.get(EventCode, event_id)
        if not record or not public_event(db.session.get(Event, event_id)):
            abort(404)
        output = BytesIO()
        qrcode.make(url_for('loyalty.scan', token=record.token, _external=True), image_factory=qrcode.image.svg.SvgPathImage).save(output)
        output.seek(0)
        return send_file(output, mimetype='image/svg+xml')

    @bp.post('/client/members/<int:participant_id>/transfer')
    @client_required
    def transfer_request(account, participant_id):
        check()
        person = db.session.get(Participant, participant_id)
        if not person or not owns_member(account, person):
            abort(404)
        email = request.form.get('email', '').strip().casefold()
        recipient = Account.query.filter_by(email=email).first()
        if not recipient or recipient.id == account.id:
            flash('Choose another responsible person who has a verified client account.', 'error')
            return redirect(url_for('loyalty.waivers'))
        recent = Transfer.query.filter_by(participant_id=person.id).filter(Transfer.created_at > now() - timedelta(minutes=1)).first()
        if recent:
            abort(429)
        token = secrets.token_urlsafe(32)
        code = f'{secrets.randbelow(1000000):06d}'
        transfer = Transfer(id=token, participant_id=person.id, from_client_id=account.id, to_client_id=recipient.id, code_hash=digest(token + ':' + code), expires_at=now() + timedelta(minutes=10))
        db.session.add(transfer)
        db.session.commit()
        body = f'{account.first_name} has requested to transfer responsibility for {person.first_name} {person.last_name} to you.\nVerification code: {code}\nExpires in 10 minutes. Sign in and accept using your own valid waiver reference:\n{url_for("loyalty.transfer_accept", token=token, _external=True)}\nIgnore this message if you do not agree to the transfer.'
        if send_email(recipient.email, 'CL Paints: member transfer approval', body):
            flash('Approval code sent to the new responsible person. The member stays with you until they accept.', 'success')
        else:
            transfer.expires_at = now()
            db.session.commit()
            flash('Email could not be sent. No responsibility has changed.', 'error')
        return redirect(url_for('loyalty.waivers'))

    @bp.route('/client/member-transfers/<token>', methods=['GET', 'POST'])
    @client_required
    def transfer_accept(account, token):
        transfer = db.session.get(Transfer, token)
        if not transfer or transfer.to_client_id != account.id:
            abort(404)
        person = db.session.get(Participant, transfer.participant_id)
        source = db.session.get(Account, transfer.from_client_id)
        if transfer.completed_at or transfer.expires_at <= now() or transfer.attempts >= 5 or not owns_member(source, person):
            abort(410)
        error = None
        if request.method == 'POST':
            check()
            attempted = Transfer.query.filter_by(id=token, completed_at=None).filter(Transfer.attempts < 5, Transfer.expires_at > now()).update({'attempts': Transfer.attempts + 1}, synchronize_session=False)
            if not attempted:
                abort(410)
            waiver = Waiver.query.filter_by(waiver_reference=request.form.get('waiver_reference', '').strip()).first()
            if waiver is None:
                from record_ids import reference_record_id
                reference = request.form.get('waiver_reference', '').strip()
                waiver_id = reference_record_id(reference, 'W')
                candidate = db.session.get(Waiver, waiver_id) if waiver_id else None
                if candidate and candidate.public_reference == reference:
                    waiver = candidate
            if not hmac.compare_digest(transfer.code_hash, digest(token + ':' + request.form.get('code', ''))) or not owns_waiver(account, waiver) or not valid_waiver(waiver) or request.form.get('authority') != 'yes':
                db.session.commit()
                error = 'Check your code, valid waiver reference and responsibility confirmation.'
            else:
                owner = db.session.get(Custodian, person.id)
                if owner:
                    changed = Custodian.query.filter_by(participant_id=person.id, client_id=source.id).update({'client_id': account.id, 'waiver_id': waiver.id}, synchronize_session=False)
                    if not changed:
                        db.session.rollback()
                        abort(409)
                else:
                    db.session.add(Custodian(participant_id=person.id, client_id=account.id, waiver_id=waiver.id))
                transfer.completed_at = now()
                transfer.target_waiver_id = waiver.id
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    abort(409)
                flash('Transfer complete. The member’s ID, loyalty points and original signed waiver are preserved.', 'success')
                return redirect(url_for('loyalty.waivers'))
        return render_template('client/member_transfer.html', person=person, error=error, client_csrf=csrf())
    app.register_blueprint(bp)
