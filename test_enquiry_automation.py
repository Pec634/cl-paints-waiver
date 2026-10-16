import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import unittest
from unittest.mock import patch
import app as main
from enquiry_automation import select_reply, validate_settings


class EnquiryAutomationTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()

    def tearDown(self):
        main.db.session.remove()
        self.context.pop()

    def test_matching_priority_boundaries_and_disabled_rule(self):
        config = main.get_business_settings()
        topic, body = select_reply(config, 'Availability and pricing', 'How much?')
        self.assertEqual(topic, 'pricing')
        self.assertIn('£90.00', body)
        self.assertEqual(select_reply(config, '', 'Are you available?')[0], 'availability')
        self.assertEqual(select_reply(config, '', 'Please update my address')[0], 'other')
        self.assertIn('48 hours', select_reply(config, '', 'Hello')[1])
        config['auto_pricing_enabled'] = '0'
        self.assertIsNone(select_reply(config, 'Pricing', ''))

    def test_website_send_once_and_keep_new(self):
        Enquiry, Reply = main.website_enquiry_models
        enquiry = Enquiry(name='Visitor', email='visitor@example.com', subject='Pricing',
                          message='How much?', submission_token='unique')
        main.db.session.add(enquiry)
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            main.app.extensions['send_enquiry_auto_reply']('website', enquiry)
            main.app.extensions['send_enquiry_auto_reply']('website', enquiry)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(Reply.query.one().delivery, 'accepted')
        self.assertEqual(enquiry.status, 'new')

    def test_failed_send_keeps_record(self):
        Enquiry, Reply = main.website_enquiry_models
        enquiry = Enquiry(name='Visitor', email='visitor@example.com', subject='Hello',
                          message='Thanks', submission_token='unique')
        main.db.session.add(enquiry)
        main.db.session.commit()
        with patch.object(main, 'send_client_email', side_effect=RuntimeError('unavailable')):
            main.app.extensions['send_enquiry_auto_reply']('website', enquiry)
        self.assertEqual(Reply.query.one().delivery, 'failed')
        self.assertFalse(main.notification_models[1].query.one().email_sent)

    def test_portal_reply_visible_and_duplicate_protected(self):
        account = main.ClientAccount(first_name='Test', last_name='Client', email='client@example.com')
        main.db.session.add(account)
        main.db.session.flush()
        enquiry = main.ClientEnquiry(client_id=account.id, subject='Hello', message='A question')
        main.db.session.add(enquiry)
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            main.app.extensions['send_enquiry_auto_reply']('portal', enquiry, account)
            main.app.extensions['send_enquiry_auto_reply']('portal', enquiry, account)
        self.assertEqual(send.call_count, 1)
        workflow = main.tool_models[3].query.one()
        self.assertEqual(workflow.status, 'new')
        self.assertIn('48 hours', workflow.reply)

    def test_validation_and_configuration_security(self):
        config = main.get_business_settings()
        self.assertEqual(validate_settings(config)['auto_other_enabled'], '1')
        with self.assertRaises(ValueError):
            validate_settings(dict(config, auto_other_body='{unknown}'))
        admin = main.app.test_client()
        self.assertEqual(admin.get('/admin/communications/configuration').status_code, 302)
        with admin.session_transaction() as state:
            state['admin_authenticated'] = True
        self.assertIn(b'Automatic enquiry replies', admin.get('/admin/communications/configuration').data)
        self.assertEqual(admin.post('/admin/settings', data={'section': 'enquiry_automation'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
