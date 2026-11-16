import unittest
from unittest.mock import patch
import test_native_forms as fixtures
from giveaway_removal import eligible_accounts

main = fixtures.main


class GiveawayRemovalTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeFormsTest(); self.fixture.setUp()
        self.form = self.fixture.create('giveaway')
        self.admin, self.client = self.fixture.admin, self.fixture.client
        self.client.post(f'/forms/{self.form.id}', data=self.fixture.data(self.form))
        self.entry = fixtures.Submission.query.filter_by(form_id=self.form.id).one()
        self.account = main.db.session.get(main.ClientAccount, self.entry.client_id)
        self.path = f'/admin/native-forms/{self.form.id}/entrants/{self.entry.id}/remove'
        self.data = dict(csrf_token='admin-token', confirm_remove='yes', reason='Duplicate registration requested by client')

    def tearDown(self):
        self.fixture.tearDown()

    def test_remove_preserves_history_account_and_bookings(self):
        count = main.Booking.query.count()
        self.assertEqual(self.admin.post(self.path, data=self.data).status_code, 302)
        record = main.db.session.get(main.db._giveaway_removal, self.entry.id)
        self.assertEqual(record.reason, self.data['reason'])
        self.assertIsNotNone(record.removed_at)
        self.assertIsNotNone(main.db.session.get(main.ClientAccount, self.account.id))
        self.assertIsNotNone(main.db.session.get(fixtures.Submission, self.entry.id))
        self.assertEqual(main.Booking.query.count(), count)
        self.assertEqual(eligible_accounts(main.db, main.ClientAccount, fixtures.Submission, self.form.id).count(), 0)
        page = self.admin.get(f'/admin/native-forms/{self.form.id}/submissions')
        self.assertNotIn(f'id="submission-{self.entry.id}"'.encode(), page.data)
        history = self.admin.get(f'/admin/native-forms/{self.form.id}/submissions?removed=yes')
        self.assertIn(b'Removed from giveaway', history.data)
        self.assertIn(self.data['reason'].encode(), history.data)
        self.assertIn(b'GMT', history.data)
        csv = self.admin.get(f'/admin/native-forms/{self.form.id}/export?removed=yes')
        self.assertIn(b'Removed', csv.data)

    def test_auth_confirmation_reason_and_form_scope_are_required(self):
        self.assertEqual(self.client.post(self.path, data=self.data).status_code, 302)
        self.assertEqual(self.admin.post(self.path, data=dict(self.data, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=dict(self.data, confirm_remove='')).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=dict(self.data, reason='')).status_code, 400)
        other = self.fixture.create('giveaway')
        self.assertEqual(self.admin.post(f'/admin/native-forms/{other.id}/entrants/{self.entry.id}/remove', data=self.data).status_code, 404)
        self.assertIsNone(main.db.session.get(main.db._giveaway_removal, self.entry.id))

    def test_removed_entrant_never_wins_or_receives_draw_notification(self):
        other = main.ClientAccount(email='remaining@example.com', first_name='Remaining', last_name='Entrant')
        main.db.session.add(other); main.db.session.flush()
        main.db.session.add(fixtures.Submission(form_id=self.form.id, client_id=other.id, token='remaining-token',
            giveaway_key=f'{self.form.id}:{other.id}', email=other.email, name='Remaining Entrant', answers_json='{}',
            terms_snapshot=self.form.terms, title_snapshot=self.form.title))
        main.db.session.commit()
        self.admin.post(self.path, data=self.data)
        with patch.dict(main.app.extensions, {'client_notice_deliver': lambda *args: True}):
            response = self.admin.post(f'/admin/native-forms/{self.form.id}/draw', data={'csrf_token': 'admin-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['number'], other.account_number)
        draw = main.db.session.get(main.db._giveaway_draw, self.form.id)
        self.assertEqual(draw.entrant_count, 1)
        Notice = main.app.extensions['client_notification_model']
        self.assertEqual(Notice.query.filter_by(email=self.account.email, reference=f'Giveaway-{self.form.id}').count(), 0)
        remaining = fixtures.Submission.query.filter_by(client_id=other.id, form_id=self.form.id).one()
        self.assertEqual(self.admin.post(f'/admin/native-forms/{self.form.id}/entrants/{remaining.id}/remove', data=self.data).status_code, 409)

    def test_repeated_removal_keeps_original_audit(self):
        self.admin.post(self.path, data=self.data)
        at = main.db.session.get(main.db._giveaway_removal, self.entry.id).removed_at
        self.admin.post(self.path, data=dict(self.data, reason='A later reason'))
        record = main.db.session.get(main.db._giveaway_removal, self.entry.id)
        self.assertEqual(record.reason, self.data['reason'])
        self.assertEqual(record.removed_at, at)
