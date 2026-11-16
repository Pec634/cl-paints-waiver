import unittest
from unittest.mock import patch
import test_native_forms as fixtures
import test_native_form_browser as browsers

main = fixtures.main


class GuestGiveawayTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeFormsTest(); self.fixture.setUp()
        self.form = self.fixture.create('giveaway')
        self.path = f'/forms/{self.form.id}'
        self.guest = main.app.test_client()

    def tearDown(self):
        self.fixture.tearDown()

    def data(self, email='guest@example.com'):
        self.assertEqual(self.guest.get(self.path).status_code, 200)
        with self.guest.session_transaction() as state:
            return dict(csrf_token=state['client_csrf'], submission_token=state[f'native_form_{self.form.id}'],
                        guest_email=email, agree='yes')

    def test_email_only_entry_without_signup_or_authenticated_session(self):
        page = self.guest.get(self.path)
        self.assertIn(b'No portal sign-up or sign-in is required', page.data)
        self.assertIn(b'name="guest_email"', page.data)
        self.assertNotIn(b'name="guest_first_name"', page.data)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            page = self.guest.post(self.path, data=self.data('Guest@EXAMPLE.COM'), follow_redirects=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Your giveaway entry has been received', page.data)
        entry = fixtures.Submission.query.filter_by(form_id=self.form.id).one()
        self.assertEqual(entry.email, 'guest@example.com')
        self.assertEqual(entry.terms_snapshot, self.form.terms)
        self.assertEqual(send.call_args.args[0], 'guest@example.com')
        with self.guest.session_transaction() as state:
            self.assertNotIn('client_id', state)
        self.assertEqual(self.guest.get(f'/client/form-submissions/{entry.id}').status_code, 404)
        self.assertEqual(self.guest.get('/client/account').status_code, 302)
        self.assertEqual(main.app.test_client().get(f'/giveaways/{self.form.id}/entry-received').status_code, 404)

    def test_duplicates_do_not_reveal_or_change_existing_client_details(self):
        self.fixture.client.post(self.path, data=self.fixture.data(self.form))
        entry = fixtures.Submission.query.filter_by(form_id=self.form.id).one()
        account = main.db.session.get(main.ClientAccount, entry.client_id)
        original = (account.first_name, account.last_name, account.phone, account.address)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            page = self.guest.post(self.path, data=self.data(account.email.upper()), follow_redirects=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Your giveaway entry has been received', page.data)
        self.assertNotIn(f'{account.first_name} {account.last_name}'.encode(), page.data)
        send.assert_not_called()
        self.assertEqual(fixtures.Submission.query.filter_by(form_id=self.form.id).count(), 1)
        self.assertEqual((account.first_name, account.last_name, account.phone, account.address), original)

    def test_rules_csrf_email_and_spam_checks_remain_required(self):
        before = main.ClientAccount.query.count()
        data = self.data()
        self.assertEqual(self.guest.post(self.path, data=dict(data, csrf_token='bad')).status_code, 400)
        for change in ({'agree': ''}, {'guest_email': 'bad'}, {'contact_website': 'spam'}):
            page = self.guest.post(self.path, data=dict(data, **change))
            self.assertIn(b'name="guest_email"', page.data)
            self.assertIn(b'booking-admin-error', page.data)
        self.assertEqual(main.ClientAccount.query.count(), before)
        self.assertEqual(fixtures.Submission.query.count(), 0)
        photo = self.fixture.create('photo')
        self.assertEqual(self.guest.get(f'/forms/{photo.id}').status_code, 302)
        self.assertEqual(self.guest.post(f'/forms/{photo.id}', data=data).status_code, 401)

    def test_guest_entry_participates_in_existing_draw(self):
        self.guest.post(self.path, data=self.data())
        entry = fixtures.Submission.query.filter_by(form_id=self.form.id).one()
        with patch.dict(main.app.extensions, {'client_notice_deliver': lambda *args: True}):
            response = self.fixture.admin.post(f'/admin/native-forms/{self.form.id}/draw', data={'csrf_token': 'admin-token'})
        self.assertEqual(response.status_code, 200)
        draw = main.db.session.get(main.db._giveaway_draw, self.form.id)
        self.assertEqual(draw.client_id, entry.client_id)
        self.assertEqual(draw.entrant_count, 1)
        self.assertEqual(main.app.extensions['client_notification_model'].query.filter_by(email=entry.email, reference=f'Giveaway-{self.form.id}').count(), 1)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_mobile_guest_form_requires_email_and_rules_without_name_fields(self):
        page = self.guest.get(self.path)
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const email = document.querySelector('[name="guest_email"]');
            assert(email && email.required, 'Email is required');
            assert(!document.querySelector('[name="guest_first_name"]'), 'Guest entry should not require names');
            assert(document.querySelector('[name="agree"]').required, 'Rules agreement is required');
            assert(!document.querySelector('#client-navigation'), 'Guest entry should not show account navigation');
            assert(email.getBoundingClientRect().right <= innerWidth + 1, 'Email field overflows phone');
        ''', width=390)
