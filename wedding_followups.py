"""Durable four-hour wedding enquiry follow-ups, independent of kiosk visits."""
from datetime import datetime, timedelta
from decimal import Decimal
import secrets
import threading
from string import Formatter
from types import SimpleNamespace
from flask import abort, flash, redirect, render_template, request, session, url_for

DEFAULT_SUBJECT = 'Lovely meeting you at Aston Hall Hotel Wedding Fair'
DEFAULT_BODY = """Hello {name},

It was lovely to meet you at the wedding fair. As requested, here is a little information to look through when you have a moment.

Our standard face painting rate is £{hourly_rate} per hour, with a minimum booking of {minimum_hours} hours (from £{minimum_price}, before any travel charges or extras). Your final price depends on your plans, venue and requirements.

To check dates or request a booking, visit {booking_url}. Enter your date, times and venue and use 'Check dates and times'. You can then send a booking request. Availability is provisional until we confirm your booking.

If you only know the year or are still choosing a venue, just reply to this email and we will be happy to help.

CL Paints
{contact_email}"""
PLACEHOLDERS = ('name', 'first_name', 'hourly_rate', 'minimum_hours', 'minimum_price', 'booking_url', 'contact_email')


def validate_template(subject, body):
    if not subject.strip() or len(subject) > 200 or '\n' in subject or '\r' in subject:
        raise ValueError('Enter a subject of up to 200 characters on one line.')
    if not body.strip() or len(body) > 10000:
        raise ValueError('Enter an email message of up to 10,000 characters.')
    try:
        for text in (subject, body):
            for _, field, spec, conversion in Formatter().parse(text):
                if field is not None and (field not in PLACEHOLDERS or spec or conversion):
                    raise ValueError('Use only the placeholders listed below, inside single braces.')
    except ValueError as error:
        raise ValueError('Check your placeholders and braces. Use only the placeholders listed below.') from error


def define_model(db):
    class WeddingFollowup(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        submission_id = db.Column(db.Integer, db.ForeignKey('native_submission.id'), nullable=False, unique=True)
        due_at = db.Column(db.DateTime, nullable=False, index=True)
        status = db.Column(db.String(20), nullable=False, default='pending')
        attempts = db.Column(db.Integer, nullable=False, default=0)
        attempted_at = db.Column(db.DateTime)
        sent_at = db.Column(db.DateTime)
    return WeddingFollowup


def message(settings, entry, unsubscribe):
    base = settings['public_app_url'].rstrip('/')
    rate = Decimal(settings['hourly_rate'])
    hours = Decimal(settings['minimum_hours'])
    values = dict(name=' '.join(entry.name.split()), first_name=entry.name.split()[0] if entry.name.split() else '',
        hourly_rate=f'{rate:.2f}', minimum_hours=f'{hours:g}', minimum_price=f'{rate * hours:.2f}',
        booking_url=base + '/booking', contact_email=settings['contact_email'])
    subject = settings.get('wedding_followup_subject', DEFAULT_SUBJECT).format_map(values)
    body = settings.get('wedding_followup_body', DEFAULT_BODY).format_map(values)
    body += '\n\nYou received this one-off email because you requested information at Aston Hall Hotel Wedding Fair. '
    body += f'To stop these emails: {unsubscribe}'
    return subject, body


def register(app, db, Job, Submission, Preference, settings, send_email, Setting, admin_required):
    def templates():
        config = dict(wedding_followup_subject=DEFAULT_SUBJECT, wedding_followup_body=DEFAULT_BODY)
        config.update({item.key: item.value for item in Setting.query.filter(Setting.key.in_(config)).all()})
        if config['wedding_followup_subject'] == 'Your wedding plans - pricing and booking with CL Paints':
            config['wedding_followup_subject'] = DEFAULT_SUBJECT
        return config

    @app.route('/admin/communications/wedding-followup', methods=['GET', 'POST'])
    @admin_required
    def wedding_followup_settings():
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        config = templates()
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')): abort(400)
            config = dict(wedding_followup_subject=request.form.get('subject', '').strip(),
                          wedding_followup_body=request.form.get('body', '').strip())
            try:
                validate_template(config['wedding_followup_subject'], config['wedding_followup_body'])
                if request.form.get('action') == 'save':
                    for key, value in config.items():
                        item = db.session.get(Setting, key)
                        if item: item.value = value
                        else: db.session.add(Setting(key=key, value=value))
                    db.session.commit()
                    flash('Wedding follow-up email saved. Queued and future emails will use this wording.', 'success')
                    return redirect(url_for('wedding_followup_settings'))
            except ValueError as problem:
                error = str(problem)
        preview_subject = preview_body = None
        if not error:
            preview_settings = {**settings(), **config}
            preview_subject, preview_body = message(preview_settings, SimpleNamespace(name='Alex Guest'),
                preview_settings['public_app_url'].rstrip('/') + '/marketing/unsubscribe-preview')
        response = app.make_response(render_template('admin_wedding_followup.html', config=config,
            csrf=csrf, error=error, placeholders=PLACEHOLDERS, preview_subject=preview_subject, preview_body=preview_body))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def enqueue(entry):
        existing = Job.query.filter_by(submission_id=entry.id).first()
        if existing: return existing
        job = Job(submission_id=entry.id, due_at=entry.created_at + timedelta(hours=4))
        db.session.add(job)
        return job

    def process(now=None):
        now = now or datetime.utcnow()
        Job.query.filter(Job.status == 'sending', Job.attempted_at < now - timedelta(minutes=10)).update(
            {Job.status: 'review'}, synchronize_session=False)
        db.session.commit()
        identities = [job.id for job in Job.query.filter(Job.status == 'pending', Job.due_at <= now).order_by(Job.due_at).limit(100).all()]
        for identity in identities:
            claimed = Job.query.filter(Job.id == identity, Job.status == 'pending', Job.due_at <= now).update(
                {Job.status: 'sending', Job.attempted_at: now, Job.attempts: Job.attempts + 1}, synchronize_session=False)
            db.session.commit()
            if not claimed: continue
            job = db.session.get(Job, identity, populate_existing=True)
            entry = db.session.get(Submission, job.submission_id)
            # Older deployments may already have queued repeat entries. Only
            # the first job for this form/email is eligible to send.
            first = Job.query.join(Submission, Job.submission_id == Submission.id).filter(
                Submission.form_id == entry.form_id, Submission.email == entry.email).order_by(Job.id).first()
            if first.id != job.id:
                job.status = 'duplicate'; db.session.commit(); continue
            pref = db.session.get(Preference, entry.email)
            if pref and pref.unsubscribed_at:
                job.status = 'cancelled'; db.session.commit(); continue
            if not pref:
                pref = Preference(email=entry.email, token=secrets.token_urlsafe(32))
                db.session.add(pref); db.session.commit()
            config = settings()
            config.update(templates())
            unsubscribe = config['public_app_url'].rstrip('/') + '/marketing/unsubscribe/' + pref.token
            subject, body = message(config, entry, unsubscribe)
            try:
                sent = bool(send_email(entry.email, subject, body))
            except Exception:
                # An interrupted provider request may already have been accepted.
                job.status = 'review'
                db.session.commit()
                app.logger.exception('Wedding follow-up delivery needs review: %s', job.id)
                continue
            if sent:
                job.status = 'sent'; job.sent_at = now; entry.email_sent = True
            else:
                job.status = 'pending' if job.attempts < 3 else 'failed'
                job.due_at = now + timedelta(minutes=15)
            db.session.commit()

    app.extensions['wedding_followups'] = dict(enqueue=enqueue, process=process, model=Job)

    @app.cli.command('send-wedding-followups')
    def send_due():
        """Send due wedding emails; safe to run from a scheduled worker."""
        process()

    def run():
        stop = threading.Event()
        while not stop.wait(30):
            with app.app_context():
                try: process()
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Wedding follow-up queue processing failed')
                finally: db.session.remove()

    # A persistent database keeps queued jobs across restarts; tests use memory.
    if ':memory:' not in app.config['SQLALCHEMY_DATABASE_URI']:
        threading.Thread(target=run, name='wedding-followups', daemon=True).start()
