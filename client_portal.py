"""Email-code authentication and client-scoped views of management records."""
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import hmac
import secrets
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from email_validator import validate_email, EmailNotValidError


def register_client_portal(app, db, Account, Code, Owner, Enquiry, Booking, settings, send_email,
                           schedule_events, admin_required):
    session_seconds = 8 * 3600
    remembered_seconds = 30 * 24 * 3600
    app.permanent_session_lifetime = timedelta(days=30)
    def client_session_seconds():
        return remembered_seconds if session.get('client_remember') is True else session_seconds
    portal = Blueprint('client', __name__, url_prefix='/client')
    def digest(value):
        return hmac.new(str(app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()
    def current_account():
        account_id = session.get('client_id')
        issued = session.get('client_signed_in', 0)
        if not account_id or datetime.now().timestamp() - issued >= client_session_seconds():
            session.pop('client_id', None)
            session.pop('client_signed_in', None)
            session.pop('client_remember', None)
            return None
        return db.session.get(Account, account_id)
    def client_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            account = current_account()
            if account is None:
                return redirect(url_for('client.login'))
            return view(account, *args, **kwargs)
        return wrapped
    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))
    def check_csrf():
        if not hmac.compare_digest(request.form.get('csrf_token', ''), csrf()):
            abort(400, 'Reload the page and try again.')
    def owned_bookings(account):
        return Booking.query.filter(func.lower(Booking.email) == account.email).order_by(Booking.submitted_at.desc())
    def owned_rewards(account):
        from rewards import fetch_one, row_to_dict
        records = []
        for owner in Owner.query.filter_by(client_id=account.id).all():
            row = fetch_one('SELECT * FROM referrals WHERE code=:code', {'code': owner.code})
            if row:
                record = row_to_dict(row)
                record['used'] = Booking.query.filter_by(promo_code=owner.code).first() is not None
                records.append(record)
        return records
    @portal.context_processor
    def context():
        return dict(client_account=current_account(), client_csrf=csrf())

    @app.context_processor
    def client_session_context():
        account = current_account() if not request.path.startswith('/admin') else None
        return dict(client_session_expires=(session.get('client_signed_in', 0) + client_session_seconds()) if account else None)

    @app.context_processor
    def reward_link_context():
        if request.endpoint != 'rewards.dashboard':
            return {}
        accounts = Account.query.order_by(Account.email).all()
        by_id = {account.id: account for account in accounts}
        return dict(reward_clients=accounts, reward_owners={owner.code: by_id.get(owner.client_id)
                    for owner in Owner.query.all()}, client_csrf=csrf())

    def issue_code(email, first, last, signup):
        now = datetime.now()
        ip = digest(request.remote_addr or 'unknown')
        recent = Code.query.filter(Code.email == email, Code.created_at > now-timedelta(seconds=60)).first()
        email_count = Code.query.filter(Code.email == email, Code.created_at > now-timedelta(minutes=15)).count()
        ip_count = Code.query.filter(Code.ip_hash == ip, Code.created_at > now-timedelta(hours=1)).count()
        if recent or email_count >= 3 or ip_count >= 20:
            raise ValueError('Please wait before requesting another code. Check your inbox and spam folder.')
        account = Account.query.filter_by(email=email).first()
        # Keep the same response for unknown sign-in addresses.
        raw_code = f'{secrets.randbelow(1000000):06d}'
        challenge_id = secrets.token_hex(24)
        Code.query.filter_by(email=email, consumed=False).update({'consumed': True})
        challenge = Code(id=challenge_id, email=email, first_name=first if signup else '',
            last_name=last if signup else '', mode='signup' if signup else 'login',
            code_hash=digest(challenge_id + ':' + raw_code), ip_hash=ip,
            created_at=now, expires_at=now+timedelta(minutes=10), consumed=not (signup or account))
        db.session.add(challenge)
        db.session.commit()
        session['client_challenge'] = challenge_id
        if signup or account:
            if not send_email(email, 'Your CL Paints verification code',
                f'Your verification code is {raw_code}.\n\nIt expires in 10 minutes and can only be used once.\nIf you did not request this, ignore this email.'):
                challenge.consumed = True
                db.session.commit()
                raise ValueError('We could not send your code. Please try again later or contact us.')

    @portal.route('/login', methods=['GET', 'POST'])
    @portal.route('/signup', methods=['GET', 'POST'], endpoint='signup')
    def login():
        signup = request.path.endswith('/signup')
        if current_account():
            return redirect(url_for('client.dashboard'))
        error = 'Your sign-in has expired. Enter your email to sign in again.' if request.args.get('expired') == '1' else None
        if request.method == 'POST':
            check_csrf()
            try:
                email = validate_email(request.form.get('email', '').strip(), check_deliverability=False).normalized.casefold()
                first = request.form.get('first_name', '').strip()
                last = request.form.get('last_name', '').strip()
                if signup and (not first or not last or len(first) > 100 or len(last) > 100):
                    raise ValueError('Enter your first name and surname (up to 100 characters each).')
                issue_code(email, first, last, signup)
                session['client_pending_remember'] = request.form.get('stay_signed_in') == 'yes'
                return redirect(url_for('client.verify'))
            except (EmailNotValidError, ValueError) as problem:
                error = str(problem)
            except SQLAlchemyError:
                db.session.rollback()
                error = 'We could not request a code. Please try again.'
        return render_template('client/login.html', signup=signup, error=error)

    @portal.route('/verify', methods=['GET', 'POST'])
    def verify():
        challenge = db.session.get(Code, session.get('client_challenge', ''))
        if challenge is None:
            return redirect(url_for('client.login'))
        error = None
        if request.method == 'POST':
            check_csrf()
            raw = request.form.get('code', '').strip()
            now = datetime.now()
            try:
                if challenge.consumed or challenge.expires_at <= now or challenge.attempts >= 5:
                    raise ValueError('This code has expired or is unavailable. Request a new code.')
                # Reserve one attempt atomically, even across simultaneous requests.
                changed = Code.query.filter(Code.id == challenge.id, Code.consumed.is_(False),
                    Code.expires_at > now, Code.attempts < 5).update({'attempts': Code.attempts + 1}, synchronize_session=False)
                if not changed:
                    raise ValueError('This code is unavailable. Request a new code.')
                if not hmac.compare_digest(challenge.code_hash, digest(challenge.id + ':' + raw)):
                    db.session.commit()
                    raise ValueError('The verification code is incorrect.')
                consumed = Code.query.filter(Code.id == challenge.id, Code.consumed.is_(False)).update({'consumed': True}, synchronize_session=False)
                if not consumed:
                    raise ValueError('This code has already been used.')
                account = Account.query.filter_by(email=challenge.email).first()
                if account is None:
                    if challenge.mode != 'signup':
                        raise ValueError('Create an account before signing in.')
                    account = Account(email=challenge.email, first_name=challenge.first_name, last_name=challenge.last_name)
                    db.session.add(account)
                    db.session.flush()
                db.session.commit()
                session.pop('client_challenge', None)
                session['client_id'] = account.id
                session['client_signed_in'] = now.timestamp()
                session['client_remember'] = session.pop('client_pending_remember', False) is True
                session.permanent = session['client_remember']
                session['client_csrf'] = secrets.token_urlsafe(32)
                flash('You’re signed in. Welcome to your colourful corner of CL Paints!', 'client_login_success')
                scan_token = session.pop('loyalty_scan_token', None)
                if scan_token:
                    return redirect(url_for('loyalty.scan', token=scan_token))
                return redirect(url_for('client.account' if not account.phone or not account.address else 'client.dashboard'))
            except ValueError as problem:
                db.session.rollback()
                error = str(problem)
            except SQLAlchemyError:
                db.session.rollback()
                error = 'We could not complete verification. Please request a new code.'
        return render_template('client/verify.html', error=error, signup=challenge.mode == 'signup',
            resend_seconds=resend_wait(challenge.email))

    def resend_wait(email):
        now = datetime.now()
        recent = Code.query.filter_by(email=email).order_by(Code.created_at.desc()).all()
        deadlines = [recent[0].created_at + timedelta(seconds=60)] if recent else []
        email_window = [code for code in recent if code.created_at > now - timedelta(minutes=15)]
        if len(email_window) >= 3:
            deadlines.append(email_window[2].created_at + timedelta(minutes=15))
        ip = digest(request.remote_addr or 'unknown')
        ip_window = Code.query.filter(Code.ip_hash == ip, Code.created_at > now - timedelta(hours=1)).order_by(Code.created_at.desc()).all()
        if len(ip_window) >= 20:
            deadlines.append(ip_window[19].created_at + timedelta(hours=1))
        import math
        return max(0, math.ceil((max(deadlines) - now).total_seconds())) if deadlines else 0

    @portal.post('/resend-code')
    def resend_code():
        check_csrf()
        if current_account():
            return redirect(url_for('client.dashboard'))
        challenge = db.session.get(Code, session.get('client_challenge', ''))
        if challenge is None:
            return redirect(url_for('client.login'))
        try:
            issue_code(challenge.email, challenge.first_name, challenge.last_name, challenge.mode == 'signup')
            flash('If your email is eligible, a new code has been sent. Use the latest email.', 'success')
        except ValueError as problem:
            flash(str(problem), 'error')
        except SQLAlchemyError:
            db.session.rollback()
            flash('We could not request a code. Please try again.', 'error')
        return redirect(url_for('client.verify'))

    @portal.post('/logout')
    def logout():
        check_csrf()
        for key in ['client_id', 'client_signed_in', 'client_challenge', 'client_csrf', 'client_remember', 'client_pending_remember']:
            session.pop(key, None)
        return redirect(url_for('client.login'))

    @portal.get('/')
    @client_required
    def dashboard(account):
        bookings = owned_bookings(account).all()
        upcoming = []
        today = datetime.now().date()
        for booking in bookings:
            if booking.status == 'Accepted':
                for event in schedule_events(booking):
                    try:
                        event_date = datetime.strptime(event.get('date', ''), '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        continue
                    if event_date >= today:
                        upcoming.append(dict(booking=booking, event=event, days_until=(event_date - today).days))
        upcoming.sort(key=lambda item: (item['event']['date'], item['event'].get('start_time', '')))
        return render_template('client/dashboard.html', bookings=bookings[:3], upcoming=upcoming[:3],
                               pending=sum(b.status == 'Under Review' for b in bookings), rewards=owned_rewards(account))

    @portal.get('/bookings')
    @client_required
    def bookings(account):
        return render_template('client/bookings.html', bookings=owned_bookings(account).all())

    @portal.get('/bookings/<int:booking_id>')
    @client_required
    def booking_detail(account, booking_id):
        booking = owned_bookings(account).filter(Booking.id == booking_id).first_or_404()
        return render_template('client/booking_detail.html', booking=booking, events=schedule_events(booking))

    @portal.get('/rewards')
    @client_required
    def rewards(account):
        return render_template('client/rewards.html', rewards=owned_rewards(account))

    @portal.route('/account', methods=['GET', 'POST'])
    @client_required
    def account(account):
        error = None
        if request.method == 'POST':
            check_csrf()
            ClientBillingAddress = app.extensions['client_billing_address_model']
            from client_addresses import read_address, format_address, profile_details
            values = {key: request.form.get(key, '').strip() for key in ['first_name', 'last_name', 'phone']}
            try:
                address_details = read_address(request.form)
                if 'client_type' in request.form:
                    address_details.update(profile_details(request.form, app.extensions['profile_ethnicities']))
            except ValueError as problem:
                error = str(problem)
            if not all(values.values()) or any(len(values[key]) > limit for key, limit in [('first_name', 100), ('last_name', 100), ('phone', 50)]):
                error = 'Complete your name, phone and address using the stated field limits.'
            if error is None:
                for key, value in values.items():
                    setattr(account, key, value)
                billing = db.session.get(ClientBillingAddress, account.id)
                if not billing:
                    billing = ClientBillingAddress(client_id=account.id)
                    db.session.add(billing)
                billing.details = address_details
                account.address = format_address(address_details)
                db.session.commit()
                flash('Your account details are saved.', 'success')
                return redirect(url_for('client.dashboard'))
        ClientBillingAddress = app.extensions['client_billing_address_model']
        billing = db.session.get(ClientBillingAddress, account.id)
        form_data = request.form if request.method == 'POST' else (billing.details if billing else {})
        return render_template('client/account.html', error=error, form_data=form_data, legacy_address=account.address if not billing else '')

    @portal.route('/contact', methods=['GET', 'POST'])
    @client_required
    def contact(account):
        error = None
        if request.method == 'POST':
            check_csrf()
            subject = request.form.get('subject', '').strip()
            message = request.form.get('message', '').strip()
            if not subject or len(subject) > 150 or not message or len(message) > 3000:
                error = 'Enter a subject (up to 150 characters) and a message (up to 3,000 characters).'
            elif Enquiry.query.filter(Enquiry.client_id == account.id, Enquiry.created_at > datetime.now()-timedelta(minutes=1)).first():
                error = 'Please wait a minute before sending another message.'
            else:
                enquiry = Enquiry(client_id=account.id, subject=subject, message=message)
                db.session.add(enquiry)
                db.session.commit()
                notification = (
                    f'New client enquiry #{enquiry.id}\n\n'
                    f'From: {account.first_name} {account.last_name}\n'
                    f'Email: {account.email}\nPhone: {account.phone or "Not provided"}\n'
                    f'Subject: {subject}\n\n{message}\n\n'
                    f'Review in the admin app: {url_for("admin_clients", _external=True)}#enquiry-{enquiry.id}\n'
                    f'Reply to the client at {account.email}.'
                )
                if not send_email(settings()['contact_email'], f'CL Paints: new enquiry #{enquiry.id}', notification):
                    app.logger.warning('Enquiry %s saved, but its email notification could not be sent.', enquiry.id)
                flash('Your message has been saved for CL Paints to review.', 'success')
                return redirect(url_for('client.contact'))
        return render_template('client/contact.html', error=error)

    @app.route('/admin/clients', methods=['GET', 'POST'])
    @admin_required
    def admin_clients():
        from rewards import fetch_one
        if request.method == 'POST':
            check_csrf()
            account = db.session.get(Account, request.form.get('client_id', type=int))
            code = request.form.get('code', '').strip()
            if account is None or not fetch_one('SELECT code FROM referrals WHERE code=:code', {'code': code}):
                flash('Choose an existing client and referral code.', 'error')
            else:
                owner = db.session.get(Owner, code)
                if owner and owner.client_id != account.id:
                    flash('This code is already linked to another client.', 'error')
                else:
                    if owner is None:
                        db.session.add(Owner(code=code, client_id=account.id))
                        try:
                            db.session.commit()
                        except IntegrityError:
                            db.session.rollback()
                            flash('This code was linked by another request. Refresh and check its owner.', 'error')
                            return redirect(url_for('rewards.dashboard' if request.form.get('return_to') == 'rewards' else 'admin_clients'))
                        app.extensions['client_reward_code_notice'](code, f'Referral code {code} has been linked to your verified account. Open Rewards to see its details.')
                    flash('Referral code linked to the verified client account.', 'success')
            return redirect(url_for('rewards.dashboard' if request.form.get('return_to') == 'rewards' else 'admin_clients'))
        clients = Account.query.order_by(Account.first_name, Account.last_name).all()
        return render_template('admin_clients.html', clients=clients, enquiries=Enquiry.query.order_by(Enquiry.created_at.desc()).limit(50).all(),
                               accounts={a.id: a for a in clients}, owners=Owner.query.all(), client_csrf=csrf())
    app.register_blueprint(portal)
    return current_account
