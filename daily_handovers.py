"""Private daily manager handovers with staffing and retained revisions."""
from datetime import date, datetime
import json
import os
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

TEXT_FIELDS = {'manager_name': 200, 'business_today': 4000, 'am_notes': 6000,
               'pm_notes': 6000, 'incidents': 6000, 'follow_up': 4000,
               'correction_reason': 1000, 'am_manager': 200, 'pm_manager': 200}
STAFF_FIELDS = ('name', 'role', 'start', 'finish', 'attendance', 'notes', 'actual_start', 'actual_finish')
ATTENDANCE = ('Scheduled', 'Present', 'Absent', 'Left early')


def define_model(db):
    class DailyHandover(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        handover_date = db.Column(db.Date, nullable=False, index=True)
        revision = db.Column(db.Integer, nullable=False)
        status = db.Column(db.String(10), nullable=False)
        data_json = db.Column(db.Text, nullable=False)
        recorded_by = db.Column(db.String(255), nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('handover_date', 'revision'),)

        @property
        def details(self):
            return json.loads(self.data_json)
    return DailyHandover


def register(app, db, Handover, Booking, schedule, admin_required, Cashup):
    @app.route('/admin/handovers', methods=['GET', 'POST'])
    @admin_required
    def admin_daily_handovers():
        today = datetime.now(ZoneInfo('Europe/London')).date()
        supplied = request.form.get('handover_date') if request.method == 'POST' else request.args.get('date', today.isoformat())
        try:
            selected = date.fromisoformat(supplied or '')
        except ValueError:
            abort(400, 'Choose a valid handover date.')
        bookings = []
        for booking in Booking.query.filter_by(status='Accepted').all():
            for index, event in enumerate(schedule(booking)):
                if event.get('date') == selected.isoformat() and event.get('publicity_type') == 'Public':
                    cashup = Cashup.query.filter_by(booking_id=booking.id, event_index=index,
                        event_date=selected.isoformat()).order_by(Cashup.revision.desc()).first()
                    bookings.append(dict(booking=booking, event=event, index=index, cashup=cashup))
        cashups_pending = sum(not item['cashup'] or item['cashup'].phase != 'Closed' for item in bookings)
        if request.method == 'GET' and request.args.get('cashup_status') == '1':
            response = app.json.response(dict(pending=cashups_pending, events=[dict(booking_id=item['booking'].id,
                day=item['index'], phase=item['cashup'].phase if item['cashup'] else 'Not started') for item in bookings]))
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        latest = Handover.query.filter_by(handover_date=selected).order_by(Handover.revision.desc()).first()
        values = latest.details if latest else {field: '' for field in TEXT_FIELDS}
        values = dict(values, correction_reason='')
        values.setdefault('incident_status', '')
        values.setdefault('staff', [])
        if request.method == 'GET' and request.args.get('print') == '1':
            if not latest:
                abort(404)
            response = app.make_response(render_template('operational_report.html', kind='handover', saved=latest, values=latest.details))
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')):
                abort(400)
            if request.form.get('version', '') != (str(latest.id) if latest else ''):
                abort(409, 'This handover has changed. Reload before saving to avoid overwriting another manager.')
            action = request.form.get('action')
            if action not in ('draft', 'complete', 'acknowledge'):
                abort(400)
            if action == 'acknowledge':
                if cashups_pending:
                    abort(409, 'Close all event-day cash-ups before acknowledging this handover.')
                if not latest or latest.status != 'Complete':
                    abort(409, 'Complete the handover before acknowledgement.')
                name = request.form.get('acknowledged_by', '').strip()
                if not name or len(name)>200:
                    abort(400, 'Enter the receiving manager name (up to 200 characters).')
                values = dict(latest.details, acknowledged_by=name,
                    acknowledged_at=datetime.now(ZoneInfo('Europe/London')).isoformat(timespec='minutes'))
                row = Handover(handover_date=selected, revision=latest.revision+1, status='Complete',
                    data_json=json.dumps(values), recorded_by=os.getenv('ADMIN_EMAIL') or 'CL Paints admin')
                db.session.add(row)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    abort(409, 'This handover changed. Reload before acknowledgement.')
                return redirect(url_for('admin_daily_handovers', date=selected.isoformat()))
            try:
                values = {field: request.form.get(field, '').strip() for field in TEXT_FIELDS}
                values['incident_status'] = request.form.get('incident_status', '')
                columns = {field: request.form.getlist('staff_' + field) for field in STAFF_FIELDS}
                count = len(columns['name'])
                for field in ('actual_start', 'actual_finish'):
                    if not columns[field]:
                        columns[field] = [''] * count
                if count > 30 or any(len(column) != count for column in columns.values()):
                    raise ValueError('Use up to 30 complete staffing rows.')
                values['staff'] = [{field: columns[field][index].strip() for field in STAFF_FIELDS} for index in range(count)]
                values['staff'] = [row for row in values['staff'] if any(row[field] for field in STAFF_FIELDS if field != 'attendance')]
                for field, limit in TEXT_FIELDS.items():
                    if len(values[field]) > limit:
                        raise ValueError(f'{field.replace("_", " ").capitalize()} is too long (maximum {limit:,} characters).')
                if not values['manager_name']:
                    raise ValueError('Enter the manager name before saving.')
                if values['incident_status'] not in ('', 'none', 'recorded'):
                    raise ValueError('Choose whether any incidents occurred.')
                if values['incident_status'] == 'recorded' and not values['incidents']:
                    raise ValueError('Add incident details and action taken, or select no incidents.')
                if values['incident_status'] == 'none' and values['incidents']:
                    raise ValueError('Incident details are entered. Select incidents recorded or clear those details.')
                for row in values['staff']:
                    if not row['name'] or any(len(row[field]) > (1000 if field == 'notes' else 200) for field in STAFF_FIELDS):
                        raise ValueError('Enter a name for each staffing row and keep staffing notes under 1,000 characters.')
                    if row['attendance'] not in ATTENDANCE:
                        raise ValueError('Choose a valid staffing attendance status.')
                    for field in ('start', 'finish', 'actual_start', 'actual_finish'):
                        if row[field]:
                            try:
                                if datetime.strptime(row[field], '%H:%M').strftime('%H:%M') != row[field]:
                                    raise ValueError()
                            except ValueError:
                                raise ValueError('Use 24-hour HH:MM times for staff shifts.')
                if latest and latest.status == 'Complete' and not values['correction_reason']:
                    raise ValueError('Enter a correction reason when changing a completed handover.')
                if latest and latest.status == 'Complete' and action != 'complete':
                    raise ValueError('Save changes to a completed handover as a completed correction.')
                if action == 'complete':
                    if cashups_pending:
                        raise ValueError('Close the cash-up for every event on this date before completing the handover. You can save a draft meanwhile.')
                    if selected > today:
                        raise ValueError('Future handovers can be saved as drafts; complete them on the day or afterwards.')
                    if any(not values[field] for field in ('business_today', 'am_notes', 'pm_notes', 'incident_status')):
                        raise ValueError('Complete today\'s business, AM and PM notes, and the incident check before completing the sheet. Enter "Nothing to report" where appropriate.')
                values['cashups'] = [dict(booking_id=item['booking'].id, reference=item['booking'].public_reference,
                    event_index=item['index'], event_date=selected.isoformat(), record_id=item['cashup'].id if item['cashup'] else None,
                    phase=item['cashup'].phase if item['cashup'] else 'Not started') for item in bookings]
                row = Handover(handover_date=selected, revision=latest.revision+1 if latest else 1,
                    status='Complete' if action == 'complete' else 'Draft', data_json=json.dumps(values),
                    recorded_by=os.getenv('ADMIN_EMAIL') or 'CL Paints admin')
                db.session.add(row)
                db.session.commit()
                flash('Daily handover saved. This sheet is visible only to admins.', 'success')
                return redirect(url_for('admin_daily_handovers', date=selected.isoformat()))
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)
            except IntegrityError:
                db.session.rollback()
                abort(409, 'Another handover was saved. Reload before saving again.')
        history = Handover.query.filter_by(handover_date=selected).order_by(Handover.revision.desc()).all()
        recent_ids = db.session.query(db.func.max(Handover.id)).group_by(Handover.handover_date)
        recent = Handover.query.filter(Handover.id.in_(recent_ids)).order_by(Handover.handover_date.desc()).limit(30).all()
        response = app.make_response(render_template('admin_daily_handovers.html', selected=selected, today=today,
            latest=latest, values=values, history=history, recent=recent, bookings=bookings,
            attendance_options=ATTENDANCE, client_csrf=token, error=error, cashups_pending=cashups_pending))
        response.headers['Cache-Control'] = 'private, no-store'
        return response, 400 if error else 200
