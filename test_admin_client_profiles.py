import unittest
import test_booking_messages as fixtures
import test_native_form_browser as browsers

main=fixtures.main

class AdminClientProfilesTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BookingMessagesTest(); self.fixture.setUp()
        self.admin,self.client=self.fixture.admin,self.fixture.client
        self.account=self.fixture.fixture.account
        self.path=f'/admin/clients/{self.account.id}'
    def tearDown(self): self.fixture.tearDown()

    def test_profile_search_tabs_and_record_isolation(self):
        self.fixture.fixture.fixture.booking('unrelated@example.com',event_type='Unrelated secret event')
        self.fixture.booking.email=self.account.email.upper()
        main.db.session.commit()
        for tab in ('bookings','payments','waivers','messages','rewards','notes'):
            page=self.admin.get(self.path,query_string={'tab':tab})
            self.assertEqual(page.status_code,200, page.data[:500])
            self.assertIn('no-store',page.headers['Cache-Control'])
            self.assertNotIn(b'Unrelated secret event',page.data)
            self.assertNotIn(self.fixture.booking.date_of_birth.isoformat().encode(),page.data)
        self.assertIn(self.fixture.booking.public_reference.encode(),self.admin.get(self.path).data)
        self.assertIn(self.path.encode(),self.admin.get('/admin/search',query_string={'q':self.account.email}).data)
        self.assertIn(self.path.encode(),self.admin.get('/admin/clients').data)
        self.assertEqual(self.admin.get('/admin/clients/999999').status_code,404)
        self.assertEqual(self.admin.get(self.path+'?tab=unknown').status_code,400)

    def test_private_notes_require_admin_csrf_and_escape_content(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code,302)
        self.assertEqual(self.client.get(self.path).status_code,302)
        self.assertEqual(self.admin.post(self.path,data={'note':'unauthorised'}).status_code,400)
        response=self.admin.post(self.path,data={'note':'<script>PRIVATE-NOTE</script>','csrf_token':'admin-token'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(main.AdminClientNote.query.count(),1)
        page=self.admin.get(response.location)
        self.assertIn(b'&lt;script&gt;PRIVATE-NOTE&lt;/script&gt;',page.data)
        self.assertNotIn(b'<script>PRIVATE-NOTE</script>',page.data)
        self.assertNotIn(b'PRIVATE-NOTE',self.client.get('/client/').data)
        self.assertEqual(main.phone_push_models[1].query.count(),0)

    def test_profile_message_summary_keeps_unread_and_note_pagination(self):
        data=self.fixture.data(self.client,self.fixture.client_path,'Profile message')
        self.client.post(self.fixture.client_path,data=data)
        page=self.admin.get(self.path+'?tab=messages')
        self.assertIn(b'Profile message',page.data)
        self.assertIn(b'1 unread client message',page.data)
        self.assertIsNone(main.BookingMessage.query.one().read_at)
        main.db.session.add_all([main.AdminClientNote(client_id=self.account.id,body=f'Note {i}') for i in range(26)])
        main.db.session.commit()
        page=self.admin.get(self.path+'?tab=notes')
        self.assertIn(b'Page 1 of 2',page.data)
        self.assertNotIn(b'>Note 0<',page.data)
        self.assertIn(b'>Note 0<',self.admin.get(self.path+'?tab=notes&page=2').data)

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_profile_navigation_at_phone_width(self):
        page=self.admin.get(self.path)
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const nav=document.querySelector('nav[aria-label="Client profile sections"]');
            assert(nav.querySelectorAll('a').length===6,'All profile sections available');
            assert(nav.querySelector('[aria-current="page"]').textContent==='Bookings','Current section announced');
            assert(nav.getBoundingClientRect().right<=innerWidth+1,'Section navigation fits phone width');
            assert(document.querySelector('.admin aside a[aria-current="page"]').textContent==='Clients','Clients navigation active');
        ''',width=390)
