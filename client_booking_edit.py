"""Client revisions share public form validation and always return to admin review."""
import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import flash, g
from werkzeug.datastructures import MultiDict
from client_addresses import FIELDS
from client_notifications import booking_snapshot

EDITABLE_FIELDS = (
    'request_type', 'client_type', 'title', 'job_title', 'first_name', 'last_name',
    'date_of_birth', 'is_over_18', 'ethnicity', 'ethnicity_detail', 'religion',
    'client_address', 'phone', 'email', 'event_date', 'single_date', 'additional_event_dates',
    'start_time', 'finish_time', 'event_address', 'publicity_type', 'charge_type',
    'location_type', 'event_type', 'theme', 'expected_attendees', 'celebrates_christmas_easter',
    'additional_info', 'pitch_fee_required', 'payment_preference', 'signature',
    'liability_acknowledged', 'terms_accepted_at', 'terms_version', 'total_event_cost', 'status',
)


def history(booking):
    try:
        return json.loads(booking.event_schedule or '{}').get('client_revisions', [])
    except (ValueError, TypeError, AttributeError):
        return []


def history_time(value):
    """Legacy naive timestamps are UTC; show UK daylight saving and seconds."""
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else value
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return at.astimezone(ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M:%S %Z')
    except (ValueError, TypeError, AttributeError):
        return 'Time not recorded'


def form_values(booking, schedule):
    values = MultiDict({column.name: str(getattr(booking, column.name) or '')
                        for column in booking.__table__.columns
                        if column.name not in ('internal_notes', 'company_signature', 'signature')})
    data = json.loads(booking.event_schedule or '{}')
    events = [dict(day, pitch_fee_required='yes' if day.get('pitch_fee_required') else 'no')
              for day in schedule(booking)]
    values['event_schedule'] = json.dumps(dict(events=events, same_details=data.get('same_details', False)))
    values['single_date'] = 'yes' if booking.single_date else 'no'
    values['is_over_18'] = 'yes' if booking.is_over_18 else ''
    address = data.get('billing_address', {})
    if not address:
        lines = booking.client_address.splitlines()
        if len(lines) == len(FIELDS):
            address = dict(zip((field[0] for field in FIELDS), lines))
    values.update(address)
    intake = data.get('intake_options', {})
    values['booking_package'] = intake.get('package', {}).get('name', '') if isinstance(intake.get('package'), dict) else ''
    values.setlist('booking_extras', [str(extra.get('name', '')) for extra in intake.get('extras', [])])
    return values


def save_revision(app, db, booking, revised, account, Request, Enquiry, schedule, address, settings):
    before = booking_snapshot(booking, schedule)
    old_events = schedule(booking)
    previous = json.loads(booking.event_schedule or '{}')
    updated = json.loads(revised.event_schedule)
    for day in updated['events']:
        old = next((event for event in old_events if event.get('date') == day['date'] and
                    event.get('event_address') == day['event_address']), {})
        for field in ('travel_miles', 'travel_charge'):
            if field in old:
                day[field] = old[field]
    # Only fields accepted and validated by the public booking handler are copied.
    # Preserve staff notes, travel charges, payment records and referral claims.
    for field in EDITABLE_FIELDS:
        setattr(booking, field, getattr(revised, field))
    previous.update({key: updated[key] for key in ('events', 'same_details', 'intake_options', 'booking_legal', 'pricing_rules')})
    previous['billing_address'] = address
    if previous.get('on_behalf'):
        terms = app.jinja_env.get_template('_booking_legal_text.html').render(business_settings=settings)
        previous['on_behalf'].update(pending=False, signed_at=datetime.utcnow().isoformat(),
                                    signed_by=account.email,
                                    signed_via='private_booking_link' if getattr(g, 'private_booking', None) else 'client_portal',
                                    terms_snapshot=terms, terms_hash=hashlib.sha256(terms.encode()).hexdigest())
    booking.event_schedule = json.dumps(previous)
    after = booking_snapshot(booking, schedule)
    changes = {label: {'before': before.get(label), 'after': value}
               for label, value in after.items() if before.get(label) != value}
    history = previous.setdefault('client_revisions', [])
    history.append(dict(at=datetime.now(timezone.utc).isoformat(), by=account.email, changes=changes,
                        via='private_booking_link' if getattr(g, 'private_booking', None) else 'client_portal'))
    booking.event_schedule = json.dumps(previous)
    details = '\n'.join(f'{label}: {change["before"]} → {change["after"]}' for label, change in changes.items())
    details = f'Client edited booking (revision {len(history)}). Review the latest booking, pricing and travel charges before confirming.\n\n{details}'
    item = Request.query.filter_by(pending_key=f'{booking.id}:edit').first()
    if item:
        item.details = details
        enquiry = db.session.get(Enquiry, item.enquiry_id)
        enquiry.message = details
    else:
        enquiry = Enquiry(client_id=account.id, subject=f'Client edited booking · {booking.public_reference}', message=details)
        db.session.add(enquiry)
        db.session.flush()
        item = Request(booking_id=booking.id, enquiry_id=enquiry.id, kind='change',
                       details=details, pending_key=f'{booking.id}:edit')
        db.session.add(item)
    app.extensions['client_booking_updated'](booking, before, schedule)
    db.session.commit()
    # Use the same notification sender as other client booking requests.
    from flask import current_app
    sender = current_app.extensions['client_revision_email']
    try:
        sent = sender(item, account, booking)
    except Exception:
        app.logger.exception('Client revision saved; admin notification email failed')
        sent = False
    flash('Changes saved and sent to CL Paints for review. You can edit again until confirmation.'
          if sent else 'Changes saved for review, but the notification email could not be sent. Please message CL Paints.', 'success' if sent else 'warning')
