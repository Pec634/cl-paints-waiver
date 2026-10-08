import base64
from io import BytesIO
import unittest
from unittest.mock import patch
import test_client_notifications as fixtures

main=fixtures.main
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfa0AAAAASUVORK5CYII=')

class EmailMediaTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NotificationsTest(); self.fixture.setUp()
        self.admin=self.fixture.admin
        self.admin.get('/admin/settings?tab=email')
        with self.admin.session_transaction() as state: self.csrf=state['settings_csrf']
    def tearDown(self): self.fixture.tearDown()
    def add(self,kind,area='both',label='Information',content=None,filename=None,url=None):
        data=dict(csrf_token=self.csrf,kind=kind,area=area,label=label)
        if content is not None: data['file']=(BytesIO(content),filename)
        if url is not None: data['url']=url
        return self.admin.post('/admin/settings/email-media',data=data)
    def test_preview_and_real_send_payload_includes_inline_image_document_and_links(self):
        self.add('image',label='Our logo',content=PNG,filename='logo.png')
        self.add('document',area='booking',label='Event guide',content=b'%PDF-1.4\nTest document',filename='guide.pdf')
        self.add('link',label='Information <guide>',url='https://clpaints.com/information?a=1&b=2')
        with patch.object(main,'send_client_email',self.fixture.fixture.email_patch.temp_original), patch.object(main,'RESEND_API_KEY','test'),patch.object(main.resend.Emails,'send') as send:
            self.fixture.update()
        payload=send.call_args.args[0]
        self.assertEqual(len(payload['attachments']),2)
        image=payload['attachments'][0]
        self.assertIn('cid:'+image['content_id'],payload['html'])
        self.assertEqual(base64.b64decode(image['content']),PNG)
        self.assertEqual(payload['attachments'][1]['filename'],'guide.pdf')
        self.assertIn('Information &lt;guide&gt;',payload['html'])
        self.assertIn('https://clpaints.com/information',payload['text'])
        preview=self.admin.get('/admin/email-preview/booking')
        self.assertNotIn(b'src="cid:',preview.data)
        self.assertIn(b'Download attachment: Event guide',preview.data)
        self.assertNotIn(b'Event guide',self.admin.get('/admin/email-preview/reward').data)
    def test_permissions_validation_and_removal(self):
        self.assertEqual(self.admin.post('/admin/settings/email-media',data={}).status_code,400)
        for url in ['javascript:alert(1)','http://example.com','https://user:password@example.com']:
            self.add('link',url=url)
        self.add('image',content=b'<svg>unsafe</svg>',filename='picture.svg')
        self.add('document',content=b'fake',filename='document.docx')
        self.assertEqual(main.EmailMedia.query.count(),0)
        self.add('document',content=b'Information',filename='guide.txt')
        item=main.EmailMedia.query.one()
        path=f'/admin/settings/email-media/{item.id}/file'
        self.assertEqual(self.fixture.client.get(path).status_code,302)
        response=self.admin.get(path)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertIn('no-store',response.headers['Cache-Control']); response.close()
        self.admin.post(f'/admin/settings/email-media/{item.id}/delete',data={'csrf_token':self.csrf})
        self.assertEqual(main.EmailMedia.query.count(),0)
        self.assertEqual(main.app.extensions['email_media_attachments']('booking'),[])
