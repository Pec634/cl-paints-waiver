import json
import unittest
import test_client_portal as fixtures


class WebsitePagesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.admin = fixtures.main.app.test_client()
        self.guest = fixtures.main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True
        self.admin.get('/admin/website-builder')
        with self.admin.session_transaction() as session:
            self.csrf = session['client_csrf']

    def tearDown(self):
        self.fixture.tearDown()

    def manage(self, **data):
        return self.admin.post('/admin/website-builder/pages', data=dict(csrf_token=self.csrf, **data))

    def test_custom_page_lifecycle(self):
        response = self.manage(action='add', name='Party packages', slug='party-packages')
        self.assertEqual(response.status_code, 302)
        key = response.location.split('page=')[1]
        self.assertEqual(self.guest.get('/pages/party-packages').status_code, 404)
        self.assertEqual(self.admin.get('/pages/party-packages').status_code, 200)
        builder = self.admin.get(response.location)
        self.assertIn(b'/pages/party-packages', builder.data)
        layout = {'_blocks': [{'cells': [{'kind': 'text', 'text': 'Our party packages'}]}]}
        saved = self.admin.post('/admin/website-builder', data=dict(page=key, action='publish',
                               csrf_token=self.csrf, layout=json.dumps(layout)))
        self.assertEqual(saved.status_code, 200)
        page = self.guest.get('/pages/party-packages')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Our party packages', page.data)
        self.assertIn(b'/pages/party-packages', self.guest.get('/sitemap.xml').data)
        self.assertIn(b'Party packages</a>', self.guest.get('/').data)
        self.assertEqual(self.manage(action='rename', page=key, name='Celebrations').status_code, 302)
        self.assertIn(b'Celebrations</a>', self.guest.get('/').data)
        self.assertEqual(self.guest.get('/pages/party-packages').status_code, 200)
        self.assertEqual(self.manage(action='remove', page=key).status_code, 302)
        self.assertEqual(self.guest.get('/pages/party-packages').status_code, 404)
        self.assertNotIn(b'/pages/party-packages', self.guest.get('/sitemap.xml').data)

    def test_builtin_rename_remove_and_permissions(self):
        self.assertEqual(self.manage(action='rename', page='services', name='What we offer').status_code, 302)
        self.assertIn(b'What we offer</a>', self.guest.get('/').data)
        self.assertEqual(self.manage(action='remove', page='services').status_code, 302)
        self.assertEqual(self.guest.get('/services').status_code, 404)
        self.assertEqual(self.manage(action='remove', page='home').status_code, 400)
        self.assertEqual(self.admin.post('/admin/website-builder/pages', data={'action': 'add'}).status_code, 400)
        self.assertEqual(self.guest.post('/admin/website-builder/pages').status_code, 302)
        self.assertEqual(self.manage(action='add', name='Bad', slug='../admin').status_code, 400)
        self.assertEqual(self.manage(action='add', name='New', slug='new').status_code, 302)
        self.assertEqual(self.manage(action='add', name='Duplicate', slug='new').status_code, 400)

    def test_workspace_tabs_resize_and_page_status_browser(self):
        from test_native_form_browser import NativeFormBrowserTest
        NativeFormBrowserTest().browser(self.admin.get('/admin/website-builder').data, '''
            const tab=name=>document.getElementById('builder-tab-'+name);
            const pane=name=>document.getElementById('builder-pane-'+name);
            assert(tab('content').getAttribute('aria-selected')==='true','content is the initial tab');
            tab('pages').click();
            assert(!pane('pages').hidden&&pane('content').hidden,'pages tab shows page management');
            assert(pane('pages').textContent.includes('Published'),'page publication state is shown');
            assert(document.getElementById('builder-page-management').open,'page management is expanded');
            tab('design').click();
            assert(!pane('design').hidden,'design tab opens');
            assert([...pane('design').querySelectorAll('details')].every(node=>!node.open),'advanced settings start collapsed');
            tab('design').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
            assert(tab('pages').getAttribute('aria-selected')==='true','keyboard changes tabs');
            const divider=document.querySelector('.builder-divider');
            divider.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
            assert(divider.getAttribute('aria-valuenow')==='25','divider keyboard minimum');
            divider.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
            assert(divider.getAttribute('aria-valuenow')==='27','divider keyboard adjustment');
            assert(getComputedStyle(document.querySelector('.builder-toolbar')).position==='sticky','toolbar remains accessible');
            const tools=document.querySelector('.builder-tools');
            assert(getComputedStyle(tools).overflowY==='auto','editor scrolls independently');
        ''')
