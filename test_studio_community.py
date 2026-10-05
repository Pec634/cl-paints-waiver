import base64
import binascii
import struct
import unittest
import zlib
from datetime import datetime
import test_client_portal as fixtures

main=fixtures.main


def photograph():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',600,720,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\xff\xff\xff'*600)*720))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(png).decode()


class StudioCommunityTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ClientPortalTest();self.fixture.setUp()
        self.owner=self.fixture.client;self.viewer=main.app.test_client();self.admin=main.app.test_client()
        accounts=[]
        for email in ('owner@example.com','viewer@example.com'):
            account=main.ClientAccount(email=email,first_name='Test',last_name='Painter');main.db.session.add(account);main.db.session.flush();accounts.append(account)
        main.db.session.commit();self.account=accounts[0]
        for client,account in zip((self.owner,self.viewer),accounts):
            with client.session_transaction() as session:session.update(client_id=account.id,client_signed_in=datetime.now().timestamp(),client_csrf='token')
        with self.admin.session_transaction() as session:session.update(admin_authenticated=True,studio_admin_csrf='admin-token')
    def tearDown(self):self.fixture.tearDown()
    def share(self,**changes):
        data=dict(csrf_token='token',title='Butterfly',display_name='',theme='fantasy',template='illustrated',consent='yes',guidelines='yes',image=photograph());data.update(changes)
        return self.owner.post('/client/community-gallery/share',data=data)
    def test_approval_ownership_and_withdrawal(self):
        self.assertEqual(self.share().status_code,302);design=main.StudioDesign.query.one()
        self.assertEqual(design.display_name,'Anonymous painter')
        self.assertNotIn(b'Butterfly',self.viewer.get('/client/community-gallery').data)
        path=f'/client/community-gallery/{design.id}/image'
        self.assertEqual(self.viewer.get(path).status_code,404)
        self.assertEqual(self.owner.get(path).status_code,200)
        self.assertEqual(self.viewer.post(f'/client/community-gallery/{design.id}/unpublish',data={'csrf_token':'token'}).status_code,404)
        self.assertEqual(self.admin.get('/admin/studio-gallery').status_code,200)
        self.assertEqual(self.admin.post(f'/admin/studio-gallery/{design.id}/approve',data={'csrf_token':'bad'}).status_code,400)
        self.assertEqual(self.admin.post(f'/admin/studio-gallery/{design.id}/approve',data={'csrf_token':'admin-token'}).status_code,302)
        page=self.viewer.get('/client/community-gallery').data
        self.assertIn(b'Butterfly',page);self.assertNotIn(b'owner@example.com',page)
        self.assertEqual(self.viewer.get(path).status_code,200)
        self.owner.post(f'/client/community-gallery/{design.id}/unpublish',data={'csrf_token':'token'})
        self.assertEqual(self.viewer.get(path).status_code,404)
        self.assertEqual(self.admin.post(f'/admin/studio-gallery/{design.id}/approve',data={'csrf_token':'admin-token'}).status_code,400)
    def test_reports_favourites_and_admin_removal(self):
        self.share();design=main.StudioDesign.query.one();design.status='approved';main.db.session.commit()
        for action in ('favourite','report'):
            self.assertEqual(self.viewer.post(f'/client/community-gallery/{design.id}/{action}',data={'csrf_token':'token','reason':'Personal information'}).status_code,302)
        self.assertEqual(main.StudioFavourite.query.count(),1);self.assertEqual(main.StudioReport.query.count(),1)
        self.viewer.post(f'/client/community-gallery/{design.id}/report',data={'csrf_token':'token','reason':'Updated report'})
        self.assertEqual(main.StudioReport.query.count(),1)
        self.assertIn(b'Butterfly',self.viewer.get('/client/community-gallery?favourites=1').data)
        self.admin.post(f'/admin/studio-gallery/{design.id}/reject',data={'csrf_token':'admin-token'})
        self.assertTrue(main.StudioReport.query.one().resolved)
        self.assertEqual(self.viewer.get(f'/client/community-gallery/{design.id}/image').status_code,404)
    def test_invalid_inputs_and_authentication(self):
        for changes in ({'csrf_token':'wrong'},{'consent':'no'},{'guidelines':'no'},{'template':'my-upload'},{'image':'data:image/png;base64,PHN2Zz4='},{'title':'x'*81}):
            self.assertEqual(self.share(**changes).status_code,400)
        self.assertEqual(main.StudioDesign.query.count(),0)
        anonymous=main.app.test_client()
        self.assertEqual(anonymous.get('/client/community-gallery').status_code,302)
        self.assertEqual(self.viewer.get('/admin/studio-gallery').status_code,302)

if __name__=='__main__':unittest.main()
