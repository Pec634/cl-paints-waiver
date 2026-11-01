import json
import re
import unittest
from decimal import Decimal
import test_business_tools as fixtures

main = fixtures.main


class EventFinancesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.booking = self.fixture.booking
        self.booking.status = 'Accepted'
        self.booking.event_schedule = json.dumps({'events': [
            dict(date='2026-11-01', publicity_type='Public', event_type='Market', event_address='Town hall', pitch_fee_required=True, pitch_fee_amount='50.00'),
            dict(date='2026-11-02', publicity_type='Public', event_type='Market', event_address='Town hall', pitch_fee_required=True, pitch_fee_amount='30.00')]})
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def create(self):
        return self.admin.post('/admin/events/from-booking', data=dict(csrf_token='admin-token', booking_id=self.booking.id, return_to='events'))

    def pay(self, event_id, amount):
        page = self.admin.get('/admin/cash-movements').get_data(as_text=True)
        data = {name: re.search(fr'name="{name}" value="([^"]*)"', page)[1]
                for name in ('csrf_token', 'movement_token', 'version')}
        data.update(action='pitch_fee', source='sumup', event_id=event_id, amount=amount, reason='Market pitch fee', checked_by='Manager')
        return self.admin.post('/admin/cash-movements', data=data)

    def test_create_links_each_day_and_repeated_creation_does_not_duplicate(self):
        response = self.create()
        self.assertIn('/admin/events?', response.location)
        events = main.Event.query.filter_by(booking_id=self.booking.id).order_by(main.Event.booking_day_number).all()
        self.assertEqual([e.booking_day_number for e in events], [1, 2])
        self.assertEqual(events[0].event_address, 'Town hall')
        self.assertEqual(events[0].status, 'Closed')
        self.create()
        self.assertEqual(main.Event.query.filter_by(booking_id=self.booking.id).count(), 2)
        self.assertIn(f'/admin/bookings/{self.booking.id}/create-events'.encode(), self.admin.get('/admin/bookings').data)
        page = self.admin.get('/admin/events').data
        self.assertIn(b'Client payments for the whole booking', page)
        self.assertIn(b'50.00', page)
        self.assertIn(b'30.00', page)
        self.assertEqual(main.CashMovement.query.count(), 0)

    def test_linked_payments_update_fee_status_only_for_matching_day(self):
        self.create()
        first, second = main.Event.query.filter_by(booking_id=self.booking.id).order_by(main.Event.booking_day_number).all()
        before = main.app.extensions['payment_summary'](self.booking)
        self.pay(first.id, '20')
        self.assertEqual(main.CashMovement.query.one().event_id, first.id)
        self.assertIn(b'Part paid', self.admin.get('/admin/events').data)
        self.pay(first.id, '30')
        self.assertEqual(main.CashMovement.query.filter_by(event_id=second.id).count(), 0)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking), before)
        page = self.admin.get('/admin/events').data
        self.assertIn(b'Paid', page)
        self.assertIn(b'SumUp bank account', page)
        self.assertIn(b'Linked event:', self.admin.get('/admin/cash-movements').data)
        self.assertIn(f'value="{first.id}" selected'.encode(), self.admin.get(f'/admin/cash-movements?event_id={first.id}').data)
        self.pay('', '30')
        page = self.admin.get('/admin/events').data
        second_card = page.split(f'id="event-{second.id}"'.encode())[1].split(b'</details>')[0]
        self.assertIn(b'Recorded pitch fee payments: &pound;0.00', second_card)

    def test_creation_access_and_invalid_payment_event(self):
        self.assertEqual(main.app.test_client().post('/admin/events/from-booking').status_code, 302)
        self.assertEqual(self.admin.post('/admin/events/from-booking', data={'booking_id':self.booking.id}).status_code, 400)
        self.booking.status = 'Under Review'
        main.db.session.commit()
        self.create()
        self.assertEqual(main.Event.query.filter_by(booking_id=self.booking.id).count(), 0)
        self.pay('999999', '20')
        self.assertEqual(main.CashMovement.query.count(), 0)
        self.pay('', '20')
        self.assertIsNone(main.CashMovement.query.one().event_id)
