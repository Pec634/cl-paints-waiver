import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import json
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash, check_password_hash
import app as main


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()
        self.client = main.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.assertEqual(self.client.get('/admin/settings').status_code, 200)
        with self.client.session_transaction() as session:
            self.token = session['settings_csrf']

    def tearDown(self):
        self.context.pop()

    def save(self, section, **values):
        return self.client.post('/admin/settings', data=dict(values, section=section, csrf_token=self.token))

    def test_validation_and_business_details(self):
        self.assertEqual(main.app.test_client().get('/admin/settings').status_code, 302)
        self.assertEqual(self.client.post('/admin/settings', data={'section': 'booking'}).status_code, 400)
        self.save('booking', hourly_rate='NaN', minimum_hours='2', max_event_dates='10')
        self.assertEqual(main.get_business_settings()['hourly_rate'], '45.00')
        self.save('business', business_name='Test Paints', contact_email='hello@example.com', phone='01234', website='https://example.com')
        response = self.client.get('/booking')
        self.assertIn(b'Test Paints', response.data)
        self.assertIn(b'hello@example.com', response.data)

    def test_booking_and_saved_travel_rules(self):
        self.save('booking', hourly_rate='60.00', minimum_hours='3', max_event_dates='4')
        self.save('travel', free_miles='5', mile_rate='2', travel_cap='30')
        event = dict(date='2099-01-01', start_time='10:00', finish_time='12:00', event_address='Test venue',
                     event_type='Birthday', theme='N/A', pitch_fee_required='no', publicity_type='Private',
                     location_type='Indoors', charge_type='Client')
        values = dict(request_type='booking', client_type='individual', first_name='Test', last_name='Client',
                      email='test@example.com', phone='+447911123456', address_property='10', address_street='Abbey Road', address_city='London', address_postcode='NW10 7TR', address_country='United Kingdom',
                      signature='Test Client', date_of_birth='1990-01-01', is_over_18='yes',
                      ethnicity='Prefer not to say', religion='Prefer not to say', single_date='yes',
                      payment_preference='Full payment', liability_acknowledged='yes', terms_accepted='yes')
        values['event_schedule'] = json.dumps({'events': [event]})
        response = self.client.post('/booking', data=values)
        self.assertIn(b'at least 3 hours', response.data)
        self.assertEqual(main.Booking.query.count(), 0)
        event['finish_time'] = '13:00'
        values['event_schedule'] = json.dumps({'events': [event]})
        with patch.object(main, 'send_booking_request_confirmation', return_value=True):
            self.assertEqual(self.client.post('/booking', data=values).status_code, 302)
        booking = main.Booking.query.one()
        self.assertEqual(float(booking.total_event_cost), 180)
        self.save('booking', hourly_rate='99', minimum_hours='2', max_event_dates='10')
        self.save('travel', free_miles='0', mile_rate='10', travel_cap='100')
        self.client.post(f'/admin/bookings/{booking.id}/manage', data={'action': 'update', 'travel_miles_0': '15'})
        main.db.session.refresh(booking)
        self.assertEqual(float(booking.travel_charge), 20)
        self.assertEqual(float(booking.total_event_cost), 180)
        # Older bookings stored a bare event list and keep the original travel rules.
        booking.event_schedule = json.dumps(json.loads(booking.event_schedule)['events'])
        main.db.session.commit()
        self.client.post(f'/admin/bookings/{booking.id}/manage', data={'action': 'update', 'travel_miles_0': '15'})
        main.db.session.refresh(booking)
        self.assertEqual(float(booking.travel_charge), 5)

    def test_account_requires_current_password(self):
        main.db.session.add(main.AdminCredential(password_hash=generate_password_hash('current-password')))
        main.db.session.commit()
        self.save('account', current_password='wrong', recovery_email='new@example.com')
        self.assertNotEqual(main.get_business_settings()['recovery_email'], 'new@example.com')
        self.save('account', current_password='current-password', recovery_email='new@example.com',
                  new_password='new-password-123', confirm_password='new-password-123')
        self.assertEqual(main.get_business_settings()['recovery_email'], 'new@example.com')
        self.assertTrue(check_password_hash(main.AdminCredential.query.one().password_hash, 'new-password-123'))


if __name__ == '__main__':
    unittest.main()
