import json
import unittest
from unittest.mock import patch
import test_booking_on_behalf as fixtures
import test_native_form_browser as browsers
from booking_edit import version

main = fixtures.main


class ClientBookingEditTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OnBehalfTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = self.fixture.admin
        self.booking = self.fixture.create()
        self.path = f'/client/bookings/{self.booking.id}/edit'

    def tearDown(self):
        self.fixture.tearDown()

    def form(self, venue='New venue'):
        data = self.fixture.form()
        with self.client.session_transaction() as session:
            data['csrf_token'] = session['client_csrf']
        data.update(booking_version=version(self.booking), signature='Test Client',
                    is_over_18='yes', liability_acknowledged='yes', terms_accepted='yes')
        events = json.loads(data['event_schedule'])
        events['events'][0]['event_address'] = venue
        data['event_schedule'] = json.dumps(events)
        return data

    def save(self, venue='New venue'):
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.client.post(self.path, data=self.form(venue))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-1500:])
        main.db.session.refresh(self.booking)

    def test_repeated_edits_require_review_and_preserve_staff_fields(self):
        self.booking.internal_notes = 'Private notes'
        self.booking.travel_charge = 15
        main.db.session.commit()
        page = self.client.get(self.path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'action="{self.path}"'.encode(), page.data)
        self.assertNotIn(b'Private notes', page.data)
        count = main.Booking.query.count()
        self.save()
        self.assertEqual(main.Booking.query.count(), count)
        self.assertEqual(self.booking.event_address, 'New venue')
        self.assertEqual(self.booking.internal_notes, 'Private notes')
        self.assertEqual(self.booking.travel_charge, 15)
        self.assertFalse(fixtures.pending_agreement(self.booking))
        self.assertEqual(self.booking.status, 'Under Review')
        item = main.BookingRequest.query.filter_by(pending_key=f'{self.booking.id}:edit').one()
        self.save('Another venue')
        self.assertEqual(main.BookingRequest.query.count(), 1)
        self.assertIn('Another venue', item.details)
        history = json.loads(self.booking.event_schedule)['client_revisions']
        self.assertEqual(len(history), 2)
        response = self.admin.post(f'/admin/bookings/{self.booking.id}/manage', data={'action': 'accept'})
        self.assertIn(f'/admin/booking-requests/{item.id}', response.location)
        self.assertEqual(self.booking.status, 'Under Review')
        review = f'/admin/booking-requests/{item.id}'
        self.assertIn(b'Booking change history', self.admin.get(review).data)
        self.admin.post(review, data=dict(csrf_token='admin-token', booking_version=version(self.booking),
                        action='complete', response='Reviewed and approved'))
        self.assertEqual(item.status, 'Completed')
        with patch.object(main, 'send_client_email', return_value=True):
            self.admin.post(f'/admin/bookings/{self.booking.id}/manage', data={'action': 'request_payment'})
            with patch('payment_workflow.confirmation_ready', return_value=True):
                self.admin.post(f'/admin/bookings/{self.booking.id}/manage', data={'action': 'accept'})
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertEqual(self.client.get(self.path).status_code, 409)
        self.assertEqual(self.client.post(self.path, data=self.form()).status_code, 409)

    def test_ownership_csrf_validation_and_stale_edits(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        bad = self.form(); bad['csrf_token'] = 'bad'
        self.assertEqual(self.client.post(self.path, data=bad).status_code, 400)
        bad = self.form(); bad['signature'] = ''
        self.assertEqual(self.client.post(self.path, data=bad).status_code, 200)
        self.assertNotEqual(self.booking.event_address, 'New venue')
        stale = self.form('Stale venue')
        self.save('Latest venue')
        response = self.client.post(self.path, data=stale)
        self.assertIn(b'Reopen the editor', response.data)
        self.assertEqual(self.booking.event_address, 'Latest venue')
        self.booking.email = 'other@example.com'; main.db.session.commit()
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.assertEqual(self.client.post(self.path, data=self.form()).status_code, 404)

    def test_new_revision_invalidates_open_admin_review_and_allows_further_edits(self):
        self.save()
        item = main.BookingRequest.query.filter_by(pending_key=f'{self.booking.id}:edit').one()
        old_version = version(self.booking)
        self.save('Latest venue')
        review = f'/admin/booking-requests/{item.id}'
        self.admin.post(review, data=dict(csrf_token='admin-token', booking_version=old_version,
                        action='complete', response='Approved'))
        self.assertEqual(item.status, 'Pending')
        self.admin.post(review, data=dict(csrf_token='admin-token', booking_version=version(self.booking),
                        action='complete', response='Approved'))
        self.assertEqual(item.status, 'Completed')
        self.booking.status = 'Awaiting Payment'; main.db.session.commit()
        self.save('Changed again')
        self.assertEqual(self.booking.status, 'Under Review')
        self.assertEqual(main.BookingRequest.query.filter_by(status='Pending').count(), 1)

    def test_prices_are_recalculated_and_staff_fields_cannot_be_posted(self):
        self.booking.internal_notes = 'Keep private'
        self.booking.company_signature = 'Staff signature'
        main.db.session.commit()
        data = self.form()
        events = json.loads(data['event_schedule'])
        events['events'][0]['finish_time'] = '13:00'
        data.update(event_schedule=json.dumps(events), status='Accepted', total_event_cost='0',
                    internal_notes='Forged', company_signature='Forged', email='other@example.com')
        rate = json.loads(self.booking.event_schedule)['pricing_rules']['hourly_rate']
        from decimal import Decimal
        with patch.object(main, 'send_client_email', return_value=False):
            response = self.client.post(self.path, data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.booking.total_event_cost, Decimal(rate) * 3)
        self.assertEqual(self.booking.status, 'Under Review')
        self.assertEqual(self.booking.email, self.fixture.email)
        self.assertEqual(self.booking.internal_notes, 'Keep private')
        self.assertEqual(self.booking.company_signature, 'Staff signature')
        self.assertEqual(main.BookingRequest.query.filter_by(status='Pending').count(), 1)
        page = self.client.get(self.path)
        self.assertIn(b'13:00', page.data)
        self.assertIn(b'value="10"', page.data)

    def test_timestamped_history_is_visible_to_client_and_admin_and_survives_review(self):
        self.save('First venue')
        self.save('Second venue')
        saved = json.loads(self.booking.event_schedule)
        self.assertTrue(saved['client_revisions'][0]['at'].endswith('+00:00'))
        saved['client_revisions'][0]['at'] = '2026-01-15T10:20:30'
        saved['client_revisions'][1]['at'] = '2026-07-15T10:20:31+00:00'
        self.booking.event_schedule = json.dumps(saved)
        main.db.session.commit()
        item = main.BookingRequest.query.filter_by(pending_key=f'{self.booking.id}:edit').one()
        review = f'/admin/booking-requests/{item.id}'
        for client, path in ((self.client, f'/client/bookings/{self.booking.id}'),
                             (self.admin, f'/admin/bookings/{self.booking.id}/activity'),
                             (self.admin, review)):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Booking change history', page.data)
            self.assertIn(b'15/01/2026 10:20:30 GMT', page.data)
            self.assertIn(b'15/07/2026 11:20:31 BST', page.data)
            self.assertIn(b'Revision 1', page.data)
            self.assertIn(b'Revision 2', page.data)
            self.assertIn(b'Before: First venue', page.data)
            self.assertIn(b'After: Second venue', page.data)
        self.admin.post(review, data=dict(csrf_token='admin-token', booking_version=version(self.booking),
                        action='complete', response='Reviewed'))
        self.assertIn(b'Revision 1', self.admin.get(review).data)
        self.assertIn(b'Revision 2', self.client.get(f'/client/bookings/{self.booking.id}').data)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_editor_prefills_events_and_serializes_client_changes_in_browser(self):
        page = self.client.get(self.path)
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const form = document.querySelector('.booking-form');
            const venue = form.querySelector('[data-event-field="event_address"]');
            assert(venue.value === 'Town Hall', 'Existing venue should be prefilled');
            assert(form.querySelector('[data-event-field="start_time"]').value === '10:00', 'Existing time missing');
            assert(form.querySelector('[name="address_property"]').value === '10', 'Billing address missing');
            assert(form.querySelector('[name="email"]').readOnly, 'Account identity should stay fixed');
            assert(form.getAttribute('action').endsWith('/edit'), 'Changes should submit to the editor');
            venue.value = 'Updated by client'; input(venue);
            form.dispatchEvent(new Event('native-draft-collect'));
            assert(JSON.parse(form.querySelector('[name="event_schedule"]').value).events[0].event_address === 'Updated by client', 'Changed venue not serialized');
            assert(form.querySelector('.booking-submit').textContent === 'Review booking changes', 'Edit action label missing');
        ''')
