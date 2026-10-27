"""Audited corrections to historical booking prices and missing received payments."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from booking_cashup import money
from booking_edit import version
from client_notifications import booking_snapshot


def define_model(db):
    class BookingFinancialCorrection(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        booking_id=db.Column(db.Integer,db.ForeignKey('booking.id'),nullable=False,index=True)
        token=db.Column(db.String(64),nullable=False,unique=True)
        before_json=db.Column(db.Text,nullable=False)
        after_json=db.Column(db.Text,nullable=False)
        reason=db.Column(db.Text,nullable=False)
        recorded_by=db.Column(db.String(255),nullable=False)
        recorded_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    return BookingFinancialCorrection


def register(app,db,Correction,Booking,Entry,Change,Checkout,schedule,admin_required):
    def historical(booking):
        events=schedule(booking)
        if not events: return False
        try:
            finishes=[]
            for event in events:
                start=datetime.fromisoformat(event['date']+'T'+event.get('start_time',booking.start_time))
                end=datetime.fromisoformat(event['date']+'T'+event.get('finish_time',booking.finish_time))
                if end<=start: end+=timedelta(days=1)
                finishes.append(end)
            return max(finishes)<=datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=None)
        except (ValueError,TypeError,KeyError): return False

    def revision(booking):
        summary=app.extensions['payment_summary'](booking)
        return hashlib.sha256(json.dumps(dict(booking=version(booking),
            entries=[(entry.id,str(entry.amount),entry.kind) for entry in summary['entries']],
            deposit=str(summary['deposit'])),sort_keys=True).encode()).hexdigest()

    @app.context_processor
    def context():
        if request.endpoint!='admin_payments': return {}
        booking=db.session.get(Booking,request.view_args['booking_id'])
        if not booking or not historical(booking): return dict(historical_finances_available=False)
        return dict(historical_finances_available=True,historical_finances_version=revision(booking),
            historical_finances_token=session.setdefault(f'historical_finances_{booking.id}',secrets.token_hex(24)),
            historical_corrections=Correction.query.filter_by(booking_id=booking.id).order_by(Correction.id.desc()).all())

    def timeline(booking):
        return [dict(at=row.recorded_at,label='Historical financial correction',actor=row.recorded_by,
            details=row.reason) for row in Correction.query.filter_by(booking_id=booking.id).all()]
    app.extensions['historical_finances_timeline']=timeline

    @app.post('/admin/bookings/<int:booking_id>/historical-finances')
    @admin_required
    def admin_historical_finances(booking_id):
        booking=Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        csrf=session.get('client_csrf','')
        if not csrf or not secrets.compare_digest(csrf,request.form.get('csrf_token','')): abort(400)
        token=request.form.get('correction_token','')
        existing=Correction.query.filter_by(token=token).first()
        if existing:
            if existing.booking_id!=booking.id: abort(400)
            flash('This historical correction has already been saved. No duplicate payment was added.','success')
            return redirect(url_for('admin_payments',booking_id=booking.id))
        expected=session.get(f'historical_finances_{booking.id}','')
        if not expected or not secrets.compare_digest(expected,token): abort(400)
        try:
            if not historical(booking): raise ValueError('Historical corrections are available only after all booking dates have finished.')
            if request.form.get('version')!=revision(booking): raise ValueError('These booking or payment figures changed. Reload Payments and review the latest figures before correcting them.')
            reason=request.form.get('reason','').strip()
            if not reason or len(reason)>2000: raise ValueError('Enter a correction reason of up to 2,000 characters.')
            event_cost=money(request.form.get('event_cost',''))
            travel=money(request.form.get('travel_charge',''))
            received=money(request.form.get('received_amount','0'))
            summary=app.extensions['payment_summary'](booking)
            if summary['deposit']>event_cost+travel: raise ValueError('The corrected price is below the requested deposit. Correct the payment schedule first.')
            if Checkout.query.filter_by(booking_id=booking.id,recorded=False).first():
                raise ValueError('An unresolved online checkout exists. Reconcile its payment status before changing historical figures.')
            if event_cost==booking.total_event_cost and travel==booking.travel_charge and received==0:
                raise ValueError('Enter a corrected price or an additional missing payment.')
            paid_date=None; method=''; reference=request.form.get('receipt_reference','').strip()
            if len(reference)>200: raise ValueError('Keep the receipt reference under 200 characters.')
            if received:
                try: paid_date=datetime.strptime(request.form.get('paid_date',''),'%Y-%m-%d').date()
                except ValueError: raise ValueError('Enter the original payment date.')
                if paid_date>datetime.now(ZoneInfo('Europe/London')).date(): raise ValueError('An already-received payment cannot have a future payment date.')
                method=request.form.get('method','')
                if method not in ('SumUp','Cash','Bank transfer'): raise ValueError('Choose the original payment method.')
            before=booking_snapshot(booking,schedule)
            before_money=dict(event_cost=str(booking.total_event_cost),travel=str(booking.travel_charge),paid=str(summary['paid']))
            booking.total_event_cost=event_cost
            booking.travel_charge=travel
            if received:
                db.session.add(Entry(booking_id=booking.id,token='historical-'+token,amount=received,kind='payment',
                    method=method,paid_date=paid_date,note=('Historical payment received before entry. '+reference)[:500]))
            after=booking_snapshot(booking,schedule)
            changes={key:dict(before=before.get(key,'Not set'),after=after.get(key,'Removed'))
                for key in before.keys()|after.keys() if before.get(key)!=after.get(key)}
            db.session.add(Correction(booking_id=booking.id,token=token,reason=reason,
                before_json=json.dumps(before_money),after_json=json.dumps(dict(event_cost=str(event_cost),travel=str(travel),
                    added_payment=str(received),paid_date=str(paid_date or ''),method=method,reference=reference)),
                recorded_by=os.getenv('ADMIN_EMAIL') or 'CL Paints admin'))
            if changes: db.session.add(Change(booking_id=booking.id,changes_json=json.dumps(changes)))
            db.session.commit()
            session.pop(f'historical_finances_{booking.id}',None)
            flash('Historical price and payment records saved. Booking status is unchanged. No card was charged and no client email was sent.','success')
        except (ValueError,InvalidOperation,IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if not isinstance(error,IntegrityError) else 'This correction was already recorded. Reload Payments.','error')
        return redirect(url_for('admin_payments',booking_id=booking.id))
