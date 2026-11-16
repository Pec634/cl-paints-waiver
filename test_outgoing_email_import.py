import unittest
from unittest.mock import patch
from datetime import datetime
import test_outgoing_emails as fixtures
from outgoing_email_import import import_page, HistoryError

main = fixtures.main


class OutgoingEmailImportTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OutgoingEmailsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin
        self.admin.get('/admin/communications/outgoing-emails')
        with self.admin.session_transaction() as session:
            self.csrf = session['client_csrf']
        self.summary = dict(id='email-123', to=['client@example.com'],
            **{'from': 'CL Paints <info@clpaints.com>'}, subject='Old booking notice',
            created_at='2026-10-25T12:30:45+00:00')

    def tearDown(self):
        self.fixture.tearDown()

    def fetch(self, path):
        if path.startswith('emails?'):
            return {'data': [self.summary], 'has_more': False}
        return dict(self.summary, text='Historical booking message', html='<p>Historical booking message</p>')

    def test_import_preserves_date_body_search_and_skips_duplicates(self):
        result = import_page(main.db, main.OutgoingEmail, self.fetch)
        self.assertEqual(result['imported'], 1)
        item = main.OutgoingEmail.query.one()
        self.assertEqual(item.created_at, datetime(2026, 10, 25, 12, 30, 45))
        self.assertEqual(item.body_text, 'Historical booking message')
        self.assertEqual(item.provider_id, 'email-123')
        self.assertEqual(item.trigger, 'historical')
        self.assertEqual(import_page(main.db, main.OutgoingEmail, self.fetch)['imported'], 0)
        self.assertEqual(main.OutgoingEmail.query.count(), 1)
        page = self.admin.get('/admin/communications/outgoing-emails?q=Historical&trigger=historical')
        self.assertIn(b'Historical booking message', page.data)
        self.assertIn(b'25/10/2026 12:30:45 GMT', page.data)

    def test_batch_resume_and_csrf_never_resend(self):
        self.assertEqual(self.admin.post('/admin/communications/outgoing-emails/import', data={}).status_code, 400)
        self.assertEqual(main.app.test_client().post('/admin/communications/outgoing-emails/import', data={}).status_code, 302)
        with patch('outgoing_email_import.history_fetcher', return_value=self.fetch), patch.object(main.resend.Emails, 'send') as send:
            response = self.admin.post('/admin/communications/outgoing-emails/import',
                data={'csrf_token': self.csrf, 'action': 'start'}, follow_redirects=True)
        self.assertIn(b'Imported 1 email(s)', response.data)
        send.assert_not_called()
        self.summary['id'] = 'email-456'
        calls = []
        def second(path):
            calls.append(path)
            return self.fetch(path)
        with patch('outgoing_email_import.history_fetcher', return_value=second):
            self.admin.post('/admin/communications/outgoing-emails/import',
                data={'csrf_token': self.csrf, 'action': 'continue'})
        self.assertIn('after=email-123', calls[0])
        self.assertEqual(main.OutgoingEmail.query.count(), 2)

    def test_security_redaction_html_only_and_unrelated_senders(self):
        self.summary['subject'] = 'Your CL Paints verification code'
        def security(path):
            return self.fetch(path) if path.startswith('emails?') else dict(self.summary, text='Code 123456', html='<p>123456</p>')
        import_page(main.db, main.OutgoingEmail, security)
        item = main.OutgoingEmail.query.one()
        self.assertNotIn('123456', item.body_text)
        self.assertEqual(item.body_html, '')
        self.summary.update(id='email-other', subject='HTML-only notice')
        def markup(path):
            return self.fetch(path) if path.startswith('emails?') else dict(self.summary, text=None, html='<p>Original message</p><script>SECRET_SCRIPT</script>')
        import_page(main.db, main.OutgoingEmail, markup)
        item = main.OutgoingEmail.query.filter_by(provider_id='email-other').one()
        self.assertIn('Original message', item.body_text)
        self.assertNotIn('SECRET_SCRIPT', item.body_text)
        self.summary.update(id='unrelated', **{'from': 'unrelated@example.com'})
        result = import_page(main.db, main.OutgoingEmail, self.fetch)
        self.assertEqual(result['imported'], 0)

    def test_provider_error_keeps_progress_and_explains_missing_access(self):
        with patch('outgoing_email_import.history_fetcher', side_effect=HistoryError('History access denied')):
            page = self.admin.post('/admin/communications/outgoing-emails/import', data={
                'csrf_token': self.csrf, 'action': 'start'}, follow_redirects=True)
        self.assertIn(b'History access denied', page.data)
        def interrupted(path):
            if path.startswith('emails?'):
                return {'data': [self.summary], 'has_more': False}
            raise HistoryError('Rate limited')
        result = import_page(main.db, main.OutgoingEmail, interrupted, cursor='previous-email')
        self.assertEqual(result['cursor'], 'previous-email')
        self.assertTrue(result['more'])
        self.assertEqual(result['error'], 'Rate limited')
