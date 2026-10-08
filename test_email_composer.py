import unittest
import test_settings as fixtures
import test_native_form_browser as browsers

main=fixtures.main
class EmailComposerTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SettingsTest();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def test_saved_preview_and_general_settings(self):
        response=self.fixture.client.get('/admin/settings?tab=email')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'data-email-composer="booking"',response.data)
        self.assertIn(b'data-email-composer="reward"',response.data)
        self.assertNotIn(b'email-workspace',self.fixture.client.get('/admin/settings').data)
        preview=self.fixture.client.get('/admin/email-preview/reward?embed=1')
        self.assertEqual(preview.status_code,200)
        self.assertIn('no-store',preview.headers['Cache-Control'])
        self.assertNotIn(b'Admin navigation',preview.data)
        self.assertEqual(main.app.test_client().get('/admin/email-preview/reward?embed=1').status_code,302)
    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_composer_switch_tokens_and_attachment_controls(self):
        response=self.fixture.client.get('/admin/settings?tab=email')
        for width in (1280,390):
            browsers.NativeFormBrowserTest().browser(response.data, '''
              document.querySelector('[data-email-select="reward"]').click();
              const reward=document.querySelector('[data-email-composer="reward"]');
              assert(!reward.hidden && document.querySelector('[data-email-composer="booking"]').hidden,'Only selected composer visible');
              assert(document.querySelector('[data-email-preview]').getAttribute('src').includes('/reward?embed=1'),'Correct preview');
              const body=reward.querySelector('textarea');body.focus();body.setSelectionRange(0,0);
              reward.querySelector('[data-email-token="{name}"]').click();
              assert(body.value.startsWith('{name}'),'Token inserted at cursor');
              assert(reward.querySelector('[data-email-draft-status]').textContent==='Unsaved changes','Draft status');
              reward.querySelector('[data-email-add="link"]').click();
              const media=document.querySelector('.email-media-drawer form');
              assert(document.querySelector('.email-media-drawer').open,'Attachment drawer opens');
              assert(media.querySelector('[name="area"]').value==='reward','Correct template scope');
              assert(media.querySelector('[name="file"]').disabled && !media.querySelector('[name="url"]').disabled,'Relevant link fields only');
              assert(document.querySelector('.email-workspace').getBoundingClientRect().right<=innerWidth+1,'Workspace fits screen');
            ''',width=width)
