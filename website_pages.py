"""Website page names and custom pages managed by the admin builder."""
import json
import re
import secrets
from flask import abort, redirect, render_template, request, session, url_for

BUILTINS = {'home': 'Home', 'services': 'Services', 'about': 'About',
            'gallery': 'Gallery', 'contact': 'Contact'}


def register(app, db, Setting, admin_required):
    def catalog():
        setting = db.session.get(Setting, 'website_pages')
        return json.loads(setting.value) if setting else {}

    def pages():
        entries = {key: dict(name=name, custom=False) for key, name in BUILTINS.items()}
        for key, value in catalog().items():
            entries[key] = dict(entries.get(key, {}), **value)
        return {key: value for key, value in entries.items() if not value.get('removed')}

    def page_url(key):
        entry = pages().get(key)
        if entry and entry.get('custom'):
            return url_for('website_custom_page', slug=entry['slug'])
        return url_for('website_' + key)

    app.extensions['website_pages'] = pages
    app.extensions['website_page_url'] = page_url

    @app.context_processor
    def page_context():
        entries = pages()
        for key, entry in entries.items():
            layout = db.session.get(db._website_layout, key)
            draft = db.session.get(db._website_draft, key)
            published = not entry.get('custom') or layout is not None
            changed = draft is not None and json.loads(draft.content) != json.loads(layout.content if layout else '{}')
            entry['status'] = 'Draft' if not published else 'Published · draft changes' if changed else 'Published'
        nav = [(key, entry['name'], page_url(key)) for key, entry in entries.items()
               if not entry.get('custom') or db.session.get(db._website_layout, key)]
        nav.insert(min(4, len(nav)), ('studio', 'Studio', url_for('website_studio')))
        return dict(builder_pages=entries, website_navigation=nav, website_page_url=page_url)

    @app.post('/admin/website-builder/pages')
    @admin_required
    def admin_website_pages():
        if not session.get('client_csrf') or not secrets.compare_digest(
                request.form.get('csrf_token', ''), session['client_csrf']):
            abort(400)
        records = catalog()
        action = request.form.get('action')
        key = request.form.get('page', '')
        entries = pages()
        if action in ('add', 'rename'):
            name = request.form.get('name', '').strip()
            if not name or len(name) > 80:
                abort(400, 'Enter a page name of up to 80 characters.')
        if action == 'add':
            slug = request.form.get('slug', '').strip().lower()
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or len(slug) > 80:
                abort(400, 'Use letters, numbers and hyphens for the page address.')
            if any(entry.get('slug') == slug for entry in entries.values()):
                abort(400, 'That page address is already in use.')
            key = 'p-' + secrets.token_hex(6)
            records[key] = dict(name=name, slug=slug, custom=True)
            db.session.add(db._website_draft(page=key, content='{}'))
        elif action in ('rename', 'remove'):
            if key not in entries:
                abort(404)
            if action == 'remove' and key == 'home':
                abort(400, 'The home page must remain available.')
            records[key] = dict(entries[key])
            if action == 'rename':
                records[key]['name'] = name
            else:
                records[key]['removed'] = True
                key = 'home'
        else:
            abort(400)
        setting = db.session.get(Setting, 'website_pages')
        if setting is None:
            setting = Setting(key='website_pages', value='{}')
            db.session.add(setting)
        setting.value = json.dumps(records)
        db.session.commit()
        return redirect(url_for('admin_website_builder', page=key))

    @app.get('/pages/<slug>')
    def website_custom_page(slug):
        match = next(((key, entry) for key, entry in pages().items()
                      if entry.get('custom') and entry.get('slug') == slug), None)
        if match is None:
            abort(404)
        key, entry = match
        if not db.session.get(db._website_layout, key) and not session.get('admin_authenticated'):
            abort(404)
        return render_template('website/custom.html', page=key, page_name=entry['name'],
                               seo_title=entry['name'] + ' | CL Paints', seo_description='')
