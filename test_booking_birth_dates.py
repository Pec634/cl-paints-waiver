import unittest
from datetime import date
from types import SimpleNamespace
from sqlalchemy import create_engine, inspect
from booking_birth_dates import birth_date, ensure_nullable_dob


class BirthDatesTest(unittest.TestCase):
    def test_business_profile_can_omit_birth_date(self):
        from client_addresses import profile_details
        values = profile_details(dict(client_type='business', title='Ms', job_title='Manager',
            date_of_birth='', ethnicity='Prefer not to say', religion='Prefer not to say'), {})
        self.assertEqual(values['date_of_birth'], '')

    def test_business_optional_individual_required_and_excel_timestamp(self):
        self.assertIsNone(birth_date('', 'business'))
        self.assertIsNone(birth_date('00/00/00', 'Business'))
        self.assertEqual(birth_date('1990-01-02 00:00:00', 'individual'), date(1990, 1, 2))
        with self.assertRaises(ValueError):
            birth_date('', 'individual')

    def test_sqlite_migration_preserves_data_foreign_keys_indexes_and_triggers(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            connection.exec_driver_sql('CREATE TABLE booking (id INTEGER PRIMARY KEY, date_of_birth DATE NOT NULL, email TEXT)')
            connection.exec_driver_sql('CREATE UNIQUE INDEX uq_booking_email ON booking(email)')
            connection.exec_driver_sql('CREATE TABLE child (booking_id INTEGER REFERENCES booking(id))')
            connection.exec_driver_sql('CREATE TABLE audit (booking_id INTEGER)')
            connection.exec_driver_sql('CREATE TRIGGER booking_insert AFTER INSERT ON booking BEGIN INSERT INTO audit VALUES (NEW.id); END')
            connection.exec_driver_sql("INSERT INTO booking VALUES (1, '1990-01-01', 'a@example.com')")
            connection.exec_driver_sql('INSERT INTO child VALUES (1)')
        ensure_nullable_dob(SimpleNamespace(engine=engine))
        ensure_nullable_dob(SimpleNamespace(engine=engine))
        self.assertTrue(next(c for c in inspect(engine).get_columns('booking') if c['name'] == 'date_of_birth')['nullable'])
        with engine.begin() as connection:
            self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_keys').scalar(), 1)
            self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
            self.assertEqual(connection.exec_driver_sql('SELECT date_of_birth FROM booking WHERE id=1').scalar(), '1990-01-01')
            connection.exec_driver_sql("INSERT INTO booking VALUES (2, NULL, 'b@example.com')")
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM audit').scalar(), 2)
        self.assertIn('uq_booking_email', {index['name'] for index in inspect(engine).get_indexes('booking')})
        engine.dispose()
