import unittest
import json
import re
import test_client_portal as fixtures
import test_native_form_browser as browsers


class PublicWebsiteTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ClientPortalTest();self.fixture.setUp()
        self.client=fixtures.main.app.test_client()

    def tearDown(self):self.fixture.tearDown()

    def test_public_pages_and_private_admin(self):
        for path in ['/','/services','/about','/gallery','/contact']:
            page=self.client.get(path)
            self.assertEqual(page.status_code,200)
            self.assertEqual(page.data.count(b'<h1>'),1)
            self.assertIn(b'name="description"',page.data)
            self.assertIn(b'href="/booking"',page.data)
            self.assertIn(b'href="/client/login"',page.data)
        self.assertEqual(self.client.get('/admin/dashboard').status_code,302)

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_home_fits_phone(self):
        browsers.NativeFormBrowserTest().browser(self.client.get('/').data, '''
            assert(document.documentElement.scrollWidth<=innerWidth,'Homepage fits phone');
            assert(document.querySelector('.hero-photo img').complete,'Hero photo loads');
            assert(document.querySelector('.hero-photo img').naturalWidth>0,'Hero image available');
            assert(document.querySelector('nav a[aria-current="page"]').textContent==='Home','Current page identified');
            const menu=document.querySelector('.website-menu-toggle');
            menu.click();
            assert(menu.getAttribute('aria-expanded')==='true','Mobile menu expands');
            document.querySelector('.hero-photo .photo-expand').click();
            assert(document.querySelector('.website-lightbox').open,'Photo opens full size');
            document.querySelector('.website-lightbox button').click();
            assert(!document.querySelector('.website-lightbox').open,'Photo can close');
        ''',width=390)

    def test_studio_public_and_old_link_redirects(self):
        page=self.client.get('/face-paint-studio')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'data-player="guest"',page.data)
        self.assertNotIn(b'<form id="studio-community-share"',page.data)
        self.assertIn(b'Sign in to share your design',page.data)
        self.assertEqual(self.client.get('/client/face-paint-studio').location,'/face-paint-studio')

    def test_search_metadata_and_legacy_links(self):
        page = self.client.get('/', base_url='https://preview.example').get_data(as_text=True)
        self.assertIn('rel="canonical" href="https://www.clpaints.com/"', page)
        schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(schema['@type'], 'LocalBusiness')
        self.assertEqual(schema['areaServed'], ['Doncaster', 'South Yorkshire'])
        self.assertNotIn('aggregateRating', schema)
        self.assertIn('property="og:image"', page)
        self.assertIn('Football cheek painting', page)
        self.assertIn('<section class="section"><h2>From your idea', page)
        for old, new in [('/home','/'),('/home/','/'),('/gallery-1','/gallery'),('/gallery-1/','/gallery'),('/about-us/','/about')]:
            response = self.client.get(old)
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.location, new)
        self.assertIn(b'https://www.clpaints.com/gallery', self.client.get('/sitemap.xml').data)
        self.assertIn(b'Sitemap: https://www.clpaints.com/sitemap.xml', self.client.get('/robots.txt').data)
        self.assertIn('noindex', self.client.get('/client/login').headers['X-Robots-Tag'])
        self.assertNotIn('X-Robots-Tag', self.client.get('/').headers)
