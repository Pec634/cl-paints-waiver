import re
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from werkzeug.exceptions import InternalServerError

import test_business_tools as fixtures

main = fixtures.main


class PortalExperienceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = self.fixture.admin
        self.booking = self.fixture.booking
        self.account = self.fixture.fixture.account

    def tearDown(self):
        self.fixture.tearDown()

    def test_notification_centre_ownership_filters_and_seen_state(self):
        other = self.fixture.fixture.fixture.booking('private@example.com',event_type='SECRET EVENT')
        main.db.session.add_all([
            main.BookingMessage(booking_id=self.booking.id,sender='admin',body='OWNED MESSAGE',submission_key='centre-own'),
            main.BookingMessage(booking_id=other.id,sender='admin',body='SECRET MESSAGE',submission_key='centre-other'),
        ])
        main.db.session.commit()
        page = self.client.get('/client/notifications')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'OWNED MESSAGE',page.data)
        self.assertNotIn(b'SECRET',page.data)
        self.assertIn('no-store',page.headers['Cache-Control'])
        self.assertNotIn(b'OWNED MESSAGE',self.client.get('/client/notifications?category=payments').data)
        self.assertIn(b'OWNED MESSAGE',self.client.get('/client/notifications?category=messages&state=actions').data)
        token = re.search(rb'name="read_token" value="([^"]+)"',page.data)[1].decode()
        csrf = self.fixture.fixture.fixture.csrf()
        self.assertEqual(self.client.post('/client/notifications',data=dict(csrf_token='bad',read_token=token)).status_code,400)
        self.assertEqual(self.client.post('/client/notifications',data=dict(csrf_token=csrf,read_token='bad')).status_code,400)
        self.client.post('/client/notifications',data=dict(csrf_token=csrf,read_token=token))
        self.assertNotIn(b'OWNED MESSAGE',self.client.get('/client/notifications?state=new').data)
        self.assertIn(b'OWNED MESSAGE',self.client.get('/client/notifications?state=actions').data)
        self.assertIsNone(main.BookingMessage.query.filter_by(submission_key='centre-own').one().read_at)
        self.assertEqual(self.admin.post('/admin/notifications',data=dict(csrf_token='admin-token',read_token=token)).status_code,400)
        self.assertEqual(self.client.get('/admin/notifications').status_code,302)
        self.assertEqual(self.client.get('/client/notifications?category=bad').status_code,400)

    def test_mark_seen_does_not_hide_notifications_arriving_after_render(self):
        page = self.admin.get('/admin/notifications')
        token = re.search(rb'name="read_token" value="([^"]+)"',page.data)[1].decode()
        main.db.session.add(main.BookingMessage(booking_id=self.booking.id,sender='client',body='ARRIVED LATER',submission_key='late-centre'))
        main.db.session.commit()
        self.admin.post('/admin/notifications',data=dict(csrf_token='admin-token',read_token=token))
        self.assertIn(b'ARRIVED LATER',self.admin.get('/admin/notifications?state=new').data)

    def test_search_names_references_and_wildcard_characters(self):
        self.assertEqual(self.client.get('/admin/search?q=Test').status_code,302)
        page = self.admin.get('/admin/search',query_string=dict(q=self.booking.public_reference))
        self.assertEqual(page.status_code,200)
        self.assertIn(f'/admin/bookings/{self.booking.id}/activity'.encode(),page.data)
        page = self.admin.get('/admin/search',query_string=dict(q=self.account.first_name+' '+self.account.last_name))
        self.assertIn(f'/admin/clients/{self.account.id}'.encode(),page.data)
        self.assertIn(self.account.email.encode(),page.data)
        page = self.admin.get('/admin/search?q=%25')
        self.assertNotIn(f'/admin/bookings/{self.booking.id}/activity'.encode(),page.data)
        self.assertIn(b'No matching bookings',page.data)
        self.assertIn(b'No matching bookings',self.admin.get('/admin/search?q=zzzzneverexists').data)
        self.assertEqual(self.admin.get('/admin/search',query_string={'q':'a'*101}).status_code,400)

    def test_errors_have_recovery_links_and_preserve_api_responses(self):
        page = self.client.get('/client/bookings/999999')
        self.assertEqual(page.status_code,404)
        self.assertIn(b'Return to dashboard',page.data)
        self.assertIn(b'We could not find that page',page.data)
        self.assertIn('no-store',page.headers['Cache-Control'])
        page = self.client.post(f'/client/bookings/{self.booking.id}/messages',data={})
        self.assertEqual(page.status_code,400)
        self.assertIn(b'Please open a fresh form',page.data)
        page = main.app.test_client().get('/missing-public-page')
        self.assertEqual(page.status_code,404)
        self.assertIn(b'Sign in to your portal',page.data)
        api = self.client.get('/api/not-a-route')
        self.assertEqual(api.status_code,404)
        self.assertNotIn(b'portal-recovery',api.data)

    def test_approaching_events_and_updates_are_actionable(self):
        self.booking.status='Accepted'
        self.booking.event_date=(datetime.now()+timedelta(days=2)).date()
        main.db.session.commit()
        self.assertIn(b'Prepare for an approaching event',self.client.get('/client/').data)
        self.assertIn(b'Prepare for an approaching event',self.admin.get('/admin/dashboard').data)
        Change=main.notification_models[0]
        main.db.session.add(Change(booking_id=self.booking.id,changes_json='{"Theme":{"before":"Old","after":"New"}}'))
        main.db.session.commit()
        self.assertIn(b'Review updated booking details',self.client.get('/client/').data)

    def test_client_payment_page_and_enquiries_remain_owned(self):
        other_account = main.ClientAccount(email='private@example.com',first_name='Private',last_name='Client')
        main.db.session.add(other_account); main.db.session.flush()
        self.fixture.fixture.fixture.booking(other_account.email,event_type='PRIVATE PAYMENT BOOKING')
        main.db.session.add_all([
            main.ClientEnquiry(client_id=self.account.id,subject='OWN ENQUIRY',message='My question'),
            main.ClientEnquiry(client_id=other_account.id,subject='PRIVATE ENQUIRY',message='Private question'),
        ])
        main.db.session.commit()
        page = self.client.get('/client/payments')
        self.assertEqual(page.status_code,200)
        self.assertIn(self.booking.public_reference.encode(),page.data)
        self.assertNotIn(b'PRIVATE PAYMENT BOOKING',page.data)
        self.assertIn('no-store',page.headers['Cache-Control'])
        page = self.client.get('/client/notifications')
        self.assertIn(b'OWN ENQUIRY',page.data)
        self.assertNotIn(b'PRIVATE ENQUIRY',page.data)
        self.assertEqual(main.app.test_client().get('/client/payments').status_code,302)

    def test_server_error_screen_does_not_query_the_database(self):
        with main.app.test_request_context('/client/bookings/1'), patch.object(main.db.session, 'get', side_effect=RuntimeError('Database unavailable')):
            response = main.app.handle_http_exception(InternalServerError())
        self.assertEqual(response.status_code,500)
        self.assertIn(b'We could not finish that request',response.data)
        self.assertNotIn(b'Database unavailable',response.data)

    def test_submission_search_opens_the_exact_response(self):
        Form, Submission = main.native_form_models[:2]
        form = Form(kind='giveaway',title='Search campaign',fields_json='[]',terms='Rules',enabled=True)
        main.db.session.add(form); main.db.session.flush()
        item = Submission(form_id=form.id,client_id=self.account.id,email=self.account.email,
            name='FIND THIS RESPONSE',token='search-response',answers_json='{}',terms_snapshot='Rules',title_snapshot=form.title)
        other = Submission(form_id=form.id,client_id=self.account.id,email=self.account.email,
            name='UNRELATED RESPONSE',token='other-search-response',answers_json='{}',terms_snapshot='Rules',title_snapshot=form.title)
        main.db.session.add_all([item,other]); main.db.session.commit()
        page = self.admin.get('/admin/search',query_string=dict(q=f'F-{item.id}'))
        self.assertIn(b'FIND THIS RESPONSE',page.data)
        path = f'/admin/native-forms/{form.id}/submissions?submission={item.id}'
        self.assertIn(path.encode(),page.data)
        page = self.admin.get(path)
        self.assertIn(f'id="submission-{item.id}"'.encode(),page.data)
        self.assertNotIn(b'UNRELATED RESPONSE',page.data)


if __name__ == '__main__': unittest.main()
