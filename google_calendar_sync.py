"""One-way booking export; only events marked as owned by this app are changed."""
from datetime import datetime, timedelta
import base64
import hashlib
import html
import json
import os
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import click
from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

SCOPE = 'https://www.googleapis.com/auth/calendar.events'
STATUSES = {'Under Review': ('Under Review', '5'), 'Awaiting Payment': ('Awaiting Payment', '6'),
            'Accepted': ('Confirmed', '10')}
NAMESPACE_KEY = 'google_calendar_sync_namespace'
TOKEN_KEY = 'google_calendar_oauth_token'


class CalendarError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def oauth_ready():
    return all(os.getenv(key) for key in ('GOOGLE_CALENDAR_ID', 'GOOGLE_CALENDAR_CLIENT_ID',
                                          'GOOGLE_CALENDAR_CLIENT_SECRET', 'SECRET_KEY'))


def token_cipher():
    from cryptography.fernet import Fernet
    key = hashlib.sha256((os.environ['SECRET_KEY'] + ':google-calendar-tokens').encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def connection():
    Setting = current_app.extensions['google_calendar_setting_model']
    row = Setting.query.filter_by(key=TOKEN_KEY).first()
    if not row:
        return None
    try:
        saved = json.loads(token_cipher().decrypt(row.value.encode()))
        if saved['calendar_id'] != os.getenv('GOOGLE_CALENDAR_ID') or not saved['refresh_token']:
            return None
        return saved
    except Exception:
        raise CalendarError('Reconnect Google Calendar. The saved connection could not be read or the server secret changed.') from None


def configured():
    return oauth_ready() and bool(connection())


def token_request(values):
    req = Request('https://oauth2.googleapis.com/token', data=urlencode(values).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('access_token'), str) or not data['access_token']:
            raise ValueError()
        return data
    except (URLError, TimeoutError, ValueError):
        raise CalendarError('Google sign-in could not be completed or renewed. Reconnect Google Calendar and check your Google app settings.') from None


def access_token():
    if not configured():
        raise CalendarError('Connect Google Calendar from the availability calendar first.')
    return token_request(dict(client_id=os.environ['GOOGLE_CALENDAR_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CALENDAR_CLIENT_SECRET'],
        refresh_token=connection()['refresh_token'], grant_type='refresh_token'))['access_token']


def api(token, method, path, payload=None, etag=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    if etag:
        headers['If-Match'] = etag
    req = Request('https://www.googleapis.com/calendar/v3/' + path,
                  data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read(4000001)
        if len(raw) > 4000000:
            raise ValueError()
        result = json.loads(raw) if raw else {}
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as error:
        raise CalendarError(f'Google Calendar returned HTTP {error.code}. Check calendar permissions or retry syncing.', error.code) from None
    except (URLError, TimeoutError, ValueError):
        raise CalendarError('Google Calendar could not be reached. Some changes may have completed; retry to reconcile.') from None


def event_payload(booking, event, index, namespace, base_url):
    try:
        zone = ZoneInfo('Europe/London')
        start = datetime.fromisoformat(event['date'] + 'T' + event['start_time'])
        end = datetime.fromisoformat(event['date'] + 'T' + event['finish_time'])
        if start.tzinfo or end.tzinfo:
            raise ValueError()
        if end <= start:
            end += timedelta(days=1)
        start, end = start.replace(tzinfo=zone), end.replace(tzinfo=zone)
    except (KeyError, TypeError, ValueError):
        raise CalendarError(f'{booking.public_reference}, day {index + 1}: correct the event date and times before syncing.') from None
    status, colour = STATUSES[booking.status]
    # Stable identity survives edits but cannot collide with a later reused database ID.
    identity = f'{namespace}:{booking.id}:{booking.submitted_at.isoformat()}:{index}'
    event_id = hashlib.sha256(identity.encode()).hexdigest()
    reference = html.escape(booking.public_reference)
    link = html.escape(base_url.rstrip('/') + f'/admin/bookings/{booking.id}/activity', quote=True)
    return event_id, dict(
        summary=f'[{status}] {booking.public_reference} - {booking.first_name} {booking.last_name}',
        location=event.get('event_address') or booking.event_address or '',
        description=f'CL Paints booking {reference}, day {index + 1}.<br>Status: {status}.<br>'
                    f'<a href="{link}">Manage booking in CL Paints</a><br>Edit booking details in CL Paints; calendar edits are overwritten by sync.',
        start={'dateTime': start.isoformat(), 'timeZone': 'Europe/London'},
        end={'dateTime': end.isoformat(), 'timeZone': 'Europe/London'},
        colorId=colour, status='confirmed' if booking.status == 'Accepted' else 'tentative',
        transparency='opaque' if booking.status == 'Accepted' else 'transparent', visibility='private',
        extendedProperties={'private': {'clpaints_sync': namespace, 'clpaints_booking': str(booking.id)}})


def register(app, db, Setting, Booking, schedule, settings, admin_required):
    app.extensions['google_calendar_setting_model'] = Setting

    def callback_uri():
        base = settings()['public_app_url'].rstrip('/')
        parsed = urlsplit(base)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')):
            raise CalendarError('Configure an HTTPS Public app URL in Settings before connecting Google Calendar.')
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CalendarError('Check the Public app URL in Settings.')
        return base + url_for('google_calendar_callback')

    def sync(apply=False):
        if not configured():
            raise CalendarError('Connect Google Calendar from the availability calendar first.')
        namespace = db.session.get(Setting, NAMESPACE_KEY)
        if namespace is None:
            db.session.add(Setting(key=NAMESPACE_KEY, value=secrets.token_hex(16)))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
        # Serialise app sync workers so a stale worker cannot overwrite a newer one.
        namespace = Setting.query.filter_by(key=NAMESPACE_KEY).with_for_update().one().value
        try:
            desired = {}
            for booking in Booking.query.filter(Booking.status.in_(STATUSES)).all():
                events = schedule(booking)
                if not events:
                    raise CalendarError(f'{booking.public_reference}: add an event date and times before syncing.')
                for index, event in enumerate(events):
                    event_id, payload = event_payload(booking, event, index, namespace, settings()['public_app_url'])
                    desired[event_id] = payload
            token = access_token()
            endpoint = 'calendars/' + quote(os.environ['GOOGLE_CALENDAR_ID'], safe='') + '/events'
            existing = {}
            page_token = None
            seen = set()
            for _ in range(100):
                params = dict(privateExtendedProperty='clpaints_sync=' + namespace, maxResults=2500)
                if page_token:
                    params['pageToken'] = page_token
                result = api(token, 'GET', endpoint + '?' + urlencode(params))
                if not isinstance(result.get('items'), list):
                    raise CalendarError('Google returned an invalid event list. No calendar changes were made.')
                for event in result['items']:
                    if not isinstance(event, dict) or not event.get('id'):
                        raise CalendarError('Google returned an invalid event identity.')
                    if event.get('extendedProperties', {}).get('private', {}).get('clpaints_sync') != namespace:
                        raise CalendarError('Google returned an event owned by another source; sync stopped.')
                    existing[event['id']] = event
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
                if not isinstance(page_token, str) or page_token in seen:
                    raise CalendarError('Google Calendar pagination repeated; sync stopped.')
                seen.add(page_token)
            else:
                raise CalendarError('Too many Google Calendar event pages; sync stopped.')
            report = dict(create=0, update=0, remove=0, unchanged=0, applied=apply)
            for event_id, payload in desired.items():
                old = existing.get(event_id)
                if old is None:
                    report['create'] += 1
                    if apply:
                        try:
                            api(token, 'POST', endpoint + '?sendUpdates=none', dict(payload, id=event_id))
                        except CalendarError as error:
                            if error.status != 409:
                                raise
                            # A retry after a timeout may find a successfully created event.
                            old = api(token, 'GET', endpoint + '/' + event_id)
                            if old.get('extendedProperties', {}).get('private', {}).get('clpaints_sync') != namespace:
                                raise CalendarError('Event identity belongs to another source; sync stopped.')
                            api(token, 'PATCH', endpoint + '/' + event_id + '?sendUpdates=none', payload, old.get('etag'))
                elif matches(old, payload):
                    report['unchanged'] += 1
                else:
                    report['update'] += 1
                    if apply:
                        api(token, 'PATCH', endpoint + '/' + event_id + '?sendUpdates=none', payload, old.get('etag'))
            for event_id, old in existing.items():
                if event_id in desired:
                    continue
                report['remove'] += 1
                if apply:
                    try:
                        api(token, 'DELETE', endpoint + '/' + quote(event_id, safe='') + '?sendUpdates=none', etag=old.get('etag'))
                    except CalendarError as error:
                        if error.status not in (404, 410):
                            raise
            return report
        finally:
            db.session.rollback()  # Release sync lock; bookings are never edited by this integration.

    app.extensions['google_calendar_sync'] = sync

    @app.post('/admin/calendar/google/connect')
    @admin_required
    def google_calendar_connect():
        if not session.get('google_calendar_csrf') or not secrets.compare_digest(session['google_calendar_csrf'], request.form.get('csrf_token', '')):
            abort(400)
        if not oauth_ready():
            flash('Configure Google login credentials, the calendar ID and a stable server SECRET_KEY first.', 'error')
            return redirect(url_for('admin_google_calendar'))
        try:
            uri = callback_uri()
        except CalendarError as error:
            flash(str(error), 'error')
            return redirect(url_for('admin_google_calendar'))
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        session['google_calendar_oauth'] = dict(state=state, verifier=verifier, created=time.time(), redirect_uri=uri)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(
            client_id=os.environ['GOOGLE_CALENDAR_CLIENT_ID'], redirect_uri=uri, response_type='code', scope=SCOPE,
            access_type='offline', prompt='consent select_account', state=state,
            code_challenge=challenge, code_challenge_method='S256')))

    @app.get('/admin/calendar/google/callback')
    @admin_required
    def google_calendar_callback():
        pending = session.pop('google_calendar_oauth', None)
        if not pending or not secrets.compare_digest(pending['state'], request.args.get('state', '')) or not 0 <= time.time() - pending['created'] <= 600:
            abort(400, 'Google sign-in expired. Start the connection again.')
        if request.args.get('error') or not request.args.get('code'):
            flash('Google Calendar was not connected. You can try again when ready.', 'error')
            return redirect(url_for('admin_google_calendar'))
        try:
            if not oauth_ready():
                raise CalendarError('Google Calendar login is not configured on this server.')
            data = token_request(dict(client_id=os.environ['GOOGLE_CALENDAR_CLIENT_ID'],
                client_secret=os.environ['GOOGLE_CALENDAR_CLIENT_SECRET'], code=request.args['code'],
                code_verifier=pending['verifier'], redirect_uri=pending['redirect_uri'], grant_type='authorization_code'))
            if not isinstance(data.get('refresh_token'), str) or not data['refresh_token'] or SCOPE not in data.get('scope', '').split():
                raise CalendarError('Google did not grant background calendar access. Reconnect and allow calendar access.')
            # Verify write access to the selected calendar without creating any events.
            path = 'calendars/' + quote(os.environ['GOOGLE_CALENDAR_ID'], safe='') + '/events?maxResults=1'
            check = api(data['access_token'], 'GET', path)
            if check.get('accessRole') not in ('owner', 'writer'):
                raise CalendarError('This Google account needs permission to make changes and see all details on the CL Paints calendar.')
            saved = dict(refresh_token=data['refresh_token'], calendar_id=os.environ['GOOGLE_CALENDAR_ID'])
            encrypted = token_cipher().encrypt(json.dumps(saved).encode()).decode()
            db.session.merge(Setting(key=TOKEN_KEY, value=encrypted))
            db.session.commit()
            flash('Google Calendar connected. Preview changes before your first sync.', 'success')
        except CalendarError as error:
            db.session.rollback()
            flash(str(error), 'error')
        return redirect(url_for('admin_google_calendar'))

    @app.post('/admin/calendar/google/disconnect')
    @admin_required
    def google_calendar_disconnect():
        if not session.get('google_calendar_csrf') or not secrets.compare_digest(session['google_calendar_csrf'], request.form.get('csrf_token', '')):
            abort(400)
        Setting.query.filter_by(key=TOKEN_KEY).delete(synchronize_session=False)
        db.session.commit()
        session.pop('google_calendar_oauth', None)
        flash('Calendar sync disconnected. Existing Google events are retained. You can revoke access in your Google account settings.', 'success')
        return redirect(url_for('admin_google_calendar'))

    @app.route('/admin/calendar/google', methods=['GET', 'POST'])
    @admin_required
    def admin_google_calendar():
        csrf = session.setdefault('google_calendar_csrf', secrets.token_urlsafe(32))
        report = None
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
            if request.form.get('action') not in ('preview', 'sync'):
                abort(400)
            try:
                report = sync(apply=request.form['action'] == 'sync')
            except CalendarError as error:
                flash(str(error) + ' Retry syncing to reconcile any changes already sent.', 'error')
        try:
            ready = configured()
        except CalendarError as error:
            ready = False
            flash(str(error), 'error')
        try:
            uri = callback_uri()
        except CalendarError:
            uri = ''
        response = app.make_response(render_template('admin_google_calendar.html', ready=ready, login_ready=oauth_ready(),
            csrf=csrf, report=report, callback_uri=uri, calendar_id=os.getenv('GOOGLE_CALENDAR_ID', '')))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.cli.command('sync-google-calendar')
    @click.option('--apply', is_flag=True, help='Write changes to Google. Without this, preview only.')
    def command(apply):
        """Sync booking statuses and event dates to the configured company calendar."""
        try:
            click.echo(json.dumps(sync(apply=apply), indent=2))
        except CalendarError as error:
            raise click.ClickException(str(error) + ' Retry to reconcile any changes already sent.') from None


def matches(old, new):
    for key, value in new.items():
        if key in ('start', 'end'):
            try:
                if datetime.fromisoformat(old[key]['dateTime'].replace('Z', '+00:00')) != datetime.fromisoformat(value['dateTime']):
                    return False
            except (KeyError, ValueError, TypeError):
                return False
        elif key == 'extendedProperties':
            if any(old.get(key, {}).get('private', {}).get(k) != v for k, v in value['private'].items()):
                return False
        elif old.get(key) != value:
            return False
    return True
