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
