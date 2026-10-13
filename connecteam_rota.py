"""Admin-only Connecteam schedule viewing and explicit draft shift export."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import html
import json
import os
import secrets
import hashlib
import time
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from flask import abort, flash, redirect, render_template, request, session, url_for, current_app, has_app_context, g
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class RateLimited(ValueError):
    def __init__(self, retry_at):
        self.retry_at=retry_at
        when=datetime.fromtimestamp(retry_at,ZoneInfo('Europe/London')).strftime('%d %b at %H:%M UK time')
        super().__init__('Connecteam is temporarily limiting API requests. Try again after '+when+'.')


def retry_time(headers):
    now=time.time()
    def number(key):
        try:return float(headers.get(key,''))
        except (ValueError,TypeError):return None
    remaining=number('x-ratelimit-day-remaining')
    reset=number('x-ratelimit-day-reset' if remaining==0 else 'x-ratelimit-minute-reset')
    if reset is not None and now<reset<=now+7*86400:return reset
    delay=number('Retry-After')
    if delay is not None and 0<delay<=7*86400:return now+delay
    try:
        value=parsedate_to_datetime(headers.get('Retry-After','')).timestamp()
        if now<value<=now+7*86400:return value
    except (ValueError,TypeError,OverflowError):pass
    return now+60


def cached_setting(key,value=None):
    backend=current_app.extensions.get('connecteam_cache') if has_app_context() else None
    if not backend:return None
    db,Setting=backend
    try:
        row=db.session.get(Setting,key)
        if value is None:return json.loads(row.value) if row else None
        if row is None:row=Setting(key=key,value='');db.session.add(row)
        row.value=json.dumps(value);db.session.commit()
    except (ValueError,SQLAlchemyError):
        db.session.rollback()
    return None


def saved_response(cached,notice):
    if has_app_context():
        notices=getattr(g,'connecteam_notices',[])
        when=datetime.fromtimestamp(cached['at'],ZoneInfo('Europe/London')).strftime('%d %b %H:%M')
        notices.append(notice+' Showing saved data from '+when+' UK time.');g.connecteam_notices=notices
    return json.loads(json.dumps(cached['data']))


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
    account=hashlib.sha256(key.encode()).hexdigest()[:24]
    cache_key='ct_cache_'+hashlib.sha256((key+path).encode()).hexdigest()[:32]
    wait_key='ct_wait_'+account
    cached=cached_setting(cache_key) if payload is None else None
    ttl=21600 if path.startswith('/users/') else 3600 if path=='/scheduler/v1/schedulers' else 900
    if cached and time.time()<cached.get('expires',cached['at']+ttl):return saved_response(cached,'Using cached Connecteam data.')
    waiting=cached_setting(wait_key)
    if waiting and waiting.get('until',0)>time.time():
        error=RateLimited(waiting['until'])
        if cached and time.time()-cached['at']<86400:return saved_response(cached,str(error))
        raise error
    req = Request('https://api.connecteam.com' + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'X-API-KEY': key, 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'CLPaints/1.0'})
    try:
        with urlopen(req, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
            raise ValueError('Connecteam returned an unexpected response.')
        if payload is None:cached_setting(cache_key,dict(at=time.time(),data=data['data']))
        return data['data']
    except HTTPError as error:
        if error.code==429:
            limited=RateLimited(retry_time(error.headers or {}));cached_setting(wait_key,dict(until=limited.retry_at))
            if cached and time.time()-cached['at']<86400:return saved_response(cached,str(limited))
            raise limited from None
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
    app.extensions['connecteam_cache']=(db,Setting)
    @app.route('/admin/connecteam', methods=['GET', 'POST'])
    @admin_required
    def connecteam_rota():
        date_order = request.args.get('order', 'asc')
        if date_order not in ('asc', 'desc'):
            abort(400, 'Choose ascending or descending date order.')
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
                    day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
                    query=urlencode(dict(startTime=int(day_start.timestamp()),endTime=int((day_start+timedelta(days=30)).timestamp()),limit=100))
                    path=f'/scheduler/v1/schedulers/{selected_id}/shifts?{query}'
                    key='ct_cache_'+hashlib.sha256((os.getenv('CONNECTEAM_API_KEY','').strip()+path).encode()).hexdigest()[:32]
                    cached=cached_setting(key)
                    if cached:cached['expires']=0;cached_setting(key,cached)
                    flash('Draft shift created. Assign staff and publish it in Connecteam.', 'success')
                except RateLimited as exc:
                    db.session.delete(link)
                    flash(str(exc)+' No shift was sent; retry after the limit resets.', 'error')
                except ValueError as exc:
                    link.status = 'check_required'; flash(str(exc) + ' Export is blocked to prevent duplicates; review Connecteam.', 'error')
                db.session.commit()
            else:
                abort(400)
            return redirect(url_for('connecteam_rota'))
        if selected_id in active:
            try:
                day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
                query = urlencode(dict(startTime=int(day_start.timestamp()), endTime=int((day_start + timedelta(days=30)).timestamp()), limit=100))
                shifts = api(f'/scheduler/v1/schedulers/{selected_id}/shifts?{query}').get('shifts', [])
                for shift in shifts:
                    shift['display_start'] = datetime.fromtimestamp(shift['startTime'], ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M')
                    shift['display_finish'] = datetime.fromtimestamp(shift['endTime'], ZoneInfo('Europe/London')).strftime('%H:%M')
                enrich_shifts(shifts)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else 'Could not read the shift times.'
        staff_options = {}
        for shift in shifts:
            for user, name in zip(shift.get('assignedUserIds') or [], shift.get('staff_names') or []):
                staff_options[str(user)] = name
        staff_filter = request.args.get('staff', '').strip()
        if staff_filter and staff_filter != 'unassigned' and not staff_filter.isdigit():
            abort(400)
        total_shifts = len(shifts)
        if staff_filter == 'unassigned':
            shifts = [shift for shift in shifts if not shift.get('assignedUserIds')]
        elif staff_filter:
            shifts = [shift for shift in shifts if staff_filter in {str(user) for user in (shift.get('assignedUserIds') or [])}]
        shifts.sort(key=lambda shift: shift.get('startTime', 0), reverse=date_order == 'desc')
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
                               shifts=shifts, rows=rows, error=error, csrf=token, staff_filter=staff_filter, date_order=date_order,
                               staff_options=sorted(staff_options.items(), key=lambda item: item[1].casefold()), total_shifts=total_shifts,
                               cache_notices=list(dict.fromkeys(getattr(g,'connecteam_notices',[]))))
