import json
import re
import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import text

import test_booking_on_behalf as fixtures
from booking_edit import version
from booking_rewards import reward_discount
from test_admin_polish_browser import BrowserChecks, EDGE

main = fixtures.main


class BookingRewardsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OnBehalfTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.admin = self.fixture.admin
        self.client = self.fixture.client
        self.account = self.fixture.fixture.fixture.account
        main.db.session.add(main.BusinessSetting(key='hourly_rate', value='50.00'))
        main.db.session.commit()

    def add_reward(self, code, owner, status='earned', earned_date='2025-01-02'):
        main.db.session.execute(text("""
            INSERT INTO referrals
                (customer_name, code, original_event_date, expires_date, reward_earned_date, status)
            VALUES ('Reward owner', :code, '2025-01-01', '2026-01-01', :earned_date, :status)
        """), {'code': code, 'earned_date': earned_date if status == 'earned' else None, 'status': status})
        main.db.session.add(main.ClientRewardOwner(code=code, client_id=owner.id))
        main.db.session.commit()

    def reward_status(self, code):
        return main.db.session.execute(text('SELECT status FROM referrals WHERE code = :code'), {'code': code}).scalar()

    def token(self, client, path):
        page = client.get(path).get_data(as_text=True)
        match = re.search(r'name="booking_reward_token"[^>]*\bvalue="([^"]+)"', page)
        return match.group(1) if match else None

    def signed_form(self, path='/booking', **overrides):
        token = self.token(self.client, path)
        with self.client.session_transaction() as session:
            csrf = session['client_csrf']
        form = dict(self.fixture.form(), csrf_token=csrf, signature='Test Client', is_over_18='yes',
                    liability_acknowledged='yes', terms_accepted='yes', use_booking_reward='yes')
        if token:
            form['booking_reward_token'] = token
        form.update(overrides)
        return form

    def test_public_booking_discounts_once_and_decline_returns_unused_reward(self):
        self.add_reward('RWD01', self.account)
        self.add_reward('RWD02', self.account, earned_date='2025-01-03')
        data = self.signed_form()
        self.assertTrue(data['booking_reward_token'])
        with patch.object(main, 'send_booking_request_confirmation', return_value=True):
            response = self.client.post('/booking', data=data)
        self.assertEqual(response.status_code, 302)
        claim = main.BookingReward.query.one()
        booking = main.db.session.get(main.Booking, claim.booking_id)
        self.assertEqual(booking.total_event_cost, Decimal('75.00'))
        self.assertEqual(claim.code, 'RWD01')
        self.assertEqual(reward_discount(booking), Decimal('25.00'))
        day, = main.booking_schedule_events(booking)
        self.assertEqual((day['start_time'], day['finish_time'], day['duration_hours']), ('10:00', '12:00', '2'))
        self.assertEqual(self.reward_status('RWD01'), 'redeemed')
        history_page = self.client.get('/client/rewards')
        self.assertIn(b'30-minute reward history', history_page.data)
        self.assertIn(f'/client/bookings/{booking.id}'.encode(), history_page.data)
        self.assertIn('Booking saving £25.00'.encode(), history_page.data)

        count = main.Booking.query.count()
        replay = self.client.post('/booking', data=data)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(main.Booking.query.count(), count)
        self.assertEqual(main.BookingReward.query.count(), 1)
        self.assertEqual(self.reward_status('RWD02'), 'earned')

        path = f'/admin/bookings/{booking.id}/edit'
        self.assertEqual(self.admin.get(path).status_code, 200)
        with self.admin.session_transaction() as session:
            csrf = session['client_csrf']
        schedule = json.loads(booking.event_schedule)
        schedule['events'][0]['travel_miles'] = '30'
        edit = dict(csrf_token=csrf, booking_version=version(booking),
                    event_schedule=json.dumps(schedule), payment_preference='50% deposit')
        quote_response = self.admin.post(path, data=dict(edit, action='quote'))
        self.assertEqual(quote_response.status_code, 200)
        quote = quote_response.json['quote']
        self.assertEqual(quote['reward_discount'], '25.00')
        self.assertEqual(quote['event_total'], '75.00')
        self.assertEqual(quote['travel'], '20.00')
        self.assertEqual(quote['total'], '95.00')
        self.assertEqual(quote['deposit'], '47.50')
        self.assertEqual(self.admin.post(path, data=edit).status_code, 302)
        self.assertEqual((booking.total_event_cost, booking.travel_charge), (Decimal('75.00'), Decimal('20.00')))
        self.assertEqual(reward_discount(booking), Decimal('25.00'))

        self.assertEqual(self.admin.post(f'/admin/bookings/{booking.id}/manage', data={'action': 'decline'}).status_code, 302)
        self.assertEqual(booking.status, 'Declined')
        self.assertEqual(booking.total_event_cost, Decimal('100.00'))
        self.assertEqual(reward_discount(booking), Decimal('0.00'))
        day, = main.booking_schedule_events(booking)
        self.assertEqual(Decimal(day['estimated_cost']), Decimal('100.00'))
        self.assertNotIn('reward_discount', day)
        self.assertIsNone(main.db.session.get(main.BookingReward, booking.id))
        self.assertEqual(self.reward_status('RWD01'), 'earned')
        history_page = self.client.get('/client/rewards')
        self.assertIn(b'The booking was declined.', history_page.data)
        self.assertIn('Original saving £25.00'.encode(), history_page.data)

        with self.admin.session_transaction() as session:
            csrf = session['client_csrf']
        response = self.admin.post(f'/admin/bookings/{booking.id}/delete',
                                   data={'csrf_token': csrf, 'confirm_delete': 'yes'})
        self.assertIn('deleted=', response.location)
        history_page = self.client.get('/client/rewards')
        self.assertIn(booking.public_reference.encode(), history_page.data)
        self.assertNotIn(f'/client/bookings/{booking.id}'.encode(), history_page.data)

    def test_legacy_applied_reward_is_shown_and_remains_in_history_after_cancellation(self):
        self.add_reward('LEG01', self.account)
        data = self.signed_form()
        with patch.object(main, 'send_booking_request_confirmation', return_value=True):
            self.assertEqual(self.client.post('/booking', data=data).status_code, 302)
        association = main.BookingReward.query.one()
        booking = main.db.session.get(main.Booking, association.booking_id)
        main.db.session.delete(main.BookingRewardHistory.query.one())
        main.db.session.commit()
        self.assertIn('Booking saving £25.00'.encode(), self.client.get('/client/rewards').data)

        with patch.object(main, 'send_client_email', return_value=True):
            response = self.client.post(f'/client/bookings/{booking.id}/request',
                data={'csrf_token': data['csrf_token'], 'kind': 'cancellation', 'details': 'Please cancel this booking.'})
            self.assertEqual(response.status_code, 302)
            item = main.BookingRequest.query.filter_by(booking_id=booking.id).one()
            self.assertEqual(self.admin.post(f'/admin/booking-requests/{item.id}',
                data={'csrf_token': 'admin-token', 'action': 'complete', 'response': 'Cancellation approved.'}).status_code, 302)
        history_page = self.client.get('/client/rewards')
        self.assertIn(b'The booking was cancelled.', history_page.data)
        self.assertIn('Original saving £25.00'.encode(), history_page.data)
        self.assertEqual(self.reward_status('LEG01'), 'earned')
        self.assertIsNone(main.BookingRewardHistory.query.one().applied_at)

    def test_reward_requires_a_signed_in_owner_and_earned_status(self):
        other = main.ClientAccount(email='other-reward-owner@example.com', first_name='Other', last_name='Client')
        main.db.session.add(other)
        main.db.session.commit()
        self.add_reward('OTHER', other)
        self.add_reward('NEWRD', self.account, status='active')
        data = self.signed_form()
        count = main.Booking.query.count()

        guest = main.app.test_client()
        self.assertIn(b'Sign in to your client account to use your earned reward.', guest.post('/booking', data=data).data)
        self.assertNotIn('booking_reward_token', data)
        response = self.client.post('/booking', data=data)
        self.assertEqual(response.status_code, 200)

        another_client = main.app.test_client()
        portal = self.fixture.fixture.fixture.fixture
        code = portal.request_code(another_client, email=other.email, signup=False)
        self.assertEqual(portal.verify(code, another_client).status_code, 302)
        token = self.token(another_client, '/booking')
        self.assertTrue(token)
        stolen = self.client.post('/booking', data=dict(data, booking_reward_token=token))
        self.assertEqual(stolen.status_code, 200)
        self.assertEqual(main.Booking.query.count(), count)
        self.assertEqual(main.BookingReward.query.count(), 0)
        self.assertEqual(self.reward_status('OTHER'), 'earned')
        self.assertEqual(self.reward_status('NEWRD'), 'active')

    def test_client_edits_reuse_attached_reward_without_consuming_another(self):
        self.add_reward('FIRST', self.account)
        self.add_reward('SECND', self.account, earned_date='2025-01-03')
        booking = self.fixture.create()
        path = f'/client/bookings/{booking.id}/edit'
        client_form = self.signed_form(path=path, booking_version=version(booking))
        self.assertTrue(client_form['booking_reward_token'])
        response = self.client.post(path, data=client_form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(booking.total_event_cost, Decimal('75.00'))
        self.assertEqual(self.reward_status('FIRST'), 'redeemed')
        self.assertEqual(self.reward_status('SECND'), 'earned')

        stale = self.client.post(path, data=client_form)
        self.assertIn(b'This booking changed while you were editing', stale.data)
        client_form['booking_version'] = version(booking)
        schedule = json.loads(client_form['event_schedule'])
        schedule['events'][0]['theme'] = 'Updated theme'
        client_form['event_schedule'] = json.dumps(schedule)
        self.assertEqual(self.client.post(path, data=client_form).status_code, 302)
        self.assertEqual(booking.theme, 'Updated theme')
        self.assertEqual(booking.total_event_cost, Decimal('75.00'))
        self.assertEqual(main.BookingReward.query.one().code, 'FIRST')
        self.assertEqual(self.reward_status('SECND'), 'earned')

    @unittest.skipUnless(EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_public_form_previews_reward_only_for_complete_eligible_events(self):
        self.add_reward('RWD01', self.account)
        page = self.client.get('/booking')
        BrowserChecks.browser(self, page.data, '''
            const option = document.getElementById('bookingRewardOption');
            const checkbox = document.getElementById('useBookingReward');
            const estimate = document.getElementById('estimatedEventCost');
            const reward = document.getElementById('bookingRewardEstimate');
            const field = name => document.querySelector(`[data-event-field="${name}"]`);
            const set = (name, value) => {
                field(name).value = value;
                change(field(name));
            };
            const pound = String.fromCharCode(163);
            assert(option.hidden && checkbox.disabled, 'blank schedules should hide the reward');
            set('start_time', '10:00');
            set('finish_time', '12:00');
            set('pitch_fee_required', 'no');
            set('charge_type', 'Client');
            set('publicity_type', 'Private');
            assert(option.hidden, 'the event date is required before offering the reward');
            set('date', '2099-01-05');
            assert(!option.hidden && !checkbox.disabled, 'private billable event should offer the reward');
            assert(estimate.textContent === pound + '100.00', 'gross price should be visible until reward is selected');
            checkbox.click();
            assert(estimate.textContent === pound + '75.00', 'reward should reduce the price by half an hour');
            assert(reward.textContent.endsWith(pound + '25.00'), 'reward line should show the saving');
            assert(field('finish_time').value === '12:00', 'the duration should stay the same');
            set('publicity_type', 'Public');
            assert(option.hidden && checkbox.disabled, 'public events should hide the reward');
            assert(estimate.textContent === pound + '100.00', 'ineligible events should restore the gross price');
        ''', 1100)
