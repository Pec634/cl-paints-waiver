import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import test_loyalty as fixtures
from pos import parse_items

main = fixtures.main


class PosTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.env = patch.dict(os.environ, SUMUP_API_KEY='test-key', SUMUP_MERCHANT_CODE='MERCHANT',
                              SUMUP_POS_AFFILIATE_KEY='affiliate')
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.fixture.tearDown()

    def create(self, method='Cash', **extra):
        data = dict(csrf_token='admin-token', sale_token='a' * 24, method=method,
            cash_tender='20.00',
            items=json.dumps([dict(name='Face painting', quantity=2, price='7.50')]))
        data.update(extra)
        return self.admin.post('/admin/pos/sales', data=data)

    def test_search_is_staff_only_and_covers_participant_adult_email_reference(self):
        self.assertEqual(main.app.test_client().get('/admin/pos?q=Alex').status_code, 302)
        for query in ['Alex', 'Test Client', self.fixture.account.email, 'SOURCE']:
            page = self.admin.get('/admin/pos', query_string={'q':query})
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Link to sale', page.data)
            self.assertNotIn(b'Original signature', page.data)
            self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertNotIn(b'Link to sale', self.admin.get('/admin/pos?q=%25').data)
        self.fixture.waiver.expiry_date = datetime.utcnow() - timedelta(days=2)
        main.db.session.commit()
        page = self.admin.get('/admin/pos?q=Alex')
        self.assertIn(b'Expired', page.data)
        self.assertNotIn(b'Link to sale', page.data)
        self.fixture.waiver.is_archived = True
        main.db.session.commit()
        self.assertNotIn(b'SOURCE', self.admin.get('/admin/pos?q=Alex').data)

    def test_cash_totals_idempotency_csrf_and_consent_history(self):
        self.assertEqual(self.create(csrf_token='bad').status_code, 400)
        result = self.create(waiver_id=str(self.fixture.waiver.id))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.admin.get(result.location).status_code, 200)
        self.create()
        sale = main.PosSale.query.one()
        self.assertEqual(str(sale.amount), '15.00')
        self.assertEqual(sale.status, 'Paid')
        self.assertEqual(sale.waiver_id, self.fixture.waiver.id)
        self.assertEqual(self.admin.post(f'/admin/waivers/{sale.waiver_id}/delete').status_code, 409)

    def test_invalid_prices_and_waiver_are_rejected(self):
        for price in ['NaN', 'Infinity', '-1', '0', '1.001', '100000']:
            with self.assertRaises(ValueError):
                parse_items(json.dumps([dict(name='Test', quantity=1, price=price)]))
        for quantity in ['1.2', 0, 1000]:
            with self.assertRaises(ValueError):
                parse_items(json.dumps([dict(name='Test', quantity=quantity, price='1.00')]))
        self.fixture.waiver.expiry_date = datetime.utcnow() - timedelta(days=2)
        main.db.session.commit()
        self.create(waiver_id=str(self.fixture.waiver.id))
        self.assertEqual(main.PosSale.query.count(), 0)

    def test_card_launch_once_verify_exact_provider_payment(self):
        self.create('Card')
        sale = main.PosSale.query.one()
        start = f'/admin/pos/sales/{sale.id}/start'
        verify = f'/admin/pos/sales/{sale.id}/verify'
        self.assertEqual(self.admin.post(verify, data={'csrf_token':'admin-token'}).status_code, 409)
        response = self.admin.post(start, data={'csrf_token':'admin-token'})
        self.assertIn(b'sumupmerchant://pay/1.0?', response.data)
        self.assertNotIn(b'test-key', response.data)
        self.assertEqual(self.admin.post(start, data={'csrf_token':'admin-token'}).status_code, 302)
        self.assertEqual(sale.status, 'Awaiting verification')
        good = dict(status='SUCCESSFUL', currency='GBP', amount=15,
            foreign_transaction_id=sale.reference, transaction_code='TX123')
        for changes in [dict(status='FAILED'), dict(currency='EUR'), dict(amount=1), dict(foreign_transaction_id='wrong')]:
            with patch('pos.reader_transaction', return_value={**good, **changes}):
                self.admin.post(verify, data={'csrf_token':'admin-token'})
            self.assertEqual(sale.status, 'Awaiting verification')
        with patch('pos.reader_transaction', return_value=good) as provider:
            self.admin.post(verify, data={'csrf_token':'admin-token'})
            self.admin.post(verify, data={'csrf_token':'admin-token'})
        provider.assert_called_once_with('MERCHANT', sale.reference)
        self.assertEqual(sale.status, 'Paid')
        self.assertEqual(sale.transaction_code, 'TX123')

    def test_missing_configuration_does_not_create_card_sale(self):
        with patch.dict(os.environ, SUMUP_POS_AFFILIATE_KEY=''):
            self.create('Card')
        self.assertEqual(main.PosSale.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
