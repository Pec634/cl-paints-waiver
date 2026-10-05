from datetime import datetime, timedelta
import os
import re
import unittest
from unittest.mock import patch
import test_client_portal as fixtures

main=fixtures.main
Attempt,Challenge=main.admin_security_models


class AdminSecurityTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ClientPortalTest();self.fixture.setUp()
        self.client=main.app.test_client()

    def tearDown(self):self.fixture.tearDown()

    def token(self):
        self.client.get('/admin/login')
        with self.client.session_transaction() as session:return session['admin_login_csrf']

    def test_login_csrf_throttle_and_inactivity(self):
        self.assertEqual(self.client.post('/admin/login',data={'password':'wrong'}).status_code,400)
        token=self.token()
        with patch.object(main,'ADMIN_PASSWORD','test-password'),patch.dict(os.environ,{'ADMIN_EMAIL_VERIFICATION':'false'}):
            for _ in range(5):self.client.post('/admin/login',data={'csrf_token':token,'password':'wrong'})
            self.assertEqual(self.client.post('/admin/login',data={'csrf_token':token,'password':'test-password'}).status_code,429)
            Attempt.query.delete();main.db.session.commit()
            self.assertEqual(self.client.post('/admin/login',data={'csrf_token':token,'password':'test-password'}).status_code,302)
        with self.client.session_transaction() as session:
            session['admin_last_activity']=datetime.utcnow().timestamp()-1801
        self.assertIn('expired=1',self.client.get('/admin/dashboard').location)
        with self.client.session_transaction() as session:self.assertNotIn('admin_authenticated',session)

    def test_email_verification_required_and_consumed(self):
        token=self.token()
        with patch.object(main,'ADMIN_PASSWORD','test-password'),patch.object(main,'ADMIN_EMAIL','admin@example.com'),patch.dict(os.environ,{'ADMIN_EMAIL_VERIFICATION':'true'}),patch.object(main,'send_client_email',return_value=True) as sender:
            response=self.client.post('/admin/login',data={'csrf_token':token,'password':'test-password'})
        self.assertTrue(response.location.endswith('/admin/verify'))
        code=re.search(r'code is (\d{6})',sender.call_args.args[2]).group(1)
        with self.client.session_transaction() as session:self.assertNotIn('admin_authenticated',session)
        self.client.get('/admin/verify')
        with self.client.session_transaction() as session:token=session['admin_verify_csrf']
        self.assertEqual(self.client.post('/admin/verify',data={'csrf_token':token,'code':code}).status_code,302)
        self.assertTrue(Challenge.query.one().consumed)
        with self.client.session_transaction() as session:self.assertTrue(session['admin_authenticated'])
        page=self.client.get('/admin/dashboard')
        self.assertEqual(page.headers['Cache-Control'],'no-store')
        self.assertEqual(page.headers['X-Frame-Options'],'SAMEORIGIN')

    def test_verification_delivery_failure_does_not_sign_in(self):
        token=self.token()
        with patch.object(main,'ADMIN_PASSWORD','test-password'),patch.object(main,'ADMIN_EMAIL','admin@example.com'),patch.dict(os.environ,{'ADMIN_EMAIL_VERIFICATION':'true'}),patch.object(main,'send_client_email',return_value=False):
            response=self.client.post('/admin/login',data={'csrf_token':token,'password':'test-password'})
        self.assertEqual(response.status_code,503)
        with self.client.session_transaction() as session:self.assertNotIn('admin_authenticated',session)


if __name__=='__main__':unittest.main()
