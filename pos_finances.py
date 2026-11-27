"""Retained till refunds and dated, itemised cash-up summaries."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError

UTC = timezone.utc
UK = ZoneInfo('Europe/London')


def define_refund_model(db):
    class PosRefund(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        sale_id = db.Column(db.Integer, db.ForeignKey('pos_sale.id'), nullable=False, index=True)
        token = db.Column(db.String(64), nullable=False, unique=True)
        items_json = db.Column(db.Text, nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        method = db.Column(db.String(12), nullable=False)
        status = db.Column(db.String(30), nullable=False)
        reason = db.Column(db.String(1000), nullable=False)
        recorded_by = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        completed_at = db.Column(db.DateTime, nullable=True, index=True)
        provider_baseline = db.Column(db.Numeric(10, 2), nullable=True)
        provider_transaction_id = db.Column(db.String(100), nullable=True)
        note = db.Column(db.String(500), nullable=False, default='')
        receipt_email = db.Column(db.String(320), nullable=True)
        receipt_status = db.Column(db.String(20), nullable=True)
        receipt_sent_at = db.Column(db.DateTime, nullable=True)
        loyalty_review_status = db.Column(db.String(30), nullable=True)
        loyalty_review_note = db.Column(db.Text, nullable=True)
        loyalty_reviewed_by = db.Column(db.String(255), nullable=True)
        loyalty_reviewed_at = db.Column(db.DateTime, nullable=True)

        @property
        def items(self):
            return json.loads(self.items_json)
    return PosRefund


def refund_lines(sale):
    sold = json.loads(sale.items_json)
    reserved = [0] * len(sold)
    for refund in sale.refunds:
        if refund.status != 'Failed':
            for item in refund.items:
                reserved[item['line']] += item['quantity']
    return [dict(item, line=index, remaining=item['quantity']-reserved[index]) for index, item in enumerate(sold)]


def post_reader_refund(merchant, transaction_id, amount):
    # The documented legacy refund endpoint uses major units and a 204 success response.
    # Keep the decimal exact in JSON, and only call after merchant-scoped transaction verification.
    payload = ('{"amount":'+format(amount,'.2f')+'}').encode('utf-8')
    path = f'https://api.sumup.com/v0.1/me/refund/{quote(transaction_id, safe="")}'
    req = Request(path, data=payload, method='POST', headers={
        'Authorization':'Bearer '+os.environ['SUMUP_API_KEY'], 'Content-Type':'application/json', 'Accept':'application/json'})
    with urlopen(req, timeout=15) as response:
        if response.status != 204:
            raise ValueError('The refund response needs verification with SumUp.')


class PosLedger:
    def __init__(self, app, db, Sale, Refund, Event):
        self.app, self.db, self.Sale, self.Refund, self.Event = app, db, Sale, Refund, Event

    def events(self):
        return self.Event.query.filter(self.Event.event_date == datetime.now(UK).date(),
            self.Event.status.in_(['Open', 'Closing Soon'])).order_by(self.Event.name).all()

    def prepare(self, form):
        raw = form.get('trading_event_id', '') or form.get('loyalty_event_id', '')
        if not raw:
            return None, None, None
        try:
            event_id = int(raw)
        except ValueError:
            raise ValueError('Choose a valid trading event.')
        event = next((item for item in self.events() if item.id == event_id), None)
        if not event:
            raise ValueError('Choose an open trading event for today.')
        if form.getlist('loyalty_participant_id') and form.get('loyalty_event_id', type=int) != event.id:
            raise ValueError('Trading and loyalty must refer to the same event.')
        return event.id, getattr(event, 'booking_id', None), (getattr(event, 'booking_day_number', 1) or 1)-1

    def summary(self, selected, booking_id=None, event_index=None, since=None, trading_event_id=None):
        start = datetime.combine(selected, datetime.min.time(), UK).astimezone(UTC).replace(tzinfo=None)
        end = datetime.combine(selected+timedelta(days=1), datetime.min.time(), UK).astimezone(UTC).replace(tzinfo=None)
        paid_time = self.db.func.coalesce(self.Sale.paid_at,self.Sale.created_at)
        sales = self.Sale.query.filter(self.Sale.status == 'Paid', paid_time >= start, paid_time < end)
        refunds = self.Refund.query.join(self.Sale, self.Sale.id == self.Refund.sale_id).filter(
            self.Refund.status == 'Refunded', self.Refund.completed_at >= start, self.Refund.completed_at < end)
        condition = None
        if trading_event_id is not None:
            condition = self.db.func.coalesce(self.Sale.trading_event_id, self.Sale.loyalty_event_id) == trading_event_id
        elif booking_id is not None:
            events = self.db.session.query(self.Event.id).filter(self.Event.booking_id==booking_id,
                self.Event.booking_day_number==event_index+1)
            condition = self.db.or_(self.db.and_(self.Sale.booking_id == booking_id, self.Sale.event_index == event_index),
                self.db.and_(self.Sale.booking_id.is_(None),self.db.func.coalesce(self.Sale.trading_event_id,self.Sale.loyalty_event_id).in_(events)))
        if condition is not None:
            sales, refunds = sales.filter(condition), refunds.filter(condition)
        totals = {key:Decimal('0.00') for key in ('cash_sales','card_sales','cash_refunds','card_refunds')}
        items, transactions = {}, []
        cash_before = Decimal('0.00')
        def record(sale, amount, lines, at, kind, reference, refund_id=None):
            nonlocal cash_before
            field = sale.method.lower() + ('_refunds' if kind == 'Refund' else '_sales')
            if field in totals:
                totals[field] += amount
            if sale.method == 'Cash' and since and at <= since:
                cash_before += -amount if kind == 'Refund' else amount
            for item in lines:
                key = (item['name'], str(Decimal(item['price']).quantize(Decimal('.01'))))
                row = items.setdefault(key, dict(name=key[0], price=key[1], sold=0, refunded=0, sales=Decimal(0), refunds=Decimal(0)))
                row['refunded' if kind == 'Refund' else 'sold'] += item['quantity']
                row['refunds' if kind == 'Refund' else 'sales'] += Decimal(item['price'])*item['quantity']
            transactions.append(dict(sale_id=sale.id, refund_id=refund_id, reference=reference, type=kind,
                method=sale.method, amount=f'{amount:.2f}', at=at.replace(tzinfo=UTC).isoformat(),
                customer=sale.customer_label or 'Unlinked sale',actor=sale.staff_name or 'Older transaction'))
        for sale in sales.order_by(self.Sale.paid_at, self.Sale.id).all():
            record(sale, sale.amount, json.loads(sale.items_json), sale.paid_at or sale.created_at, 'Sale', sale.reference)
        for refund in refunds.order_by(self.Refund.completed_at, self.Refund.id).all():
            sale = self.db.session.get(self.Sale, refund.sale_id)
            record(sale, refund.amount, refund.items, refund.completed_at, 'Refund', f'REF-{refund.id}', refund.id)
            transactions[-1]['loyalty_review'] = refund.loyalty_review_status
            transactions[-1]['actor'] = refund.recorded_by
        unpaid = self.Sale.query.filter(self.Sale.status!='Paid',self.Sale.created_at>=start,self.Sale.created_at<end)
        unconfirmed = self.Refund.query.join(self.Sale,self.Sale.id==self.Refund.sale_id).filter(self.Refund.status!='Refunded',
            self.Refund.created_at>=start,self.Refund.created_at<end)
        if condition is not None:
            unpaid, unconfirmed = unpaid.filter(condition), unconfirmed.filter(condition)
        for sale in unpaid.all():
            transactions.append(dict(sale_id=sale.id,refund_id=None,reference=sale.reference,type=f'Sale: {sale.status} (excluded)',
                method=sale.method,amount=f'{sale.amount:.2f}',at=sale.created_at.replace(tzinfo=UTC).isoformat(),customer=sale.customer_label or 'Unlinked sale'))
        for refund in unconfirmed.all():
            transactions.append(dict(sale_id=refund.sale_id,refund_id=refund.id,reference=f'REF-{refund.id}',type=f'Refund: {refund.status} (excluded)',
                method=refund.method,amount=f'{refund.amount:.2f}',at=refund.created_at.replace(tzinfo=UTC).isoformat(),customer=refund.reason))
        rows = []
        for row in sorted(items.values(), key=lambda row:(row['name'].casefold(), Decimal(row['price']))):
            rows.append(dict(row, sales=f"{row['sales']:.2f}", refunds=f"{row['refunds']:.2f}", net=f"{row['sales']-row['refunds']:.2f}"))
        result = {key:f'{value:.2f}' for key, value in totals.items()}
        result.update(date=selected.isoformat(), items=rows, transactions=sorted(transactions, key=lambda row:row['at']),
            gross=f"{totals['cash_sales']+totals['card_sales']:.2f}",
            refunds=f"{totals['cash_refunds']+totals['card_refunds']:.2f}",
            net=f"{totals['cash_sales']+totals['card_sales']-totals['cash_refunds']-totals['card_refunds']:.2f}",
            cash_before_opening=f'{cash_before:.2f}')
        result['version'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return result

    def cash_since(self, at):
        sales = self.Sale.query.filter_by(method='Cash', status='Paid')
        refunds = self.Refund.query.filter_by(method='Cash', status='Refunded')
        if at:
            sales, refunds = sales.filter(self.db.func.coalesce(self.Sale.paid_at,self.Sale.created_at) > at), refunds.filter(self.Refund.completed_at > at)
        paid, returned = sales.all(), refunds.all()
        return dict(amount=sum((row.amount for row in paid), Decimal(0))-sum((row.amount for row in returned), Decimal(0)),
            version=f"{max((row.id for row in paid),default=0)}:{max((row.id for row in returned),default=0)}", count=len(paid)+len(returned))


def register_refunds(app, db, Sale, Refund, admin_required, reader_transaction, send_email=None):
    access=app.extensions.get('pos_access')
    def manager():
        if access: access.require_manager()

    def finish_refund(record,sale):
        if record.status!='Refunded': return
        if record.loyalty_review_status is None and any(row.get('points', 0) > 0 or row.get('redeemed') for row in sale.loyalty_results):
            record.loyalty_review_status='Needs review'
        db.session.commit()
        claimed=Refund.query.filter(Refund.id==record.id,Refund.receipt_status=='Requested',Refund.status=='Refunded').update(
            {'receipt_status':'Sending'},synchronize_session=False)
        db.session.commit()
        if not claimed:return
        db.session.refresh(record)
        try:
            text='\n'.join([f'CL Paints refund receipt — REF-{record.id}',f'Original sale: {sale.reference}',
                f'Refunded: {record.completed_at.isoformat()} UTC',f'Payment method: {record.method}',
                *[f"{item['quantity']} x {item['name']} @ £{item['price']}" for item in record.items],
                f'Refund total: £{record.amount:.2f}',f'Remaining paid on sale: £{sale.amount-sale.refunded_total:.2f}',
                'Questions? Contact info@clpaints.com with the sale reference.'])
            from flask import render_template
            accepted=send_email and send_email(record.receipt_email,f'CL Paints refund receipt — REF-{record.id}',text,
                render_template('pos_refund_email.html',sale=sale,refund=record))
        except Exception:
            app.logger.warning('Refund email failed for refund %s',record.id);accepted=False
        record.receipt_status='Sent' if accepted else 'Failed'
        record.receipt_sent_at=datetime.utcnow() if accepted else None
        db.session.commit()
    def check():
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token','')):
            abort(400)

    def verified_transaction(sale):
        if not os.getenv('SUMUP_API_KEY'):
            raise ValueError('SumUp refunds need the merchant API key configured.')
        data = reader_transaction(sale.merchant, sale.reference)
        if (data.get('currency') != 'GBP' or data.get('foreign_transaction_id') != sale.reference
                or Decimal(str(data.get('amount'))) != sale.amount
                or data.get('transaction_code') != sale.transaction_code or not data.get('id')):
            raise ValueError('The SumUp transaction does not match this sale.')
        return data

    @app.post('/admin/pos/sales/<int:sale_id>/refund')
    @admin_required
    def pos_refund(sale_id):
        check()
        manager()
        sale = Sale.query.filter_by(id=sale_id).with_for_update().first_or_404()
        token = request.form.get('refund_token','')
        if not 20 <= len(token) <= 50 or not all(c.isalnum() or c in '-_' for c in token): abort(400)
        existing = Refund.query.filter_by(token=token).first()
        if existing:
            if existing.sale_id != sale.id: abort(409)
            return redirect(url_for('pos_sale', sale_id=sale.id))
        if sale.status != 'Paid' or any(row.status in ('Processing','Awaiting verification') for row in sale.refunds):
            abort(409, 'Only paid sales without an unresolved refund can be refunded.')
        try:
            reason = request.form.get('reason','').strip()
            if not reason or len(reason)>1000: raise ValueError('Enter a refund reason (up to 1,000 characters).')
            lines, total = [], Decimal('0.00')
            for item in refund_lines(sale):
                quantity = int(request.form.get(f"refund_quantity_{item['line']}", '0'))
                if not 0 <= quantity <= item['remaining']: raise ValueError('Refund quantities cannot exceed the remaining sold quantities.')
                if quantity:
                    lines.append(dict(line=item['line'], name=item['name'], quantity=quantity, price=item['price']))
                    total += quantity*Decimal(item['price'])
            if not lines: raise ValueError('Choose at least one item to refund.')
            if request.form.get('refund_confirmed') != 'yes': raise ValueError('Confirm the refund before processing it.')
            receipt_email=None
            if request.form.get('email_refund_receipt')=='yes':
                try: receipt_email=validate_email(request.form.get('refund_receipt_email','').strip() or sale.receipt_email or '',check_deliverability=False).normalized
                except EmailNotValidError: raise ValueError('Enter a valid email address for the refund receipt.')
            version = sale.refund_version or 0
            changed = Sale.query.filter_by(id=sale.id, refund_version=version).update({'refund_version':version+1}, synchronize_session=False)
            if not changed: abort(409, 'Another refund changed this sale. Reload before refunding.')
            record = Refund(sale_id=sale.id, token=token, items_json=json.dumps(lines), amount=total, method=sale.method,
                status='Refunded' if sale.method=='Cash' else 'Processing', reason=reason,
                recorded_by=access.actor() if access else app.config.get('ADMIN_EMAIL') or 'CL Paints admin',
                receipt_email=receipt_email,receipt_status='Requested' if receipt_email else None,
                completed_at=datetime.utcnow() if sale.method=='Cash' else None)
            if sale.method == 'Card':
                data = verified_transaction(sale)
                refunded = Decimal(str(data.get('refunded_amount', 0)))
                local = sum((row.amount for row in sale.refunds if row.status=='Refunded'),Decimal(0))
                if not refunded.is_finite() or refunded != local:
                    raise ValueError('SumUp refund history differs from the till. Reconcile the transaction before issuing another refund.')
                record.provider_baseline = refunded
                record.provider_transaction_id = str(data['id'])
            db.session.add(record)
            db.session.commit()
        except (ValueError, InvalidOperation, TypeError) as error:
            db.session.rollback(); flash(str(error), 'error')
            return redirect(url_for('pos_sale', sale_id=sale.id))
        except IntegrityError:
            db.session.rollback()
            return redirect(url_for('pos_sale', sale_id=sale.id))
        if sale.method == 'Card':
            try:
                post_reader_refund(sale.merchant, record.provider_transaction_id, record.amount)
                record.status, record.completed_at = 'Refunded', datetime.utcnow()
                record.note = 'SumUp confirmed the refund request.'
            except HTTPError as error:
                record.status = 'Failed' if error.code in (400,401,403,404,409,422) else 'Awaiting verification'
                record.note = f'SumUp returned HTTP {error.code}. Check the transaction before retrying.'
            except (URLError, TimeoutError, OSError, ValueError):
                record.status = 'Awaiting verification'
                record.note = 'Response not confirmed. Check this refund with SumUp; do not issue it again.'
            db.session.commit()
        finish_refund(record,sale)
        flash(f'Refund #{record.id}: {record.status}.', 'success' if record.status=='Refunded' else 'error')
        return redirect(url_for('pos_sale', sale_id=sale.id))

    @app.post('/admin/pos/refunds/<int:refund_id>/verify')
    @admin_required
    def pos_refund_verify(refund_id):
        check()
        manager()
        record = Refund.query.filter_by(id=refund_id).with_for_update().first_or_404()
        sale = db.get_or_404(Sale, record.sale_id)
        if record.status not in ('Processing','Awaiting verification') or record.method != 'Card': abort(409)
        try:
            data = verified_transaction(sale)
            amount = Decimal(str(data.get('refunded_amount',0)))
            if not amount.is_finite() or str(data['id']) != record.provider_transaction_id or amount != record.provider_baseline+record.amount:
                raise ValueError('Refund not confirmed. Check the original transaction in SumUp before taking further action.')
            record.status, record.completed_at = 'Refunded', datetime.utcnow()
            record.note = 'Refund verified against the original SumUp transaction.'
            db.session.commit()
            finish_refund(record,sale)
            flash('Refund verified.', 'success')
        except (ValueError, InvalidOperation, TypeError) as error:
            db.session.rollback(); flash(str(error), 'error')
        return redirect(url_for('pos_sale', sale_id=sale.id))

    @app.post('/admin/pos/refunds/<int:refund_id>/receipt/retry')
    @admin_required
    def pos_refund_receipt_retry(refund_id):
        check();manager()
        record=db.get_or_404(Refund,refund_id)
        if record.status!='Refunded' or record.receipt_status!='Failed':abort(409)
        claimed=Refund.query.filter_by(id=record.id,receipt_status='Failed').update({'receipt_status':'Requested'},synchronize_session=False)
        db.session.commit()
        if not claimed:abort(409)
        finish_refund(record,db.get_or_404(Sale,record.sale_id))
        return redirect(url_for('pos_sale',sale_id=record.sale_id))

    @app.post('/admin/pos/refunds/<int:refund_id>/loyalty-review')
    @admin_required
    def pos_refund_loyalty_review(refund_id):
        check();manager()
        record=db.get_or_404(Refund,refund_id)
        note=request.form.get('review_note','').strip()
        if record.status!='Refunded' or record.loyalty_review_status!='Needs review':abort(409)
        if not note or len(note)>1000:abort(400,'Explain the loyalty review, including any correction made in the event ledger.')
        changed=Refund.query.filter_by(id=record.id,loyalty_review_status='Needs review').update(dict(loyalty_review_status='Reviewed',
            loyalty_review_note=note,loyalty_reviewed_by=access.actor() if access else 'Portal administrator',loyalty_reviewed_at=datetime.utcnow()),synchronize_session=False)
        db.session.commit()
        if not changed:abort(409)
        return redirect(url_for('pos_sale',sale_id=record.sale_id))
