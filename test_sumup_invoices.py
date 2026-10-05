from decimal import Decimal
import unittest
import test_loyalty as fixtures

main = fixtures.main


class SumUpInvoicesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.booking = self.fixture.fixture.booking(self.fixture.account.email, total_event_cost=Decimal('100'))
        self.path = f'/admin/bookings/{self.booking.id}/invoices'
        self.fixture.admin.get(self.path)
        with self.fixture.admin.session_transaction() as session:
            self.token = session['client_csrf']
        self.data = dict(csrf_token=self.token, reference='INV-101', purpose='Deposit',
                         amount='50.00', due_date='2026-10-10', payment_url='https://pay.sumup.com/example')

    def tearDown(self):
        self.fixture.tearDown()

    def test_attach_visibility_duplicate_and_no_payment(self):
        self.assertEqual(self.fixture.admin.post(self.path, data=self.data).status_code, 302)
        self.assertEqual(main.BookingInvoice.query.count(), 1)
        self.assertIn(b'INV-101', self.fixture.client.get(f'/client/bookings/{self.booking.id}').data)
        self.assertIn(b'INV-101', self.fixture.admin.get(f'/admin/bookings/{self.booking.id}/payments').data)
        self.fixture.admin.post(self.path, data=self.data)
        self.assertEqual(main.BookingInvoice.query.count(), 1)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'], Decimal('0'))
        other = self.fixture.fixture.booking('another@example.com')
        self.assertNotIn(b'INV-101', self.fixture.client.get(f'/client/bookings/{other.id}').data)

    def test_security_and_validation(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        self.assertEqual(self.fixture.client.post(self.path, data=self.data).status_code, 302)
        self.assertEqual(self.fixture.admin.post(self.path, data=dict(self.data, csrf_token='bad')).status_code, 400)
        for bad in ['https://sumup.com.evil.test/pay', 'javascript:alert(1)', 'https://sumup.com@evil.test',
                    'http://pay.sumup.com/pay', 'https://pay.sumup.com:444/pay']:
            self.fixture.admin.post(self.path, data=dict(self.data, payment_url=bad))
        for bad in ['NaN', '-1', '0', '1.001']:
            self.fixture.admin.post(self.path, data=dict(self.data, amount=bad))
        self.assertEqual(main.BookingInvoice.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
