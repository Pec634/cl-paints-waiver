"""Client planning tools, calendar exports and optional email preferences."""
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, Response, session, url_for
from sqlalchemy import func


def define_model(db):
    class ClientEmailPreference(db.Model):
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), primary_key=True)
        booking_updates = db.Column(db.Boolean, nullable=False, default=True)
        reward_updates = db.Column(db.Boolean, nullable=False, default=True)
    return ClientEmailPreference


def calendar_text(booking, event, index):
    def escape(value):
        return str(value).replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')
    zone = ZoneInfo('Europe/London')
    start = datetime.strptime(f"{event['date']} {event['start_time']}", '%Y-%m-%d %H:%M').replace(tzinfo=zone)
    end = datetime.strptime(f"{event['date']} {event['finish_time']}", '%Y-%m-%d %H:%M').replace(tzinfo=zone)
    if end <= start:
        end += timedelta(days=1)
    utc = ZoneInfo('UTC')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CL Paints//Client Portal//EN', 'CALSCALE:GREGORIAN',
             'BEGIN:VEVENT', f'UID:booking-{booking.id}-{index}@clpaints.portal',
             'DTSTAMP:' + datetime.now(utc).strftime('%Y%m%dT%H%M%SZ'),
             'DTSTART:' + start.astimezone(utc).strftime('%Y%m%dT%H%M%SZ'),
             'DTEND:' + end.astimezone(utc).strftime('%Y%m%dT%H%M%SZ'),
             'SUMMARY:' + escape('CL Paints: ' + event.get('event_type', 'Event')),
             'LOCATION:' + escape(event.get('event_address', '')),
             'DESCRIPTION:' + escape(f'Booking {booking.public_reference}. Check your portal for the latest arrangements.'),
             'STATUS:CONFIRMED', 'END:VEVENT', 'END:VCALENDAR']
    # RFC 5545 lines are folded at 75 UTF-8 octets, without splitting characters.
    folded = []
    for line in lines:
        part = ''
        for char in line:
            if len((part + char).encode('utf-8')) > 75:
                folded.append(part)
                part = ' '
            part += char
        folded.append(part)
    return '\r\n'.join(folded) + '\r\n'


def register(app, db, Preference, Booking, Invoice, BookingRequest, current_client, schedule):
    @app.context_processor
    def feature_page_context():
        if request.endpoint not in ('client_preferences', 'client_help'):
            return {}
        return dict(client_account=current_client(),
                    client_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)))

    def required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            account = current_client()
            if not account:
                return redirect(url_for('client.login'))
            return view(account, *args, **kwargs)
        return wrapped

    def owned(account):
        return Booking.query.filter(func.lower(Booking.email) == account.email)

    def checklist(account, booking):
        payment = app.extensions['payment_summary'](booking)
        events = schedule(booking)
        return [dict(label='Contact details', done=bool(account.phone and account.address),
                     detail='Keep your phone and address up to date.', link=url_for('client.account')),
                dict(label='Booking confirmed', done=booking.status == 'Accepted',
                     detail='Current status: ' + booking.status, link=url_for('client.booking_detail', booking_id=booking.id)),
                dict(label='Event details supplied', done=bool(events) and all(e.get('date') and e.get('start_time') and e.get('finish_time') and e.get('event_address') for e in events),
                     detail='Review the date, times and venue.', link=url_for('client.booking_detail', booking_id=booking.id)),
                dict(label='Deposit recorded' if payment['deposit'] else 'Deposit arrangements',
                     done=payment['paid'] >= payment['deposit'] if payment['deposit'] else None,
                     detail=(f"Requested: £{payment['deposit']:.2f}. Recorded payments: £{payment['paid']:.2f}." if payment['deposit'] else 'No deposit request is recorded yet.'),
                     link=url_for('client.booking_detail', booking_id=booking.id))]

    @app.context_processor
    def planning_context():
        if request.endpoint not in ('client.dashboard', 'client.booking_detail'):
            return {}
        account = current_client()
        if not account:
            return {}
        if request.endpoint == 'client.booking_detail':
            booking = owned(account).filter_by(id=request.view_args['booking_id']).first()
            return dict(booking_checklist=checklist(account, booking)) if booking else {}
        bookings = owned(account).order_by(Booking.submitted_at.desc()).all()
        active = [b for b in bookings if b.status in ('Accepted', 'Under Review')]
        upcoming = []
        today = datetime.now(ZoneInfo('Europe/London')).date()
        for booking in active:
            if booking.status != 'Accepted':
                continue
            for index, event in enumerate(schedule(booking)):
                try:
                    date = datetime.strptime(event.get('date', ''), '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    continue
                if date >= today:
                    upcoming.append(dict(booking=booking, event=event, index=index, date=date))
        upcoming.sort(key=lambda item: (item['date'], item['event'].get('start_time', '')))
        next_event = upcoming[0] if upcoming else None
        focus = next_event['booking'] if next_event else (active[0] if active else None)
        rows = [dict(booking=b, payment=app.extensions['payment_summary'](b),
                     invoices=Invoice.query.filter_by(booking_id=b.id).order_by(Invoice.created_at.desc()).all()) for b in active]
        ids = [b.id for b in bookings]
        changes = BookingRequest.query.filter(BookingRequest.booking_id.in_(ids)).order_by(BookingRequest.created_at.desc()).limit(5).all() if ids else []
        return dict(portal_next_event=next_event, checklist_booking=focus,
                    booking_checklist=checklist(account, focus) if focus else [], portal_payments=rows,
                    portal_outstanding=sum((r['payment']['outstanding'] for r in rows), Decimal(0)),
                    portal_change_requests=changes, portal_booking_lookup={b.id: b for b in bookings})

    @app.get('/client/bookings/<int:booking_id>/calendar/<int:event_index>')
    @required
    def client_event_calendar(account, booking_id, event_index):
        booking = owned(account).filter_by(id=booking_id).first_or_404()
        if booking.status != 'Accepted':
            abort(404)
        events = schedule(booking)
        if event_index >= len(events):
            abort(404)
        try:
            content = calendar_text(booking, events[event_index], event_index)
        except (KeyError, ValueError, TypeError):
            abort(400, 'This event needs a valid date and start and finish times before it can be added to a calendar.')
        return Response(content, mimetype='text/calendar', headers={
            'Content-Disposition': f'attachment; filename="cl-paints-{booking.id}-{event_index}.ics"',
            'Cache-Control': 'private, no-store'})

    @app.route('/client/preferences', methods=['GET', 'POST'])
    @required
    def client_preferences(account):
        preference = db.session.get(Preference, account.id)
        if request.method == 'POST':
            if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
                abort(400)
            if preference is None:
                preference = Preference(client_id=account.id)
                db.session.add(preference)
            preference.booking_updates = request.form.get('booking_updates') == 'yes'
            preference.reward_updates = request.form.get('reward_updates') == 'yes'
            db.session.commit()
            flash('Your email preferences are saved.', 'success')
            return redirect(url_for('client_preferences'))
        return render_template('client/preferences.html', preference=preference)

    @app.get('/client/help')
    @required
    def client_help(account):
        return render_template('client/help.html')
