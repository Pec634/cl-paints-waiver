"""Admin edits to review-stage bookings using the shared event-day editor."""
import hashlib
import json
import secrets
from datetime import date
from decimal import Decimal
from flask import request, session, render_template, jsonify, url_for
from booking_import import FORM_FIELDS, EVENT_FIELDS, convert_row
from client_notifications import booking_snapshot
from booking_pricing import calculate

EDIT_FIELDS = tuple(field for field in FORM_FIELDS if field not in ('signature', 'promo_code')) + ('total_event_cost', 'travel_charge', 'internal_notes')


def version(booking):
    values = {column.name: getattr(booking, column.name) for column in booking.__table__.columns}
    return hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()


def register(app, db, Booking, Event, admin_required, schedule, settings):
    @app.route('/admin/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_booking(booking_id):
        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        if booking.status != 'Under Review':
            return jsonify(error='Only bookings Under Review can be edited here.'), 409
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'GET':
            row = {field: str(getattr(booking, field, '')) if getattr(booking, field, None) is not None else '' for field in EDIT_FIELDS if field not in EVENT_FIELDS}
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
            return render_template('admin_booking_import.html', fields=list(EDIT_FIELDS), event_fields=list(EVENT_FIELDS),
                token=token, editing=booking, initial_source=initial, edit_version=version(booking),
                pricing_enabled=True, edit_event_fields=list(EVENT_FIELDS) + ['travel_miles'])
        if not secrets.compare_digest(token, request.headers.get('X-Import-Token', '')):
            return jsonify(error='Your editing session has expired. Reload the editor.'), 400
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify(error='The edit request is too large.'), 400
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('version') != version(booking):
            return jsonify(error='This booking changed after you opened it. Reload the editor to use the latest details.'), 409
        rows = payload.get('rows')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return jsonify(error='Provide the edited booking details.'), 400
        submitted = rows[0]
        raw_events = submitted.get('events')
        if not isinstance(raw_events, list) or not raw_events:
            return jsonify(error='Keep at least one event day.'), 400
        before = booking_snapshot(booking, schedule)
        original_events = schedule(booking)
        base = {column.name: str(getattr(booking, column.name)) if getattr(booking, column.name) is not None else ''
                for column in Booking.__table__.columns if column.name != 'id'}
        base.update({field: submitted[field] for field in EDIT_FIELDS if field in submitted})
        base['events'] = raw_events
        try:
            data = json.loads(booking.event_schedule or '{}')
            if not isinstance(data, dict):
                data = {}
            raw_events, intake, rules, quote = calculate(booking, raw_events, original_events, data, settings(),
                submitted.get('payment_preference', booking.payment_preference), app.extensions['payment_summary'](booking)['paid'])
            if payload.get('action') == 'quote':
                return jsonify(quote=quote)
            base['events'] = raw_events
            columns = [column for column in Booking.__table__.columns if column.name != 'id']
            values = convert_row(base, columns)
            updated_events = json.loads(values['event_schedule'])['events']
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
                    preserved.update(updated)
                    updated.clear()
                    updated.update(preserved)
            # Public event records may have waivers and rewards attached; keep
            # their day identity and synchronize dates/venues on edit.
            for linked in Event.query.filter_by(booking_id=booking.id).all():
                matching = next((i for i, raw in enumerate(raw_events) if raw.get('_original_index') == (linked.booking_day_number or 1) - 1), None)
                if matching is None:
                    raise ValueError('A public event is linked to a day you removed. Keep that day and manage its event record separately.')
                linked.booking_day_number = matching + 1
                linked.event_date = date.fromisoformat(updated_events[matching]['date'])
                linked.event_address = updated_events[matching]['event_address']
            data.update(events=updated_events, same_details=False, intake_options=intake, pricing_rules=rules)
            values['event_schedule'] = json.dumps(data)
            values['total_event_cost'] = Decimal(quote['event_total'])
            values['travel_charge'] = Decimal(quote['travel'])
            for field in set(EDIT_FIELDS) | set(EVENT_FIELDS) | {'single_date', 'additional_event_dates', 'event_schedule'}:
                if field in values and hasattr(booking, field):
                    setattr(booking, field, values[field])
            # The existing notification pipeline commits the booking and its
            # client-visible change record together before sending its email.
            sent = app.extensions['client_booking_updated'](booking, before, schedule)
            db.session.commit()
        except (ValueError, ArithmeticError) as exc:
            db.session.rollback()
            return jsonify(error='Changes were not saved.', errors=[str(exc)]), 400
        return jsonify(redirect=url_for('admin_bookings', updated=booking.id,
            status_email='sent' if sent else 'failed' if sent is False else None))
