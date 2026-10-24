import json
import unittest
from unittest.mock import patch
import test_business_tools as fixtures

main = fixtures.main


class BookingEditTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Under Review'
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.path = f'/admin/bookings/{self.booking.id}/edit'

    def tearDown(self):
        self.fixture.tearDown()

    def payload(self):
        response = self.admin.get(self.path)
        self.assertEqual(response.status_code, 200)
        config = json.loads(response.get_data(as_text=True).split('<script id="import-config" type="application/json">', 1)[1].split('</script>', 1)[0])
        row = dict(zip(config['initialSource']['headers'], config['initialSource']['rows'][0]))
        row['events'] = json.loads(row['events'])
        return {'rows': [row], 'version': config['version']}, {'X-Import-Token': config['token']}

    def test_edits_update_portal_notifications_and_audit_and_preserve_consent(self):
        data, headers = self.payload()
        original_signature = self.booking.signature
        original_terms = self.booking.terms_accepted_at
        row = data['rows'][0]
        row.update(first_name='Changed', phone='+447911123999', internal_notes='PRIVATE ADMIN NOTE', signature='forged', status='Accepted')
        row['events'][0]['theme'] = 'New theme'
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.booking.first_name, 'Changed')
        self.assertEqual(self.booking.status, 'Under Review')
        self.assertEqual(self.booking.signature, original_signature)
        self.assertEqual(self.booking.terms_accepted_at, original_terms)
        Change, Notice = main.notification_models
        change = Change.query.filter_by(booking_id=self.booking.id).one()
        self.assertIn('First name', change.changes)
        self.assertIn('Phone', change.changes)
        self.assertIn('Event 1: Theme', change.changes)
        self.assertNotIn('PRIVATE ADMIN NOTE', change.changes_json)
        self.assertEqual(Notice.query.filter_by(kind='booking').count(), 1)
        page = self.fixture.client.get(f'/client/bookings/{self.booking.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Changed', page.data)
        self.assertNotIn(b'PRIVATE ADMIN NOTE', page.data)
        self.assertEqual(main.booking_lifecycle_models[0].query.filter_by(change_id=change.id).count(), 1)

    def test_auth_status_csrf_stale_and_invalid_inputs(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        data, headers = self.payload()
        self.assertEqual(self.admin.post(self.path, json=data).status_code, 400)
        stale = dict(data, version='wrong')
        self.assertEqual(self.admin.post(self.path, headers=headers, json=stale).status_code, 409)
        data['rows'][0]['events'][0]['finish_time'] = '00:00'
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 400)
        self.booking.status = 'Accepted'; main.db.session.commit()
        self.assertEqual(self.admin.get(self.path).status_code, 409)
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 409)

    def test_internal_notes_only_do_not_notify_client(self):
        data, headers = self.payload()
        data['rows'][0]['internal_notes'] = 'Private'
        response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=self.booking.id).count(), 0)
        self.assertEqual(main.notification_models[1].query.filter_by(kind='booking').count(), 0)

    def test_email_failure_preserves_portal_changes_and_stale_save_is_rejected(self):
        data, headers = self.payload()
        data['rows'][0]['phone'] = '+447911123888'
        with patch.object(main, 'send_client_email', side_effect=RuntimeError('Synthetic email failure')):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.booking.phone, '+447911123888')
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=self.booking.id).count(), 1)
        self.assertFalse(main.notification_models[1].query.filter_by(kind='booking').one().email_sent)
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 409)

    def test_event_edits_preserve_schedule_metadata_and_synchronize_public_event(self):
        saved = json.loads(self.booking.event_schedule or '{}')
        if not isinstance(saved, dict):
            saved = {'events': saved}
        saved['intake_options'] = {'package': 'Preserved package'}
        original_days = main.booking_schedule_events(self.booking)
        original_days[0]['travel_miles'] = '24'
        saved['events'] = original_days
        self.booking.event_schedule = json.dumps(saved)
        event = main.Event(name='Linked public event', booking_id=self.booking.id, booking_day_number=1,
            event_date=self.booking.event_date, event_address=self.booking.event_address, status='Closed', is_current=False)
        main.db.session.add(event); main.db.session.commit()
        data, headers = self.payload()
        data['rows'][0]['events'][0].update(event_date='2028-01-04', event_address='Changed venue')
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(event.event_date.isoformat(), '2028-01-04')
        self.assertEqual(event.event_address, 'Changed venue')
        result = json.loads(self.booking.event_schedule)
        self.assertEqual(result['intake_options'], {'package': 'Preserved package'})
        self.assertEqual(result['events'][0]['travel_miles'], '24')
