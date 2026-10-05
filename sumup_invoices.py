"""Booking links to invoices created in SumUp; no automatic payment synchronisation."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import secrets
from urllib.parse import urlsplit
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class BookingInvoice(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        reference = db.Column(db.String(100), nullable=False, unique=True)
        purpose = db.Column(db.String(20), nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        due_date = db.Column(db.Date, nullable=False)
        payment_url = db.Column(db.String(1000), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return BookingInvoice


def validate_link(value):
    value = value.strip()
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower()
    if (len(value) > 1000 or any(ord(c) < 33 for c in value)
            or parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not (host == 'sumup.com' or host.endswith('.sumup.com')
                    or host == 'sumup.me' or host.endswith('.sumup.me'))):
        raise ValueError('Use the secure customer invoice link from SumUp (sumup.com or sumup.me).')
    return value


def register(app, db, Invoice, Booking, admin_required, current_client, schedule):
    @app.context_processor
    def invoice_context():
        if request.endpoint not in ('admin_payments', 'client.booking_detail'):
            return {}
        booking_id = request.view_args.get('booking_id')
        booking = db.session.get(Booking, booking_id)
        if request.endpoint == 'client.booking_detail':
            account = current_client()
            if not account or not booking or booking.email.strip().casefold() != account.email:
                return {}
        return {'booking_invoices': Invoice.query.filter_by(booking_id=booking_id).order_by(Invoice.created_at.desc()).all()}

    @app.route('/admin/bookings/<int:booking_id>/invoices', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_invoices(booking_id):
        booking = db.get_or_404(Booking, booking_id)
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')):
                abort(400)
            try:
                reference = request.form.get('reference', '').strip()
                purpose = request.form.get('purpose', '')
                amount = Decimal(request.form.get('amount', ''))
                due = datetime.strptime(request.form.get('due_date', ''), '%Y-%m-%d').date()
                link = validate_link(request.form.get('payment_url', ''))
                if (not reference or len(reference) > 100 or any(ord(c) < 32 for c in reference)
                        or purpose not in ('Deposit', 'Balance', 'Full payment')
                        or not amount.is_finite() or not Decimal('0') < amount <= Decimal('999999.99')
                        or amount != amount.quantize(Decimal('.01'))):
                    raise ValueError('Enter an invoice number, purpose and positive amount with up to two decimal places.')
                existing = Invoice.query.filter_by(reference=reference).first()
                if existing:
                    raise ValueError('That invoice number is already attached. Each SumUp invoice can only be attached once.')
                db.session.add(Invoice(booking_id=booking.id, reference=reference, purpose=purpose,
                                      amount=amount, due_date=due, payment_url=link))
                db.session.commit()
                flash('SumUp invoice attached and available in the client booking. This does not record a payment or send an email.', 'success')
                return redirect(url_for('admin_payments', booking_id=booking.id))
            except (ValueError, InvalidOperation, IntegrityError):
                db.session.rollback()
                flash('Could not attach the invoice. Check the number is unique, the amount and date are valid, and the customer link is a secure SumUp URL.', 'error')
        return render_template('admin_booking_invoices.html', booking=booking, client_csrf=token)
