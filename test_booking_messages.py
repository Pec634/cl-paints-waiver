import re
import unittest
from datetime import date, timedelta
from decimal import Decimal

import test_loyalty as fixtures

main = fixtures.main


class BookingMessagesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = self.fixture.admin
        self.booking = self.fixture.fixture.booking(self.fixture.account.email, status='Accepted', total_event_cost=Decimal('100'))
        self.client_path = f'/client/bookings/{self.booking.id}/messages'
        self.admin_path = f'/admin/bookings/{self.booking.id}/messages'

    def tearDown(self):
        self.fixture.tearDown()

    def data(self, client, path, body='Please confirm the venue.'):
        page = client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn('no-store', page.headers['Cache-Control'])
        return dict(body=body, csrf_token=re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode(),
                    message_token=re.search(rb'name="message_token" value="([^"]+)"', page.data)[1].decode())

    def test_conversation_unread_replies_and_duplicate_send(self):
        data = self.data(self.client, self.client_path, '<script>alert(1)</script>\nVenue question')
        for _ in range(2):
            self.assertEqual(self.client.post(self.client_path, data=data).status_code, 302)
        self.assertEqual(main.BookingMessage.query.count(), 1)
        message = main.BookingMessage.query.one()
        self.assertIsNone(message.read_at)
        admin_dashboard = self.admin.get('/admin/dashboard').data
        self.assertIn(b'1 unread booking message', admin_dashboard)
        self.assertIn(self.admin_path.encode(), admin_dashboard)
        self.assertIsNone(message.read_at)  # Dashboard previews do not mark conversations read.
        page = self.admin.get(self.admin_path)
        self.assertNotIn(b'<script>alert(1)</script>', page.data)
        self.assertIn(b'&lt;script&gt;alert(1)&lt;/script&gt;', page.data)
        self.assertIsNotNone(message.read_at)
        self.assertNotIn(b'1 unread booking message', self.admin.get('/admin/dashboard').data)
        self.admin.post(self.admin_path, data=self.data(self.admin, self.admin_path, 'The original venue is confirmed.'))
        self.assertIn(b'1 unread booking message', self.client.get('/client/').data)
        self.assertIn(b'1 unread', self.client.get(f'/client/bookings/{self.booking.id}').data)
        page = self.client.get(self.client_path)
        self.assertIn(b'The original venue is confirmed.', page.data)
        self.assertNotIn(b'1 unread booking message', self.client.get('/client/').data)
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertEqual(self.booking.event_address, 'Test venue')

    def test_ownership_csrf_token_scope_and_validation(self):
        other = self.fixture.fixture.booking('private@example.com')
        other_path = f'/client/bookings/{other.id}/messages'
        data = self.data(self.client, self.client_path)
        self.assertEqual(self.client.get(other_path).status_code, 404)
        self.assertEqual(self.client.post(other_path, data=data).status_code, 404)
        self.assertEqual(self.client.get(self.admin_path).status_code, 302)
        self.assertEqual(self.client.post(self.client_path, data=dict(data, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.client.post(self.client_path, data=dict(data, message_token='bad')).status_code, 400)
        admin_data = self.data(self.admin, self.admin_path)
        self.assertEqual(self.admin.post(f'/admin/bookings/{other.id}/messages', data=admin_data).status_code, 400)
        self.assertEqual(self.admin.post(self.admin_path, data=dict(admin_data, csrf_token='bad')).status_code, 400)
        for body in (' ', 'a' * 4001):
            self.assertEqual(self.client.post(self.client_path, data=dict(data, body=body)).status_code, 200)
        self.assertEqual(main.BookingMessage.query.count(), 0)
        self.client.post('/client/logout', data={'csrf_token': data['csrf_token']})
        self.assertEqual(self.client.get(self.client_path).status_code, 302)
        self.assertEqual(self.client.post(self.client_path, data=data).status_code, 302)

    def test_due_actions_are_owned_accepted_and_based_on_recorded_due_dates(self):
        Plan, Entry = main.tool_models[:2]
        other = self.fixture.fixture.booking('other@example.com', status='Accepted')
        today = date.today()
        main.db.session.add_all([
            Plan(booking_id=self.booking.id, deposit=Decimal('25'), deposit_due=today),
            Plan(booking_id=other.id, deposit=Decimal('35'), deposit_due=today),
        ])
        main.db.session.commit()
        page = self.client.get('/client/').data
        self.assertLess(page.index(b'Your next steps'), page.index(b'Ready for face painting?'))
        self.assertIn(b'Deposit due', page)
        self.assertNotIn(other.public_reference.encode(), page)
        main.db.session.add(Entry(booking_id=self.booking.id, token='deposit-paid', amount=Decimal('25'),
                                 kind='payment', method='Cash', paid_date=today))
        main.db.session.commit()
        self.assertNotIn(b'Deposit due', self.client.get('/client/').data)
        plan = main.db.session.get(Plan, self.booking.id)
        plan.balance_due = today + timedelta(days=1)
        main.db.session.commit()
        self.assertNotIn(b'<h3>Balance due</h3>', self.client.get('/client/').data)
        plan.balance_due = today
        main.db.session.commit()
        self.assertIn(b'<h3>Balance due</h3>', self.client.get('/client/').data)
        self.booking.status = 'Cancelled'
        main.db.session.commit()
        self.assertNotIn(b'<h3>Balance due</h3>', self.client.get('/client/').data)

    def test_older_messages_do_not_mark_unseen_messages_read(self):
        main.db.session.add_all([main.BookingMessage(booking_id=self.booking.id, sender='admin',
            body=f'Message {index}', submission_key=f'pagination-{index}') for index in range(105)])
        main.db.session.commit()
        page = self.client.get(self.client_path)
        self.assertIn(b'Older messages', page.data)
        self.assertEqual(main.BookingMessage.query.filter_by(read_at=None).count(), 5)
        first_visible = main.BookingMessage.query.order_by(main.BookingMessage.id).offset(5).first().id
        page = self.client.get(self.client_path + f'?before={first_visible}')
        self.assertIn(b'Message 0', page.data)
        self.assertEqual(main.BookingMessage.query.filter_by(read_at=None).count(), 0)


if __name__ == '__main__':
    unittest.main()
