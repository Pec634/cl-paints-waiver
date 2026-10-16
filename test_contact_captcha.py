import json
import os
import unittest
from unittest.mock import MagicMock, patch
from contact_captcha import verify


class ContactCaptchaTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'RECAPTCHA_SITE_KEY': 'site',
            'RECAPTCHA_SECRET_KEY': 'secret', 'RECAPTCHA_ALLOWED_HOSTNAMES': 'my.clpaints.com'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def response(self, result):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(result).encode()
        return response

    def test_success_and_post_request(self):
        with patch('contact_captcha.urlopen', return_value=self.response(
                {'success': True, 'hostname': 'my.clpaints.com'})) as send:
            self.assertTrue(verify('token', 'https://my.clpaints.com'))
        req = send.call_args.args[0]
        self.assertEqual(req.get_method(), 'POST')
        self.assertIn(b'response=token', req.data)

    def test_rejected_expired_wrong_hostname_and_invalid_response(self):
        for result in ({'success': False, 'error-codes': ['timeout-or-duplicate']},
                       {'success': True, 'hostname': 'another.example'}, [],
                       {'success': True, 'hostname': None}):
            with self.subTest(result=result), patch('contact_captcha.urlopen', return_value=self.response(result)):
                self.assertFalse(verify('token', 'https://my.clpaints.com'))

    def test_missing_token_and_network_failure(self):
        with patch('contact_captcha.urlopen') as send:
            self.assertFalse(verify('', 'https://my.clpaints.com'))
            send.assert_not_called()
        with patch('contact_captcha.urlopen', side_effect=TimeoutError):
            self.assertFalse(verify('token', 'https://my.clpaints.com'))

    def test_unconfigured_and_partial_configuration(self):
        with patch.dict(os.environ, {'RECAPTCHA_SITE_KEY': '', 'RECAPTCHA_SECRET_KEY': ''}):
            self.assertTrue(verify('', 'https://my.clpaints.com'))
        with patch.dict(os.environ, {'RECAPTCHA_SECRET_KEY': ''}):
            self.assertFalse(verify('token', 'https://my.clpaints.com'))
