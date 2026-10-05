import unittest
from unittest.mock import patch
import test_client_portal as portal_tests
from client_notifications import EMAIL_DEFAULTS
main = portal_tests.main
Change, Notice = main.notification_models

class NotificationsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = portal_tests.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.account = self.fixture.signup()
        self.booking = self.fixture.booking(self.account.email)
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True

    def tearDown(self):
        self.fixture.tearDown()

    def update(self, **fields):
        data = dict(action='update', travel_miles_0='35', internal_notes='PRIVATE ADMIN NOTES')
        data.update(fields)
        return self.admin.post(f'/admin/bookings/{self.booking.id}/manage', data=data)

    def test_travel_update_email_highlights_and_acknowledgement(self):
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.update()
            self.assertEqual(response.status_code, 302)
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0], self.account.email)
            self.assertIn('Travel charge', send.call_args.args[2])
            self.assertIn('£25.00', send.call_args.args[2])
            self.assertNotIn('PRIVATE ADMIN', send.call_args.args[2])
            self.assertIn('<h1', send.call_args.args[3])
            self.update()
            send.assert_called_once()
        self.assertEqual(Change.query.count(), 1)
        detail = self.client.get(f'/client/bookings/{self.booking.id}')
        self.assertIn(b'Your booking has been updated', detail.data)
        self.assertIn(b'client-field-updated', detail.data)
        change = Change.query.one()
        target = f'/client/bookings/{self.booking.id}/acknowledge-updates'
        self.assertEqual(self.client.post(target, data={}).status_code, 400)
        self.client.post(target, data={'csrf_token':self.fixture.csrf(), 'change_id':change.id})
        self.assertNotIn(b'Your booking has been updated', self.client.get(f'/client/bookings/{self.booking.id}').data)
        self.assertIsNotNone(Change.query.one().acknowledged_at)

    def test_status_updates_and_failed_email_preserve_booking(self):
        with patch.object(main, 'send_client_email', return_value=False):
            response = self.update(action='accept')
        self.assertIn('status_email=failed', response.location)
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertFalse(Notice.query.one().email_sent)
        self.assertIn('Status', Change.query.one().changes)
        self.assertIn(b'Confirmed', self.client.get(f'/client/bookings/{self.booking.id}').data)
        self.update(action='decline')
        self.assertIn(b'Unable to confirm', self.client.get(f'/client/bookings/{self.booking.id}').data)
        self.assertEqual(Notice.query.count(), 2)

    def test_internal_notes_only_do_not_notify(self):
        self.update(travel_miles_0='0')
        self.assertEqual(Change.query.count(), 0)
        self.assertEqual(Notice.query.count(), 0)

    def test_custom_email_templates_and_unsafe_placeholder_rejected(self):
        self.admin.get('/admin/settings')
        with self.admin.session_transaction() as session:
            token = session['settings_csrf']
        values = dict(EMAIL_DEFAULTS, notification_booking_subject='Hello {name}: {reference}',
                      notification_heading='Your colourful update', notification_colour='#71429d', notification_layout='simple')
        response = self.admin.post('/admin/settings', data=dict(values, section='notifications', csrf_token=token))
        self.assertEqual(response.status_code, 302)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.update()
        self.assertTrue(send.call_args.args[1].startswith('Hello Test:'))
        self.assertIn('Your colourful update', send.call_args.args[3])
        self.assertIn('#71429d', send.call_args.args[3])
        self.assertNotIn('border-top:', send.call_args.args[3])
        self.admin.post('/admin/settings', data=dict(values, notification_booking_subject='{name.__class__}', section='notifications', csrf_token=token))
        self.assertEqual(main.get_business_settings()['notification_booking_subject'], values['notification_booking_subject'])

    def test_referral_link_earned_and_redeemed_notifications(self):
        import rewards
        rewards.execute("INSERT INTO referrals(customer_name,code,original_event_date,expires_date,status) VALUES ('Test','AB123','2026-01-01','2027-01-01','active')")
        self.admin.get('/admin/clients')
        with self.admin.session_transaction() as session:
            token = session['client_csrf']
        self.admin.post('/admin/clients', data={'csrf_token':token,'client_id':self.account.id,'code':'AB123'})
        self.assertEqual(Notice.query.count(), 1)
        record = rewards.fetch_one("SELECT id FROM referrals WHERE code='AB123'")
        with main.app.test_request_context('/admin/rewards/'):
            rewards.execute("UPDATE referrals SET status='earned' WHERE id=:id", {'id':record['id']})
            rewards.execute("UPDATE referrals SET status='earned' WHERE id=:id", {'id':record['id']})
            rewards.execute("UPDATE referrals SET status='redeemed' WHERE id=:id", {'id':record['id']})
        self.assertEqual(Notice.query.count(), 3)
        self.assertIn(b'AB123', self.client.get('/client/').data)

if __name__ == '__main__':
    unittest.main()
