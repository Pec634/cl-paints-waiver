"""SumUp checkout for validated CL Creates orders, with payment-gated confirmations."""
import os
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit
from flask import abort, jsonify, redirect, render_template, request, session, url_for, make_response
from sumup_checkout import provider_request
from sumup_invoices import validate_link


def register(app, db, Order, notify, business_settings, admin_required):
    app.jinja_env.filters['creates_iso_datetime'] = datetime.fromisoformat
    def base_url():
        base = business_settings().get('public_app_url', '').rstrip('/')
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Online payment is not configured yet. Please contact CL Creates.')
        return base

    def reference(order):
        return 'CC-' + order.checkout_token

    def verify(order):
        if order.paid >= order.total and order.total > 0:
            return True
        if not order.checkout_started:
            return False
        path = 'checkouts/' + quote(order.provider_id, safe='') if order.provider_id else 'checkouts?checkout_reference=' + quote(reference(order), safe='')
        data = provider_request(path)
        if not order.provider_id:
            if not isinstance(data, list) or len(data) != 1:
                raise ValueError('Your payment is still being checked. Please refresh before making another payment.')
            data = data[0]
        try:
            valid = (isinstance(data, dict) and bool(data.get('id')) and len(str(data['id'])) <= 100 and
                (not order.provider_id or data['id'] == order.provider_id) and data.get('checkout_reference') == reference(order) and
                data.get('merchant_code') == order.merchant and data.get('currency') == 'GBP' and
                Decimal(str(data.get('amount'))) == order.total)
        except (InvalidOperation, TypeError, KeyError): valid = False
        if not valid:
            raise ValueError('Payment details did not match your order. Please contact CL Creates.')
        order.provider_id = data['id']
        if data.get('hosted_checkout_url'):
            order.payment_url = validate_link(data['hosted_checkout_url'])
        if data.get('status') != 'PAID':
            db.session.commit(); return False
        # Claim the receipt once, including simultaneous callback and customer refresh.
        changed = Order.query.filter_by(id=order.id, confirmation_dispatched=False).update(
            dict(paid=order.total, status='Paid', confirmation_dispatched=True), synchronize_session=False)
        db.session.commit(); db.session.refresh(order)
        if changed:
            notify(order)
        return True

    app.extensions['creates_verify_payment'] = verify

    def private(response):
        response = make_response(response)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.route('/cl-creates/payment/<token>', methods=['GET','POST'])
    def creates_payment(token):
        order = Order.query.filter_by(checkout_token=token).first_or_404()
        csrf = session.setdefault('creates_csrf', secrets.token_urlsafe(32))
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token','')): abort(400)
            try:
                if verify(order): return private(redirect(url_for('creates_payment', token=token)))
                if not order.checkout_started:
                    if not os.getenv('SUMUP_API_KEY') or not os.getenv('SUMUP_MERCHANT_CODE') or order.total <= 0:
                        raise ValueError('Online payment is unavailable. Please contact CL Creates.')
                    base = base_url()
                    if order.collection_slot_id:
                        slot = next((s for s in app.extensions['creates_collection_slots']() if s.id == order.collection_slot_id), None)
                        import json
                        from datetime import timedelta
                        lead = app.extensions['creates_collection_lead_days']()
                        if not slot or slot.starts_at < datetime.utcnow()+timedelta(days=lead) or slot.starts_at.isoformat() != json.loads(order.collection_snapshot)['starts_at']:
                            raise ValueError('This collection game changed or is no longer available. Please contact CL Creates before paying.')
                    claimed = Order.query.filter_by(id=order.id, checkout_started=False).update(
                        dict(checkout_started=True, merchant=os.environ['SUMUP_MERCHANT_CODE']), synchronize_session=False)
                    db.session.commit(); db.session.refresh(order)
                    if claimed:
                        data = provider_request('checkouts', dict(checkout_reference=reference(order), amount=float(order.total), currency='GBP',
                            merchant_code=order.merchant, description='CL Creates personalised headbands', hosted_checkout={'enabled':True},
                            return_url=base+url_for('creates_payment_callback',token=token), redirect_url=base+url_for('creates_payment',token=token)))
                        if not isinstance(data,dict) or not isinstance(data.get('id'),str) or not data['id'] or len(data['id']) > 100:
                            raise ValueError('The payment response could not be confirmed. Refresh to check before retrying.')
                        try:
                            matches = (data.get('checkout_reference') == reference(order) and data.get('merchant_code') == order.merchant
                                and data.get('currency') == 'GBP' and Decimal(str(data.get('amount'))) == order.total)
                        except InvalidOperation: matches = False
                        if not matches:
                            raise ValueError('The checkout details did not match this order. Please contact CL Creates.')
                        order.provider_id=data['id']; order.payment_url=validate_link(data.get('hosted_checkout_url','')); db.session.commit()
                    else:
                        verify(order)
                if order.payment_url:
                    return private(redirect(order.payment_url))
                raise ValueError('Payment creation is being checked. Refresh this page before trying again.')
            except ValueError as exc:
                db.session.rollback(); error=str(exc)
        elif order.checkout_started:
            try: verify(order)
            except ValueError as exc:
                db.session.rollback(); error=str(exc)
        paid = order.total > 0 and order.paid >= order.total
        if paid and session.get('creates_submission') == order.submission_token:
            session.pop('creates_submission', None)
        import json
        return private(render_template('creates_payment.html', order=order, paid=paid, csrf=csrf, error=error,
            collection=json.loads(order.collection_snapshot) if order.collection_snapshot else None))

    @app.post('/cl-creates/payment-callback/<token>')
    def creates_payment_callback(token):
        order=Order.query.filter_by(checkout_token=token).first_or_404()
        try: return jsonify(verified=verify(order))
        except ValueError:
            db.session.rollback(); return jsonify(error='Payment could not be verified; retry later.'),503
