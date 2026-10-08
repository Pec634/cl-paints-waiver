import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import csv
from io import StringIO
from datetime import datetime, date
from unittest.mock import patch
import unittest
from flask import template_rendered
import app as main
import rewards
import reports


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()
        rewards.execute('DELETE FROM referrals')
        self.client = main.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.query = {'period': 'custom', 'start': '2026-01-01', 'end': '2026-12-31'}

    def tearDown(self):
        self.context.pop()

    def booking(self, **extra):
        values = dict(request_type='booking', client_type='individual', first_name='Private',
            last_name='Client', date_of_birth=date(1990, 1, 1), is_over_18=True,
            ethnicity='Prefer not to say', religion='Prefer not to say',
            client_address='1 Private Road, London SW1A 1AA', phone='+447700900000', email='test@example.com',
            event_date=date(2026, 8, 1), single_date=True, start_time='10:00', finish_time='12:00',
            event_address='Venue, Leeds LS1 1AA', publicity_type='Private', charge_type='Client',
            location_type='Indoor', event_type='Birthday', theme='N/A', pitch_fee_required=False,
            payment_preference='Full payment', signature='Private Client', liability_acknowledged=True,
            terms_accepted_at=datetime(2026, 8, 1), terms_version='test', status='Accepted',
            submitted_at=datetime(2026, 6, 1), total_event_cost=90, travel_charge=10)
        values.update(extra)
        booking = main.Booking(**values)
        main.db.session.add(booking)
        main.db.session.commit()
        return booking

    def data(self, query=None):
        captured = []
        def capture(sender, template, context, **unused):
            captured.append(context)
        with template_rendered.connected_to(capture, main.app):
            response = self.client.get('/admin/reports', query_string=query or self.query)
        self.assertEqual(response.status_code, 200)
        return captured[-1], response

    def test_aggregates_and_location_deduplication(self):
        self.booking(promo_code='AbC23')
        self.booking(submitted_at=datetime(2026, 7, 1), status='Declined')
        self.booking(submitted_at=datetime(2025, 7, 1), email='outside@example.com')
        waiver = main.Waiver(waiver_reference='TEST', responsible_first_name='Private',
            responsible_last_name='Adult', responsible_email='adult@example.com', signed_date=datetime(2026, 5, 1),
            expiry_date=datetime(2027, 5, 1), event_name='Test', terms_version='test', terms_snapshot='Test', signature_text='Adult')
        main.db.session.add(waiver)
        main.db.session.flush()
        for age in [4, 12]:
            main.db.session.add(main.Participant(waiver_id=waiver.id, first_name='Child', last_name='Private', age=age, gender='Other'))
        main.db.session.commit()
        rewards.execute("INSERT INTO referrals(customer_name,code,original_event_date,expires_date,friend_event_date,reward_earned_date,status) VALUES ('Private','AbC23','2026-01-01','2027-01-01','2026-08-01','2026-08-01','earned')")
        data, response = self.data()
        self.assertEqual(data['booking_count'], 2)
        self.assertEqual(data['unique_clients'], 1)
        self.assertEqual(data['average_age'], 8)
        self.assertEqual(data['participant_count'], 2)
        self.assertEqual(data['estimated_value'], '100.00')
        self.assertEqual(data['areas'][0]['clients'], 1)
        self.assertEqual(data['areas'][0]['bookings'], 2)
        self.assertEqual(data['areas'][0]['outcode'], 'SW1A')
        self.assertEqual(sum(item['value'] for item in data['workload']), 4)
        self.assertEqual([item['value'] for item in data['referral_flow']], [1, 1, 1, 0])
        self.assertNotIn(b'1 Private Road', response.data)
        self.assertNotIn(b'test@example.com', response.data)
        venue, _ = self.data(dict(self.query, location='venue'))
        self.assertEqual(venue['areas'][0]['outcode'], 'LS1')

    def test_repeat_customers_use_history_email_identity_and_selected_setting(self):
        self.booking(email='RETURN@example.com', submitted_at=datetime(2025, 6, 1))
        self.booking(email=' return@example.com ', submitted_at=datetime(2026, 6, 1))
        self.booking(email='pending@example.com', status='Declined', submitted_at=datetime(2025, 6, 1))
        self.booking(email='pending@example.com', status='Under Review')
        self.booking(email='new@example.com')
        self.booking(email='new@example.com', submitted_at=datetime(2027, 1, 1))
        self.booking(email='no-current-request@example.com', submitted_at=datetime(2025, 6, 1))
        self.booking(email='no-current-request@example.com', submitted_at=datetime(2025, 7, 1))
        self.booking(email='cross-setting@example.com', publicity_type='Public', submitted_at=datetime(2025, 6, 1))
        self.booking(email='cross-setting@example.com', publicity_type='Private')
        data, page = self.data()
        self.assertEqual(data['loyal_clients'], 2)
        self.assertEqual(data['repeat_clients'], 3)
        self.assertEqual(data['repeat_requests'], 3)
        self.assertIn(b'Loyal customers', page.data)
        private, _ = self.data(dict(self.query, setting='Private'))
        self.assertEqual(private['loyal_clients'], 1)
        self.assertEqual(private['repeat_clients'], 2)
        self.assertEqual(private['repeat_requests'], 2)
        export = self.client.get('/admin/reports/export', query_string=self.query)
        self.assertIn(b'Summary,loyal_clients,2', export.data)
        self.assertIn(b'Summary,repeat_clients,3', export.data)
        self.assertNotIn(b'pending@example.com', export.data)

    def test_csv_and_invalid_dates_and_authentication(self):
        self.booking(event_type='=DANGEROUS()')
        response = self.client.get('/admin/reports/export', query_string=self.query)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"'=DANGEROUS()", response.data)
        self.assertNotIn(b'Private Road', response.data)
        parsed = list(csv.reader(StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(parsed[0], ['Report', 'Category', 'Value', 'Start date', 'End date'])
        invalid = dict(self.query, start='2027-01-01')
        self.assertEqual(self.client.get('/admin/reports/export', query_string=invalid).status_code, 400)
        self.assertIn(b'start date must', self.client.get('/admin/reports', query_string=invalid).data)
        outsider = main.app.test_client()
        for path in ['/admin/reports', '/admin/reports/export']:
            self.assertEqual(outsider.get(path).status_code, 302)
        self.assertEqual(outsider.post('/admin/reports/locations/refresh').status_code, 302)

    def test_location_refresh_and_cache(self):
        self.booking()
        with patch.object(reports, 'lookup_outcode', return_value={'latitude': 51.5, 'longitude': -0.1, 'town': 'London'}) as lookup:
            self.assertEqual(self.client.post('/admin/reports/locations/refresh', data=self.query).status_code, 302)
            lookup.assert_called_once_with('SW1A')
            self.client.post('/admin/reports/locations/refresh', data=self.query)
            self.assertEqual(lookup.call_count, 1)
        data, _ = self.data()
        self.assertEqual(data['markers'][0]['latitude'], 51.5)

    def test_missing_locations_and_multi_date_workload(self):
        import json
        self.booking(client_address='No postcode', event_schedule=json.dumps({'events': [
            {'date': '2026-08-01', 'start_time': '10:00', 'finish_time': '12:00', 'event_address': 'Leeds LS1 1AA'},
            {'date': '2026-09-01', 'start_time': '10:00', 'finish_time': '13:00', 'event_address': 'London SW1A 1AA'}]}))
        data, _ = self.data()
        self.assertEqual(data['missing_addresses'], 1)
        self.assertEqual(sum(item['value'] for item in data['workload']), 5)
        self.assertEqual(reports.extract_outcode('London SW1A1AA'), 'SW1A')
        self.assertIsNone(reports.extract_outcode('No postcode'))

    def test_public_private_filters(self):
        import json
        self.booking(publicity_type='Private')
        self.booking(publicity_type='Public', email='public@example.com')
        self.booking(email='mixed@example.com', event_schedule=json.dumps({'events': [
            {'date': '2026-08-01', 'start_time': '10:00', 'finish_time': '12:00', 'event_address': 'Leeds LS1 1AA', 'publicity_type': 'Private'},
            {'date': '2026-09-01', 'start_time': '10:00', 'finish_time': '13:00', 'event_address': 'London SW1A 1AA', 'publicity_type': 'Public'}]}))
        public, _ = self.data(dict(self.query, setting='Public'))
        private, _ = self.data(dict(self.query, setting='Private'))
        self.assertEqual(public['booking_count'], 2)
        self.assertEqual(private['booking_count'], 2)
        self.assertEqual(sum(item['value'] for item in public['workload']), 5)
        self.assertEqual(sum(item['value'] for item in private['workload']), 4)
        comparison = {item['label']: item['value'] for item in public['setting_comparison']}
        self.assertEqual(comparison, {'Private': 1, 'Public': 1, 'Mixed public/private': 1})
        export = self.client.get('/admin/reports/export', query_string=dict(self.query, setting='Public'))
        self.assertIn(b'Event setting,Public', export.data)

    def test_private_hides_waiver_and_age_reports(self):
        _, response = self.data(dict(self.query, setting='Private'))
        for title in [b'Waivers signed', b'Participants recorded', b'Average participant age',
                      b'Participant age bands', b'Waivers over time', b'Participants over time']:
            self.assertNotIn(title, response.data)
        export = self.client.get('/admin/reports/export', query_string=dict(self.query, setting='Private'))
        for field in [b'waiver_count', b'participant_count', b'average_age', b'waiver_trend', b'participant_trend', b'ages,']:
            self.assertNotIn(field, export.data)
        _, public = self.data(dict(self.query, setting='Public'))
        self.assertIn(b'Waivers signed', public.data)


if __name__ == '__main__':
    unittest.main()
