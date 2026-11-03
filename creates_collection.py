"""One imported home-game schedule shared by collection and the admin calendar."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for

FEED = 'https://game.api.sheffieldsteelers.co.uk/fixtures/list/calendar?type=home'
SOURCE = 'https://www.sheffieldsteelers.co.uk/fixtures/'
UK = ZoneInfo('Europe/London')


def define_model(db):
    class CreatesCollectionSlot(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        uid = db.Column(db.String(255), nullable=False, unique=True)
        title = db.Column(db.String(255), nullable=False)
        starts_at = db.Column(db.DateTime, nullable=False)
        ends_at = db.Column(db.DateTime, nullable=False)
        venue = db.Column(db.Text, nullable=False)
        active = db.Column(db.Boolean, nullable=False, default=True)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return CreatesCollectionSlot


def parse_calendar(data):
    if len(data) > 1000000 or 'BEGIN:VCALENDAR' not in data:
        raise ValueError('The fixture feed is not a valid calendar.')
    # The official feed uses CRCRLF; unfold physical lines without losing continuations.
    data = data.replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
    data = re.sub(r'\n[ \t]', '', data)
    result = []
    def text(value):
        return value.replace('\\n', ' ').replace('\\N', ' ').replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\')
    def moment(key, value):
        if 'VALUE=DATE' in key:
            raise ValueError('A fixture is missing its face-off time.')
        zone = timezone.utc if value.endswith('Z') or 'TZID=UTC' in key or 'TZID=GMT' in key else UK
        if 'TZID=' in key and not any(z in key for z in ('Europe/London', 'UTC', 'GMT')):
            raise ValueError('The calendar uses an unsupported time zone.')
        parsed = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S').replace(tzinfo=zone)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    for event in data.split('BEGIN:VEVENT')[1:]:
        fields = {}
        for line in event.split('END:VEVENT', 1)[0].splitlines():
            if ':' in line:
                key, value = line.split(':', 1); fields[key.split(';')[0]] = (key, value)
        if 'RRULE' in fields:
            raise ValueError('Recurring fixtures need explicit dates before import.')
        try:
            uid = fields['UID'][1]; title = text(fields['SUMMARY'][1])
            start = moment(*fields['DTSTART']); end = moment(*fields['DTEND'])
            venue = text(fields.get('LOCATION', ('', 'Utilita Arena, Sheffield'))[1])
            if not uid or len(uid) > 255 or not title or len(title) > 255 or end <= start or end-start > timedelta(days=1):
                raise ValueError()
            result.append(dict(uid=uid, title=title, starts_at=start, ends_at=end, venue=venue,
                active=fields.get('STATUS', ('',''))[1] != 'CANCELLED'))
        except (KeyError, ValueError):
            raise ValueError('A fixture has incomplete or invalid details. No calendar changes were saved.')
    if not result or len({row['uid'] for row in result}) != len(result):
        raise ValueError('The fixture feed is empty or contains duplicate game identifiers.')
    return result


def register(app, db, Slot, Order, admin_required):
    def sync(data):
        rows = parse_calendar(data)
        for values in rows:
            row = Slot.query.filter_by(uid=values['uid']).first()
            if row is None:
                row = Slot(**values); db.session.add(row)
            else:
                for key, value in values.items(): setattr(row, key, value)
            row.updated_at = datetime.utcnow()
        # Disappearing fixtures stop being offered; order snapshots remain untouched.
        Slot.query.filter(Slot.uid.notin_([row['uid'] for row in rows])).update({'active': False}, synchronize_session=False)
        db.session.commit()
        return len(rows)
    app.extensions['creates_collection_sync'] = sync
    app.jinja_env.globals['collection_local'] = lambda value: value.replace(tzinfo=timezone.utc).astimezone(UK)
    import json
    app.jinja_env.globals['creates_collection_details'] = lambda order: json.loads(order.collection_snapshot) if order.collection_snapshot else {}
    def changed(order):
        if not order.collection_slot_id or not order.collection_snapshot:
            return False
        slot = db.session.get(Slot, order.collection_slot_id)
        return not slot or not slot.active or not slot.enabled or slot.starts_at.isoformat() != json.loads(order.collection_snapshot).get('starts_at')
    app.jinja_env.globals['creates_collection_changed'] = changed
    app.extensions['creates_collection_slots'] = lambda: Slot.query.filter_by(active=True, enabled=True).filter(Slot.starts_at > datetime.utcnow()).order_by(Slot.starts_at).all()
    with app.app_context():
        snapshot = Path(app.root_path)/'assets'/'steelers-home-fixtures.ics'
        if not Slot.query.first() and snapshot.is_file():
            sync(snapshot.read_bytes().decode('utf-8'))

    @app.route('/admin/cl-creates/collection', methods=['GET','POST'])
    @admin_required
    def creates_collection():
        token = session.setdefault('creates_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token','')): abort(400)
            try:
                if request.form.get('action') == 'refresh':
                    with urlopen(Request(FEED, headers={'User-Agent':'CLPaintsCalendar/1.0'}), timeout=15) as response:
                        data = response.read(1000001).decode('utf-8-sig')
                    count = sync(data); flash(f'{count} home fixtures refreshed from the official calendar.', 'success')
                elif request.form.get('action') == 'toggle':
                    slot = db.get_or_404(Slot, request.form.get('slot_id', type=int))
                    slot.enabled = not slot.enabled; db.session.commit()
                else: abort(400)
            except (ValueError, OSError, UnicodeError):
                db.session.rollback(); flash('The official calendar could not be imported. Existing collection dates are unchanged.', 'error')
            return redirect(url_for('creates_collection'))
        return render_template('creates_collection.html', slots=Slot.query.order_by(Slot.starts_at).all(), csrf=token, source=SOURCE,
            orders=Order.query.filter(Order.collection_slot_id.is_not(None)).order_by(Order.id.desc()).all(), error=None)
