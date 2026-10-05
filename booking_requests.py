"""Client booking changes and cancellations require an explicit admin decision."""
from datetime import datetime
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class BookingRequest(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        enquiry_id = db.Column(db.Integer, db.ForeignKey('client_enquiry.id'), nullable=False)
        kind = db.Column(db.String(20), nullable=False)
        details = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(20), nullable=False, default='Pending')
        pending_key = db.Column(db.String(60), unique=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        reviewed_at = db.Column(db.DateTime)
        response = db.Column(db.Text, nullable=False, default='')
    return BookingRequest


def register(app, db, Request, Booking, Enquiry, current_client, admin_required, settings, send_email, schedule):
    def check():
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)

    @app.context_processor
    def context():
        if request.endpoint == 'admin_bookings' and session.get('admin_authenticated'):
            return dict(booking_requests=Request.query.filter_by(status='Pending').order_by(Request.created_at).all())
        if request.endpoint == 'client.booking_detail':
            account = current_client()
            booking = db.session.get(Booking, request.view_args['booking_id'])
            if account and booking and booking.email.strip().casefold() == account.email:
                return dict(booking_requests=Request.query.filter_by(booking_id=booking.id).order_by(Request.created_at.desc()).all())
        return {}

    @app.post('/client/bookings/<int:booking_id>/request')
    def client_booking_request(booking_id):
        account = current_client()
        if not account: return redirect(url_for('client.login'))
        booking = db.get_or_404(Booking, booking_id)
        if booking.email.strip().casefold() != account.email: abort(404)
        check()
        kind = request.form.get('kind', '')
        details = request.form.get('details', '').strip()
        if booking.status not in ('Accepted', 'Under Review') or kind not in ('change', 'cancellation') or not details or len(details) > 2500:
            flash('Choose an active booking and describe your request (up to 2,500 characters).', 'error')
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        key = f'{booking.id}:{kind}'
        if Request.query.filter_by(pending_key=key).first():
            flash('You already have this type of request awaiting review.', 'error')
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        enquiry = Enquiry(client_id=account.id, subject=f'Booking {kind} request · {booking.public_reference}', message=details)
        db.session.add(enquiry)
        db.session.flush()
        item = Request(booking_id=booking.id, enquiry_id=enquiry.id, kind=kind, details=details, pending_key=key)
        db.session.add(item)
        try: db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('This request is already awaiting review.', 'error')
            return redirect(url_for('client.booking_detail', booking_id=booking.id))
        send_email(settings()['contact_email'], f'CL Paints: booking {kind} request',
            f'{account.first_name} {account.last_name} ({account.email})\nBooking: {booking.public_reference}\n\n{details}\n\nReview: {url_for("admin_booking_request", request_id=item.id, _external=True)}')
        flash('Your request is saved for CL Paints to review. Your booking remains unchanged until a decision is made.', 'success')
        return redirect(url_for('client.booking_detail', booking_id=booking.id))

    @app.route('/admin/booking-requests/<int:request_id>', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_request(request_id):
        item = Request.query.filter_by(id=request_id).with_for_update().first_or_404()
        booking = db.get_or_404(Booking, item.booking_id)
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            check()
            action = request.form.get('action')
            response = request.form.get('response', '').strip()
            if item.status != 'Pending' or action not in ('complete', 'decline') or not response or len(response) > 2500:
                flash('Enter your decision and response for a pending request.', 'error')
            elif action == 'complete' and item.kind == 'cancellation' and booking.status not in ('Accepted', 'Under Review'):
                flash('This booking is no longer active. Decline or explain the request instead.', 'error')
            else:
                from client_notifications import booking_snapshot
                before = booking_snapshot(booking, schedule)
                if action == 'complete' and item.kind == 'cancellation': booking.status = 'Cancelled'
                item.status = 'Completed' if action == 'complete' else 'Declined'
                item.response = response
                item.reviewed_at = datetime.utcnow()
                item.pending_key = None
                db.session.commit()
                app.extensions['client_booking_updated'](booking, before, schedule)
                send_email(booking.email, f'CL Paints: your booking {item.kind} request',
                    f'Booking: {booking.public_reference}\nRequest: {item.status}\n\n{response}\n\nView your booking: {url_for("client.booking_detail", booking_id=booking.id, _external=True)}')
                flash('Decision saved. A client notification email was attempted; refunds must be processed and recorded separately.', 'success')
                return redirect(url_for('admin_booking_request', request_id=item.id))
        return render_template('admin_booking_request.html', item=item, booking=booking, client_csrf=token)
