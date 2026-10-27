from datetime import datetime, timedelta
from decimal import Decimal
import json
import re
import unittest
from zoneinfo import ZoneInfo
import test_business_tools as fixtures
from booking_cashup import CLOSE_FIELDS, totals, float_return
import test_native_form_browser as browser_helpers

main = fixtures.main


class BookingCashupTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Accepted'
        self.date = (datetime.now(ZoneInfo('Europe/London')).date() - timedelta(days=1)).isoformat()
        self.booking.event_schedule = json.dumps(dict(events=[dict(date=self.date, start_time='09:00',
            finish_time='17:00', event_type='Fair', publicity_type='Public', event_address='Test venue', charge_type='Revenue sharing', revenue_share_percent='20')]))
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.client = self.fixture.client
        self.path = f'/admin/bookings/{self.booking.id}/cash-up'

    def tearDown(self):
        self.fixture.tearDown()

    def latest(self):
        return main.BookingCashup.query.order_by(main.BookingCashup.id.desc()).first()

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_closing_till_and_safe_visible_before_opening_and_enabled_after_saving(self):
        self.browser(self.admin.get(self.path).data, '''
            const form=document.querySelector('[data-cashup-form]');
            const stage=form.querySelector('.sheet-closing-stage');
            assert(stage && stage.disabled, 'Closing section should explain its opening-check prerequisite');
            assert(form.elements.closing_till && form.elements.closing_safe, 'Both closing amounts must be present from the first view');
            assert(stage.textContent.includes('Closing till & safe checks'), 'Closing checks need a clear heading');
            assert([...document.querySelectorAll('.operational-sheet-navigation button')].some(button=>button.textContent.includes('Closing till')), 'Closing checks should have a section shortcut');
            assert(form.querySelector('[name="action"][value="open"]'), 'Opening save must remain available');
        ''')
        self.opening()
        self.browser(self.admin.get(self.path).data, '''
            const form=document.querySelector('[data-cashup-form]');
            assert(!form.querySelector('.sheet-closing-stage').disabled, 'Saved opening must enable closing entry');
            assert(!form.elements.closing_till.matches(':disabled') && !form.elements.closing_safe.matches(':disabled'), 'Both closing amounts must be enabled');
            assert(form.querySelector('[name="action"][value="close"]'), 'Closing save must be available');
        ''')

    def data(self, **changes):
        row = self.latest()
        data = dict(csrf_token='admin-token', version=str(row.id) if row else '', event_index='0',
                    event_date=self.date, checked_by='PRIVATE CASH CHECKER', till_checked='yes', safe_checked='yes')
        data.update(changes)
        return data

    def opening(self, **changes):
        data = self.data(action='open', opening_till='50.00', opening_safe='100.00')
        page=self.admin.get(self.path+'?day='+str(changes.get('event_index','0'))).get_data(as_text=True)
        previous=re.search(r'name="safe_previous_version" value="([^"]*)"',page)
        data['safe_previous_version']=previous.group(1) if previous else ''
        data.update(changes)
        return self.admin.post(self.path, data=data)

    def closing(self, **changes):
        data = self.data(action='close', **{field: '0.00' for field, _ in CLOSE_FIELDS})
        data.update(cash_sales='200.00', card_sales='300.00', cash_refunds='10.00', card_refunds='20.00',
            till_to_safe='100.00', share_till='30.00', share_safe='24.00', share_bank='40.00',
            closing_till='110.00', closing_safe='176.00', share_percent='20', recipient='Organiser',
            transfer_reference='Receipt ABC')
        data.update(changes)
        return self.admin.post(self.path, data=data)

    def test_open_close_reconciliation_and_revenue_sharing_do_not_change_client_ledger(self):
        self.assertEqual(self.opening().status_code, 302)
        self.assertEqual(self.closing().status_code, 302)
        result = totals(self.latest().values)
        self.assertEqual(result['net'], Decimal('470.00'))
        self.assertEqual(result['share_due'], Decimal('94.00'))
        self.assertEqual(result['shared'], Decimal('94.00'))
        self.assertEqual(result['share_remaining'], Decimal('0.00'))
        self.assertEqual(result['retained'], Decimal('376.00'))
        self.assertEqual(result['expected_till'], Decimal('110.00'))
        self.assertEqual(result['expected_safe'], Decimal('176.00'))
        self.assertEqual(result['till_variance'], 0)
        self.assertEqual(result['safe_variance'], 0)
        self.assertEqual(main.tool_models[1].query.count(), 0)
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'], 0)
        self.assertEqual(main.BookingCashup.query.count(), 2)
        for path in (self.path, '/admin/bookings', f'/admin/bookings/{self.booking.id}/payments', f'/admin/bookings/{self.booking.id}/activity'):
            page = self.admin.get(path)
            self.assertEqual(page.status_code, 200, path)
            self.assertIn(b'Cash-up', page.data)
        page = self.admin.get(self.path)
        self.assertIn(b'Receipt ABC', page.data)
        self.assertIn('no-store', page.headers['Cache-Control'])

    def test_admin_only_and_csrf_and_review_gate(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        self.assertEqual(self.client.get(self.path).status_code, 302)
        self.assertEqual(self.client.post(self.path, data=self.data(action='open')).status_code, 302)
        self.assertEqual(self.opening(csrf_token='bad').status_code, 400)
        self.booking.status = 'Awaiting Payment'
        main.db.session.commit()
        self.assertEqual(self.opening().status_code, 409)
        self.assertEqual(main.BookingCashup.query.count(), 0)
        self.booking.status = 'Accepted'
        main.db.session.commit()
        self.opening()
        self.closing(notes='PRIVATE CASH NOTES')
        for path in (f'/client/bookings/{self.booking.id}', '/client/bookings', '/client/payments'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(b'PRIVATE CASH NOTES', page.data)
            self.assertNotIn(b'PRIVATE CASH CHECKER', page.data)
            self.assertNotIn(b'cash-up', page.data)

    def test_required_checks_valid_money_and_explained_discrepancies(self):
        for changes in (dict(till_checked=''), dict(safe_checked=''), dict(checked_by=''),
                        dict(opening_till='NaN'), dict(opening_safe='-1'), dict(opening_till='1.001')):
            self.assertEqual(self.opening(**changes).status_code, 400)
        self.assertEqual(main.BookingCashup.query.count(), 0)
        self.opening()
        for changes in (dict(till_checked=''), dict(recipient=''), dict(share_percent='101'),
                        dict(card_sales='Infinity'), dict(closing_till='109.00'), dict(safe_other_out='10.00')):
            self.assertEqual(self.closing(**changes).status_code, 400)
        self.assertEqual(self.closing(closing_till='109.00', notes='Till short by one pound.').status_code, 302)
        self.assertEqual(totals(self.latest().values)['till_variance'], Decimal('-1.00'))

    def test_stale_forms_drafts_and_corrections_preserve_history(self):
        self.assertEqual(self.closing().status_code, 400)
        self.opening()
        original = self.latest()
        self.assertEqual(self.closing(action='draft', till_checked='', safe_checked='').status_code, 302)
        self.assertEqual(self.latest().phase, 'Draft')
        self.assertEqual(self.closing(version=str(original.id)).status_code, 409)
        self.assertEqual(self.closing().status_code, 302)
        closed = self.latest()
        self.assertEqual(self.closing().status_code, 400)
        self.assertEqual(self.closing(action='correct').status_code, 400)
        self.assertEqual(self.closing(action='correct', share_bank='39', correction_reason='Transfer receipt corrected').status_code, 302)
        self.assertEqual(totals(self.latest().values)['share_remaining'], Decimal('1.00'))
        self.assertEqual(closed.values['share_bank'], '40.00')
        self.assertEqual(main.BookingCashup.query.count(), 4)

    def test_each_event_day_has_separate_counts_and_cannot_close_before_finish(self):
        future = (datetime.now(ZoneInfo('Europe/London')).date() + timedelta(days=2)).isoformat()
        events = json.loads(self.booking.event_schedule)['events']
        events.append(dict(events[0], date=future))
        self.booking.event_schedule = json.dumps(dict(events=events))
        main.db.session.commit()
        self.opening()
        self.assertEqual(self.opening(event_index='1', event_date=future, version='').status_code, 302)
        self.assertEqual(self.closing(event_index='1', event_date=future).status_code, 400)
        self.assertEqual(self.closing(event_index='1', event_date=future, action='draft').status_code, 302)
        self.assertEqual(self.latest().event_index, 1)
        self.assertIn(b'cash-up?day=1', self.admin.get('/admin/event-day?date='+future).data)
        self.assertEqual(self.opening(event_date='2000-01-01').status_code, 409)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_preview_distinguishes_takings_float_transfers_and_cash_counts(self):
        self.opening()
        self.browser(self.admin.get(self.path).data, '''
            const dialog = document.querySelector('.operational-sheet-dialog');
            assert(dialog.open, 'Cash-up must open as a popup');
            const form = document.querySelector('[data-cashup-form]');
            const set = (name, value) => { const input=form.elements.namedItem(name); input.value=value; input.dispatchEvent(new Event('input', {bubbles:true})); };
            const output = name => document.querySelector('[data-cashup-value="'+name+'"]').textContent;
            assert(form.elements.opening_till.readOnly, 'Opening check must remain preserved');
            set('cash_sales','200'); set('card_sales','300'); set('cash_refunds','10'); set('card_refunds','20');
            set('till_to_safe','100'); set('share_till','30'); set('share_safe','24'); set('share_bank','40');
            set('closing_till','110'); set('closing_safe','176');
            assert(output('net').endsWith('470.00'), 'Cash and card sales must exclude float and refunds');
            assert(output('share_due').endsWith('94.00'), 'Share must use net takings');
            assert(output('share_remaining').endsWith('0.00'), 'All transfer methods must count toward settlement');
            assert(output('expected_till').endsWith('110.00'), 'Till transfer calculation');
            assert(output('expected_safe').endsWith('176.00'), 'Safe transfer calculation');
            assert(output('till_variance').endsWith('0.00') && output('safe_variance').endsWith('0.00'), 'Counts must reconcile');
            set('closing_till','109');
            assert(output('till_variance').includes('-') && output('till_variance').endsWith('1.00'), 'Cash shortage must be visible');
            dialog.querySelector('[data-close-sheet]').click();
            assert(!dialog.open, 'Cash-up close must dismiss the popup');
            document.querySelector('[data-open-sheet]').click();
            assert(dialog.open && form.elements.closing_till.value === '109', 'Closing must preserve unsaved cash counts');
        ''')

    def test_dashboard_flags_cash_differences_and_review_preserves_money_and_history(self):
        self.opening()
        self.closing(closing_till='109', notes='Short by one pound')
        saved = self.latest()
        self.assertIn(b'needs review', self.admin.get('/admin/dashboard').data)
        report = self.admin.get(self.path+'?print=1')
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'Short by one pound', report.data)
        self.assertIn('no-store', report.headers['Cache-Control'])
        path = self.path+f'/{saved.id}/review'
        data = dict(csrf_token='admin-token', reviewed_by='Duty Manager', review_note='Count rechecked; shortage logged')
        self.assertEqual(self.admin.post(path, data=dict(data, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.assertEqual(self.admin.post(path, data=data).status_code, 302)
        self.assertEqual(totals(self.latest().values), totals(saved.values))
        self.assertEqual(self.latest().values['reviewed_by'], 'Duty Manager')
        self.assertNotIn(b'needs review', self.admin.get('/admin/dashboard').data)
        self.assertEqual(self.admin.post(path, data=data).status_code, 409)
        self.assertEqual(main.tool_models[1].query.count(), 0)
        self.assertEqual(self.closing(action='correct', closing_till='109', notes='Updated receipt',
            correction_reason='Sharing transfer corrected', share_bank='39').status_code, 302)
        self.assertNotIn('reviewed_at', self.latest().values)
        current = self.latest()
        self.admin.post(self.path+f'/{current.id}/review', data=data)
        dashboard = self.admin.get('/admin/dashboard').data
        self.assertIn(b'share difference', dashboard, 'Unpaid sharing must remain visible after cash-count review')
        self.assertIn(b'1.00', dashboard)
        self.assertEqual(self.client.get(self.path+'?print=1').status_code, 302)

    def test_dashboard_tracks_unfinished_cashups_and_reports_use_saved_revision(self):
        page = self.admin.get('/admin/dashboard').data
        self.assertIn(b'Opening / closing checks not recorded', page)
        self.opening()
        self.assertEqual(self.admin.get(self.path+'?record='+str(self.latest().id)).status_code, 200)
        self.closing()
        page = self.admin.get('/admin/dashboard').data
        self.assertIn(b'No finished event days awaiting cash-up.', page)
        other = self.fixture.fixture.fixture.booking('another@example.com')
        self.assertEqual(self.admin.get(f'/admin/bookings/{other.id}/cash-up?record={self.latest().id}').status_code, 404)

    def test_denomination_counts_override_entered_totals_and_save_float_return_plan(self):
        self.assertEqual(self.opening(count_opening_till='yes', denom_opening_till_100='50',
                                     opening_till='999').status_code, 302)
        self.assertEqual(Decimal(self.latest().values['opening_till']), Decimal('50'))
        self.assertEqual(self.closing(count_closing_till='yes', denom_closing_till_100='40',
            denom_closing_till_1000='7', closing_till='999').status_code, 302)
        saved = self.latest()
        self.assertEqual(Decimal(saved.values['closing_till']), Decimal('110'))
        plan = float_return(saved.values)
        self.assertEqual(plan['retained'], Decimal('40'))
        self.assertEqual(plan['shortage'], Decimal('10'))
        self.assertEqual(plan['surplus'], Decimal('70'))
        pound = next(row for row in plan['rows'] if row['pence']==100)
        self.assertEqual((pound['target'],pound['keep'],pound['short'],pound['surplus']), (50,40,10,0))
        report = self.admin.get(self.path+'?print=1')
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'Return to float', report.data)
        self.assertIn(b'40.00', report.data)
        self.assertEqual(main.tool_models[1].query.count(), 0)

    def test_denomination_validation_safe_counts_and_corrections_retain_history(self):
        for invalid in ('-1','1.5','NaN','1000000'):
            self.assertEqual(self.opening(count_opening_till='yes', denom_opening_till_100=invalid).status_code, 400)
        self.assertEqual(self.opening(count_opening_till='yes', denom_opening_till_5000='999999').status_code, 400)
        self.assertEqual(self.opening(count_opening_till='yes', denom_opening_till_100='50',
            count_opening_safe='yes', denom_opening_safe_5000='2').status_code, 302)
        self.assertEqual(self.closing(count_closing_till='yes', denom_closing_till_100='110',
            count_closing_safe='yes', denom_closing_safe_100='176').status_code, 302)
        saved = self.latest()
        self.assertEqual(self.closing(action='correct', correction_reason='Till recount', notes='One pound short',
            count_closing_till='yes', denom_closing_till_100='109',
            count_closing_safe='yes', denom_closing_safe_100='176').status_code, 302)
        self.assertEqual(saved.values['denominations']['closing_till']['100'], 110)
        self.assertEqual(self.latest().values['denominations']['closing_till']['100'], 109)
        self.assertEqual(self.latest().values['denominations']['opening_safe']['5000'], 2)

    def next_booking(self):
        booking=self.fixture.fixture.fixture.booking(self.booking.email,status='Accepted')
        booking.event_schedule=self.booking.event_schedule
        main.db.session.commit()
        self.booking=booking
        self.path=f'/admin/bookings/{booking.id}/cash-up'
        return booking

    def test_previous_safe_close_visible_and_opening_difference_is_rejected(self):
        self.opening()
        self.closing()
        previous=self.latest()
        self.next_booking()
        page=self.admin.get(self.path)
        self.assertIn(b'Previous closing safe check',page.data)
        self.assertIn(b'176.00',page.data)
        self.assertEqual(self.opening(version='',opening_safe='175').status_code,400)
        self.assertEqual(main.BookingCashup.query.count(),2)
        self.assertEqual(self.opening(version='',count_opening_safe='yes',denom_opening_safe_100='176',opening_safe='999').status_code,302)
        saved=self.latest()
        self.assertEqual(saved.values['safe_previous_record_id'],previous.id)
        self.assertEqual(Decimal(saved.values['opening_safe']),Decimal('176'))
        self.assertIn(b'Safe opening continuity',self.admin.get(self.path+'?print=1').data)

    def test_prior_safe_close_cannot_be_changed_to_break_a_saved_opening(self):
        self.opening(); self.closing()
        previous=self.latest()
        old_booking=self.booking; old_path=self.path
        self.next_booking()
        self.assertEqual(self.opening(version='',opening_safe='176').status_code,302)
        self.booking=old_booking; self.path=old_path
        response=self.closing(version=str(previous.id),action='correct',correction_reason='Safe recount',
            closing_safe='175',notes='One pound short')
        self.assertEqual(response.status_code,400)
        self.assertIn(b'already linked to a later opening',response.data)
        self.assertEqual(main.BookingCashup.query.count(),3)
        self.assertEqual(self.closing(version=str(previous.id),action='correct',correction_reason='Receipt correction').status_code,302)
        self.assertEqual(self.latest().values['closing_checked_at'],previous.values['closing_checked_at'])

    def test_stale_safe_baseline_is_rejected_even_when_entered_amount_matches_new_close(self):
        self.opening(); self.closing()
        previous=self.latest()
        self.assertEqual(self.closing(action='correct',correction_reason='Recount before next opening',
            closing_safe='180',notes='Four pounds over').status_code,302)
        corrected=self.latest()
        self.next_booking()
        response=self.opening(version='',opening_safe='180',safe_previous_version=str(previous.id))
        self.assertEqual(response.status_code,400)
        self.assertIn(b'previous safe closing check changed',response.data)
        self.assertEqual(self.opening(version='',opening_safe='180').status_code,302)
        self.assertEqual(self.latest().values['safe_previous_record_id'],corrected.id)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_opening_safe_must_match_previous_close_including_note_coin_counts(self):
        self.opening(); self.closing(); self.next_booking()
        self.browser(self.admin.get(self.path).data, '''
            const form=document.querySelector('[data-cashup-form]');
            const button=form.querySelector('button[value="open"]');
            const message=form.querySelector('[data-safe-difference]');
            assert(button.disabled,'Mismatched opening safe must block saving');
            const input=form.elements.opening_safe;
            input.value='176';input.dispatchEvent(new Event('input',{bubbles:true}));
            assert(!button.disabled && message.textContent.includes('matches'),'Matching count should enable opening');
            input.value='175';input.dispatchEvent(new Event('input',{bubbles:true}));
            assert(button.disabled,'Any safe difference must block saving');
            const toggle=form.querySelector('[name="count_opening_safe"]');toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));
            const coins=form.elements.denom_opening_safe_100;coins.value='176';coins.dispatchEvent(new Event('input',{bubbles:true}));
            assert(input.value==='176.00' && !button.disabled,'Denomination count must use the same matching rule');
        ''')

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_note_coin_totals_and_float_return_guidance(self):
        self.opening(count_opening_till='yes', denom_opening_till_100='50')
        self.browser(self.admin.get(self.path).data, '''
            const form = document.querySelector('[data-cashup-form]');
            const set = (name,value) => { const input=form.elements.namedItem(name); input.value=value; input.dispatchEvent(new Event('input',{bubbles:true})); };
            set('denom_closing_till_100','40'); set('denom_closing_till_1000','7');
            assert(form.elements.closing_till.value === '110.00', 'Coin counts must calculate till total');
            assert(form.elements.closing_till.readOnly, 'Counted total cannot be edited independently');
            const pound = form.querySelector('[data-float-pence="100"]');
            assert(pound.querySelector('[data-float-keep]').textContent==='40', 'Available pound coins return to float');
            assert(pound.querySelector('[data-float-short]').textContent==='10', 'Missing pound coins need top-up');
            assert(form.querySelector('[data-float-pence="1000"] [data-float-surplus]').textContent==='7', 'Ten-pound notes are surplus rather than invented coin change');
            assert(form.querySelector('[data-float-message]').textContent.includes('70.00'), 'Surplus cash total should display');
            assert(form.elements.till_to_safe.value==='0.00', 'Return advice must not create a cash movement');
            const toggle=form.querySelector('[name="count_closing_till"]'); toggle.checked=false; toggle.dispatchEvent(new Event('change',{bubbles:true}));
            assert(!form.elements.closing_till.readOnly, 'Legacy manual totals must remain available');
        ''')


if __name__ == '__main__':
    unittest.main()
