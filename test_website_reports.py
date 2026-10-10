import unittest
import test_native_forms as fixtures

main=fixtures.main

class WebsiteReportsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeFormsTest();self.fixture.setUp()
        self.admin=self.fixture.admin;self.guest=main.app.test_client()
    def tearDown(self):self.fixture.tearDown()
    def test_counts_sources_devices_and_access(self):
        for _ in range(2):self.guest.get('/services',headers={'User-Agent':'Mozilla iPhone Mobile','Referer':'https://www.facebook.com/private/path?email=private@example.com'})
        row=main.website_report_model.query.one()
        self.assertEqual(row.count,2);self.assertEqual(row.device,'Mobile');self.assertEqual(row.source,'www.facebook.com');self.assertEqual(row.country,'Unavailable')
        self.assertEqual(self.guest.get('/admin/website-report').status_code,302)
        page=self.admin.get('/admin/website-report')
        self.assertEqual(page.status_code,200);self.assertIn('2 page views',page.text);self.assertNotIn('private@example.com',page.text)
    def test_staff_bots_previews_and_private_pages_excluded(self):
        self.admin.get('/')
        self.guest.get('/',headers={'User-Agent':'Googlebot'})
        self.guest.get('/',headers={'Sec-Fetch-Dest':'iframe'})
        self.guest.get('/client/login')
        self.guest.get('/missing-page')
        self.assertEqual(main.website_report_model.query.count(),0)
        self.guest.get('/')
        self.assertEqual(main.website_report_model.query.one().source,'Direct / unavailable')
        self.assertIn('Choose a valid start date',self.admin.get('/admin/website-report?start=bad').text)
        self.assertIn('No website visits recorded',self.admin.get('/admin/website-report?start=2000-01-01&end=2000-01-02').text)
