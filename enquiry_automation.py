"""Deterministic, editable acknowledgements for new enquiries."""
import re
from string import Formatter
from decimal import Decimal
from sqlalchemy.exc import IntegrityError

TOPICS = ('pricing', 'availability', 'other')
DEFAULTS = {}
for topic in TOPICS:
    DEFAULTS[f'auto_{topic}_enabled'] = '1'
DEFAULTS.update(
    auto_pricing_keywords='price, pricing, cost, costs, how much, rates, quote, quotation',
    auto_availability_keywords='available, availability, free on, book, booking',
    auto_pricing_body='Thank you for your pricing enquiry. Our current hourly rate is £{hourly_rate}, with a minimum booking of {minimum_hours} hours (from £{minimum_price}, before any applicable travel charges). Final pricing depends on your event requirements and location. Please send your event date, location, duration and number of guests so we can advise. You can visit {website} for more information.',
    auto_availability_body='Thank you for your availability enquiry. Please send your event date, start time, location, duration and estimated number of guests. We will check availability and get back to you. Availability and your booking are subject to confirmation.',
    auto_other_body='Thank you for contacting CL Paints. We have received your enquiry and aim to respond within 48 hours.',
)


def validate_settings(form):
    values = {}
    for topic in TOPICS:
        values[f'auto_{topic}_enabled'] = '1' if form.get(f'auto_{topic}_enabled') == '1' else '0'
        key = f'auto_{topic}_body'
        body = form.get(key, '').strip()
        if not body or len(body) > 2800:
            raise ValueError('Each automatic reply needs between 1 and 2,800 characters.')
        for _, field, spec, conversion in Formatter().parse(body):
            if field is not None and (field not in ('hourly_rate', 'minimum_hours', 'minimum_price', 'website') or spec or conversion):
                raise ValueError('Use only the automatic reply placeholders shown on the configuration page.')
        values[key] = body
        if topic != 'other':
            key = f'auto_{topic}_keywords'
            words = form.get(key, '').strip()
            if not words or len(words) > 500 or not any(word.strip() for word in words.split(',')):
                raise ValueError('Enter comma-separated keywords, up to 500 characters.')
            values[key] = words
    return values


def select_reply(config, subject, message):
    text = f'{subject}\n{message}'.casefold()
    topic = 'other'
    for candidate in TOPICS[:2]:
        if any(re.search(r'(?<!\w)' + re.escape(word.strip().casefold()) + r'(?!\w)', text)
               for word in config[f'auto_{candidate}_keywords'].split(',') if word.strip()):
            topic = candidate
            break
    if config[f'auto_{topic}_enabled'] != '1':
        return None
    body = config[f'auto_{topic}_body'].format(
        hourly_rate=config['hourly_rate'], minimum_hours=config['minimum_hours'],
        minimum_price=f"{Decimal(config['hourly_rate']) * Decimal(config['minimum_hours']):.2f}",
        website=config['website'])
    return topic, body


def register(app, db, Reply, Workflow, Notice, settings, send_email):
    def send(source, enquiry, account=None):
        try:
            config = settings()
            selected = select_reply(config, enquiry.subject, enquiry.message)
            if not selected:
                return
            topic, body = selected
            reference = f'Automatic {topic} reply — Enquiry #{enquiry.id}'
            if source == 'website':
                record = Reply(enquiry_id=enquiry.id, token=f'auto-website-{enquiry.id}', body=body)
                email, name, kind = enquiry.email, enquiry.name, 'website_enquiry'
            else:
                record = Workflow(enquiry_id=enquiry.id, status='new', reply=body)
                email, name, kind = account.email, account.first_name, 'portal_enquiry'
            db.session.add(record)
            # Claim before sending; a unique key prevents repeat delivery.
            db.session.commit()
            notice = Notice(email=email, kind='enquiry', reference=reference, details=body, email_sent=False)
            db.session.add(notice)
            db.session.commit()
            try:
                from client_notifications import render_notification
                subject, plain, _, html = render_notification(config, name, kind, reference, body, '')
                sent = bool(send_email(email, subject, plain, html, app.extensions['email_media_attachments'](kind)))
            except Exception:
                sent = False
                app.logger.exception('Automatic enquiry reply delivery failed')
            notice.email_sent = sent
            if source == 'website':
                record.delivery = 'accepted' if sent else 'failed'
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        except Exception:
            db.session.rollback()
            app.logger.exception('Automatic enquiry reply could not be recorded')
    app.extensions['send_enquiry_auto_reply'] = send
