from datetime import date, datetime, timedelta
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

    def test_full_invoice_difference_uses_latest_attachment_and_includes_travel(self):
        admin = self.fixture.admin
        self.assertEqual(admin.post(self.path, data=dict(self.data, purpose='Full payment', amount='100.00')).status_code, 302)
        payments = f'/admin/bookings/{self.booking.id}/payments'
        heading = b'Review SumUp invoice amounts before requesting payment'
        self.assertNotIn(heading, admin.get(payments).data)

        self.booking.travel_charge = Decimal('20')
        main.db.session.commit()
        page = admin.get(payments).data
        self.assertIn(heading, page)
        self.assertIn('Full payment invoice INV-101 · Linked amount £100.00'.encode(), page)
        self.assertIn('Current booking total £120.00, £20.00 higher'.encode(), page)
        self.assertIn(heading, admin.get(self.path).data)
        overview = admin.get('/admin/payments?filter=invoice_mismatch').data
        self.assertIn(b'SumUp invoice amount to review', overview)
        self.assertIn(self.booking.public_reference.encode(), overview)
        self.assertNotIn(heading, self.fixture.client.get(f'/client/bookings/{self.booking.id}').data)

        self.assertEqual(admin.post(self.path, data=dict(
            self.data, reference='INV-102', purpose='Full payment', amount='120.00')).status_code, 302)
        self.assertNotIn(heading, admin.get(payments).data)
        self.assertEqual(main.BookingInvoice.query.count(), 2)
        self.assertNotIn(self.booking.public_reference.encode(), admin.get('/admin/payments?filter=invoice_mismatch').data)

    def test_deposit_invoice_compared_with_payment_schedule_only(self):
        admin = self.fixture.admin
        self.assertEqual(admin.post(self.path, data=self.data).status_code, 302)
        payments = f'/admin/bookings/{self.booking.id}/payments'
        self.assertNotIn(b'Review SumUp invoice amounts', admin.get(payments).data)

        Plan = main.tool_models[0]
        plan = Plan(booking_id=self.booking.id, deposit=Decimal('50'))
        main.db.session.add(plan)
        main.db.session.commit()
        self.booking.total_event_cost = Decimal('120')
        main.db.session.commit()
        self.assertNotIn(b'Review SumUp invoice amounts', admin.get(payments).data)

        plan.deposit = Decimal('35')
        main.db.session.commit()
        page = admin.get(payments).data
        self.assertIn('Deposit invoice INV-101 · Linked amount £50.00'.encode(), page)
        self.assertIn('Current scheduled deposit £35.00, £15.00 lower'.encode(), page)

    def test_balance_invoice_ignores_payment_after_attachment(self):
        admin = self.fixture.admin
        payments = f'/admin/bookings/{self.booking.id}/payments'
        Entry = main.tool_models[1]

        def record(amount, token, when):
            main.db.session.add(Entry(booking_id=self.booking.id, token=token, amount=Decimal(amount),
                kind='payment', method='Cash', paid_date=date.today(), recorded_at=when))
            main.db.session.commit()

        record('30', 'balance-deposit', datetime.utcnow() - timedelta(hours=1))
        self.assertEqual(admin.post(self.path, data=dict(self.data, purpose='Balance', amount='70.00')).status_code, 302)
        record('70', 'balance-settlement', datetime.utcnow() + timedelta(minutes=1))
        self.assertNotIn(b'Review SumUp invoice amounts', admin.get(payments).data)

        self.booking.total_event_cost = Decimal('95')
        main.db.session.commit()
        page = admin.get(payments).data
        self.assertIn('Balance invoice INV-101 · Linked amount £70.00'.encode(), page)
        self.assertIn('Current total less net payments recorded before attachment £65.00, £5.00 lower'.encode(), page)
        self.assertIn(self.booking.public_reference.encode(), admin.get('/admin/payments?filter=invoice_mismatch').data)

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
