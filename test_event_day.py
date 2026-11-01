import unittest
from datetime import datetime
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
        private_card = page.data.split(b'Private party')[1].split(b'</article>')[0]
        self.assertNotIn(b'waiver', private_card)
        booking.status='Cancelled'; main.db.session.commit()
        self.assertNotIn(b'Private party', self.admin.get('/admin/event-day').data)

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
