"""Successful sign-in audit history and admin-only client visibility."""
import unittest
from datetime import datetime, timedelta
import test_client_portal as fixtures

main = fixtures.main


class ClientLoginHistoryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True

    def tearDown(self):
        self.fixture.tearDown()

    def test_only_successful_verification_records_login_once(self):
        code = self.fixture.request_code()
        challenge = main.ClientLoginCode.query.one()
        challenge_id = challenge.id
        self.assertEqual(main.ClientLoginEvent.query.count(), 0)
        wrong = '000000' if code != '000000' else '111111'
        self.fixture.verify(wrong)
        self.assertEqual(main.ClientLoginEvent.query.count(), 0)
        self.assertEqual(self.fixture.verify(code).status_code, 302)
        event = main.ClientLoginEvent.query.one()
        self.assertEqual(event.client_id, main.ClientAccount.query.one().id)
        self.assertEqual(event.method, 'signup')
        self.assertFalse(event.remembered)
        self.assertLess(abs((datetime.utcnow() - event.signed_in_at).total_seconds()), 10)
        self.client.get('/client/')
        self.client.get('/client/account')
        with self.client.session_transaction() as session:
            session['client_challenge'] = challenge_id
        self.fixture.verify(code)
        self.assertEqual(main.ClientLoginEvent.query.count(), 1)

    def test_existing_account_login_records_remembered_session(self):
        account = self.fixture.signup()
        self.client.post('/client/logout', data={'csrf_token': self.fixture.csrf()})
        # Existing challenge is consumed; remove it to avoid resend throttling in this test.
        main.ClientLoginCode.query.delete()
        main.db.session.commit()
        code = self.fixture.request_code(signup=False)
        with self.client.session_transaction() as session:
            session['client_pending_remember'] = True
        self.assertEqual(self.fixture.verify(code).status_code, 302)
        event = main.ClientLoginEvent.query.order_by(main.ClientLoginEvent.id.desc()).first()
        self.assertEqual(main.ClientLoginEvent.query.count(), 2)
        self.assertEqual(event.client_id, account.id)
        self.assertEqual(event.method, 'email_code')
        self.assertTrue(event.remembered)

    def test_admin_history_is_client_scoped_paginated_and_private(self):
        account = self.fixture.signup()
        other = main.ClientAccount(email='other@example.com', first_name='Other', last_name='Person')
        main.db.session.add(other)
        main.db.session.flush()
        main.db.session.add(main.ClientLoginEvent(client_id=other.id, signed_in_at=datetime(2001, 1, 1), method='email_code', remembered=True))
        for day in range(26):
            main.db.session.add(main.ClientLoginEvent(client_id=account.id, signed_in_at=datetime(2026, 7, 1) + timedelta(days=day), method='email_code', remembered=False))
        main.db.session.commit()
        path = f'/admin/clients/{account.id}?tab=logins'
        response = self.admin.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login history', response.data)
        self.assertIn(b'BST', response.data)
        self.assertNotIn(b'01/01/2001', response.data)
        self.assertIn(b'Page 1 of 2', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn(b'Page 2 of 2', self.admin.get(path + '&page=2').data)
        self.assertEqual(self.client.get(path).status_code, 302)
        listing = self.admin.get('/admin/clients')
        self.assertIn(b'Last login:', listing.data)
        self.assertIn(b'Login history (27)', listing.data)
        self.assertIn('no-store', listing.headers['Cache-Control'])

    def test_existing_account_without_tracking_has_honest_empty_state(self):
        account = main.ClientAccount(email='legacy@example.com', first_name='Legacy', last_name='Client')
        main.db.session.add(account)
        main.db.session.commit()
        response = self.admin.get(f'/admin/clients/{account.id}?tab=logins')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Earlier login history is unavailable', response.data)
        self.assertEqual(main.ClientLoginEvent.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
