"""Searchable records for every portal email sent through the provider."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import secrets
from flask import abort, has_request_context, render_template, request, session
from sqlalchemy import or_

KINDS = {'booking': 'Bookings & reminders', 'enquiry': 'Enquiries & replies',
         'reward': 'Rewards', 'waiver': 'Waivers', 'campaign': 'Campaigns',
         'security': 'Sign-in & security', 'other': 'Other emails'}


def define_model(db):
    class OutgoingEmail(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        recipient = db.Column(db.String(320), nullable=False, index=True)
        sender = db.Column(db.String(320), nullable=False)
        subject = db.Column(db.Text, nullable=False)
        body_text = db.Column(db.Text, nullable=False)
        body_html = db.Column(db.Text, nullable=False, default='')
        attachments = db.Column(db.Text, nullable=False, default='[]')
        kind = db.Column(db.String(20), nullable=False, index=True)
        trigger = db.Column(db.String(20), nullable=False, index=True)
        endpoint = db.Column(db.String(120), nullable=False, default='')
        status = db.Column(db.String(20), nullable=False, default='pending', index=True)
        provider_id = db.Column(db.String(255), nullable=False, default='')
        failure = db.Column(db.String(100), nullable=False, default='')
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
        completed_at = db.Column(db.DateTime)
    return OutgoingEmail


def category(subject, endpoint):
    subject = subject.lower()
    if any(word in subject for word in ('verification', 'password reset', 'reset your', 'sign-in code')):
        return 'security'
    if 'marketing' in endpoint:
        return 'campaign'
    if 'enquir' in subject:
        return 'enquiry'
    if 'waiver' in subject:
        return 'waiver'
    if any(word in subject for word in ('reward', 'referral', 'loyalty')):
        return 'reward'
    if any(word in subject for word in ('booking', 'event reminder')) or 'booking' in endpoint:
        return 'booking'
    return 'other'


def deliver(app, db, Model, payload, send):
    """Use separate transactions so recording mail never commits caller changes."""
    endpoint = request.endpoint or '' if has_request_context() else ''
    trigger = 'admin' if has_request_context() and session.get('admin_authenticated') and request.path.startswith('/admin') else 'automatic'
    kind = category(payload.get('subject', ''), endpoint)
    redacted = kind == 'security'
    recipients = payload.get('to', [])
    if isinstance(recipients, str):
        recipients = [recipients]
    ids = []
    try:
        with db.engine.begin() as connection:
            for recipient in recipients:
                result = connection.execute(Model.__table__.insert().values(
                    recipient=recipient, sender=payload.get('from', ''), subject=payload.get('subject', ''),
                    body_text='Security email content is hidden to protect verification codes and reset links.' if redacted else payload.get('text', ''),
                    body_html='' if redacted else payload.get('html', ''),
                    attachments=json.dumps([item.get('filename', 'Attachment') for item in payload.get('attachments', [])]),
                    kind=kind, trigger=trigger, endpoint=endpoint, status='pending', created_at=datetime.utcnow()))
                ids.append(result.inserted_primary_key[0])
    except Exception:
        app.logger.exception('Outgoing email history could not be recorded')

    def finish(**values):
        if ids:
            try:
                with db.engine.begin() as connection:
                    connection.execute(Model.__table__.update().where(Model.id.in_(ids)).values(completed_at=datetime.utcnow(), **values))
            except Exception:
                app.logger.exception('Outgoing email sending status could not be recorded')
    try:
        result = send(payload)
    except Exception as exc:
        finish(status='failed', failure=type(exc).__name__)
        raise
    finish(status='accepted', provider_id=str(result.get('id', '')) if isinstance(result, dict) else '')
    return result


def register(app, db, Model, admin_required):
    @app.get('/admin/communications/outgoing-emails')
    @admin_required
    def communications_outgoing():
        term = request.args.get('q', '').strip()
        state = request.args.get('state', 'all')
        kind = request.args.get('kind', 'all')
        trigger = request.args.get('trigger', 'all')
        if len(term) > 200 or state not in ('all', 'accepted', 'failed', 'pending') or kind not in ('all', *KINDS) or trigger not in ('all', 'admin', 'automatic', 'historical'):
            abort(400)
        records = Model.query
        if term:
            match = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            records = records.filter(or_(*[column.ilike(match, escape='\\') for column in
                (Model.recipient, Model.subject, Model.body_text, Model.sender, Model.provider_id)]))
        for field, value in ((Model.status, state), (Model.kind, kind), (Model.trigger, trigger)):
            if value != 'all':
                records = records.filter(field == value)
        start = request.args.get('from', '')
        end = request.args.get('to', '')
        try:
            begin = datetime.strptime(start, '%Y-%m-%d') if start else None
            finish = datetime.strptime(end, '%Y-%m-%d') if end else None
            if begin and finish and begin > finish:
                raise ValueError()
            uk = ZoneInfo('Europe/London')
            if begin:
                records = records.filter(Model.created_at >= begin.replace(tzinfo=uk).astimezone(timezone.utc).replace(tzinfo=None))
            if finish:
                cutoff = (finish + timedelta(days=1)).replace(tzinfo=uk).astimezone(timezone.utc).replace(tzinfo=None)
                records = records.filter(Model.created_at < cutoff)
        except ValueError:
            abort(400, 'Choose a valid date range.')
        pagination = records.order_by(Model.created_at.desc(), Model.id.desc()).paginate(
            page=max(1, request.args.get('page', 1, type=int)), per_page=25, error_out=False)
        filters = dict(q=term, state=state, kind=kind, trigger=trigger, **{'from': start, 'to': end})
        response = app.make_response(render_template('admin_outgoing_emails.html', pagination=pagination,
            kinds=KINDS, filters=filters, client_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)),
            import_progress=session.get('outgoing_history_import', {})))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    from outgoing_email_import import register as register_import
    register_import(app, db, Model, admin_required)
