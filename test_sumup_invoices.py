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

    def test_saved_links_appear_in_booking_calendar_and_activity_details(self):
        self.fixture.admin.post(self.path, data=self.data)
        self.booking.status = 'Accepted'
        main.db.session.commit()
        for path in ('/admin/bookings?filter=all', '/admin/calendar?month='+self.booking.event_date.strftime('%Y-%m'),
                     f'/admin/bookings/{self.booking.id}/activity'):
            page = self.fixture.admin.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(b'No SumUp invoice links attached.', page.data)
            self.assertIn(b'https://pay.sumup.com/example', page.data)
            self.assertIn(b'View invoice in SumUp', page.data)
            self.assertNotIn(b'Your invoices are issued through SumUp.', page.data)

    def test_pdf_is_acknowledged_without_inventing_payment_matching_metadata(self):
        from io import BytesIO
        account = self.fixture.account
        path = f'/admin/clients/{account.id}/invoice-documents'
        self.fixture.admin.get(f'/admin/clients/{account.id}')
        with self.fixture.admin.session_transaction() as state:
            csrf = state['client_csrf']
        self.fixture.admin.post(path, data=dict(csrf_token=csrf, booking_id=str(self.booking.id),
            invoice_document=(BytesIO(b'%PDF-1.4\ninvoice'), 'Invoice_2026-016.pdf')))
        for path in ('/admin/bookings?filter=all', f'/admin/bookings/{self.booking.id}/payments',
                     f'/admin/bookings/{self.booking.id}/activity'):
            page = self.fixture.admin.get(path)
            self.assertIn(b'Invoice document attached', page.data)
            self.assertIn(b'Invoice_2026-016.pdf', page.data)
            self.assertIn(b'Link SumUp invoice for payment checks', page.data)
            self.assertNotIn(b'No SumUp invoice', page.data)
        page = self.fixture.client.get(f'/client/bookings/{self.booking.id}')
        self.assertIn(b'Invoice document attached', page.data)
        self.assertNotIn(b'Link SumUp invoice for payment checks', page.data)
        self.assertEqual(main.BookingInvoice.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
