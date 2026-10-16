"""Public contact messages, kept separate from client portal correspondence."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from contact_captcha import configuration as captcha_configuration, verify as verify_captcha


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def define_models(db):
    class WebsiteEnquiry(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        email = db.Column(db.String(254), nullable=False, index=True)
        subject = db.Column(db.String(160), nullable=False)
        message = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(20), nullable=False, default='new')
        submission_token = db.Column(db.String(64), nullable=False, unique=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now, index=True)
        notification_sent = db.Column(db.Boolean, nullable=False, default=False)

    class WebsiteEnquiryReply(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        enquiry_id = db.Column(db.Integer, db.ForeignKey('website_enquiry.id'), nullable=False, index=True)
        token = db.Column(db.String(64), nullable=False, unique=True)
        body = db.Column(db.Text, nullable=False)
        delivery = db.Column(db.String(20), nullable=False, default='pending')
        created_at = db.Column(db.DateTime, nullable=False, default=now)
    return WebsiteEnquiry, WebsiteEnquiryReply


def register(app, db, models, settings, send_email, admin_required):
    Enquiry, Reply = models
    app.extensions['website_enquiry_model'] = Enquiry
    app.jinja_env.filters['enquiry_time'] = lambda value: value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M')

    @app.context_processor
    def contact_context():
        if request.endpoint not in ('website_contact', 'public_contact_submit'):
            return {}
        site_key, secret_key = captcha_configuration()
        return dict(contact_captcha_site_key=site_key,
                    contact_captcha_unavailable=bool(site_key or secret_key) and not bool(site_key and secret_key),
                    contact_csrf=session.setdefault('public_contact_csrf', secrets.token_urlsafe(32)),
                    contact_sent=session.pop('public_contact_sent', False))

    @app.after_request
    def contact_no_cache(response):
        if request.endpoint in ('website_contact', 'public_contact_submit'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def contact_error(message, values, status=400):
        return render_template('website/page.html', page='contact',
                               seo_title='Contact CL Paints', seo_description='Send CL Paints a message about your event.',
                               contact_error=message, contact_values=values), status

    @app.post('/contact/message')
    def public_contact_submit():
        if request.content_length and request.content_length > 32768:
            return 'This message is too large. Keep your message under 5,001 characters.', 413
        values = {key: request.form.get(key, '').strip() for key in ('name', 'email', 'subject', 'message')}
        token = request.form.get('csrf_token', '')
        if not session.get('public_contact_csrf') or not secrets.compare_digest(session['public_contact_csrf'], token):
            return contact_error('This form has expired. Please try sending your message again.', values)
        if request.form.get('company_website', ''):
            session['public_contact_sent'] = True
            return redirect(url_for('website_contact') + '#message-form')
        if Enquiry.query.filter_by(submission_token=token).first():
            session['public_contact_sent'] = True
            return redirect(url_for('website_contact') + '#message-form')
        try:
            from email_validator import validate_email
            if not values['name'] or len(values['name']) > 120:
                raise ValueError('Enter your name using up to 120 characters.')
            if not values['message'] or len(values['message']) > 5000:
                raise ValueError('Enter a message of up to 5,000 characters.')
            if len(values['email']) > 254 or '\r' in values['email'] or '\n' in values['email']:
                raise ValueError('Enter a valid email address.')
            values['email'] = validate_email(values['email'], check_deliverability=False).normalized
            values['subject'] = values['subject'] or 'Website enquiry'
            if len(values['subject']) > 160 or '\n' in values['subject'] or '\r' in values['subject']:
                raise ValueError('Keep the subject to one line of up to 160 characters.')
        except ValueError as error:
            return contact_error(str(error), values)
        cutoff = now() - timedelta(hours=1)
        if Enquiry.query.filter(db.func.lower(Enquiry.email) == values['email'].lower(), Enquiry.created_at >= cutoff).count() >= 3:
            return contact_error('You have sent several messages recently. Please try again in an hour, or email us directly.', values, 429)
        last = session.get('public_contact_last')
        if last and now().replace(tzinfo=timezone.utc).timestamp() - last < 60:
            return contact_error('Please wait a minute before sending another message.', values, 429)
        if not verify_captcha(request.form.get('g-recaptcha-response', ''), settings()['public_app_url']):
            return contact_error('Please complete the reCAPTCHA check and send your message again. If the check is unavailable, please email us directly.', values)
        try:
            enquiry = Enquiry(**values, submission_token=token)
            db.session.add(enquiry)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return contact_error('Your message could not be saved. Please try again, or email us directly.', values, 503)
        session['public_contact_last'] = now().replace(tzinfo=timezone.utc).timestamp()
        session['public_contact_csrf'] = secrets.token_urlsafe(32)
        session['public_contact_sent'] = True
        management_link = settings()['public_app_url'].rstrip('/') + url_for('communications_public_enquiry', enquiry_id=enquiry.id)
        body = (f'New website enquiry #{enquiry.id}\n\nFrom: {enquiry.name}\nEmail: {enquiry.email}\n'
                f'Subject: {enquiry.subject}\n\n{enquiry.message}\n\nRead and reply: {management_link}')
        try:
            enquiry.notification_sent = bool(send_email(settings()['contact_email'], f'CL Paints: website enquiry #{enquiry.id}', body))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning('Website enquiry notification could not be recorded or delivered')
        app.extensions['send_enquiry_auto_reply']('website', enquiry)
        return redirect(url_for('website_contact') + '#message-form')

    @app.get('/admin/communications/website-enquiries')
    @admin_required
    def communications_public_enquiries():
        state = request.args.get('state', 'all')
        if state not in ('all', 'new', 'replied', 'resolved'):
            abort(400)
        term = request.args.get('q', '').strip()
        if len(term) > 100:
            abort(400)
        query = Enquiry.query
        if state != 'all':
            query = query.filter_by(status=state)
        if term:
            pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.filter(or_(*[column.ilike(pattern, escape='\\') for column in
                                      (Enquiry.name, Enquiry.email, Enquiry.subject, Enquiry.message)]))
        pagination = query.order_by(Enquiry.created_at.desc(), Enquiry.id.desc()).paginate(per_page=25, error_out=False)
        response = app.make_response(render_template('admin_public_enquiries.html', pagination=pagination,
                         query=term, state=state, new_count=Enquiry.query.filter_by(status='new').count()))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/admin/communications/website-enquiries/<int:enquiry_id>', methods=['GET', 'POST'])
    @admin_required
    def communications_public_enquiry(enquiry_id):
        enquiry = db.get_or_404(Enquiry, enquiry_id)
        csrf = session.setdefault('website_reply_csrf', secrets.token_urlsafe(32))
        reply_token = session.setdefault(f'website_reply_{enquiry.id}', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
            if request.form.get('action') == 'status':
                state = request.form.get('status')
                if state not in ('new', 'replied', 'resolved'):
                    abort(400)
                enquiry.status = state
                try:
                    db.session.commit()
                    flash('Enquiry status saved.', 'success')
                except SQLAlchemyError:
                    db.session.rollback()
                    flash('The status could not be saved. Please try again.', 'error')
            elif request.form.get('action') == 'reply':
                body = request.form.get('reply', '').strip()
                token = request.form.get('reply_token', '')
                if not secrets.compare_digest(reply_token, token):
                    abort(400, 'Reload the conversation before sending another reply.')
                if not body or len(body) > 5000:
                    flash('Enter a reply of up to 5,000 characters.', 'error')
                elif Reply.query.filter_by(token=token).first():
                    flash('This reply is already recorded. Check its delivery status below.', 'success')
                else:
                    reply = Reply(enquiry_id=enquiry.id, body=body, token=token)
                    db.session.add(reply)
                    try:
                        db.session.commit()
                    except SQLAlchemyError:
                        db.session.rollback()
                        flash('The reply could not be saved. Reload this conversation and check the history before trying again.', 'error')
                        return redirect(url_for('communications_public_enquiry', enquiry_id=enquiry.id))
                    try:
                        from client_notifications import render_notification
                        subject,plain,_,message=render_notification(settings(),enquiry.name,'website_enquiry',f'Enquiry #{enquiry.id}',body,'')
                        attachments=app.extensions['email_media_attachments']('website_enquiry')
                        sent = bool(send_email(enquiry.email,subject,plain,message,attachments))
                    except Exception:
                        sent = False
                    reply.delivery = 'accepted' if sent else 'failed'
                    if sent:
                        enquiry.status = 'replied'
                    try:
                        db.session.commit()
                    except SQLAlchemyError:
                        db.session.rollback()
                        flash('The email attempt finished, but its delivery status could not be saved. Check the email service before sending it again.', 'error')
                        return redirect(url_for('communications_public_enquiry', enquiry_id=enquiry.id))
                    session[f'website_reply_{enquiry.id}'] = secrets.token_urlsafe(32)
                    flash('Reply accepted by the email service.' if sent else 'The reply could not be sent. It is saved below; check your email configuration before trying again.', 'success' if sent else 'error')
            else:
                abort(400)
            return redirect(url_for('communications_public_enquiry', enquiry_id=enquiry.id))
        replies = Reply.query.filter_by(enquiry_id=enquiry.id).order_by(Reply.created_at, Reply.id).all()
        response = app.make_response(render_template('admin_public_enquiry.html', enquiry=enquiry, replies=replies,
                                                    csrf=csrf, reply_token=reply_token))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
