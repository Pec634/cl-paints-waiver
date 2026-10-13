import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
import test_business_tools as fixtures
from connecteam_rota import shift_payload
from connecteam_rota import enrich_shifts, note_text
from connecteam_rota import api as connecteam_api, RateLimited, retry_time
from urllib.error import HTTPError
from io import BytesIO
import json

main = fixtures.main


class ConnecteamTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin; self.booking = self.fixture.booking
        self.booking.status = 'Accepted'; main.db.session.commit()
        self.schedules = {'schedulers':[{'schedulerId':123, 'name':'Staff rota', 'isArchived':False}]}

    def tearDown(self):
        self.fixture.tearDown()

    def post(self, action, **extra):
        return self.admin.post('/admin/connecteam', data=dict(csrf_token='admin-token', action=action, **extra))

    def test_read_export_duplicate_and_changed_details(self):
        def response(path, payload=None):
            if path == '/scheduler/v1/schedulers': return self.schedules
            if payload is not None:
                self.assertFalse(payload[0]['isPublished'])
                self.assertEqual(payload[0]['assignedUserIds'], [])
                self.assertIn('Venue:', payload[0]['notes'][0]['html'])
                return {'shifts':[{'id':'shift-1'}]}
            return {'shifts':[]}
        with patch('connecteam_rota.api', side_effect=response) as api:
            self.assertEqual(main.app.test_client().get('/admin/connecteam').status_code, 302)
            self.assertEqual(self.admin.post('/admin/connecteam', data={}).status_code, 400)
            self.post('schedule', scheduler_id=123)
            self.assertEqual(self.admin.get('/admin/connecteam').status_code, 200)
            self.post('export', booking_id=self.booking.id, event_index=0)
            self.post('export', booking_id=self.booking.id, event_index=0)
            self.assertEqual(sum(call.args[1] is not None for call in api.call_args_list if len(call.args)>1), 1)
            self.assertEqual(main.ConnecteamShiftLink.query.one().shift_id, 'shift-1')
            self.booking.event_address = 'Changed venue'; main.db.session.commit()
            self.assertIn(b'changed since export', self.admin.get('/admin/connecteam').data)

    def test_failure_blocks_repeat_and_nonaccepted_rejected(self):
        with patch('connecteam_rota.api', return_value=self.schedules): self.post('schedule', scheduler_id=123)
        def response(path, payload=None):
            if payload is None: return self.schedules
            raise ValueError('Connection failed')
        with patch('connecteam_rota.api', side_effect=response):
            self.post('export', booking_id=self.booking.id, event_index=0)
            self.assertEqual(main.ConnecteamShiftLink.query.one().status, 'check_required')
            self.post('export', booking_id=self.booking.id, event_index=0)
            self.assertEqual(main.ConnecteamShiftLink.query.count(), 1)
            self.booking.status='Declined'; main.db.session.commit()
            self.assertEqual(self.post('export', booking_id=self.booking.id, event_index=0).status_code, 400)

    def test_shift_date_order_and_staff_filter(self):
        main.db.session.add(main.BusinessSetting(key='connecteam_scheduler_id',value='123'));main.db.session.commit()
        def response(path,payload=None):
            if path=='/scheduler/v1/schedulers':return self.schedules
            return {'shifts':[
                dict(id='late',title='LATER_SHIFT',startTime=1792108800,endTime=1792112400,assignedUserIds=[]),
                dict(id='early',title='EARLIER_SHIFT',startTime=1792022400,endTime=1792026000,assignedUserIds=[])]}
        with patch('connecteam_rota.api',side_effect=response) as api:
            ascending=self.admin.get('/admin/connecteam?order=asc&staff=unassigned')
            descending=self.admin.get('/admin/connecteam?order=desc&staff=unassigned')
            self.assertEqual(ascending.status_code,200)
            self.assertLess(ascending.data.index(b'EARLIER_SHIFT'),ascending.data.index(b'LATER_SHIFT'))
            self.assertLess(descending.data.index(b'LATER_SHIFT'),descending.data.index(b'EARLIER_SHIFT'))
            self.assertIn(b'value="desc" selected',descending.data)
            api.reset_mock()
            self.assertEqual(self.admin.get('/admin/connecteam?order=invalid').status_code,400)
            api.assert_not_called()

    def test_api_cache_and_rate_limit_cooldown(self):
        path='/scheduler/v1/schedulers'
        data={'data':self.schedules}
        with patch.dict('os.environ',{'CONNECTEAM_API_KEY':'test-cache-key'}),patch('connecteam_rota.time.time',return_value=1000):
            with patch('connecteam_rota.urlopen',return_value=BytesIO(json.dumps(data).encode())) as network:
                first=connecteam_api(path);first['schedulers'][0]['name']='Locally changed'
                second=connecteam_api(path)
                self.assertEqual(second['schedulers'][0]['name'],'Staff rota')
                self.assertEqual(network.call_count,1)
            with patch('connecteam_rota.time.time',return_value=5000),patch('connecteam_rota.urlopen',side_effect=HTTPError('https://api.connecteam.com',429,'Limited',{'Retry-After':'120'},None)) as network:
                stale=connecteam_api(path)
                self.assertEqual(stale,self.schedules)
                with self.assertRaises(RateLimited):connecteam_api('/scheduler/v1/schedulers/123/shifts?new=1')
                with self.assertRaises(RateLimited):connecteam_api('/scheduler/v1/schedulers/123/shifts',[])
                self.assertEqual(network.call_count,1)
            with patch('connecteam_rota.time.time',return_value=5121),patch('connecteam_rota.urlopen',return_value=BytesIO(json.dumps(data).encode())) as network:
                self.assertEqual(connecteam_api(path),self.schedules)
                self.assertEqual(network.call_count,1)

    def test_rate_limit_daily_reset_and_export_can_retry(self):
        with patch('connecteam_rota.time.time',return_value=1000):
            self.assertEqual(retry_time({'x-ratelimit-day-remaining':'0','x-ratelimit-day-reset':'80000','x-ratelimit-minute-reset':'1060'}),80000)
            self.assertEqual(retry_time({'Retry-After':'120'}),1120)
            self.assertEqual(retry_time({}),1060)
        with patch('connecteam_rota.api',return_value=self.schedules):self.post('schedule',scheduler_id=123)
        def response(path,payload=None):
            if payload is None:return self.schedules
            raise RateLimited(1792108800)
        with patch('connecteam_rota.api',side_effect=response):
            self.post('export',booking_id=self.booking.id,event_index=0)
        self.assertEqual(main.ConnecteamShiftLink.query.count(),0)

    def test_uk_summer_time_and_invalid_duration(self):
        event = dict(date='2026-07-01', start_time='10:00', finish_time='12:00', event_address='Venue', event_type='Party')
        payload = shift_payload(self.booking, event, 0)
        self.assertEqual(datetime.fromtimestamp(payload['startTime'], ZoneInfo('UTC')).hour, 9)
        event['finish_time']='09:00'
        with self.assertRaises(ValueError): shift_payload(self.booking, event, 0)

    def test_shift_details_names_and_safe_notes(self):
        shifts = [dict(id='example', startTime=1782896400, endTime=1782903600, assignedUserIds=[12],
                       locationData={'gps':{'address':'Example venue'}}, notes=[{'html':'<p>Bring paints</p><script>bad()</script><p>Arrive early</p>'}])]
        with patch('connecteam_rota.api', return_value={'users':[{'userId':12, 'firstName':'Alex', 'lastName':'Painter'}]}):
            enrich_shifts(shifts)
        self.assertEqual(shifts[0]['staff_names'], ['Alex Painter'])
        self.assertEqual(shifts[0]['venue'], 'Example venue')
        self.assertEqual(shifts[0]['duration'], 2)
        self.assertEqual(shifts[0]['plain_notes'], ['Bring paints\nArrive early'])
        with patch('connecteam_rota.api', side_effect=ValueError('No directory access')):
            enrich_shifts(shifts)
        self.assertEqual(shifts[0]['staff_names'], ['Staff ID 12'])

    def test_staff_filter_and_unassigned_shifts(self):
        main.db.session.add(main.BusinessSetting(key='connecteam_scheduler_id', value='123')); main.db.session.commit()
        def response(path, payload=None):
            if path == '/scheduler/v1/schedulers': return self.schedules
            if path.startswith('/users/'):
                return {'users':[{'userId':12,'firstName':'Alex','lastName':'Painter'}, {'userId':13,'firstName':'Sam','lastName':'Painter'}]}
            return {'shifts':[dict(id='one',title='Alex event',startTime=1782896400,endTime=1782903600,assignedUserIds=[12]),
                              dict(id='two',title='Sam event',startTime=1782896400,endTime=1782903600,assignedUserIds=[13]),
                              dict(id='three',title='Unassigned event',startTime=1782896400,endTime=1782903600,assignedUserIds=[])]}
        with patch('connecteam_rota.api', side_effect=response):
            page = self.admin.get('/admin/connecteam?staff=12')
            self.assertIn(b'Alex event', page.data)
            self.assertNotIn(b'Sam event', page.data)
            self.assertIn(b'Sam Painter', page.data)
            self.assertIn(b'Showing 1 of 3', page.data)
            page = self.admin.get('/admin/connecteam?staff=unassigned')
            self.assertIn(b'Unassigned event', page.data)
            self.assertNotIn(b'Alex event', page.data)
            self.assertIn(b'No shifts match', self.admin.get('/admin/connecteam?staff=99').data)
            self.assertEqual(self.admin.get('/admin/connecteam?staff=bad').status_code, 400)


if __name__ == '__main__': unittest.main()
