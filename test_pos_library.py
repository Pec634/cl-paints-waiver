"""Isolated till tests, independent of the rest of the portal's integrations."""
import json
import os
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.error import URLError, HTTPError
from werkzeug.security import generate_password_hash
from functools import wraps
from flask import Flask, abort, session
from flask_sqlalchemy import SQLAlchemy
from jinja2 import ChoiceLoader, DictLoader
import pos
from test_admin_polish_browser import BrowserChecks, EDGE
from pos_loyalty import PosLoyalty
from loyalty import define_models as define_loyalty_models
from pos_finances import define_refund_model, PosLedger, register_refunds
import booking_cashup
import cash_journal
import daily_handovers
import pos_staff
import pos_operations


class PosLibraryTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test', TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://')
        self.app.jinja_loader = ChoiceLoader([DictLoader({
            'base.html': '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/styles.css"></head><body>{% block body %}{% endblock %}</body></html>',
            '_admin_sidebar.html': '<aside>Tools</aside>'}), self.app.jinja_loader])
        self.db = SQLAlchemy(self.app)
        self.Sale = pos.define_model(self.db)
        self.Product = pos.define_product_model(self.db)
        self.Refund = define_refund_model(self.db)
        self.staff_models=pos_staff.define_models(self.db)
        self.operation_models=pos_operations.define_models(self.db)
        class Waiver(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            waiver_reference = self.db.Column(self.db.String(100))
            responsible_email = self.db.Column(self.db.String(100))
            responsible_first_name = self.db.Column(self.db.String(100))
            responsible_last_name = self.db.Column(self.db.String(100))
            is_archived = self.db.Column(self.db.Boolean, default=False)
            signed_date = self.db.Column(self.db.DateTime, default=datetime.utcnow)
            expiry_date = self.db.Column(self.db.DateTime)
            status = self.db.Column(self.db.String(30), default='Valid')
            event_name = self.db.Column(self.db.String(100), default='Event')
            participants = self.db.relationship('Participant', backref='waiver')
        class Participant(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            waiver_id = self.db.Column(self.db.Integer, self.db.ForeignKey('waiver.id'))
            first_name = self.db.Column(self.db.String(100))
            last_name = self.db.Column(self.db.String(100))
        class Event(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            name = self.db.Column(self.db.String(100))
            event_date = self.db.Column(self.db.Date)
            status = self.db.Column(self.db.String(30))
            booking_id = self.db.Column(self.db.Integer)
            booking_day_number = self.db.Column(self.db.Integer)
        class Booking(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            status = self.db.Column(self.db.String(30))
        class ClientAccount(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            email = self.db.Column(self.db.String(255), unique=True)
            first_name = self.db.Column(self.db.String(100))
            last_name = self.db.Column(self.db.String(100))
        class MoodboardImage(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
        self.Waiver, self.Participant = Waiver, Participant
        self.Event, self.Account = Event, ClientAccount
        self.Booking = Booking
        self.Cashup = booking_cashup.define_model(self.db)
        self.Handover = daily_handovers.define_model(self.db)
        self.Movement = cash_journal.define_model(self.db)
        self.TillCount = cash_journal.define_till_count_model(self.db)
        class BusinessSetting(self.db.Model):
            key = self.db.Column(self.db.String(100),primary_key=True)
            value = self.db.Column(self.db.Text)
        self.ledger = PosLedger(self.app, self.db, self.Sale, self.Refund, Event)
        self.app.extensions['pos_ledger'] = self.ledger
        self.loyalty_models = define_loyalty_models(self.db)
        self.app.extensions['kiosk_public_event'] = lambda event: event.name != 'Private event'
        self.loyalty = PosLoyalty(self.app, self.db, self.loyalty_models, ClientAccount, Participant, Waiver, Event)
        def staff_only(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not session.get('staff'): abort(401)
                return function(*args, **kwargs)
            return wrapped
        self.mail = Mock(return_value=True)
        self.access=pos_staff.PosAccess(self.app,self.db,self.staff_models,staff_only)
        self.app.extensions['pos_access']=self.access
        self.access.register()
        pos.register(self.app, self.db, self.Sale, Waiver, Participant, self.access.required, self.Product, self.mail, self.loyalty)
        self.reader = Mock()
        register_refunds(self.app, self.db, self.Sale, self.Refund, self.access.required, self.reader,self.mail)
        pos_operations.register(self.app,self.db,self.operation_models,self.Sale,Waiver,self.access,self.ledger)
        cash_journal.register(self.app,self.db,self.Movement,self.Cashup,BusinessSetting,self.TillCount,staff_only,Event)
        daily_handovers.register(self.app,self.db,self.Handover,Booking,lambda booking:[],staff_only,self.Cashup)
        for endpoint in ('event_day_dashboard','connecteam_rota'):
            self.app.add_url_rule('/test/'+endpoint,endpoint,lambda:'Test')
        self.app.add_url_rule('/admin/waivers/<int:waiver_id>', 'admin_waiver_detail', lambda waiver_id: 'Waiver')
        self.app.add_url_rule('/admin/login','admin_login',lambda:'Admin sign-in')
        self.app.add_url_rule('/admin/events/<int:event_id>/loyalty','loyalty.event_admin',lambda event_id:'Loyalty')
        self.context = self.app.app_context()
        self.context.push()
        self.db.create_all()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state.update(staff=True, admin_authenticated=True, client_csrf='token')

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.context.pop()

    def save(self, **values):
        return self.client.post('/admin/pos/library', data=dict(csrf_token='token', name='Face painting', price='7.50', **values))

    def refundable_sale(self, method='Cash'):
        sale = self.Sale(reference='POS-refund-sale', items_json=json.dumps([dict(name='Painting',quantity=2,price='7.50')]),
            amount=Decimal('15.00'), method=method, status='Paid', cash_tender=Decimal('20') if method=='Cash' else None,
            paid_at=datetime.utcnow(), merchant='MERCHANT' if method=='Card' else '', transaction_code='TX-REFUND' if method=='Card' else None)
        self.db.session.add(sale); self.db.session.commit()
        self.reader.return_value = dict(id='transaction-id', currency='GBP', foreign_transaction_id=sale.reference,
            amount='15.00', transaction_code=sale.transaction_code, refunded_amount=0)
        data = dict(csrf_token='token', refund_token='r'*24, reason='Customer request', refund_quantity_0='1', refund_confirmed='yes')
        return sale, data

    def named_staff(self,role='cashier',username='cashier'):
        pin=str(self.staff_models[0].query.count()+1)
        hashed=generate_password_hash(pin)
        row=self.staff_models[0](username=username,name='Named '+role,password_hash=hashed,pin_hash=hashed,pin_digest=self.access.pin_digest(pin),role=role,enabled=True)
        self.db.session.add(row);self.db.session.commit()
        return row

    def as_staff(self,row):
        with self.client.session_transaction() as state:
            state.clear();state.update(pos_staff_id=row.id,pos_last_activity=datetime.utcnow().timestamp(),
                pos_signed_in_at=datetime.utcnow().timestamp(),client_csrf='token')

    def close_day(self,day):
        summary=self.ledger.summary(day)
        latest=self.operation_models[1].query.filter_by(day=day).order_by(self.operation_models[1].revision.desc()).first()
        return self.client.post('/admin/pos/reconciliation',data=dict(csrf_token='token',date=day.isoformat(),
            version=str(latest.id) if latest else '',ledger_version=summary['version'],action='close',checked='yes',
            opening_cash='100.00',other_cash_in='0.00',other_cash_out='0.00',
            counted_cash=str(100+Decimal(summary['cash_sales'])-Decimal(summary['cash_refunds'])),
            sumup_net=str(Decimal(summary['card_sales'])-Decimal(summary['card_refunds'])),notes=''))

    def test_named_cashier_permissions_prices_and_sale_attribution(self):
        self.save();product=self.Product.query.one()
        cashier=self.named_staff();self.as_staff(cashier)
        self.assertEqual(self.client.post('/admin/pos/library',data={'csrf_token':'token'}).status_code,403)
        self.assertEqual(self.client.get('/admin/pos/staff').status_code,403)
        self.assertEqual(self.client.get('/admin/pos/reconciliation').status_code,403)
        page=self.client.get('/admin/pos')
        self.assertEqual(page.status_code,200)
        self.assertNotIn(b'pos-library-manager',page.data)
        self.assertNotIn(b'id="pos-add-item"',page.data)
        data=dict(csrf_token='token',sale_token='c'*24,method='Cash',cash_tender='10.00')
        for item in (dict(name=product.name,quantity=1,price='5.00',product_id=product.id),dict(name='Custom',quantity=1,price='7.50')):
            self.client.post('/admin/pos/sales',data={**data,'items':json.dumps([item])})
            self.assertEqual(self.Sale.query.count(),0)
        self.client.post('/admin/pos/sales',data={**data,'items':json.dumps([dict(name=product.name,quantity=1,price='7.50',product_id=product.id)])})
        sale=self.Sale.query.one()
        self.assertEqual(sale.staff_id,cashier.id);self.assertEqual(sale.staff_name,'Named cashier');self.assertFalse(sale.price_override)
        self.assertEqual(self.client.post(f'/admin/pos/sales/{sale.id}/refund',data={'csrf_token':'token'}).status_code,403)
        cashier.enabled=False;self.db.session.commit()
        self.assertIn('/staff/login',self.client.get('/admin/pos').location)

    def test_staff_pin_login_throttling_and_manager_pin_storage(self):
        row=self.named_staff(role='manager',username='manager')
        client=self.app.test_client()
        page=client.get('/admin/pos/staff/login');self.assertEqual(page.status_code,200)
        with client.session_transaction() as state:csrf=state['pos_login_csrf']
        self.assertEqual(client.post('/admin/pos/staff/login',data={'csrf_token':'bad'}).status_code,400)
        result=client.post('/admin/pos/staff/login',data=dict(csrf_token=csrf,pin='1'))
        self.assertEqual(result.status_code,302)
        with client.session_transaction() as state:
            self.assertEqual(state['pos_staff_id'],row.id);self.assertNotIn('admin_authenticated',state)
        for index in range(5):
            self.client.post('/admin/pos/staff/login',data={'csrf_token':self.client.get('/admin/pos/staff/login').data.decode().split('name="csrf_token" value="')[1].split('"')[0],'pin':'999999'})
        with self.client.session_transaction() as state:csrf=state['pos_login_csrf']
        self.assertEqual(self.client.post('/admin/pos/staff/login',data=dict(csrf_token=csrf,pin='1')).status_code,429)
        self.assertNotEqual(row.pin_hash,'1')

    def test_manager_price_override_and_item_categories(self):
        manager=self.named_staff('manager','manager');self.as_staff(manager)
        result=self.client.post('/admin/pos/library',data=dict(csrf_token='token',name='Glitter',price='3.00',category='Extras',shortcut='yes'))
        self.assertEqual(result.status_code,302)
        product=self.Product.query.one();self.assertEqual(product.category,'Extras');self.assertTrue(product.shortcut)
        self.client.post('/admin/pos/sales',data=dict(csrf_token='token',sale_token='v'*24,method='Cash',cash_tender='5.00',
            items=json.dumps([dict(name='Glitter',quantity=1,price='2.00',product_id=product.id)])))
        self.assertTrue(self.Sale.query.one().price_override)
        self.assertEqual(self.Sale.query.one().staff_name,'Named manager')

    def test_manager_can_create_reset_and_disable_staff_pins(self):
        payload=dict(csrf_token='token',name='Till assistant',role='cashier',enabled='yes',pin='1')
        self.assertEqual(self.client.post('/admin/pos/staff',data=payload).status_code,302)
        row=self.staff_models[0].query.one()
        self.assertEqual(row.role,'cashier');self.assertTrue(row.enabled)
        old_hash=row.pin_hash
        self.client.post('/admin/pos/staff',data={**payload,'staff_id':row.id,'pin':'02','enabled':''})
        self.assertNotEqual(row.pin_hash,old_hash);self.assertFalse(row.enabled)
        self.assertEqual(pos_operations.money('999999.99'),Decimal('999999.99'))
        self.assertEqual(pos_operations.money('-999999.99',signed=True),Decimal('-999999.99'))

    def test_pins_are_unique_preserve_zeroes_and_have_no_minimum_length(self):
        first=dict(csrf_token='token',name='First staff',role='cashier',enabled='yes',pin='0')
        self.client.post('/admin/pos/staff',data=first)
        row=self.staff_models[0].query.one()
        self.client.post('/admin/pos/staff',data={**first,'name':'Second staff'})
        self.assertEqual(self.staff_models[0].query.count(),1)
        self.client.post('/admin/pos/staff',data={**first,'name':'Second staff','pin':'00'})
        self.assertEqual(self.staff_models[0].query.count(),2)
        self.assertNotEqual(row.pin_digest,self.access.pin_digest('00'))
        original=row.pin_hash
        self.client.post('/admin/pos/staff',data={**first,'staff_id':row.id,'pin':'','enabled':''})
        self.assertEqual(row.pin_hash,original)
        self.client.post('/admin/pos/staff',data={**first,'name':'Third staff'})
        self.assertEqual(self.staff_models[0].query.count(),2)
        for pin in ('','12a',' 1','1'*257):
            self.client.post('/admin/pos/staff',data={**first,'name':'Invalid staff','pin':pin})
        self.assertEqual(self.staff_models[0].query.count(),2)
        login=self.app.test_client()
        login.get('/admin/pos/staff/login')
        with login.session_transaction() as state:csrf=state['pos_login_csrf']
        self.assertEqual(login.post('/admin/pos/staff/login',data=dict(csrf_token=csrf,pin='0')).status_code,200)
        self.assertEqual(login.post('/admin/pos/staff/login',data=dict(csrf_token=csrf,pin='00')).status_code,302)
        with login.session_transaction() as state:
            self.assertEqual(state['pos_staff_id'],self.staff_models[0].query.filter_by(name='Second staff').one().id)
        page=self.client.get('/admin/pos/staff')
        self.assertNotIn(b'minlength=',page.data)
        self.assertNotIn(row.pin_hash.encode(),page.data)

    def test_existing_staff_accounts_upgrade_and_require_pin_allocation(self):
        self.db.session.remove()
        with self.db.engine.begin() as connection:
            connection.exec_driver_sql('DROP TABLE pos_staff')
            connection.exec_driver_sql('CREATE TABLE pos_staff (id INTEGER PRIMARY KEY,username VARCHAR(80) UNIQUE,name VARCHAR(120),password_hash TEXT NOT NULL,role VARCHAR(12),enabled BOOLEAN)')
            connection.execute(self.db.text('INSERT INTO pos_staff (id,username,name,password_hash,role,enabled) VALUES (1,:username,:name,:hash,:role,1)'),
                dict(username='legacy',name='Legacy staff',hash=generate_password_hash('old-password-123'),role='cashier'))
        pos.ensure_schema(self.db);pos.ensure_schema(self.db)
        row=self.staff_models[0].query.one()
        self.assertIsNone(row.pin_hash)
        self.client.post('/admin/pos/staff',data=dict(csrf_token='token',staff_id=row.id,name=row.name,role=row.role,enabled='yes',pin='7'))
        self.assertEqual(row.pin_digest,self.access.pin_digest('7'))

    def test_held_baskets_are_private_recoverable_and_reuse_sale_token(self):
        cashier=self.named_staff();self.as_staff(cashier)
        payload=dict(csrf_token='token',label='Waiting customer',items=[dict(name='Painting',quantity=1,price='7.50')],waiver=None)
        self.assertEqual(self.client.post('/admin/pos/held',json={**payload,'csrf_token':'bad'}).status_code,400)
        saved=self.client.post('/admin/pos/held',json=payload)
        self.assertEqual(saved.status_code,200)
        held_id=saved.json['id']
        other=self.named_staff(username='other');self.as_staff(other)
        self.assertEqual(self.client.get('/admin/pos/held').json['baskets'],[])
        self.assertEqual(self.client.post(f'/admin/pos/held/{held_id}/resume',json={'csrf_token':'token'}).status_code,404)
        self.as_staff(cashier)
        resumed=self.client.post(f'/admin/pos/held/{held_id}/resume',json={'csrf_token':'token'})
        again=self.client.post(f'/admin/pos/held/{held_id}/resume',json={'csrf_token':'token'})
        self.assertEqual(resumed.json['sale_token'],again.json['sale_token'])
        self.assertEqual(resumed.json['payload']['items'][0]['price'],'7.50')

    def test_refund_receipt_and_loyalty_review_are_logged_once(self):
        sale,data=self.refundable_sale()
        sale.loyalty_result_json=json.dumps([dict(participant_id=1,name='Member',points=1,message='Point awarded')])
        self.db.session.commit()
        data.update(email_refund_receipt='yes',refund_receipt_email='customer@example.com')
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        refund=self.Refund.query.one()
        self.assertEqual(refund.receipt_status,'Sent');self.mail.assert_called_once()
        self.assertIn('Remaining paid',self.mail.call_args.args[2])
        self.assertEqual(refund.loyalty_review_status,'Needs review')
        result=self.client.post(f'/admin/pos/refunds/{refund.id}/loyalty-review',data=dict(csrf_token='token',review_note='Partial return; the painting was completed, so retain the point.'))
        self.assertEqual(result.status_code,302);self.assertEqual(refund.loyalty_review_status,'Reviewed')
        self.assertEqual(refund.loyalty_reviewed_by,'Portal administrator')

    def test_day_end_reconciliation_explains_variances_and_detects_later_sales(self):
        from zoneinfo import ZoneInfo
        sale,data=self.refundable_sale();today=datetime.now(ZoneInfo('Europe/London')).date()
        self.assertEqual(self.close_day(today).status_code,302)
        row=self.operation_models[1].query.one()
        self.assertEqual(row.values['expected_cash'],'115.00');self.assertEqual(row.values['cash_variance'],'0.00')
        self.assertIsNotNone(self.app.extensions['pos_reconciliation_closed'](today,self.ledger.summary(today)))
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        self.assertIsNone(self.app.extensions['pos_reconciliation_closed'](today,self.ledger.summary(today)))
        summary=self.ledger.summary(today)
        form=dict(csrf_token='token',date=today.isoformat(),version=str(row.id),ledger_version=summary['version'],action='close',checked='yes',
            opening_cash='100',other_cash_in='0',other_cash_out='0',counted_cash='1',sumup_net='0',notes='')
        self.assertEqual(self.client.post('/admin/pos/reconciliation',data=form).status_code,400)
        form['notes']='Counted short; manager investigating.'
        self.assertEqual(self.client.post('/admin/pos/reconciliation',data=form).status_code,302)
        self.assertEqual(self.operation_models[1].query.count(),2)
        self.assertEqual(row.values['cash_variance'],'0.00')

    def test_refund_email_failure_can_retry_without_repeating_refund(self):
        sale,data=self.refundable_sale()
        data.update(email_refund_receipt='yes',refund_receipt_email='customer@example.com')
        self.mail.return_value=False
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        refund=self.Refund.query.one();self.assertEqual(refund.status,'Refunded');self.assertEqual(refund.receipt_status,'Failed')
        self.mail.return_value=True
        self.client.post(f'/admin/pos/refunds/{refund.id}/receipt/retry',data={'csrf_token':'token'})
        self.assertEqual(refund.receipt_status,'Sent');self.assertEqual(self.Refund.query.count(),1)
        self.assertEqual(self.client.post(f'/admin/pos/refunds/{refund.id}/receipt/retry',data={'csrf_token':'token'}).status_code,409)

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_card_button_requires_server_settings_and_highlights_when_ready(self):
        self.save()
        for configured in (False,True):
            with patch.dict(os.environ,SUMUP_API_KEY='secret-test-value' if configured else '',
                    SUMUP_MERCHANT_CODE='MERCHANT' if configured else '',SUMUP_POS_AFFILIATE_KEY='affiliate-test-value' if configured else ''):
                page=self.client.get('/admin/pos')
                self.assertNotIn(b'secret-test-value',page.data)
                if not configured:
                    self.assertIn(b'SUMUP_POS_AFFILIATE_KEY',page.data)
                    self.assertIn(b'Missing',page.data)
                BrowserChecks.browser(self,page.data,'''
                    const card=document.getElementById('pos-card-pay');
                    assert(card.disabled,'empty basket can start card payment');
                    document.querySelector('[data-product-id]').click();
                    assert(card.disabled===EXPECTED_DISABLED,'card availability ignores server setup');
                    assert(card.classList.contains('pos-card-ready')===!EXPECTED_DISABLED,'ready card button not highlighted');
                    assert(document.getElementById('pos-card-status').textContent.includes(EXPECTED_DISABLED?'incomplete':'ready'),'card readiness explanation missing');
                '''.replace('EXPECTED_DISABLED','false' if configured else 'true'),width=390)

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_mobile_basket_stays_pinned_and_preserves_checkout(self):
        self.save()
        markup=self.client.get('/admin/pos').data
        for width in (320,390,800):
            with self.subTest(width=width):
                BrowserChecks.browser(self,markup,'''
                    const toggle=document.getElementById('pos-mobile-basket-toggle');
                    const panel=document.querySelector('.pos-sale-panel');
                    const browse=document.querySelector('.pos-browse');
                    assert(!toggle.hidden && panel.hidden,'mobile basket should have a visible pinned tab');
                    document.querySelector('[data-product-id]').click();
                    assert(document.getElementById('pos-mobile-basket-count').textContent==='1','basket count did not update');
                    assert(document.getElementById('pos-mobile-basket-total').textContent.includes('7.50'),'pinned total did not update');
                    const marker=document.createElement('div');marker.style.height='1500px';browse.append(marker);
                    const tabTop=toggle.getBoundingClientRect().top;
                    browse.scrollTop=browse.scrollHeight;
                    assert(browse.scrollTop>0 && Math.abs(toggle.getBoundingClientRect().top-tabTop)<1,'basket tab moves when browsing');
                    toggle.click();
                    assert(!panel.hidden && browse.inert && toggle.getAttribute('aria-expanded')==='true','basket drawer did not open');
                    const rect=panel.getBoundingClientRect();
                    assert(rect.left>=0 && rect.right<=innerWidth && rect.top>=0 && rect.bottom<=innerHeight,'basket extends off screen');
                    document.querySelector('.pos-custom-item').open=true;
                    for(let index=0;index<7;index++){
                        document.getElementById('pos-item-name').value='Extra '+index;
                        document.getElementById('pos-item-price').value='1.00';
                        document.getElementById('pos-add-item').requestSubmit();
                    }
                    panel.scrollTop=panel.scrollHeight;
                    assert(panel.scrollTop>0,'basket does not scroll independently');
                    assert(Math.abs(toggle.getBoundingClientRect().top-tabTop)<1,'basket tab moves with checkout scroll');
                    const cancel=new Event('cancel',{cancelable:true});
                    document.getElementById('pos-popup').dispatchEvent(cancel);
                    assert(cancel.defaultPrevented && panel.hidden && !browse.inert,'Escape should close the basket first');
                    toggle.click();
                    assert(document.getElementById('pos-basket').children.length===8,'reopening basket lost items');
                    document.getElementById('pos-clear-waiver').click();
                    assert(panel.hidden && document.activeElement===document.getElementById('pos-query'),'clear waiver did not return to search');
                    assert(document.documentElement.scrollWidth<=innerWidth,'pinned basket overflows mobile screen');
                ''',width=width)

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_categories_shortcuts_and_held_baskets_on_tablet(self):
        self.db.session.add_all([self.Product(name='Painting',price=Decimal('7.50'),category='Faces',shortcut=True),
            self.Product(name='Glitter',price=Decimal('3.00'),category='Extras',shortcut=False)])
        self.db.session.commit()
        markup=self.client.get('/admin/pos').data
        for width in (1024,800):
            BrowserChecks.browser(self,markup,'''
                const category=document.getElementById('pos-product-category');
                category.value='Extras';change(category);
                assert([...document.querySelectorAll('[data-product-id]')].filter(button=>!button.hidden).length===1,'category filter incorrect');
                document.getElementById('pos-shortcuts-only').click();
                assert([...document.querySelectorAll('[data-product-id]')].every(button=>button.hidden),'quick item filter incorrect');
                category.value='';change(category);
                const product=[...document.querySelectorAll('[data-product-id]')].find(button=>!button.hidden);
                assert(product.dataset.productName==='Painting','wrong quick item shown');product.click();
                let heldPayload;
                window.fetch=async (url,options={})=>({ok:true,redirected:false,json:async()=>{
                    if(options.method==='POST'&&String(url).endsWith('/resume'))return {payload:heldPayload,sale_token:'hhhhhhhhhhhhhhhhhhhhhhhh'};
                    if(options.method==='POST'){heldPayload=JSON.parse(options.body);return {id:1,next_sale_token:'nnnnnnnnnnnnnnnnnnnnnnnn'};}
                    return {baskets:heldPayload?[{id:1,label:'Waiting family',status:'Held'}]:[]};
                }});
                document.getElementById('pos-held-controls').open=true;
                await new Promise(resolve=>setTimeout(resolve,0));
                document.getElementById('pos-hold-label').value='Waiting family';
                document.getElementById('pos-hold-basket').click();
                await new Promise(resolve=>setTimeout(resolve,0));
                assert(document.getElementById('pos-basket').children.length===0,'holding basket did not clear till');
                document.querySelector('#pos-held-list button').click();
                await new Promise(resolve=>setTimeout(resolve,0));
                assert(document.getElementById('pos-basket').children.length===1,'resume did not restore basket');
                assert(document.getElementById('pos-checkout').elements.sale_token.value==='hhhhhhhhhhhhhhhhhhhhhhhh','held sale identity changed');
                assert(JSON.parse(sessionStorage.getItem('clpaints-pos-draft')).saleToken==='hhhhhhhhhhhhhhhhhhhhhhhh','resumed sale identity will be lost on refresh');
                assert(document.documentElement.scrollWidth<=innerWidth,'tablet till overflows screen');
            ''',width=width)

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_cashier_controls_and_live_reconciliation_preview(self):
        self.save();cashier=self.named_staff();self.as_staff(cashier)
        markup=self.client.get('/admin/pos').data
        BrowserChecks.browser(self,markup,'''
            document.querySelector('[data-product-id]').click();
            assert(document.querySelectorAll('#pos-basket input')[1].readOnly,'cashier can edit unit price');
            assert(!document.querySelector('#pos-add-item'),'cashier can enter custom items');
            assert(document.getElementById('pos-cash-open') && !document.getElementById('pos-cash-open').disabled,'cashier cannot take cash');
        ''',width=1024)
        manager=self.named_staff('manager','manager');self.as_staff(manager)
        markup=self.client.get('/admin/pos/reconciliation').data
        BrowserChecks.browser(self,markup,'''
            const form=document.querySelector('[data-pos-reconciliation]');
            for(const name of ['opening_cash','other_cash_in','other_cash_out','counted_cash','sumup_net'])form.elements[name].value='0.00';
            form.elements.opening_cash.value='20.00';form.elements.counted_cash.value='19.00';form.dispatchEvent(new Event('input'));
            const variance=form.querySelector('[data-reconcile-value=cash_variance]');
            assert(variance.textContent.includes('1.00') && variance.classList.contains('pos-reconcile-difference'),'cash difference not highlighted');
            form.elements.counted_cash.value='20.00';form.dispatchEvent(new Event('input'));
            assert(!variance.classList.contains('pos-reconcile-difference'),'matched cash still flagged');
        ''',width=1024)

    def test_cash_refunds_are_itemised_bounded_idempotent_and_audited(self):
        sale, data = self.refundable_sale()
        path = f'/admin/pos/sales/{sale.id}/refund'
        self.assertEqual(self.app.test_client().post(path,data=data).status_code,401)
        self.assertEqual(self.client.post(path,data={**data,'csrf_token':'bad'}).status_code,400)
        for changes in ({'refund_quantity_0':'3'},{'refund_quantity_0':'-1'},{'refund_quantity_0':'1.5'},{'reason':''},{'refund_confirmed':''}):
            self.client.post(path,data={**data,**changes})
            self.assertEqual(self.Refund.query.count(),0)
        self.client.post(path,data=data)
        self.client.post(path,data=data)
        refund = self.Refund.query.one()
        self.assertEqual(refund.amount,Decimal('7.50'))
        self.assertEqual(refund.status,'Refunded')
        self.assertEqual(refund.items[0]['name'],'Painting')
        self.assertIsNotNone(refund.completed_at)
        self.assertEqual(sale.refunded_total,Decimal('7.50'))
        self.client.post(path,data={**data,'refund_token':'s'*24,'refund_quantity_0':'2'})
        self.assertEqual(self.Refund.query.count(),1)
        self.client.post(path,data={**data,'refund_token':'s'*24})
        self.assertEqual(sale.refunded_total,sale.amount)
        self.assertIn(b'Net paid: &pound;0.00',self.client.get(f'/admin/pos/sales/{sale.id}').data)

    def test_card_refund_success_and_unknown_response_verification(self):
        sale,data = self.refundable_sale('Card')
        path = f'/admin/pos/sales/{sale.id}/refund'
        with patch.dict(os.environ,SUMUP_API_KEY='test'), patch('pos_finances.post_reader_refund') as provider:
            provider.side_effect=URLError('Connection lost')
            self.client.post(path,data=data)
            refund=self.Refund.query.one()
            self.assertEqual(refund.status,'Awaiting verification')
            self.assertEqual(sale.refunded_total,0)
            self.assertEqual(self.client.post(path,data={**data,'refund_token':'u'*24}).status_code,409)
            self.client.post(path,data=data)
            provider.assert_called_once_with('MERCHANT','transaction-id',Decimal('7.50'))
            self.reader.return_value={**self.reader.return_value,'refunded_amount':'7.50'}
            verify=f'/admin/pos/refunds/{refund.id}/verify'
            self.client.post(verify,data={'csrf_token':'token'})
            self.assertEqual(refund.status,'Refunded')
            self.assertEqual(sale.refunded_total,Decimal('7.50'))
            self.assertEqual(self.client.post(verify,data={'csrf_token':'token'}).status_code,409)
            provider.side_effect=None
            self.client.post(path,data={**data,'refund_token':'u'*24})
            self.assertEqual(sale.refunded_total,Decimal('15.00'))

    def test_card_refund_rejection_does_not_reduce_takings(self):
        sale,data=self.refundable_sale('Card')
        with patch.dict(os.environ,SUMUP_API_KEY='test'),patch('pos_finances.post_reader_refund',side_effect=HTTPError('https://api.sumup.com',403,'Denied',{},None)):
            self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        self.assertEqual(self.Refund.query.one().status,'Failed')
        self.assertEqual(sale.refunded_total,0)
        self.assertIsNone(self.Refund.query.one().completed_at)

    def test_day_ledger_counts_refunds_on_refund_date_and_breaks_down_items(self):
        from zoneinfo import ZoneInfo
        sale,data=self.refundable_sale()
        today=datetime.now(ZoneInfo('Europe/London')).date()
        yesterday=today-timedelta(days=1)
        sale.paid_at=datetime.combine(yesterday,datetime.min.time())+timedelta(hours=12)
        self.db.session.commit()
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        before=self.ledger.summary(yesterday)
        after=self.ledger.summary(today)
        self.assertEqual((before['gross'],before['refunds']),('15.00','0.00'))
        self.assertEqual((after['gross'],after['refunds'],after['net']),('0.00','7.50','-7.50'))
        self.assertEqual((before['items'][0]['sold'],after['items'][0]['refunded']),(2,1))
        self.assertEqual(after['transactions'][0]['type'],'Refund')
        self.assertEqual(self.ledger.cash_since(sale.paid_at)['amount'],Decimal('-7.50'))

    def test_event_cashup_totals_include_only_allocated_pos_transactions(self):
        from booking_cashup import totals
        from zoneinfo import ZoneInfo
        sale,data=self.refundable_sale()
        booking=self.Booking(status='Accepted');self.db.session.add(booking);self.db.session.flush()
        sale.booking_id=booking.id;sale.event_index=0;self.db.session.commit()
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        summary=self.ledger.summary(datetime.now(ZoneInfo('Europe/London')).date(),booking.id,0)
        self.assertEqual(summary['net'],'7.50')
        self.assertEqual(self.ledger.summary(datetime.now(ZoneInfo('Europe/London')).date(),booking.id,1)['gross'],'0.00')
        values={**{'pos_'+key:summary[key] for key in ('cash_sales','card_sales','cash_refunds','card_refunds')},'opening_till':'20.00','closing_till':'27.50'}
        result=totals(values)
        self.assertEqual(result['expected_till'],Decimal('27.50'))
        self.assertEqual(result['net'],Decimal('7.50'))
        self.assertEqual(result['till_variance'],0)
        values['opening_till']='35.00';values['pos_cash_before_opening']='15.00'
        self.assertEqual(totals(values)['expected_till'],Decimal('27.50'))

    def test_daily_handover_retains_transaction_and_item_snapshot(self):
        from zoneinfo import ZoneInfo
        sale,data=self.refundable_sale()
        today=datetime.now(ZoneInfo('Europe/London')).date().isoformat()
        page=self.client.get('/admin/handovers?date='+today)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Till sales &amp; refunds',page.data)
        self.assertIn(b'Painting',page.data)
        form=dict(csrf_token='token',handover_date=today,version='',action='complete',manager_name='Manager',
            business_today='Trading',am_notes='Opened',pm_notes='Closed',incident_status='none')
        self.assertEqual(self.client.post('/admin/handovers',data=form).status_code,400)
        self.assertEqual(self.close_day(datetime.now(ZoneInfo('Europe/London')).date()).status_code,302)
        result=self.client.post('/admin/handovers',data=form)
        self.assertEqual(result.status_code,302)
        saved=self.Handover.query.one()
        self.assertEqual(saved.details['pos_ledger']['gross'],'15.00')
        self.assertEqual(saved.details['pos_ledger']['items'][0]['sold'],2)
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        self.assertEqual(saved.details['pos_ledger']['refunds'],'0.00')
        live=self.client.get('/admin/handovers?date='+today)
        self.assertIn(b'REF-1',live.data)
        printed=self.client.get('/admin/handovers?date='+today+'&print=1')
        self.assertEqual(printed.status_code,200)
        self.assertIn(b'Painting',printed.data)
        self.assertNotIn(b'REF-1',printed.data)

    def test_cash_position_accounts_for_till_sales_and_refunds_once(self):
        opening=self.Movement(token='opening',kind='opening',source='other',destination='till',amount=0,
            opening_till=Decimal('20'),opening_safe=Decimal('100'),reason='Opening',checked_by='Manager',
            recorded_at=datetime.utcnow()-timedelta(hours=1))
        self.db.session.add(opening);self.db.session.commit()
        sale,data=self.refundable_sale()
        state=self.app.extensions['cash_journal_position']()
        self.assertEqual(state['till'],Decimal('35.00'))
        before=state['version']
        self.client.post(f'/admin/pos/sales/{sale.id}/refund',data=data)
        state=self.app.extensions['cash_journal_position']()
        self.assertEqual(state['till'],Decimal('27.50'))
        self.assertNotEqual(before,state['version'])
        booking=self.Booking(status='Accepted');self.db.session.add(booking);self.db.session.flush()
        row=self.Cashup(booking_id=booking.id,event_index=0,event_date=datetime.utcnow().date().isoformat(),revision=1,phase='Closed',
            recorded_by='Manager',data_json=json.dumps(dict(closing_till='27.50',closing_safe='100.00')))
        self.db.session.add(row);self.db.session.commit()
        state=self.app.extensions['cash_journal_position']()
        self.assertEqual(state['till'],Decimal('27.50'))

    def test_refund_provider_request_uses_exact_major_units_and_expected_status(self):
        from pos_finances import post_reader_refund
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.status=204
        with patch.dict(os.environ,SUMUP_API_KEY='test'),patch('pos_finances.urlopen',return_value=response) as provider:
            post_reader_refund('MERCHANT','transaction/id',Decimal('7.50'))
        req=provider.call_args.args[0]
        self.assertEqual(req.full_url,'https://api.sumup.com/v0.1/me/refund/transaction%2Fid')
        self.assertEqual(req.data,b'{"amount":7.50}')
        self.assertEqual(req.method,'POST')

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_refund_quantities_preview_and_cash_confirmation(self):
        sale,data=self.refundable_sale()
        markup=self.client.get(f'/admin/pos/sales/{sale.id}').data
        BrowserChecks.browser(self,markup,'''
            const form=document.querySelector('[data-refund-form]');
            form.closest('details').open=true;
            form.querySelector('[data-refund-all]').click();
            assert(form.querySelector('[data-refund-total]').textContent.includes('15.00'),'refund preview incorrect');
            const field=form.querySelector('[data-refund-price]');
            assert(field.value==='2' && field.max==='2','remaining quantities incorrect');
            field.value='1';field.dispatchEvent(new Event('input'));
            assert(form.querySelector('[data-refund-total]').textContent.includes('7.50'),'partial preview incorrect');
            assert(form.querySelector('[name=refund_confirmed]').required,'cash returned confirmation missing');
            assert(document.documentElement.scrollWidth<=innerWidth,'refund popup overflows phone');
        ''',width=390)

    def loyalty_fixture(self, count=2):
        from zoneinfo import ZoneInfo
        waiver = self.Waiver(waiver_reference='LOYALTY-WAIVER', responsible_first_name='Loyalty', responsible_last_name='Customer',
            responsible_email='loyalty@example.com', expiry_date=datetime.utcnow()+timedelta(days=30))
        event = self.Event(name='Public event', event_date=datetime.now(ZoneInfo('Europe/London')).date(), status='Open')
        self.db.session.add_all([waiver, event]); self.db.session.flush()
        people = [self.Participant(waiver_id=waiver.id, first_name=f'Member{index}', last_name='Customer') for index in range(count)]
        self.db.session.add_all(people); self.db.session.commit()
        data = dict(csrf_token='token', sale_token='l'*24, method='Cash', cash_tender='20.00', waiver_id=str(waiver.id),
            loyalty_event_id=str(event.id), loyalty_participant_id=[str(person.id) for person in people],
            items=json.dumps([dict(name='Painting', quantity=count, price='7.50')]))
        return waiver, people, event, data

    def test_paid_sales_credit_individual_members_once_per_event(self):
        waiver, people, event, data = self.loyalty_fixture()
        _, Balance, Visit, _, _ = self.loyalty_models
        response = self.client.post('/admin/pos/sales', data=data)
        sale = self.Sale.query.one()
        self.assertEqual([self.db.session.get(Balance, person.id).points for person in people], [1, 1])
        self.assertEqual(Visit.query.count(), 2)
        self.assertTrue(all(visit.pos_sale_id == sale.id for visit in Visit.query.all()))
        self.assertEqual(self.Account.query.count(), 1)
        self.assertEqual([row['points'] for row in sale.loyalty_results], [1, 1])
        self.assertIn(b'1 point added', self.client.get(response.location).data)
        self.client.post('/admin/pos/sales', data=data)
        self.client.post('/admin/pos/sales', data={**data, 'sale_token':'m'*24})
        self.assertEqual(Visit.query.count(), 2)
        self.assertEqual([self.db.session.get(Balance, person.id).points for person in people], [1, 1])
        self.assertIn('Already checked in', self.Sale.query.order_by(self.Sale.id.desc()).first().loyalty_results[0]['message'])
        # The QR flow sees these exact same visits and its event uniqueness applies.
        self.assertIsNotNone(Visit.query.filter_by(participant_id=people[0].id, event_id=event.id).first())

    def test_qr_visits_and_full_balances_do_not_receive_extra_pos_points(self):
        waiver, people, event, data = self.loyalty_fixture()
        _, Balance, Visit, _, _ = self.loyalty_models
        account = self.Account(email=waiver.responsible_email, first_name='Loyalty', last_name='Customer')
        self.db.session.add(account); self.db.session.flush()
        self.db.session.add_all([Balance(participant_id=people[0].id, points=1), Balance(participant_id=people[1].id, points=3),
            Visit(participant_id=people[0].id, event_id=event.id, client_id=account.id, status='point')])
        self.db.session.commit()
        self.client.post('/admin/pos/sales', data=data)
        self.assertEqual([self.db.session.get(Balance, person.id).points for person in people], [1, 3])
        self.assertEqual(Visit.query.count(), 1)
        self.assertEqual([row['points'] for row in self.Sale.query.one().loyalty_results], [0, 0])

    def test_pos_loyalty_requires_eligible_event_and_members(self):
        waiver, people, event, data = self.loyalty_fixture(1)
        for changes in ({'loyalty_event_id':''}, {'loyalty_event_id':'9999'}, {'waiver_id':''}, {'loyalty_participant_id':['9999']}):
            self.client.post('/admin/pos/sales', data={**data, **changes})
            self.assertEqual(self.Sale.query.count(), 0)
        event.name = 'Private event'; self.db.session.commit()
        self.client.post('/admin/pos/sales', data=data)
        self.assertEqual(self.Sale.query.count(), 0)
        event.name = 'Public event'; event.status = 'Closed'; self.db.session.commit()
        self.client.post('/admin/pos/sales', data=data)
        self.assertEqual(self.Sale.query.count(), 0)

    def test_live_waiver_endpoint_supports_one_character_and_protects_results(self):
        waiver, people, event, data = self.loyalty_fixture(1)
        endpoint = '/admin/pos/waivers'
        self.assertEqual(self.app.test_client().get(endpoint+'?q=L').status_code, 401)
        page = self.client.get(endpoint, query_string={'q':'L'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertEqual(page.json['count'], 1)
        self.assertIn('LOYALTY-WAIVER', page.json['html'])
        self.assertNotIn('pos-checkout', page.json['html'])
        self.assertEqual(self.client.get(endpoint+'?q=').json['count'], 0)
        self.assertEqual(self.client.get(endpoint+'?q=%25').json['count'], 0)
        waiver.expiry_date = datetime.utcnow()-timedelta(days=1)
        self.db.session.commit()
        self.assertNotIn('Link to sale', self.client.get(endpoint+'?q=L').json['html'])
        waiver.is_archived = True; self.db.session.commit()
        self.assertEqual(self.client.get(endpoint+'?q=L').json['count'], 0)

    def test_card_loyalty_waits_for_successful_payment(self):
        waiver, people, event, data = self.loyalty_fixture(1)
        _, Balance, Visit, _, _ = self.loyalty_models
        with patch.dict(os.environ, SUMUP_API_KEY='test', SUMUP_MERCHANT_CODE='test', SUMUP_POS_AFFILIATE_KEY='test'):
            self.client.post('/admin/pos/sales', data={**data, 'method':'Card'})
            sale = self.Sale.query.one()
            self.assertEqual(Visit.query.count(), 0)
            sale.status = 'Awaiting verification'; self.db.session.commit()
            verify = f'/admin/pos/sales/{sale.id}/verify'
            with patch('pos.reader_transaction', return_value={'status':'FAILED'}):
                self.client.post(verify, data={'csrf_token':'token'})
            self.assertEqual(Visit.query.count(), 0)
            event.status = 'Closed'; self.db.session.commit()
            result = dict(status='SUCCESSFUL', currency='GBP', foreign_transaction_id=sale.reference, amount='7.50', transaction_code='loyalty-tx')
            with patch('pos.reader_transaction', return_value=result):
                self.client.post(verify, data={'csrf_token':'token'})
                self.client.post(verify, data={'csrf_token':'token'})
            self.assertEqual(Visit.query.count(), 1)
            self.assertEqual(self.db.session.get(Balance, people[0].id).points, 1)

    def test_prepare_sumup_payment_renders_handoff_once(self):
        with patch.dict(os.environ,SUMUP_API_KEY='private-key',SUMUP_MERCHANT_CODE='MERCHANT',SUMUP_POS_AFFILIATE_KEY='affiliate-key'):
            self.client.post('/admin/pos/sales',data=dict(csrf_token='token',sale_token='p'*24,method='Card',
                items=json.dumps([dict(name='Painting',quantity=1,price='7.50')])))
            sale=self.Sale.query.one()
            response=self.client.post(f'/admin/pos/sales/{sale.id}/start',data={'csrf_token':'token'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(sale.status,'Awaiting verification')
            self.assertIn(b'sumupmerchant://pay/1.0?',response.data)
            self.assertIn(b'Open SumUp and take',response.data)
            self.assertNotIn(b'private-key',response.data)
            self.assertLessEqual(len(sale.status),self.Sale.__table__.c.status.type.length)
            repeated=self.client.post(f'/admin/pos/sales/{sale.id}/start',data={'csrf_token':'token'})
            self.assertEqual(repeated.status_code,302)
            self.assertEqual(self.Sale.query.count(),1)

    def test_postgresql_upgrade_widens_payment_status_column(self):
        from sqlalchemy import inspect
        engine=self.db.engine
        inspector=inspect(engine)
        tables=inspector.get_table_names()
        columns={table:inspector.get_columns(table) for table in tables}
        for column in columns['pos_sale']:
            if column['name']=='status':column['type']=self.db.String(20)
        mocked=Mock()
        mocked.get_columns.side_effect=lambda name:columns[name]
        mocked.get_table_names.return_value=tables
        with patch('pos.inspect',return_value=mocked),patch.object(engine.dialect,'name','postgresql'),patch.object(engine,'begin') as begin:
            connection=begin.return_value.__enter__.return_value
            pos.ensure_schema(self.db)
        statements=[call.args[0] for call in connection.exec_driver_sql.call_args_list]
        self.assertIn('ALTER TABLE pos_sale ALTER COLUMN status TYPE VARCHAR(32)',statements)

    def test_library_crud_and_sale_price_snapshot(self):
        self.assertEqual(self.save().status_code, 302)
        product = self.Product.query.one()
        self.assertEqual(str(product.price), '7.50')
        self.client.post('/admin/pos/sales', data=dict(csrf_token='token', sale_token='a'*24, method='Cash',
            cash_tender='20.00',
            items=json.dumps([dict(name=product.name, quantity=2, price='6.00')])))
        self.client.post('/admin/pos/library', data=dict(csrf_token='token', product_id=product.id, name='Painting', price='8.00'))
        self.assertEqual(str(product.price), '8.00')
        self.assertEqual(str(self.Sale.query.one().amount), '12.00')
        self.assertEqual(self.client.get('/admin/pos').status_code, 200)
        self.client.post(f'/admin/pos/library/{product.id}/delete', data=dict(csrf_token='token'))
        self.assertEqual(self.Product.query.count(), 0)
        self.assertEqual(self.Sale.query.count(), 1)

    def test_cash_tender_validation_inline_receipt_and_retry(self):
        data = dict(csrf_token='token', sale_token='b'*24, method='Cash',
            items=json.dumps([dict(name='Painting', quantity=3, price='2.10')]))
        self.assertEqual(self.client.post('/admin/pos/sales', data={**data, 'csrf_token':'bad', 'cash_tender':'10.00'}).status_code, 400)
        for tender in ('', 'NaN', 'Infinity', '6.29', '-1', '6.301', '1000000'):
            response = self.client.post('/admin/pos/sales', data={**data, 'cash_tender':tender})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.Sale.query.count(), 0)
        response = self.client.post('/admin/pos/sales', data={**data, 'cash_tender':'10.00'})
        sale = self.Sale.query.one()
        self.assertEqual(str(sale.change_due), '3.70')
        self.assertIn('/admin/pos?completed=', response.location)
        receipt = self.client.get(response.location)
        self.assertIn(b'Change to give:', receipt.data)
        self.assertIn(b'3.70', receipt.data)
        self.client.post('/admin/pos/sales', data={**data, 'cash_tender':'20.00'})
        self.assertEqual(self.Sale.query.count(), 1)
        self.assertEqual(str(sale.cash_tender), '10.00')
        self.assertEqual(self.app.test_client().get(f'/admin/pos/sales/{sale.id}').status_code, 401)

    def test_sale_timestamps_use_uk_time_and_show_seconds(self):
        self.assertEqual(pos.format_sale_time(datetime(2026, 7, 1, 12, 34, 56)), '01/07/2026 13:34:56 BST')
        self.assertEqual(pos.format_sale_time(datetime(2026, 11, 17, 12, 34, 56)), '17/11/2026 12:34:56 GMT')
        self.client.post('/admin/pos/sales', data=dict(csrf_token='token', sale_token='t'*24,
            method='Cash', cash_tender='10.00', items=json.dumps([dict(name='Painting', quantity=1, price='7.50')])))
        sale = self.Sale.query.one()
        sale.created_at = datetime(2026, 7, 1, 12, 34, 56)
        sale.paid_at = datetime(2026, 7, 1, 12, 35, 10)
        self.db.session.commit()
        for path in ('/admin/pos', f'/admin/pos/sales/{sale.id}', f'/admin/pos?completed={sale.id}'):
            page = self.client.get(path)
            self.assertIn(b'01/07/2026 13:34:56 BST', page.data)
            self.assertIn(b'01/07/2026 13:35:10 BST', page.data)

    def test_optional_cash_receipt_is_sent_once_and_contains_totals(self):
        data = dict(csrf_token='token', sale_token='e'*24, method='Cash', cash_tender='10.00',
            items=json.dumps([dict(name='<Painting>', quantity=1, price='7.50')]))
        self.client.post('/admin/pos/sales', data={**data, 'receipt_email':'not-an-email'})
        self.mail.assert_not_called()
        self.assertIsNone(self.Sale.query.one().receipt_email)
        opted = {**data, 'sale_token':'f'*24, 'receipt_requested':'1', 'receipt_email':'customer@example.com'}
        self.client.post('/admin/pos/sales', data=opted)
        self.mail.assert_called_once()
        recipient, subject, text, html = self.mail.call_args.args
        self.assertEqual(recipient, 'customer@example.com')
        self.assertIn('7.50', text)
        self.assertIn('2.50', text)
        self.assertIn('&lt;Painting&gt;', html)
        self.assertNotIn('/admin/', html)
        sale = self.Sale.query.filter_by(reference='POS-'+'f'*24).one()
        self.assertEqual(sale.receipt_status, 'Sent')
        self.assertIsNotNone(sale.receipt_sent_at)
        self.client.post('/admin/pos/sales', data=opted)
        self.mail.assert_called_once()
        self.assertEqual(self.client.post(f'/admin/pos/sales/{sale.id}/receipt/retry', data={'csrf_token':'token'}).status_code, 409)

    def test_bad_receipt_email_prevents_sale_and_failure_can_retry(self):
        data = dict(csrf_token='token', sale_token='g'*24, method='Cash', cash_tender='10.00', receipt_requested='1',
            receipt_email='invalid', items=json.dumps([dict(name='Painting', quantity=1, price='7.50')]))
        self.client.post('/admin/pos/sales', data=data)
        self.assertEqual(self.Sale.query.count(), 0)
        self.mail.return_value = False
        data['receipt_email'] = 'customer@example.com'
        response = self.client.post('/admin/pos/sales', data=data)
        sale = self.Sale.query.one()
        self.assertEqual(sale.status, 'Paid')
        self.assertEqual(sale.receipt_status, 'Failed')
        self.assertIn(b'Retry email receipt', self.client.get(response.location).data)
        self.client.post('/admin/pos/sales', data=data)
        self.assertEqual(self.mail.call_count, 1)
        retry = f'/admin/pos/sales/{sale.id}/receipt/retry'
        self.assertEqual(self.client.post(retry, data={'csrf_token':'bad'}).status_code, 400)
        self.assertEqual(self.app.test_client().post(retry).status_code, 401)
        self.mail.return_value = True
        self.client.post(retry, data={'csrf_token':'token'})
        self.assertEqual(sale.receipt_status, 'Sent')
        self.assertEqual(self.mail.call_count, 2)

    def test_card_receipt_waits_for_verified_payment(self):
        with patch.dict(os.environ, SUMUP_API_KEY='test', SUMUP_MERCHANT_CODE='test', SUMUP_POS_AFFILIATE_KEY='test'):
            self.client.post('/admin/pos/sales', data=dict(csrf_token='token', sale_token='h'*24, method='Card',
                receipt_requested='1', receipt_email='customer@example.com',
                items=json.dumps([dict(name='Painting', quantity=1, price='7.50')])))
            sale = self.Sale.query.one()
            self.mail.assert_not_called()
            retry = f'/admin/pos/sales/{sale.id}/receipt/retry'
            self.assertEqual(self.client.post(retry, data={'csrf_token':'token'}).status_code, 409)
            sale.status = 'Awaiting verification'; self.db.session.commit()
            verify = f'/admin/pos/sales/{sale.id}/verify'
            with patch('pos.reader_transaction', return_value={'status':'FAILED'}):
                self.client.post(verify, data={'csrf_token':'token'})
            self.mail.assert_not_called()
            result = dict(status='SUCCESSFUL', currency='GBP', foreign_transaction_id=sale.reference, amount='7.50', transaction_code='receipt-tx')
            with patch('pos.reader_transaction', return_value=result):
                self.client.post(verify, data={'csrf_token':'token'})
                self.client.post(verify, data={'csrf_token':'token'})
            self.mail.assert_called_once()
            self.assertEqual(sale.receipt_status, 'Sent')

    def test_existing_sales_schema_upgrade_preserves_records(self):
        self.db.session.remove()
        with self.db.engine.begin() as connection:
            connection.exec_driver_sql('DROP TABLE pos_sale')
            connection.exec_driver_sql('''CREATE TABLE pos_sale (id INTEGER PRIMARY KEY, reference VARCHAR(64),
                created_at DATETIME, items_json TEXT, amount NUMERIC(10,2), waiver_id INTEGER,
                method VARCHAR(12), status VARCHAR(20), merchant VARCHAR(100), transaction_code VARCHAR(100), paid_at DATETIME)''')
            connection.exec_driver_sql("""INSERT INTO pos_sale (id, reference, created_at, items_json, amount, method, status, merchant)
                VALUES (1, 'POS-legacy', '2026-01-01 12:00:00', '[]', 7.50, 'Cash', 'Paid', '')""")
        pos.ensure_schema(self.db)
        pos.ensure_schema(self.db)
        sale = self.Sale.query.one()
        self.assertEqual(sale.reference, 'POS-legacy')
        self.assertEqual(str(sale.amount), '7.50')
        self.assertIsNone(sale.cash_tender)
        self.assertIsNone(sale.change_due)

    def test_waiver_participant_history_and_snapshot(self):
        waiver = self.Waiver(waiver_reference='WAIVER-123', responsible_first_name='Taylor', responsible_last_name='Green',
            responsible_email='taylor@example.com', expiry_date=datetime.utcnow()+timedelta(days=30))
        other = self.Waiver(waiver_reference='OTHER', responsible_first_name='Other', responsible_last_name='Person',
            responsible_email='other@example.com', expiry_date=datetime.utcnow()+timedelta(days=30))
        self.db.session.add_all([waiver, other]); self.db.session.flush()
        participant = self.Participant(waiver_id=waiver.id, first_name='Robin', last_name='Green')
        wrong = self.Participant(waiver_id=other.id, first_name='Other', last_name='Child')
        self.db.session.add_all([participant, wrong]); self.db.session.commit()
        data = dict(csrf_token='token', sale_token='c'*24, method='Cash', cash_tender='10.00', waiver_id=waiver.id,
            items=json.dumps([dict(name='Painting', quantity=1, price='7.50')]))
        self.client.post('/admin/pos/sales', data={**data, 'participant_id':wrong.id})
        self.assertEqual(self.Sale.query.count(), 0)
        self.client.post('/admin/pos/sales', data={**data, 'participant_id':participant.id})
        sale = self.Sale.query.one()
        self.assertEqual(sale.participant_id, participant.id)
        self.assertEqual(sale.participant_name, 'Robin Green')
        participant.first_name = 'Renamed'; waiver.responsible_email = 'changed@example.com'; waiver.is_archived = True
        self.db.session.commit()
        for query in ('Robin Green', 'Renamed Green', 'taylor@example.com', 'WAIVER-123', sale.reference, str(sale.id)):
            page = self.client.get('/admin/pos', query_string={'sale_q':query})
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'1 sales', page.data)
        self.assertIn(b'0 sales', self.client.get('/admin/pos?sale_q=absent').data)
        self.assertIn(b'0 sales', self.client.get('/admin/pos', query_string={'history_waiver':other.id}).data)
        self.assertIn(b'Robin Green', self.client.get(f'/admin/pos/sales/{sale.id}').data)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_live_search_retains_basket_handles_new_links_and_ignores_old_responses(self):
        self.save()
        waiver, people, event, data = self.loyalty_fixture(1)
        fixture = self.client.get('/admin/pos/waivers?q=L').json
        markup = self.client.get('/admin/pos').data
        seed = '<script>window.posSearchFixture = '+json.dumps(fixture).replace('<', '\\u003c')+';</script>'
        markup = markup.replace(b'<head>', b'<head>'+seed.encode(), 1)
        BrowserChecks.browser(self, markup, '''
            const requests = [];
            window.fetch = (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
            const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
            document.querySelector('[data-product-id]').click();
            const search = document.getElementById('pos-query');
            search.focus(); search.value = 'L'; search.dispatchEvent(new Event('input'));
            await pause(250);
            assert(requests.length === 1 && new URL(requests[0].url).searchParams.get('q') === 'L', 'first character did not trigger search');
            search.value = 'Lo'; search.dispatchEvent(new Event('input'));
            await pause(250);
            assert(requests.length === 2 && requests[0].options.signal.aborted, 'superseded search was not cancelled');
            requests[1].resolve({ok:true, redirected:false, json:async () => window.posSearchFixture});
            await pause(0);
            assert(document.querySelector('#pos-waiver-results button[data-waiver-id]'), 'live results missing');
            assert(document.activeElement === search, 'live results stole typing focus');
            requests[0].resolve({ok:true, redirected:false, json:async () => ({html:'<p>Old results</p>', count:99})});
            await pause(0);
            assert(!document.getElementById('pos-waiver-results').textContent.includes('Old results'), 'stale response replaced newer results');
            const link = document.querySelector('#pos-waiver-results button[data-waiver-id]');
            link.click();
            assert(document.getElementById('pos-waiver-id').value === link.dataset.waiverId, 'new search result cannot link to basket');
            assert(!document.getElementById('pos-waiver-fold').open, 'new link did not fold search');
            assert(document.getElementById('pos-basket').children.length === 1, 'search lost basket');
            search.value = ''; search.dispatchEvent(new Event('input'));
            assert(!document.getElementById('pos-waiver-results').children.length, 'cleared search left old results');
            assert(document.getElementById('pos-waiver-id').value, 'clearing search unlinked waiver');
            search.value = 'Error';
            document.getElementById('pos-search').dispatchEvent(new Event('submit', {cancelable:true}));
            requests[2].reject(new Error('Offline')); await pause(0);
            assert(document.getElementById('pos-waiver-search-status').textContent.includes('try Search again'), 'search failure gave no retry guidance');
            assert(document.getElementById('pos-basket').children.length === 1, 'failed search lost basket');
        ''', width=390)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_popup_reopens_without_losing_basket_and_scrolls_inside_screen(self):
        self.save()
        for index in range(12):
            self.db.session.add(self.Sale(reference=f'POS-history-{index}', items_json='[]', amount=7.50, method='Cash', status='Paid'))
        self.db.session.commit()
        markup = self.client.get('/admin/pos').data
        for width in (1280, 390):
            BrowserChecks.browser(self, markup, '''
                const popup = document.getElementById('pos-popup');
                assert(popup.open && popup.matches(':modal'), 'till did not open as a modal');
                assert(popup.contains(document.getElementById('pos-library')) && popup.contains(document.getElementById('pos-history')), 'POS features remain outside popup');
                document.querySelector('[data-product-id]').click();
                document.getElementById('pos-popup-close').click();
                assert(!popup.open, 'close till failed');
                document.getElementById('pos-popup-open').click();
                assert(popup.open && popup.matches(':modal'), 'reopen till failed');
                assert(document.getElementById('pos-basket').children.length === 1, 'closing popup lost basket');
                assert(document.documentElement.classList.contains('pos-modal-open'), 'background scroll is not locked');
                const content = popup.querySelector('.pos-browse');
                const history = document.getElementById('pos-history');
                assert(!history.open, 'sale history should start folded');
                history.querySelector('summary').click();
                assert(history.open, 'sale history dropdown did not open');
                const historyList = history.querySelector('.pos-history-list');
                historyList.scrollTop = historyList.scrollHeight;
                assert(historyList.scrollTop > 0, 'sale history list cannot scroll');
                const basketPanel = popup.querySelector('.pos-sale-panel');
                const basketTop = basketPanel.getBoundingClientRect().top;
                content.scrollTop = content.scrollHeight;
                assert(content.scrollTop > 0, 'popup content cannot scroll');
                if (innerWidth >= 900) {
                    assert(Math.abs(basketPanel.getBoundingClientRect().top - basketTop) < 1, 'basket moved while browsing');
                    for (let index = 0; index < 6; index++) {
                        document.getElementById('pos-item-name').value = 'Extra item ' + index;
                        document.getElementById('pos-item-price').value = '1.00';
                        document.getElementById('pos-add-item').requestSubmit();
                    }
                    basketPanel.scrollTop = basketPanel.scrollHeight;
                    assert(basketPanel.scrollTop > 0, 'long basket cannot scroll independently');
                    assert(Math.abs(basketPanel.getBoundingClientRect().top - basketTop) < 1, 'basket position changed while scrolling its contents');
                }
                const rect = popup.getBoundingClientRect();
                assert(rect.left >= 0 && rect.right <= innerWidth + 1 && rect.top >= 0 && rect.bottom <= innerHeight + 1, 'popup exceeds screen');
            ''', width=width)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_loyalty_member_selection_stays_with_basket_when_waiver_folds(self):
        for count in (1, 2):
            waiver, people, event, data = self.loyalty_fixture(count)
            markup = self.client.get('/admin/pos?q=Loyalty').data
            assertions = '''
                const select = [...document.querySelectorAll('.pos-participant')].find(field => field.options.length === MEMBER_COUNT + 1);
                const button = select.closest('.pos-waiver').querySelector('button[data-waiver-id]');
                button.click();
                const fields = document.getElementById('pos-loyalty-fields');
                assert(!fields.hidden && !document.getElementById('pos-waiver-fold').open, 'loyalty controls were hidden with waiver search');
                const choices = [...fields.querySelectorAll('input[type=checkbox]')];
                assert(choices.length === MEMBER_COUNT, 'loyalty people missing');
                assert(choices.filter(field => field.checked).length === (MEMBER_COUNT === 1 ? 1 : 0), 'wrong default loyalty selection');
                choices.forEach(field => { field.checked = true; });
                document.getElementById('pos-loyalty-event').value = 'EVENT_ID';
                const data = new FormData(document.getElementById('pos-checkout'));
                assert(data.getAll('loyalty_participant_id').length === MEMBER_COUNT, 'selected people missing from checkout');
                assert(data.get('loyalty_event_id') === 'EVENT_ID', 'event missing from checkout');
                document.getElementById('pos-clear-waiver').click();
                assert(fields.hidden && !new FormData(document.getElementById('pos-checkout')).has('loyalty_participant_id'), 'clearing waiver left loyalty recipients');
            '''.replace('MEMBER_COUNT', str(count)).replace('EVENT_ID', str(event.id))
            BrowserChecks.browser(self, markup, assertions, width=390)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_individual_and_collective_waivers_fold_after_linking(self):
        for count in (1, 2):
            waiver = self.Waiver(waiver_reference=f'FOLD-{count}', responsible_first_name='Test', responsible_last_name='Customer',
                responsible_email='customer@example.com', expiry_date=datetime.utcnow()+timedelta(days=30))
            self.db.session.add(waiver); self.db.session.flush()
            for index in range(count):
                self.db.session.add(self.Participant(waiver_id=waiver.id, first_name=f'Child{index}', last_name='Customer'))
        self.db.session.commit()
        markup = self.client.get('/admin/pos?q=Test').data
        BrowserChecks.browser(self, markup, '''
            const fold = document.getElementById('pos-waiver-fold');
            const summary = document.getElementById('pos-waiver-summary');
            assert(fold.open, 'waiver search must start expanded');
            const links = [...document.querySelectorAll('button[data-waiver-id]')];
            assert(links.length === 2, 'individual and collective fixtures missing');
            for (const button of links) {
                fold.open = true; button.click();
                assert(!fold.open, 'whole waiver link did not fold away');
                assert(document.activeElement === summary, 'focus remained inside collapsed fields');
                assert(document.getElementById('pos-waiver-id').value === button.dataset.waiverId, 'waiver link lost');
                assert(!document.getElementById('pos-waiver-selection').hidden, 'linked summary missing');
                summary.click(); assert(fold.open, 'waiver search cannot reopen');
                const participant = button.closest('.pos-waiver').querySelector('select');
                participant.selectedIndex = 1; change(participant);
                assert(!fold.open, 'selected participant did not fold away');
                assert(document.getElementById('pos-participant-id').value === participant.value, 'participant link lost');
                document.getElementById('pos-clear-waiver').click();
                assert(fold.open && !document.getElementById('pos-waiver-id').value, 'clear waiver did not reopen search');
            }
        ''', width=390)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_completed_cash_clears_draft_and_keeps_change_on_till(self):
        response = self.client.post('/admin/pos/sales', data=dict(csrf_token='token', sale_token='d'*24,
            method='Cash', cash_tender='10.00', items=json.dumps([dict(name='Painting', quantity=1, price='7.50')])))
        markup = self.client.get(response.location).data
        seed = b'''<script>sessionStorage.setItem('clpaints-pos-submitted', 'dddddddddddddddddddddddd');
            sessionStorage.setItem('clpaints-pos-draft', JSON.stringify({items:[{name:'Painting', quantity:1, pence:750}]}));</script>'''
        markup = markup.replace(b'<head>', b'<head>'+seed, 1)
        BrowserChecks.browser(self, markup, '''
            assert(document.querySelector('#pos-cash-receipt').textContent.includes('2.50'), 'completed cash receipt lost change');
            assert(document.getElementById('pos-basket').children.length === 0, 'completed basket was restored');
            assert(document.getElementById('pos-cash-open').disabled, 'completed basket can be paid again');
            assert(!sessionStorage.getItem('clpaints-pos-submitted'), 'submitted marker remains');
            assert(document.getElementById('pos-library'), 'completion is not on the till');
        ''', width=390)

    def test_validation_and_staff_protection(self):
        for price in ('0', '-1', 'NaN', '1.001', '100000'):
            self.client.post('/admin/pos/library', data=dict(csrf_token='token', name='Painting', price=price))
        self.assertEqual(self.Product.query.count(), 0)
        self.assertEqual(self.client.post('/admin/pos/library', data=dict(csrf_token='bad')).status_code, 400)
        self.assertEqual(self.app.test_client().post('/admin/pos/library').status_code, 401)
        self.save()
        product = self.Product.query.one()
        self.assertEqual(self.client.post(f'/admin/pos/library/{product.id}/delete', data=dict(csrf_token='bad')).status_code, 400)
        self.assertEqual(self.Product.query.count(), 1)

    @unittest.skipUnless(EDGE.is_file(), 'Edge is not installed')
    def test_tapping_editing_removing_and_mobile_layout(self):
        self.save()
        markup = self.client.get('/admin/pos').data
        for width in (1280, 390):
            with self.subTest(width=width):
                BrowserChecks.browser(self, markup, '''
                    const product = document.querySelector('[data-product-id]');
                    const receiptOption = document.getElementById('pos-receipt-requested');
                    const receiptEmail = document.getElementById('pos-receipt-email');
                    assert(!receiptOption.checked && receiptEmail.disabled, 'email receipt was opted in automatically');
                    receiptOption.click();
                    assert(!receiptEmail.disabled && receiptEmail.required, 'email receipt input did not activate');
                    receiptEmail.value = 'customer@example.com';
                    assert(new FormData(document.getElementById('pos-checkout')).get('receipt_requested') === '1', 'receipt consent missing from sale');
                    receiptOption.click();
                    assert(!new FormData(document.getElementById('pos-checkout')).has('receipt_email'), 'opted-out email still submitted');
                    document.querySelector('.pos-library-manager').open = true;
                    const editForm = document.querySelector('.pos-management-actions form');
                    const editData = new FormData(editForm);
                    assert(editData.get('name') === 'Face painting' && editData.get('price') === '7.50', 'table fields are not associated with save form');
                    const deleteForm = document.querySelectorAll('.pos-management-actions form')[1];
                    assert(!new FormData(deleteForm).has('price'), 'remove form includes edit fields');
                    assert(document.documentElement.scrollWidth <= innerWidth, 'management table overflows phone');
                    document.querySelector('.pos-library-manager').open = false;
                    const libraryRect = document.querySelector('.pos-library').getBoundingClientRect();
                    const basketRect = document.querySelector('.pos-sale-panel').getBoundingClientRect();
                    const waiverRect = document.querySelector('.pos-waiver-panel').getBoundingClientRect();
                    if (innerWidth >= 900) {
                        assert(Math.abs(waiverRect.top - libraryRect.top) < 2, 'waiver search and library are not aligned');
                        assert(waiverRect.right <= libraryRect.left, 'waiver search must sit beside library');
                        assert(Math.abs(waiverRect.top - basketRect.top) < 2, 'basket is not anchored beside the browsing area');
                        assert(libraryRect.right <= basketRect.left, 'basket must sit beside the library');
                    } else {
                        assert(waiverRect.bottom <= libraryRect.top, 'waiver search must sit above library on phone');
                        assert(!document.getElementById('pos-mobile-basket-toggle').hidden, 'phone basket tab missing');
                        assert(document.querySelector('.pos-sale-panel').hidden, 'phone basket should start tucked away');
                    }
                    product.click(); product.click();
                    const basket = document.getElementById('pos-basket');
                    assert(basket.children.length === 1, 'repeated tap created duplicate lines');
                    assert(basket.querySelector('input').value === '2', 'repeated tap did not increase quantity');
                    const price = basket.querySelectorAll('input')[1]; price.value = '6.25'; change(price);
                    assert(document.getElementById('pos-total').textContent.includes('12.50'), 'price adjustment total wrong');
                    assert(product.dataset.productPrice === '7.50', 'basket adjustment changed saved price');
                    const quantity = basket.querySelector('input'); quantity.value = '3'; change(quantity);
                    assert(document.getElementById('pos-total').textContent.includes('18.75'), 'quantity total wrong');
                    document.getElementById('pos-cash-open').click();
                    const tender = document.getElementById('pos-cash-tender');
                    assert(!document.getElementById('pos-cash-panel').hidden && document.activeElement === tender, 'cash panel did not open inline');
                    tender.value = '10.00'; tender.dispatchEvent(new Event('input'));
                    assert(document.getElementById('pos-cash-confirm').disabled, 'underpaid cash can complete');
                    assert(document.getElementById('pos-cash-change').textContent.includes('8.75'), 'shortfall incorrect');
                    tender.value = '20.00'; tender.dispatchEvent(new Event('input'));
                    assert(!document.getElementById('pos-cash-confirm').disabled, 'valid cash cannot complete');
                    assert(document.getElementById('pos-cash-change').textContent.includes('1.25'), 'change incorrect');
                    const cashData = new FormData(document.getElementById('pos-checkout'));
                    assert(cashData.get('cash_tender') === '20.00', 'cash tender missing from checkout');
                    document.getElementById('pos-cash-cancel').click();
                    assert(document.getElementById('pos-cash-panel').hidden && tender.disabled, 'cash cancel failed');
                    const items = JSON.parse(document.getElementById('pos-items').value);
                    assert(items[0].price === '6.25' && items[0].quantity === 3, 'checkout values wrong');
                    basket.querySelector('button').click();
                    assert(basket.children.length === 0, 'remove failed');
                    assert(document.querySelector('#pos-checkout button').disabled, 'empty checkout enabled');
                    assert(document.getElementById('pos-clear-basket').disabled, 'empty basket clear button enabled');
                    product.click();
                    document.getElementById('pos-item-name').value = 'Custom item';
                    document.getElementById('pos-item-price').value = '2.50';
                    document.getElementById('pos-add-item').requestSubmit();
                    assert(basket.children.length === 2, 'multiple basket lines missing');
                    document.getElementById('pos-clear-basket').click();
                    assert(basket.children.length === 0, 'clear all left basket lines');
                    assert(document.getElementById('pos-items').value === '[]', 'clear all left checkout items');
                    assert(document.getElementById('pos-total').textContent.includes('0.00'), 'clear all left total');
                    assert(document.querySelector('#pos-checkout button').disabled, 'clear all left checkout enabled');
                    assert(JSON.parse(sessionStorage.getItem('clpaints-pos-draft')).items.length === 0, 'clear all left saved draft items');
                    const search = document.getElementById('pos-library-search'); search.value='missing'; search.dispatchEvent(new Event('input'));
                    assert(product.hidden, 'library search failed');
                    assert(document.documentElement.scrollWidth <= innerWidth, 'till overflows screen');
                ''', width=width)


if __name__ == '__main__':
    unittest.main()
