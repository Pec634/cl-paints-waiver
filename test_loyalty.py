import re
import secrets
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
import test_client_portal as portal_tests
main = portal_tests.main

EventCode, Balance, Visit, Custodian, Transfer = main.loyalty_models


class LoyaltyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = portal_tests.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.account = self.fixture.signup()
        self.waiver = self.make_waiver(self.account.email, 'SOURCE')
        self.person = main.Participant(waiver_id=self.waiver.id, first_name='Alex', last_name='Client', age=8, gender='Other')
        self.other = main.Participant(waiver_id=self.waiver.id, first_name='Sam', last_name='Client', age=10, gender='Other')
        main.db.session.add_all([self.person, self.other])
        main.db.session.commit()
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True
            session['client_csrf'] = 'admin-token'

    def tearDown(self):
        self.fixture.tearDown()

    def make_waiver(self, email, reference):
        waiver = main.Waiver(waiver_reference=reference, responsible_first_name='Test', responsible_last_name='Client',
            responsible_email=email, signed_date=datetime.utcnow(), expiry_date=datetime.utcnow()+timedelta(days=365),
            event_name='Public fair', event_date=datetime.now(ZoneInfo('Europe/London')).date(),
            terms_version='test', terms_snapshot='Original terms', signature_text='Original signature',
            liability_acknowledged=True, responsible_authority=True, responsible_accuracy=True)
        main.db.session.add(waiver)
        main.db.session.commit()
        return waiver

    def event(self):
        event = main.Event(name='Public fair', event_date=datetime.now(ZoneInfo('Europe/London')).date(), status='Open')
        main.db.session.add(event)
        main.db.session.commit()
        code = EventCode(event_id=event.id, token=secrets.token_urlsafe(32))
        main.db.session.add(code)
        main.db.session.commit()
        return event, '/client/loyalty/scan/'+code.token

    def post_scan(self, path, ids=None, **extras):
        return self.client.post(path, data=dict(csrf_token=self.fixture.csrf(), member_id=ids or [self.person.id], **extras))

    def test_only_selected_once_per_event_and_csrf(self):
        event, path = self.event()
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(Visit.query.count(), 0)
        self.assertEqual(self.client.post(path, data={'member_id':self.person.id}).status_code, 400)
        self.assertEqual(self.post_scan(path).status_code, 302)
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 1)
        self.assertIsNone(main.db.session.get(Balance, self.other.id))
        self.assertEqual(main.notification_models[1].query.count(), 1)
        self.assertEqual(self.admin.post(f'/admin/waivers/{self.waiver.id}/delete').status_code, 409)
        self.post_scan(path)
        self.assertEqual(Visit.query.count(), 1)

        self.assertEqual(main.notification_models[1].query.count(), 1)
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 1)
        self.assertEqual(self.client.get('/client/rewards').status_code, 200)

    def test_admin_check_in_validity_claims_and_exact_ids(self):
        event, path = self.event()
        query = dict(event_id=event.id, q=self.waiver.public_reference)
        response = self.admin.get('/admin/check-in', query_string=query)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Alex Client', response.data)
        self.assertIn(b'Sam Client', response.data)
        self.assertEqual(self.client.get('/admin/check-in', query_string=query).status_code, 302)
        main.db.session.add(Balance(participant_id=self.person.id, points=3))
        main.db.session.commit()
        response = self.admin.get('/admin/check-in', query_string=dict(event_id=event.id,q=self.person.loyalty_reference))
        self.assertIn(b'Free paint eligible', response.data)
        self.assertNotIn(b'Sam Client', response.data)
        main.db.session.add(Visit(participant_id=self.person.id,event_id=event.id,client_id=self.account.id,status='free'))
        main.db.session.commit()
        response = self.admin.get('/admin/check-in', query_string=dict(event_id=event.id,q=self.person.loyalty_reference))
        self.assertIn(b'Free paint already claimed', response.data)
        self.waiver.expiry_date = datetime.utcnow()-timedelta(days=1)
        main.db.session.commit()
        self.assertIn(b'not valid', self.admin.get('/admin/check-in', query_string=query).data)
        self.assertEqual(Balance.query.count(), 1)
        self.assertEqual(Visit.query.count(), 1)

    def test_fourth_free_requires_event_moodboard_resets_and_repeats(self):
        for _ in range(3):
            event, path = self.event()
            self.post_scan(path)
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 3)
        event, path = self.event()
        self.post_scan(path)
        self.assertIsNone(Visit.query.filter_by(event_id=event.id).first())
        image = main.MoodboardImage(title='Rainbow butterfly', image_url='https://example.com/paint.jpg')
        main.db.session.add(image)
        main.db.session.commit()
        main.db.session.add(main.EventMoodboardImage(event_id=event.id, image_id=image.id))
        main.db.session.commit()
        self.assertIn(b'Rainbow butterfly', self.client.get(path).data)
        self.post_scan(path, **{f'design_{self.person.id}':image.id})
        visit = Visit.query.filter_by(event_id=event.id).one()
        self.assertEqual(visit.status, 'free')
        self.assertEqual(visit.moodboard_id, image.id)
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 0)
        self.assertIn('free face paint claimed', main.notification_models[1].query.order_by(main.notification_models[1].id.desc()).first().details)
        self.assertIn(self.person.loyalty_reference.encode(), self.client.get('/client/account').data)
        self.post_scan(path, **{f'design_{self.person.id}':image.id})
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 0)
        _, path = self.event()
        self.post_scan(path)
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 1)

    def test_closed_wrong_date_private_and_expired_waiver(self):
        event, path = self.event()
        event.status = 'Closed'
        main.db.session.commit()
        self.assertEqual(self.client.get(path).status_code, 410)
        event.status = 'Open'
        event.event_date -= timedelta(days=1)
        main.db.session.commit()
        self.assertEqual(self.post_scan(path).status_code, 410)
        event.event_date += timedelta(days=1)
        booking = self.fixture.booking(self.account.email, status='Accepted', publicity_type='Private')
        event.booking_id = booking.id
        event.booking_day_number = 1
        main.db.session.commit()
        self.assertEqual(self.client.get(path).status_code, 410)
        self.assertEqual(self.admin.get(f'/admin/events/{event.id}/loyalty').status_code, 404)
        event.booking_id = None
        self.waiver.expiry_date = datetime.utcnow()-timedelta(days=1)
        main.db.session.commit()
        self.assertEqual(self.post_scan(path).status_code, 400)
        self.assertEqual(Visit.query.count(), 0)

    def test_waiver_email_privacy_and_invalid_member(self):
        self.assertIn(b'Original signature', self.client.get(f'/client/waivers/{self.waiver.id}').data)
        other_waiver = self.make_waiver('other@example.com', 'OTHER')
        person = main.Participant(waiver_id=other_waiver.id, first_name='Hidden', last_name='Other', age=6, gender='Other')
        main.db.session.add(person)
        main.db.session.commit()
        self.assertEqual(self.client.get(f'/client/waivers/{other_waiver.id}').status_code, 404)
        self.assertNotIn(b'Hidden', self.client.get('/client/waivers').data)
        _, path = self.event()
        self.assertEqual(self.post_scan(path, [person.id]).status_code, 400)

    def test_admin_qr_generation_and_resume_after_login(self):
        event, path = self.event()
        self.assertEqual(self.admin.get(f'/admin/events/{event.id}/loyalty').status_code, 200)
        qr = self.admin.get(f'/admin/events/{event.id}/loyalty/qr')
        self.assertEqual(qr.status_code, 200)
        self.assertIn(b'<svg', qr.data)
        anonymous = main.app.test_client()
        self.assertEqual(anonymous.get(path).status_code, 302)
        for challenge in main.ClientLoginCode.query.all():
            challenge.created_at -= timedelta(minutes=2)
        main.db.session.commit()
        code = self.fixture.request_code(client=anonymous, signup=False)
        response = self.fixture.verify(code, client=anonymous)
        self.assertEqual(response.location, path)

    def test_new_events_get_distinct_loyalty_codes(self):
        for name in ['First fair', 'Second fair']:
            response = self.admin.post('/admin/events/create', data={'name': name, 'event_date': '2099-01-01'})
            self.assertEqual(response.status_code, 302)
        codes = EventCode.query.all()
        self.assertEqual(len(codes), 2)
        self.assertNotEqual(codes[0].token, codes[1].token)
        self.assertTrue(all(event.status == 'Closed' for event in main.Event.query.all()))

    def recipient(self):
        account = main.ClientAccount(email='recipient@example.com', first_name='New', last_name='Guardian')
        main.db.session.add(account)
        main.db.session.commit()
        waiver = self.make_waiver(account.email, 'TARGET')
        client = main.app.test_client()
        with client.session_transaction() as session:
            session['client_id'] = account.id
            session['client_signed_in'] = datetime.now().timestamp()
            session['client_csrf'] = 'recipient-token'
        return account, waiver, client

    def request_transfer(self):
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.client.post(f'/client/members/{self.person.id}/transfer', data={'csrf_token':self.fixture.csrf(), 'email':'recipient@example.com'})
        self.assertEqual(response.status_code, 302)
        code = re.search(r'Verification code: (\d{6})', send.call_args.args[2]).group(1)
        return Transfer.query.one(), code

    def test_transfer_preserves_identity_points_and_signed_record(self):
        account, target, recipient = self.recipient()
        _, scan = self.event()
        self.post_scan(scan)
        transfer, code = self.request_transfer()
        original_loyalty_id = self.person.loyalty_reference
        path = '/client/member-transfers/'+transfer.id
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertNotIn(b'Alex', recipient.get('/client/rewards').data)
        self.assertEqual(recipient.get(path).status_code, 200)
        response = recipient.post(path, data={'csrf_token':'recipient-token', 'code':code, 'waiver_reference':target.public_reference, 'authority':'yes'})
        self.assertEqual(response.status_code, 302)
        owner = main.db.session.get(Custodian, self.person.id)
        self.assertEqual(owner.client_id, account.id)
        self.assertEqual(owner.waiver_id, target.id)
        self.assertEqual(self.person.waiver_id, self.waiver.id)
        self.assertEqual(self.person.loyalty_reference, original_loyalty_id)
        self.assertEqual(self.waiver.signature_text, 'Original signature')
        self.assertEqual(main.db.session.get(Balance, self.person.id).points, 1)
        self.assertIn(b'Alex', recipient.get('/client/rewards').data)
        self.assertNotIn(b'Alex', self.client.get('/client/rewards').data)
        self.assertEqual(recipient.post(path, data={'csrf_token':'recipient-token','code':code}).status_code, 410)
        self.assertEqual(self.client.post(f'/client/members/{self.person.id}/transfer', data={'csrf_token':self.fixture.csrf()}).status_code, 404)
        self.assertEqual(recipient.get(f'/client/waivers/{self.waiver.id}').status_code, 404)

    def test_transfer_wrong_codes_lockout_and_delivery_failure(self):
        account, target, recipient = self.recipient()
        transfer, code = self.request_transfer()
        path = '/client/member-transfers/'+transfer.id
        for _ in range(5):
            recipient.post(path, data={'csrf_token':'recipient-token', 'code':'wrong', 'waiver_reference':'TARGET','authority':'yes'})
        self.assertEqual(recipient.get(path).status_code, 410)
        self.assertIsNone(main.db.session.get(Custodian, self.person.id))
        transfer.created_at -= timedelta(minutes=2)
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=False):
            self.client.post(f'/client/members/{self.person.id}/transfer', data={'csrf_token':self.fixture.csrf(), 'email':account.email})
        self.assertTrue(all(t.expires_at <= datetime.utcnow() or t.attempts == 5 for t in Transfer.query.all()))


if __name__ == '__main__':
    unittest.main()
