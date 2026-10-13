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

    def test_text_sections_between_media_preserve_order_and_placeholders(self):
        self.fixture.add('link',label='Read more',url='https://clpaints.com/guide')
        link=main.EmailMedia.query.one()
        layout=dict(text_blocks={'text-first':{'text':'Hello {name}, first paragraph.'},
                                 'text-second':{'text':'Final paragraph about {reference}: {details} <safe>'}},
                    order=['heading','body','text-first',f'media-{link.id}','text-second','portal','footer'])
        preview=self.post('preview',layout)
        self.assertEqual(preview.status_code,200)
        message=preview.json['html']
        self.assertLess(message.index('first paragraph'),message.index('Read more'))
        self.assertLess(message.index('Read more'),message.index('Final paragraph'))
        self.assertIn('Hello Sample client',message)
        self.assertIn('&lt;safe&gt;',message)
        self.assertEqual(self.post('save',layout).status_code,200)
        config=main.get_business_settings()
        _,plain,_,sent=render_notification(config,'Real client','booking','REF-123','Real update','https://clpaints.com')
        self.assertIn('Hello Real client',sent)
        self.assertIn('REF-123: Real update',sent)
        self.assertLess(plain.index('first paragraph'),plain.index('Read more'))
        self.assertLess(plain.index('Read more'),plain.index('Final paragraph'))
        self.assertIn('text-second',main.db.session.get(main.BusinessSetting,'email_layout_booking').value)
        self.assertEqual(self.fixture.admin.get('/admin/email-preview/booking').status_code,200)
        layout['text_blocks'].pop('text-first');layout['order'].remove('text-first')
        self.assertEqual(self.post('save',layout).status_code,200)
        self.assertNotIn('first paragraph',render_notification(config,'Client','booking','REF','Update','https://clpaints.com')[3])

    def test_extra_text_block_validation(self):
        for blocks in [{'invalid':{'text':'Text'}},{'text-one':{'text':'{unknown}'}},
                       {'text-one':{'text':'x'*5001}}, {'text-one':{'text':123}},
                       {f'text-{index}':{'text':'Block'} for index in range(9)}]:
            self.assertEqual(self.post('preview',dict(text_blocks=blocks)).status_code,400)

    def test_enquiry_template_preview_save_and_media_scope(self):
        self.fixture.add('link',area='both',label='Booking and reward guide',url='https://clpaints.com/booking-guide')
        self.fixture.add('link',area='website_enquiry',label='Visitor guide',url='https://clpaints.com/visitor-guide')
        for kind in ('portal_enquiry','website_enquiry'):
            fields={f'notification_{kind}_subject':'Reply about {reference}',
                    f'notification_{kind}_body':'Dear {name},\n\n{details}\n\nOur custom sign-off'}
            response=self.fixture.admin.post(f'/admin/email-layout/{kind}/save',json={'layout':{'text_blocks':{'text-after':{'text':'Extra enquiry text'}}},'fields':fields},headers={'X-CSRF-Token':self.fixture.csrf})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(self.fixture.admin.get(f'/admin/email-preview/{kind}?embed=1').status_code,200)
            link='' if kind=='website_enquiry' else 'https://clpaints.com/client/contact'
            subject,plain,_,message=render_notification(main.get_business_settings(),'Visitor',kind,'Enquiry #42','Actual written reply',link)
            self.assertEqual(subject,'Reply about Enquiry #42')
            self.assertIn('Dear Visitor',message)
            self.assertIn('Actual written reply',plain)
            self.assertIn('Extra enquiry text',message)
            self.assertNotIn('Booking and reward guide',message)
            if kind=='website_enquiry':
                self.assertIn('Visitor guide',message)
                self.assertNotIn('href=""',message)
            else:self.assertNotIn('Visitor guide',message)
        response=self.fixture.admin.post('/admin/email-layout/website_enquiry/save',json={'fields':{'notification_website_enquiry_body':'No reply placeholder'}},headers={'X-CSRF-Token':self.fixture.csrf})
        self.assertEqual(response.status_code,400)
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
