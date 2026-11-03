import json
import re
import unittest
from datetime import datetime, timedelta
import test_business_tools as fixtures
from shared_calendar import fold

main=fixtures.main


class SharedCalendarTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp();self.admin=self.fixture.admin
        self.booking=self.fixture.booking;self.booking.status='Accepted'
        self.booking.event_schedule=json.dumps({'events':[dict(date='2027-07-01',start_time='10:00',finish_time='12:00',event_address='PRIVATE HOME ADDRESS')]})
        self.slot=main.CreatesCollectionSlot(uid='one-game',title='Steelers vs Test',starts_at=datetime(2027,7,1,18),ends_at=datetime(2027,7,1,21),venue='Public Arena')
        main.db.session.add(self.slot);main.db.session.add(main.tool_models[2](starts_at=datetime(2027,7,2,9),ends_at=datetime(2027,7,2,10),reason='PRIVATE BLOCK NOTE'));main.db.session.commit()
        self.admin.get('/admin/calendar/share')
        with self.admin.session_transaction() as state:self.csrf=state['shared_calendar_csrf']
    def tearDown(self):self.fixture.tearDown()
    def action(self,action):return self.admin.post('/admin/calendar/share',data={'csrf_token':self.csrf,'action':action})
    def token(self):return main.db.session.get(main.BusinessSetting,'combined_calendar_share_token').value
    def test_combined_subscription_private_data_utc_and_stable_event_ids(self):
        self.action('create');url='/calendar/shared/'+self.token()+'.ics'
        response=main.app.test_client().get(url);self.assertEqual(response.status_code,200)
        text=response.get_data(as_text=True)
        self.assertIn('CL Paints',text);self.assertIn('CL Creates collection',text);self.assertIn('Public Arena',text)
        for private in ('PRIVATE HOME ADDRESS','PRIVATE BLOCK NOTE',self.booking.email,'SECRET ADMIN NOTE'):
            self.assertNotIn(private,text)
        self.assertIn('DTSTART:20270701T090000Z',text)
        self.assertIn('TRANSP:TRANSPARENT',text)
        self.assertEqual(text.count('BEGIN:VEVENT'),3)
        ids=re.findall(r'UID:([^\r\n]+)',text)
        self.booking.status='Under Review';main.db.session.commit()
        updated=self.admin.get(url).get_data(as_text=True)
        self.assertEqual(re.findall(r'UID:([^\r\n]+)',updated),ids)
        self.assertIn('STATUS:TENTATIVE',updated)
        self.slot.enabled=False;self.booking.status='Cancelled';main.db.session.commit()
        self.assertEqual(self.admin.get(url).get_data(as_text=True).count('BEGIN:VEVENT'),1)
    def test_access_csrf_rotation_and_disable(self):
        self.assertEqual(main.app.test_client().get('/admin/calendar/share').status_code,302)
        self.assertEqual(self.admin.post('/admin/calendar/share',data={'action':'create'}).status_code,400)
        self.assertEqual(self.admin.get('/calendar/shared/wrong.ics').status_code,404)
        self.action('create');old=self.token();self.action('create');self.assertEqual(self.token(),old)
        self.action('rotate');self.assertNotEqual(self.token(),old)
        self.assertEqual(self.admin.get('/calendar/shared/'+old+'.ics').status_code,404)
        token=self.token();self.action('disable')
        self.assertEqual(self.admin.get('/calendar/shared/'+token+'.ics').status_code,404)
    def test_unicode_line_folding_limits_physical_lines(self):
        source='SUMMARY:'+('é🎨,;'*80)
        folded=fold(source)
        self.assertTrue(all(len(line.encode('utf-8'))<=75 for line in folded.split('\r\n')))
        self.assertEqual(folded.replace('\r\n ',''),source)
