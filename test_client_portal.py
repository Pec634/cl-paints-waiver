import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from datetime import datetime, timedelta, date
from io import BytesIO
import json
import re
import unittest
from unittest.mock import patch
import app as main
import rewards


class ClientPortalTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()
        rewards.execute('DELETE FROM referrals')
        self.client = main.app.test_client()

    def tearDown(self):
        self.context.pop()

    def csrf(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session['client_csrf']

    def request_code(self, client=None, email='client@example.com', signup=True):
        client = client or self.client
        path = '/client/signup' if signup else '/client/login'
        self.assertEqual(client.get(path).status_code, 200)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = client.post(path, data={'csrf_token': self.csrf(client), 'email': email,
                'first_name': 'Test', 'last_name': 'Client'})
        self.assertEqual(response.status_code, 302)
        if send.called:
            return re.search(r'code is (\d{6})', send.call_args.args[2]).group(1)
        return None

    def verify(self, code, client=None):
        client = client or self.client
        return client.post('/client/verify', data={'csrf_token': self.csrf(client), 'code': code})

    def signup(self, email='client@example.com'):
        code = self.request_code(email=email)
        self.assertEqual(self.verify(code).status_code, 302)
        return main.ClientAccount.query.filter_by(email=email).one()

    def booking(self, email, **extra):
        values = dict(request_type='booking', client_type='individual', first_name='Test', last_name='Client',
            date_of_birth=date(1990, 1, 1), is_over_18=True, ethnicity='Prefer not to say', religion='Prefer not to say',
            client_address='Test address', phone='+447911123456', email=email, event_date=date(2099, 1, 1),
            single_date=True, start_time='10:00', finish_time='12:00', event_address='Test venue', publicity_type='Private',
            charge_type='Client', location_type='Indoors', event_type='Birthday', theme='N/A', pitch_fee_required=False,
            payment_preference='Full payment', signature='Test', liability_acknowledged=True, terms_accepted_at=datetime.now(),
            terms_version='test', internal_notes='SECRET ADMIN NOTE', company_signature='SECRET ADMIN SIGNATURE')
        values.update(extra)
        booking = main.Booking(**values)
        main.db.session.add(booking)
        main.db.session.commit()
        return booking

    def test_signup_verification_and_page_rendering(self):
        code = self.request_code()
        self.assertEqual(main.ClientAccount.query.count(), 0)
        self.assertNotEqual(main.ClientLoginCode.query.one().code_hash, code)
        self.assertEqual(self.verify(code).status_code, 302)
        self.assertEqual(main.ClientAccount.query.count(), 1)
        for path in ['/client/', '/client/account', '/client/bookings', '/client/rewards', '/client/contact', '/booking']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get('/admin/clients').status_code, 302)
        self.assertEqual(self.client.get('/admin/reports').status_code, 302)
        self.assertEqual(self.client.post('/client/logout', data={'csrf_token': self.csrf()}).status_code, 302)
        self.assertEqual(self.client.get('/client/').status_code, 302)
        self.client.get('/client/login')
        self.assertEqual(self.client.post('/client/verify', data={'csrf_token': self.csrf(), 'code': code}).status_code, 302)

    def test_returning_client_signin_and_resend_cooldown(self):
        self.signup()
        self.client.post('/client/logout', data={'csrf_token': self.csrf()})
        self.client.get('/client/login')
        response = self.client.post('/client/login', data={'csrf_token': self.csrf(), 'email': 'client@example.com'})
        self.assertIn(b'Please wait', response.data)
        challenge = main.ClientLoginCode.query.one()
        challenge.created_at = datetime.now()-timedelta(minutes=2)
        main.db.session.commit()
        code = self.request_code(signup=False)
        self.assertEqual(self.verify(code).status_code, 302)
        self.assertEqual(main.ClientAccount.query.count(), 1)

    def test_code_attempt_limits_expiry_and_resend(self):
        code = self.request_code()
        for _ in range(5):
            response = self.verify('000000' if code != '000000' else '111111')
            self.assertEqual(response.status_code, 200)
        self.assertIn(b'expired or is unavailable', self.verify(code).data)
        self.assertEqual(main.ClientAccount.query.count(), 0)
        challenge = main.ClientLoginCode.query.one()
        challenge.created_at = datetime.now()-timedelta(minutes=2)
        main.db.session.commit()
        fresh = self.request_code()
        challenges = main.ClientLoginCode.query.order_by(main.ClientLoginCode.created_at).all()
        self.assertTrue(challenges[0].consumed)
        challenges[-1].expires_at = datetime.now()-timedelta(seconds=1)
        main.db.session.commit()
        self.assertIn(b'expired or is unavailable', self.verify(fresh).data)

    def test_missing_account_and_delivery_failure(self):
        self.assertIsNone(self.request_code(signup=False))
        self.assertEqual(main.ClientAccount.query.count(), 0)
        self.client.get('/client/signup')
        with patch.object(main, 'send_client_email', return_value=False):
            response = self.client.post('/client/signup', data={'csrf_token': self.csrf(), 'email': 'other@example.com',
                                                               'first_name': 'Other', 'last_name': 'Client'})
        self.assertIn(b'could not send your code', response.data)
        self.assertEqual(main.ClientAccount.query.count(), 0)

    def test_record_isolation_and_reward_assignment(self):
        account = self.signup()
        own = self.booking('CLIENT@example.com')
        other = self.booking('other@example.com', event_type='PRIVATE OTHER EVENT')
        response = self.client.get('/client/bookings')
        self.assertIn(f'#{own.id}'.encode(), response.data)
        self.assertNotIn(b'PRIVATE OTHER EVENT', response.data)
        self.assertEqual(self.client.get(f'/client/bookings/{other.id}').status_code, 404)
        detail = self.client.get(f'/client/bookings/{own.id}')
        self.assertNotIn(b'SECRET ADMIN', detail.data)
        rewards.execute("INSERT INTO referrals(customer_name,code,original_event_date,expires_date,status) VALUES ('Test','AbC23','2026-01-01','2027-01-01','active')")
        self.assertNotIn(b'AbC23', self.client.get('/client/rewards').data)
        admin = main.app.test_client()
        with admin.session_transaction() as session:
            session['admin_authenticated'] = True
        self.assertEqual(admin.get('/admin/clients').status_code, 200)
        admin.post('/admin/clients', data={'csrf_token': self.csrf(admin), 'client_id': account.id, 'code': 'AbC23'})
        self.assertIn(b'AbC23', self.client.get('/client/rewards').data)

    def test_booking_email_cannot_be_forged(self):
        self.signup()
        self.assertEqual(self.client.post('/booking', data={}).status_code, 400)
        event = dict(date='2099-01-01', start_time='10:00', finish_time='12:00', event_address='Test venue',
            event_type='Birthday', theme='N/A', pitch_fee_required='no', publicity_type='Private', location_type='Indoors', charge_type='Client')
        with patch.object(main, 'send_booking_request_confirmation', return_value=True):
            response = self.client.post('/booking', data=dict(csrf_token=self.csrf(), request_type='booking', client_type='individual',
                first_name='Test', last_name='Client', email='victim@example.com', phone='+447911123456',
                client_address='Test address', signature='Test Client', date_of_birth='1990-01-01', is_over_18='yes',
                ethnicity='Prefer not to say', religion='Prefer not to say', single_date='yes', payment_preference='Full payment',
                liability_acknowledged='yes', terms_accepted='yes', event_schedule=json.dumps({'events': [event]})))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(main.Booking.query.one().email, 'client@example.com')

    def test_profile_and_contact_and_csrf(self):
        self.signup()
        self.assertEqual(self.client.post('/client/account', data={}).status_code, 400)
        self.client.post('/client/account', data={'csrf_token': self.csrf(), 'first_name': 'Test', 'last_name': 'Client',
            'phone': '01234', 'address': 'Test address'})
        self.assertEqual(main.ClientAccount.query.one().address, 'Test address')
        self.client.post('/client/contact', data={'csrf_token': self.csrf(), 'subject': 'Booking help', 'message': 'Please help.'})
        self.assertEqual(main.ClientEnquiry.query.count(), 1)
        self.assertEqual(self.client.post('/client/logout', data={}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
