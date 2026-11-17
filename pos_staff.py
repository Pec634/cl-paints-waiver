"""Named, restricted till accounts alongside the existing portal administrator."""
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import hmac
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


def define_models(db):
    class PosStaff(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(80), nullable=False, unique=True)
        name = db.Column(db.String(120), nullable=False)
        password_hash = db.Column(db.Text, nullable=False)
        pin_hash = db.Column(db.Text, nullable=True)
        pin_digest = db.Column(db.String(64), nullable=True, unique=True)
        role = db.Column(db.String(12), nullable=False)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
    class PosLoginAttempt(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        source = db.Column(db.String(64), nullable=False, index=True)
        at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    return PosStaff, PosLoginAttempt


class PosAccess:
    def __init__(self, app, db, models, admin_required):
        self.app, self.db = app, db
        self.Staff, self.Attempt = models
        self.admin_required = admin_required

    def pin_digest(self, pin):
        key=self.app.secret_key
        if isinstance(key,str):key=key.encode('utf-8')
        return hmac.new(key,pin.encode('ascii'),hashlib.sha256).hexdigest()

    def staff(self):
        identity = session.get('pos_staff_id')
        if not identity:
            return None
        return self.db.session.get(self.Staff, identity)

    def manager(self):
        staff = self.staff()
        return bool(staff and staff.enabled and staff.role=='manager') if session.get('pos_staff_id') else bool(session.get('admin_authenticated'))

    def require_manager(self):
        if not self.manager():
            abort(403, 'A POS manager must sign in for this action.')

    def actor(self):
        staff = self.staff()
        return staff.name if staff else self.app.config.get('ADMIN_EMAIL') or 'Portal administrator'

    def owner(self):
        return 'staff:'+str(session['pos_staff_id']) if session.get('pos_staff_id') else 'administrator'

    def required(self, view):
        admin_view = self.admin_required(view)
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('pos_staff_id'):
                return admin_view(*args, **kwargs)
            staff = self.staff()
            now = datetime.utcnow().timestamp()
            if (not staff or not staff.enabled or now-session.get('pos_last_activity',0)>1800
                    or now-session.get('pos_signed_in_at',0)>28800):
                session.clear()
                return redirect(url_for('pos_staff_login', expired=1))
            session['pos_last_activity'] = now
            session.setdefault('client_csrf',secrets.token_urlsafe(32))
            return view(*args, **kwargs)
        return wrapped

    def register(self):
        app, db, Staff, Attempt = self.app, self.db, self.Staff, self.Attempt
        @app.context_processor
        def pos_identity():
            if request.path.startswith('/admin/pos') or (request.path.startswith('/admin/') and session.get('admin_authenticated')):
                return dict(pos_manager=self.manager(), pos_actor=self.actor(), pos_staff_tools=True)
            return {}

        @app.route('/admin/pos/staff/login', methods=['GET','POST'])
        def pos_staff_login():
            token = session.setdefault('pos_login_csrf', secrets.token_urlsafe(32))
            error = None
            if request.method=='POST':
                if not secrets.compare_digest(token,request.form.get('csrf_token','')): abort(400)
                source = hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
                if Attempt.query.filter(Attempt.source==source,Attempt.at>datetime.utcnow()-timedelta(minutes=15)).count()>=5:
                    return render_template('pos_staff_login.html',csrf=token,error='Too many attempts. Try again in 15 minutes.'),429
                pin = request.form.get('pin','')
                valid = bool(pin) and len(pin)<=256 and pin.isascii() and pin.isdigit()
                staff = Staff.query.filter_by(pin_digest=self.pin_digest(pin),enabled=True).first() if valid else None
                if staff and staff.pin_hash and check_password_hash(staff.pin_hash,pin):
                    Attempt.query.filter_by(source=source).delete(); db.session.commit()
                    session.clear()
                    session.update(pos_staff_id=staff.id,pos_last_activity=datetime.utcnow().timestamp(),pos_signed_in_at=datetime.utcnow().timestamp())
                    return redirect(url_for('pos_home'))
                db.session.add(Attempt(source=source)); db.session.commit()
                error = 'PIN not recognised.'
            return render_template('pos_staff_login.html',csrf=token,error=error)

        @app.post('/admin/pos/staff/logout')
        @self.required
        def pos_staff_logout():
            self.check()
            session.clear()
            return render_template('pos_staff_logout.html')

        @app.route('/admin/pos/staff', methods=['GET','POST'])
        @self.required
        def pos_staff_manage():
            self.require_manager()
            token = session.setdefault('client_csrf',secrets.token_urlsafe(32))
            if request.method=='POST':
                self.check()
                identity = request.form.get('staff_id',type=int)
                staff = db.get_or_404(Staff,identity) if identity else Staff()
                try:
                    username = staff.username if identity else 'staff-'+secrets.token_hex(12)
                    name = request.form.get('name','').strip()
                    role = request.form.get('role')
                    pin = request.form.get('pin','')
                    if not name or len(name)>120 or role not in ('cashier','manager'):
                        raise ValueError('Enter a staff name and choose cashier or manager.')
                    if (not identity or pin) and (not pin or len(pin)>256 or not pin.isascii() or not pin.isdigit()):
                        raise ValueError('Enter a staff PIN using digits only. There is no minimum length.')
                    if pin:
                        digest=self.pin_digest(pin)
                        duplicate=Staff.query.filter(Staff.pin_digest==digest).first()
                        if duplicate and duplicate.id!=identity:
                            raise ValueError('That PIN is already allocated to another staff member.')
                    staff.username,staff.name,staff.role = username,name,role
                    staff.enabled = request.form.get('enabled')=='yes'
                    if pin:
                        staff.pin_hash=generate_password_hash(pin)
                        staff.pin_digest=digest
                        # Retain the legacy required column without enabling password sign-in.
                        staff.password_hash=staff.pin_hash
                    db.session.add(staff); db.session.commit()
                    flash('Staff account saved. Disabled accounts lose access on their next request.','success')
                except (ValueError,IntegrityError) as error:
                    db.session.rollback()
                    flash(str(error) if isinstance(error,ValueError) else 'That PIN is already allocated to another staff member.','error')
                return redirect(url_for('pos_staff_manage'))
            return render_template('pos_staff_manage.html',staff=Staff.query.order_by(Staff.name).all(),csrf=token)

    def check(self):
        token = request.form.get('csrf_token','') if not request.is_json else (request.get_json(silent=True) or {}).get('csrf_token','')
        if not session.get('client_csrf') or not isinstance(token,str) or not secrets.compare_digest(session['client_csrf'],token):
            abort(400)
