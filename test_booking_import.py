import io
import json
import unittest
from datetime import datetime, time

from booking_import import parse_file, convert_row
import test_business_tools as fixtures

main = fixtures.main


class BookingImportTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.path = '/admin/bookings/import'
        self.admin.get(self.path)
        with self.admin.session_transaction() as session:
            self.headers = {'X-Import-Token': session['booking_import_token']}
        self.row = dict(first_name='Imported', last_name='Client', date_of_birth='01/02/1990',
            email='imported@example.com', event_date='2027-10-25', start_time='10:00',
            finish_time='12:00', event_address='Test venue')

    def tearDown(self):
        self.fixture.tearDown()

    def test_preview_does_not_write_and_save_is_atomic_and_replay_protected(self):
        count = main.Booking.query.count()
        response = self.admin.post(self.path, headers=self.headers, data={'file':
            (io.BytesIO(json.dumps([self.row]).encode()), 'bookings.json')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.Booking.query.count(), count)
        bad = dict(self.row, email='invalid')
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [self.row, bad]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(main.Booking.query.count(), count)
        self.row['theme'] = 'Edited preview'
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [self.row]})
        self.assertEqual(response.status_code, 200)
        booking = main.Booking.query.filter_by(email=self.row['email']).one()
        self.assertEqual(booking.theme, 'Edited preview')
        self.assertFalse(booking.liability_acknowledged)
        self.assertEqual(booking.signature, '')
        self.assertEqual(booking.terms_accepted_at, datetime.min)
        self.assertEqual(booking.status, 'Under Review')
        self.assertEqual(self.admin.post(self.path, headers=self.headers, json={'rows': [self.row]}).status_code, 400)

    def test_auth_csrf_duplicates_and_invalid_values(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        self.assertEqual(self.admin.post(self.path, json={'rows': [self.row]}).status_code, 400)
        self.assertEqual(self.admin.post(self.path, headers=self.headers, json={'rows': [self.row, self.row]}).status_code, 400)
        columns = [c for c in main.Booking.__table__.columns if c.name != 'id']
        for changes in ({'travel_charge': 'NaN'}, {'finish_time': '09:00'}, {'event_schedule': '{"events": []}'}, {'first_name': ''}, {'is_over_18': 'unknown'}):
            with self.assertRaises(ValueError):
                convert_row(dict(self.row, **changes), columns)

    def test_mapping_uses_booking_form_fields(self):
        from booking_import import FORM_FIELDS
        page = self.admin.get(self.path).get_data(as_text=True)
        config = json.loads(page.split('<script id="import-config" type="application/json">', 1)[1].split('</script>', 1)[0])
        self.assertEqual(config['fields'], list(FORM_FIELDS))
        self.assertIn('first_name', config['fields'])
        self.assertIn('event_address', config['fields'])
        for internal in ('id', 'submitted_at', 'terms_accepted_at', 'referral_verified', 'event_schedule', 'company_signature', 'status'):
            self.assertNotIn(internal, config['fields'])

    def test_legacy_export_assembles_addresses_without_losing_columns(self):
        headers, rows = parse_file('legacy.csv', (
            'ClientDetails_Name_First,ClientDetails_Address_Line1,ClientDetails_Address_City,'
            'EventSectionForASingularDate_Address_Line1,EventSectionForASingularDate_Address_PostalCode\n'
            'Jane,1 High Street,London,Town Hall,SW1A 1AA\n'
        ).encode())
        self.assertEqual(rows[0][headers.index('client_address')], '1 High Street, London')
        self.assertEqual(rows[0][headers.index('event_address')], 'Town Hall, SW1A 1AA')
        self.assertEqual(rows[0][0], 'Jane')
        self.assertEqual(len(headers), len(rows[0]))

    def test_separate_address_fields_are_shown_and_saved(self):
        from booking_import import FORM_FIELDS, ADDRESS_FIELDS
        for fields in ADDRESS_FIELDS.values():
            for field in fields:
                self.assertIn(field, FORM_FIELDS)
        row = dict(self.row, client_address_property='Flat 3', client_address_street='High Street',
            client_address_city='London', client_address_state='Greater London',
            client_address_postcode='SW1A 1AA', client_address_country='United Kingdom',
            client_address_country_code='GB', event_address_property='Town Hall',
            event_address_street='Market Road', event_address_city='London',
            event_address_postcode='SW1A 2AA', event_address_country='United Kingdom')
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [row]})
        self.assertEqual(response.status_code, 200)
        booking = main.Booking.query.filter_by(email=row['email']).one()
        self.assertEqual(booking.client_address, 'Flat 3\nHigh Street\nLondon\nGreater London\nSW1A 1AA\nUnited Kingdom\nGB')
        self.assertEqual(booking.event_address, 'Town Hall\nMarket Road\nLondon\nSW1A 2AA\nUnited Kingdom')

    def test_multiple_event_days_save_as_one_booking_and_check_each_day(self):
        first = dict(event_date='2027-11-01', start_time='10:00', finish_time='12:00',
                     event_address_property='Town Hall', event_address_city='London', estimated_cost='100')
        second = dict(first, event_date='2027-11-03', start_time='13:00', finish_time='16:00',
                      event_address_property='School Hall', estimated_cost='150')
        count = main.Booking.query.count()
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [dict(self.row, events=[first, second])]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.Booking.query.count(), count + 1)
        booking = main.Booking.query.filter_by(email=self.row['email']).one()
        self.assertFalse(booking.single_date)
        self.assertEqual(booking.additional_event_dates, '2027-11-03')
        self.assertEqual(booking.total_event_cost, 250)
        schedule = json.loads(booking.event_schedule)['events']
        self.assertEqual(len(schedule), 2)
        self.assertEqual(schedule[1]['duration_hours'], '3.0')
        self.assertEqual(schedule[1]['event_address'], 'School Hall\nLondon')
        calendar_days = [row for row in main.app.extensions['calendar_rows']() if row['booking'] == booking]
        self.assertEqual(len(calendar_days), 2)
        self.assertEqual(self.admin.get('/admin/calendar?month=2027-11').status_code, 200)
        self.assertEqual(self.admin.get('/admin/bookings').status_code, 200)
        self.admin.get(self.path)
        with self.admin.session_transaction() as session:
            headers = {'X-Import-Token': session['booking_import_token']}
        response = self.admin.post(self.path, headers=headers, json={'rows': [dict(self.row, events=[second])]})
        self.assertEqual(response.status_code, 400)
        self.assertIn('already exists', response.json['errors'][0])

    def test_invalid_second_day_prevents_entire_import(self):
        day = dict(event_date='2027-11-01', start_time='10:00', finish_time='12:00', event_address='Hall')
        count = main.Booking.query.count()
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [dict(self.row, events=[day, dict(day, event_date='bad-date')])]})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Event day 2', response.json['errors'][0])
        self.assertEqual(main.Booking.query.count(), count)

    def test_legacy_datetime_times_are_normalized_before_length_validation(self):
        columns = [column for column in main.Booking.__table__.columns if column.name != 'id']
        for start, finish in [('2026-10-24 15:00:00', '2026-10-24 17:00:00'),
                              ('15:00:00', '17:00:00'), ('3:00 PM', '5:00 PM')]:
            values = convert_row(dict(self.row, start_time=start, finish_time=finish), columns)
            self.assertEqual(values['start_time'], '15:00')
            self.assertEqual(values['finish_time'], '17:00')
        headers, rows = parse_file('legacy.csv', b'ClientDetails_Name_First,EventSectionForASingularDate_StartTime\nJane,2026-10-24 15:00:00\n')
        self.assertEqual(rows[0][1], '15:00')

    def test_placeholder_birth_date_is_explained_and_not_invented(self):
        response = self.admin.post(self.path, headers=self.headers, json={'rows': [dict(self.row, date_of_birth='00/00/00')]})
        self.assertEqual(response.status_code, 400)
        self.assertIn('placeholder date', response.json['errors'][0])
        self.assertIsNone(main.Booking.query.filter_by(email=self.row['email']).first())

    def test_excel_links_event_day_worksheet_by_parent_id(self):
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['ClientBookingRequest_Id', 'first_name'])
        book.active.append(['parent-1', 'Jane'])
        book.active.append(['parent-2', 'John'])
        days = book.create_sheet('EventDetails')
        days.append(['ClientBookingRequest_Id', 'EventDetails_Id', 'Date', 'StartTime', 'FinishTime', 'Address_Line1'])
        days.append(['parent-1', 'day-1', datetime(2027, 11, 1), time(10), time(12), 'Town Hall'])
        days.append(['parent-1', 'day-2', datetime(2027, 11, 3), time(13), time(16), 'School Hall'])
        days.append(['parent-2', 'day-3', datetime(2027, 11, 5), time(10), time(12), 'Other Hall'])
        stream = io.BytesIO(); book.save(stream); book.close()
        headers, rows = parse_file('bookings.xlsx', stream.getvalue())
        first = json.loads(rows[0][headers.index('events')])
        second = json.loads(rows[1][headers.index('events')])
        self.assertEqual(len(first), 2)
        self.assertEqual(first[1]['event_address_property'], 'School Hall')
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]['event_address_property'], 'Other Hall')

    def test_supported_files_and_bad_headers(self):
        self.assertEqual(parse_file('test.csv', b'first_name;last_name\nJane;Smith')[1], [['Jane', 'Smith']])
        self.assertEqual(parse_file('test.tsv', b'first_name\tlast_name\nJane\tSmith')[0], ['first_name', 'last_name'])
        from openpyxl import Workbook
        book = Workbook(); book.active.append(['first_name']); book.active.append(['Jane'])
        stream = io.BytesIO(); book.save(stream); book.close()
        self.assertEqual(parse_file('test.xlsx', stream.getvalue())[1], [['Jane']])
        with self.assertRaises(ValueError):
            parse_file('test.csv', b'name,name\nJane,Smith')

    def test_excel_ignores_formatted_empty_rows_and_columns(self):
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill
        book = Workbook()
        sheet = book.active
        sheet.append([])
        sheet.append(['first_name', 'start_time', 'event_date', 'notes'])
        sheet.append(['Jane', time(10, 30), datetime(2027, 10, 25)])
        sheet.append([])
        sheet.append(['John', time(11), datetime(2027, 10, 26), 'Keep this'])
        sheet.cell(500, 150).fill = PatternFill(fill_type='solid', fgColor='FFFF00')
        stream = io.BytesIO(); book.save(stream); book.close()
        headers, rows = parse_file('bookings.xlsx', stream.getvalue())
        self.assertEqual(headers, ['first_name', 'start_time', 'event_date', 'notes'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ['Jane', '10:30', '2027-10-25 00:00:00', ''])
        self.assertEqual(rows[1][-1], 'Keep this')

    def test_excel_limits_still_apply_to_real_bookings(self):
        from openpyxl import Workbook
        book = Workbook(); book.active.append(['first_name'])
        for index in range(201):
            book.active.append([f'Client {index}'])
        stream = io.BytesIO(); book.save(stream); book.close()
        with self.assertRaisesRegex(ValueError, '200 bookings'):
            parse_file('bookings.xlsx', stream.getvalue())

    def test_wide_booking_export_and_sparse_columns(self):
        from openpyxl import Workbook
        book = Workbook()
        headers = [f'Field {index}' for index in range(104)]
        book.active.append(headers)
        book.active.append([f'Value {index}' for index in range(104)])
        stream = io.BytesIO(); book.save(stream)
        parsed_headers, rows = parse_file('bookings.xlsx', stream.getvalue())
        self.assertEqual(parsed_headers, headers)
        self.assertEqual(len(rows[0]), 104)
        book.close()
        book = Workbook()
        book.active.cell(1, 600, 'Email')
        book.active.cell(2, 600, 'client@example.com')
        stream = io.BytesIO(); book.save(stream); book.close()
        self.assertEqual(parse_file('bookings.xlsx', stream.getvalue()), (['Email'], [['client@example.com']]))

    def test_excel_rejects_more_than_500_populated_columns(self):
        from openpyxl import Workbook
        book = Workbook(); book.active.append([f'Field {index}' for index in range(501)])
        book.active.append(['value'] * 501)
        stream = io.BytesIO(); book.save(stream); book.close()
        with self.assertRaisesRegex(ValueError, '500 populated columns'):
            parse_file('bookings.xlsx', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
