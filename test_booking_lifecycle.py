from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_business_tools as fixtures

main = fixtures.main
Activity, Proposal, FollowUp = main.booking_lifecycle_models


class BookingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Accepted'
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.client = self.fixture.client
        self.account = self.fixture.fixture.account
        self.route = f'/admin/bookings/{self.booking.id}/activity'
        self.csrf = self.fixture.fixture.fixture.csrf()
        self.start = (datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=None) + timedelta(days=40)).replace(hour=10, minute=0, second=0, microsecond=0)

    def tearDown(self):
        self.fixture.tearDown()

    def propose(self, **values):
        return self.admin.post(self.route, data=dict(csrf_token='admin-token', action='propose',
            event_index='0', starts_at=self.start.isoformat(timespec='minutes'), reason='Please consider this replacement date.', **values))

    def decide(self, proposal, decision='accept', **values):
        data = dict(csrf_token=self.csrf, decision=decision)
        data.update(values)
        return self.client.post(f'/client/bookings/{self.booking.id}/date-proposals/{proposal.id}', data=data)

    def test_acceptance_updates_schedule_once_and_records_actor(self):
        original = self.booking.event_date
        self.assertEqual(self.propose().status_code, 302)
        proposal = Proposal.query.one()
        self.assertEqual(self.booking.event_date, original)
        self.assertEqual(proposal.ends_at - proposal.starts_at, timedelta(hours=2))
        self.assertIn(b'Review a replacement date', self.client.get('/client/').data)
        self.assertIn(b'Date proposal', self.client.get('/client/notifications').data)
        self.assertEqual(self.decide(proposal).status_code, 302)
        self.assertEqual(proposal.status, 'Accepted')
        self.assertEqual(self.booking.event_date, self.start.date())
        self.assertEqual(self.booking.start_time, '10:00')
        self.assertEqual(self.booking.finish_time, '12:00')
        self.assertEqual(self.booking.total_event_cost, 100)
        self.assertEqual(self.booking.event_address, 'Test venue')
        audit = Activity.query.filter(Activity.change_id.isnot(None)).one()
        self.assertEqual(audit.role, 'client')
        self.assertEqual(audit.actor, self.account.email)
        self.decide(proposal)
        self.assertEqual(main.notification_models[0].query.count(), 1)
        self.assertIn(b'Replacement date accepted', self.client.get(f'/client/bookings/{self.booking.id}').data)
        self.assertIn(self.account.email.encode(), self.admin.get(self.route).data)

    def test_ownership_csrf_and_validation(self):
        self.assertEqual(self.client.get(self.route).status_code, 302)
        self.assertEqual(self.admin.post(self.route, data={'action':'propose'}).status_code, 400)
        data = dict(csrf_token='admin-token', action='propose', event_index='999', starts_at=self.start.isoformat(), reason='Change date')
        self.assertEqual(self.admin.post(self.route, data=data).status_code, 200)
        self.assertEqual(Proposal.query.count(), 0)
        data['event_index'] = '0'; data['starts_at'] = '2000-01-01T10:00'
        self.admin.post(self.route, data=data)
        self.assertEqual(Proposal.query.count(), 0)
        self.propose()
        proposal = Proposal.query.one()
        self.assertEqual(self.decide(proposal, csrf_token='bad').status_code, 400)
        other = self.fixture.fixture.fixture.booking('other@example.com')
        path = f'/client/bookings/{other.id}/date-proposals/{proposal.id}'
        self.assertEqual(self.client.post(path, data=dict(csrf_token=self.csrf,decision='accept')).status_code, 404)

    def test_availability_rechecked_and_stale_proposal_keeps_original(self):
        self.propose()
        proposal = Proposal.query.one()
        original = self.booking.event_date
        block = main.tool_models[2](starts_at=self.start - timedelta(minutes=30), ends_at=self.start + timedelta(hours=3), reason='New unavailable time')
        main.db.session.add(block); main.db.session.commit()
        self.decide(proposal)
        self.assertEqual(proposal.status, 'Pending')
        self.assertEqual(self.booking.event_date, original)
        self.assertIn(b'no longer available', self.client.get(f'/client/bookings/{self.booking.id}').data)
        main.db.session.delete(block)
        self.booking.theme = 'Updated theme'
        main.db.session.commit()
        self.decide(proposal)
        self.assertEqual(proposal.status, 'Stale')
        self.assertEqual(self.booking.event_date, original)
        self.assertIsNone(proposal.pending_key)

    def test_buffers_and_other_days_block_proposals(self):
        main.db.session.add(main.tool_models[2](starts_at=self.start + timedelta(hours=2, minutes=30),
            ends_at=self.start + timedelta(hours=3), reason='Setup conflict'))
        main.db.session.commit()
        self.assertEqual(self.propose().status_code, 200)
        self.assertEqual(Proposal.query.count(), 0)
        main.tool_models[2].query.delete()
        other = self.fixture.fixture.fixture.booking('other@example.com',status='Accepted',
            event_date=self.start.date(),start_time='11:00',finish_time='13:00')
        self.propose()
        self.assertEqual(Proposal.query.count(), 0)

    def test_decline_withdraw_expiry_and_duplicate_proposals(self):
        self.propose(); self.propose()
        self.assertEqual(Proposal.query.count(), 1)
        proposal = Proposal.query.one()
        self.decide(proposal, 'decline')
        self.assertEqual(proposal.status, 'Declined')
        self.propose()
        second = Proposal.query.order_by(Proposal.id.desc()).first()
        self.admin.post(self.route, data=dict(csrf_token='admin-token',action='withdraw',proposal_id=second.id))
        self.assertEqual(second.status, 'Withdrawn')
        self.propose()
        third = Proposal.query.order_by(Proposal.id.desc()).first()
        third.expires_at = datetime.utcnow() - timedelta(seconds=1)
        main.db.session.commit()
        original = self.booking.event_date
        self.decide(third)
        self.assertEqual(third.status, 'Expired')
        self.assertEqual(self.booking.event_date, original)
        self.propose()
        self.assertEqual(Proposal.query.filter_by(status='Pending').count(), 1)

    def test_multi_day_change_preserves_metadata_and_linked_event(self):
        first = dict(main.booking_schedule_events(self.booking)[0])
        second = dict(first, date='2099-01-02')
        self.booking.event_schedule = json.dumps(dict(events=[first,second],same_details=False,pricing_rules={'hourly_rate':'50'},intake_options={'note':'Keep this'}))
        linked = main.Event(booking_id=self.booking.id,booking_day_number=2,name='Linked event',event_date=datetime(2099,1,2).date(),status='Closed')
        main.db.session.add(linked); main.db.session.commit()
        self.admin.post(self.route, data=dict(csrf_token='admin-token', action='propose',event_index='1',starts_at=self.start.isoformat(),reason='Replace second day'))
        self.decide(Proposal.query.one())
        data = json.loads(self.booking.event_schedule)
        self.assertEqual(data['events'][0], first)
        self.assertEqual(data['events'][1]['date'], self.start.date().isoformat())
        self.assertEqual(data['pricing_rules'], {'hourly_rate':'50'})
        self.assertEqual(data['intake_options'], {'note':'Keep this'})
        self.assertEqual(linked.event_date, self.start.date())
        self.assertEqual(self.booking.event_date, datetime(2099,1,1).date())

    def test_completion_feedback_and_repeat_booking_are_private_and_explicit(self):
        self.assertEqual(self.admin.post(self.route, data=dict(csrf_token='admin-token',action='complete')).status_code, 200)
        self.assertEqual(FollowUp.query.count(), 0)
        self.booking.event_date = (datetime.now(ZoneInfo('Europe/London'))-timedelta(days=2)).date()
        main.db.session.commit()
        self.admin.post(self.route, data=dict(csrf_token='admin-token',action='complete'))
        followup = FollowUp.query.one()
        self.assertIsNone(followup.requested_at)
        feedback_path = f'/client/bookings/{self.booking.id}/feedback'
        self.assertEqual(self.client.get(feedback_path).status_code, 404)
        with patch.object(main,'send_client_email',return_value=True) as send:
            for _ in range(2):
                self.admin.post(self.route, data=dict(csrf_token='admin-token',action='feedback'))
            send.assert_called_once()
        self.assertIn(b'Share event feedback', self.client.get('/client/').data)
        self.assertEqual(self.client.post(feedback_path,data={'rating':'5'}).status_code, 400)
        self.assertEqual(self.client.post(feedback_path,data=dict(csrf_token=self.csrf,rating='9')).status_code, 200)
        self.client.post(feedback_path,data=dict(csrf_token=self.csrf,rating='5',feedback='A lovely event.'))
        self.client.post(feedback_path,data=dict(csrf_token=self.csrf,rating='1',feedback='Overwrite'))
        self.assertEqual(followup.rating, 5)
        self.assertEqual(followup.feedback, 'A lovely event.')
        self.assertIn(b'A lovely event.', self.admin.get(self.route).data)
        other = self.fixture.fixture.fixture.booking('other@example.com')
        self.assertEqual(self.client.get(f'/booking?repeat={other.id}').status_code, 404)
        details = main.app.extensions['repeat_booking_details'](self.account,self.booking.id)
        self.assertEqual(json.loads(details['event_schedule'])['events'][0]['date'], '')
        self.assertNotIn('signature', details)
        self.assertNotIn('promo_code', details)
        self.assertEqual(self.client.get(f'/booking?repeat={self.booking.id}').status_code, 200)

    def test_internal_audit_is_hidden_from_client(self):
        self.admin.post(f'/admin/bookings/{self.booking.id}/manage',data=dict(status='Accepted',internal_notes='PRIVATE ADMIN NOTES'))
        self.assertIn(b'PRIVATE ADMIN NOTES',self.admin.get(self.route).data)
        self.assertNotIn(b'PRIVATE ADMIN NOTES',self.client.get(f'/client/bookings/{self.booking.id}').data)


if __name__ == '__main__': unittest.main()
