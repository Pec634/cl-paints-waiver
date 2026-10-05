"""Admin-only Connecteam schedule viewing and explicit draft shift export."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import html
import json
import os
import secrets
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def note_text(value):
    class NoteParser(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts = []; self.suppressed = 0
        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'): self.suppressed += 1
            if tag in ('br', 'p', 'div', 'li'): self.parts.append('\n')
        def handle_endtag(self, tag):
            if tag in ('script', 'style') and self.suppressed: self.suppressed -= 1
            if tag in ('p', 'div', 'li'): self.parts.append('\n')
        def handle_data(self, data):
            if not self.suppressed: self.parts.append(data)
    parser = NoteParser(); parser.feed(value or '')
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def enrich_shifts(shifts):
    ids = sorted({int(user) for shift in shifts for user in (shift.get('assignedUserIds') or [])})
    names = {}
    if ids:
        try:
            for offset in range(0, len(ids), 100):
                query = urlencode({'userIds': ids[offset:offset+100], 'limit': 100, 'userStatus': 'all'}, doseq=True)
                for user in api('/users/v1/users?' + query).get('users', []):
                    names[int(user['userId'])] = (str(user.get('firstName', '')) + ' ' + str(user.get('lastName', ''))).strip()
        except (ValueError, TypeError, KeyError):
            pass  # Shift details remain usable when user-directory permission is unavailable.
    for shift in shifts:
        shift['staff_names'] = [names.get(int(user)) or f'Staff ID {user}' for user in (shift.get('assignedUserIds') or [])]
        location = shift.get('locationData') or {}
        shift['venue'] = (location.get('gps') or {}).get('address', '')
        shift['plain_notes'] = [note_text(note.get('html') or note.get('text', '')) for note in (shift.get('notes') or []) if isinstance(note, dict)]
        shift['display_end_date'] = datetime.fromtimestamp(shift['endTime'], ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M')
        shift['duration'] = round((shift['endTime'] - shift['startTime']) / 3600, 2)


def api(path, payload=None):
    key = os.getenv('CONNECTEAM_API_KEY', '').strip()
    if not key:
        raise ValueError('CONNECTEAM_API_KEY is not configured on this server.')
    req = Request('https://api.connecteam.com' + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'X-API-KEY': key, 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'CLPaints/1.0'})
    try:
        with urlopen(req, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
            raise ValueError('Connecteam returned an unexpected response.')
        return data['data']
    except HTTPError as error:
        raise ValueError(f'Connecteam returned HTTP {error.code}. Check API permissions, quota and schedule access.') from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise ValueError('Could not confirm the Connecteam response. Check the connection and rota before trying again.') from None


def define_model(db):
    class ConnecteamShiftLink(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
        event_index = db.Column(db.Integer, nullable=False)
        scheduler_id = db.Column(db.Integer, nullable=False)
        shift_id = db.Column(db.String(100))
        status = db.Column(db.String(30), nullable=False, default='sending')
        snapshot = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        __table_args__ = (db.UniqueConstraint('booking_id', 'event_index'),)
    return ConnecteamShiftLink


def shift_payload(booking, event, index):
    tz = ZoneInfo('Europe/London')
    start = datetime.fromisoformat(event['date'] + 'T' + event['start_time']).replace(tzinfo=tz)
    finish = datetime.fromisoformat(event['date'] + 'T' + event['finish_time']).replace(tzinfo=tz)
    if finish <= start or (finish.timestamp() - start.timestamp()) > 86400:
        raise ValueError('Check the booking start and finish times before exporting.')
    title = f'CL Paints {booking.public_reference} · {event.get("event_type", "Event")} · Date {index + 1}'
    notes = f'Booking: {booking.public_reference}\nVenue: {event.get("event_address", "")}\nTheme: {event.get("theme", "")}\nAssign staff and publish in Connecteam.'
    return dict(title=title, startTime=int(start.timestamp()), endTime=int(finish.timestamp()),
                timezone='Europe/London', isPublished=False, assignedUserIds=[],
                notes=[{'html': '<p>' + html.escape(notes).replace('\n', '<br>') + '</p>'}])


def register(app, db, Link, Setting, Booking, schedule, admin_required):
    @app.route('/admin/connecteam', methods=['GET', 'POST'])
    @admin_required
    def connecteam_rota():
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        schedules = []; shifts = []; error = None
        selected = db.session.get(Setting, 'connecteam_scheduler_id')
        selected_id = int(selected.value) if selected and selected.value.isdigit() else None
        now = datetime.now(ZoneInfo('Europe/London'))
        try:
            schedules = api('/scheduler/v1/schedulers').get('schedulers', [])
            active = {int(item['schedulerId']) for item in schedules if not item.get('isArchived')}
        except ValueError as exc:
            error = str(exc); active = set()
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')): abort(400)
            if error:
                flash(error, 'error'); return redirect(url_for('connecteam_rota'))
            action = request.form.get('action')
            if action == 'schedule':
                chosen = request.form.get('scheduler_id', type=int)
                if chosen not in active: abort(400)
                if not selected:
                    selected = Setting(key='connecteam_scheduler_id'); db.session.add(selected)
                selected.value = str(chosen); db.session.commit()
                flash('Connecteam schedule selected.', 'success')
            elif action == 'export':
                if selected_id not in active: abort(400, 'Select an active schedule first.')
                booking = db.get_or_404(Booking, request.form.get('booking_id', type=int))
                if booking.status != 'Accepted': abort(400, 'Only accepted bookings can be exported.')
                index = request.form.get('event_index', type=int)
                events = schedule(booking)
                if index is None or index < 0 or index >= len(events): abort(400)
                try:
                    payload = shift_payload(booking, events[index], index)
                except (ValueError, KeyError, TypeError):
                    flash('Check the event date and times before exporting.', 'error')
                    return redirect(url_for('connecteam_rota'))
                link = Link(booking_id=booking.id, event_index=index, scheduler_id=selected_id, snapshot=json.dumps(payload, sort_keys=True))
                db.session.add(link)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash('This booking date already has an export record. Check its status before creating another shift.', 'error')
                    return redirect(url_for('connecteam_rota'))
                try:
                    result = api(f'/scheduler/v1/schedulers/{selected_id}/shifts?notifyUsers=false', [payload])
                    created = result.get('shifts', [])
                    if len(created) != 1 or not created[0].get('id'):
                        raise ValueError('Connecteam did not confirm the new shift. Check the rota manually.')
                    link.shift_id = str(created[0]['id']); link.status = 'exported'
                    flash('Draft shift created. Assign staff and publish it in Connecteam.', 'success')
                except ValueError as exc:
                    link.status = 'check_required'; flash(str(exc) + ' Export is blocked to prevent duplicates; review Connecteam.', 'error')
                db.session.commit()
            else:
                abort(400)
            return redirect(url_for('connecteam_rota'))
        if selected_id in active:
            try:
                query = urlencode(dict(startTime=int(now.timestamp()), endTime=int((now + timedelta(days=30)).timestamp()), limit=100))
                shifts = api(f'/scheduler/v1/schedulers/{selected_id}/shifts?{query}').get('shifts', [])
                for shift in shifts:
                    shift['display_start'] = datetime.fromtimestamp(shift['startTime'], ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M')
                    shift['display_finish'] = datetime.fromtimestamp(shift['endTime'], ZoneInfo('Europe/London')).strftime('%H:%M')
                enrich_shifts(shifts)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else 'Could not read the shift times.'
        rows = []
        links = {(item.booking_id, item.event_index): item for item in Link.query.all()}
        for booking in Booking.query.filter_by(status='Accepted').order_by(Booking.event_date).all():
            for index, event in enumerate(schedule(booking)):
                link = links.get((booking.id, index)); changed = False
                if link:
                    try: changed = json.dumps(shift_payload(booking, event, index), sort_keys=True) != link.snapshot
                    except (ValueError, KeyError, TypeError): changed = True
                rows.append(dict(booking=booking, index=index, event=event, link=link, changed=changed))
        return render_template('admin_connecteam.html', schedules=schedules, selected_id=selected_id,
                               shifts=shifts, rows=rows, error=error, csrf=token)
