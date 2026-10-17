"""Staff-controlled shared-device signup and public-event waiver flow."""
from datetime import datetime, timedelta
import secrets
import json
from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import inspect, text, MetaData, Table, select


def ensure_schema(db):
    """Upgrade existing kiosk tables without changing saved sessions."""
    columns = {column['name'] for column in inspect(db.engine).get_columns('kiosk_session')}
    if 'choices_json' not in columns:
        with db.engine.begin() as connection:
            connection.execute(text('ALTER TABLE kiosk_session ADD COLUMN choices_json TEXT'))
    if 'completed_at' not in columns:
        with db.engine.begin() as connection:
            connection.execute(text('ALTER TABLE kiosk_session ADD COLUMN completed_at TIMESTAMP'))
    event_column = next(column for column in inspect(db.engine).get_columns('kiosk_session') if column['name'] == 'event_id')
    if not event_column['nullable']:
        with db.engine.begin() as connection:
            if connection.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN')
                # SQLite cannot alter nullability in place. Copy all saved columns
                # and preserve indexes/triggers before replacing the old table.
                schema_objects = connection.execute(text("SELECT sql FROM sqlite_master WHERE tbl_name='kiosk_session' AND type IN ('index','trigger') AND sql IS NOT NULL")).scalars().all()
                metadata = MetaData()
                previous = Table('kiosk_session', metadata, autoload_with=connection)
                replacement = previous.to_metadata(metadata, name='kiosk_session_nullable')
                replacement.c.event_id.nullable = True
                replacement.indexes.clear()
                replacement.create(connection)
                connection.execute(replacement.insert().from_select(list(previous.c.keys()), select(previous)))
                previous.drop(connection)
                connection.execute(text('ALTER TABLE kiosk_session_nullable RENAME TO kiosk_session'))
                for statement in schema_objects: connection.execute(text(statement))
            else:
                connection.execute(text('ALTER TABLE kiosk_session ALTER COLUMN event_id DROP NOT NULL'))


def define_model(db):
    class KioskSession(db.Model):
        id = db.Column(db.String(64), primary_key=True)
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
        phase = db.Column(db.String(20), nullable=False, default='signup')
        csrf = db.Column(db.String(64), nullable=False)
        waiver_id = db.Column(db.Integer, db.ForeignKey('waiver.id'))
        completed_at = db.Column(db.DateTime)
        choices_json = db.Column(db.Text)
        pin_attempts = db.Column(db.Integer, nullable=False, default=0)
        locked_until = db.Column(db.DateTime)
    return KioskSession


def register(app, db, Kiosk, Setting, Event, Waiver, current_client, admin_required, render_waiver, create_waiver,
             Participant, Account, Code, Custodian, send_email):
    def active():
        kiosk_id = session.get('kiosk_id')
        if not kiosk_id:
            return None
        item = db.session.get(Kiosk, kiosk_id)
        if item and item.phase == 'complete' and item.completed_at and datetime.utcnow() >= item.completed_at + timedelta(seconds=30):
            clear_client()
            clear_lookup()
            session.pop('kiosk_event_chosen', None)
            item.phase='signup'; item.waiver_id=None; item.completed_at=None
            db.session.commit()
        return item if item and item.phase != 'closed' else None

    def clear_client():
        # Rendering a background redirect must not invalidate an open form.
        # Submission tokens remain single-use; rotate CSRF when entering/exiting.
        for key in ['client_id','client_signed_in','client_remember','client_pending_remember','client_challenge','loyalty_scan_token']:
            session.pop(key, None)

    @app.before_request
    def kiosk_guard():
        item = active()
        if not item: return
        allowed = {'static','phone_push_worker','kiosk_screen','kiosk_customer','kiosk_submit','kiosk_staff',
                   'kiosk_new_waiver','kiosk_lookup_id','kiosk_email_code','kiosk_verify_email','kiosk_confirm_members','kiosk_start_over'}
        allowed.update({'kiosk_menu', 'kiosk_choose', 'kiosk_form_done'})
        choices = json.loads(item.choices_json or '{}')
        if not item.event_id or (item.choices_json and not session.get('kiosk_event_chosen')):
            allowed.difference_update({'kiosk_submit', 'kiosk_new_waiver', 'kiosk_lookup_id', 'kiosk_email_code',
                'kiosk_verify_email', 'kiosk_confirm_members', 'kiosk_start_over'})
        if request.endpoint in ('native_form_open', 'native_form_submit', 'form_activity', 'kiosk_reset_form') and (request.view_args or {}).get('form_id') in choices.get('forms', []):
            allowed.add(request.endpoint)
        if request.endpoint == 'native_form_image': allowed.add(request.endpoint)
        if request.endpoint in ('booking_availability_check', 'verify_referral_code') and choices.get('forms'):
            allowed.add(request.endpoint)
        if request.endpoint == 'booking_request':
            identity = request.form.get('seasonal_id', type=int) if request.method == 'POST' else request.args.get('seasonal', type=int)
            if identity in choices.get('forms', []): allowed.add(request.endpoint)
        if request.endpoint not in allowed:
            if request.method == 'GET': return redirect(url_for('kiosk_customer'))
            abort(403, 'This device is in kiosk mode. Staff must unlock it.')

    @app.after_request
    def kiosk_response(response):
        if session.get('kiosk_id'):
            response.headers['Cache-Control'] = 'no-store'
            if request.endpoint == 'booking_request' and request.method == 'POST' and response.status_code == 302 and 'submitted=' in response.headers.get('Location', ''):
                session['kiosk_completed_form'] = request.form.get('seasonal_id', type=int)
                return redirect(url_for('kiosk_form_done'))
        return response

    @app.route('/admin/kiosk', methods=['GET','POST'])
    @admin_required
    def kiosk_setup():
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token','')): abort(400)
            if request.form.get('action') == 'wedding_fair':
                from native_form_presets import PRESETS
                from native_form_fields import validate_fields
                preset = PRESETS['wedding_fair']
                Form = app.extensions['native_form_models'][0]
                form = Form.query.filter_by(kind='enquiry', title=preset['title'], enabled=True).first()
                if not form:
                    form = Form(kind=preset['kind'], title=preset['title'], description=preset['description'],
                        terms=preset['terms'], fields_json=json.dumps(validate_fields(preset['fields'])), enabled=True)
                    db.session.add(form); db.session.flush()
                    app.extensions['native_form_records']['set_settings'](form, {'wedding_followup': '4h'})
                    app.extensions['native_form_records']['record_version'](form)
                    db.session.commit()
                flash('Wedding fair form is ready. Tick it under Published forms and start the kiosk. Wedding information is emailed four hours after each entry.', 'success')
                return redirect(url_for('kiosk_setup', wedding_form=form.id))
            event = db.session.get(Event, request.form.get('event_id', type=int))
            event_ids = request.form.getlist('event_ids', type=int)
            if not event_ids and event: event_ids = [event.id]
            if event_ids: event = db.session.get(Event, event_ids[0])
            form_ids = request.form.getlist('form_ids', type=int)
            from native_forms import available
            Form = app.extensions['native_form_models'][0]
            choices_valid = all((e := db.session.get(Event, identity)) and app.extensions['kiosk_public_event'](e) and e.status in ('Open','Closing Soon') for identity in event_ids) and all(available(db.session.get(Form, identity)) for identity in form_ids)
            eligible = bool(event_ids or form_ids)
            pin = request.form.get('pin','')
            stored = db.session.get(Setting, 'kiosk_pin_hash')
            replace_pin = request.form.get('replace_pin') == 'yes'
            if not eligible or not choices_valid:
                flash('Choose at least one open event waiver or published form.', 'error')
            elif not pin.isascii() or not pin.isdigit() or not 4 <= len(pin) <= 8:
                flash('Enter a staff PIN containing 4–8 digits.', 'error')
            elif stored and not replace_pin and not check_password_hash(stored.value, pin):
                flash('That does not match the saved staff PIN. To choose a new PIN, tick "Set a new staff PIN" and enter it again.', 'error')
            else:
                if not stored: db.session.add(Setting(key='kiosk_pin_hash', value=generate_password_hash(pin)))
                elif replace_pin: stored.value = generate_password_hash(pin)
                item = Kiosk(id=secrets.token_urlsafe(32),event_id=event.id if event else None,csrf=secrets.token_urlsafe(32))
                item.choices_json = json.dumps(dict(events=event_ids, forms=form_ids)) if 'selection_present' in request.form or form_ids else None
                db.session.add(item); db.session.commit()
                clear_client(); session['kiosk_id'] = item.id
                session.pop('client_csrf', None)
                session.pop('kiosk_event_chosen', None)
                return redirect(url_for('kiosk_screen'))
        events = [event for event in Event.query.filter(Event.status.in_(['Open','Closing Soon'])).all() if app.extensions['kiosk_public_event'](event)]
        from native_forms import available
        forms = [f for f in app.extensions['native_form_models'][0].query.order_by(app.extensions['native_form_models'][0].title).all() if available(f)]
        queue = app.extensions['wedding_followups']['model']
        followups = queue.query.order_by(queue.due_at.desc()).limit(20).all()
        return render_template('admin_kiosk.html', events=events, forms=forms, client_csrf=token,
            followups=followups,
            pin_configured=db.session.get(Setting,'kiosk_pin_hash') is not None)

    def menu(item):
        from native_forms import available
        choices = json.loads(item.choices_json or '{}')
        Form = app.extensions['native_form_models'][0]
        events = [db.session.get(Event, identity) for identity in choices.get('events', [])]
        forms = [db.session.get(Form, identity) for identity in choices.get('forms', [])]
        return render_template('kiosk_menu.html', item=item,
            events=[e for e in events if e and app.extensions['kiosk_public_event'](e) and e.status in ('Open','Closing Soon')],
            forms=[f for f in forms if available(f)])

    @app.get('/kiosk/menu')
    def kiosk_menu():
        item = active()
        if not item: abort(403)
        clear_client(); clear_lookup()
        session.pop('kiosk_event_chosen', None)
        item.phase='signup'; item.completed_at=None; item.waiver_id=None
        db.session.commit()
        return menu(item)

    @app.post('/kiosk/choose')
    def kiosk_choose():
        item = active()
        if not item: abort(403)
        if not secrets.compare_digest(item.csrf, request.form.get('csrf_token', '')): abort(400)
        identity = request.form.get('event_id', type=int)
        if identity not in json.loads(item.choices_json or '{}').get('events', []): abort(403)
        event = db.get_or_404(Event, identity)
        if not app.extensions['kiosk_public_event'](event) or event.status not in ('Open','Closing Soon'): abort(404)
        clear_client(); clear_lookup()
        item.event_id=identity; item.phase='signup'; db.session.commit()
        session['kiosk_event_chosen']=True
        return redirect(url_for('kiosk_customer'))

    @app.post('/kiosk/forms/<int:form_id>/reset')
    def kiosk_reset_form(form_id):
        item = active()
        if not item: abort(403)
        if form_id not in json.loads(item.choices_json or '{}').get('forms', []): abort(403)
        if not secrets.compare_digest(item.csrf, request.headers.get('X-CSRF-Token', '')): abort(400)
        Form = app.extensions['native_form_models'][0]
        form = db.get_or_404(Form, form_id)
        app.extensions['native_form_records']['clear_draft'](form)
        clear_client(); clear_lookup()
        for key in ('native_form_'+str(form_id), 'native_draft_owner', 'form_visitor', 'kiosk_completed_form'):
            session.pop(key, None)
        item.phase = 'signup'; item.completed_at = None; item.waiver_id = None
        db.session.commit()
        return dict(reset_url=url_for('native_form_open', form_id=form.id))

    @app.get('/kiosk/form-done')
    def kiosk_form_done():
        item = active()
        if not item: abort(403)
        clear_client()
        session.pop('native_booking_confirmation', None)
        from native_forms import available
        identity = session.get('kiosk_completed_form')
        choices = json.loads(item.choices_json or '{}')
        Form = app.extensions['native_form_models'][0]
        form = db.session.get(Form, identity) if identity in choices.get('forms', []) else None
        next_url = url_for('native_form_open', form_id=form.id) if available(form) else url_for('kiosk_menu')
        session.pop('form_visitor', None)
        session.pop('native_draft_owner', None)
        return render_template('kiosk_form_done.html', next_url=next_url)

    @app.get('/kiosk')
    def kiosk_screen():
        item = active()
        if not item: return redirect(url_for('admin_login'))
        return render_template('kiosk_screen.html', item=item)

    @app.get('/kiosk/customer')
    def kiosk_customer():
        item = active()
        if not item: abort(403)
        if item.phase == 'complete':
            import math
            remaining=max(0,math.ceil((item.completed_at+timedelta(seconds=30)-datetime.utcnow()).total_seconds()))
            return render_template('kiosk_complete.html', waiver=db.get_or_404(Waiver,item.waiver_id), reset_seconds=remaining)
        if item.phase == 'members': return member_page(item)
        clear_client()
        if item.phase == 'signup' and item.choices_json and not session.get('kiosk_event_chosen'):
            return menu(item)
        if item.phase == 'signup':
            return render_template('kiosk_start.html', item=item, awaiting_code=bool(session.get('kiosk_code')))
        # Reuse the full signed waiver, terms, declarations and participants form.
        return render_waiver(item.event_id)

    @app.context_processor
    def kiosk_context():
        item = active()
        return dict(kiosk_item=item)

    @app.post('/kiosk/submit')
    def kiosk_submit():
        item = active()
        if not item or item.phase != 'waiver': abort(403)
        if not secrets.compare_digest(item.csrf, request.headers.get('X-CSRF-Token','')): abort(400)
        data = request.get_json()
        if not isinstance(data, dict): abort(400)
        claimed = Kiosk.query.filter_by(id=item.id, phase='waiver').update({'phase':'saving'}, synchronize_session=False)
        db.session.commit()
        if not claimed: abort(409, 'This waiver is already being submitted.')
        try:
            response = make_response(create_waiver(item.event_id))
        except Exception:
            db.session.rollback()
            item.phase='waiver'; db.session.commit()
            raise
        result = response.get_json()
        if response.status_code == 200 and result and result.get('success'):
            waiver = Waiver.query.filter_by(waiver_reference=result['legacy_waiver_reference']).one()
            item.phase='complete'; item.waiver_id=waiver.id; item.completed_at=datetime.utcnow(); db.session.commit()
            clear_client()
            return dict(success=True,waiver_reference=waiver.public_reference,kiosk_redirect=url_for('kiosk_customer'))
        item.phase='waiver'; db.session.commit()
        return response

    @app.post('/kiosk/staff')
    def kiosk_staff():
        item = active()
        if not item: abort(403)
        if not secrets.compare_digest(item.csrf,request.form.get('csrf_token','')): abort(400)
        if item.locked_until and item.locked_until > datetime.utcnow():
            flash('Too many incorrect PINs. Wait five minutes before trying again.', 'error')
            return redirect(url_for('kiosk_screen'))
        stored = db.session.get(Setting,'kiosk_pin_hash')
        if not stored or not check_password_hash(stored.value,request.form.get('pin','')):
            item.pin_attempts += 1
            if item.pin_attempts >= 5: item.locked_until=datetime.utcnow()+timedelta(minutes=5); item.pin_attempts=0
            db.session.commit(); flash('Staff PIN is incorrect.', 'error')
            return redirect(url_for('kiosk_screen'))
        action = request.form.get('action')
        if action != 'exit': abort(400)
        item.pin_attempts=0; item.locked_until=None
        clear_client()
        clear_lookup()
        item.phase='closed'; session.pop('kiosk_id',None)
        session.pop('client_csrf', None)
        db.session.commit()
        return redirect(url_for('admin_dashboard' if action == 'exit' else 'kiosk_screen'))

    from kiosk_existing import register as register_existing
    member_page, clear_lookup = register_existing(app, db, Waiver, Participant, Account, Code, Custodian,
        active, clear_client, send_email)
