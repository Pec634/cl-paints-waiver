import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_business_tools as fixtures
import test_native_form_browser as browsers
from staff_timesheets import digest, hours, local

main = fixtures.main
Staff, Assignment, Entry, Audit = main.staff_time_models


class StaffTimesheetsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin
        self.at = datetime(2026, 11, 1, 9)
        self.clock = patch('staff_timesheets.now', side_effect=lambda: self.at); self.clock.start()
        self.event = main.Event(name='Town fair', status='Open', event_date=self.at.date(), event_address='Town hall')
        main.db.session.add(self.event); main.db.session.commit()
        self.admin.get('/admin/staff-timesheets')
        self.staff = Staff(name='Alex', token_digest=digest('test-staff-token'))
        self.other = Staff(name='Other member', token_digest=digest('another-staff-token'))
        main.db.session.add_all([self.staff, self.other]); main.db.session.commit()
        self.assignment = Assignment(staff_id=self.staff.id, event_key=f'e:{self.event.id}', event_name=self.event.name,
            event_date=self.event.event_date, venue=self.event.event_address)
        main.db.session.add(self.assignment); main.db.session.commit()
        self.worker = main.app.test_client()
        self.worker.get('/staff/clock/test-staff-token')

    def tearDown(self):
        self.clock.stop(); self.fixture.tearDown()

    def csrf(self, client):
        with client.session_transaction() as state:
            return state['staff_time_csrf']

    def punch(self, action, **extra):
        entry = Entry.query.filter_by(active_staff_id=self.staff.id).first()
        data = dict(csrf_token=self.csrf(self.worker), action=action, assignment_id=self.assignment.id,
            location_reason='Device location unavailable; manager present')
        if entry:
            data.update(entry_id=entry.id, revision=entry.revision)
        data.update(extra)
        return self.worker.post('/staff/clock', data=data)

    def manager(self, **extra):
        data = dict(csrf_token=self.csrf(self.admin)); data.update(extra)
        return self.admin.post('/admin/staff-timesheets', data=data)

    def edit(self, entry, **extra):
        data = dict(csrf_token=self.csrf(self.admin), revision=entry.revision,
            clock_in='2026-11-01T09:00+00:00', clock_out='2026-11-01T11:00+00:00', break_minutes='10',
            checked_by='Manager', reason='Corrected missed clock out')
        data.update(extra)
        return self.admin.post(f'/admin/staff-timesheets/{entry.id}', data=data)

    def test_clocking_breaks_locations_and_server_times(self):
        timestamp = self.at.replace(tzinfo=timezone.utc).timestamp()*1000
        self.punch('in', latitude='51.5', longitude='-0.1', accuracy='12', location_at=str(timestamp), clock_in='2000-01-01')
        entry = Entry.query.one()
        self.assertEqual(entry.clock_in, self.at)
        self.assertEqual(json.loads(entry.in_location)['accuracy'], 12)
        self.at += timedelta(hours=1); self.punch('break_start')
        self.at += timedelta(minutes=15); self.punch('break_end')
        self.at += timedelta(minutes=45); self.punch('out')
        main.db.session.refresh(entry)
        self.assertEqual(entry.break_seconds, 900)
        self.assertEqual(hours(entry), 1.75)
        self.assertIsNone(entry.active_staff_id)
        self.assertIn('unavailable', json.loads(entry.out_location))
        self.assertEqual(Audit.query.count(), 4)
        self.assertIn(b'1.75', self.admin.get('/admin/staff-timesheets').data)
        self.assertIn(b'Alex', self.worker.get('/staff/clock').data)

    def test_auth_csrf_private_records_and_revocation(self):
        guest = main.app.test_client()
        self.assertEqual(guest.get('/staff/clock').status_code, 403)
        self.assertEqual(guest.get('/admin/staff-timesheets').status_code, 302)
        self.assertEqual(guest.get('/staff/clock/not-a-real-token').status_code, 404)
        self.assertEqual(self.worker.post('/staff/clock', data={'action':'in'}).status_code, 400)
        self.assertEqual(self.worker.get('/admin/staff-timesheets').status_code, 302)
        self.manager(action='link', staff_id=self.staff.id)
        self.assertEqual(self.worker.get('/staff/clock').status_code, 403)
        self.assertEqual(guest.get('/staff/clock/test-staff-token').status_code, 404)

    def test_location_validation_and_explained_fallback(self):
        for changes in (dict(location_reason=''), dict(latitude='NaN', longitude='0', accuracy='1', location_at='0'),
                        dict(latitude='91', longitude='0', accuracy='1', location_at='0'),
                        dict(latitude='51', longitude='0', accuracy='1', location_at='0')):
            self.punch('in', **changes)
            self.assertEqual(Entry.query.count(), 0)
        self.punch('in')
        self.assertIn('unavailable', json.loads(Entry.query.one().in_location))
        page = self.worker.get('/staff/clock')
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertEqual(page.headers['Referrer-Policy'], 'no-referrer')

    def test_one_open_shift_and_optimistic_locking(self):
        self.punch('in'); self.punch('in')
        self.assertEqual(Entry.query.count(), 1)
        entry = Entry.query.one()
        self.at += timedelta(minutes=15)
        self.punch('break_start')
        self.punch('out', revision=1)
        main.db.session.refresh(entry)
        self.assertIsNone(entry.clock_out)
        self.punch('out')
        main.db.session.refresh(entry)
        self.assertIsNotNone(entry.clock_out)
        self.assertIsNone(entry.break_started)

    def test_assigned_staff_and_current_event_only(self):
        other_assignment = Assignment(staff_id=self.other.id, event_key=f'e:{self.event.id}', event_name='Other-only event', event_date=self.at.date(), venue='Venue')
        main.db.session.add(other_assignment); main.db.session.commit()
        self.punch('in', assignment_id=other_assignment.id)
        self.assertEqual(Entry.query.count(), 0)
        self.assertNotIn(b'Other-only event', self.worker.get('/staff/clock').data)
        self.event.event_date += timedelta(days=1); main.db.session.commit()
        self.punch('in'); self.assertEqual(Entry.query.count(), 0)
        self.event.event_date = self.at.date(); self.event.status='Archived'; main.db.session.commit()
        self.punch('in'); self.assertEqual(Entry.query.count(), 0)

    def test_manager_corrections_preserve_originals_and_reject_stale(self):
        self.punch('in'); entry=Entry.query.one()
        original_location = entry.in_location
        self.at += timedelta(hours=3)
        self.edit(entry, reason='')
        main.db.session.refresh(entry); self.assertEqual(entry.revision, 1)
        self.edit(entry)
        main.db.session.refresh(entry)
        self.assertEqual(entry.in_location, original_location)
        self.assertEqual(entry.clock_out, datetime(2026,11,1,11))
        self.assertAlmostEqual(hours(entry), 11/6)
        self.assertEqual(Audit.query.filter_by(action='manager_edit').count(), 1)
        before = json.loads(Audit.query.filter_by(action='manager_edit').one().before_json)
        self.assertIsNone(before['clock_out'])
        self.edit(entry, revision=1)
        self.assertEqual(Audit.query.filter_by(action='manager_edit').count(), 1)
        self.assertIn(b'Corrected missed clock out', self.admin.get(f'/admin/staff-timesheets/{entry.id}').data)

    def test_manual_shift_and_csv_formula_escaping(self):
        self.staff.name = '=Danger'; main.db.session.commit()
        self.at = datetime(2026,11,1,18)
        data=dict(action='manual', assignment_id=self.assignment.id, clock_in='2026-11-01T09:00', clock_out='2026-11-01T17:00',
            break_minutes='30', checked_by='Manager', reason='Forgot to clock in')
        self.manager(**data); self.manager(**data)
        self.assertEqual(Entry.query.count(), 1)
        self.assertEqual(hours(Entry.query.one()), 7.5)
        self.assertEqual(Audit.query.one().action, 'manager_added')
        csv=self.admin.get('/admin/staff-timesheets?export=csv')
        self.assertEqual(csv.mimetype, 'text/csv')
        self.assertIn(b"'=Danger", csv.data)
        self.assertIn(b'7.5', csv.data)
        self.assertEqual(self.admin.get('/admin/staff-timesheets?start=bad').status_code, 400)

    def test_public_booking_days_not_duplicated_and_private_days_supported(self):
        booking=self.fixture.booking; booking.status='Accepted'
        booking.event_schedule=json.dumps({'events':[dict(date='2026-11-01',publicity_type='Private',event_type='Party'),
            dict(date='2026-11-01',publicity_type='Public',event_type='Fair')]})
        linked=main.Event(name='Linked fair', event_date=self.at.date(), booking_id=booking.id, booking_day_number=2, status='Open')
        main.db.session.add(linked); main.db.session.commit()
        choices=main.app.extensions['staff_time_events']()
        self.assertIn(f'b:{booking.id}:0', choices)
        self.assertIn(f'b:{booking.id}:1', choices)
        self.assertNotIn(f'e:{linked.id}', choices)

    def test_staff_setup_assignments_and_disabling_access(self):
        self.manager(action='staff', name='New painter')
        created=Staff.query.filter_by(name='New painter').one()
        with self.admin.session_transaction() as state:
            message = [text for category,text in state['_flashes'] if category=='staff_link'][-1]
        token=re.search(r'/staff/clock/([A-Za-z0-9_-]+)', message)[1]
        self.assertNotEqual(created.token_digest, token)
        data=dict(action='assignment',staff_id=created.id,event_key=f'e:{self.event.id}')
        self.manager(**data); self.manager(**data)
        self.assertEqual(Assignment.query.filter_by(staff_id=created.id).count(), 1)
        self.manager(action='status',staff_id=created.id)
        self.assertEqual(main.app.test_client().get('/staff/clock/'+token).status_code, 404)

    def test_history_keeps_event_snapshot_after_event_rename(self):
        self.punch('in'); self.event.name='Renamed fair'; main.db.session.commit()
        self.assertEqual(Entry.query.one().event_name, 'Town fair')

    def test_assignment_removal_retains_history_and_prevents_clocking(self):
        self.punch('in')
        self.manager(action='unassign', assignment_id=self.assignment.id)
        main.db.session.refresh(self.assignment); self.assertTrue(self.assignment.enabled)
        self.at += timedelta(hours=1); self.punch('out')
        self.manager(action='unassign', assignment_id=self.assignment.id)
        main.db.session.refresh(self.assignment); self.assertFalse(self.assignment.enabled)
        self.punch('in')
        self.assertEqual(Entry.query.count(), 1)
        self.manager(action='assignment', staff_id=self.staff.id, event_key=f'e:{self.event.id}')
        main.db.session.refresh(self.assignment); self.assertTrue(self.assignment.enabled)

    def test_review_assignments_become_clockable_only_on_confirmation(self):
        booking=self.fixture.booking
        booking.status='Under Review'
        booking.event_schedule=json.dumps({'events':[dict(date='2026-11-01',event_type='Party',publicity_type='Private')]})
        self.assignment.event_key=f'b:{booking.id}:0'
        main.db.session.commit()
        self.punch('in')
        self.assertEqual(Entry.query.count(),0)
        self.assertIn(b'No assigned events for today',self.worker.get('/staff/clock').data)
        booking.status='Accepted';main.db.session.commit()
        self.punch('in')
        self.assertEqual(Entry.query.count(),1)

    def test_booking_save_and_confirmation_open_staff_selection(self):
        booking=self.fixture.booking;booking.status='Under Review';main.db.session.commit()
        response=self.admin.post(f'/admin/bookings/{booking.id}/manage',data={'action':'update','status':'Under Review'})
        self.assertIn(f'/admin/staff-timesheets?assign_booking={booking.id}',response.location)
        page=self.admin.get(response.location)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'data-operational-sheet',page.data)
        self.assertIn(b'provisional',page.data)
        booking.status='Awaiting Payment';main.db.session.commit()
        with patch('payment_workflow.confirmation_ready',return_value=True):
            response=self.admin.post(f'/admin/bookings/{booking.id}/manage',data={'action':'accept'})
        self.assertIn(f'assign_booking={booking.id}',response.location)
        self.assertEqual(main.db.session.get(main.Booking,booking.id).status,'Accepted')

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_booking_staff_popup_is_scoped_and_works_on_phone(self):
        booking=self.fixture.booking;booking.status='Under Review';main.db.session.commit()
        page=self.admin.get(f'/admin/staff-timesheets?assign_booking={booking.id}')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const dialog=document.querySelector('.operational-sheet-dialog');
            assert(dialog && dialog.open,'Open staff selection automatically');
            const form=dialog.querySelector('[data-staff-assignment]');
            const values=[...form.elements.event_key.options].map(option=>option.value).filter(Boolean);
            assert(values.length===1 && values[0].startsWith('b:'),'Only this booking’s event days should appear');
            assert(form.elements.event_key.value===values[0],'Preselect the first booking day');
            assert(dialog.textContent.includes('provisional'),'Explain review-stage assignments');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Staff popup fits phone');
        ''',width=390)

    def test_uk_clock_change_correction_requires_offset(self):
        self.at = datetime(2026,11,1,18)
        data=dict(action='manual', assignment_id=self.assignment.id, clock_in='2026-10-25T01:30',
            clock_out='2026-10-25T03:30', break_minutes='0', checked_by='Manager', reason='Historical shift')
        self.manager(**data); self.assertEqual(Entry.query.count(), 0)
        data['clock_in']='2026-10-25T01:30+01:00'
        self.manager(**data)
        self.assertEqual(hours(Entry.query.one()), 3)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_location_browser_capture_and_denial_fallback(self):
        browser = browsers.NativeFormBrowserTest()
        page = self.worker.get('/staff/clock').data
        browser.browser(page, '''
            const form=document.querySelector('[data-staff-clock]');
            form.elements.assignment_id.selectedIndex=1;
            form.querySelector('button[value="in"]').click();
            assert(window.clockSubmitted.get('latitude')==='51.5','Capture current latitude');
            assert(window.clockSubmitted.get('accuracy')==='12','Capture accuracy');
            assert(window.clockSubmitted.get('action')==='in','Preserve clocking action');
        ''', setup="Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(ok){ok({coords:{latitude:51.5,longitude:-0.1,accuracy:12},timestamp:Date.now()});}}});HTMLFormElement.prototype.submit=function(){window.clockSubmitted=new FormData(this);};")
        browser.browser(page, '''
            const form=document.querySelector('[data-staff-clock]');
            form.elements.assignment_id.selectedIndex=1;
            const button=form.querySelector('button[value="in"]');button.click();
            assert(!window.clockSubmitted,'No silent clocking without location or explanation');
            assert(!button.disabled,'Allow retry after location denial');
            form.elements.location_reason.value='Permission denied; manager checked arrival';button.click();
            assert(window.clockSubmitted.get('location_reason').includes('manager'),'Submit explained fallback');
            assert(window.clockSubmitted.get('latitude')==='','Do not invent a location');
        ''', setup="Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(ok,fail){fail({code:1});}}});HTMLFormElement.prototype.submit=function(){window.clockSubmitted=new FormData(this);};")

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_staff_and_manager_pages_fit_phone_and_geolocation_is_on_demand(self):
        browser = browsers.NativeFormBrowserTest()
        browser.browser(self.worker.get('/staff/clock').data, '''
            assert(document.querySelector('[data-staff-clock]'),'Show personal clocking form');
            assert(!document.querySelector('.admin aside'),'Staff must not get admin navigation');
            assert(window.locationRequests===0,'Do not track location before a clocking action');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Staff page fits phone');
        ''', width=390, setup="window.locationRequests=0;Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(){window.locationRequests++;}}});")
        self.punch('in')
        browser.browser(self.admin.get('/admin/staff-timesheets').data, '''
            assert(document.querySelector('#working-now').textContent.includes('Alex'),'Show live staff');
            assert(document.querySelector('#staff-setup'),'Show assignment controls');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Manager timesheets fit phone');
        ''', width=390)
        self.at += timedelta(hours=3)
        entry=Entry.query.one(); self.edit(entry)
        browser.browser(self.admin.get(f'/admin/staff-timesheets/{entry.id}').data, '''
            document.querySelectorAll('main details').forEach(panel=>panel.open=true);
            assert(document.querySelector('main').textContent.includes('Before'),'Show readable correction history');
            assert(document.querySelector('main').textContent.includes('review needed'),'Flag missing device location');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Audit and correction form fit phone');
        ''', width=390)


if __name__=='__main__':
    unittest.main()
