import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import test_client_portal as fixtures
from client_features import calendar_text
main = fixtures.main


class ClientFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.account = self.fixture.signup()
        self.client = self.fixture.client

    def tearDown(self):
        self.fixture.tearDown()

    def test_dashboard_and_booking_tools_use_owned_data(self):
        booking = self.fixture.booking(self.account.email, status='Accepted')
        other = self.fixture.booking('other@example.com', status='Accepted', event_type='PRIVATE OTHER EVENT')
        invoice = main.BookingInvoice(booking_id=booking.id, reference='FEATURE-INVOICE', purpose='Deposit',
            amount=Decimal('25'), due_date=date(2099, 1, 1), payment_url='https://pay.sumup.com/test')
        main.db.session.add(invoice)
        main.db.session.commit()
        page = self.client.get('/client/')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b'<h2>Your booking checklist</h2>'), 1)
        self.assertIn(b'FEATURE-INVOICE', page.data)
        self.assertIn(b'Add to calendar', page.data)
        self.assertNotIn(b'PRIVATE OTHER EVENT', page.data)
        self.assertEqual(self.client.get(f'/client/bookings/{booking.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/client/bookings/{other.id}/calendar/0').status_code, 404)
        self.assertEqual(self.client.get(f'/client/bookings/{booking.id}/calendar/999').status_code, 404)
        calendar = self.client.get(f'/client/bookings/{booking.id}/calendar/0')
        self.assertEqual(calendar.status_code, 200)
        self.assertIn(b'BEGIN:VEVENT', calendar.data)
        self.assertIn('no-store', calendar.headers['Cache-Control'])
        booking.status = 'Cancelled'
        main.db.session.commit()
        self.assertEqual(self.client.get(f'/client/bookings/{booking.id}/calendar/0').status_code, 404)

    def test_preferences_apply_to_email_but_preserve_portal_updates(self):
        self.assertEqual(self.client.post('/client/preferences', data={}).status_code, 400)
        self.assertEqual(self.client.post('/client/preferences', data={'csrf_token': self.fixture.csrf()}).status_code, 302)
        saved = main.db.session.get(main.ClientEmailPreference, self.account.id)
        self.assertFalse(saved.booking_updates)
        self.assertFalse(saved.reward_updates)
        with main.app.test_request_context('/'), patch.object(main, 'send_client_email', return_value=True) as send:
            main.app.extensions['client_reward_notice'](self.account.email, self.account.first_name, 'TEST', 'Reward update')
            send.assert_not_called()
        self.assertIn(b'Reward update', self.client.get('/client/').data)
        self.client.post('/client/preferences', data={'csrf_token': self.fixture.csrf(), 'reward_updates': 'yes'})
        with main.app.test_request_context('/'), patch.object(main, 'send_client_email', return_value=True) as send:
            main.app.extensions['client_reward_notice'](self.account.email, self.account.first_name, 'TEST2', 'Another update')
            send.assert_called_once()
        self.assertEqual(self.client.get('/client/help').status_code, 200)
        self.client.post('/client/logout', data={'csrf_token': self.fixture.csrf()})
        for path in ('/client/help', '/client/preferences'):
            self.assertEqual(self.client.get(path).status_code, 302)

    def test_calendar_handles_uk_summer_time_overnight_and_escaping(self):
        booking = SimpleNamespace(id=1, public_reference='BOOK-1')
        event = dict(date='2027-07-01', start_time='23:30', finish_time='00:30',
                     event_type='Party, fun', event_address='Venue\nBEGIN:BAD;' + 'é' * 80)
        result = calendar_text(booking, event, 0)
        self.assertIn('DTSTART:20270701T223000Z', result)
        self.assertIn('DTEND:20270701T233000Z', result)
        self.assertIn('SUMMARY:CL Paints: Party\\, fun', result)
        self.assertNotIn('\r\nBEGIN:BAD', result)
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in result.split('\r\n')))


if __name__ == '__main__':
    unittest.main()
