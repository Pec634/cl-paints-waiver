import unittest
from datetime import datetime
from unittest.mock import patch
from flask import session
import test_client_portal as fixtures
import test_native_form_browser as browsers

main = fixtures.main
send_email = main.send_client_email


class OutgoingEmailsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest(); self.fixture.setUp()
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as state:
            state['admin_authenticated'] = True

    def tearDown(self):
        self.fixture.tearDown()

    def send(self, subject='Booking added', body='Review booking BOOK-123', recipient='client@example.com'):
        with patch.object(main, 'RESEND_API_KEY', 'test-key'), patch.object(main.resend.Emails, 'send', return_value={'id': 'provider-123'}):
            return send_email(recipient, subject, body, '<p>Review booking</p>')

    def test_auto_email_snapshot_and_provider_status_recorded(self):
        with main.app.test_request_context('/booking'):
            self.assertTrue(self.send())
        item = main.OutgoingEmail.query.one()
        self.assertEqual(item.recipient, 'client@example.com')
        self.assertEqual(item.body_text, 'Review booking BOOK-123')
        self.assertEqual(item.body_html, '<p>Review booking</p>')
        self.assertEqual(item.status, 'accepted')
        self.assertEqual(item.provider_id, 'provider-123')
        self.assertEqual(item.kind, 'booking')
        self.assertEqual(item.trigger, 'automatic')
        self.assertIsNotNone(item.completed_at)
        page = self.admin.get('/admin/communications/outgoing-emails')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Review booking BOOK-123', page.data)
        self.assertIn('no-store', page.headers['Cache-Control'])
        self.assertEqual(main.app.test_client().get('/admin/communications/outgoing-emails').status_code, 302)

    def test_search_filters_dates_and_pagination(self):
        with main.app.test_request_context('/admin/bookings/new', method='POST'):
            session['admin_authenticated'] = True
            self.send('Needle booking', 'Unique message', 'needle@example.com')
        needle = main.OutgoingEmail.query.one()
        needle.created_at = datetime(2026, 7, 1, 23, 30)
        for index in range(26):
            main.db.session.add(main.OutgoingEmail(recipient='other@example.com', sender='CL Paints', subject=f'Other {index}',
                body_text='Other message', kind='reward', trigger='automatic', status='accepted', created_at=datetime(2026, 6, 1)))
        main.db.session.commit()
        path = '/admin/communications/outgoing-emails'
        for query in ('?q=Unique+message', '?q=needle@example.com', '?kind=booking&trigger=admin&state=accepted&from=2026-07-02&to=2026-07-02'):
            page = self.admin.get(path + query)
            self.assertIn(b'Needle booking', page.data)
            self.assertNotIn(b'Other 1', page.data)
        self.assertNotIn(b'Needle booking', self.admin.get(path + '?to=2026-07-01').data)
        page = self.admin.get(path + '?kind=reward&state=accepted&trigger=automatic&q=Other')
        self.assertIn(b'Page 1 of 2', page.data)
        self.assertIn(b'kind=reward', page.data)
        self.assertIn(b'q=Other', page.data)
        self.assertEqual(self.admin.get(path + '?state=invalid').status_code, 400)
        self.assertEqual(self.admin.get(path + '?from=invalid').status_code, 400)
        self.assertEqual(self.admin.get(path + '?from=2026-11-10&to=2026-11-01').status_code, 400)

    def test_failure_missing_configuration_and_security_redaction(self):
        with patch.object(main, 'RESEND_API_KEY', 'test-key'), patch.object(main.resend.Emails, 'send', side_effect=RuntimeError('Provider refused')):
            self.assertFalse(send_email('client@example.com', 'Failed booking', 'Not sent'))
        with patch.object(main, 'RESEND_API_KEY', ''):
            self.assertFalse(send_email('client@example.com', 'Missing configuration', 'Not sent'))
        self.assertEqual(main.OutgoingEmail.query.filter_by(status='failed').count(), 2)
        self.send('Your CL Paints verification code', 'Code is 987654. https://example.com/reset/SECRET')
        record = main.OutgoingEmail.query.filter_by(kind='security').one()
        self.assertNotIn('987654', record.body_text)
        self.assertNotIn('SECRET', record.body_text)
        self.assertEqual(record.body_html, '')
        page = self.admin.get('/admin/communications/outgoing-emails?state=failed')
        self.assertIn(b'Failed booking', page.data)
        self.assertNotIn(b'Your CL Paints verification code', page.data)

    def test_direct_booking_acknowledgement_is_also_logged(self):
        booking = self.fixture.booking('client@example.com')
        with patch.object(main, 'RESEND_API_KEY', 'test-key'), patch.object(main.resend.Emails, 'send', return_value={'id': 'ack-123'}):
            self.assertTrue(main.send_booking_request_confirmation(booking))
        item = main.OutgoingEmail.query.one()
        self.assertIn(booking.public_reference, item.subject)
        self.assertEqual(item.provider_id, 'ack-123')

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_outgoing_email_filters_fit_mobile_and_message_opens(self):
        self.send()
        page = self.admin.get('/admin/communications/outgoing-emails')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const form = document.querySelector('form.portal-filter');
            assert(form.querySelector('[name="q"]'), 'Email search missing');
            assert(form.querySelector('[name="state"]'), 'Sending status filter missing');
            assert(form.querySelector('[name="kind"]'), 'Category filter missing');
            assert(form.getBoundingClientRect().right <= innerWidth + 1, 'Filters overflow phone width');
            const message = document.querySelector('article details');
            message.querySelector('summary').click();
            assert(message.open && message.textContent.includes('BOOK-123'), 'Email message does not open');
        ''', width=390)
