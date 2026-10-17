from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_client_portal as fixtures
from wedding_followups import message

main = fixtures.main


class WeddingFollowupsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest(); self.fixture.setUp()
        Form, Submission, _ = main.native_form_models
        account = main.ClientAccount(email='couple@example.com', first_name='Alex', last_name='Guest')
        form = Form(kind='enquiry', title='Wedding fair', terms='Email me wedding details', fields_json='[]', enabled=True)
        main.db.session.add_all([account, form]); main.db.session.flush()
        self.entry = Submission(form_id=form.id, client_id=account.id, token='wedding-test', email=account.email,
            name='Alex Guest', answers_json='{}', terms_snapshot=form.terms, title_snapshot=form.title)
        main.db.session.add(self.entry); main.db.session.flush()
        self.queue = main.app.extensions['wedding_followups']
        self.queue['enqueue'](self.entry); main.db.session.commit()
        self.job = self.queue['model'].query.one()

    def tearDown(self): self.fixture.tearDown()

    def test_repeated_enqueue_keeps_original_due_time(self):
        original_due = self.job.due_at
        self.assertEqual(self.queue['enqueue'](self.entry).id, self.job.id)
        main.db.session.commit()
        self.assertEqual(self.queue['model'].query.count(), 1)
        self.assertEqual(self.job.due_at, original_due)

    def test_old_duplicate_jobs_send_only_one_email(self):
        Submission = main.native_form_models[1]
        duplicate = Submission(form_id=self.entry.form_id, client_id=self.entry.client_id,
            token='older-duplicate', email=self.entry.email, name=self.entry.name,
            answers_json='{}', terms_snapshot=self.entry.terms_snapshot, title_snapshot=self.entry.title_snapshot)
        main.db.session.add(duplicate); main.db.session.flush()
        second_job = self.queue['enqueue'](duplicate); main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.queue['process'](max(self.job.due_at, second_job.due_at))
        send.assert_called_once()
        self.assertEqual(second_job.status, 'duplicate')

    def test_default_subject_names_the_fair(self):
        subject, _ = message(main.get_business_settings(), self.entry, 'https://example.com/unsubscribe')
        self.assertEqual(subject, 'Lovely meeting you at Aston Hall Hotel Wedding Fair')

    def test_admin_can_preview_save_and_send_custom_wedding_message(self):
        admin = main.app.test_client()
        with admin.session_transaction() as state: state['admin_authenticated'] = True
        path = '/admin/communications/wedding-followup'
        self.assertEqual(admin.get(path).status_code, 200)
        with admin.session_transaction() as state: csrf = state['client_csrf']
        payload = dict(csrf_token=csrf, subject='Wedding information for {first_name}',
            body='Hello {name}. From £{minimum_price}. Dates and booking: {booking_url}', action='preview')
        with patch.object(main, 'send_client_email', return_value=True) as send:
            preview = admin.post(path, data=payload)
        self.assertIn(b'Wedding information for Alex', preview.data)
        send.assert_not_called()
        self.assertIsNone(main.db.session.get(main.BusinessSetting, 'wedding_followup_body'))
        payload['action'] = 'save'
        self.assertEqual(admin.post(path, data=payload).status_code, 302)
        self.assertEqual(main.db.session.get(main.BusinessSetting, 'wedding_followup_body').value, payload['body'])
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.queue['process'](self.job.due_at)
        self.assertEqual(send.call_args.args[1], 'Wedding information for Alex')
        self.assertIn('Hello Alex Guest.', send.call_args.args[2])
        self.assertIn('/marketing/unsubscribe/', send.call_args.args[2])

    def test_editor_rejects_invalid_templates_and_requires_admin_and_csrf(self):
        path = '/admin/communications/wedding-followup'
        anonymous = main.app.test_client()
        self.assertEqual(anonymous.get(path).status_code, 302)
        self.assertEqual(anonymous.post(path, data={}).status_code, 302)
        admin = main.app.test_client()
        with admin.session_transaction() as state: state['admin_authenticated'] = True
        admin.get(path)
        with admin.session_transaction() as state: csrf = state['client_csrf']
        self.assertEqual(admin.post(path, data=dict(csrf_token='wrong', subject='Test', body='Text')).status_code, 400)
        for subject, body in [('Test', '{unknown}'), ('Test', '{name.__class__}'), ('Test', '{name!r}'),
                              ('Test', 'Missing {brace'), ('Bad\nSubject', 'Text'), ('', 'Text')]:
            response = admin.post(path, data=dict(csrf_token=csrf, subject=subject, body=body, action='save'))
            self.assertIn(b'role="alert"', response.data)
            self.assertIsNone(main.db.session.get(main.BusinessSetting, 'wedding_followup_body'))

    def test_unsubscribed_customer_is_not_emailed(self):
        Preference = main.marketing_models[0]
        main.db.session.add(Preference(email=self.entry.email, token='unsubscribe-test', unsubscribed_at=datetime.utcnow()))
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.queue['process'](self.job.due_at)
        send.assert_not_called()
        self.assertEqual(self.job.status, 'cancelled')

    def test_failed_delivery_retries_later(self):
        due = self.job.due_at
        with patch.object(main, 'send_client_email', return_value=False) as send:
            self.queue['process'](due)
            self.queue['process'](due + timedelta(minutes=1))
        send.assert_called_once()
        self.assertEqual(self.job.status, 'pending')
        self.assertEqual(self.job.due_at, due + timedelta(minutes=15))
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.queue['process'](self.job.due_at)
        send.assert_called_once()
        self.assertEqual(self.job.status, 'sent')

    def test_email_uses_saved_prices(self):
        _, body = message(dict(public_app_url='https://example.com', hourly_rate='60', minimum_hours='3',
            contact_email='hello@example.com'), SimpleNamespace(name='Alex'), 'https://example.com/unsubscribe')
        self.assertIn('£60.00 per hour', body)
        self.assertIn('£180.00', body)
        self.assertIn('https://example.com/booking', body)


if __name__ == '__main__': unittest.main()
