from datetime import datetime, timedelta
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError
from zoneinfo import ZoneInfo
import test_business_tools as fixtures
import test_native_form_browser as browsers
from booking_cashup import CLOSE_FIELDS, totals

main = fixtures.main
Entry = main.tool_models[1]


class CashupInvoicePaymentsTest(unittest.TestCase):
    browser = browsers.NativeFormBrowserTest.browser

    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Accepted'
        self.date = (datetime.now(ZoneInfo('Europe/London')).date()-timedelta(days=1)).isoformat()
        self.booking.event_schedule = json.dumps(dict(events=[dict(date=self.date, start_time='09:00',
            finish_time='17:00', publicity_type='Private', event_type='Party', event_address='Venue')]))
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.path = f'/admin/bookings/{self.booking.id}/cash-up'
        self.route = self.path+'/invoice-payment'

    def tearDown(self):
        self.fixture.tearDown()

    def latest(self):
        return main.BookingCashup.query.filter_by(booking_id=self.booking.id).order_by(main.BookingCashup.id.desc()).first()

    def data(self, **changes):
        latest = self.latest()
        values = dict(csrf_token='admin-token', version=str(latest.id) if latest else '', event_index='0',
            event_date=self.date, invoice_checked_by='Manager', invoice_payment_confirmed='yes',
            cash_handled='no', invoice_payment_state='full', invoice_reference='2026-001', invoice_paid_date=self.date)
        values.update(changes)
        return values

    def opening(self):
        return self.admin.post(self.path, data=dict(csrf_token='admin-token', version='', event_index='0', event_date=self.date,
            action='open', opening_till='50', opening_safe='100', till_checked='yes', safe_checked='yes', checked_by='Manager'))

    def test_mixed_bank_card_full_payment_posts_once_and_closes_without_counts(self):
        data = self.data(invoice_new_bank='60', invoice_new_card='40')
        self.assertEqual(self.admin.post(self.route, data=data).status_code, 302)
        self.assertEqual(Entry.query.count(), 2)
        self.assertEqual(self.latest().phase, 'Closed')
        self.assertTrue(self.latest().values['no_cash_handled'])
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'], Decimal('100'))
        self.assertEqual(self.admin.post(self.route, data=data).status_code, 409)
        self.assertEqual(Entry.query.count(), 2)
        report = self.admin.get(self.path+'?print=1')
        self.assertIn(b'Bank transfer', report.data)
        self.assertIn(b'No physical cash was handled', report.data)
        self.assertNotIn(b'Counted closing safe cash', report.data)
        self.assertEqual(self.booking.status, 'Accepted')

    def test_existing_payment_is_selected_without_posting_again(self):
        entry = Entry(booking_id=self.booking.id, token='existing', amount=100, kind='payment', method='SumUp',
            paid_date=datetime.fromisoformat(self.date).date(), note='Verified SumUp invoice')
        main.db.session.add(entry)
        main.db.session.commit()
        self.admin.post(self.route, data=self.data(invoice_existing_ids=[str(entry.id)]))
        self.assertEqual(Entry.query.count(), 1)
        self.assertEqual(self.latest().values['invoice_payments'][0]['id'], entry.id)
        self.assertEqual(self.latest().phase, 'Closed')

    def test_partial_cash_is_added_to_safe_not_event_sales(self):
        self.assertEqual(self.opening().status_code, 302)
        self.admin.post(self.route, data=self.data(cash_handled='yes', invoice_payment_state='partial',
            invoice_new_cash='35', invoice_cash_destination='safe'))
        self.assertEqual(self.latest().phase, 'Draft')
        self.assertEqual(Entry.query.one().amount, Decimal('35'))
        self.assertEqual(totals(self.latest().values)['expected_safe'], Decimal('135'))
        self.assertEqual(totals(self.latest().values)['net'], Decimal('0'))
        row = self.latest()
        self.admin.post(self.path, data=dict(csrf_token='admin-token', version=str(row.id), event_index='0', event_date=self.date,
            action='close', **{key:'0' for key, _ in CLOSE_FIELDS}, share_percent='0', checked_by='Manager',
            till_checked='yes', safe_checked='yes', notes='Invoice receipt allocated to safe') | dict(closing_till='50', closing_safe='135'))
        self.assertEqual(self.latest().phase, 'Closed')
        self.assertEqual(totals(self.latest().values)['safe_variance'], Decimal(0))
        self.assertEqual(Entry.query.count(), 1)

    def test_invalid_or_unverified_payments_never_change_ledger(self):
        for changes in [dict(invoice_new_bank='101'), dict(invoice_new_bank='NaN'),
                        dict(invoice_new_bank='50'), dict(invoice_new_cash='100', invoice_cash_destination='safe'),
                        dict(invoice_new_bank='100', invoice_payment_confirmed=''),
                        dict(invoice_new_bank='100', invoice_reference=''),
                        dict(invoice_existing_ids=['999999']), dict(invoice_payment_state='partial')]:
            self.admin.post(self.route, data=self.data(**changes))
            self.assertEqual(Entry.query.count(), 0, changes)
            self.assertIsNone(self.latest(), changes)
        self.assertEqual(self.fixture.client.post(self.route, data=self.data()).status_code, 302)
        self.assertEqual(self.admin.post(self.route, data=self.data(csrf_token='bad')).status_code, 400)

    def test_no_cash_completion_does_not_reset_shared_safe(self):
        self.admin.post(self.route, data=self.data(invoice_new_bank='100'))
        other = self.fixture.fixture.fixture.booking('other@example.com')
        other.status = 'Accepted'
        other.event_schedule = self.booking.event_schedule
        main.db.session.commit()
        page = self.admin.get(f'/admin/bookings/{other.id}/cash-up')
        self.assertIn(b'name="safe_previous_version" value=""', page.data)

    def test_failed_sheet_commit_rolls_back_new_payment(self):
        with patch.object(main.db.session, 'commit', side_effect=IntegrityError('test failure', {}, Exception('failed'))):
            self.admin.post(self.route, data=self.data(invoice_new_bank='100'))
        self.assertEqual(Entry.query.count(), 0)
        self.assertIsNone(self.latest())

    def test_existing_cash_movement_cannot_be_used_on_two_sheets(self):
        entry = Entry(booking_id=self.booking.id, token='existing-cash', amount=35, kind='payment', method='Cash',
            paid_date=datetime.fromisoformat(self.date).date(), note='Cash invoice receipt already recorded')
        main.db.session.add(entry)
        main.db.session.commit()
        self.opening()
        self.admin.post(self.route, data=self.data(cash_handled='yes', invoice_payment_state='partial',
            invoice_existing_ids=[str(entry.id)], **{f'invoice_destination_{entry.id}':'safe'}))
        self.assertEqual(Entry.query.count(), 1)
        self.assertEqual(totals(self.latest().values)['expected_safe'], Decimal('135'))
        events = json.loads(self.booking.event_schedule)['events']
        events.append(dict(events[0]))
        self.booking.event_schedule = json.dumps(dict(events=events))
        main.db.session.commit()
        self.admin.post(self.path, data=dict(csrf_token='admin-token', version='', event_index='1', event_date=self.date,
            action='open', opening_till='0', opening_safe='0', till_checked='yes', safe_checked='yes', checked_by='Manager'))
        second = main.BookingCashup.query.filter_by(event_index=1).one()
        self.admin.post(self.route, data=self.data(event_index='1', version=str(second.id), cash_handled='yes',
            invoice_payment_state='partial', invoice_existing_ids=[str(entry.id)], **{f'invoice_destination_{entry.id}':'safe'}))
        self.assertEqual(main.BookingCashup.query.filter_by(event_index=1).count(), 1)
        self.assertEqual(Entry.query.count(), 1)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_invoice_controls_and_cash_preview_are_available(self):
        self.opening()
        self.admin.post(self.route, data=self.data(cash_handled='yes', invoice_payment_state='partial',
            invoice_new_cash='35', invoice_cash_destination='safe'))
        self.browser(self.admin.get(self.path).data, '''
            const form = document.querySelector('[data-cashup-form]');
            assert(form.dataset.invoiceSafe === '3500', 'Saved invoice safe cash must feed the preview');
            assert(document.querySelector('[data-invoice-reconciliation]').textContent.includes('35'), 'Saved invoice receipt must be visible');
            assert([...document.querySelectorAll('.operational-sheet-navigation button')].some(button=>button.textContent.includes('Invoice payment')), 'Invoice section needs a sheet shortcut');
        ''')
