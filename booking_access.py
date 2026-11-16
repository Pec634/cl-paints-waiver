"""Revocable private links grant access to one booking, never an account."""
from datetime import datetime, timedelta
from io import BytesIO
import secrets
from flask import abort, g, redirect, render_template, request, session, url_for, send_file
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class BookingAccess(db.Model):
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), primary_key=True)
        nonce = db.Column(db.String(64), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)
    return BookingAccess


def register(app, db, Access, Booking, Account, admin_required, settings):
    signer = URLSafeSerializer(app.secret_key, salt='private-booking-access-v1')
    allowed = {'client.booking_detail', 'client_edit_booking', 'client_agree_booking',
               'client_booking_messages', 'client_booking_request', 'acknowledge', 'booking_response_pdf'}

    def owner(booking):
        return Account.query.filter(db.func.lower(db.func.trim(Account.email)) == booking.email.strip().lower()).first()

    def prepare_created_booking(booking):
        """Create sharing access in the same transaction as the admin booking."""
        if not owner(booking):
            try:
                with db.session.begin_nested():
                    db.session.add(Account(email=booking.email.strip().lower(), first_name=booking.first_name,
                                           last_name=booking.last_name, phone=booking.phone,
                                           address=booking.client_address))
                    db.session.flush()
            except IntegrityError:
                if not owner(booking):
                    raise
        if not db.session.get(Access, booking.id):
            now = datetime.utcnow()
            db.session.add(Access(booking_id=booking.id, nonce=secrets.token_urlsafe(32),
                                  created_at=now, expires_at=now + timedelta(days=90)))

    app.extensions['booking_created_share_link'] = prepare_created_booking

    def scoped_account():
        grant = session.get('booking_access')
        if not isinstance(grant, dict) or request.endpoint not in allowed:
            return None
        if (request.view_args or {}).get('booking_id') != grant.get('booking_id'):
            return None
        access = db.session.get(Access, grant['booking_id'])
        booking = db.session.get(Booking, grant['booking_id'])
        if (not access or not booking or access.expires_at <= datetime.utcnow() or
                not secrets.compare_digest(access.nonce, str(grant.get('nonce', ''))) or
                booking.email.strip().lower() != grant.get('email')):
            session.pop('booking_access', None)
            abort(403, 'This private booking link has expired or been replaced. Please ask CL Paints for a new link.')
        account = owner(booking)
        if not account:
            abort(403)
        g.private_booking = booking
        return account

    app.extensions['booking_link_account'] = scoped_account

    def private_url(booking, access):
        token = signer.dumps(dict(booking_id=booking.id, nonce=access.nonce, email=booking.email.strip().lower()))
        root = settings().get('public_app_url', '').rstrip('/') or request.url_root.rstrip('/')
        return root + url_for('open_private_booking', token=token)

    @app.get('/booking/access/<token>')
    def open_private_booking(token):
        try:
            payload = signer.loads(token)
        except BadSignature:
            abort(404)
        if not isinstance(payload, dict) or type(payload.get('booking_id')) is not int:
            abort(404)
        access = db.session.get(Access, payload['booking_id'])
        booking = db.session.get(Booking, payload['booking_id'])
        if (not access or not booking or access.expires_at <= datetime.utcnow() or
                not secrets.compare_digest(access.nonce, str(payload.get('nonce', ''))) or
                payload.get('email') != booking.email.strip().lower() or not owner(booking)):
            abort(404)
        session['booking_access'] = payload
        session.setdefault('client_csrf', secrets.token_urlsafe(32))
        return redirect(url_for('client.booking_detail', booking_id=booking.id))

    @app.route('/admin/bookings/<int:booking_id>/share', methods=['GET', 'POST'])
    @admin_required
    def admin_share_booking(booking_id):
        booking = db.get_or_404(Booking, booking_id)
        account = owner(booking)
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        access = db.session.get(Access, booking.id)
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
            action = request.form.get('action')
            if action not in ('generate', 'revoke'):
                abort(400)
            if action == 'generate' and not account:
                abort(400, 'Link this booking to a client account first.')
            now = datetime.utcnow()
            if action == 'generate':
                if access is None:
                    access = Access(booking_id=booking.id)
                    db.session.add(access)
                access.nonce = secrets.token_urlsafe(32)
                access.created_at = now
                access.expires_at = now + timedelta(days=90)
            elif access:
                access.nonce = secrets.token_urlsafe(32)
                access.expires_at = now
            db.session.commit()
            return redirect(url_for('admin_share_booking', booking_id=booking.id))
        active = bool(account and access and access.expires_at > datetime.utcnow())
        return render_template('admin_share_booking.html', booking=booking, account=account,
                               access=access, share_url=private_url(booking, access) if active else '',
                               client_csrf=csrf)

    @app.get('/admin/bookings/<int:booking_id>/share/qr.png')
    @admin_required
    def admin_share_booking_qr(booking_id):
        import qrcode
        booking = db.get_or_404(Booking, booking_id)
        access = db.session.get(Access, booking.id)
        if not access or access.expires_at <= datetime.utcnow() or not owner(booking):
            abort(404)
        output = BytesIO()
        qrcode.make(private_url(booking, access)).save(output, format='PNG')
        output.seek(0)
        return send_file(output, mimetype='image/png', download_name=f'{booking.public_reference}-booking-qr.png')

    @app.context_processor
    def private_context():
        booking = getattr(g, 'private_booking', None)
        return dict(private_booking_access=bool(booking), private_booking_id=booking.id if booking else None)

    @app.after_request
    def private_headers(response):
        if request.endpoint in ('open_private_booking', 'admin_share_booking', 'admin_share_booking_qr') or getattr(g, 'private_booking', None):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response
