import json
import unittest
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch
import test_business_tools as fixtures
from test_admin_polish_browser import BrowserChecks, EDGE

main = fixtures.main


class BookingEditTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Under Review'
        stored = json.loads(self.booking.event_schedule or '{}')
        if not isinstance(stored, dict):
            stored = {'events': stored}
        stored['pricing_rules'] = dict(hourly_rate='50', minimum_hours='2', free_miles='10', mile_rate='1', travel_cap='50')
        self.booking.event_schedule = json.dumps(stored)
        main.db.session.commit()
        self.admin = self.fixture.admin
        self.path = f'/admin/bookings/{self.booking.id}/edit'

    def tearDown(self):
        self.fixture.tearDown()

    def payload(self):
        response = self.admin.get(self.path)
        self.assertEqual(response.status_code, 200)
        config = json.loads(response.get_data(as_text=True).split('<script id="import-config" type="application/json">', 1)[1].split('</script>', 1)[0])
        row = dict(zip(config['initialSource']['headers'], config['initialSource']['rows'][0]))
        row['events'] = json.loads(row['events'])
        return {'rows': [row], 'version': config['version']}, {'X-Import-Token': config['token']}

    def test_admin_edits_through_prefilled_booking_form(self):
        page = self.admin.get(self.path)
        self.assertIn(b'class="booking-form"', page.data)
        self.assertNotIn(b'Test address', page.data)
        self.assertNotIn(self.booking.email.encode(), page.data)
        self.assertNotIn(b'name="signature"', page.data)
        if EDGE.is_file():
            BrowserChecks.browser(self, page.data, '''
                const form = document.querySelector('.booking-form');
                for (const selector of ['.booking-availability-check', '.booking-saved-pricing']) {
                    const panel = form.querySelector(selector);
                    assert(parseFloat(getComputedStyle(panel).paddingInlineStart) >= 18, 'panel content touches the edge');
                }
                assert(!form.querySelector('[name="first_name"], [name="email"]'), 'client details appear in the editor');
                assert(!new FormData(form).has('client_address'), 'client address should not be submitted');
                assert(form.querySelector('[data-event-field="date"]').value === '2099-01-01', 'date was not prefilled');
                assert(form.querySelector('[data-event-field="event_address"]').value === 'Test venue', 'venue was not prefilled');
                window.fetch = async (url, options) => {
                    const schedule = JSON.parse(options.body.get('event_schedule'));
                    assert(options.body.get('action') === 'quote' && schedule.events[0].travel_miles === '30',
                        'mileage was not sent for a quote');
                    assert(options.body.get('payment_preference') === '50% deposit', 'deposit option was not quoted');
                    return Response.json({quote: {event_total: '100.00', total: '120.00', travel: '20.00', outstanding: '120.00', deposit: '60.00',
                        days: [{travel: '20.00'}], notes: []}});
                };
                const miles = form.querySelector('[data-event-field="travel_miles"]');
                form.elements.payment_preference.value = '50% deposit';
                miles.value = '30';
                miles.dispatchEvent(new Event('input', {bubbles: true}));
                await new Promise(resolve => setTimeout(resolve, 550));
                assert(form.querySelector('[data-day-travel-estimate]').textContent.includes('£20.00'), 'day travel did not update');
                assert(form.querySelector('#booking-travel-estimate').textContent.includes('£20.00'), 'travel total did not update');
                assert(form.querySelector('#adminTravelCharge').textContent === '£20.00', 'payment travel did not update');
                assert(form.querySelector('#adminBookingTotal').textContent === '£120.00', 'payment total did not update');
                assert(!form.elements.payment_preference.querySelector('[value="No payment required"]'),
                    'positive booking total should hide the no-payment option');
                assert(!form.querySelector('#adminOutstandingBalance'), 'unconfirmed booking should show the total only');
                assert(!form.querySelector('#depositEstimateRow').hidden && form.querySelector('#depositEstimateAmount').textContent === '£60.00',
                    'deposit did not include travel');
                assert(form.checkValidity(), 'saved booking should be ready to review');
                form.querySelector('.booking-submit').click();
                assert(document.querySelector('#bookingReviewDialog').open, 'review dialog did not open');
                assert(!document.querySelector('#bookingReviewContent').textContent.includes('Client details'),
                    'client details appear in the review dialog');
                const schedule = JSON.parse(form.elements.event_schedule.value);
                assert(schedule.events[0].start_time === '10:00', 'form did not serialize the saved time');
            ''', 1100)
        data, headers = self.payload()
        row = data['rows'][0]
        events = row.pop('events')
        events[0]['theme'] = 'Space'
        row.update(csrf_token=headers['X-Import-Token'], booking_version=data['version'],
                   event_schedule=json.dumps({'events': events}), client_address='Forged address',
                   email='forged@example.com')
        original_email = self.booking.email
        events[0]['travel_miles'] = '30'
        quote = self.admin.post(self.path, data=dict(row, action='quote', payment_preference='50% deposit',
            event_schedule=json.dumps({'events': events})))
        self.assertEqual(quote.json['quote']['travel'], '20.00')
        self.assertEqual(quote.json['quote']['deposit'], '60.00')
        events[0]['charge_type'] = 'Customers'
        travel_only = dict(row, payment_preference='No payment required', event_schedule=json.dumps({'events': events}))
        self.assertEqual(self.admin.post(self.path, data=dict(travel_only, action='quote')).json['quote']['total'], '20.00')
        self.assertEqual(self.admin.post(self.path, data=travel_only).status_code, 400)
        with patch.object(main, 'send_client_email', return_value=True):
            self.assertEqual(self.admin.post(self.path, data=row).status_code, 302)
        self.assertEqual(self.booking.theme, 'Space')
        self.assertEqual(self.booking.signature, 'Test')
        self.assertEqual(self.booking.client_address, 'Test address')
        self.assertEqual(self.booking.email, original_email)
        stale = self.admin.post(self.path, data=row)
        self.assertEqual(stale.status_code, 409)
        self.assertIn(f'name="booking_version" value="{data["version"]}"'.encode(), stale.data)

    def test_admin_editor_selects_and_saves_no_payment_when_total_and_balance_are_zero(self):
        self.booking.status = 'Accepted'
        self.booking.charge_type = 'Customers'
        self.booking.total_event_cost = Decimal(0)
        self.booking.travel_charge = Decimal(0)
        self.booking.payment_preference = '50% deposit'
        main.db.session.commit()

        page = self.admin.get(self.path)
        self.assertIn(b'<option value="No payment required" selected>', page.data)
        if EDGE.is_file():
            BrowserChecks.browser(self, page.data, '''
                const form = document.querySelector('.booking-form');
                const preference = form.elements.payment_preference;
                const miles = form.querySelector('[data-event-field="travel_miles"]');
                const depositRow = document.querySelector('#depositEstimateRow');
                const assertFree = () => {
                    assert(preference.value === 'No payment required' && preference.disabled, 'zero should select no payment');
                    assert(depositRow.hidden, 'free bookings should hide the deposit estimate');
                };
                assertFree();
                window.fetch = async (url, options) => {
                    const schedule = JSON.parse(options.body.get('event_schedule'));
                    const charge = schedule.events[0].travel_miles === '30' ? '20.00' : '0.00';
                    return Response.json({quote: {event_total: '0.00', total: charge, travel: charge, outstanding: '0.00',
                        deposit: null, days: [{travel: charge}], notes: []}});
                };
                miles.value = '30';
                change(miles);
                await new Promise(resolve => setTimeout(resolve, 500));
                assert(!preference.disabled && !preference.value, 'a positive total should prompt for payment preference');
                assert(!preference.querySelector('[value="No payment required"]'), 'a zero balance alone should not allow the option');
                miles.value = '0';
                change(miles);
                await new Promise(resolve => setTimeout(resolve, 500));
                assertFree();
            ''', 1100)

        data, headers = self.payload()
        row = data['rows'][0]
        row['events'][0].update(charge_type='Customers', travel_miles='0')
        quote = self.admin.post(self.path, headers=headers, json=dict(data, action='quote')).json['quote']
        self.assertEqual((quote['total'], quote['outstanding'], quote['deposit']), ('0.00', '0.00', None))

        form = dict(row, csrf_token=headers['X-Import-Token'], booking_version=data['version'],
                    event_schedule=json.dumps({'events': row['events']}))
        form.pop('payment_preference')
        with patch.object(main, 'send_client_email', return_value=True):
            self.assertEqual(self.admin.post(self.path, data=form).status_code, 302)
        self.assertEqual(self.booking.payment_preference, 'No payment required')

    def test_edits_update_portal_notifications_and_audit_and_preserve_consent(self):
        data, headers = self.payload()
        original_signature = self.booking.signature
        original_terms = self.booking.terms_accepted_at
        row = data['rows'][0]
        row.update(first_name='Changed', phone='+447911123999', internal_notes='PRIVATE ADMIN NOTE', signature='forged', status='Accepted')
        row['events'][0]['theme'] = 'New theme'
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.booking.first_name, 'Test')
        self.assertEqual(self.booking.phone, '+447911123456')
        self.assertEqual(self.booking.status, 'Under Review')
        self.assertEqual(self.booking.signature, original_signature)
        self.assertEqual(self.booking.terms_accepted_at, original_terms)
        Change, Notice = main.notification_models
        change = Change.query.filter_by(booking_id=self.booking.id).one()
        self.assertNotIn('First name', change.changes)
        self.assertNotIn('Phone', change.changes)
        self.assertIn('Event 1: Theme', change.changes)
        self.assertNotIn('PRIVATE ADMIN NOTE', change.changes_json)
        self.assertEqual(Notice.query.filter_by(kind='booking').count(), 1)
        page = self.fixture.client.get(f'/client/bookings/{self.booking.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'New theme', page.data)
        self.assertNotIn(b'PRIVATE ADMIN NOTE', page.data)
        self.assertEqual(main.booking_lifecycle_models[0].query.filter_by(change_id=change.id).count(), 1)

    def test_under_review_edit_emails_even_when_optional_updates_disabled(self):
        Account = main.ClientAccount
        account = Account.query.filter_by(email=self.booking.email).one()
        main.db.session.add(main.ClientEmailPreference(client_id=account.id, booking_updates=False))
        main.db.session.commit()
        data, headers = self.payload()
        data['rows'][0]['events'][0]['theme'] = 'Updated theme'
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.admin.post(self.path, headers=headers, json=data)
            self.assertEqual(response.status_code, 200)
            send.assert_called_once()
            self.assertIn('log in', send.call_args.args[2])

    def test_auth_status_csrf_stale_and_invalid_inputs(self):
        self.assertEqual(main.app.test_client().get(self.path).status_code, 302)
        data, headers = self.payload()
        self.assertEqual(self.admin.post(self.path, json=data).status_code, 400)
        stale = dict(data, version='wrong')
        self.assertEqual(self.admin.post(self.path, headers=headers, json=stale).status_code, 409)
        data['rows'][0]['events'][0]['finish_time'] = '00:00'
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 400)
        self.booking.status = 'Declined'; main.db.session.commit()
        self.assertEqual(self.admin.get(self.path).status_code, 409)
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 409)

    def test_accepted_booking_edit_requests_acknowledgement_separately_from_payment(self):
        self.booking.status = 'Accepted'
        account = main.ClientAccount.query.filter_by(email=self.booking.email).one()
        main.db.session.add(main.ClientEmailPreference(client_id=account.id, booking_updates=False))
        main.db.session.commit()
        self.assertIn(b'id="adminOutstandingBalance"', self.admin.get(self.path).data)
        data, headers = self.payload()
        data['rows'][0]['events'][0]['theme'] = 'Updated theme'
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.admin.post(self.path, headers=headers, json=data)
            self.assertEqual(response.status_code, 200, response.json)
            send.assert_called_once()
            self.assertIn("I've reviewed these updates", send.call_args.args[2])
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertEqual(main.tool_models[1].query.filter_by(booking_id=self.booking.id).count(), 0)
        change = main.notification_models[0].query.filter_by(booking_id=self.booking.id).one()
        self.assertIn(b'Awaiting client acknowledgement', self.admin.get('/admin/bookings?filter=all').data)
        client = self.fixture.client
        detail = client.get(f'/client/bookings/{self.booking.id}')
        self.assertIn(b'Updated theme', detail.data)
        self.assertEqual(client.post(f'/client/bookings/{self.booking.id}/acknowledge-updates',
            data={'csrf_token': self.fixture.fixture.fixture.csrf(), 'change_id': change.id}).status_code, 302)
        self.assertIsNotNone(change.acknowledged_at)
        self.assertNotIn(b'Awaiting client acknowledgement', self.admin.get('/admin/bookings?filter=all').data)

        data, headers = self.payload()
        data['rows'][0]['events'][0]['event_date'] = '2099-02-01'
        response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 400, response.json)
        self.assertIn('Activity & date changes', response.json['errors'][0])

    def test_internal_notes_only_do_not_notify_client(self):
        data, headers = self.payload()
        data['rows'][0]['internal_notes'] = 'Private'
        response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=self.booking.id).count(), 0)
        self.assertEqual(main.notification_models[1].query.filter_by(kind='booking').count(), 0)

    def test_email_failure_preserves_portal_changes_and_stale_save_is_rejected(self):
        data, headers = self.payload()
        data['rows'][0]['events'][0]['theme'] = 'Saved despite email failure'
        with patch.object(main, 'send_client_email', side_effect=RuntimeError('Synthetic email failure')):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.booking.theme, 'Saved despite email failure')
        self.assertEqual(main.notification_models[0].query.filter_by(booking_id=self.booking.id).count(), 1)
        self.assertFalse(main.notification_models[1].query.filter_by(kind='booking').one().email_sent)
        self.assertEqual(self.admin.post(self.path, headers=headers, json=data).status_code, 409)

    def test_event_edits_preserve_schedule_metadata_and_synchronize_public_event(self):
        saved = json.loads(self.booking.event_schedule or '{}')
        if not isinstance(saved, dict):
            saved = {'events': saved}
        saved['intake_options'] = {'package': dict(name='Preserved package', price='100', hours='2')}
        original_days = main.booking_schedule_events(self.booking)
        original_days[0]['travel_miles'] = '24'
        saved['events'] = original_days
        self.booking.event_schedule = json.dumps(saved)
        event = main.Event(name='Linked public event', booking_id=self.booking.id, booking_day_number=1,
            event_date=self.booking.event_date, event_address=self.booking.event_address, status='Closed', is_current=False)
        main.db.session.add(event); main.db.session.commit()
        data, headers = self.payload()
        data['rows'][0]['events'][0].update(event_date='2028-01-04', event_address='Changed venue')
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(event.event_date.isoformat(), '2028-01-04')
        self.assertEqual(event.event_address, 'Changed venue')
        result = json.loads(self.booking.event_schedule)
        self.assertEqual(result['intake_options']['package']['name'], 'Preserved package')
        self.assertEqual(Decimal(result['events'][0]['travel_miles']), Decimal('24'))

    def pricing_setup(self, intake=None):
        saved = json.loads(self.booking.event_schedule or '{}')
        if not isinstance(saved, dict):
            saved = {'events': saved}
        saved['pricing_rules'] = dict(hourly_rate='50', minimum_hours='2', free_miles='10', mile_rate='1', travel_cap='50')
        if intake:
            saved['intake_options'] = intake
        self.booking.event_schedule = json.dumps(saved)
        main.db.session.commit()

    def test_live_quote_and_save_recalculate_time_and_ignore_posted_totals(self):
        self.pricing_setup()
        data, headers = self.payload()
        day = data['rows'][0]['events'][0]
        start = datetime.strptime(day['start_time'], '%H:%M')
        day.update(finish_time=(start + timedelta(hours=3)).strftime('%H:%M'), charge_type='Client', pitch_fee_required='No', estimated_cost='0')
        data['rows'][0].update(total_event_cost='0', travel_charge='9999')
        quote = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(quote.status_code, 200, quote.json)
        self.assertEqual(quote.json['quote']['event_total'], '150.00')
        self.assertEqual(self.booking.total_event_cost, Decimal('100'))
        self.assertEqual(main.notification_models[0].query.count(), 0)
        with patch.object(main, 'send_client_email', return_value=True):
            saved = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(self.booking.total_event_cost, Decimal('150'))
        self.assertEqual(self.booking.travel_charge, Decimal('0'))
        changes = main.notification_models[0].query.one().changes
        self.assertIn('Estimated event cost', changes)

    def test_charge_type_pitch_cost_and_travel_are_repriced(self):
        self.pricing_setup()
        data, headers = self.payload()
        day = data['rows'][0]['events'][0]
        day.update(charge_type='Customers', travel_miles='40')
        response = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['quote']['event_total'], '0.00')
        self.assertEqual(response.json['quote']['travel'], '30.00')
        day.update(charge_type='Client', pitch_fee_required='Yes', pitch_fee_amount='25')
        response = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(response.json['quote']['event_total'], '0.00')
        self.assertEqual(response.json['quote']['pitch_cost'], '25.00')
        self.assertEqual(response.json['quote']['total'], '30.00')

    def test_multi_day_travel_cap_and_incompatible_package_explanations(self):
        self.pricing_setup({'package': dict(name='Party', hours='2', price='120'), 'extras': [dict(name='Extra', price='10')], 'extras_total': '10'})
        data, headers = self.payload()
        day = data['rows'][0]['events'][0]
        day.update(travel_miles='40', charge_type='Client', pitch_fee_required='No')
        second = dict(day, _original_index=None, event_date='2028-01-05')
        data['rows'][0]['events'].append(second)
        quote = self.admin.post(self.path, headers=headers, json=dict(data, action='quote')).json['quote']
        self.assertEqual(quote['event_total'], '250.00')
        self.assertEqual(quote['travel'], '50.00')
        day['charge_type'] = 'Revenue sharing'
        quote = self.admin.post(self.path, headers=headers, json=dict(data, action='quote')).json['quote']
        self.assertEqual(quote['event_total'], '100.00')
        self.assertTrue(any('package' in note for note in quote['notes']))
        self.assertTrue(any('extras' in note for note in quote['notes']))

    def test_existing_travel_is_retained_when_mileage_is_unknown(self):
        self.booking.travel_charge = Decimal('17')
        self.pricing_setup()
        data, headers = self.payload()
        day = data['rows'][0]['events'][0]
        start = datetime.strptime(day['start_time'], '%H:%M')
        day.update(finish_time=(start + timedelta(hours=3)).strftime('%H:%M'), charge_type='Client', pitch_fee_required='No')
        day.pop('travel_miles', None)
        result = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(result.json['quote']['travel'], '17.00')
        self.assertEqual(result.json['quote']['total'], '167.00')

    def test_unchanged_client_pays_booking_with_stale_zero_is_recalculated(self):
        self.booking.total_event_cost = Decimal('0')
        stored = json.loads(self.booking.event_schedule)
        for event in stored.get('events', []):
            event['estimated_cost'] = '0'
        self.booking.event_schedule = json.dumps(stored)
        main.db.session.commit()
        data, headers = self.payload()
        # No cost-driving field is edited: stale imported totals must still heal.
        result = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['quote']['event_total'], '100.00')
        self.assertEqual(result.json['quote']['days'][0]['cost'], '100.00')
        self.assertEqual(self.booking.total_event_cost, Decimal('0'))
        with patch.object(main, 'send_client_email', return_value=True):
            saved = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(self.booking.total_event_cost, Decimal('100'))

    def test_booking_hourly_rate_override_is_previewed_saved_and_kept_local(self):
        standard_rate = main.get_business_settings()['hourly_rate']
        data, headers = self.payload()
        data['rows'][0]['booking_hourly_rate'] = '35'
        preview = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertEqual(preview.json['quote']['rate'], '35.00')
        self.assertEqual(preview.json['quote']['event_total'], '70.00')
        self.assertEqual(self.booking.total_event_cost, Decimal('100'))
        with patch.object(main, 'send_client_email', return_value=True):
            saved = self.admin.post(self.path, headers=headers, json=data)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(json.loads(self.booking.event_schedule)['pricing_rules']['hourly_rate'], '35.00')
        self.assertEqual(self.booking.total_event_cost, Decimal('70'))
        self.assertEqual(main.get_business_settings()['hourly_rate'], standard_rate)
        changes = main.notification_models[0].query.one().changes
        self.assertEqual(changes['Hourly rate']['after'], '£35.00')
        reopened, _ = self.payload()
        self.assertEqual(reopened['rows'][0]['booking_hourly_rate'], '35.00')

    def test_booking_hourly_rate_rejects_zero_negative_and_nonfinite(self):
        data, headers = self.payload()
        for value in ('0', '-35', 'NaN', 'Infinity'):
            data['rows'][0]['booking_hourly_rate'] = value
            response = self.admin.post(self.path, headers=headers, json=dict(data, action='quote'))
            self.assertEqual(response.status_code, 400, response.json)
