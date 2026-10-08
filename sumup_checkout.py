"""SumUp-hosted payments verified through the provider before ledger posting."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
import secrets
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import URLError
from zoneinfo import ZoneInfo
from flask import abort, flash, jsonify, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sumup_invoices import validate_link


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


def provider_request(path,payload=None):
    key=os.getenv('SUMUP_API_KEY','')
    if not key:raise ValueError('SumUp online payments have not been configured.')
    req=Request('https://api.sumup.com/v0.1/'+path,data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'},method='POST' if payload is not None else 'GET')
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
    def owned(booking):
        account=current_client()
        return bool(account and booking and account.email.casefold()==booking.email.casefold())
    def verify(row):
        if row.recorded:return True
        if not row.provider_id:
            candidates=provider_request('checkouts?checkout_reference='+quote(row.reference,safe=''))
            if not isinstance(candidates,list) or len(candidates)!=1 or not isinstance(candidates[0],dict):
                raise ValueError('Checkout creation is still unresolved. Check SumUp before retrying.')
            data=candidates[0]
            identity=data.get('id','')
            if not isinstance(identity,str) or not identity or len(identity)>100 or any(c not in '0123456789abcdefABCDEF-' for c in identity):
                raise ValueError('Checkout identity could not be verified.')
            row.provider_id=identity
            if data.get('hosted_checkout_url'):row.payment_url=validate_link(data['hosted_checkout_url'])
        data=provider_request('checkouts/'+row.provider_id)
        if not isinstance(data,dict):raise ValueError('Invalid checkout response.')
        try:
            matches=(data.get('id')==row.provider_id and data.get('checkout_reference')==row.reference and data.get('merchant_code')==row.merchant and data.get('currency')=='GBP' and Decimal(str(data.get('amount')))==row.amount)
        except InvalidOperation:matches=False
        if not matches:
            db.session.rollback();raise ValueError('Payment details did not match this booking. Contact CL Paints to investigate.')
        if data.get('status')!='PAID':db.session.commit();return False
        claimed=Checkout.query.filter_by(id=row.id,recorded=False).update({'recorded':True},synchronize_session=False)
        if claimed:
            db.session.add(Entry(booking_id=row.booking_id,token='sumup-'+row.token,amount=row.amount,kind='payment',method='SumUp',note='Verified online '+row.purpose+' checkout '+row.reference,paid_date=datetime.now(ZoneInfo('Europe/London')).date()))
            try:db.session.commit()
            except IntegrityError:
                db.session.rollback()
                if not Entry.query.filter_by(token='sumup-'+row.token).first():raise
        return True
    def create(booking,purpose):
        if not configured():raise ValueError('Online payments have not been enabled yet. Please contact CL Paints to arrange payment.')
        if booking.status!='Accepted':raise ValueError('The booking must be accepted before requesting online payment.')
        summary=app.extensions['payment_summary'](booking)
        amount=min(summary['outstanding'],max(Decimal(0),summary['deposit']-summary['paid'])) if purpose=='Deposit' else summary['outstanding']
        if amount<=0:raise ValueError('No payment is due for this option. Set the deposit arrangement first, if needed.')
        Booking.query.filter_by(id=booking.id).with_for_update().first()
        existing=Checkout.query.filter_by(booking_id=booking.id,purpose=purpose,recorded=False).order_by(Checkout.id.desc()).first()
        if existing:
            if verify(existing):raise ValueError('A payment was verified and recorded. Refresh the booking before paying again.')
            status=provider_request('checkouts/'+existing.provider_id).get('status')
            if status not in ('EXPIRED','FAILED'):
                if existing.amount!=amount:raise ValueError('An earlier checkout is still pending. Resolve it in SumUp before changing the amount.')
                return existing.payment_url
        base=settings().get('public_app_url','').rstrip('/')
        from urllib.parse import urlsplit
        parsed=urlsplit(base)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Online payment is not ready. Contact CL Paints to arrange another payment method.')
        token=secrets.token_hex(24)
        row=Checkout(booking_id=booking.id,token=token,reference='CL-'+token,amount=amount,purpose=purpose,merchant=os.environ['SUMUP_MERCHANT_CODE'])
        db.session.add(row);db.session.commit()
        payload=dict(checkout_reference=row.reference,amount=float(amount),currency='GBP',merchant_code=row.merchant,description='CL Paints '+purpose+' - '+booking.public_reference,
            hosted_checkout={'enabled':True},return_url=base+url_for('sumup_payment_callback',token=token),redirect_url=base+url_for('client.booking_detail',booking_id=booking.id))
        data=provider_request('checkouts',payload)
        if not isinstance(data,dict):raise ValueError('Invalid checkout response.')
        identity=data.get('id','')
        if not isinstance(identity,str) or not identity or len(identity)>100 or any(c not in '0123456789abcdefABCDEF-' for c in identity):
            raise ValueError('SumUp did not return a valid checkout identity.')
        link=validate_link(data.get('hosted_checkout_url',''))
        row.provider_id=identity;row.payment_url=link;db.session.commit();return link

    @app.context_processor
    def context():
        if request.endpoint not in ('admin_payments','client.booking_detail'):return {}
        booking=db.session.get(Booking,request.view_args['booking_id'])
        if not booking:return {}
        if request.endpoint=='client.booking_detail' and not owned(booking):return {}
        return dict(sumup_online_ready=configured(),sumup_checkouts=Checkout.query.filter_by(booking_id=booking.id).order_by(Checkout.id.desc()).all())

    @app.post('/client/bookings/<int:booking_id>/pay')
    def client_booking_pay(booking_id):
        booking=db.get_or_404(Booking,booking_id)
        if not owned(booking):abort(404)
        check();purpose=request.form.get('purpose')
        if purpose not in ('Deposit','Balance'):abort(400)
        try:return redirect(create(booking,purpose))
        except ValueError as error:
            db.session.rollback();flash(str(error),'error');return redirect(url_for('client.booking_detail',booking_id=booking.id))

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
        except ValueError:return jsonify(error='Payment could not be verified. Retry later.'),503

    @app.post('/bookings/<int:booking_id>/online-payment/<int:checkout_id>/refresh')
    def sumup_payment_refresh(booking_id,checkout_id):
        row=db.get_or_404(Checkout,checkout_id);booking=db.get_or_404(Booking,booking_id)
        admin=session.get('admin_authenticated') and datetime.utcnow().timestamp()-session.get('admin_last_activity',0)<1800
        if row.booking_id!=booking.id or (not admin and not owned(booking)):abort(404)
        check()
        try:flash('Payment verified and recorded.' if verify(row) else 'Payment is not yet marked paid by SumUp.','success')
        except ValueError as error:flash(str(error),'error')
        return redirect(url_for('admin_payments',booking_id=booking.id) if admin else url_for('client.booking_detail',booking_id=booking.id))

    app.extensions['sumup_verify_checkout']=verify
