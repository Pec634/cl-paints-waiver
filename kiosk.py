"""Staff-controlled shared-device signup and public-event waiver flow."""
from datetime import datetime, timedelta
import secrets
from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import inspect, text


def ensure_schema(db):
    """Upgrade existing kiosk tables without changing saved sessions."""
    columns = {column['name'] for column in inspect(db.engine).get_columns('kiosk_session')}
    if 'completed_at' not in columns:
        with db.engine.begin() as connection:
            connection.execute(text('ALTER TABLE kiosk_session ADD COLUMN completed_at TIMESTAMP'))


def define_model(db):
    class KioskSession(db.Model):
        id = db.Column(db.String(64), primary_key=True)
        event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
        phase = db.Column(db.String(20), nullable=False, default='signup')
        csrf = db.Column(db.String(64), nullable=False)
        waiver_id = db.Column(db.Integer, db.ForeignKey('waiver.id'))
        completed_at = db.Column(db.DateTime)
        pin_attempts = db.Column(db.Integer, nullable=False, default=0)
        locked_until = db.Column(db.DateTime)
    return KioskSession


def register(app, db, Kiosk, Setting, Event, Waiver, current_client, admin_required, render_waiver, create_waiver):
    def active():
        kiosk_id = session.get('kiosk_id')
        if not kiosk_id:
            return None
        item = db.session.get(Kiosk, kiosk_id)
        if item and item.phase == 'complete' and item.completed_at and datetime.utcnow() >= item.completed_at + timedelta(seconds=30):
            clear_client()
            item.phase='signup'; item.waiver_id=None; item.completed_at=None
            db.session.commit()
        return item if item and item.phase != 'closed' else None

    def clear_client():
        for key in ['client_id','client_signed_in','client_remember','client_pending_remember','client_challenge','client_csrf','loyalty_scan_token']:
            session.pop(key, None)

    @app.before_request
    def kiosk_guard():
        item = active()
        if not item: return
        allowed = {'static','kiosk_screen','kiosk_customer','kiosk_submit','kiosk_staff'}
        if request.endpoint not in allowed:
            if request.method == 'GET': return redirect(url_for('kiosk_customer'))
            abort(403, 'This device is in kiosk mode. Staff must unlock it.')

    @app.route('/admin/kiosk', methods=['GET','POST'])
    @admin_required
    def kiosk_setup():
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token','')): abort(400)
            event = db.session.get(Event, request.form.get('event_id', type=int))
            eligible = event and app.extensions['kiosk_public_event'](event) and event.status in ('Open','Closing Soon')
            pin = request.form.get('pin','')
            stored = db.session.get(Setting, 'kiosk_pin_hash')
            if not eligible or not pin.isascii() or not pin.isdigit() or not 4 <= len(pin) <= 8:
                flash('Choose an open public event and a 4–8 digit staff PIN.', 'error')
            elif stored and not check_password_hash(stored.value, pin):
                flash('Staff PIN is incorrect.', 'error')
            else:
                if not stored: db.session.add(Setting(key='kiosk_pin_hash', value=generate_password_hash(pin)))
                item = Kiosk(id=secrets.token_urlsafe(32),event_id=event.id,csrf=secrets.token_urlsafe(32))
                db.session.add(item); db.session.commit()
                clear_client(); session['kiosk_id'] = item.id
                return redirect(url_for('kiosk_screen'))
        events = [event for event in Event.query.filter(Event.status.in_(['Open','Closing Soon'])).all() if app.extensions['kiosk_public_event'](event)]
        return render_template('admin_kiosk.html', events=events, client_csrf=token,
            pin_configured=db.session.get(Setting,'kiosk_pin_hash') is not None)

    @app.get('/kiosk')
    def kiosk_screen():
        item = active()
        if not item: return redirect(url_for('admin_login'))
        return render_template('kiosk_screen.html', item=item, event=db.get_or_404(Event,item.event_id))

    @app.get('/kiosk/customer')
    def kiosk_customer():
        item = active()
        if not item: abort(403)
        if item.phase == 'complete':
            import math
            remaining=max(0,math.ceil((item.completed_at+timedelta(seconds=30)-datetime.utcnow()).total_seconds()))
            return render_template('kiosk_complete.html', waiver=db.get_or_404(Waiver,item.waiver_id), reset_seconds=remaining)
        clear_client()
        if item.phase == 'signup': item.phase='waiver'; db.session.commit()
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
        item.phase='closed'; session.pop('kiosk_id',None)
        db.session.commit()
        return redirect(url_for('admin_dashboard' if action == 'exit' else 'kiosk_screen'))
