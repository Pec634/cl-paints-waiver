import html
import json
import re
import unittest
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from unittest.mock import patch
import test_client_booking_edit as fixtures
import test_native_form_browser as browsers

main = fixtures.main


class BookingAccessTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientBookingEditTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.admin = self.fixture.admin
        self.guest = main.app.test_client()
        self.share = f'/admin/bookings/{self.booking.id}/share'

    def tearDown(self):
        self.fixture.tearDown()

    def action(self, action):
        return self.admin.post(self.share, data={'csrf_token': 'admin-token', 'action': action})

    def generate(self):
        self.assertEqual(self.action('generate').status_code, 302)
        page = self.admin.get(self.share)
        self.assertEqual(page.status_code, 200)
        url = html.unescape(re.search(r'id="private-booking-url"[^>]*value="([^"]+)"', page.get_data(as_text=True))[1])
        return url, urlsplit(url).path

    def open(self):
        url, path = self.generate()
        response = self.guest.get(path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'YOUR PRIVATE BOOKING', response.data)
        return url, path

    def test_link_and_qr_open_single_booking_without_account_login(self):
        url, path = self.open()
        with self.guest.session_transaction() as session:
            self.assertNotIn('client_id', session)
            self.assertIn('booking_access', session)
        page = self.guest.get(f'/client/bookings/{self.booking.id}')
        self.assertNotIn(b'id="client-navigation"', page.data)
        self.assertNotIn(b'portal-mobile-shortcuts', page.data)
        self.assertIn('no-store', page.headers['Cache-Control'])
        self.assertNotIn(b'class="client-session-timer"', page.data)
        self.assertEqual(page.headers['Referrer-Policy'], 'no-referrer')
        import qrcode
        with patch.object(qrcode, 'make', wraps=qrcode.make) as make:
            qr = self.admin.get(self.share + '/qr.png')
        self.assertEqual(qr.status_code, 200)
        self.assertTrue(qr.data.startswith(b'\x89PNG'))
        make.assert_called_once_with(url)
        self.assertEqual(self.guest.get(self.share).status_code, 302)
        self.assertEqual(self.guest.get(self.share + '/qr.png').status_code, 302)
        self.assertEqual(self.guest.get(f'/client/bookings/{self.booking.id}/pdf').status_code, 200)

    def test_access_never_grants_account_or_other_booking_access(self):
        self.open()
        other = self.fixture.fixture.fixture.fixture.fixture.booking(self.booking.email)
        for path in ('/client/', '/client/account', '/client/bookings', '/client/rewards',
                     f'/client/bookings/{other.id}', f'/client/bookings/{other.id}/edit',
                     f'/client/bookings/{other.id}/messages'):
            self.assertEqual(self.guest.get(path).status_code, 302, path)
        self.assertEqual(self.guest.post(f'/client/bookings/{other.id}/agree', data={}).status_code, 401)

    def test_client_can_sign_and_edit_but_confirmation_locks_edits(self):
        self.open()
        with self.guest.session_transaction() as session:
            csrf = session['client_csrf']
        agreement = self.fixture.fixture.agreement(self.booking)
        agreement['csrf_token'] = csrf
        with patch.object(main, 'send_client_email', return_value=True):
            signed = self.guest.post(f'/client/bookings/{self.booking.id}/agree', data=agreement)
        self.assertEqual(signed.status_code, 302)
        self.assertEqual(self.booking.signature, 'Test Client')
        self.assertEqual(json.loads(self.booking.event_schedule)['on_behalf']['signed_via'], 'private_booking_link')
        data = self.fixture.form('Changed through private link')
        data['csrf_token'] = csrf
        self.assertEqual(self.guest.post(self.fixture.path, data=dict(data, csrf_token='wrong')).status_code, 400)
        with patch.object(main, 'send_client_email', return_value=True):
            saved = self.guest.post(self.fixture.path, data=data)
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.booking.event_address, 'Changed through private link')
        self.assertEqual(self.booking.status, 'Under Review')
        self.assertEqual(json.loads(self.booking.event_schedule)['client_revisions'][-1]['via'], 'private_booking_link')
        self.booking.status = 'Accepted'; main.db.session.commit()
        self.assertEqual(self.guest.get(self.fixture.path).status_code, 409)
        self.assertEqual(self.guest.get(f'/client/bookings/{self.booking.id}').status_code, 200)

    def test_revoking_replacing_expiring_and_tampering(self):
        url, path = self.open()
        self.assertEqual(main.app.test_client().get(path + 'bad').status_code, 404)
        self.action('revoke')
        self.assertEqual(main.app.test_client().get(path).status_code, 404)
        self.assertEqual(self.guest.get(f'/client/bookings/{self.booking.id}').status_code, 403)
        new_url, new_path = self.generate()
        self.assertNotEqual(url, new_url)
        self.assertEqual(main.app.test_client().get(path).status_code, 404)
        self.assertEqual(self.guest.get(new_path).status_code, 302)
        record = main.db.session.get(main.BookingAccess, self.booking.id)
        record.expires_at = datetime.utcnow() - timedelta(seconds=1)
        main.db.session.commit()
        self.assertEqual(main.app.test_client().get(new_path).status_code, 404)
        self.assertEqual(self.guest.get(f'/client/bookings/{self.booking.id}').status_code, 403)

    def test_admin_csrf_and_changed_booking_owner(self):
        self.assertEqual(self.admin.post(self.share, data={'action': 'generate', 'csrf_token': 'bad'}).status_code, 400)
        url, path = self.open()
        self.booking.email = 'new-owner@example.com'; main.db.session.commit()
        self.assertEqual(main.app.test_client().get(path).status_code, 404)
        self.assertEqual(self.guest.get(f'/client/bookings/{self.booking.id}').status_code, 403)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_private_booking_browser_has_booking_actions_without_portal_navigation(self):
        self.open()
        page = self.guest.get(f'/client/bookings/{self.booking.id}')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            assert(document.querySelector('.client-header').textContent.includes('YOUR PRIVATE BOOKING'), 'Private booking heading missing');
            assert(!document.querySelector('#client-navigation'), 'Portal navigation should not be shown');
            const notice = document.getElementById('booking-unconfirmed-notice');
            if (notice?.open) notice.close();
            assert(Array.from(document.querySelectorAll('a')).some(link => link.textContent.includes('Edit booking details')), 'Editing link missing');
            assert(document.querySelector('#client-booking-agreement'), 'Client signature form missing');
        ''', width=390)
