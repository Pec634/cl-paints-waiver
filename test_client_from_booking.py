from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

import test_business_tools as fixtures

main = fixtures.main
Entry = main.tool_models[1]


class ClientFromBookingTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.email = 'historic@example.com'
        self.booking.client_address = 'Customer billing address'
        self.booking.event_address = 'Different event venue'
        self.booking.total_event_cost = Decimal('70')
        self.booking.travel_charge = Decimal('0')
        main.db.session.add(Entry(booking_id=self.booking.id, token='original-historical-payment',
            amount=Decimal('70'), kind='payment', method='SumUp', note='Previously paid', paid_date=date(2026, 10, 27)))
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.path = f'/admin/bookings/{self.booking.id}/client'
        self.admin.get(self.path)
        with self.admin.session_transaction() as state:
            self.csrf = state['client_csrf']

    def tearDown(self):
        self.fixture.tearDown()

    def test_create_copies_contact_details_and_preserves_recorded_payment(self):
        before = main.app.extensions['payment_summary'](self.booking)
        original_status = self.booking.status
        with patch.object(main, 'send_client_email') as send:
            response = self.admin.post(self.path, data=dict(csrf_token=self.csrf))
            send.assert_not_called()
        self.assertEqual(response.status_code, 302)
        account = main.ClientAccount.query.filter_by(email='historic@example.com').one()
        self.assertEqual(account.first_name, self.booking.first_name)
        self.assertEqual(account.phone, self.booking.phone)
        self.assertEqual(account.address, 'Customer billing address')
        self.assertNotEqual(account.address, self.booking.event_address)
        after = main.app.extensions['payment_summary'](self.booking)
        for key in ('total', 'paid', 'outstanding'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(Entry.query.count(), 1)
        self.assertEqual(Entry.query.one().paid_date, date(2026, 10, 27))
        self.assertEqual(self.booking.status, original_status)
        page = self.admin.get(response.location)
        self.assertIn(self.booking.public_reference.encode(), page.data)
        self.assertIn(b'70.00', page.data)
        self.assertIn(b'invoice_document', page.data)
        with self.admin.session_transaction() as state:
            self.assertNotIn('client_id', state, 'Creating a profile must not sign the admin in as the client')

    def test_repeat_and_existing_email_reuse_profile_without_overwriting(self):
        self.admin.post(self.path, data=dict(csrf_token=self.csrf))
        account = main.ClientAccount.query.filter_by(email='historic@example.com').one()
        count = main.ClientAccount.query.count()
        account.first_name = 'Existing profile name'
        self.booking.email = ' Historic@Example.com '
        main.db.session.commit()
        for method in (self.admin.get, lambda path: self.admin.post(path, data=dict(csrf_token=self.csrf, first_name='Overwrite'))):
            response = method(self.path)
            self.assertIn(f'/admin/clients/{account.id}', response.location)
        self.assertEqual(main.ClientAccount.query.count(), count)
        self.assertEqual(account.first_name, 'Existing profile name')

    def test_authorization_validation_and_fixed_booking_email(self):
        self.assertEqual(self.fixture.client.get(self.path).status_code, 302)
        self.assertEqual(main.app.test_client().post(self.path).status_code, 302)
        self.assertEqual(self.admin.post(self.path, data=dict(csrf_token='bad')).status_code, 400)
        response = self.admin.post(self.path, data=dict(csrf_token=self.csrf, first_name=''))
        self.assertIn(b'Enter a first name', response.data)
        self.assertIsNone(main.ClientAccount.query.filter_by(email='historic@example.com').first())
        self.admin.post(self.path, data=dict(csrf_token=self.csrf, email='unrelated@example.com'))
        self.assertIsNotNone(main.ClientAccount.query.filter_by(email='historic@example.com').first())
        self.assertIsNone(main.ClientAccount.query.filter_by(email='unrelated@example.com').first())

    def test_booking_pages_offer_create_then_existing_profile(self):
        paths = ['/admin/bookings?filter=all', f'/admin/bookings/{self.booking.id}/payments',
                 f'/admin/bookings/{self.booking.id}/activity']
        for path in paths:
            self.assertIn(b'Create client from booking', self.admin.get(path).data)
        self.admin.post(self.path, data=dict(csrf_token=self.csrf))
        for path in paths:
            self.assertIn(b'Client profile &amp; invoice uploads', self.admin.get(path).data)
            if path != paths[0]:
                self.assertNotIn(b'Create client from booking', self.admin.get(path).data)

    def test_submenu_booking_picker_search_and_existing_profile_filter(self):
        picker = '/admin/bookings/create-client'
        self.assertEqual(self.fixture.client.get(picker).status_code, 302)
        page = self.admin.get(picker)
        self.assertIn(self.path.encode(), page.data)
        self.assertIn('no-store', page.headers['Cache-Control'])
        self.assertNotIn(self.path.encode(), self.admin.get(picker+'?q=nonexistent-customer').data)
        self.assertIn(self.path.encode(), self.admin.get(picker+'?q=historic@example.com').data)
        self.admin.post(self.path, data=dict(csrf_token=self.csrf))
        self.assertNotIn(self.path.encode(), self.admin.get(picker).data)
