"""Event design baskets with server-priced, provider-verified SumUp payments."""
import os
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit
from flask import abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sumup_checkout import provider_request
from sumup_invoices import validate_link


def define_model(db):
    class MoodboardOrder(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
        token = db.Column(db.String(64), unique=True, nullable=False)
        items = db.Column(db.JSON, nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        merchant = db.Column(db.String(100), nullable=False)
        provider_id = db.Column(db.String(100), unique=True)
        payment_url = db.Column(db.String(1000))
        paid = db.Column(db.Boolean, nullable=False, default=False)
        fulfilment = db.Column(db.String(20), nullable=False, default='Waiting')
        fulfilment_updated_at = db.Column(db.DateTime)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return MoodboardOrder


def ensure_schema(db):
    from sqlalchemy import inspect, text
    columns = {column['name'] for column in inspect(db.engine).get_columns('moodboard_order')}
    with db.engine.begin() as connection:
        if 'fulfilment' not in columns:
            connection.execute(text("ALTER TABLE moodboard_order ADD COLUMN fulfilment VARCHAR(20) NOT NULL DEFAULT 'Waiting'"))
        if 'fulfilment_updated_at' not in columns:
            connection.execute(text('ALTER TABLE moodboard_order ADD COLUMN fulfilment_updated_at TIMESTAMP'))


def register(app, db, Order, Event, Assignment, prices, settings, admin_required, Setting):
    signer = URLSafeTimedSerializer(app.secret_key, salt='moodboard-basket-review-v1')

    def paused(event):
        row = db.session.get(Setting, 'moodboard_paused_' + str(event.id))
        return bool(row and row.value == '1')

    def available(event):
        return False  # New SumUp checkouts now belong to CL Creates headband orders.

    def ready():
        base = settings()['public_app_url'].rstrip('/')
        parsed = urlsplit(base)
        return bool(os.getenv('SUMUP_API_KEY') and os.getenv('SUMUP_MERCHANT_CODE') and
                    parsed.scheme == 'https' and parsed.hostname and not parsed.username and
                    not parsed.password and not parsed.query and not parsed.fragment)

    @app.context_processor
    def context():
        return {'moodboard_payments_ready': ready, 'moodboard_payments_available': available,
                'moodboard_payments_paused': paused}

    def reference(order):
        return 'MB-' + order.token

    def verify(order):
        if order.paid:
            return 'PAID'
        if not order.provider_id:
            results = provider_request('checkouts?checkout_reference=' + quote(reference(order), safe=''))
            if not isinstance(results, list) or len(results) != 1:
                raise ValueError('Payment creation is still being checked. Please refresh before attempting another payment.')
            data = results[0]
        else:
            data = provider_request('checkouts/' + quote(order.provider_id, safe=''))
        try:
            matches = (isinstance(data, dict) and data.get('checkout_reference') == reference(order)
                       and data.get('merchant_code') == order.merchant and data.get('currency') == 'GBP'
                       and Decimal(str(data.get('amount'))) == order.amount)
            identity = data.get('id', '')
            if not matches or not identity or len(identity) > 100 or any(c not in '0123456789abcdefABCDEF-' for c in identity):
                raise ValueError('Payment details could not be verified.')
            if order.provider_id and identity != order.provider_id:
                raise ValueError('Payment details could not be verified.')
        except (InvalidOperation, TypeError, AttributeError):
            raise ValueError('Payment details could not be verified.')
        order.provider_id = identity
        if data.get('hosted_checkout_url'):
            order.payment_url = validate_link(data['hosted_checkout_url'])
        if data.get('status') == 'PAID':
            order.paid = True
        db.session.commit()
        return data.get('status', 'PENDING')

    @app.post('/moodboard/event/<int:event_id>/pay')
    def moodboard_pay(event_id):
        return 'Moodboard online payments have been removed. Please ask CL Paints about payment at the event.', 410

    @app.get('/moodboard/payment/<token>')
    def moodboard_payment(token):
        order = Order.query.filter_by(token=token).first_or_404()
        event = db.get_or_404(Event, order.event_id)
        error = None
        try:
            status = verify(order)
        except ValueError as exc:
            db.session.rollback()
            status, error = 'UNKNOWN', str(exc)
        response = app.make_response(render_template('moodboard_payment.html', order=order, event=event, status=status,
            error=error, can_pay=available(event) and status == 'PENDING' and not error))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.post('/moodboard/payment/<token>/callback')
    def moodboard_payment_callback(token):
        order = Order.query.filter_by(token=token).first_or_404()
        try:
            return jsonify(status=verify(order))
        except ValueError:
            db.session.rollback()
            return jsonify(error='Payment could not be verified. Retry later.'), 503

    @app.get('/admin/events/<int:event_id>/moodboard/orders')
    @admin_required
    def admin_moodboard_orders(event_id):
        return render_template('admin_moodboard_orders.html', event=db.get_or_404(Event, event_id),
            orders=Order.query.filter_by(event_id=event_id).order_by(Order.id.desc()).all(),
            csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)))

    def check_csrf():
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)

    @app.post('/admin/events/<int:event_id>/moodboard/payments')
    @admin_required
    def admin_moodboard_payment_control(event_id):
        return 'New moodboard payments have been removed. Existing payment history remains available.', 410

    @app.post('/admin/events/<int:event_id>/moodboard/orders/<int:order_id>/fulfilment')
    @admin_required
    def admin_moodboard_fulfilment(event_id, order_id):
        check_csrf()
        order = db.get_or_404(Order, order_id)
        if order.event_id != event_id:
            abort(404)
        expected = request.form.get('expected')
        target = request.form.get('status')
        if (expected, target) not in (('Waiting', 'Being painted'), ('Being painted', 'Completed')):
            abort(400)
        changed = Order.query.filter_by(id=order.id, paid=True, fulfilment=expected).update(
            {'fulfilment': target, 'fulfilment_updated_at': datetime.utcnow()}, synchronize_session=False)
        if not changed:
            db.session.rollback()
            return 'This order is unpaid or its status has changed. Refresh the payment list.', 409
        db.session.commit()
        return redirect(url_for('admin_moodboard_orders', event_id=event_id))
