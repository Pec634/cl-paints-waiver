import unittest
from unittest.mock import patch
import test_loyalty as fixtures

main = fixtures.main


class BookingRequestsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.booking = self.fixture.fixture.booking(self.fixture.account.email, status='Accepted')
        self.path = f'/client/bookings/{self.booking.id}/request'
        self.data = dict(csrf_token=self.fixture.fixture.csrf(), kind='cancellation', details='Please cancel my party.')

    def tearDown(self):
        self.fixture.tearDown()

    def test_pending_cancellation_approval_notifications_and_duplicate(self):
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.assertEqual(self.fixture.client.post(self.path, data=self.data).status_code, 302)
            self.assertEqual(send.call_args.args[0], main.get_business_settings()['contact_email'])
        self.assertEqual(self.booking.status, 'Accepted')
        self.fixture.client.post(self.path, data=self.data)
        self.assertEqual(main.BookingRequest.query.count(), 1)
        item = main.BookingRequest.query.one()
        self.assertEqual(main.ClientEnquiry.query.count(), 1)
        self.assertIn(b'cancellation request', self.fixture.admin.get('/admin/bookings').data.lower())
        route = f'/admin/booking-requests/{item.id}'
        self.assertEqual(self.fixture.client.get(route).status_code, 302)
        self.assertEqual(self.fixture.admin.get(route).status_code, 200)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.fixture.admin.post(route, data=dict(csrf_token='admin-token', action='complete', response='Cancellation agreed. No payment was taken.'))
            self.assertTrue(any(call.args[0] == self.booking.email for call in send.call_args_list))
        self.assertEqual(self.booking.status, 'Cancelled')
        self.assertEqual(item.status, 'Completed')
        self.assertIsNone(item.pending_key)
        self.assertFalse(any(row['booking'] and row['booking'].id == self.booking.id for row in main.app.extensions['calendar_rows']()))
        self.assertIn(b'Cancellation agreed', self.fixture.client.get(f'/client/bookings/{self.booking.id}').data)

    def test_owner_csrf_decline_and_no_automatic_changes(self):
        self.assertEqual(self.fixture.client.post(self.path, data=dict(self.data, csrf_token='bad')).status_code, 400)
        other = self.fixture.fixture.booking('other@example.com')
        self.assertEqual(self.fixture.client.post(f'/client/bookings/{other.id}/request', data=self.data).status_code, 404)
        self.fixture.client.post(self.path, data=dict(self.data, kind='change', details='Please change the venue.'))
        item = main.BookingRequest.query.one()
        self.fixture.admin.post(f'/admin/booking-requests/{item.id}', data=dict(csrf_token='admin-token', action='decline', response='The original venue remains agreed.'))
        self.assertEqual(item.status, 'Declined')
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertEqual(self.booking.event_address, 'Test venue')

    def test_social_links_and_safe_settings(self):
        page = self.fixture.client.get('/client/').data
        self.assertIn(b'https://www.instagram.com/cl.paints_/', page)
        self.assertIn(b'https://uk.trustpilot.com/review/clpaints.com', page)
        self.assertIn(b'61578784131483', page)
        self.fixture.admin.get('/admin/settings')
        with self.fixture.admin.session_transaction() as session: token = session['settings_csrf']
        self.fixture.admin.post('/admin/settings', data=dict(csrf_token=token, section='social',
            facebook_url='javascript:alert(1)', instagram_url='', trustpilot_url=''))
        self.assertTrue(main.get_business_settings()['facebook_url'].startswith('https://'))
        self.fixture.admin.post('/admin/settings', data=dict(csrf_token=token, section='social',
            facebook_url='', instagram_url='', trustpilot_url=''))
        self.assertNotIn(b'cl.paints_/', self.fixture.client.get('/client/').data)


if __name__ == '__main__': unittest.main()
