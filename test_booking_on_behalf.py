import json
import unittest
from unittest.mock import patch
import test_business_tools as fixtures
from booking_on_behalf import pending_agreement

main = fixtures.main


class OnBehalfTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin; self.client = self.fixture.client
        self.email = self.fixture.fixture.account.email
        self.path = '/admin/bookings/new'
        self.admin.get(self.path)
        with self.admin.session_transaction() as session:
            self.csrf = session['client_csrf']

    def tearDown(self):
        self.fixture.tearDown()

    def form(self):
        return dict(csrf_token=self.csrf, admin_authority='yes', request_type='booking', client_type='business',
            job_title='Manager', first_name='Test', last_name='Client', email=self.email, phone='+447911123456',
            address_property='10', address_street='High Street', address_city='London', address_postcode='SW1A 1AA',
            address_country='United Kingdom', date_of_birth='', ethnicity='Prefer not to say', religion='Prefer not to say',
            single_date='yes', payment_preference='Full payment', event_schedule=json.dumps({'events': [dict(
                date='2099-01-05', start_time='10:00', finish_time='12:00', event_address='Town Hall',
                event_type='Business event', theme='N/A', pitch_fee_required='no', publicity_type='Private', location_type='Indoors', charge_type='Client')]}))

    def create(self):
        form = self.form()
        form.update(signature='Not the client', liability_acknowledged='yes', terms_accepted='yes')
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(self.path, data=form)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-1000:])
        return main.Booking.query.order_by(main.Booking.id.desc()).first()

    def agreement(self, booking):
        from booking_edit import version
        with self.client.session_transaction() as session:
            csrf = session['client_csrf']
        with main.app.test_request_context():
            from hashlib import sha256
            from flask import render_template
            terms = sha256(render_template('_booking_legal_text.html').encode()).hexdigest()
        return dict(csrf_token=csrf, booking_version=version(booking), terms_hash=terms,
            signature='Test Client', terms_accepted='yes', liability_acknowledged='yes', is_over_18='yes')

    def test_admin_creation_never_records_client_consent_and_public_cannot_bypass(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        booking = self.create()
        self.assertTrue(pending_agreement(booking))
        self.assertEqual(booking.signature, '')
        self.assertFalse(booking.liability_acknowledged)
        self.assertEqual(booking.terms_version, 'pending-client')
        self.assertEqual(booking.status, 'Under Review')
        self.assertEqual(main.notification_models[1].query.filter_by(kind='booking').count(), 1)
        count = main.Booking.query.count()
        public = main.app.test_client()
        public.post('/booking?on_behalf=yes', data=self.form())
        self.assertEqual(main.Booking.query.count(), count)
        bad = self.form(); bad['csrf_token'] = 'invalid'
        self.assertEqual(self.admin.post(self.path, data=bad).status_code, 400)

    def test_client_profile_booking_form_links_account_and_preserves_admin_submission(self):
        account = self.fixture.fixture.account
        path = f'{self.path}?client_id={account.id}'
        profile = self.admin.get(f'/admin/clients/{account.id}')
        self.assertIn(path.encode(), profile.data)
        page = self.admin.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'action="{path}"'.encode(), page.data)
        self.assertIn(account.email.encode(), page.data)
        form = self.form()
        form['email'] = 'different@example.com'
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(path, data=form)
        self.assertEqual(response.status_code, 302)
        booking = main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertEqual(booking.email, account.email)
        self.assertTrue(pending_agreement(booking))
        self.assertEqual(booking.signature, '')
        self.assertEqual(self.client.get(f'/client/bookings/{booking.id}').status_code, 200)
        self.assertEqual(self.admin.get(self.path + '?client_id=invalid').status_code, 404)

    def test_generic_admin_form_posts_to_admin_route(self):
        page = self.admin.get(self.path)
        self.assertIn(b'action="/admin/bookings/new"', page.data)

    def test_completion_displays_ready_to_share_link_and_qr(self):
        import re
        from urllib.parse import urlsplit
        account = self.fixture.fixture.account
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(f'{self.path}?client_id={account.id}', data=self.form())
        booking = main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertIn(f'/admin/bookings/{booking.id}/share', response.location)
        page = self.admin.get(response.location)
        self.assertIn(b'Booking added successfully', page.data)
        self.assertIn(b'client review email was sent', page.data)
        self.assertIn(b'Copy link', page.data)
        self.assertIn(b'Download QR code', page.data)
        link = re.search(r'id="private-booking-url"[^>]*value="([^"]+)"', page.get_data(as_text=True))[1]
        fresh = self.admin.get(response.location)
        self.assertIn(link.encode(), fresh.data)
        self.assertIn(f'/admin/bookings/{booking.id}/share'.encode(), self.admin.get(f'/admin/clients/{account.id}').data)
        self.assertEqual(main.app.test_client().get(urlsplit(link).path, follow_redirects=True).status_code, 200)
        self.assertEqual(self.admin.get(f'/admin/bookings/{booking.id}/share/qr.png').status_code, 200)
        self.assertEqual(booking.status, 'Under Review')
        self.assertTrue(pending_agreement(booking))

    def test_new_client_also_gets_working_link_when_email_fails(self):
        import re
        from urllib.parse import urlsplit
        data = self.form(); data['email'] = 'new-account@example.com'
        with patch.object(main, 'send_client_email', return_value=False):
            page = self.admin.post(self.path, data=data, follow_redirects=True)
        self.assertIn(b'booking is saved, but the review email could not be sent', page.data)
        booking = main.Booking.query.filter_by(email=data['email']).one()
        self.assertIsNotNone(main.ClientAccount.query.filter_by(email=data['email']).one())
        link = re.search(r'id="private-booking-url"[^>]*value="([^"]+)"', page.get_data(as_text=True))[1]
        guest = main.app.test_client()
        self.assertEqual(guest.get(urlsplit(link).path, follow_redirects=True).status_code, 200)
        self.assertEqual(booking.status, 'Under Review')
        with guest.session_transaction() as state:
            self.assertNotIn('client_id', state)

    def test_account_booking_sends_client_review_email(self):
        account = self.fixture.fixture.account
        Preference = main.app.extensions['client_email_preference_model']
        main.db.session.add(Preference(client_id=account.id, booking_updates=False, reward_updates=False))
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.admin.post(f'{self.path}?client_id={account.id}', data=self.form())
        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        email, subject, body, markup = send.call_args.args[:4]
        self.assertEqual(email, account.email)
        self.assertIn('A booking has been added to your CL Paints account', subject)
        self.assertIn('A booking has been added to your account.', body)
        self.assertIn('Please log in to your client account to review the booking.', body)
        self.assertIn('/client/bookings/', body)
        self.assertIn('not confirmed', body)
        self.assertIn('A booking has been added to your account.', markup)

    def test_admin_can_customize_booking_added_email(self):
        page = self.admin.get('/admin/communications/configuration')
        self.assertIn(b'Bookings added by admin', page.data)
        with self.admin.session_transaction() as session:
            token = session['settings_csrf']
        response = self.admin.post('/admin/settings', data=dict(
            csrf_token=token, section='email_booking_added', return_to='communications',
            notification_booking_added_subject='Please review booking {reference}',
            notification_booking_added_body='Hi {name},\nWe have prepared your booking.\n{details}'))
        self.assertEqual(response.status_code, 302)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.admin.post(self.path, data=self.form())
        self.assertTrue(send.call_args.args[1].startswith('Please review booking '))
        self.assertIn('We have prepared your booking.', send.call_args.args[2])
        self.assertIn('/client/bookings/', send.call_args.args[2])

    def test_prefill_uses_older_booking_when_latest_and_profile_fields_are_blank(self):
        from datetime import date
        old = self.create()
        old.date_of_birth = date(1990, 4, 5)
        old.title = 'Dr'
        old.job_title = 'Earlier saved job'
        main.db.session.commit()
        latest = self.create()
        for field in ('phone', 'client_address', 'client_type', 'job_title', 'title', 'ethnicity', 'religion'):
            setattr(latest, field, '')
        latest.date_of_birth = None
        account = self.fixture.fixture.account
        account.phone = ''
        account.address = ''
        main.db.session.add(main.ClientBillingAddress(client_id=account.id, details={
            'date_of_birth': '', 'client_type': '', 'ethnicity': '', 'religion': '',
            'address_property': '', 'address_country': 'United Kingdom'}))
        main.db.session.commit()
        for client, path in ((self.admin, f'{self.path}?client_id={account.id}'), (self.client, '/booking')):
            page = client.get(path)
            for value in (b'value="1990-04-05"', b'value="Dr" selected', b'Earlier saved job',
                          b'value="10"', b'value="High Street"', b'value="+447911123456"'):
                self.assertIn(value, page.data)

    def test_account_bookings_prefill_all_saved_client_details(self):
        booking = self.create()
        booking.title = 'Dr'
        booking.job_title = 'Studio Manager'
        account = self.fixture.fixture.account
        account.phone = '+447911123456'
        main.db.session.commit()
        for client, path in ((self.admin, f'{self.path}?client_id={account.id}'),
                             (self.client, '/booking')):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            for value in (b'Studio Manager', b'value="10"', b'value="High Street"',
                          b'value="London"', b'value="SW1A 1AA"', b'value="United Kingdom"',
                          b'value="business" selected', b'value="Dr" selected'):
                self.assertIn(value, page.data)
            self.assertIn(account.email.encode(), page.data)
            self.assertNotIn(b'value="Test Client"', page.data)
        billing = main.ClientBillingAddress(client_id=account.id, details={
            'client_type': 'individual', 'date_of_birth': '1990-02-03',
            'title': 'Ms', 'religion': 'No Religion', 'ethnicity': 'Prefer not to say',
            'address_property': '22', 'address_street': 'New Road', 'address_city': 'York',
            'address_postcode': 'YO1 1AA', 'address_country': 'United Kingdom'})
        main.db.session.add(billing); main.db.session.commit()
        page = self.admin.get(f'{self.path}?client_id={account.id}')
        for value in (b'value="1990-02-03"', b'value="22"', b'value="New Road"',
                      b'value="individual" selected', b'value="Ms" selected'):
            self.assertIn(value, page.data)

    def test_client_signs_in_portal_before_admin_requests_payment(self):
        booking = self.create()
        self.admin.post(f'/admin/bookings/{booking.id}/manage', data={'action': 'accept'})
        self.assertEqual(booking.status, 'Under Review')
        page = self.client.get(f'/client/bookings/{booking.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Your review and signature are required', page.data)
        path = f'/client/bookings/{booking.id}/agree'
        self.assertEqual(main.app.test_client().post(path, data=self.agreement(booking)).status_code, 401)
        data = self.agreement(booking)
        with patch.object(main, 'send_client_email', return_value=True):
            result = self.client.post(path, data=data)
        self.assertEqual(result.status_code, 302)
        self.assertFalse(pending_agreement(booking))
        self.assertEqual(booking.signature, 'Test Client')
        self.assertTrue(booking.liability_acknowledged)
        record = json.loads(booking.event_schedule)['on_behalf']
        self.assertEqual(record['signed_by'], self.email)
        self.assertIn('terms_snapshot', record)
        self.assertEqual(booking.status, 'Under Review')
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=booking.id).count(), 1)
        self.client.post(path, data=data)
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=booking.id).count(), 1)
        with patch.object(main, 'send_client_email', return_value=True):
            self.admin.post(f'/admin/bookings/{booking.id}/manage', data={'action': 'request_payment'})
        self.assertEqual(booking.status, 'Awaiting Payment')

    def test_stale_or_missing_consent_does_not_sign(self):
        booking = self.create()
        path = f'/client/bookings/{booking.id}/agree'
        data = self.agreement(booking)
        invalid = dict(data, csrf_token='wrong')
        self.assertEqual(self.client.post(path, data=invalid).status_code, 400)
        invalid = dict(data, signature='')
        self.client.post(path, data=invalid)
        self.assertTrue(pending_agreement(booking))
        booking.theme = 'Changed'; main.db.session.commit()
        self.client.post(path, data=data)
        self.assertTrue(pending_agreement(booking))
        self.assertEqual(booking.signature, '')

    def test_other_clients_cannot_sign_and_admin_creation_is_audited(self):
        booking = self.create()
        rows = main.app.extensions['booking_lifecycle']['timeline'](booking, admin=True)
        self.assertTrue(any(row['label'] == 'Booking entered on behalf of client' for row in rows))
        data = self.agreement(booking)
        booking.email = 'other-client@example.com'; main.db.session.commit()
        response = self.client.post(f'/client/bookings/{booking.id}/agree', data=data)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(pending_agreement(booking))
