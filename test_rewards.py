"""Verify the integrated referral scheme using an isolated database."""
import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import unittest
from io import BytesIO
import app as main
import rewards


class RewardsWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        rewards.execute('DELETE FROM referrals')
        main.db.session.query(main.Booking).delete()
        main.db.session.query(main.ReferralCodeUse).delete()
        main.db.session.commit()
        self.client = main.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True

    def tearDown(self):
        self.context.pop()

    def create(self):
        response = self.client.post('/admin/rewards/referral/new', data={
            'first_name': 'Test', 'surname': 'Customer', 'event_date': '01/01/2026'})
        self.assertEqual(response.status_code, 302)
        row = rewards.fetch_one('SELECT * FROM referrals')
        self.assertEqual(len(row['code']), 5)
        self.assertEqual(row['expires_date'], '2027-01-01')
        return row

    def test_workflow(self):
        row = self.create()
        self.assertTrue(main.booking_code_is_valid(row['code']))
        base = f"/admin/rewards/referral/{row['id']}"
        self.client.post(base+'/validate', data={'friend_event_date': '31/12/2025'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'active')
        self.client.post(base+'/validate', data={'friend_event_date': '02/01/2027'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'active')
        self.client.post(base+'/validate', data={'friend_event_date': '01/06/2026'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'earned')
        self.assertFalse(main.booking_code_is_valid(row['code']))
        self.client.post(base+'/redeem', data={'redeemed_date': '01/05/2026'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'earned')
        self.client.post(base+'/redeem', data={'redeemed_date': '01/06/2030'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'redeemed')
        self.client.post(base+'/validate', data={'friend_event_date': '01/07/2026'})
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'redeemed')

    def test_pages_and_access(self):
        row = self.create()
        for path in ['/admin/rewards/', '/admin/rewards/?section=earned',
                     '/admin/rewards/?section=redeemed', '/admin/rewards/referral/new',
                     '/admin/rewards/import', f"/admin/rewards/referral/{row['id']}/validate", '/booking']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(main.app.test_client().get('/admin/rewards/').status_code, 302)
        response = self.client.get('/admin/rewards/backup/database')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'SQLite format 3'))

    def test_dashboard_empty_and_authentication(self):
        for path in ['/', '/admin/dashboard']:
            self.assertEqual(main.app.test_client().get(path).status_code, 302)
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Needs attention', response.data)
            self.assertIn(b'No upcoming bookings yet.', response.data)
            self.assertIn(b'Quick actions', response.data)

    def test_booking_usage(self):
        from datetime import datetime, date
        row = self.create()
        unused = self.client.get('/admin/rewards/?section=all')
        self.assertIn(b'Not used in a booking', unused.data)
        booking = main.Booking(
            request_type='booking', client_type='individual', first_name='Friend',
            last_name='Client', date_of_birth=date(1990, 1, 1), is_over_18=True,
            ethnicity='Prefer not to say', religion='Prefer not to say',
            client_address='Test address', phone='+447700900000', email='test@example.com',
            event_date=date(2026, 12, 1), single_date=True, start_time='10:00',
            finish_time='12:00', event_address='Test venue', publicity_type='Private',
            charge_type='Client', location_type='Indoor', event_type='Birthday', theme='N/A',
            pitch_fee_required=False, payment_preference='Full payment', promo_code=row['code'],
            signature='Friend Client', liability_acknowledged=True,
            terms_accepted_at=datetime.now(), terms_version='test', status='Under Review',
            submitted_at=datetime(2026, 10, 4, 12, 30), referral_verified=True)
        main.db.session.add(booking)
        main.db.session.commit()
        self.assertFalse(main.booking_code_is_valid(row['code']))
        self.assertIn(b'Friend Client', self.client.get('/').data)
        booking.status = 'Accepted'
        booking.event_date = date(2099, 12, 1)
        main.db.session.commit()
        self.assertIn(b'Test venue', self.client.get('/').data)
        response = self.client.get('/admin/rewards/?section=all')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Used in 1 booking request', response.data)
        self.assertIn(b'Friend Client', response.data)
        self.assertIn(b'04/10/2026 12:30', response.data)
        self.assertIn(f'#booking-{booking.id}'.encode(), response.data)
        self.assertEqual(rewards.fetch_one('SELECT * FROM referrals')['status'], 'active')
        booking.status = 'Declined'
        main.db.session.commit()
        self.assertIn(b'Declined', self.client.get('/admin/rewards/?section=all').data)

    def test_code_single_use_and_rollback(self):
        row = self.create()
        main.claim_booking_code(row['code'])
        main.db.session.rollback()
        self.assertTrue(main.booking_code_is_valid(row['code']))
        main.claim_booking_code(row['code'])
        main.db.session.commit()
        self.assertFalse(main.booking_code_is_valid(row['code']))
        response = self.client.post('/api/referrals/verify', json={'code': row['code']})
        self.assertEqual(response.json['status'], 'invalid')
        with self.assertRaises(ValueError):
            main.claim_booking_code(row['code'])
        # Simulate a submission that passed its check before the first committed.
        from unittest.mock import patch
        with patch.object(main, 'booking_code_is_valid', return_value=True):
            with self.assertRaises(ValueError):
                main.claim_booking_code(row['code'])
        self.assertEqual(main.db.session.query(main.ReferralCodeUse).count(), 1)

    def test_private_transfer_preserves_codes_and_single_use(self):
        import json
        from rewards_transfer import export_referrals
        row = self.create()
        main.claim_booking_code(row['code'])
        main.db.session.commit()
        payload = export_referrals(main.db.engine)
        rewards.execute('DELETE FROM referrals')
        main.db.session.query(main.ReferralCodeUse).delete()
        main.db.session.commit()
        for _ in range(2):
            response = self.client.post('/admin/rewards/import-transfer', data={
                'transfer_file': (BytesIO(json.dumps(payload).encode()), 'transfer.json')})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(len(rewards.fetch_all('SELECT * FROM referrals')), 1)
        self.assertFalse(main.booking_code_is_valid(row['code']))
        self.assertEqual(main.app.test_client().post('/admin/rewards/import-transfer').status_code, 302)

    def test_all_codes_and_search(self):
        for code, status, expires in [('Act23', 'active', '2099-01-01'),
                                      ('Exp23', 'active', '2020-01-01'),
                                      ('Earn2', 'earned', '2027-01-01'),
                                      ('Rede2', 'redeemed', '2027-01-01')]:
            rewards.execute('INSERT INTO referrals (customer_name, code, original_event_date, expires_date, status) VALUES (:name, :code, :original, :expires, :status)',
                            {'name': 'Test Customer', 'code': code, 'original': '2019-01-01', 'expires': expires, 'status': status})
        response = self.client.get('/admin/rewards/?section=all')
        self.assertEqual(response.status_code, 200)
        for code in ['Act23', 'Exp23', 'Earn2', 'Rede2']:
            self.assertIn(code.encode(), response.data)
        response = self.client.get('/admin/rewards/?section=all&q=earn2')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Earn2', response.data)
        self.assertNotIn(b'Act23', response.data)
        self.assertNotIn(b'Rede2', response.data)

    def test_legacy_import_preserves_states_and_skips_duplicates(self):
        payload = 'Test Customer - AbC23 - Event Date: 2026-01-01 - Expires: 2027-01-01 - Friend Event Date: 2026-06-01 - Reward Earned: 2026-06-01'
        for _ in range(2):
            response = self.client.post('/admin/rewards/import', data={
                'earned_file': (BytesIO(payload.encode()), 'rewards.txt')})
            self.assertEqual(response.status_code, 200)
        rows = rewards.fetch_all('SELECT * FROM referrals')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'earned')
        self.assertEqual(rows[0]['code'], 'AbC23')


if __name__ == '__main__':
    unittest.main()
