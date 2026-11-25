"""Admin booking edits using the shared event-day editor."""
import hashlib
import json
import os
import secrets
from datetime import date
from decimal import Decimal
from flask import request, session, render_template, jsonify, redirect, url_for
from booking_import import EVENT_FIELDS, convert_row
from client_notifications import booking_snapshot
from booking_pricing import calculate
from booking_rewards import reward_discount

BOOKING_EDIT_FIELDS = (*EVENT_FIELDS, 'payment_preference', 'booking_hourly_rate', 'total_event_cost',
                       'travel_charge', 'internal_notes')


def version(booking):
    values = {column.name: getattr(booking, column.name) for column in booking.__table__.columns}
    return hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()


def register(app, db, Booking, Event, admin_required, schedule, settings):
    @app.route('/admin/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_booking(booking_id):
        from payment_workflow import NO_PAYMENT_REQUIRED, validate_payment_preference

        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        if booking.status not in ('Under Review', 'Awaiting Payment', 'Accepted'):
            return jsonify(error='Only active bookings can be edited here.'), 409
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        form_submit = request.method == 'POST' and not request.is_json

        def page(error=None, code=200):
            row = {field: str(getattr(booking, field, None) or '') for field in BOOKING_EDIT_FIELDS
                   if field not in EVENT_FIELDS}
            try:
                stored = json.loads(booking.event_schedule or '{}')
            except (ValueError, TypeError):
                stored = {}
            if not isinstance(stored, dict):
                stored = {}
            saved_rules = dict(settings(), **stored.get('pricing_rules', {}))
            row['booking_hourly_rate'] = str(saved_rules['hourly_rate'])
            events = []
            for index, original in enumerate(schedule(booking)):
                day = dict(original, event_date=original['date'], _original_index=index)
                for field in EVENT_FIELDS:
                    if field not in day and hasattr(booking, field):
                        value = getattr(booking, field)
                        day[field] = str(value) if value is not None else ''
                if day.get('estimated_cost') in (None, ''):
                    day['estimated_cost'] = str(booking.total_event_cost) if index == 0 else '0.00'
                events.append(day)
            row['events'] = json.dumps(events)
            initial = dict(headers=list(row), rows=[list(row.values())])
            form_data = dict(row, single_date='yes' if booking.single_date else 'no')
            form_data['event_schedule'] = json.dumps(dict(
                events=[dict(day, pitch_fee_required='yes' if str(day.get('pitch_fee_required')).lower()
                             in ('yes', 'true', '1') else 'no') for day in events],
                same_details=stored.get('same_details', False)))
            if form_submit:
                for field in (*BOOKING_EDIT_FIELDS, 'event_schedule', 'single_date'):
                    if field in request.form:
                        form_data[field] = request.form[field]
            saved_payment = app.extensions['payment_summary'](booking)
            no_payment_due = saved_payment['total'] == saved_payment['outstanding'] == 0
            if no_payment_due:
                form_data['payment_preference'] = NO_PAYMENT_REQUIRED
            return render_template('booking_form.html', admin_edit=True, editing_booking=booking,
                form_data=form_data, edit_version=request.form.get('booking_version') if form_submit else version(booking),
                error=error,
                pricing_rate=form_data.get('booking_hourly_rate', row['booking_hourly_rate']),
                business_settings=dict(saved_rules, max_event_dates=max(len(events), int(saved_rules['max_event_dates']))),
                google_maps_api_key=os.getenv('GOOGLE_MAPS_API_KEY', ''),
                intake=stored.get('intake_options', {}), saved_payment=saved_payment, no_payment_due=no_payment_due,
                applied_reward=reward_discount(booking),
                edit_config=dict(initialSource=initial, token=token,
                    version=version(booking))), code

        def failure(message, code=400):
            return page(message, code) if form_submit else (jsonify(error=message), code)

        if request.method == 'GET':
            return page()
        supplied_token = request.form.get('csrf_token', '') if form_submit else request.headers.get('X-Import-Token', '')
        if not secrets.compare_digest(token, supplied_token):
            return failure('Your editing session has expired. Reload the editor.')
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify(error='The edit request is too large.'), 400
        if form_submit:
            try:
                saved_schedule = json.loads(request.form.get('event_schedule', ''))
                events = saved_schedule['events']
                if not isinstance(events, list) or not all(isinstance(day, dict) for day in events):
                    raise ValueError('Provide valid event details.')
                original_count = len(schedule(booking))
                for index, day in enumerate(events):
                    day.pop('_original_index', None)
                    if index < original_count:
                        day['_original_index'] = index
                submitted = request.form.to_dict()
                submitted['events'] = events
                payload = dict(version=request.form.get('booking_version'), rows=[submitted], action=request.form.get('action'))
            except (ValueError, TypeError, KeyError) as exc:
                return failure(str(exc) if isinstance(exc, ValueError) else 'Provide valid event details.')
        else:
            payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('version') != version(booking):
            return failure('This booking changed after you opened it. Open the editor again to use the latest details.', 409)
        rows = payload.get('rows')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return jsonify(error='Provide the edited booking details.'), 400
        submitted = rows[0]
        raw_events = submitted.get('events')
        if not isinstance(raw_events, list) or not raw_events:
            return failure('Keep at least one event day.')
        before = booking_snapshot(booking, schedule)
        original_events = schedule(booking)
        base = {column.name: str(getattr(booking, column.name)) if getattr(booking, column.name) is not None else ''
                for column in Booking.__table__.columns if column.name != 'id'}
        base.update({field: submitted[field] for field in BOOKING_EDIT_FIELDS if field in submitted})
        base['events'] = raw_events
        try:
            try:
                data = json.loads(booking.event_schedule or '{}')
            except (ValueError, TypeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            if 'booking_hourly_rate' in submitted:
                from booking_pricing import money
                rate = money(submitted['booking_hourly_rate'], 'booking hourly rate')
                if rate <= 0:
                    raise ValueError('The booking hourly rate must be greater than zero.')
                data['pricing_rules'] = dict(data.get('pricing_rules', {}), hourly_rate=str(rate))
            preference = submitted.get('payment_preference', '' if form_submit else booking.payment_preference)
            raw_events, intake, rules, quote = calculate(booking, raw_events, original_events, data, settings(),
                preference, app.extensions['payment_summary'](booking)['paid'])
            total = Decimal(quote['total'])
            outstanding = Decimal(quote['outstanding'])
            if total == outstanding == 0:
                preference = NO_PAYMENT_REQUIRED
                quote['deposit'] = None
            if payload.get('action') == 'quote':
                return jsonify(quote=quote)
            if preference != booking.payment_preference or preference == NO_PAYMENT_REQUIRED:
                validate_payment_preference(preference, total, outstanding)
            base['payment_preference'] = preference
            base['events'] = raw_events
            columns = [column for column in Booking.__table__.columns if column.name != 'id']
            values = convert_row(base, columns)
            updated_events = json.loads(values['event_schedule'])['events']
            if booking.status == 'Accepted':
                timing_fields = ('date', 'start_time', 'finish_time')
                original_times = [tuple(event[field] for field in timing_fields) for event in original_events]
                updated_times = [tuple(event[field] for field in timing_fields) for event in updated_events]
                if updated_times != original_times:
                    raise ValueError('Use Activity & date changes to propose new dates or times for an accepted booking.')
            keys = [(event['date'], event['start_time']) for event in updated_events]
            if len(set(keys)) != len(keys):
                raise ValueError('The schedule contains duplicate event dates and start times.')
            for other in Booking.query.filter(Booking.id != booking.id, db.func.lower(Booking.email) == values['email'].lower()).all():
                if any((event['date'], event['start_time']) in keys for event in schedule(other)):
                    raise ValueError('Another booking for this client already has this event date and start time.')
            used = set()
            for raw, updated in zip(raw_events, updated_events):
                updated['travel_miles'] = raw['travel_miles']
                updated['travel_charge'] = raw['travel_charge']
                index = raw.get('_original_index')
                if index is not None:
                    if type(index) is not int or index < 0 or index >= len(original_events) or index in used:
                        raise ValueError('Invalid event-day reference. Reload this booking.')
                    used.add(index)
                    preserved = dict(original_events[index])
                    preserved.pop('reward_discount', None)
                    preserved.update(updated)
                    updated.clear()
                    updated.update(preserved)
                if raw.get('reward_discount'):
                    updated['reward_discount'] = raw['reward_discount']
            # Public event records may have waivers and rewards attached; keep
            # their day identity and synchronize dates/venues on edit.
            for linked in Event.query.filter_by(booking_id=booking.id).all():
                matching = next((i for i, raw in enumerate(raw_events) if raw.get('_original_index') == (linked.booking_day_number or 1) - 1), None)
                if matching is None:
                    raise ValueError('A public event is linked to a day you removed. Keep that day and manage its event record separately.')
                linked.booking_day_number = matching + 1
                linked.event_date = date.fromisoformat(updated_events[matching]['date'])
                linked.event_address = updated_events[matching]['event_address']
            data.update(events=updated_events, same_details=bool(saved_schedule.get('same_details')) if form_submit else False,
                        intake_options=intake, pricing_rules=rules)
            values['event_schedule'] = json.dumps(data)
            values['total_event_cost'] = Decimal(quote['event_total'])
            values['travel_charge'] = Decimal(quote['travel'])
            for field in (*BOOKING_EDIT_FIELDS, 'single_date', 'additional_event_dates', 'event_schedule'):
                if field in values and hasattr(booking, field):
                    setattr(booking, field, values[field])
            # The existing notification pipeline commits the booking and its
            # client-visible change record together before sending its email.
            sent = app.extensions['client_booking_updated'](booking, before, schedule, request_acknowledgement=True)
            db.session.commit()
        except (ValueError, ArithmeticError) as exc:
            db.session.rollback()
            if form_submit:
                return failure(str(exc))
            return jsonify(error='Changes were not saved.', errors=[str(exc)]), 400
        target = url_for('admin_bookings', updated=booking.id,
            status_email='sent' if sent else 'failed' if sent is False else None)
        return redirect(target) if form_submit else jsonify(redirect=target)
