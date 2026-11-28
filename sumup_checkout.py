"""Booking checkouts verified through SumUp before ledger posting."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import secrets
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit
from urllib.error import URLError
from zoneinfo import ZoneInfo
from flask import abort, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sumup_invoices import validate_link
from payment_workflow import AWAITING_PAYMENT, payments_allowed


def checkout_identity(data):
    identity = data.get('id', '') if isinstance(data, dict) else ''
    if not isinstance(identity, str) or not identity or len(identity) > 100 or any(
        char not in '0123456789abcdefABCDEF-' for char in identity
    ):
        raise ValueError('SumUp did not return a valid checkout identity.')
    return identity


def payment_date(data, *, fallback=True):
    london = ZoneInfo('Europe/London')
    transactions = data.get('transactions')
    if isinstance(transactions, list):
        successful = [
            item for item in transactions
            if isinstance(item, dict) and item.get('status') == 'SUCCESSFUL'
            and (not data.get('transaction_id') or item.get('id') == data['transaction_id'])
        ]
        if len(successful) == 1 and isinstance(successful[0].get('timestamp'), str):
            try:
                paid_at = datetime.fromisoformat(successful[0]['timestamp'].replace('Z', '+00:00'))
                if paid_at.tzinfo is not None:
                    return paid_at.astimezone(london).date()
            except (ValueError, OverflowError):
                pass
    return datetime.now(london).date() if fallback else None


def define_model(db):
    class SumupCheckout(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        booking_id=db.Column(db.Integer,db.ForeignKey('booking.id'),nullable=False,index=True)
        token=db.Column(db.String(64),nullable=False,unique=True)
        provider_id=db.Column(db.String(100),unique=True)
        reference=db.Column(db.String(64),nullable=False,unique=True)
        amount=db.Column(db.Numeric(10,2),nullable=False)
        purpose=db.Column(db.String(20),nullable=False)
        merchant=db.Column(db.String(100),nullable=False)
        payment_url=db.Column(db.String(1000))
        recorded=db.Column(db.Boolean,nullable=False,default=False)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    return SumupCheckout


def provider_request(path,payload=None,method=None):
    key=os.getenv('SUMUP_API_KEY','')
    if not key:raise ValueError('SumUp online payments have not been configured.')
    req=Request('https://api.sumup.com/v0.1/'+path,data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'},method=method or ('POST' if payload is not None else 'GET'))
    try:
        with urlopen(req,timeout=10) as response:
            data=json.loads(response.read(100001))
            if not isinstance(data,(dict,list)):raise ValueError()
            return data
    except (URLError,TimeoutError,ValueError):
        raise ValueError('SumUp could not be reached or returned an invalid response. Please try again.')


def register(app,db,Checkout,Booking,Entry,current_client,admin_required,settings):
    def configured():return bool(os.getenv('SUMUP_API_KEY') and os.getenv('SUMUP_MERCHANT_CODE'))
    def check():
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'],request.form.get('csrf_token','')):abort(400)
    def booking_owner(booking):
        account = current_client()
        if account and booking and account.email.casefold() == booking.email.casefold():
            return account

    def widget_page(booking, checkout, account, *, payment_approved=False):
        response = make_response(render_template('client/booking_checkout.html', booking=booking, checkout=checkout,
            client_account=account, client_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)),
            payment_approved=payment_approved))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def checkout_data(row):
        if not row.provider_id:
            candidates = provider_request('checkouts?checkout_reference=' + quote(row.reference, safe=''))
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError('Checkout creation is still unresolved. Check SumUp before retrying.')
            row.provider_id = checkout_identity(candidates[0])
            if candidates[0].get('hosted_checkout_url'):
                row.payment_url = validate_link(candidates[0]['hosted_checkout_url'])
        data = provider_request('checkouts/' + row.provider_id)
        if not isinstance(data, dict):
            raise ValueError('Invalid checkout response.')
        try:
            matches = (data.get('id') == row.provider_id and data.get('checkout_reference') == row.reference
                       and data.get('merchant_code') == row.merchant and data.get('currency') == 'GBP'
                       and Decimal(str(data.get('amount'))) == row.amount)
        except InvalidOperation:
            matches = False
        if not matches:
            raise ValueError('Payment details did not match this booking. Contact CL Paints to investigate.')
        return data

    def record_payment(row, data):
        if data.get('status') != 'PAID':
            return False
        token = 'sumup-' + row.token
        claimed = Checkout.query.filter_by(id=row.id, recorded=False).update({'recorded': True}, synchronize_session=False)
        if claimed:
            db.session.add(Entry(booking_id=row.booking_id, token=token, amount=row.amount, kind='payment',
                method='SumUp', note=f'Verified online {row.purpose} checkout {row.reference}',
                paid_date=payment_date(data)))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if not Entry.query.filter_by(token=token).first():
                raise
        return True

    def verify(row):
        if row.recorded:
            return True
        if record_payment(row, checkout_data(row)):
            return True
        db.session.commit()
        return False

    def amount_due(booking, purpose):
        summary = app.extensions['payment_summary'](booking)
        if purpose == 'Deposit':
            return min(summary['outstanding'], max(Decimal(0), summary['deposit'] - summary['paid']))
        return summary['outstanding']

    def create(booking, purpose, *, client_payment=False):
        if not configured():raise ValueError('Online payments have not been enabled yet. Please contact CL Paints to arrange payment.')
        if db.engine.dialect.name == 'sqlite':
            # SQLite ignores FOR UPDATE. Take its write lock before checking for an active checkout.
            Booking.query.filter_by(id=booking.id).update({Booking.status: Booking.status}, synchronize_session=False)
        db.session.refresh(booking, with_for_update={'key_share': True})
        if not payments_allowed(booking):raise ValueError('CL Paints must review this booking and mark it Awaiting Payment before online payment is available.')
        widget = client_payment and booking.status == AWAITING_PAYMENT
        amount = amount_due(booking, purpose)
        if amount <= 0:
            raise ValueError('No payment is due for this option. Set the deposit arrangement first, if needed.')
        # Changing the amount must check both purposes. A replacement within
        # either purpose was only created after the previous checkout closed.
        latest_ids = (db.session.query(db.func.max(Checkout.id))
            .filter_by(booking_id=booking.id).group_by(Checkout.purpose))
        existing = Checkout.query.filter(Checkout.id.in_(latest_ids), Checkout.recorded.is_(False))
        active = []
        for attempt in existing:
            data = checkout_data(attempt)
            if record_payment(attempt, data):
                raise ValueError('A payment was verified and recorded. Refresh the booking before paying again.')
            if data.get('status') not in ('EXPIRED', 'FAILED'):
                active.append(attempt)
        if active:
            old = active[0]
            if len(active) != 1 or old.purpose != purpose or old.amount != amount:
                raise ValueError('An earlier SumUp checkout is still open. Complete that payment or wait for it to expire before changing the amount.')
            if not old.payment_url and not widget:
                raise ValueError('A client checkout is still open. Wait for it to expire before creating a new link.')
            db.session.commit()
            return old
        base=settings().get('public_app_url','').rstrip('/')
        parsed=urlsplit(base)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Online payment is not ready. Contact CL Paints to arrange another payment method.')
        token=secrets.token_hex(24)
        row=Checkout(booking_id=booking.id,token=token,reference='CL-'+token,amount=amount,purpose=purpose,merchant=os.environ['SUMUP_MERCHANT_CODE'])
        db.session.add(row);db.session.commit()
        payload = dict(checkout_reference=row.reference, amount=float(amount), currency='GBP',
            merchant_code=row.merchant, description='CL Paints '+purpose+' - '+booking.public_reference,
            return_url=base+url_for('sumup_payment_callback', token=token))
        if widget:
            payload['redirect_url'] = base+url_for('client_booking_widget',
                booking_id=booking.id, checkout_id=row.id, returned=1)
            payload['valid_until'] = (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
        else:
            payload['hosted_checkout'] = {'enabled': True}
            payload['redirect_url'] = base+url_for('client.booking_detail', booking_id=booking.id)
        data = provider_request('checkouts', payload)
        row.provider_id = checkout_identity(data)
        if not widget:
            row.payment_url = validate_link(data.get('hosted_checkout_url', ''))
        db.session.commit()
        return row

    @app.context_processor
    def context():
        base_context = dict(booking_payments_allowed=payments_allowed)
        if request.endpoint not in ('admin_payments','client.booking_detail'):return base_context
        booking=db.session.get(Booking,request.view_args['booking_id'])
        if not booking:return {}
        if request.endpoint=='client.booking_detail' and not booking_owner(booking):return {}
        return dict(base_context,sumup_online_ready=configured(),sumup_payment_allowed=payments_allowed(booking),sumup_checkouts=Checkout.query.filter_by(booking_id=booking.id).order_by(Checkout.id.desc()).all())

    @app.post('/client/bookings/<int:booking_id>/pay')
    def client_booking_pay(booking_id):
        booking=db.get_or_404(Booking,booking_id)
        if not booking_owner(booking):abort(404)
        check();purpose=request.form.get('purpose')
        if purpose not in ('Deposit','Balance'):abort(400)
        try:
            checkout = create(booking, purpose, client_payment=True)
            return redirect(checkout.payment_url or url_for('client_booking_widget', booking_id=booking.id, checkout_id=checkout.id))
        except ValueError as error:
            db.session.rollback();flash(str(error),'error');return redirect(url_for('client.booking_detail',booking_id=booking.id))

    @app.get('/client/bookings/<int:booking_id>/pay/<int:checkout_id>')
    def client_booking_widget(booking_id, checkout_id):
        booking = db.get_or_404(Booking, booking_id)
        row = db.get_or_404(Checkout, checkout_id)
        account = booking_owner(booking)
        if row.booking_id != booking.id or not account or row.payment_url:
            abort(404)
        if row.recorded:
            return widget_page(booking, row, account, payment_approved=True)
        booking_url = url_for('client.booking_detail', booking_id=booking.id)
        returned = request.args.get('returned') == '1'
        widget_allowed = configured() and booking.status == AWAITING_PAYMENT and payments_allowed(booking)
        if not (returned or widget_allowed):
            return redirect(booking_url)
        try:
            data = checkout_data(row)
            if record_payment(row, data):
                return widget_page(booking, row, account, payment_approved=True)
            db.session.commit()
            if row.recorded:
                return widget_page(booking, row, account, payment_approved=True)
            if data.get('status') in ('FAILED', 'EXPIRED'):
                flash('SumUp did not complete this payment. Choose a payment option to try again.', 'error')
                return redirect(booking_url)
            if returned:
                flash('SumUp has not confirmed the payment yet. Use Check payment status to check again.', 'success')
                return redirect(booking_url)
            if row.payment_url or booking.status != AWAITING_PAYMENT or not payments_allowed(booking):
                return redirect(booking_url)
            if data.get('status') != 'PENDING':
                raise ValueError('SumUp could not confirm that this checkout is open. Contact CL Paints before paying.')
            if row.amount != amount_due(booking, row.purpose):
                raise ValueError('The amount due for this booking has changed. Contact CL Paints before paying.')
            return widget_page(booking, row, account)
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
            return redirect(booking_url)

    @app.post('/admin/bookings/<int:booking_id>/online-payment')
    @admin_required
    def admin_online_payment(booking_id):
        booking=db.get_or_404(Booking,booking_id);check();purpose=request.form.get('purpose')
        if purpose not in ('Deposit','Balance'):abort(400)
        try:
            create(booking,purpose);flash('Hosted payment link created. It appears in the client booking; creating a link does not charge a card.','success')
        except ValueError as error:db.session.rollback();flash(str(error),'error')
        return redirect(url_for('admin_payments',booking_id=booking.id))

    @app.post('/payments/sumup/callback/<token>')
    def sumup_payment_callback(token):
        row=Checkout.query.filter_by(token=token).first_or_404()
        try:return jsonify(recorded=verify(row))
        except ValueError:db.session.rollback();return jsonify(error='Payment could not be verified. Retry later.'),503

    @app.post('/bookings/<int:booking_id>/online-payment/<int:checkout_id>/refresh')
    def sumup_payment_refresh(booking_id,checkout_id):
        row=db.get_or_404(Checkout,checkout_id);booking=db.get_or_404(Booking,booking_id)
        from staff_permissions import admin_session
        admin=admin_session() and (session.get('pos_staff_id') or datetime.utcnow().timestamp()-session.get('admin_last_activity',0)<1800)
        account = booking_owner(booking)
        if row.booking_id != booking.id or not (admin or account):
            abort(404)
        check()
        from_widget = bool(account and not row.payment_url and request.form.get('return_to_checkout') == 'yes')
        try:
            paid = verify(row)
            if paid and account and not row.payment_url and (from_widget or not admin):
                return redirect(url_for('client_booking_widget', booking_id=booking_id, checkout_id=checkout_id), code=303)
            flash('Payment verified and recorded.' if paid else 'Payment is not yet marked paid by SumUp.', 'success')
        except ValueError as error:db.session.rollback();flash(str(error),'error')
        target = 'admin_payments' if admin and not from_widget else 'client.booking_detail'
        return redirect(url_for(target, booking_id=booking_id))

    app.extensions['sumup_verify_checkout']=verify
