from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, unquote, parse_qs

import test_business_tools as fixtures
from google_calendar_sync import CalendarError, event_payload, matches, token_cipher, TOKEN_KEY, SCOPE
from google_calendar_sync import access_token as real_access_token

main = fixtures.main


class GoogleCalendarSyncTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Under Review'
        self.booking.event_schedule = json.dumps({'events': [dict(date='2026-10-27', start_time='09:00', finish_time='17:00', event_address='Test venue')]})
        main.db.session.commit()
        self.env = patch.dict(os.environ, GOOGLE_CALENDAR_ID='company@example.com', GOOGLE_CALENDAR_CLIENT_ID='test-client',
            GOOGLE_CALENDAR_CLIENT_SECRET='test-client-secret', SECRET_KEY='test-server-secret')
        self.env.start()
        encrypted = token_cipher().encrypt(json.dumps(dict(refresh_token='test-refresh', calendar_id='company@example.com')).encode()).decode()
        main.db.session.add(main.BusinessSetting(key=TOKEN_KEY, value=encrypted))
        main.db.session.commit()
        self.token = patch('google_calendar_sync.access_token', return_value='test-token')
        self.token.start()
        self.events = {}
        self.calls = []
        self.provider = patch('google_calendar_sync.api', side_effect=self.api)
        self.provider.start()
        self.sync = main.app.extensions['google_calendar_sync']

    def tearDown(self):
        self.provider.stop()
        self.token.stop()
        self.env.stop()
        self.fixture.tearDown()

    def api(self, token, method, path, payload=None, etag=None):
        self.calls.append((method, path, payload))
        event_id = unquote(urlsplit(path).path.split('/')[-1])
        if method == 'GET' and event_id == 'events':
            return dict(items=deepcopy(list(self.events.values())))
        if method == 'GET':
            return deepcopy(self.events[event_id])
        if method == 'POST':
            self.events[payload['id']] = dict(deepcopy(payload), etag='test-etag')
            return deepcopy(self.events[payload['id']])
        if method == 'PATCH':
            self.events[event_id].update(deepcopy(payload))
            return deepcopy(self.events[event_id])
        if method == 'DELETE':
            del self.events[event_id]
            return {}
        raise AssertionError(method)

    def test_preview_creation_repeat_and_status_changes(self):
        report = self.sync()
        self.assertEqual(report['create'], 1)
        self.assertEqual(self.events, {})
        self.sync(apply=True)
        event_id, event = next(iter(self.events.items()))
        self.assertIn('[Under Review]', event['summary'])
        self.assertEqual(event['transparency'], 'transparent')
        self.assertEqual(event['status'], 'tentative')
        self.assertEqual(self.sync(apply=True)['unchanged'], 1)
        for status, label in [('Awaiting Payment', 'Awaiting Payment'), ('Accepted', 'Confirmed')]:
            self.booking.status = status
            main.db.session.commit()
            self.assertEqual(self.sync(apply=True)['update'], 1)
            self.assertEqual(list(self.events), [event_id])
            self.assertIn('[' + label + ']', self.events[event_id]['summary'])
        self.assertEqual(self.events[event_id]['transparency'], 'opaque')
        self.assertNotIn('attendees', self.events[event_id])

    def test_multi_day_and_date_change_keep_identity(self):
        self.sync(apply=True)
        event_id = next(iter(self.events))
        events = json.loads(self.booking.event_schedule)['events']
        events[0]['date'] = '2026-11-01'
        events.append(dict(date='2026-11-02', start_time='23:00', finish_time='01:00'))
        self.booking.event_schedule = json.dumps(dict(events=events))
        main.db.session.commit()
        result = self.sync(apply=True)
        self.assertEqual((result['create'], result['update']), (1, 1))
        self.assertTrue(self.events[event_id]['start']['dateTime'].startswith('2026-11-01'))
        overnight = next(event for key, event in self.events.items() if key != event_id)
        self.assertTrue(overnight['end']['dateTime'].startswith('2026-11-03T01:00'))

    def test_declined_cancelled_and_deleted_bookings_remove_owned_events(self):
        for status in ('Declined', 'Cancelled'):
            self.booking.status = 'Under Review'
            main.db.session.commit()
            self.sync(apply=True)
            self.booking.status = status
            main.db.session.commit()
            self.assertEqual(self.sync(apply=True)['remove'], 1)
            self.assertEqual(self.events, {})
        self.booking.status = 'Under Review'
        main.db.session.commit()
        self.sync(apply=True)
        main.db.session.delete(self.booking)
        main.db.session.commit()
        self.assertEqual(self.sync(apply=True)['remove'], 1)

    def test_unowned_event_response_stops_all_writes(self):
        self.events['unrelated-event'] = dict(id='unrelated-event', summary='Company meeting')
        with self.assertRaises(CalendarError):
            self.sync(apply=True)
        self.assertEqual(len(self.events), 1)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_invalid_schedule_stops_before_google_changes(self):
        self.booking.event_schedule = json.dumps(dict(events=[dict(date='bad')]))
        main.db.session.commit()
        with self.assertRaises(CalendarError):
            self.sync(apply=True)
        self.assertEqual(self.calls, [])

    def test_api_failure_is_recoverable_without_duplicates(self):
        original = self.api
        def fail_after_insert(token, method, path, payload=None, etag=None):
            result = original(token, method, path, payload, etag)
            if method == 'POST':
                raise CalendarError('Connection interrupted')
            return result
        with patch('google_calendar_sync.api', side_effect=fail_after_insert):
            with self.assertRaises(CalendarError):
                self.sync(apply=True)
        self.assertEqual(self.sync(apply=True)['unchanged'], 1)
        self.assertEqual(len(self.events), 1)

    def test_timezone_and_no_internal_notes(self):
        self.booking.internal_notes = 'PRIVATE INTERNAL NOTES'
        for date, offset in [('2026-07-01', '+01:00'), ('2026-12-01', '+00:00')]:
            _, payload = event_payload(self.booking, dict(date=date, start_time='09:00', finish_time='10:00'), 0, 'namespace', 'https://example.com')
            self.assertTrue(payload['start']['dateTime'].endswith(offset))
            self.assertNotIn('PRIVATE INTERNAL NOTES', json.dumps(payload))
        old = deepcopy(payload)
        old['start']['dateTime'] = '2026-12-01T09:00:00Z'
        self.assertTrue(matches(old, payload))

    def test_pagination_is_completed_before_removing_events(self):
        self.sync(apply=True)
        event = deepcopy(next(iter(self.events.values())))
        self.calls.clear()
        original = self.api
        def pages(token, method, path, payload=None, etag=None):
            if method == 'GET' and '/events?' in path:
                self.calls.append((method, path, payload))
                if 'pageToken=' not in path:
                    return dict(items=[], nextPageToken='second-page')
                return dict(items=[event])
            return original(token, method, path, payload, etag)
        with patch('google_calendar_sync.api', side_effect=pages):
            report = self.sync(apply=True)
        self.assertEqual(report['unchanged'], 1)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_conflicting_insert_reconciles_owned_event(self):
        original = self.api
        def conflict(token, method, path, payload=None, etag=None):
            if method == 'POST':
                original(token, method, path, payload, etag)
                raise CalendarError('Already exists', 409)
            return original(token, method, path, payload, etag)
        with patch('google_calendar_sync.api', side_effect=conflict):
            self.sync(apply=True)
        self.assertEqual(len(self.events), 1)
        self.assertTrue(any(method == 'PATCH' for method, _, _ in self.calls))

    def test_admin_csrf_cli_preview_and_missing_credentials(self):
        path = '/admin/calendar/google'
        self.assertEqual(self.fixture.client.get(path).status_code, 302)
        self.assertEqual(self.fixture.admin.post(path, data=dict(csrf_token='bad', action='sync')).status_code, 400)
        self.fixture.admin.get(path)
        with self.fixture.admin.session_transaction() as state:
            csrf = state['google_calendar_csrf']
        self.assertEqual(self.fixture.admin.post(path, data=dict(csrf_token=csrf, action='preview')).status_code, 200)
        self.assertEqual(self.events, {})
        runner = main.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=['sync-google-calendar']).exit_code, 0)
        self.assertEqual(self.events, {})
        self.assertEqual(runner.invoke(args=['sync-google-calendar', '--apply']).exit_code, 0)
        self.assertEqual(len(self.events), 1)
        with patch.dict(os.environ, GOOGLE_CALENDAR_ID=''):
            self.assertNotEqual(runner.invoke(args=['sync-google-calendar']).exit_code, 0)

    def begin_connection(self):
        admin = self.fixture.admin
        admin.get('/admin/calendar/google')
        with admin.session_transaction() as state:
            csrf = state['google_calendar_csrf']
        response = admin.post('/admin/calendar/google/connect', data=dict(csrf_token=csrf))
        self.assertEqual(response.status_code, 302)
        return csrf, parse_qs(urlsplit(response.location).query)

    def test_google_login_uses_state_pkce_and_stores_encrypted_token(self):
        csrf, params = self.begin_connection()
        self.assertEqual(params['access_type'], ['offline'])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertEqual(params['scope'], [SCOPE])
        with patch('google_calendar_sync.token_request', return_value=dict(access_token='access', refresh_token='new-private-refresh', scope=SCOPE)) as exchange, \
             patch('google_calendar_sync.api', return_value=dict(accessRole='writer', items=[])) as api:
            response = self.fixture.admin.get('/admin/calendar/google/callback', query_string=dict(state=params['state'][0], code='code'))
        self.assertEqual(response.status_code, 302)
        values = exchange.call_args.args[0]
        self.assertEqual(values['redirect_uri'], params['redirect_uri'][0])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(values['code_verifier'].encode()).digest()).decode().rstrip('=')
        self.assertEqual(challenge, params['code_challenge'][0])
        row = main.db.session.get(main.BusinessSetting, TOKEN_KEY)
        self.assertNotIn('new-private-refresh', row.value)
        self.assertEqual(json.loads(token_cipher().decrypt(row.value.encode()))['refresh_token'], 'new-private-refresh')
        self.assertEqual(api.call_args.args[1], 'GET', 'Connecting must not create Google events')
        self.assertEqual(self.fixture.admin.get('/admin/calendar/google/callback', query_string=dict(state=params['state'][0], code='code')).status_code, 400)
        with self.fixture.admin.session_transaction() as state:
            self.assertNotIn('new-private-refresh', str(dict(state)))

    def test_login_rejects_invalid_state_expiry_and_wrong_calendar_access(self):
        _, params = self.begin_connection()
        with patch('google_calendar_sync.token_request') as exchange:
            response = self.fixture.admin.get('/admin/calendar/google/callback?state=wrong&code=code')
            self.assertEqual(response.status_code, 400)
            exchange.assert_not_called()
        _, params = self.begin_connection()
        with self.fixture.admin.session_transaction() as state:
            pending = dict(state['google_calendar_oauth'], created=0)
            state['google_calendar_oauth'] = pending
        self.assertEqual(self.fixture.admin.get('/admin/calendar/google/callback', query_string=dict(state=params['state'][0], code='code')).status_code, 400)
        for data, role in [(dict(access_token='access', scope=SCOPE), 'writer'),
                           (dict(access_token='access', refresh_token='new', scope='other-scope'), 'writer'),
                           (dict(access_token='access', refresh_token='new', scope=SCOPE), 'reader')]:
            _, params = self.begin_connection()
            old = main.db.session.get(main.BusinessSetting, TOKEN_KEY).value
            with patch('google_calendar_sync.token_request', return_value=data), patch('google_calendar_sync.api', return_value=dict(accessRole=role)):
                self.fixture.admin.get('/admin/calendar/google/callback', query_string=dict(state=params['state'][0], code='code'))
            self.assertEqual(main.db.session.get(main.BusinessSetting, TOKEN_KEY).value, old)

    def test_connect_disconnect_are_admin_only_and_csrf_protected(self):
        for path in ('/admin/calendar/google/connect', '/admin/calendar/google/disconnect'):
            self.assertEqual(self.fixture.client.post(path).status_code, 302)
            self.assertEqual(self.fixture.admin.post(path, data=dict(csrf_token='bad')).status_code, 400)
        csrf, _ = self.begin_connection()
        self.sync(apply=True)
        response = self.fixture.admin.post('/admin/calendar/google/disconnect', data=dict(csrf_token=csrf))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(main.db.session.get(main.BusinessSetting, TOKEN_KEY))
        self.assertEqual(len(self.events), 1, 'Disconnect must retain existing calendar entries')

    def test_background_refresh_and_changed_server_secret(self):
        with patch('google_calendar_sync.token_request', return_value=dict(access_token='renewed')) as refresh:
            self.assertEqual(real_access_token(), 'renewed')
            self.assertEqual(refresh.call_args.args[0]['grant_type'], 'refresh_token')
        with patch.dict(os.environ, SECRET_KEY='rotated-server-secret'):
            with self.assertRaises(CalendarError):
                real_access_token()
