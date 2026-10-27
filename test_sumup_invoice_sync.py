from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

import test_business_tools as fixtures
from sumup_invoice_sync import history

main = fixtures.main
Entry = main.tool_models[1]


class SumupInvoiceSyncTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.admin = self.fixture.admin
        self.invoice = main.BookingInvoice(booking_id=self.booking.id, reference='2026-016',
            purpose='Deposit', amount=Decimal('45'), due_date=datetime.now().date(),
            payment_url='https://pay.sumup.com/test')
        main.db.session.add(self.invoice)
        main.db.session.commit()
        self.env = patch.dict(os.environ, SUMUP_API_KEY='test-key', SUMUP_MERCHANT_CODE='TEST')
        self.env.start()
        self.sync = main.app.extensions['sumup_invoice_sync']
        self.row = dict(id='test-transaction', amount=45, currency='GBP',
            timestamp=datetime.now(timezone.utc).isoformat(), merchant_code='TEST',
            status='SUCCESSFUL', payment_type='ECOM', product_summary='Invoice # 2026-016',
            transaction_code='TEST123', refunded_amount=0)

    def tearDown(self):
        self.env.stop()
        self.fixture.tearDown()

    def provider(self, path):
        return dict(items=[dict(self.row)], links=[]) if '/history?' in path else dict(self.row)

    def test_preview_record_and_repeat_preserve_amount_date_and_booking_status(self):
        original_status = self.booking.status
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertEqual(self.sync()['matched'], 1)
            self.assertEqual(Entry.query.count(), 0)
            self.assertEqual(self.sync(apply=True)['recorded'], 1)
            self.assertEqual(self.sync(apply=True)['already_recorded'], 1)
        entry = Entry.query.one()
        self.assertEqual(entry.amount, Decimal('45'))
        self.assertEqual(entry.paid_date, datetime.now().date())
        self.assertIn('2026-016', entry.note)
        self.assertEqual(self.booking.status, original_status)

    def test_mismatch_partial_refund_and_failed_payments_never_post(self):
        for field, value in [('amount', 20), ('currency', 'EUR'), ('status', 'FAILED'),
                             ('merchant_code', 'OTHER'), ('id', 'OTHER'),
                             ('product_summary', 'Invoice # 2026-016-extra'),
                             ('payment_type', 'POS'), ('simple_status', 'REFUNDED')]:
            detail = dict(self.row, **{field: value})
            with patch('sumup_invoice_sync.provider_get', side_effect=[dict(items=[self.row]), detail]):
                self.assertTrue(self.sync(apply=True)['review'], (field, value))
            self.assertEqual(Entry.query.count(), 0)
        self.row['refunded_amount'] = 10
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertTrue(self.sync(apply=True)['review'])
        self.assertEqual(Entry.query.count(), 0)

    def test_existing_manual_payment_and_multiple_candidates_require_review(self):
        main.db.session.add(Entry(booking_id=self.booking.id, token='manual', amount=45,
            kind='payment', method='SumUp', note='Already recorded', paid_date=datetime.now().date()))
        main.db.session.commit()
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertTrue(self.sync(apply=True)['review'])
        self.assertEqual(Entry.query.count(), 1)
        with patch('sumup_invoice_sync.provider_get', return_value=dict(items=[self.row, dict(self.row, id='second')])):
            self.assertTrue(self.sync(apply=True)['review'])
        self.assertEqual(Entry.query.count(), 1)

    def test_provider_failure_rolls_back_previously_matched_payment(self):
        main.db.session.add(main.BookingInvoice(booking_id=self.booking.id, reference='2026-017',
            purpose='Balance', amount=Decimal('45'), due_date=datetime.now().date(),
            payment_url='https://pay.sumup.com/second'))
        main.db.session.commit()
        second = dict(self.row, id='second', product_summary='Invoice # 2026-017')
        with patch('sumup_invoice_sync.provider_get', side_effect=[dict(items=[self.row, second]), self.row, ValueError('Unavailable')]):
            with self.assertRaises(ValueError):
                self.sync(apply=True)
        self.assertEqual(Entry.query.count(), 0)

    def test_exact_reference_and_balance_limit(self):
        self.row['product_summary'] = 'Invoice # 2026-0169'
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertEqual(self.sync(apply=True)['unmatched'], 1)
        self.row['product_summary'] = 'Invoice # 2026-016'
        self.booking.total_event_cost = Decimal('10')
        main.db.session.commit()
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertTrue(self.sync(apply=True)['review'])
        self.assertEqual(Entry.query.count(), 0)

    def test_admin_csrf_and_client_access(self):
        path = f'/admin/bookings/{self.booking.id}/invoices/sync'
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider) as api:
            self.assertEqual(self.fixture.client.post(path, data={'csrf_token': 'admin-token'}).status_code, 302)
            self.assertEqual(self.admin.post(path, data={'csrf_token': 'bad'}).status_code, 400)
            api.assert_not_called()
            self.assertEqual(self.admin.post(path, data={'csrf_token': 'admin-token'}).status_code, 302)
        self.assertEqual(Entry.query.count(), 1)

    def test_pagination_and_reject_external_link(self):
        with patch('sumup_invoice_sync.provider_get', side_effect=[
            dict(items=[self.row], links=[dict(rel='next', href='?oldest_ref=test')]),
            dict(items=[dict(self.row, id='second')], links=[]),
        ]) as api:
            self.assertEqual(len(history('TEST', 90)), 2)
            self.assertIn('/transactions/history?oldest_ref=test', api.call_args.args[0])
        with patch('sumup_invoice_sync.provider_get', return_value=dict(items=[], links=[dict(rel='next', href='https://example.com/steal')])):
            with self.assertRaises(ValueError):
                history('TEST', 90)

    def test_cli_defaults_to_preview(self):
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            result = main.app.test_cli_runner().invoke(args=['sync-sumup-invoices'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Entry.query.count(), 0)
            result = main.app.test_cli_runner().invoke(args=['sync-sumup-invoices', '--apply'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Entry.query.count(), 1)

    def test_subsequent_invoice_can_sync_and_later_refund_is_flagged(self):
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.sync(apply=True)
        main.db.session.add(main.BookingInvoice(booking_id=self.booking.id, reference='2026-017',
            purpose='Balance', amount=Decimal('55'), due_date=datetime.now().date(),
            payment_url='https://pay.sumup.com/second'))
        main.db.session.commit()
        self.row.update(id='second', product_summary='Invoice # 2026-017', amount=55)
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertEqual(self.sync(apply=True)['recorded'], 1)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'], Decimal('100'))
        self.row.update(status='REFUNDED', refunded_amount=55)
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.assertTrue(self.sync(apply=True)['review'])
        self.assertEqual(Entry.query.count(), 2, 'Refunds must be reviewed without silently changing the ledger')

    def test_payment_date_uses_uk_timezone(self):
        self.row['timestamp'] = '2025-07-01T23:30:00Z'
        with patch('sumup_invoice_sync.provider_get', side_effect=self.provider):
            self.sync(apply=True)
        self.assertEqual(Entry.query.one().paid_date.isoformat(), '2025-07-02')
