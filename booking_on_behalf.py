"""Client review and genuine consent for bookings entered by CL Paints."""
import hashlib
import json
import secrets
from datetime import datetime
from flask import abort, flash, redirect, request, session, url_for
from booking_edit import version
from client_notifications import booking_snapshot


def pending_agreement(booking):
    try:
        data = json.loads(booking.event_schedule or '{}')
        return bool(isinstance(data, dict) and isinstance(data.get('on_behalf'), dict) and data['on_behalf'].get('pending'))
    except (ValueError, TypeError):
        return False


def register(app, db, Booking, current_client, schedule, settings):
    def terms_hash():
        return hashlib.sha256(terms_text().encode()).hexdigest()

    def terms_text():
        return app.jinja_env.get_template('_booking_legal_text.html').render(business_settings=settings())

    @app.context_processor
    def agreement_context():
        data = dict(booking_pending_agreement=pending_agreement)
        if request.endpoint == 'client.booking_detail':
            booking = db.session.get(Booking, request.view_args['booking_id'])
            if booking and pending_agreement(booking):
                data.update(agreement_version=version(booking), agreement_terms_hash=terms_hash())
        return data

    @app.post('/client/bookings/<int:booking_id>/agree')
    def client_agree_booking(booking_id):
        account = current_client()
        if not account:
            abort(401)
        booking = Booking.query.filter(Booking.id == booking_id, db.func.lower(Booking.email) == account.email.lower()).with_for_update().first_or_404()
        token = session.get('client_csrf')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        if not pending_agreement(booking):
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        if request.form.get('booking_version') != version(booking) or request.form.get('terms_hash') != terms_hash():
            flash('The booking or its terms changed while you were reviewing. Review the latest details before signing.', 'error')
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        signature = request.form.get('signature', '').strip()
        if not signature or len(signature) > 200 or any(request.form.get(field) != 'yes' for field in ('terms_accepted', 'liability_acknowledged', 'is_over_18')):
            flash('Enter your full name and confirm your age, liability statement and booking terms.', 'error')
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        if booking.status != 'Under Review':
            abort(409)
        before = booking_snapshot(booking, schedule)
        data = json.loads(booking.event_schedule)
        data['on_behalf'].update(pending=False, signed_at=datetime.utcnow().isoformat(), signed_by=account.email,
            terms_hash=terms_hash(), terms_snapshot=terms_text())
        booking.event_schedule = json.dumps(data)
        booking.signature = signature
        booking.liability_acknowledged = True
        booking.is_over_18 = True
        booking.terms_accepted_at = datetime.utcnow()
        booking.terms_version = '2026-10-01'
        app.extensions['client_booking_updated'](booking, before, schedule)
        db.session.commit()
        flash('Your signature and agreement have been saved. CL Paints will review and confirm your booking separately.', 'success')
        return redirect(url_for('client.booking_detail', booking_id=booking.id))
