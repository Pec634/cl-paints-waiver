import unittest
from datetime import datetime
from record_ids import record_reference, reference_record_id

class RecordIdsTest(unittest.TestCase):
    def test_format_unique_and_stable(self):
        date = datetime(2026, 10, 5)
        self.assertEqual(record_reference('B', 1, date), '05/10/2026 - B - 0001')
        self.assertEqual(record_reference('W', 36, date), '05/10/2026 - W - 0010')
        self.assertEqual(record_reference('L', 1296, date), '05/10/2026 - L - 0100')
        self.assertNotEqual(record_reference('B', 1, date), record_reference('B', 2, date))
        self.assertEqual(reference_record_id('05/10/2026 - W - 0010', 'W'), 36)
        self.assertIsNone(reference_record_id('05/10/2026 - W - 0010', 'B'))
        self.assertIsNone(reference_record_id('99/99/2026 - W - 0010', 'W'))

    def test_code_expands_instead_of_reusing(self):
        self.assertEqual(record_reference('L', 36**4, datetime(2026, 10, 5)), '05/10/2026 - L - 10000')
