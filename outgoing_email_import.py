"""Read-only Resend history import; never resends an email."""
from datetime import datetime, timezone
from email.utils import parseaddr
from html.parser import HTMLParser
import os
import json
import secrets
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask import abort, flash, redirect, request, session, url_for
from outgoing_emails import category


class HistoryError(Exception):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li') and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def history_fetcher():
    key = os.getenv('RESEND_HISTORY_API_KEY') or os.getenv('RESEND_API_KEY')
    if not key:
        raise HistoryError('Resend is not configured here. Run the import on the live server with its Resend key configured.')
    last = [0.0]

    def fetch(path):
        pause = 0.6 - (time.monotonic() - last[0])
        if pause > 0:
            time.sleep(pause)
        last[0] = time.monotonic()
        req = Request('https://api.resend.com/' + path, headers={
            'Authorization': 'Bearer ' + key, 'User-Agent': 'CL-Paints-email-history-import'})
        try:
            with urlopen(req, timeout=8) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise HistoryError('Resend history access was denied. Configure RESEND_HISTORY_API_KEY on the server with Full access; a sending-only key cannot read past emails.') from None
            if exc.code == 429:
                raise HistoryError('Resend is temporarily rate limiting requests. Wait a moment, then continue the import.') from None
            raise HistoryError(f'Resend could not return this email history (HTTP {exc.code}). You can retry the import.') from None
        except (URLError, TimeoutError, ValueError):
            raise HistoryError('Resend history could not be reached. Saved imports are retained; try continuing again.') from None
    return fetch


def import_page(db, Model, fetch, cursor=''):
    params = {'limit': 10}
    if cursor:
        params['after'] = cursor
    page = fetch('emails?' + urlencode(params))
    result = dict(imported=0, skipped=0, cursor=cursor, more=bool(page.get('has_more')), error='')
    for summary in page.get('data', []):
        email_id = summary.get('id')
        if not email_id:
            continue
        # Only import the sender used by this portal, not unrelated team emails.
        if parseaddr(summary.get('from', ''))[1].lower() != 'info@clpaints.com':
            result.update(cursor=email_id, skipped=result['skipped'] + 1)
            continue
        recipients = summary.get('to') or []
        if isinstance(recipients, str):
            recipients = [recipients]
        if recipients and all(Model.query.filter_by(provider_id=email_id, recipient=recipient).first() for recipient in recipients):
            result.update(cursor=email_id, skipped=result['skipped'] + 1)
            continue
        try:
            email = fetch('emails/' + quote(email_id, safe=''))
        except HistoryError as exc:
            result.update(more=True, error=str(exc))
            return result
        subject = email.get('subject') or summary.get('subject') or '(No subject)'
        kind = category(subject, '')
        text = email.get('text') or ''
        markup = email.get('html') or ''
        if kind == 'security':
            text = 'Security email content is hidden to protect verification codes and reset links.'
            markup = ''
        elif not text and markup:
            parser = PlainText(); parser.feed(markup)
            text = ''.join(parser.parts).strip()
        if not text and not markup:
            text = 'The original message content is no longer available from Resend.'
        try:
            at = datetime.fromisoformat(email.get('created_at') or summary['created_at'])
            at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
            at = at.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError, KeyError):
            result.update(more=True, error='Resend returned an invalid email timestamp. Import stopped without inventing a sending date.')
            return result
        for recipient in recipients:
            if Model.query.filter_by(provider_id=email_id, recipient=recipient).first():
                continue
            db.session.add(Model(recipient=recipient, sender=email.get('from') or summary.get('from', ''),
                subject=subject, body_text=text, body_html=markup, attachments='[]', kind=kind,
                trigger='historical', endpoint='import_resend_history', status='accepted',
                provider_id=email_id, created_at=at))
            db.session.commit()
            result['imported'] += 1
        result['cursor'] = email_id
    return result


def register(app, db, Model, admin_required):
    @app.post('/admin/communications/outgoing-emails/import')
    @admin_required
    def outgoing_emails_import():
        csrf = session.get('client_csrf', '')
        if not csrf or not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
            abort(400)
        action = request.form.get('action')
        if action not in ('start', 'continue'):
            abort(400)
        progress = {} if action == 'start' else session.get('outgoing_history_import', {})
        try:
            result = import_page(db, Model, history_fetcher(), progress.get('cursor', ''))
        except HistoryError as exc:
            flash(str(exc), 'error')
        else:
            session['outgoing_history_import'] = dict(cursor=result['cursor'], more=result['more'],
                imported=progress.get('imported', 0) + result['imported'])
            flash(f'Imported {result["imported"]} email(s); skipped {result["skipped"]} already recorded or unrelated email(s). ' +
                  ('More history is available. Select Continue import.' if result['more'] else 'Reached the end of the history available from Resend.'), 'success')
            if result['error']:
                flash(result['error'], 'error')
        return redirect(url_for('communications_outgoing'))
