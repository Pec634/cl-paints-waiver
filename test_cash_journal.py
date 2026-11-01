from datetime import datetime, timedelta
from decimal import Decimal
import json
import re
import unittest
from zoneinfo import ZoneInfo
import test_business_tools as fixtures
import test_native_form_browser as browsers
from booking_cashup import OPEN_FIELDS, CLOSE_FIELDS

main = fixtures.main


class CashJournalTest(unittest.TestCase):
    browser = browsers.NativeFormBrowserTest.browser

    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.path = '/admin/cash-movements'
        self.booking = self.fixture.booking
        self.booking.status = 'Accepted'
        self.date = (datetime.now(ZoneInfo('Europe/London')).date()-timedelta(days=1)).isoformat()
        self.booking.event_schedule = json.dumps(dict(events=[dict(date=self.date, start_time='09:00', finish_time='17:00')]))
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def form(self):
        page = self.admin.get(self.path)
        return {name: re.search(fr'name="{name}" value="([^"]*)"', page.get_data(as_text=True))[1]
                for name in ('csrf_token', 'movement_token', 'version')}

    def opening(self):
        self.admin.post(self.path, data=dict(self.form(), action='opening', opening_till='20', opening_safe='100',
            reason='First stocktake', checked_by='Manager'))

    def move(self, **changes):
        data = dict(self.form(), action='transfer', source='safe', destination='till', amount='30',
            reason='Till float top-up', checked_by='Manager')
        data.update(changes)
        return self.admin.post(self.path, data=data)

    def test_initial_count_and_non_event_topup_preserve_booking_ledger(self):
        before = main.app.extensions['payment_summary'](self.booking)
        self.opening()
        self.move()
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('50'), Decimal('70')))
        self.assertEqual(main.tool_models[1].query.count(), 0)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['total'], before['total'])
        self.assertIn(b'Till float top-up', self.admin.get(self.path).data)
        self.assertEqual(main.CashMovement.query.count(), 2)
        self.move(source='till', destination='safe', reason='Reverse incorrect top-up')
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('20'), Decimal('100')))

    def test_till_pitch_fee_reduces_cash_once_and_preserves_client_payments(self):
        self.opening()
        before = main.app.extensions['payment_summary'](self.booking)['total']
        data = dict(self.form(), action='pitch_fee', source='till', amount='12.50',
            denom_pitch_used_1000='1', denom_pitch_used_200='1', denom_pitch_used_50='1',
            denom_pitch_remaining_500='1', denom_pitch_remaining_200='1', denom_pitch_remaining_50='1',
            remaining_checked='yes', pitch_count_version='',
            reason='Riverside market pitch fee', checked_by='Manager')
        self.admin.post(self.path, data=data)
        self.admin.post(self.path, data=data)
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('7.50'), Decimal('100')))
        self.assertEqual(main.CashMovement.query.filter_by(kind='pitch_fee').count(), 1)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['total'], before)
        page = self.admin.get(self.path).data
        self.assertIn(b'Pitch fee payment &middot; &pound;12.50 &middot; paid from Till', page)
        self.assertIn(b'Riverside market pitch fee', page)
        self.assertIn(b'Counted remaining till: <strong>&pound;7.50', page)
        self.assertIn(b'Notes and coins used and remaining', page)
        self.assertEqual(main.TillDenominationRecord.query.filter_by(kind='fee_used').count(), 1)
        view = main.app.extensions['till_float_view']()
        self.assertTrue(view['fresh'])
        self.assertEqual(view['current_total'], Decimal('7.50'))
        self.move(source='other', destination='till', amount='12.50', reason='Reverse incorrect pitch fee')
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('20'))

    def test_sumup_pitch_fee_needs_no_cash_setup_and_does_not_change_cash_version(self):
        before = main.app.extensions['cash_journal_position']()
        self.move(action='pitch_fee', source='sumup', amount='50', reason='Market pitch fee')
        after = main.app.extensions['cash_journal_position']()
        self.assertEqual(before, after)
        self.assertIn(b'paid from SumUp bank account', self.admin.get(self.path).data)
        self.opening()
        self.denominations('count', denom_till_2000='1')
        self.move(action='pitch_fee', source='sumup', amount='25')
        self.assertTrue(main.app.extensions['till_float_view']()['fresh'])
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('20'))

    def test_cash_sheet_without_fee_carries_balances_and_preserves_count(self):
        self.opening()
        self.denominations('target', denom_till_100='10', denom_till_1000='1')
        self.move(action='till_sheet', source='till', denom_pitch_remaining_2000='1',
            remaining_checked='yes', pitch_count_version='')
        record = main.CashMovement.query.filter_by(kind='cash_check').one()
        self.assertEqual(record.amount, Decimal('0'))
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('20'), Decimal('100')))
        view = main.app.extensions['till_float_view']()
        self.assertEqual(view['current_total'], Decimal('20'))
        self.assertTrue(view['fresh'])
        self.assertEqual(view['short_total'], Decimal('20'))
        self.assertIn(b'Till cash sheet &middot; no pitch fee', self.admin.get(self.path).data)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_live_float_plan_shows_both_transfer_directions_and_safe_uncertainty(self):
        self.opening()
        self.denominations('target', denom_till_100='10', denom_till_1000='1')
        self.browser(self.admin.get(self.path).data, '''
            const form = document.querySelector('[data-pitch-fee]');
            assert(form.textContent.includes('Previous cash records carried forward'), 'Show saved cash');
            assert(form.textContent.includes('100.00'), 'Carry safe balance');
            form.elements.source.value = 'till'; change(form.elements.source);
            form.elements.denom_pitch_remaining_2000.value = '1'; input(form.elements.denom_pitch_remaining_2000);
            const totals = form.querySelector('[data-pitch-plan-total]').textContent;
            assert(totals.includes('Safe → Till: £20.00') && totals.includes('Till → Safe: £20.00'), 'Keep both transfer directions, even when net movement is zero');
            const pound = form.querySelector('[data-pitch-plan="100"] [data-pitch-plan-move]').textContent;
            assert(pound.includes('Safe → Till: 10') && pound.includes('check safe availability'), 'Unknown safe denominations need checking');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Plan must fit phone');
        ''', width=390)

    def test_pitch_counts_validate_and_save_explained_difference_atomically(self):
        self.opening()
        base = dict(action='pitch_fee', source='till', amount='999', remaining_checked='yes',
            pitch_count_version='', denom_pitch_used_1000='1', denom_pitch_remaining_500='1')
        for changes in ({}, dict(denom_pitch_used_1000='-1'), dict(denom_pitch_used_1000='1.5'),
                        dict(denom_pitch_remaining_500='NaN'), dict(remaining_checked=''),
                        dict(denom_pitch_used_1000='3'), dict(pitch_count_version='999')):
            self.move(**dict(base, discrepancy_note='', **changes))
            self.assertEqual(main.CashMovement.query.count(), 1)
            self.assertEqual(main.TillDenominationRecord.query.count(), 0)
        self.move(**dict(base, discrepancy_note='Five pounds missing, investigating'))
        self.assertEqual(main.CashMovement.query.filter_by(kind='pitch_fee').one().amount, Decimal('10'))
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('10'))
        view = main.app.extensions['till_float_view']()
        self.assertEqual(view['current_total'], Decimal('5'))
        self.assertTrue(view['fresh'])
        self.assertIn(b'Five pounds missing, investigating', self.admin.get(self.path).data)

    def test_pitch_fee_validation_and_till_requires_initial_balance(self):
        self.move(action='pitch_fee', source='till', amount='1')
        self.assertEqual(main.CashMovement.query.count(), 0)
        self.opening()
        for changes in (dict(source='safe'), dict(source='bank'), dict(source='unknown'),
                        dict(amount='21'), dict(amount='0'), dict(amount='-1'),
                        dict(amount='NaN'), dict(amount='1.001'), dict(reason=''), dict(checked_by='')):
            self.move(action='pitch_fee', **dict(dict(source='till', amount='5'), **changes))
            self.assertEqual(main.CashMovement.query.count(), 1)

    def test_open_event_blocks_till_pitch_fee_but_allows_sumup(self):
        self.opening()
        main.db.session.add(main.BookingCashup(booking_id=self.booking.id, event_index=0,
            event_date=self.date, revision=1, phase='Open', data_json='{}', recorded_by='Manager'))
        main.db.session.commit()
        self.move(action='pitch_fee', source='till', amount='5')
        self.assertEqual(main.CashMovement.query.filter_by(kind='pitch_fee').count(), 0)
        self.move(action='pitch_fee', source='sumup', amount='50')
        self.assertEqual(main.CashMovement.query.filter_by(kind='pitch_fee').count(), 1)
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('20'))

    def denominations(self, kind, **changes):
        base = self.form()
        previous = main.TillDenominationRecord.query.filter_by(kind=kind).order_by(main.TillDenominationRecord.id.desc()).first()
        data = dict(csrf_token=base['csrf_token'], cash_version=base['version'], record_version=str(previous.id) if previous else '',
            kind=kind, checked_by='Manager', note='Count check')
        data.update(changes)
        return self.admin.post('/admin/cash-movements/till-count', data=data)

    def test_default_and_actual_denominations_show_shortages_without_moving_money(self):
        self.opening()
        self.denominations('target', denom_till_10='100')
        self.denominations('count', denom_till_2000='1')
        view = main.app.extensions['till_float_view']()
        self.assertEqual(view['target'].total, Decimal('10'))
        self.assertEqual(view['current_total'], Decimal('20'))
        self.assertEqual(view['short_total'], Decimal('10'))
        self.assertTrue(view['fresh'])
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('20'))
        self.assertEqual(main.CashMovement.query.count(), 1)
        self.assertIn(b'Saved note and coin quantities', self.admin.get(self.path).data)
        self.move()
        self.assertFalse(main.app.extensions['till_float_view']()['fresh'])

    def test_float_warning_compares_count_to_default_not_cash_journal(self):
        self.opening()
        self.denominations('target', denom_till_100='142')
        self.denominations('count', denom_till_100='133')
        page = self.admin.get(self.path)
        self.assertIn(b'&pound;9.00 below the default float', page.data)
        self.assertIn(b'Default: &pound;142.00. Counted: &pound;133.00.', page.data)
        self.assertIn(b'Cash-record discrepancy (separate from the default float)', page.data)
        self.denominations('count', denom_till_100='150')
        self.assertIn(b'&pound;8.00 above the default float', self.admin.get(self.path).data)
        self.denominations('count', denom_till_100='142')
        self.assertIn(b'The last till count matches the default float.', self.admin.get(self.path).data)

    def test_counts_validate_quantities_and_require_discrepancy_explanation(self):
        self.opening()
        for changes in (dict(denom_till_100='-1'), dict(denom_till_100='1.5'),
                        dict(denom_till_100='1000000'), dict(denom_till_5000='999999')):
            self.denominations('target', **changes)
            self.assertEqual(main.TillDenominationRecord.query.count(), 0)
        self.denominations('count', denom_till_100='10', note='')
        self.assertEqual(main.TillDenominationRecord.query.count(), 0)
        self.denominations('count', denom_till_100='10', note='Explained difference to review')
        self.assertEqual(main.TillDenominationRecord.query.count(), 1)
        self.assertEqual(main.app.extensions['cash_journal_position']()['till'], Decimal('20'))
        self.assertIn(b'Counted cash differs', self.admin.get(self.path).data)

    def test_denomination_posts_require_admin_csrf_and_fresh_versions(self):
        path = '/admin/cash-movements/till-count'
        self.assertEqual(self.fixture.client.post(path).status_code, 302)
        self.assertEqual(self.admin.post(path, data={'csrf_token':'bad'}).status_code, 400)
        self.denominations('target', denom_till_100='10')
        self.denominations('target', record_version='', denom_till_100='20')
        self.assertEqual(main.TillDenominationRecord.query.count(), 1)

    def test_till_shortages_show_safe_quantities_and_mark_them_stale_after_safe_transfer(self):
        values = {field:'0.00' for field, _ in OPEN_FIELDS+CLOSE_FIELDS}
        values.update(closing_till='20', closing_safe='10', checked_by='Manager',
            denominations={'closing_safe':{'100':10}, 'closing_till':{'2000':1}})
        main.db.session.add(main.BookingCashup(booking_id=self.booking.id, event_index=0, event_date=self.date,
            revision=1, phase='Closed', data_json=json.dumps(values), recorded_by='Manager'))
        main.db.session.commit()
        self.denominations('target', denom_till_100='5')
        view = main.app.extensions['till_float_view']()
        pound = next(row for row in view['rows'] if row['pence']==100)
        self.assertEqual(pound['short'], 5)
        self.assertEqual(pound['safe_quantity'], 10)
        self.assertEqual(pound['safe_value'], Decimal('10'))
        self.assertTrue(view['safe_fresh'])
        page = self.admin.get(self.path)
        self.assertIn(b'Enough in the safe to cover this shortage.', page.data)
        self.move(amount='1')
        self.assertFalse(main.app.extensions['till_float_view']()['safe_fresh'])
        self.assertIn(b'recount before transferring', self.admin.get(self.path).data)

    def test_missing_safe_breakdown_is_unknown_not_zero(self):
        self.opening()
        self.denominations('target', denom_till_100='5')
        self.denominations('count', denom_till_2000='1')
        self.assertIn(b'Safe quantity unknown', self.admin.get(self.path).data)

    def test_admin_csrf_validation_and_duplicate_protection(self):
        self.assertEqual(self.fixture.client.get(self.path).status_code, 302)
        self.assertEqual(self.admin.post(self.path, data={'csrf_token':'bad'}).status_code, 400)
        self.opening()
        data = dict(self.form(), action='transfer', source='safe', destination='till', amount='30', reason='Top-up', checked_by='Manager')
        self.admin.post(self.path, data=data)
        self.admin.post(self.path, data=data)
        self.assertEqual(main.CashMovement.query.count(), 2)
        for changes in (dict(amount='999'), dict(amount='-1'), dict(amount='NaN'), dict(destination='safe'), dict(reason='')):
            self.move(**changes)
            self.assertEqual(main.CashMovement.query.count(), 2)

    def test_next_event_opening_includes_topup_and_stale_forms_are_rejected(self):
        self.opening()
        path = f'/admin/bookings/{self.booking.id}/cash-up'
        page = self.admin.get(path).get_data(as_text=True)
        version = re.search(r'name="safe_external_version" value="([^"]*)"', page)[1]
        self.move()
        payload = dict(csrf_token='admin-token', version='', event_index='0', event_date=self.date, action='open',
            opening_till='50', opening_safe='70', checked_by='Manager', till_checked='yes', safe_checked='yes',
            safe_external_version=version)
        self.assertEqual(self.admin.post(path, data=payload).status_code, 400)
        page = self.admin.get(path).get_data(as_text=True)
        payload['safe_external_version'] = re.search(r'name="safe_external_version" value="([^"]*)"', page)[1]
        transfer_data = self.form()
        self.assertEqual(self.admin.post(path, data=dict(payload, opening_safe='100')).status_code, 400)
        self.assertEqual(self.admin.post(path, data=payload).status_code, 302)
        self.admin.post(self.path, data=dict(transfer_data, action='transfer', source='safe', destination='till',
            amount='10', reason='Blocked during open event', checked_by='Manager'))
        self.assertEqual(main.CashMovement.query.count(), 2, 'Off-event transfers must not overlap open cash sheets')

    def test_event_closing_becomes_new_baseline_without_reapplying_topup(self):
        self.opening()
        self.move()
        values = {field:'0.00' for field, _ in OPEN_FIELDS+CLOSE_FIELDS}
        values.update(opening_till='50', opening_safe='70', closing_till='50', closing_safe='70',
            checked_by='Manager', share_percent='0', closing_checked_at=datetime.now(ZoneInfo('Europe/London')).isoformat())
        row = main.BookingCashup(booking_id=self.booking.id, event_index=0, event_date=self.date,
            revision=1, phase='Closed', data_json=json.dumps(values), recorded_by='Manager')
        main.db.session.add(row)
        main.db.session.commit()
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('50'), Decimal('70')))
        self.assertEqual(state['movement_ids'], [])
        self.move(amount='10')
        state = main.app.extensions['cash_journal_position']()
        self.assertEqual((state['till'], state['safe']), (Decimal('60'), Decimal('60')))
        page = self.admin.get(self.path)
        self.assertIn(b'Event cash movements &amp; counts', page.data)
        self.assertIn(b'Open cash sheet', page.data)
        data = dict(csrf_token='admin-token', event_index='0', event_date=self.date, version=str(row.id), action='correct',
            **{key:'0' for key, _ in CLOSE_FIELDS}, share_percent='0', checked_by='Manager', till_checked='yes', safe_checked='yes',
            correction_reason='Change closing count', notes='Correction')
        data.update(closing_till='50', closing_safe='60')
        response = self.admin.post(f'/admin/bookings/{self.booking.id}/cash-up', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Non-event cash transfers already depend on this closing count', response.data)
        self.assertEqual(main.BookingCashup.query.count(), 1)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_closed_public_event_cash_workflow_opens_automatically(self):
        self.opening()
        event = main.Event(name='Closing fair', event_date=datetime.now(ZoneInfo('Europe/London')).date(), status='Open')
        main.db.session.add(event)
        main.db.session.commit()
        response = self.admin.post(f'/admin/events/{event.id}/status', data={'status':'Closed'})
        self.browser(self.admin.get(response.location).data, '''
            const dialog = document.querySelector('.operational-sheet-dialog');
            assert(dialog && dialog.open, 'Closing a public event must open the cash workflow automatically');
            const form = dialog.querySelector('[data-pitch-fee]');
            assert(form && form.elements.reason.value.includes('Closing fair'), 'Prefill the event reference');
            form.elements.source.value = 'till'; change(form.elements.source);
            assert(!form.querySelector('[data-pitch-count]').hidden, 'Pitch denomination counts must work in popup');
            assert(dialog.querySelector('[data-till-denominations]'), 'Allow a till count without a pitch fee');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Popup must fit a phone');
            dialog.querySelector('[data-close-sheet]').click();
            assert(!dialog.open, 'Allow dismissing the workflow without saving');
            document.querySelector('[data-open-sheet]').click();
            assert(dialog.open && form.elements.source.value === 'till', 'Reopening preserves entered values');
        ''', width=390)

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_page_fits_phone_and_finance_navigation(self):
        self.opening()
        self.browser(self.admin.get(self.path).data, '''
            const link = document.querySelector('a[href="/admin/cash-movements"]');
            assert(link && link.closest('details').querySelector('summary').textContent.includes('Finance'), 'Cash history must be under Finance & reports');
            const target = [...document.querySelectorAll('[data-till-denominations]')].find(form => form.elements.kind.value === 'target');
            for (let parent = target.parentElement; parent; parent = parent.parentElement) {
                if (parent.tagName === 'DETAILS') parent.open = true;
            }
            const pitch = document.querySelector('#pitch-fees form');
            assert(pitch && pitch.elements.action.value === 'pitch_fee', 'Pitch fees need a dedicated form');
            assert(pitch.elements.source.querySelector('option[value="till"]'), 'Till must be a payment source');
            assert(pitch.elements.source.querySelector('option[value="sumup"]'), 'SumUp must be a payment source');
            assert(pitch.checkValidity() === false, 'Pitch fee details must be required');
            pitch.elements.source.value = 'till'; change(pitch.elements.source);
            assert(!pitch.querySelector('[data-pitch-count]').hidden, 'Till counts must be visible');
            const used = pitch.elements.denom_pitch_used_1000;
            used.value = '1'; input(used);
            const remaining = pitch.elements.denom_pitch_remaining_500;
            remaining.value = '2'; input(remaining);
            assert(pitch.elements.amount.value === '10.00' && pitch.elements.amount.readOnly, 'Calculate fee from notes used');
            assert(pitch.querySelector('[data-pitch-difference]').textContent.includes('matches'), 'Reconcile remaining till');
            remaining.value = '1'; input(remaining);
            assert(pitch.elements.discrepancy_note.required, 'Require explanation for a difference');
            pitch.elements.source.value = 'sumup'; change(pitch.elements.source);
            assert(pitch.querySelector('[data-pitch-count]').disabled, 'SumUp must not require cash counts');
            assert(!pitch.elements.amount.readOnly, 'SumUp amount must be editable');
            const pound = target.querySelector('[data-till-pence="100"]');
            pound.value = '12'; pound.dispatchEvent(new Event('input', {bubbles:true}));
            assert(target.querySelector('[data-till-count-total]').textContent.includes('12.00'), 'Default float total must update when quantities change');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Cash journal must fit phone width');
        ''', width=390)
