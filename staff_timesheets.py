"""Portal staff clocking, event assignments and audited manager corrections."""
import csv
import hashlib
import io
import json
import math
import secrets
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for, make_response
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect

UK = ZoneInfo('Europe/London')


def ensure_schema(db):
    """Upgrade existing clocking tables without replacing staff or time records."""
    inspector = inspect(db.engine)
    changes = {
        'staff_assignment': {'enabled': 'BOOLEAN NOT NULL DEFAULT TRUE'},
        'staff_time_entry': {'event_name': 'VARCHAR(255)', 'event_date': 'DATE',
            'venue': 'TEXT', 'submission_token': 'VARCHAR(64)'},
    }
    with db.engine.begin() as connection:
        for table, columns in changes.items():
            if not inspector.has_table(table):
                continue
            existing = {column['name'] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        if inspector.has_table('staff_time_entry'):
            for field in ('event_name', 'event_date', 'venue'):
                connection.exec_driver_sql(f'UPDATE staff_time_entry SET {field} = '
                    f'(SELECT staff_assignment.{field} FROM staff_assignment '
                    f'WHERE staff_assignment.id = staff_time_entry.assignment_id) WHERE {field} IS NULL')
            connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_time_submission_token '
                'ON staff_time_entry (submission_token)')


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def local(value):
    return value.replace(tzinfo=timezone.utc).astimezone(UK) if value else None


def hours(entry, at=None):
    finish = entry.clock_out or at or now()
    seconds = (finish - entry.clock_in).total_seconds() - entry.break_seconds
    if entry.break_started:
        seconds -= (finish - entry.break_started).total_seconds()
    return max(0, seconds) / 3600


def define_models(db):
    class StaffMember(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        token_digest = db.Column(db.String(64), unique=True, nullable=False)
        active = db.Column(db.Boolean, nullable=False, default=True)

    class StaffAssignment(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        staff_id = db.Column(db.Integer, db.ForeignKey('staff_member.id'), nullable=False)
        event_key = db.Column(db.String(64), nullable=False)
        event_name = db.Column(db.String(255), nullable=False)
        event_date = db.Column(db.Date, nullable=False)
        venue = db.Column(db.Text, nullable=False, default='')
        enabled = db.Column(db.Boolean, nullable=False, default=True)
        __table_args__ = (db.UniqueConstraint('staff_id', 'event_key'),)

    class StaffTimeEntry(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        staff_id = db.Column(db.Integer, db.ForeignKey('staff_member.id'), nullable=False, index=True)
        assignment_id = db.Column(db.Integer, db.ForeignKey('staff_assignment.id'), nullable=False)
        event_name = db.Column(db.String(255), nullable=False)
        event_date = db.Column(db.Date, nullable=False)
        venue = db.Column(db.Text, nullable=False, default='')
        active_staff_id = db.Column(db.Integer, unique=True)
        submission_token = db.Column(db.String(64), unique=True)
        clock_in = db.Column(db.DateTime, nullable=False, index=True)
        clock_out = db.Column(db.DateTime)
        break_started = db.Column(db.DateTime)
        break_seconds = db.Column(db.Integer, nullable=False, default=0)
        in_location = db.Column(db.Text, nullable=False)
        out_location = db.Column(db.Text)
        revision = db.Column(db.Integer, nullable=False, default=1)
        manager_note = db.Column(db.String(1000), nullable=False, default='')

    class StaffTimeAudit(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        entry_id = db.Column(db.Integer, db.ForeignKey('staff_time_entry.id'), nullable=False, index=True)
        action = db.Column(db.String(30), nullable=False)
        actor = db.Column(db.String(200), nullable=False)
        reason = db.Column(db.String(1000), nullable=False, default='')
        before_json = db.Column(db.Text)
        after_json = db.Column(db.Text, nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, default=now)

    return StaffMember, StaffAssignment, StaffTimeEntry, StaffTimeAudit


def register(app, db, models, Event, Booking, schedule, admin_required):
    Staff, Assignment, Entry, Audit = models

    def events():
        choices = {}
        for booking in Booking.query.filter(Booking.status.in_(('Accepted', 'Under Review'))).all():
            for index, day in enumerate(schedule(booking)):
                try:
                    event_date = date.fromisoformat(day.get('date', ''))
                except (ValueError, TypeError):
                    continue
                key = f'b:{booking.id}:{index}'
                choices[key] = dict(key=key, name=f'{booking.public_reference} · Day {index+1} · {day.get("event_type", "Event")}',
                    date=event_date, venue=day.get('event_address') or booking.event_address or '',
                    can_clock=booking.status == 'Accepted', status=booking.status)
        for event in Event.query.filter(Event.status != 'Archived').all():
            if event.booking_id:
                continue  # Linked public events use their booking day, once.
            if event.event_date:
                key = f'e:{event.id}'
                choices[key] = dict(key=key, name=event.name, date=event.event_date, venue=event.event_address or '', can_clock=True, status=event.status)
        return choices

    app.extensions['staff_time_events'] = events

    def csrf():
        return session.setdefault('staff_time_csrf', secrets.token_urlsafe(32))

    def check_csrf():
        if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400)

    def snapshot(entry):
        return json.dumps({key: getattr(entry, key).isoformat() if isinstance(getattr(entry, key), datetime) else getattr(entry, key)
            for key in ('clock_in', 'clock_out', 'break_started', 'break_seconds', 'in_location', 'out_location', 'revision', 'manager_note')})

    def audit(entry, action, actor, before=None, reason=''):
        db.session.add(Audit(entry_id=entry.id, action=action, actor=actor, before_json=before,
            after_json=snapshot(entry), reason=reason))

    def location():
        reason = request.form.get('location_reason', '').strip()
        if request.form.get('latitude') or request.form.get('longitude'):
            try:
                lat = float(request.form['latitude']); lon = float(request.form['longitude'])
                accuracy = float(request.form['accuracy'])
                sampled = float(request.form['location_at'])
                if not all(math.isfinite(v) for v in (lat, lon, accuracy, sampled)) or not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 <= accuracy <= 100000:
                    raise ValueError()
                if abs(now().replace(tzinfo=timezone.utc).timestamp() - sampled/1000) > 120:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise ValueError('Location could not be verified. Request a fresh location or explain why it is unavailable.')
            return json.dumps(dict(latitude=lat, longitude=lon, accuracy=accuracy, captured_at=sampled))
        if not reason or len(reason) > 500:
            raise ValueError('Allow location access, or explain why your location is unavailable (up to 500 characters).')
        return json.dumps(dict(unavailable=reason))

    def staff_user():
        staff = db.session.get(Staff, session.get('clock_staff_id')) if session.get('clock_staff_id') else None
        if not staff or not staff.active or session.get('clock_expires', 0) < now().replace(tzinfo=timezone.utc).timestamp() or not secrets.compare_digest(staff.token_digest, session.get('clock_digest', '')):
            abort(403, 'Open your current personal staff clocking link to sign in.')
        return staff

    def restricted(response):
        response = make_response(response)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/staff/clock/<token>')
    def staff_clock_login(token):
        staff = Staff.query.filter_by(token_digest=digest(token), active=True).first_or_404()
        session['clock_staff_id'] = staff.id
        session['clock_digest'] = staff.token_digest
        session['clock_expires'] = (now() + timedelta(hours=24)).replace(tzinfo=timezone.utc).timestamp()
        session['staff_time_csrf'] = secrets.token_urlsafe(32)
        return restricted(redirect(url_for('staff_clock')))

    @app.post('/staff/clock/logout')
    def staff_clock_logout():
        check_csrf()
        for key in ('clock_staff_id', 'clock_digest', 'clock_expires', 'staff_time_csrf'):
            session.pop(key, None)
        return restricted(('Signed out. Use your personal clocking link to sign in again.', 200))

    @app.route('/staff/clock', methods=['GET', 'POST'])
    def staff_clock():
        staff = staff_user()
        today = local(now()).date()
        available = events()
        active = Entry.query.filter_by(active_staff_id=staff.id).first()
        if request.method == 'POST':
            check_csrf()
            try:
                action = request.form.get('action')
                at = now()
                if action == 'in':
                    if active:
                        raise ValueError('You are already clocked in. Clock out before starting another shift.')
                    assignment = db.session.get(Assignment, request.form.get('assignment_id', type=int))
                    current = available.get(assignment.event_key) if assignment else None
                    if not assignment or not assignment.enabled or assignment.staff_id != staff.id or not current or not current['can_clock'] or current['date'] != today:
                        raise ValueError('Choose one of your assigned events for today.')
                    active = Entry(staff_id=staff.id, assignment_id=assignment.id, active_staff_id=staff.id,
                        event_name=current['name'], event_date=current['date'], venue=current['venue'],
                        clock_in=at, in_location=location(), break_seconds=0, revision=1, manager_note='')
                    db.session.add(active); db.session.flush()
                    audit(active, 'clock_in', staff.name)
                else:
                    if not active or request.form.get('entry_id', type=int) != active.id or request.form.get('revision', type=int) != active.revision:
                        raise ValueError('Your shift changed. Reload before trying again.')
                    before = snapshot(active)
                    changes = dict(revision=active.revision+1)
                    if action == 'break_start' and not active.break_started:
                        changes['break_started'] = at
                    elif action == 'break_end' and active.break_started:
                        changes.update(break_started=None, break_seconds=active.break_seconds+int((at-active.break_started).total_seconds()))
                    elif action == 'out':
                        changes.update(clock_out=at, active_staff_id=None, out_location=location())
                        if active.break_started:
                            changes.update(break_started=None, break_seconds=active.break_seconds+int((at-active.break_started).total_seconds()))
                    else:
                        raise ValueError('That action is not available for your current shift.')
                    changed = Entry.query.filter_by(id=active.id, revision=active.revision, active_staff_id=staff.id).update(changes, synchronize_session=False)
                    if changed != 1:
                        raise ValueError('Your shift changed. Reload before trying again.')
                    db.session.refresh(active)
                    audit(active, action, staff.name, before)
                db.session.commit()
                flash('Clocking record saved.', 'success')
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else 'A shift is already open. Reload to see your current shift.', 'error')
            return restricted(redirect(url_for('staff_clock')))
        assignments = [row for row in Assignment.query.filter_by(staff_id=staff.id, enabled=True).all()
            if row.event_key in available and available[row.event_key]['can_clock'] and available[row.event_key]['date'] == today]
        assignment_map = {row.id: row for row in Assignment.query.filter_by(staff_id=staff.id).all()}
        return restricted(render_template('staff_clock.html', staff=staff, assignments=assignments, available=available,
            assignment_map=assignment_map, active=active, entries=Entry.query.filter_by(staff_id=staff.id).order_by(Entry.clock_in.desc()).limit(50).all(),
            csrf=csrf(), local=local, hours=hours, json_loads=json.loads, today=today))

    def parse_time(value):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UK)
                if parsed.utcoffset() != parsed.replace(fold=1).utcoffset():
                    raise ValueError()
                if parsed.astimezone(timezone.utc).astimezone(UK).replace(tzinfo=None) != parsed.replace(tzinfo=None):
                    raise ValueError()
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError):
            raise ValueError('Enter valid UK dates and times. For a clock-change ambiguity, include an explicit UTC offset, such as +00:00.')

    @app.route('/admin/staff-timesheets', methods=['GET', 'POST'])
    @admin_required
    def admin_staff_timesheets():
        available = events()
        assign_booking = None
        if request.args.get('assign_booking'):
            assign_booking = db.get_or_404(Booking, request.args.get('assign_booking', type=int))
            if assign_booking.status not in ('Under Review', 'Accepted'):
                abort(404)
        assignment_choices = [event for key, event in available.items()
            if not assign_booking or key.startswith(f'b:{assign_booking.id}:')]
        if request.method == 'POST':
            check_csrf()
            try:
                action = request.form.get('action')
                if action == 'staff':
                    name = request.form.get('name', '').strip()
                    if not name or len(name) > 120:
                        raise ValueError('Enter the staff member’s name (up to 120 characters).')
                    token = secrets.token_urlsafe(32)
                    staff = Staff(name=name, token_digest=digest(token))
                    db.session.add(staff); db.session.commit()
                    flash(f'Personal clocking link for {name}: ' + url_for('staff_clock_login', token=token, _external=True), 'staff_link')
                elif action == 'link':
                    staff = db.get_or_404(Staff, request.form.get('staff_id', type=int))
                    token = secrets.token_urlsafe(32); staff.token_digest = digest(token)
                    db.session.commit()
                    flash(f'New personal link for {staff.name} (previous links and sessions are revoked): ' + url_for('staff_clock_login', token=token, _external=True), 'staff_link')
                elif action == 'assignment':
                    staff = db.get_or_404(Staff, request.form.get('staff_id', type=int))
                    event = available.get(request.form.get('event_key'))
                    if not staff.active or not event:
                        raise ValueError('Choose an active staff member and an available event.')
                    if assign_booking and not event['key'].startswith(f'b:{assign_booking.id}:'):
                        raise ValueError('Choose an event day from this booking.')
                    existing = Assignment.query.filter_by(staff_id=staff.id, event_key=event['key']).first()
                    if not existing:
                        db.session.add(Assignment(staff_id=staff.id, event_key=event['key'], event_name=event['name'], event_date=event['date'], venue=event['venue']))
                    else:
                        existing.enabled = True
                    db.session.commit(); flash('Staff member assigned.', 'success')
                elif action == 'unassign':
                    assignment = db.get_or_404(Assignment, request.form.get('assignment_id', type=int))
                    if Entry.query.filter_by(assignment_id=assignment.id, active_staff_id=assignment.staff_id).first():
                        raise ValueError('Close the active shift before removing this assignment.')
                    assignment.enabled = False
                    db.session.commit(); flash('Assignment removed. Existing timesheets are retained.', 'success')
                elif action == 'status':
                    staff = db.get_or_404(Staff, request.form.get('staff_id', type=int))
                    if Entry.query.filter_by(active_staff_id=staff.id).first():
                        raise ValueError('Close this staff member’s active shift before disabling their access.')
                    staff.active = not staff.active
                    staff.token_digest = digest(secrets.token_urlsafe(32))
                    db.session.commit(); flash('Staff access updated. Issue a new link if enabling access.', 'success')
                elif action == 'manual':
                    assignment = db.get_or_404(Assignment, request.form.get('assignment_id', type=int))
                    reason = request.form.get('reason', '').strip()
                    checker = request.form.get('checked_by', '').strip()
                    if not reason or len(reason) > 1000 or not checker or len(checker) > 120:
                        raise ValueError('Enter your name and the reason for adding the missed shift.')
                    clock_in = parse_time(request.form.get('clock_in'))
                    clock_out = parse_time(request.form.get('clock_out'))
                    try:
                        minutes = int(request.form.get('break_minutes', ''))
                    except ValueError:
                        raise ValueError('Enter whole unpaid break minutes.')
                    if clock_out <= clock_in or clock_out > now() or minutes < 0 or minutes*60 > (clock_out-clock_in).total_seconds():
                        raise ValueError('Check shift times and break minutes. A manual shift must be completed, with no future times.')
                    if Entry.query.filter(Entry.staff_id == assignment.staff_id, Entry.clock_in < clock_out,
                            db.or_(Entry.clock_out.is_(None), Entry.clock_out > clock_in)).first():
                        raise ValueError('This staff member already has a shift overlapping these times.')
                    entry = Entry(staff_id=assignment.staff_id, assignment_id=assignment.id,
                        submission_token=digest(f'manual:{assignment.staff_id}:{clock_in.isoformat()}:{clock_out.isoformat()}'),
                        event_name=assignment.event_name, event_date=assignment.event_date, venue=assignment.venue,
                        clock_in=clock_in, clock_out=clock_out, break_seconds=minutes*60, revision=1,
                        in_location=json.dumps(dict(unavailable='Manager added a missed shift; no device location was captured.')),
                        out_location=json.dumps(dict(unavailable='Manager added a missed shift; no device location was captured.')), manager_note=reason)
                    db.session.add(entry); db.session.flush(); audit(entry, 'manager_added', checker, reason=reason)
                    db.session.commit(); flash('Missed shift added with an audit record.', 'success')
                else:
                    raise ValueError('Choose a valid staff action.')
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else 'This record was already saved or changed. Reload the page.', 'error')
            return redirect(url_for('admin_staff_timesheets', assign_booking=assign_booking.id if assign_booking else None))
        today = local(now()).date()
        try:
            start = date.fromisoformat(request.args.get('start', (today-timedelta(days=6)).isoformat()))
            end = date.fromisoformat(request.args.get('end', today.isoformat()))
            if end < start or (end-start).days > 366:
                raise ValueError()
        except ValueError:
            abort(400, 'Choose a valid date range of up to one year.')
        start_utc = datetime.combine(start, datetime.min.time(), UK).astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = datetime.combine(end+timedelta(days=1), datetime.min.time(), UK).astimezone(timezone.utc).replace(tzinfo=None)
        rows = Entry.query.filter(Entry.clock_in < end_utc, db.or_(Entry.clock_out.is_(None), Entry.clock_out >= start_utc))
        selected = request.args.get('event_key', '')
        if assign_booking and not selected and assignment_choices:
            selected = assignment_choices[0]['key']
        if selected:
            rows = rows.join(Assignment, Entry.assignment_id == Assignment.id).filter(Assignment.event_key == selected)
        rows = rows.order_by(Entry.clock_in.desc()).all()
        staff_map = {s.id: s for s in Staff.query.order_by(Staff.name).all()}
        assignments = {a.id: a for a in Assignment.query.all()}
        if request.args.get('export') == 'csv':
            output = io.StringIO(); writer = csv.writer(output)
            writer.writerow(['Staff', 'Event', 'Event date', 'Clock in (UK)', 'Clock out (UK)', 'Unpaid break minutes', 'Net hours (whole shift)', 'Status', 'Revision'])
            def cell(value):
                value = str(value)
                return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value
            for entry in rows:
                assignment = assignments[entry.assignment_id]
                writer.writerow([cell(staff_map[entry.staff_id].name), cell(entry.event_name), entry.event_date,
                    local(entry.clock_in).isoformat(), local(entry.clock_out).isoformat() if entry.clock_out else '',
                    round(entry.break_seconds/60, 2), round(hours(entry), 2), 'Open' if not entry.clock_out else 'Closed', entry.revision])
            response = make_response(output.getvalue()); response.mimetype = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename="staff-timesheets.csv"'
            return restricted(response)
        return restricted(render_template('admin_staff_timesheets.html', staff_map=staff_map, assignments=assignments, entries=rows,
            live=Entry.query.filter(Entry.active_staff_id.is_not(None)).all(), available=sorted(available.values(), key=lambda e: (e['date'], e['name']), reverse=True),
            csrf=csrf(), start=start, end=end, selected=selected, local=local, hours=hours,
            total_hours=sum(hours(entry) for entry in rows if entry.clock_out), today=today,
            assign_booking=assign_booking, assignment_choices=assignment_choices))

    @app.route('/admin/staff-timesheets/<int:entry_id>', methods=['GET', 'POST'])
    @admin_required
    def admin_staff_timesheet_edit(entry_id):
        entry = db.get_or_404(Entry, entry_id)
        if request.method == 'POST':
            check_csrf()
            try:
                if request.form.get('revision', type=int) != entry.revision:
                    raise ValueError('This shift changed. Reload before editing it.')
                reason = request.form.get('reason', '').strip()
                checker = request.form.get('checked_by', '').strip()
                if not reason or len(reason) > 1000 or not checker or len(checker) > 120:
                    raise ValueError('Enter your name and a reason for the correction (up to 1,000 characters).')
                clock_in = parse_time(request.form.get('clock_in'))
                clock_out = parse_time(request.form['clock_out']) if request.form.get('clock_out') else None
                try:
                    minutes = int(request.form.get('break_minutes', ''))
                except ValueError:
                    raise ValueError('Enter whole unpaid break minutes.')
                finish = clock_out or now()
                if clock_in > finish or finish > now() + timedelta(seconds=5) or minutes < 0 or minutes*60 > (finish-clock_in).total_seconds():
                    raise ValueError('Check the shift times and break length. Times cannot be in the future or breaks longer than the shift.')
                before = snapshot(entry)
                changes = dict(clock_in=clock_in, clock_out=clock_out, break_seconds=minutes*60,
                    break_started=None, manager_note=reason, revision=entry.revision+1, active_staff_id=entry.staff_id if clock_out is None else None)
                if Entry.query.filter(Entry.staff_id == entry.staff_id, Entry.id != entry.id,
                        db.or_(Entry.clock_out.is_(None), Entry.clock_out > clock_in),
                        Entry.clock_in < (clock_out or datetime.max)).first():
                    raise ValueError('These times overlap another shift for this staff member.')
                changed = Entry.query.filter_by(id=entry.id, revision=entry.revision).update(changes, synchronize_session=False)
                if changed != 1:
                    raise ValueError('This shift changed. Reload before editing it.')
                db.session.refresh(entry); audit(entry, 'manager_edit', checker, before, reason)
                db.session.commit(); flash('Correction saved. Original clocking records remain in the audit history.', 'success')
                return redirect(url_for('admin_staff_timesheet_edit', entry_id=entry.id))
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else 'This staff member already has another active shift.', 'error')
        return restricted(render_template('admin_staff_timesheet_edit.html', entry=entry, staff=db.session.get(Staff, entry.staff_id),
            assignment=db.session.get(Assignment, entry.assignment_id), audits=Audit.query.filter_by(entry_id=entry.id).order_by(Audit.id.desc()).all(),
            csrf=csrf(), local=local, hours=hours, json_loads=json.loads,
            audit_time=lambda value: local(datetime.fromisoformat(value)).strftime('%d/%m/%Y %H:%M:%S') if value else 'Not recorded'))
