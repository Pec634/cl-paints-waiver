import unittest
import test_booking_messages as fixtures
import test_native_form_browser as browsers

main=fixtures.main
class CommunicationsTest(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.BookingMessagesTest();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def test_sections_auth_templates_and_configuration_save(self):
        for path in ['/admin/notifications','/admin/communications/messages','/admin/communications/history','/admin/communications/templates','/admin/communications/configuration']:
            page=self.fixture.admin.get(path)
            self.assertEqual(page.status_code,200,page.data[:400])
            self.assertIn(b'Communications sections',page.data)
            self.assertEqual(main.app.test_client().get(path).status_code,302)
        page=self.fixture.admin.get('/admin/communications/templates')
        self.assertIn(b'data-email-composer="booking"',page.data)
        with self.fixture.admin.session_transaction() as state: csrf=state['settings_csrf']
        response=self.fixture.admin.post('/admin/settings',data=dict(section='operations',return_to='communications',csrf_token=csrf,calendar_buffer_minutes='60',reminder_days='3',public_app_url='https://clpaints.com'))
        self.assertTrue(response.location.endswith('/admin/communications/configuration'))
        self.assertEqual(main.get_business_settings()['reminder_days'],'3')
    def test_message_filters_do_not_mark_read_and_history_search(self):
        self.fixture.client.post(self.fixture.client_path,data=self.fixture.data(self.fixture.client,self.fixture.client_path,'Client question'))
        page=self.fixture.admin.get('/admin/communications/messages?view=unread')
        self.assertIn(b'Client question',page.data)
        self.assertIsNone(main.BookingMessage.query.one().read_at)
        self.fixture.admin.post(self.fixture.admin_path,data=self.fixture.data(self.fixture.admin,self.fixture.admin_path,'Admin response'))
        page=self.fixture.admin.get('/admin/communications/messages?view=sent')
        self.assertIn(b'Admin response',page.data);self.assertNotIn(b'Client question',page.data)
        Notice=main.notification_models[1]
        main.db.session.add(Notice(email='client@example.com',kind='booking',reference='REF-HUB',details='Recorded update',email_sent=True));main.db.session.commit()
        page=self.fixture.admin.get('/admin/communications/history?q=REF-HUB&state=accepted')
        self.assertIn(b'Recorded update',page.data)
        self.assertNotIn(b'Recorded update',self.fixture.admin.get('/admin/communications/history?state=failed').data)
        self.assertEqual(self.fixture.admin.get('/admin/communications/history?source=campaigns').status_code,200)
    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_hub_mobile_sections(self):
        page=self.fixture.admin.get('/admin/communications/messages')
        browsers.NativeFormBrowserTest().browser(page.data, '''
          const nav=document.querySelector('nav[aria-label="Communications sections"]');
          assert(nav.querySelectorAll('a').length===6,'All hub sections accessible');
          assert(nav.getBoundingClientRect().right<=innerWidth+1,'Hub navigation fits phone');
          assert(nav.querySelector('[aria-current="page"]').textContent==='Messages','Active section announced');
        ''',width=390)
    def test_enquiry_reply_and_accepted_campaign_history(self):
        enquiry=main.ClientEnquiry(client_id=self.fixture.fixture.account.id,subject='Central enquiry',message='Question for admin')
        main.db.session.add(enquiry);main.db.session.commit()
        page=self.fixture.admin.get('/admin/communications/messages?view=enquiries')
        self.assertIn(b'Central enquiry',page.data)
        response=self.fixture.admin.post(f'/admin/enquiries/{enquiry.id}/update',data=dict(csrf_token='admin-token',return_to='communications',status='replied',reply='Central reply'))
        self.assertIn('view=enquiries',response.location)
        self.assertIn(b'Central reply',self.fixture.admin.get('/admin/communications/history').data)
        Campaign,Delivery=main.marketing_models[1:]
        campaign=Campaign(subject='Accepted campaign',body='Campaign content')
        main.db.session.add(campaign);main.db.session.flush()
        main.db.session.add(Delivery(campaign_id=campaign.id,email='client@example.com',status='accepted'));main.db.session.commit()
        self.assertIn(b'Accepted campaign',self.fixture.admin.get('/admin/communications/history?source=campaigns&state=accepted').data)
