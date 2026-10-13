import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import unittest
from unittest.mock import patch
import app as main


class WebsiteEnquiriesTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()
        self.visitor = main.app.test_client()
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as state:
            state['admin_authenticated'] = True
        self.Enquiry, self.Reply = main.website_enquiry_models

    def tearDown(self):
        main.db.session.remove()
        self.context.pop()

    def data(self, client=None, **extra):
        client = client or self.visitor
        response = client.get('/contact')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Send us a message', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])
        with client.session_transaction() as state:
            token = state['public_contact_csrf']
        return dict(name='Public Visitor', email='visitor@example.com', subject='Festival question',
                    message='Do you paint at festivals?', csrf_token=token, **extra)

    def test_submission_separation_and_notification_failure(self):
        with patch.object(main, 'send_client_email', return_value=False) as send:
            response = self.visitor.post('/contact/message', data=self.data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.Enquiry.query.count(), 1)
        self.assertEqual(main.ClientEnquiry.query.count(), 0)
        self.assertEqual(main.ClientAccount.query.count(), 0)
        self.assertFalse(self.Enquiry.query.one().notification_sent)
        self.assertEqual(send.call_args.args[0], main.get_business_settings()['contact_email'])
        self.assertIn(b'your message has been received', self.visitor.get(response.location).data)
        self.assertIn(b'Festival question', self.admin.get('/admin/communications/website-enquiries').data)
        self.assertNotIn(b'Festival question', self.admin.get('/admin/communications/messages?view=enquiries').data)
        self.assertEqual(self.visitor.get('/admin/communications/website-enquiries').status_code, 302)

    def test_validation_spam_trap_and_cooldown(self):
        data = self.data()
        self.assertEqual(self.visitor.post('/contact/message', data=dict(data, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.visitor.post('/contact/message', data=dict(data, email='invalid')).status_code, 400)
        response = self.visitor.post('/contact/message', data=dict(data, name='<script>alert(1)</script>', message=''))
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'&lt;script&gt;alert(1)&lt;/script&gt;', response.data)
        self.assertEqual(self.Enquiry.query.count(), 0)
        self.visitor.post('/contact/message', data=dict(data, company_website='https://spam.example'))
        self.assertEqual(self.Enquiry.query.count(), 0)
        with patch.object(main, 'send_client_email', return_value=True):
            self.visitor.post('/contact/message', data=self.data())
            self.assertEqual(self.visitor.post('/contact/message', data=self.data()).status_code, 429)
        self.assertEqual(self.Enquiry.query.count(), 1)

    def test_admin_reply_delivery_and_search(self):
        with patch.object(main, 'send_client_email', return_value=True):
            self.visitor.post('/contact/message', data=self.data())
        enquiry = self.Enquiry.query.one()
        path = f'/admin/communications/website-enquiries/{enquiry.id}'
        self.admin.get(path)
        with self.admin.session_transaction() as state:
            payload = dict(csrf_token=state['website_reply_csrf'], reply_token=state[f'website_reply_{enquiry.id}'],
                           action='reply', reply='Yes, tell us your event date.')
        self.assertEqual(self.admin.post(path, data=dict(payload, csrf_token='bad')).status_code, 400)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            self.assertEqual(self.admin.post(path, data=payload).status_code, 302)
            self.assertEqual(send.call_args.args[0], enquiry.email)
        self.assertEqual(self.Reply.query.one().delivery, 'accepted')
        self.assertEqual(enquiry.status, 'replied')
        self.assertEqual(self.admin.post(path, data=payload).status_code, 400)
        self.assertEqual(self.Reply.query.count(), 1)
        self.assertIn(b'Festival question', self.admin.get('/admin/communications/website-enquiries?q=festival&state=replied').data)
        self.assertNotIn(b'Festival question', self.admin.get('/admin/communications/website-enquiries?state=new').data)
        self.admin.get(path)
        with self.admin.session_transaction() as state:
            payload['reply_token'] = state[f'website_reply_{enquiry.id}']
        with patch.object(main, 'send_client_email', return_value=False):
            self.admin.post(path, data=payload)
        self.assertEqual(self.Reply.query.order_by(self.Reply.id.desc()).first().delivery, 'failed')
