import json
import unittest
import test_email_media as fixtures
import test_native_form_browser as browsers
from client_notifications import render_notification

main=fixtures.main
class EmailLayoutTest(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.EmailMediaTest();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def post(self,action,layout,fields=None):
        return self.fixture.admin.post('/admin/email-layout/booking/'+action,json={'layout':layout,'fields':fields or {}},headers={'X-CSRF-Token':self.fixture.csrf})
    def test_draft_preview_save_and_delivered_layout_agree(self):
        self.fixture.add('image',label='Logo',content=fixtures.PNG,filename='logo.png')
        self.fixture.add('link',label='Read guide',url='https://clpaints.com/guide')
        image,link=main.EmailMedia.query.order_by(main.EmailMedia.id).all()
        layout=dict(order=['footer',f'media-{link.id}','body',f'media-{image.id}','heading','portal'],font_size=20,padding=40,
            media={str(image.id):dict(width=50,align='right',caption='Caption <safe>'),str(link.id):dict(style='button')})
        fields={'notification_booking_body':'Unique body <script>alert(1)</script>'}
        preview=self.post('preview',layout,fields)
        self.assertEqual(preview.status_code,200)
        message=preview.json['html']
        self.assertLess(message.index('Read guide'),message.index('Unique body'))
        self.assertLess(message.index('Unique body'),message.index('Caption &lt;safe&gt;'))
        self.assertIn('width:50%',message);self.assertIn('font-size:20px',message)
        self.assertNotIn('<script>alert(1)</script>',message)
        self.assertIsNone(main.db.session.get(main.BusinessSetting,'email_layout_booking'))
        self.assertEqual(self.post('save',layout,fields).status_code,200)
        config=main.get_business_settings()
        _,_,_,sent=render_notification(config,'Client','booking','REF','Details','https://clpaints.com')
        self.assertLess(sent.index('Read guide'),sent.index('Unique body'))
        self.assertIn('src="cid:',sent);self.assertIn('width:50%',sent)
        main.db.session.delete(image);main.db.session.commit()
        self.assertEqual(self.fixture.admin.get('/admin/email-preview/booking').status_code,200)
    def test_authentication_and_css_block_validation(self):
        self.assertEqual(main.app.test_client().post('/admin/email-layout/booking/preview').status_code,302)
        self.assertEqual(self.fixture.admin.post('/admin/email-layout/booking/preview',json={}).status_code,400)
        for layout in [dict(order=['body','body']),dict(order=['media-9999']),dict(font='Arial;evil'),dict(background='url(evil)'),dict(width=99999),dict(line_height='NaN')]:
            self.assertEqual(self.post('preview',layout).status_code,400)
    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_live_typing_reorder_and_save_in_browser(self):
        page=self.fixture.admin.get('/admin/settings?tab=email')
        browsers.NativeFormBrowserTest().browser(page.data, '''
          const pause=()=>new Promise(resolve=>setTimeout(resolve,340));await pause();
          const body=document.querySelector('[data-email-composer="booking"] textarea');
          body.value='Live draft';body.dispatchEvent(new Event('input',{bubbles:true}));await pause();
          assert(window.layoutCalls.at(-1).fields.notification_booking_body==='Live draft','Draft sent for live preview');
          assert(document.querySelector('[data-email-preview]').srcdoc.includes('Draft preview'),'Live preview applied');
          document.querySelector('[data-layout-block="body"] button').click();await pause();
          assert(window.layoutCalls.at(-1).layout.order[0]==='body','Reordered block sent for preview');
          document.querySelector('[data-layout-save]').click();await pause();
          assert(window.layoutCalls.at(-1).action==='save','Explicit save');
          assert(document.querySelector('[data-layout-status]').textContent.includes('saved'),'Save status');
          document.querySelector('[data-email-select="reward"]').click();
          document.querySelector('[data-layout-save]').click();
          await new Promise(resolve=>setTimeout(resolve,30));
          assert(window.layoutCalls.at(-1).kind==='reward','Layout follows selected reward template');
        ''',width=390,setup='''
          window.layoutCalls=[];
          window.fetch=async(url,options)=>{const data=JSON.parse(options.body);data.kind=url.includes('/reward/')?'reward':'booking';data.action=url.endsWith('/save')?'save':'preview';window.layoutCalls.push(data);return {ok:true,json:async()=>({html:'<p>Draft preview</p>'})};};
        ''')
