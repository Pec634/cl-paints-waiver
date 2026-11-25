import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch
import test_business_tools as fixtures

main = fixtures.main


class EventDayTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin
        self.event, _ = self.fixture.fixture.event()
        self.today = datetime.now(ZoneInfo('Europe/London')).date()

    def tearDown(self):
        self.fixture.tearDown()

    def test_public_event_links_and_access(self):
        with patch('event_day.api') as api:
            response = self.admin.get('/admin/event-day')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Start waiver kiosk', response.data)
            self.assertIn(b'Show loyalty QR', response.data)
            api.assert_not_called()
        self.assertEqual(main.app.test_client().get('/admin/event-day').status_code, 302)
        self.assertEqual(self.admin.get('/admin/event-day?date=bad').status_code, 400)
        page = self.admin.get('/admin/event-day?date=2000-01-01')
        self.assertIn(b'No events for this date', page.data)

    def test_private_event_excludes_waiver_tools_and_cancelled_bookings(self):
        booking = self.fixture.booking
        booking.status = 'Accepted'; booking.event_date = self.today; booking.publicity_type = 'private'
        event = main.Event(name='Private party', event_date=self.today, status='Open', booking_id=booking.id, booking_day_number=1)
        main.db.session.add(event); main.db.session.commit()
        page = self.admin.get('/admin/event-day')
        self.assertIn(b'Private party', page.data)
        self.assertIn(f'/admin/equipment?booking={booking.id}'.encode(), page.data)
        private_card = page.data.split(b'Private party')[1].split(b'</article>')[0]
        self.assertNotIn(b'waiver', private_card)
        booking.status='Cancelled'; main.db.session.commit()
        self.assertNotIn(b'Private party', self.admin.get('/admin/event-day').data)

    def test_upcoming_booking_shows_latest_booking_check_with_equipment_permission(self):
        Category, _, Entry, BookingCheck = main.equipment_models
        booking = self.fixture.booking
        booking.status = 'Accepted'
        booking.event_date = self.today + timedelta(days=2)
        day = f'/admin/event-day?date={booking.event_date.isoformat()}'
        category = Category(name='Private parties', name_key='private parties')
        main.db.session.add_all([
            category,
            Entry(category_name=category.name, recorded_by='Defaults editor',
                  recorded_at=datetime(2026, 7, 1, 9), needed=['Paints'], not_needed=[]),
        ])
        main.db.session.commit()
        self.assertIn(b'Equipment checklist not saved', self.admin.get(day).data)

        other_category = Category(name='Other category', name_key='other category')
        first = Entry(category_name=other_category.name, recorded_by='Earlier checker',
                      recorded_at=datetime(2026, 7, 1, 9, 10), needed=[], not_needed=[])
        latest = Entry(category_name=category.name, recorded_by='Latest checker',
                       recorded_at=datetime(2026, 7, 1, 9, 15), needed=[], not_needed=[])
        main.db.session.add_all([other_category, first, latest])
        main.db.session.flush()
        for entry, group in ((first, other_category), (latest, category)):
            main.db.session.add(BookingCheck(entry_id=entry.id, booking_id=booking.id,
                                              category_id=group.id, booking_label=booking.public_reference,
                                              needed_ids=[]))
        staff = main.app.extensions['pos_access'].Staff(
            username='event-day-viewer', name='Event-day viewer', role='cashier', password_hash='unused',
            permissions_json='["event_day"]')
        main.db.session.add(staff)
        main.db.session.commit()
        page = self.admin.get(day).data
        self.assertIn(b'Equipment checklist saved', page)
        self.assertIn(b'Latest check for Private parties by <strong>Latest checker</strong>', page)
        self.assertIn(b'01 Jul 2026, 10:15 BST', page)
        self.assertIn(f'/admin/equipment?booking={booking.id}&amp;category={category.id}'.encode(), page)
        self.assertNotIn(b'Earlier checker', page)
        self.assertNotIn(b'Defaults editor', page)

        staff_client = main.app.test_client()
        now = datetime.now(timezone.utc).timestamp()
        with staff_client.session_transaction() as state:
            state.update(pos_staff_id=staff.id, pos_signed_in_at=now, pos_last_activity=now)
        restricted = staff_client.get(day)
        self.assertEqual(restricted.status_code, 200)
        self.assertNotIn(b'Latest checker', restricted.data)
        self.assertNotIn(b'Equipment checklist saved', restricted.data)

        staff.permissions_json = '["event_day", "equipment"]'
        main.db.session.commit()
        self.assertIn(b'Latest checker', staff_client.get(day).data)

    def test_staff_rota_is_loaded_only_when_requested(self):
        main.db.session.add(main.BusinessSetting(key='connecteam_scheduler_id', value='123')); main.db.session.commit()
        now = int(datetime.now(ZoneInfo('Europe/London')).timestamp())
        with patch('event_day.api', return_value={'shifts':[dict(title='Event staff', startTime=now, endTime=now+3600, assignedUserIds=[1], isPublished=True)]}) as api:
            response = self.admin.get('/admin/event-day?rota=1')
            self.assertIn(b'Event staff', response.data)
            self.assertIn(b'1 staff assigned', response.data)
            self.assertEqual(api.call_count, 1)
        with patch('event_day.api', side_effect=ValueError('Unavailable')):
            response = self.admin.get('/admin/event-day?rota=1')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Staff rota could not be loaded', response.data)

    def test_closing_public_event_opens_cash_workflow_once_per_transition(self):
        path = f'/admin/events/{self.event.id}/status'
        response = self.admin.post(path, data={'status': 'Closed'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/admin/cash-movements?closed_event={self.event.id}', response.location)
        self.assertEqual(main.db.session.get(main.Event, self.event.id).status, 'Closed')
        page = self.admin.get(response.location)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'data-operational-sheet', page.data)
        self.assertIn(b'No pitch fee? Count the till', page.data)
        self.assertIn(self.event.name.encode(), page.data)
        self.assertEqual(self.admin.post(path, data={'status': 'Closed'}).location, '/admin/events')
        self.assertEqual(main.CashMovement.query.count(), 0)

    def test_linked_public_close_opens_correct_booking_day_and_private_close_does_not(self):
        booking = self.fixture.booking
        booking.status = 'Accepted'
        booking.event_schedule = '[{"date":"2026-11-01","publicity_type":"Public"},{"date":"2026-11-02","publicity_type":"Public"}]'
        self.event.booking_id = booking.id
        self.event.booking_day_number = 2
        main.db.session.commit()
        path = f'/admin/events/{self.event.id}/status'
        response = self.admin.post(path, data={'status': 'Closed'})
        self.assertIn(f'/admin/bookings/{booking.id}/cash-up?day=1', response.location)
        self.event.status = 'Open'
        booking.event_schedule = '[{"date":"2026-11-01","publicity_type":"Private"},{"date":"2026-11-02","publicity_type":"Private"}]'
        main.db.session.commit()
        self.assertEqual(self.admin.post(path, data={'status': 'Closed'}).location, '/admin/events')

    def test_close_workflow_requires_admin_and_a_closed_public_event(self):
        path = f'/admin/events/{self.event.id}/status'
        self.assertEqual(main.app.test_client().post(path, data={'status':'Closed'}).status_code, 302)
        self.assertEqual(main.db.session.get(main.Event, self.event.id).status, 'Open')
        self.assertEqual(self.admin.get(f'/admin/cash-movements?closed_event={self.event.id}').status_code, 404)
        self.assertEqual(self.admin.get('/admin/cash-movements?closed_event=999999').status_code, 404)


if __name__ == '__main__': unittest.main()
