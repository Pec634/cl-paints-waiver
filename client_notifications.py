"""Persisted customer notifications and editable, safely rendered email layouts."""
import html
import json
import re
from datetime import datetime
from string import Formatter
from flask import abort, current_app, redirect, request, session, url_for
import secrets

EMAIL_DEFAULTS = {
    'notification_booking_subject': 'Your CL Paints booking {reference} has been updated',
    'notification_booking_body': 'Hello {name},\n\nWe have updated your booking {reference}.\n\n{details}\n\nPlease open your booking to review the highlighted changes.',
    'notification_reward_subject': 'A rewards update from CL Paints',
    'notification_reward_body': 'Hello {name},\n\n{details}\n\nOpen your Rewards page to see your codes and points.',
    'notification_heading': 'A little update from CL Paints',
    'notification_footer': 'Bringing colour to life - One face at time',
    'notification_colour': '#f52f83',
    'notification_layout': 'card',
}

def validate_email_settings(values):
    for key, value in values.items():
        if key.endswith('colour'):
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Choose a valid six-digit email colour.')
        elif key.endswith('layout'):
            if value not in ['card', 'simple']:
                raise ValueError('Choose a supported email layout.')
        else:
            if not value or len(value) > (200 if 'subject' in key else 5000):
                raise ValueError('Email subjects allow 200 characters; other text allows 5,000.')
            if 'subject' in key and ('\n' in value or '\r' in value):
                raise ValueError('Email subjects must be a single line.')
            try:
                for _, field, spec, conversion in Formatter().parse(value):
                    if field is not None and (field not in ['name', 'reference', 'details'] or spec or conversion):
                        raise ValueError('Use only {name}, {reference} and {details} placeholders.')
            except ValueError:
                raise ValueError('Use only {name}, {reference} and {details} placeholders, with matching braces.')

def define_notification_models(db):
    class BookingChange(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        changes_json = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        acknowledged_at = db.Column(db.DateTime)
        @property
        def changes(self):
            return json.loads(self.changes_json)

    class ClientNotification(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), nullable=False, index=True)
        kind = db.Column(db.String(20), nullable=False)
        reference = db.Column(db.String(100), nullable=False)
        details = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        email_sent = db.Column(db.Boolean, nullable=False, default=False)
    return BookingChange, ClientNotification

def define_read_model(db):
    class NotificationRead(db.Model):
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), primary_key=True)
        last_notice_id = db.Column(db.Integer, nullable=False, default=0)
    return NotificationRead

def booking_snapshot(booking, schedule):
    result = {'Status': booking.status, 'Travel charge': f'£{booking.travel_charge:.2f}',
        'Estimated event cost': f'£{booking.total_event_cost:.2f}',
        'Estimated total': f'£{booking.total_event_cost + booking.travel_charge:.2f}',
        'Payment preference': booking.payment_preference}
    if current_app.extensions.get('payment_fields'):
        result.update(current_app.extensions['payment_fields'](booking))
    for index, event in enumerate(schedule(booking), 1):
        for field, label in [('date', 'Date'), ('start_time','Start time'), ('finish_time','Finish time'),
                             ('event_address','Address'), ('event_type','Event type'), ('theme','Theme')]:
            result[f'Event {index}: {label}'] = str(event.get(field, ''))
    return result

def render_notification(config, name, kind, reference, details, link):
    variables = dict(name=name, reference=reference, details=details)
    subject = config[f'notification_{kind}_subject'].format(**variables)
    body = config[f'notification_{kind}_body'].format(**variables)
    heading = config['notification_heading'].format(**variables)
    footer = config['notification_footer'].format(**variables)
    colour = config['notification_colour']
    border = f'border-top:5px solid {colour};border-radius:16px;' if config['notification_layout'] == 'card' else ''
    message = (f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:24px;{border}">'
               f'<h1 style="font-size:24px;color:{colour}">{html.escape(heading)}</h1>'
               f'<p style="white-space:pre-line;line-height:1.6">{html.escape(body)}</p>'
               f'<p><a style="color:{colour}" href="{html.escape(link, quote=True)}">View your {"booking" if kind == "booking" else "rewards"}</a></p>'
               f'<p style="color:#667189">{html.escape(footer)}</p></div>')
    return subject, body, footer, message

def register_notifications(app, db, models, Booking, Account, Owner, current_client, settings, send):
    Change, Notice = models
    def notify(email, name, kind, reference, details, link):
        config = settings()
        subject, body, footer, message = render_notification(config, name, kind, reference, details, link)
        notice = Notice(email=email, kind=kind, reference=reference, details=details)
        db.session.add(notice)
        db.session.commit()
        notice.email_sent = send(email, subject, body + '\n\n' + link + '\n\n' + footer, message)
        db.session.commit()
        return notice.email_sent
    def booking_updated(booking, before, schedule):
        after = booking_snapshot(booking, schedule)
        changes = {key: {'before': before.get(key, 'Not set'), 'after': after.get(key, 'Removed')}
                   for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        if not changes:
            return None
        db.session.add(Change(booking_id=booking.id, changes_json=json.dumps(changes)))
        db.session.commit()
        details = '\n'.join(f'{key}: {value["before"]} → {value["after"]}' for key, value in changes.items())
        return notify(booking.email, booking.first_name, 'booking', booking.public_reference, details,
                      url_for('client.booking_detail', booking_id=booking.id, _external=True))
    def reward(email, name, reference, details):
        return notify(email, name, 'reward', reference, details, url_for('client.rewards', _external=True))
    def reward_code(code, details):
        owner = db.session.get(Owner, code)
        account = db.session.get(Account, owner.client_id) if owner else None
        if account:
            return reward(account.email, account.first_name, code, details)
    @app.context_processor
    def updates_context():
        account = current_client() if request.path.startswith('/client/') else None
        if not account:
            return {}
        result = {'client_notifications': Notice.query.filter(db.func.lower(Notice.email) == account.email).order_by(Notice.id.desc()).limit(10).all()}
        Read = app.extensions['notification_read_model']
        marker = db.session.get(Read, account.id)
        last_read = marker.last_notice_id if marker else 0
        result['client_unread_count'] = Notice.query.filter(db.func.lower(Notice.email) == account.email, Notice.id > last_read).count()
        result['client_last_notice_id'] = max((notice.id for notice in result['client_notifications']), default=0)
        if request.endpoint == 'client.booking_detail':
            changes = Change.query.filter_by(booking_id=request.view_args['booking_id'], acknowledged_at=None).order_by(Change.id.desc()).all()
            fields = {key for change in changes for key in change.changes}
            result.update(booking_changes=changes, changed_booking_fields=fields, booking_event_changed=any(key.startswith('Event ') for key in fields))
        return result
    @app.post('/client/notifications/read')
    def mark_notifications_read():
        account = current_client()
        if not account: abort(401)
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)
        requested = request.form.get('notice_id', type=int)
        notice = Notice.query.filter(db.func.lower(Notice.email) == account.email, Notice.id == requested).first()
        if not notice: abort(404)
        Read = app.extensions['notification_read_model']
        marker = db.session.get(Read, account.id)
        if not marker:
            marker = Read(client_id=account.id, last_notice_id=notice.id)
            db.session.add(marker)
        else: marker.last_notice_id = max(marker.last_notice_id, notice.id)
        db.session.commit()
        return redirect(url_for('client.dashboard') + '#recent-updates')
    @app.post('/client/bookings/<int:booking_id>/acknowledge-updates')
    def acknowledge(booking_id):
        account = current_client()
        booking = db.session.get(Booking, booking_id)
        if not account or not booking or booking.email.strip().casefold() != account.email:
            abort(404)
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)
        ids = request.form.getlist('change_id', type=int)
        Change.query.filter(Change.booking_id == booking_id, Change.id.in_(ids), Change.acknowledged_at.is_(None)).update({'acknowledged_at': datetime.utcnow()}, synchronize_session=False)
        db.session.commit()
        return redirect(url_for('client.booking_detail', booking_id=booking_id))
    app.extensions['client_booking_updated'] = booking_updated
    app.extensions['client_reward_notice'] = reward
    app.extensions['client_reward_code_notice'] = reward_code
    return booking_updated, reward
