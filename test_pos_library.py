"""Isolated till tests, independent of the rest of the portal's integrations."""
import json
import os
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, abort, session
from flask_sqlalchemy import SQLAlchemy
from jinja2 import ChoiceLoader, DictLoader
import pos
from test_admin_polish_browser import BrowserChecks, EDGE
from pos_loyalty import PosLoyalty
from loyalty import define_models as define_loyalty_models


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
        class ClientAccount(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            email = self.db.Column(self.db.String(255), unique=True)
            first_name = self.db.Column(self.db.String(100))
            last_name = self.db.Column(self.db.String(100))
        class MoodboardImage(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
        self.Waiver, self.Participant = Waiver, Participant
        self.Event, self.Account = Event, ClientAccount
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
        pos.register(self.app, self.db, self.Sale, Waiver, Participant, staff_only, self.Product, self.mail, self.loyalty)
        self.app.add_url_rule('/admin/waivers/<int:waiver_id>', 'admin_waiver_detail', lambda waiver_id: 'Waiver')
        self.context = self.app.app_context()
        self.context.push()
        self.db.create_all()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state.update(staff=True, client_csrf='token')

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.context.pop()

    def save(self, **values):
        return self.client.post('/admin/pos/library', data=dict(csrf_token='token', name='Face painting', price='7.50', **values))

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
                    assert(waiverRect.bottom <= libraryRect.top, 'waiver search must sit above the till');
                    if (innerWidth > 1000) {
                        assert(Math.abs(libraryRect.top - basketRect.top) < 2, 'library and basket are not aligned');
                        assert(libraryRect.right <= basketRect.left, 'basket must sit beside the library');
                    } else {
                        assert(libraryRect.bottom <= basketRect.top, 'basket must follow library on phone');
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
