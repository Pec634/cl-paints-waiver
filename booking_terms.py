"""Admin-managed booking terms with safe formatting and saved agreement versions."""
import hashlib
import json
import re
import secrets
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from flask import abort, flash, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape


def format_terms(text):
    blocks = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        block = block.strip()
        if not block:
            continue
        heading = block.startswith('# ')
        tag = 'h3' if heading else 'p'
        content = escape(block[2:] if heading else block).replace('\n', Markup('<br>'))
        blocks.append(Markup(f'<{tag}>') + content + Markup(f'</{tag}>'))
    return Markup('\n').join(blocks)


class DefaultText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.tag = None
        self.content = []

    def handle_starttag(self, tag, attrs):
        if tag in ('h3', 'p'):
            self.tag, self.content = tag, []

    def handle_data(self, data):
        if self.tag:
            self.content.append(data)

    def handle_endtag(self, tag):
        if tag == self.tag:
            self.blocks.append(('# ' if tag == 'h3' else '') + ''.join(self.content).strip())
            self.tag = None


def arrange_rescheduling_terms(text, html=False):
    """Place amendments after duration and update numbering and cross-references."""
    pattern = r'<h3>(\d+)\. ([^<]+)</h3>' if html else r'^# (\d+)\. ([^\n]+)'
    headings = list(re.finditer(pattern, text, re.MULTILINE))
    amendment = next((i for i, heading in enumerate(headings)
                      if heading[2] == 'Booking amendments and rescheduling'), None)
    if amendment is None:
        return text
    sections = [(heading, text[heading.start():headings[i + 1].start() if i + 1 < len(headings) else len(text)])
                for i, heading in enumerate(headings)]
    moved = sections.pop(amendment)
    duration = next((i for i, (heading, _) in enumerate(sections) if heading[2] == 'Booking duration'), None)
    if duration is None:
        # Keep bespoke published terms intact when the standard anchor is absent.
        return text
    sections.insert(duration + 1, moved)
    numbers = {heading[1]: str(i + 1) for i, (heading, _) in enumerate(sections)}
    result = [text[:headings[0].start()]]
    for heading, section in sections:
        old, new = heading[1], numbers[heading[1]]
        prefix = r'(<(?:h3|p)>)' if html else r'(^# |^)'
        section = re.sub(prefix + re.escape(old) + r'\.(?=\d| )',
                         lambda match: match[1] + new + '.', section, flags=re.MULTILINE)
        section = re.sub(r'\bSection (\d+)\b',
                         lambda match: 'Section ' + numbers.get(match[1], match[1]), section)
        result.append(section.rstrip() + '\n\n')
    return ''.join(result).rstrip()


def register(app, db, Setting, admin_required):
    default_html = (Path(app.root_path) / 'templates/_booking_terms_default.html').read_text(encoding='utf-8')
    amendment_html = (Path(app.root_path) / 'templates/_booking_rescheduling_terms.html').read_text(encoding='utf-8')
    amendment_parser = DefaultText()
    amendment_parser.feed(amendment_html)
    amendment_text = '\n\n'.join(amendment_parser.blocks)
    default_html += '\n' + amendment_html
    default_html = arrange_rescheduling_terms(default_html, html=True)
    parser = DefaultText()
    parser.feed(default_html)
    default_text = '\n\n'.join(parser.blocks)

    def current():
        row = db.session.get(Setting, 'booking_terms')
        data = json.loads(row.value) if row else dict(text=default_text, updated_at=None)
        if row and not re.search(r'^# \d+\. Booking amendments and rescheduling\s*$', data['text'], re.MULTILINE):
            data['text'] = data['text'].rstrip() + '\n\n' + amendment_text
        data['text'] = arrange_rescheduling_terms(data['text'])
        return data

    def version():
        return 'bt-' + hashlib.sha256(current()['text'].encode()).hexdigest()[:20]

    def terms_html():
        row = db.session.get(Setting, 'booking_terms')
        return format_terms(current()['text']) if row else Markup(default_html)

    def snapshot():
        return dict(version=version(), html=str(app.jinja_env.get_template('_booking_legal_text.html').render()))

    app.jinja_env.globals.update(booking_terms_html=terms_html, booking_terms_version=version)
    app.extensions['booking_terms_snapshot'] = snapshot

    @app.route('/admin/booking-terms', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_terms():
        token = session.setdefault('booking_terms_csrf', secrets.token_urlsafe(32))
        data = current()
        text, error = data['text'], None
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')):
                abort(400)
            text = request.form.get('terms', '').replace('\r\n', '\n').strip()
            if not text or len(text) > 50000:
                error = 'Enter booking terms between 1 and 50,000 characters.'
            elif any(ord(char) < 32 and char not in '\n\t' for char in text):
                error = 'Remove unsupported characters from the terms.'
            elif request.form.get('action') == 'publish':
                if request.form.get('version') != version():
                    error = 'The terms were updated in another window. Reload this page and review the latest wording before publishing.'
                else:
                    db.session.merge(Setting(key='booking_terms', value=json.dumps(dict(text=text, updated_at=datetime.utcnow().isoformat()))))
                    db.session.commit()
                    flash('Booking terms published. The booking form now shows your updated wording.', 'success')
                    return redirect(url_for('admin_booking_terms'))
            elif request.form.get('action') != 'preview':
                abort(400)
        return render_template('admin_booking_terms.html', text=text, preview=format_terms(text),
                               version=version(), updated_at=data['updated_at'], csrf=token, error=error)
