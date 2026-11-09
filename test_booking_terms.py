import json
import unittest
from unittest.mock import patch
import test_booking_on_behalf as fixtures

main = fixtures.main


class BookingTermsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OnBehalfTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.public = main.app.test_client()
        self.path = '/admin/booking-terms'
        self.admin.get(self.path)
        with self.admin.session_transaction() as session:
            self.csrf = session['booking_terms_csrf']

    def tearDown(self):
        self.fixture.tearDown()

    def publish(self, text, **extra):
        data = dict(csrf_token=self.csrf, action='publish', terms=text,
                    version=main.app.jinja_env.globals['booking_terms_version']())
        data.update(extra)
        return self.admin.post(self.path, data=data)

    def test_admin_only_csrf_and_input_validation(self):
        self.assertEqual(self.public.get(self.path).status_code, 302)
        self.assertEqual(self.fixture.client.get(self.path).status_code, 302)
        self.assertEqual(self.publish('New terms', csrf_token='bad').status_code, 400)
        self.assertIn(b'between 1 and 50,000', self.publish(' ').data)
        self.assertIn(b'between 1 and 50,000', self.publish('x'*50001).data)
        self.assertIn(b'Booking terms &amp; conditions', self.admin.get('/admin/dashboard').data)

    def test_preview_then_publish_updates_live_form_and_escapes_html(self):
        self.assertIn(b'1. Booking eligibility', self.public.get('/booking').data)
        text = '# Updated booking terms\n\nNew wording with <script>alert(1)</script>.'
        preview = self.admin.post(self.path, data=dict(csrf_token=self.csrf, action='preview', terms=text))
        self.assertIn(b'&lt;script&gt;', preview.data)
        self.assertNotIn(b'New wording with', self.public.get('/booking').data)
        self.assertEqual(self.publish(text).status_code, 302)
        page = self.public.get('/booking').data
        self.assertIn(b'<h3>Updated booking terms</h3>', page)
        self.assertIn(b'&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertNotIn(b'<script>alert(1)</script>', page)
        self.assertIn(b'Allergy &amp; Patch Test Notice', page)

    def test_new_bookings_keep_terms_snapshot_and_stale_forms_are_rejected(self):
        self.publish('# First version\n\nOriginal booking wording.')
        version = main.app.jinja_env.globals['booking_terms_version']()
        form = self.fixture.form()
        form.update(signature='Test Client', terms_accepted='yes', liability_acknowledged='yes',
                    is_over_18='yes', booking_terms_version=version)
        with patch.object(main, 'send_booking_request_confirmation', return_value=True):
            response = self.public.post('/booking', data=form)
        self.assertEqual(response.status_code, 302)
        booking = main.Booking.query.order_by(main.Booking.id.desc()).first()
        snapshot = json.loads(booking.event_schedule)['booking_legal']
        self.assertEqual(booking.terms_version, version)
        self.assertIn('Original booking wording.', snapshot['html'])
        self.publish('# Second version\n\nNew booking wording.')
        self.assertEqual(json.loads(booking.event_schedule)['booking_legal'], snapshot)
        count = main.Booking.query.count()
        response = self.public.post('/booking', data=form)
        self.assertIn(b'booking terms changed', response.data)
        self.assertEqual(main.Booking.query.count(), count)

    def test_pending_client_agreement_uses_published_terms_and_rechecks_hash(self):
        booking = self.fixture.create()
        old = self.fixture.agreement(booking)
        self.publish('# Current terms\n\nPlease review the updated wording.')
        self.assertIn(b'Please review the updated wording.', self.fixture.client.get(f'/client/bookings/{booking.id}').data)
        path = f'/client/bookings/{booking.id}/agree'
        self.fixture.client.post(path, data=old)
        self.assertTrue(fixtures.pending_agreement(booking))
        with patch.object(main, 'send_client_email', return_value=True):
            self.fixture.client.post(path, data=self.fixture.agreement(booking))
        self.assertFalse(fixtures.pending_agreement(booking))
        self.assertIn('Please review the updated wording.', json.loads(booking.event_schedule)['booking_legal']['html'])

    def test_stale_editor_cannot_overwrite_new_publication(self):
        old = main.app.jinja_env.globals['booking_terms_version']()
        self.publish('New published terms.')
        response = self.publish('Outdated terms.', version=old)
        self.assertIn(b'updated in another window', response.data)
        self.assertIn(b'New published terms.', self.public.get('/booking').data)
