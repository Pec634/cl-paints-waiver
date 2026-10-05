"""Consent-based campaigns, separate from essential customer notifications."""
from datetime import datetime
import secrets
import json
import re
from io import BytesIO
from urllib.parse import urlparse
import cloudinary.uploader
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def define_models(db):
    class MarketingPreference(db.Model):
        email = db.Column(db.String(255), primary_key=True)
        token = db.Column(db.String(64), unique=True, nullable=False)
        unsubscribed_at = db.Column(db.DateTime)
    class MarketingCampaign(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        subject = db.Column(db.String(200), nullable=False)
        body = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        started_at = db.Column(db.DateTime)
    class MarketingDelivery(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id'), nullable=False)
        email = db.Column(db.String(255), nullable=False)
        status = db.Column(db.String(30), nullable=False, default='pending')
        attempted_at = db.Column(db.DateTime)
        __table_args__ = (db.UniqueConstraint('campaign_id', 'email'),)
    return MarketingPreference, MarketingCampaign, MarketingDelivery


def define_design_models(db):
    class MarketingDesign(db.Model):
        campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id'), primary_key=True)
        config_json = db.Column(db.Text, nullable=False, default='{}')
    class MarketingImage(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id'), nullable=False, index=True)
        image_url = db.Column(db.Text, nullable=False)
        alt = db.Column(db.String(200), nullable=False, default='CL Paints')
    return MarketingDesign, MarketingImage


def register(app, db, models, Waiver, admin_required, send_email):
    Preference, Campaign, Delivery = models
    Design, Image = app.extensions['marketing_design_models']
    defaults = dict(heading='CL Paints', preheader='', colour='#f52f83', layout='card',
                    button_label='', button_url='', image_position='above', footer='Bringing colour to life - One face at time')

    def design(campaign):
        item = db.session.get(Design, campaign.id)
        return {**defaults, **(json.loads(item.config_json) if item else {})}

    def campaign_values():
        config = {key: request.form.get(key, value).strip() for key, value in defaults.items()}
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()
        parsed = urlparse(config['button_url'])
        invalid = (not subject or len(subject) > 200 or '\n' in subject or '\r' in subject
                   or not body or len(body) > 10000 or any(len(v) > 500 for v in config.values())
                   or not re.fullmatch(r'#[0-9a-fA-F]{6}', config['colour'])
                   or config['layout'] not in ('card', 'simple') or config['image_position'] not in ('above', 'below')
                   or (config['button_url'] and (parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password))
                   or bool(config['button_url']) != bool(config['button_label']))
        return subject, body, config, invalid

    def upload_image(campaign):
        upload = request.files.get('image')
        alt = request.form.get('alt', '').strip()
        if not upload or not upload.filename or len(alt) > 200: abort(400)
        if Image.query.filter_by(campaign_id=campaign.id).count() >= 4:
            flash('Each campaign supports up to four images. Remove an image before adding another.', 'error')
        else:
            data = upload.stream.read(2_000_001)
            if len(data) > 2_000_000:
                flash('Choose an image smaller than 2 MB.', 'error')
            else:
                try:
                    result = cloudinary.uploader.upload(BytesIO(data), folder='cl-paints/marketing',
                        resource_type='image', allowed_formats=['jpg', 'png', 'webp'])
                    if urlparse(result['secure_url']).scheme != 'https': raise ValueError('Invalid image URL')
                    db.session.add(Image(campaign_id=campaign.id, image_url=result['secure_url'], alt=alt or 'CL Paints'))
                    db.session.commit(); flash('Image added to the email.', 'success')
                except Exception:
                    db.session.rollback()
                    flash('Image upload failed. Use JPG, PNG or WebP and check your Cloudinary configuration.', 'error')

    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))

    def check():
        if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400)

    def recipients():
        # Most recent waiver determines consent; withdrawal overrides older opt-ins.
        latest = {}
        for waiver in Waiver.query.order_by(Waiver.signed_date.desc(), Waiver.id.desc()).all():
            latest.setdefault(waiver.responsible_email.strip().casefold(), waiver)
        excluded = {p.email for p in Preference.query.filter(Preference.unsubscribed_at.isnot(None)).all()}
        return sorted(email for email, waiver in latest.items()
                      if waiver.marketing_consent and email not in excluded and '@' in email)

    def preference(email):
        item = db.session.get(Preference, email)
        if item is None:
            item = Preference(email=email, token=secrets.token_urlsafe(32))
            db.session.add(item)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                item = db.session.get(Preference, email)
        return item

    def message(campaign, link):
        config = design(campaign)
        images = Image.query.filter_by(campaign_id=campaign.id).order_by(Image.id).all()
        text = campaign.body
        if config['button_url']:
            text += '\n\n' + config['button_label'] + ': ' + config['button_url']
        text += '\n\n' + config['footer'] + '\n\nUnsubscribe: ' + link
        content = render_template('marketing_email.html', campaign=campaign, design=config, images=images, unsubscribe=link)
        return text, content

    @app.route('/admin/marketing', methods=['GET', 'POST'])
    @admin_required
    def marketing_dashboard():
        if request.method == 'POST':
            check()
            subject, body, config, invalid = campaign_values()
            if invalid:
                flash('Enter a single-line subject (up to 200 characters) and message (up to 10,000).', 'error')
            else:
                item = Campaign(subject=subject, body=body)
                db.session.add(item); db.session.flush()
                db.session.add(Design(campaign_id=item.id, config_json=json.dumps(config)))
                db.session.commit()
                if request.files.get('image') and request.files['image'].filename:
                    upload_image(item)
                return redirect(url_for('marketing_campaign', campaign_id=item.id))
        return render_template('admin_marketing.html', recipients=recipients(),
                               campaigns=Campaign.query.order_by(Campaign.id.desc()).all(), csrf=csrf(), design=defaults)

    @app.route('/admin/marketing/<int:campaign_id>', methods=['GET', 'POST'])
    @admin_required
    def marketing_campaign(campaign_id):
        campaign = db.get_or_404(Campaign, campaign_id)
        if request.method == 'POST':
            check()
            action = request.form.get('action')
            if action == 'edit':
                if campaign.started_at: abort(409, 'Started campaigns cannot be edited.')
                subject, body, config, invalid = campaign_values()
                if invalid:
                    flash('Check the subject, message, design options and button. Buttons need a label and a valid HTTPS link.', 'error')
                else:
                    item = db.session.get(Design, campaign.id)
                    if not item:
                        item = Design(campaign_id=campaign.id); db.session.add(item)
                    item.config_json = json.dumps(config)
                    campaign.subject = subject; campaign.body = body
                    db.session.commit(); flash('Campaign design saved.', 'success')
            elif action == 'upload':
                if campaign.started_at: abort(409)
                upload_image(campaign)
            elif action == 'remove_image':
                if campaign.started_at: abort(409)
                image = Image.query.filter_by(id=request.form.get('image_id', type=int), campaign_id=campaign.id).first_or_404()
                db.session.delete(image); db.session.commit()
            elif action == 'test':
                email = request.form.get('test_email', '').strip().casefold()
                if '@' not in email or len(email) > 255 or '\n' in email or '\r' in email:
                    abort(400)
                body, markup = message(campaign, url_for('marketing_unsubscribe_preview', _external=True))
                sent = send_email(email, '[TEST] ' + campaign.subject, body, markup)
                flash('Test accepted for sending.' if sent else 'Test sending failed. Check Resend configuration.', 'success' if sent else 'error')
            elif action == 'start':
                claimed = Campaign.query.filter_by(id=campaign.id, started_at=None).update({'started_at': datetime.utcnow()}, synchronize_session=False)
                if claimed:
                    for email in recipients():
                        db.session.add(Delivery(campaign_id=campaign.id, email=email))
                    db.session.commit()
                else:
                    db.session.rollback()
                flash('Recipient list saved. Use Send remaining emails to send the campaign.', 'success')
            elif action == 'send':
                # One recipient per request keeps sends reviewable and avoids worker timeouts.
                delivery = Delivery.query.filter_by(campaign_id=campaign.id, status='pending').order_by(Delivery.id).first()
                if delivery:
                    claimed = Delivery.query.filter_by(id=delivery.id, status='pending').update({'status': 'sending', 'attempted_at': datetime.utcnow()}, synchronize_session=False)
                    db.session.commit()
                    if claimed:
                        pref = preference(delivery.email)
                        if delivery.email not in recipients() or pref.unsubscribed_at:
                            delivery.status = 'skipped'
                        else:
                            body, markup = message(campaign, url_for('marketing_unsubscribe', token=pref.token, _external=True))
                            try:
                                sent = send_email(delivery.email, campaign.subject, body, markup)
                            except Exception:
                                sent = False
                            delivery.status = 'accepted' if sent else 'failed'
                        db.session.commit()
                        flash('Sending result: ' + delivery.status + '.', 'success' if delivery.status != 'failed' else 'error')
            else:
                abort(400)
            return redirect(url_for('marketing_campaign', campaign_id=campaign.id))
        deliveries = Delivery.query.filter_by(campaign_id=campaign.id).order_by(Delivery.id).all()
        return render_template('admin_marketing_campaign.html', campaign=campaign, deliveries=deliveries,
                               pending=sum(d.status == 'pending' for d in deliveries), eligible=len(recipients()), csrf=csrf(),
                               design=design(campaign), images=Image.query.filter_by(campaign_id=campaign.id).order_by(Image.id).all())

    @app.get('/admin/marketing/<int:campaign_id>/preview')
    @admin_required
    def marketing_email_preview(campaign_id):
        campaign = db.get_or_404(Campaign, campaign_id)
        return message(campaign, url_for('marketing_unsubscribe_preview', _external=True))[1]

    @app.get('/marketing/unsubscribe-preview')
    def marketing_unsubscribe_preview():
        return render_template('marketing_unsubscribe.html', preview=True)

    @app.route('/marketing/unsubscribe/<token>', methods=['GET', 'POST'])
    def marketing_unsubscribe(token):
        pref = Preference.query.filter_by(token=token).first_or_404()
        if request.method == 'POST':
            # The unguessable email token authorises only withdrawal of marketing consent.
            pref.unsubscribed_at = pref.unsubscribed_at or datetime.utcnow()
            db.session.commit()
        return render_template('marketing_unsubscribe.html', unsubscribed=bool(pref.unsubscribed_at))
