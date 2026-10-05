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
        self.email_patch = patch.object(main, 'send_client_email', return_value=True)
        self.email_patch.start()

    def tearDown(self):
        self.email_patch.stop()
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

    def test_resend_countdown_enforcement_and_replacement(self):
        old_code = self.request_code()
        original = main.ClientLoginCode.query.one()
        page = self.client.get('/client/verify')
        self.assertIn(b'data-resend-seconds="60"', page.data)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.client.post('/client/resend-code', data={'csrf_token': self.csrf()})
            self.assertFalse(send.called)
        self.assertEqual(main.ClientLoginCode.query.count(), 1)
        self.assertEqual(self.client.post('/client/resend-code', data={'csrf_token': 'wrong'}).status_code, 400)
        original.created_at = datetime.now() - timedelta(seconds=61)
        main.db.session.commit()
        self.assertIn(b'data-resend-seconds="0"', self.client.get('/client/verify').data)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.assertEqual(self.client.post('/client/resend-code', data={'csrf_token': self.csrf()}).status_code, 302)
        new_code = re.search(r'code is (\d{6})', send.call_args.args[2]).group(1)
        main.db.session.refresh(original)
        self.assertTrue(original.consumed)
        latest = main.ClientLoginCode.query.order_by(main.ClientLoginCode.created_at.desc()).first()
        self.assertEqual(latest.first_name, 'Test')
        self.assertEqual(latest.mode, 'signup')
        self.assertEqual(self.verify(new_code).status_code, 302)
        self.assertEqual(main.ClientAccount.query.count(), 1)

    def test_resend_longer_limit_and_send_failure(self):
        self.request_code()
        original = main.ClientLoginCode.query.one()
        original.created_at = datetime.now() - timedelta(seconds=180)
        for index in range(2):
            main.db.session.add(main.ClientLoginCode(id=f'previous-{index}', email=original.email,
                first_name='Test', last_name='Client', mode='signup', code_hash='unused',
                ip_hash=original.ip_hash, created_at=datetime.now()-timedelta(seconds=120-index*30),
                expires_at=datetime.now()+timedelta(minutes=10), consumed=True))
        main.db.session.commit()
        page = self.client.get('/client/verify')
        seconds = int(re.search(rb'data-resend-seconds="(\d+)"', page.data).group(1))
        self.assertGreater(seconds, 60)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.client.post('/client/resend-code', data={'csrf_token': self.csrf()})
            self.assertFalse(send.called)
        for code in main.ClientLoginCode.query.all():
            code.created_at = datetime.now() - timedelta(minutes=16)
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=False):
            self.client.post('/client/resend-code', data={'csrf_token': self.csrf()})
        self.assertTrue(main.ClientLoginCode.query.order_by(main.ClientLoginCode.created_at.desc()).first().consumed)
        self.assertIn(b'could not send', self.client.get('/client/verify').data)

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
        self.assertIn(own.public_reference.encode(), response.data)
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
                address_property='10', address_street='Abbey Road', address_city='London', address_postcode='NW10 7TR', address_country='United Kingdom', signature='Test Client', date_of_birth='1990-01-01', is_over_18='yes',
                ethnicity='Prefer not to say', religion='Prefer not to say', single_date='yes', payment_preference='Full payment',
                liability_acknowledged='yes', terms_accepted='yes', event_schedule=json.dumps({'events': [event]})))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(main.Booking.query.one().email, 'client@example.com')

    def test_profile_and_contact_and_csrf(self):
        self.signup()
        self.assertEqual(self.client.post('/client/account', data={}).status_code, 400)
        self.client.post('/client/account', data={'csrf_token': self.csrf(), 'first_name': 'Test', 'last_name': 'Client',
            'phone': '01234', 'address_property': '10', 'address_street': 'Abbey Road', 'address_city': 'London',
            'address_postcode': 'NW10 7TR', 'address_country': 'United Kingdom'})
        self.assertEqual(main.ClientAccount.query.one().address, '10\nAbbey Road\nLondon\nNW10 7TR\nUnited Kingdom')
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.client.post('/client/contact', data={'csrf_token': self.csrf(), 'subject': 'Booking help', 'message': 'Please help.'})
        self.assertEqual(send.call_args.args[0], main.get_business_settings()['contact_email'])
        self.assertIn('client@example.com', send.call_args.args[2])
        self.assertIn('Please help.', send.call_args.args[2])
        self.assertIn('#enquiry-', send.call_args.args[2])
        self.assertEqual(main.ClientEnquiry.query.count(), 1)
        self.assertEqual(self.client.post('/client/logout', data={}).status_code, 400)

    def test_complete_billing_address_required_and_booking_prefill(self):
        account = self.signup()
        account.address = 'Previously saved address'
        main.db.session.commit()
        page = self.client.get('/client/account')
        self.assertIn(b'Previously saved address', page.data)
        self.assertIn(b'value="United Kingdom"', page.data)
        fields = dict(address_property='Suite 53c', address_street='Abbey Road', address_city='London',
                      address_postcode='NW10 7TR', address_country='United Kingdom')
        data = dict(fields, csrf_token=self.csrf(), first_name='Test', last_name='Client', phone='01234')
        for field in fields:
            self.assertEqual(self.client.post('/client/account', data=dict(data, **{field: ''})).status_code, 200)
            self.assertEqual(account.address, 'Previously saved address')
        self.assertEqual(self.client.post('/client/account', data=data).status_code, 302)
        self.assertEqual(main.db.session.get(main.ClientBillingAddress, account.id).details, fields)
        page = self.client.get('/booking')
        self.assertIn(b'value="Suite 53c"', page.data)
        self.assertIn(b'value="NW10 7TR"', page.data)
        self.assertIn(b'value="London"', self.client.get('/client/account').data)

    def test_address_autofill_whitespace_and_specific_errors(self):
        from client_addresses import read_address
        data = dict(address_property='Suite\n53c', address_street='Abbey\tRoad', address_city='London',
                    address_postcode='NW10 7TR', address_country='United Kingdom')
        self.assertEqual(read_address(data)['address_property'], 'Suite 53c')
        self.assertEqual(read_address(data)['address_street'], 'Abbey Road')
        with self.assertRaisesRegex(ValueError, 'too long'):
            read_address(dict(data, address_property='x'*151))
        with self.assertRaisesRegex(ValueError, 'No house'):
            read_address(dict(data, address_property=''))

    def test_account_waiver_without_event_and_verified_email(self):
        self.signup()
        page = self.client.get('/client/waivers/new')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'value="client@example.com" readonly', page.data)
        self.assertIn(b'/api/waivers/account', page.data)
        self.assertIn(b'without selecting an event', page.data)
        self.assertEqual(main.Event.query.count(), 0)
        data = dict(responsible_first_name='Test', responsible_last_name='Client', responsible_email='someone@example.com',
            signature_text='Test Client', liability_acknowledged=True, responsible_authority=True,
            responsible_accuracy=True, marketing_consent=False,
            participants=[dict(first_name='Alex', last_name='Client', age=8, gender='Gender Neutral')])
        self.assertEqual(main.app.test_client().post('/api/waivers/account', json=data).status_code, 401)
        self.assertEqual(self.client.post('/api/waivers/account', json=data).status_code, 400)
        with patch.object(main.resend.Emails, 'send', return_value={}):
            response = self.client.post('/api/waivers/account', json=data, headers={'X-CSRF-Token': self.csrf()})
        self.assertEqual(response.status_code, 200)
        waiver = main.Waiver.query.one()
        self.assertIsNone(waiver.event_date)
        self.assertEqual(waiver.responsible_email, 'client@example.com')
        self.assertEqual(waiver.status, 'Valid')
        self.assertEqual(len(waiver.participants), 1)
        self.assertIn(waiver.public_reference.encode(), self.client.get('/client/waivers').data)
        self.assertEqual(main.loyalty_models[2].query.count(), 0)
        self.assertEqual(main.app.test_client().get('/client/waivers/new').status_code, 302)

    def test_booking_profile_details_prefill_and_validation(self):
        self.signup()
        data = dict(csrf_token=self.csrf(), first_name='Test', last_name='Client', phone='01234',
            address_property='Suite 53c', address_street='Abbey Road', address_city='London',
            address_postcode='NW10 7TR', address_country='United Kingdom', client_type='business',
            title='Dr', job_title='Event organiser', date_of_birth='1990-01-01',
            ethnicity='Prefer not to say', ethnicity_detail='Prefer not to say', religion='Prefer not to say')
        self.assertEqual(self.client.post('/client/account', data=dict(data, job_title='')).status_code, 200)
        self.assertEqual(main.ClientBillingAddress.query.count(), 0)
        self.assertEqual(self.client.post('/client/account', data=data).status_code, 302)
        page = self.client.get('/booking').data
        self.assertIn(b'value="1990-01-01"', page)
        self.assertIn(b'value="Event organiser"', page)
        self.assertIn(b'value="business" selected', page)
        self.assertIn(b'value="Dr" selected', page)
        self.assertIn(b'value="yes" required checked', page)
        self.assertIn(b'data-initial-value="Prefer not to say"', page)

    def test_client_calendar_does_not_expose_booking_information(self):
        self.booking('secret@example.com', status='Accepted', first_name='SECRET PERSON', event_address='SECRET VENUE')
        self.booking('pending@example.com', status='Under Review', start_time='15:00', finish_time='17:00')
        Block = main.tool_models[2]
        main.db.session.add(Block(starts_at=datetime(2099,1,2,9), ends_at=datetime(2099,1,2,11), reason='SECRET REASON'))
        main.db.session.commit()
        response = main.app.test_client().get('/booking/calendar?month=2099-01')
        self.assertEqual(response.status_code, 200)
        for secret in [b'secret@example.com', b'SECRET PERSON', b'SECRET VENUE', b'SECRET REASON', b'15:00']:
            self.assertNotIn(secret, response.data)
        self.assertIn('Unavailable 09:00–13:00'.encode(), response.data)
        self.assertIn('Unavailable 09:00–11:00'.encode(), response.data)
        self.assertEqual(self.client.get('/booking/calendar?month=invalid').status_code, 400)

    def test_client_session_expiry_and_timer(self):
        self.signup()
        self.assertIn(b'data-client-session-expires=', self.client.get('/client/').data)
        self.assertIn(b'data-client-session-expires=', self.client.get('/booking').data)
        with self.client.session_transaction() as session:
            session['client_signed_in'] = datetime.now().timestamp() - 8*3600 - 1
        self.assertEqual(self.client.get('/client/').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('client_id', session)
        page = self.client.get('/client/login?expired=1')
        self.assertIn(b'Your sign-in has expired', page.data)
        self.assertNotIn(b'data-client-session-expires=', page.data)

    def test_stay_signed_in_persistent_cookie_and_fixed_expiry(self):
        self.client.get('/client/signup')
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.client.post('/client/signup', data=dict(csrf_token=self.csrf(), email='remember@example.com',
                first_name='Test', last_name='Client', stay_signed_in='yes'))
        code = re.search(r'code is (\d{6})', send.call_args.args[2]).group(1)
        response = self.verify(code)
        self.assertIn('Expires=', response.headers.get('Set-Cookie', ''))
        with self.client.session_transaction() as session:
            self.assertTrue(session['client_remember'])
            self.assertNotIn('client_pending_remember', session)
            session['client_signed_in'] = datetime.now().timestamp() - 9*3600
        self.assertEqual(self.client.get('/client/').status_code, 200)
        with self.client.session_transaction() as session:
            session['client_signed_in'] = datetime.now().timestamp() - 30*86400 - 1
        self.assertEqual(self.client.get('/client/').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('client_id', session)
            self.assertNotIn('client_remember', session)

    def test_unread_notifications_owned_acknowledgement(self):
        account = self.signup()
        Notice = main.notification_models[1]
        mine = Notice(email=account.email, kind='reward', reference='Test reward', details='Your reward is ready.')
        other = Notice(email='someone@example.com', kind='reward', reference='Private reward', details='PRIVATE')
        main.db.session.add_all([mine, other])
        main.db.session.commit()
        page = self.client.get('/client/').data
        self.assertIn(b'1 unread', page)
        self.assertNotIn(b'PRIVATE', page)
        self.assertEqual(self.client.post('/client/notifications/read', data=dict(csrf_token='bad', notice_id=mine.id)).status_code, 400)
        self.assertEqual(self.client.post('/client/notifications/read', data=dict(csrf_token=self.csrf(), notice_id=other.id)).status_code, 404)
        self.assertEqual(self.client.post('/client/notifications/read', data=dict(csrf_token=self.csrf(), notice_id=mine.id)).status_code, 302)
        self.assertNotIn(b'1 unread', self.client.get('/client/').data)
        main.db.session.add(Notice(email=account.email, kind='booking', reference='New update', details='New details'))
        main.db.session.commit()
        self.client.post('/client/notifications/read', data=dict(csrf_token=self.csrf(), notice_id=mine.id))
        self.assertIn(b'1 unread', self.client.get('/client/').data)

    def test_enquiry_survives_notification_failure(self):
        self.signup()
        with patch.object(main, 'send_client_email', return_value=False) as send:
            response = self.client.post('/client/contact', data={'csrf_token': self.csrf(),
                'subject': 'Booking help', 'message': 'Please help.'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(main.ClientEnquiry.query.count(), 1)
            send.assert_called_once()
            self.client.post('/client/contact', data={'csrf_token': self.csrf(),
                'subject': 'Duplicate', 'message': 'Please help.'})
            send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
