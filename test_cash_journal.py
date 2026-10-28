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
    def test_page_fits_phone_and_finance_navigation(self):
        self.opening()
        self.browser(self.admin.get(self.path).data, '''
            const link = document.querySelector('a[href="/admin/cash-movements"]');
            assert(link && link.closest('details').querySelector('summary').textContent.includes('Finance'), 'Cash history must be under Finance & reports');
            const target = [...document.querySelectorAll('[data-till-denominations]')].find(form => form.elements.kind.value === 'target');
            target.closest('details').open = true;
            const pound = target.querySelector('[data-till-pence="100"]');
            pound.value = '12'; pound.dispatchEvent(new Event('input', {bubbles:true}));
            assert(target.querySelector('[data-till-count-total]').textContent.includes('12.00'), 'Default float total must update when quantities change');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Cash journal must fit phone width');
        ''', width=390)
