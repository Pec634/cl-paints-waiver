import json
import unittest
import test_email_media as fixtures
main=fixtures.main

class EmailPresetsTest(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.EmailMediaTest();self.fixture.setUp();self.admin=self.fixture.admin;self.headers={'X-CSRF-Token':self.fixture.csrf}
    def tearDown(self):self.fixture.tearDown()
    def post(self,path,data):return self.admin.post(path,json=data,headers=self.headers)
    def preset(self):
        self.fixture.add('image',label='Preset logo',content=fixtures.PNG,filename='logo.png')
        image=main.EmailMedia.query.one()
        response=self.post('/admin/email-presets/save',dict(name='Enquiry welcome',kind='booking',
            fields={'notification_booking_subject':'Hello {name}','notification_booking_body':'Welcome {name}: {details}'},
            layout={'text_blocks':{'text-extra':{'text':'After the picture'}},'order':['body',f'media-{image.id}','text-extra','portal','footer','heading']}))
        self.assertEqual(response.status_code,200,response.data)
        return response.json['id'],image
    def test_independent_portable_preset_load_preview_and_apply(self):
        preset_id,image=self.preset()
        exported=self.admin.get(f'/admin/email-presets/{preset_id}/export')
        self.assertIn('attachment',exported.headers['Content-Disposition'])
        portable=json.loads(exported.data)
        self.assertTrue(portable['assets'][0]['content'])
        main.db.session.delete(image);main.db.session.commit()
        preset=self.admin.get(f'/admin/email-presets/{preset_id}/load').json
        self.assertEqual(preset['fields']['body'],'Welcome {name}: {details}')
        self.assertEqual(main.EmailMedia.query.count(),0)
        payload={'layout':preset['layout'],'assets':preset['assets'],'fields':{
            'notification_website_enquiry_subject':preset['fields']['subject'],
            'notification_website_enquiry_body':preset['fields']['body'],
            **{key:value for key,value in preset['fields'].items() if key.startswith('notification_')}}}
        preview=self.post('/admin/email-layout/website_enquiry/preview',payload)
        self.assertEqual(preview.status_code,200,preview.data)
        self.assertIn('data:image/png;base64,',preview.json['html'])
        self.assertEqual(main.EmailMedia.query.count(),0)
        self.assertIsNone(main.db.session.get(main.BusinessSetting,'email_layout_website_enquiry'))
        applied=self.post('/admin/email-layout/website_enquiry/save',payload)
        self.assertEqual(applied.status_code,200,applied.data)
        self.assertEqual(main.EmailMedia.query.one().area,'website')
        self.assertEqual(main.EmailMedia.query.one().content,fixtures.PNG)
        self.assertNotIn('media--',json.dumps(applied.json['layout']))
        self.assertEqual(self.post('/admin/email-layout/website_enquiry/save',payload).status_code,200)
        self.assertEqual(main.EmailMedia.query.count(),1)
        imported=self.post('/admin/email-presets/import',portable)
        self.assertEqual(imported.status_code,200)
        self.assertNotEqual(imported.json['id'],preset_id)
        self.assertEqual(self.post(f'/admin/email-presets/{preset_id}/delete',{}).status_code,200)
        self.assertIsNotNone(main.db.session.get(main.BusinessSetting,'email_layout_website_enquiry'))
    def test_auth_validation_and_library_limit(self):
        self.assertEqual(main.app.test_client().get('/admin/email-presets').status_code,302)
        self.assertEqual(self.admin.post('/admin/email-presets/save',json={}).status_code,400)
        self.assertEqual(self.post('/admin/email-presets/import',{'format':'wrong'}).status_code,400)
        preset_id,_=self.preset();portable=self.admin.get(f'/admin/email-presets/{preset_id}/load').json
        portable['assets'][0]['content']='not base64!'
        self.assertEqual(self.post('/admin/email-presets/import',portable).status_code,400)
        self.assertEqual(self.admin.get('/admin/email-presets/missing/load').status_code,404)
