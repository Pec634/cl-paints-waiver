"""Local preview must never grant access on a deployed or non-local app."""
import os
import unittest
from unittest.mock import patch
import test_business_tools as fixtures


class LocalPreviewTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp()
        self.app=fixtures.main.app
        self.debug=self.app.debug
        self.client=self.app.test_client()

    def tearDown(self):
        self.app.debug=self.debug
        self.fixture.tearDown()

    def test_preview_restrictions_and_test_identity(self):
        with patch.dict(os.environ,{'CLIENT_LOCAL_PREVIEW':'true','RENDER':''}):
            self.app.debug=True
            page=self.client.get('/client/login')
            self.assertIn(b'Preview portal locally',page.data)
            with self.client.session_transaction() as session:token=session['client_csrf']
            self.assertEqual(self.client.post('/client/local-preview',data={}).status_code,400)
            response=self.client.post('/client/local-preview',data={'csrf_token':token})
            self.assertEqual(response.status_code,302)
            with self.client.session_transaction() as session:
                account=fixtures.main.db.session.get(fixtures.main.ClientAccount,session['client_id'])
                self.assertEqual(account.email,'portal-preview@example.invalid')
            self.assertEqual(self.client.get('/face-paint-studio').status_code,200)
            self.assertEqual(self.client.post('/client/local-preview',environ_overrides={'REMOTE_ADDR':'192.168.1.2'}).status_code,404)
            self.assertEqual(self.client.post('/client/local-preview',base_url='https://example.com').status_code,404)
            self.app.debug=False
            self.assertEqual(self.client.post('/client/local-preview').status_code,404)
            self.app.debug=True
            with patch.dict(os.environ,{'RENDER':'true'}):
                self.assertEqual(self.client.post('/client/local-preview').status_code,404)
        with patch.dict(os.environ,{'CLIENT_LOCAL_PREVIEW':'false'}):
            self.assertEqual(self.client.post('/client/local-preview').status_code,404)
