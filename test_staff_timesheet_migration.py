import unittest
from types import SimpleNamespace
from sqlalchemy import create_engine, inspect
from staff_timesheets import ensure_schema


class StaffMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_rows_backfills_snapshots_and_is_repeatable(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE staff_assignment (id INTEGER PRIMARY KEY, event_name TEXT, event_date DATE, venue TEXT)')
            connection.exec_driver_sql("INSERT INTO staff_assignment VALUES (1,'Original fair','2026-11-01','Town hall')")
            connection.exec_driver_sql('CREATE TABLE staff_time_entry (id INTEGER PRIMARY KEY, assignment_id INTEGER, clock_in TEXT)')
            connection.exec_driver_sql("INSERT INTO staff_time_entry VALUES (7,1,'2026-11-01 09:00:00')")
        db = SimpleNamespace(engine=engine)
        ensure_schema(db)
        with engine.begin() as connection:
            row = connection.exec_driver_sql('SELECT id,event_name,event_date,venue,clock_in FROM staff_time_entry').one()
            self.assertEqual(tuple(row), (7,'Original fair','2026-11-01','Town hall','2026-11-01 09:00:00'))
            self.assertEqual(connection.exec_driver_sql('SELECT enabled FROM staff_assignment').scalar(), 1)
            connection.exec_driver_sql("UPDATE staff_assignment SET event_name='Renamed later'")
        ensure_schema(db)
        with engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT event_name FROM staff_time_entry').scalar(), 'Original fair')
        self.assertIn('submission_token', {c['name'] for c in inspect(engine).get_columns('staff_time_entry')})
