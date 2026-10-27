from datetime import datetime, timedelta
import json
import unittest
from zoneinfo import ZoneInfo
import test_business_tools as fixtures
import test_native_form_browser as browser_helpers
from booking_cashup import CLOSE_FIELDS

main = fixtures.main


class DailyHandoversTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser

    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.client = self.fixture.client
        self.today = datetime.now(ZoneInfo('Europe/London')).date()
        self.path = '/admin/handovers'

    def tearDown(self):
        self.fixture.tearDown()

    def latest(self):
        return main.DailyHandover.query.order_by(main.DailyHandover.id.desc()).first()

    def data(self, **changes):
        row = self.latest()
        values = dict(csrf_token='admin-token', handover_date=self.today.isoformat(),
            version=str(row.id) if row else '', action='draft', manager_name='Private Manager',
            business_today='Market stall and private party', am_notes='PRIVATE AM NOTES',
            pm_notes='PRIVATE PM NOTES', incident_status='recorded', incidents='PRIVATE INCIDENT: action taken',
            follow_up='PRIVATE FOLLOW-UP', staff_name=['Private Staff'], staff_role=['Lead painter'],
            staff_start=['09:00'], staff_finish=['17:00'], staff_attendance=['Present'],
            staff_notes=['Break covered at noon'])
        values.update(changes)
        return values

    def test_draft_completion_staffing_and_admin_only_retrieval(self):
        self.assertEqual(self.admin.post(self.path, data=self.data()).status_code, 302)
        draft = self.latest()
        self.assertEqual(draft.status, 'Draft')
        self.assertEqual(draft.details['staff'][0]['name'], 'Private Staff')
        response = self.admin.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'PRIVATE AM NOTES', response.data)
        self.assertIn(b'PRIVATE INCIDENT', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.admin.post(self.path, data=self.data(action='complete')).status_code, 302)
        self.assertEqual(self.latest().status, 'Complete')
        self.assertEqual(main.DailyHandover.query.count(), 2)
        self.assertEqual(self.client.get(self.path).status_code, 302)
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        self.assertEqual(self.client.post(self.path, data=self.data()).status_code, 302)
        for path in ('/client/', '/client/bookings', '/client/payments'):
            page = self.client.get(path)
            self.assertNotIn(b'PRIVATE INCIDENT', page.data)
            self.assertNotIn(b'Private Staff', page.data)

    def test_validation_completion_requirements_and_escaping(self):
        for changes in (dict(manager_name=''), dict(manager_name='x'*201),
                        dict(incident_status='none'), dict(incidents=''), dict(staff_start=['25:00']),
                        dict(staff_name=['']), dict(staff_role=[]), dict(staff_attendance=['bad']),
                        dict(action='complete', am_notes=''), dict(action='complete', pm_notes=''),
                        dict(action='complete', incident_status='', incidents='')):
            response = self.admin.post(self.path, data=self.data(**changes))
            self.assertEqual(response.status_code, 400, changes)
        self.assertEqual(main.DailyHandover.query.count(), 0)
        self.assertEqual(self.admin.post(self.path, data=self.data(csrf_token='bad')).status_code, 400)
        self.assertEqual(self.admin.get(self.path+'?date=invalid').status_code, 400)
        self.admin.post(self.path, data=self.data(am_notes='<script>alert(1)</script>'))
        page = self.admin.get(self.path).data
        self.assertIn(b'&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertNotIn(b'<script>alert(1)</script>', page)

    def test_dates_drafts_and_corrections_keep_previous_revisions(self):
        future = (self.today+timedelta(days=1)).isoformat()
        self.assertEqual(self.admin.post(self.path, data=self.data(action='complete', handover_date=future)).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=self.data(handover_date=future)).status_code, 302)
        future_id = self.latest().id
        self.assertEqual(self.admin.post(self.path, data=self.data(version='', action='complete', incident_status='none', incidents='')).status_code, 302)
        completed = self.latest()
        self.assertEqual(completed.handover_date, self.today)
        self.assertEqual(self.admin.post(self.path, data=self.data(version=str(future_id))).status_code, 409)
        self.assertEqual(self.admin.post(self.path, data=self.data(action='complete')).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=self.data(correction_reason='Correct attendance')).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=self.data(action='complete',
            correction_reason='Correct attendance', staff_attendance=['Absent'])).status_code, 302)
        self.assertEqual(completed.details['staff'][0]['attendance'], 'Present')
        self.assertEqual(self.latest().details['staff'][0]['attendance'], 'Absent')
        self.assertEqual(main.DailyHandover.query.count(), 3)
        page = self.admin.get(self.path+'?date='+future)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Draft', page.data)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_staff_rows_and_event_day_link(self):
        page = self.admin.get(self.path)
        self.browser(page.data, '''
            const form = document.querySelector('[data-handover-form]');
            const rows = form.querySelector('[data-staff-rows]');
            assert(rows.children.length === 1, 'One blank staffing row should start the sheet');
            rows.querySelector('[name="staff_name"]').value = 'Alex';
            form.querySelector('[data-add-staff]').click();
            assert(rows.children.length === 2, 'Add staff must create a row');
            assert(rows.firstElementChild.querySelector('[name="staff_name"]').value === 'Alex', 'Existing staff must be preserved');
            assert(rows.lastElementChild.querySelector('[name="staff_name"]').value === '', 'New staff row must be blank');
            rows.lastElementChild.querySelector('[data-remove-staff]').click();
            assert(rows.children.length === 1, 'Remove must remove only the selected row');
            assert(form.querySelector('[name="am_notes"]') && form.querySelector('[name="pm_notes"]'), 'Both handover sections required');
        ''')
        self.assertIn(('/admin/handovers?date='+self.today.isoformat()).encode(), self.admin.get('/admin/event-day').data)

    def test_actual_shifts_manager_acknowledgement_and_private_saved_report(self):
        data = self.data(action='complete', am_manager='AM Leader', pm_manager='PM Leader',
            staff_actual_start=['09:15'], staff_actual_finish=['17:30'])
        self.assertEqual(self.admin.post(self.path, data=data).status_code, 302)
        saved = self.latest()
        self.assertEqual(saved.details['staff'][0]['start'], '09:00')
        self.assertEqual(saved.details['staff'][0]['actual_start'], '09:15')
        report = self.admin.get(self.path+'?print=1')
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'AM Leader', report.data)
        self.assertIn(b'09:15', report.data)
        self.assertNotIn(b'data-handover-form', report.data)
        self.assertIn('no-store', report.headers['Cache-Control'])
        self.assertEqual(self.client.get(self.path+'?print=1').status_code, 302)
        acknowledgement = dict(action='acknowledge', handover_date=self.today.isoformat(),
            version=str(saved.id), csrf_token='admin-token', acknowledged_by='Next Manager')
        self.assertEqual(self.admin.post(self.path, data=dict(acknowledgement, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.admin.post(self.path, data=acknowledgement).status_code, 302)
        self.assertEqual(self.latest().details['acknowledged_by'], 'Next Manager')
        self.assertEqual(self.latest().details['staff'], saved.details['staff'])
        self.assertEqual(self.admin.post(self.path, data=acknowledgement).status_code, 409)
        dashboard = self.admin.get('/admin/dashboard').data
        self.assertIn(b'Today &amp; daily actions', dashboard)
        self.assertIn(b'09:15', dashboard)
        data.update(version=str(self.latest().id), correction_reason='Update PM notes', pm_notes='Changed PM notes')
        self.assertEqual(self.admin.post(self.path, data=data).status_code, 302)
        self.assertNotIn('acknowledged_at', self.latest().details)
        self.assertIn(b'awaiting acknowledgement', self.admin.get('/admin/dashboard').data)

    def test_actual_shift_validation_and_draft_acknowledgement(self):
        self.assertEqual(self.admin.post(self.path, data=self.data(staff_actual_start=['25:00'])).status_code, 400)
        self.admin.post(self.path, data=self.data())
        self.assertEqual(self.admin.post(self.path, data=self.data(action='acknowledge', acknowledged_by='Manager')).status_code, 409)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_mobile_staff_cards_and_popup_preserve_edits(self):
        self.browser(self.admin.get(self.path).data, '''
            const dialog = document.querySelector('.operational-sheet-dialog');
            assert(dialog.open, 'Handover must open as a popup');
            const rows = dialog.querySelector('[data-staff-rows]');
            const card = rows.firstElementChild;
            assert(card.hasAttribute('data-staff-row'), 'Staff must use labelled cards');
            assert(card.getBoundingClientRect().right <= dialog.getBoundingClientRect().right, 'Staff card must fit mobile popup');
            document.querySelector('[data-add-staff]').click();
            assert(rows.lastElementChild.querySelector('[name="staff_actual_start"]'), 'New staff must have actual start time');
            assert(rows.lastElementChild.querySelector('[name="staff_actual_finish"]'), 'New staff must have actual finish time');
            const manager = dialog.querySelector('[name="manager_name"]');
            manager.value = 'Unsaved manager';
            dialog.querySelector('[data-close-sheet]').click();
            assert(!dialog.open, 'Close should dismiss popup');
            const opener = document.querySelector('[data-open-sheet]');
            assert(document.activeElement === opener, 'Focus must return to opener');
            opener.click();
            assert(dialog.open && manager.value === 'Unsaved manager', 'Reopening must preserve edits');
            assert(dialog.querySelector('.operational-sheet-navigation button'), 'Section shortcuts must be available');
        ''', width=390)

    def prepare_event_day(self, count=1):
        selected=(self.today-timedelta(days=1)).isoformat()
        booking=self.fixture.booking
        booking.status='Accepted'
        booking.event_schedule=json.dumps(dict(events=[dict(date=selected,start_time='09:00',
            finish_time='17:00',event_type='Fair',event_address='Venue',charge_type='Revenue sharing',
            revenue_share_percent='20') for _ in range(count)]))
        main.db.session.commit()
        return selected,booking

    def test_event_handovers_require_each_cashup_and_ordinary_days_do_not(self):
        ordinary=self.admin.get(self.path+'?cashup_status=1')
        self.assertEqual(ordinary.json,dict(pending=0,events=[]))
        self.assertIn(b'Cash-up is not required',self.admin.get(self.path).data)
        selected,booking=self.prepare_event_day(count=2)
        path=self.path+'?date='+selected
        self.assertEqual(self.admin.get(path+'&cashup_status=1').json['pending'],2)
        data=self.data(handover_date=selected,action='complete')
        blocked=self.admin.post(self.path,data=data)
        self.assertEqual(blocked.status_code,400)
        self.assertIn(b'Close the cash-up for every event',blocked.data)
        self.assertEqual(self.admin.post(self.path,data=dict(data,action='draft')).status_code,302)
        for index in range(2):
            cash_path=f'/admin/bookings/{booking.id}/cash-up'
            opened=self.admin.post(cash_path,data=dict(csrf_token='admin-token',event_index=str(index),
                event_date=selected,version='',action='open',opening_till='0',opening_safe='0',
                till_checked='yes',safe_checked='yes',checked_by='Manager',embed='1'))
            self.assertEqual(opened.status_code,302)
            self.assertIn('embed=1',opened.location)
            embedded=self.admin.get(opened.location)
            self.assertEqual(embedded.status_code,200)
            self.assertNotIn(b'data-open-sheet',embedded.data)
            self.assertIn(b'name="embed" value="1"',embedded.data)
            row=main.BookingCashup.query.filter_by(booking_id=booking.id,event_index=index).first()
            amounts={field:'0' for field,_ in CLOSE_FIELDS}
            closed=self.admin.post(cash_path,data=dict(amounts,csrf_token='admin-token',event_index=str(index),
                event_date=selected,version=str(row.id),action='close',share_percent='20',
                checked_by='Manager',till_checked='yes',safe_checked='yes',embed='1'))
            self.assertEqual(closed.status_code,302)
            self.assertEqual(self.admin.get(path+'&cashup_status=1').json['pending'],1-index)
        data.update(version=str(self.latest().id))
        self.assertEqual(self.admin.post(self.path,data=data).status_code,302)
        self.assertEqual(self.latest().status,'Complete')
        self.assertEqual(len(self.latest().details['cashups']),2)
        self.assertTrue(all(record['phase']=='Closed' for record in self.latest().details['cashups']))
        self.assertEqual(self.client.get(path+'&cashup_status=1').status_code,302)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_cashup_embeds_in_handover_without_discarding_notes(self):
        selected,_=self.prepare_event_day()
        self.browser(self.admin.get(self.path+'?date='+selected).data, '''
            const form=document.querySelector('[data-handover-form]');
            const section=form.querySelector('[data-handover-cashups]');
            const frame=section.querySelector('[data-cashup-frame]');
            assert(frame && frame.dataset.src.includes('embed=1'),'Event cash-up must be incorporated into the handover');
            assert(!frame.hasAttribute('src'),'Cash-up should load only when opened');
            form.elements.am_notes.value='Keep my unsaved handover notes';
            const details=section.querySelector('details');
            details.open=true; details.dispatchEvent(new Event('toggle'));
            assert(frame.hasAttribute('src'),'Opening the event must load its cash-up');
            details.open=false;
            assert(form.elements.am_notes.value==='Keep my unsaved handover notes','Toggling cash-up must preserve handover notes');
            assert(form.querySelector('[value="complete"]').disabled,'Unclosed event cash-up must prevent handover completion');
            assert(!form.querySelector('[value="draft"]').disabled,'Draft must remain available');
        ''')



if __name__ == '__main__':
    unittest.main()
