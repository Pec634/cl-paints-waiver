"""Saved baskets and manager day-end reconciliation with retained snapshots."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import secrets
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from zoneinfo import ZoneInfo


def define_models(db):
    class PosHeldBasket(db.Model):
        id = db.Column(db.Integer,primary_key=True)
        owner = db.Column(db.String(80),nullable=False,index=True)
        label = db.Column(db.String(80),nullable=False)
        payload_json = db.Column(db.Text,nullable=False)
        sale_token = db.Column(db.String(50),nullable=False,unique=True)
        status = db.Column(db.String(12),nullable=False,default='Held')
        created_at = db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    class PosReconciliation(db.Model):
        id = db.Column(db.Integer,primary_key=True)
        day = db.Column(db.Date,nullable=False,index=True)
        revision = db.Column(db.Integer,nullable=False)
        status = db.Column(db.String(12),nullable=False)
        data_json = db.Column(db.Text,nullable=False)
        recorded_by = db.Column(db.String(255),nullable=False)
        recorded_at = db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('day','revision'),)
        @property
        def values(self): return json.loads(self.data_json)
    return PosHeldBasket,PosReconciliation


def money(raw, signed=False):
    try:
        value=Decimal(str(raw))
        maximum=Decimal('999999.99')
        if not value.is_finite() or not (-maximum if signed else Decimal(0))<=value<=maximum or value!=value.quantize(Decimal('.01')):
            raise ValueError()
        return value
    except (ValueError,TypeError,InvalidOperation):
        raise ValueError('Use amounts with at most two decimal places, within £999,999.99.')


def register(app,db,models,Sale,Waiver,access,ledger):
    Held,Reconciliation=models
    def latest(day):
        return Reconciliation.query.filter_by(day=day).order_by(Reconciliation.revision.desc()).first()
    def closed(day,summary):
        row=latest(day)
        return row if row and row.status=='Closed' and row.values['ledger']['version']==summary['version'] else None
    app.extensions['pos_reconciliation_closed']=closed

    @app.get('/admin/pos/held')
    @access.required
    def pos_held_list():
        paid=db.exists().where(Sale.reference=='POS-'+Held.sale_token)
        rows=Held.query.filter(Held.owner==access.owner(),~paid).order_by(Held.id.desc()).limit(50).all()
        return jsonify(baskets=[dict(id=row.id,label=row.label,status=row.status,at=row.created_at.isoformat()+'Z') for row in rows])

    @app.post('/admin/pos/held')
    @access.required
    def pos_hold():
        access.check()
        from pos import parse_items
        raw=request.get_json(silent=True) or {}
        try:
            items,_=parse_items(json.dumps(raw.get('items')))
            label=str(raw.get('label','')).strip()
            if not label or len(label)>80: raise ValueError('Name this held basket (up to 80 characters).')
            payload={key:raw.get(key) for key in ('waiver','receipt_email','receipt_requested','trading_event_id','loyalty_event_id','loyalty_people')}
            payload['items']=items
            if len(json.dumps(payload))>30000: raise ValueError('This basket contains too much saved information.')
            waiver=payload.get('waiver')
            if waiver and (not isinstance(waiver,dict) or not db.session.get(Waiver,int(waiver.get('id',0)))):
                raise ValueError('The linked waiver is unavailable.')
            row=Held(owner=access.owner(),label=label,payload_json=json.dumps(payload),sale_token=secrets.token_urlsafe(24))
            db.session.add(row);db.session.commit()
            return jsonify(id=row.id,next_sale_token=secrets.token_urlsafe(24))
        except (ValueError,TypeError,AttributeError) as error:
            db.session.rollback();return jsonify(error=str(error)),400

    @app.post('/admin/pos/held/<int:basket_id>/resume')
    @access.required
    def pos_resume(basket_id):
        access.check()
        row=Held.query.filter_by(id=basket_id,owner=access.owner()).with_for_update().first_or_404()
        if Sale.query.filter_by(reference='POS-'+row.sale_token).first(): abort(409,'This basket already has a saved sale.')
        payload=json.loads(row.payload_json)
        row.status='Resumed';db.session.commit()
        return jsonify(payload=payload,sale_token=row.sale_token)

    def public_event_summaries(day):
        public_event = app.extensions.get('kiosk_public_event')
        if not public_event:
            return []
        events = ledger.Event.query.filter_by(event_date=day).order_by(ledger.Event.name, ledger.Event.id)
        return [dict(name=event.name, event_id=event.id, ledger=ledger.summary(day, trading_event_id=event.id))
                for event in events if public_event(event)]

    @app.get('/admin/pos/event-summary')
    @access.required
    def pos_event_summary():
        access.require_manager()
        try:
            day = date.fromisoformat(request.args.get('date', datetime.now(ZoneInfo('Europe/London')).date().isoformat()))
        except ValueError:
            abort(400)
        response = app.make_response(render_template('pos_event_summary.html', day=day, events=public_event_summaries(day)))
        response.cache_control.no_store = True
        return response

    @app.route('/admin/pos/reconciliation',methods=['GET','POST'])
    @access.required
    def pos_reconcile():
        access.require_manager()
        try: day=date.fromisoformat(request.values.get('date',datetime.now(ZoneInfo('Europe/London')).date().isoformat()))
        except ValueError: abort(400)
        row=latest(day)
        summary=ledger.summary(day)
        values=row.values if row else dict(opening_cash='0.00',other_cash_in='0.00',other_cash_out='0.00',counted_cash='',sumup_net='',notes='')
        error=None
        if request.method=='POST':
            access.check()
            if request.form.get('version','')!=(str(row.id) if row else ''): abort(409,'This reconciliation changed. Reload before saving.')
            try:
                if request.form.get('ledger_version')!=summary['version']: raise ValueError('Till transactions changed. Reload and review the updated totals.')
                values={key:request.form.get(key,'').strip() for key in ('opening_cash','other_cash_in','other_cash_out','counted_cash','sumup_net','notes')}
                opening,added,removed,counted=[money(values[key]) for key in ('opening_cash','other_cash_in','other_cash_out','counted_cash')]
                sumup=money(values['sumup_net'],signed=True)
                expected=opening+added-removed+Decimal(summary['cash_sales'])-Decimal(summary['cash_refunds'])
                card=Decimal(summary['card_sales'])-Decimal(summary['card_refunds'])
                values.update(expected_cash=f'{expected:.2f}',expected_card=f'{card:.2f}',cash_variance=f'{counted-expected:.2f}',card_variance=f'{sumup-card:.2f}',ledger=summary)
                if len(values['notes'])>2000: raise ValueError('Keep reconciliation notes within 2,000 characters.')
                action=request.form.get('action')
                if action not in ('draft','close'): abort(400)
                if action=='close':
                    if day>datetime.now(ZoneInfo('Europe/London')).date(): raise ValueError('Future dates can only be saved as drafts.')
                    if (counted!=expected or sumup!=card) and not values['notes']: raise ValueError('Explain the cash or card differences before closing.')
                    if request.form.get('checked')!='yes': raise ValueError('Confirm the cash count and SumUp comparison before closing.')
                    values['public_events'] = public_event_summaries(day)
                    if ledger.summary(day)['version'] != summary['version']:
                        raise ValueError('Till transactions changed. Reload and review the updated totals.')
                saved=Reconciliation(day=day,revision=row.revision+1 if row else 1,status='Closed' if action=='close' else 'Draft',
                    data_json=json.dumps(values),recorded_by=access.actor())
                db.session.add(saved);db.session.commit()
                flash('Till closed and day-end summaries saved.' if action == 'close' else 'Comparison draft saved.', 'success')
                return redirect(url_for('pos_reconcile',date=day.isoformat()))
            except (ValueError,IntegrityError) as exc:
                db.session.rollback();error=str(exc) if isinstance(exc,ValueError) else 'Another manager saved this day. Reload before saving.'
        return render_template('pos_reconciliation.html',day=day,latest=row,values=values,summary=summary,error=error,
            history=Reconciliation.query.filter_by(day=day).order_by(Reconciliation.revision.desc()).all(),
            csrf=session.setdefault('client_csrf',secrets.token_urlsafe(32))),400 if error else 200
