"""Named, restricted till accounts alongside the existing portal administrator."""
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import hmac
import json
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from staff_permissions import AREAS, KEYS, SHARED_PRIVATE, permissions, required_area


def define_models(db):
    class PosStaff(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(80), nullable=False, unique=True)
        name = db.Column(db.String(120), nullable=False)
        password_hash = db.Column(db.Text, nullable=False)
        pin_hash = db.Column(db.Text, nullable=True)
        pin_digest = db.Column(db.String(64), nullable=True, unique=True)
        role = db.Column(db.String(12), nullable=False)
        permissions_json = db.Column(db.Text, nullable=True)
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
        return bool(staff and staff.enabled and {'pos','pos_manager'} <= permissions(staff)) if session.get('pos_staff_id') else bool(session.get('admin_authenticated'))

    def allowed(self, endpoint):
        if not session.get('pos_staff_id'):return bool(session.get('admin_authenticated'))
        staff=self.staff()
        area=required_area(endpoint,self.app.view_functions.get(endpoint))
        if endpoint=='native_field_file' and hasattr(self.db,'_native_extra_models'):
            identity=(request.view_args or {}).get('file_id')
            record=self.db.session.get(self.db._native_extra_models[-1],identity) if identity else None
            area=('bookings' if record.booking_id else 'forms') if record else None
        now=datetime.utcnow().timestamp()
        active=now-session.get('pos_last_activity',0)<=1800 and now-session.get('pos_signed_in_at',0)<=28800
        return bool(active and staff and staff.enabled and area and area in permissions(staff))

    def links(self):
        staff=self.staff()
        granted=permissions(staff) if staff and staff.enabled else set()
        return [dict(key=key,label=label,url=url_for(endpoint),description=description)
            for key,label,endpoint,description in AREAS
            if key in granted and endpoint in self.app.view_functions]

    def authorize_session(self):
        staff=self.staff()
        now=datetime.utcnow().timestamp()
        if (not staff or not staff.enabled or now-session.get('pos_last_activity',0)>1800
                or now-session.get('pos_signed_in_at',0)>28800):
            session.clear()
            if request.is_json or request.headers.get('Accept')=='application/json':
                return {'error':'Your staff session has ended. Sign in with your PIN again.'},401
            return redirect(url_for('pos_staff_login',expired=1))
        if request.endpoint not in ('pos_stock', 'pos_waiver_search', 'admin_participants') or request.headers.get('X-Portal-Refresh') != '1':
            session['pos_last_activity']=now
        session.setdefault('client_csrf',secrets.token_urlsafe(32))
        return None

    def authorize(self):
        denied=self.authorize_session()
        if denied is not None:return denied
        if request.endpoint in ('staff_portal_home','pos_staff_logout'):return None
        if not self.allowed(request.endpoint):abort(403,'Your administrator has not enabled this area for your staff account.')
        if request.endpoint=='communications_templates' and request.method=='POST' and request.form.get('section') not in {
                'notifications','email_bookings','email_booking_added','email_rewards','email_portal_enquiry','email_website_enquiry','email_design'}:
            abort(403)
        return None

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
            denied=self.authorize()
            if denied is not None:return denied
            return view(*args, **kwargs)
        return wrapped

    def register(self):
        app, db, Staff, Attempt = self.app, self.db, self.Staff, self.Attempt
        def staff_gate():
            if session.get('pos_staff_id') and request.endpoint not in ('pos_staff_login','staff_portal_login','admin_login','admin_owner_login','admin_verify','admin_logout') and (
                    request.path.startswith('/admin') or request.endpoint in SHARED_PRIVATE):
                if request.endpoint=='admin_dashboard' and request.method=='GET':
                    denied=self.authorize_session()
                    return denied if denied is not None else redirect(url_for('staff_portal_home'))
                return self.authorize()
        # Run before feature-specific hooks, including hooks that perform writes.
        app.before_request_funcs.setdefault(None,[]).insert(0,staff_gate)

        @app.context_processor
        def pos_identity():
            if session.get('pos_staff_id'):
                session.setdefault('client_csrf',secrets.token_urlsafe(32))
                return dict(pos_manager=self.manager(),pos_actor=self.actor(),pos_staff_tools=False,
                    staff_portal=True,staff_actor=self.actor(),staff_can=self.allowed)
            if request.path.startswith('/admin/pos') or (request.path.startswith('/admin/') and session.get('admin_authenticated')):
                return dict(pos_manager=self.manager(), pos_actor=self.actor(), pos_staff_tools=True)
            return {}

        @app.get('/admin/staff')
        @self.required
        def staff_portal_home():
            return render_template('staff_portal.html',areas=self.links())

        @app.get('/admin/staff/login')
        def staff_portal_login():
            return redirect(url_for('pos_staff_login'))

        @app.route('/admin/pos/staff/login', methods=['GET','POST'])
        def pos_staff_login():
            token = session.setdefault('pos_login_csrf', secrets.token_urlsafe(32))
            error = None
            owner_login_url = url_for('admin_owner_login') if 'admin_owner_login' in app.view_functions else None
            if request.method=='POST':
                if not secrets.compare_digest(token,request.form.get('csrf_token','')): abort(400)
                source = hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
                if Attempt.query.filter(Attempt.source==source,Attempt.at>datetime.utcnow()-timedelta(minutes=15)).count()>=5:
                    return render_template('pos_staff_login.html',csrf=token,owner_login_url=owner_login_url,error='Too many attempts. Try again in 15 minutes.'),429
                pin = request.form.get('pin','')
                valid = bool(pin) and len(pin)<=256 and pin.isascii() and pin.isdigit()
                staff = Staff.query.filter_by(pin_digest=self.pin_digest(pin),enabled=True).first() if valid else None
                if staff and staff.pin_hash and check_password_hash(staff.pin_hash,pin):
                    Attempt.query.filter_by(source=source).delete(); db.session.commit()
                    session.clear()
                    session.update(pos_staff_id=staff.id,pos_last_activity=datetime.utcnow().timestamp(),pos_signed_in_at=datetime.utcnow().timestamp())
                    return redirect(url_for('pos_home' if permissions(staff)=={'pos'} else 'staff_portal_home'))
                db.session.add(Attempt(source=source)); db.session.commit()
                error = 'PIN not recognised.'
            return render_template('pos_staff_login.html',csrf=token,owner_login_url=owner_login_url,error=error)

        @app.post('/admin/pos/staff/logout')
        @self.required
        def pos_staff_logout():
            self.check()
            session.clear()
            return render_template('pos_staff_logout.html')

        @app.route('/admin/pos/staff', methods=['GET','POST'])
        @self.required
        def pos_staff_manage():
            if session.get('pos_staff_id') or not session.get('admin_authenticated'):abort(403)
            token = session.setdefault('client_csrf',secrets.token_urlsafe(32))
            if request.method=='POST':
                self.check()
                identity = request.form.get('staff_id',type=int)
                staff = db.get_or_404(Staff,identity) if identity else Staff()
                try:
                    username = staff.username if identity else 'staff-'+secrets.token_hex(12)
                    name = request.form.get('name','').strip()
                    explicit=request.form.get('permissions_version')=='1'
                    selected=set(request.form.getlist('permissions')) if explicit else ({'pos','pos_manager'} if request.form.get('role')=='manager' else {'pos'})
                    if selected-KEYS:raise ValueError('Choose valid portal permissions.')
                    if 'pos_manager' in selected:selected.add('pos')
                    role = ('manager' if 'pos_manager' in selected else 'cashier') if explicit else request.form.get('role')
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
                    staff.permissions_json=json.dumps(sorted(selected))
                    staff.enabled = request.form.get('enabled')=='yes'
                    if pin:
                        staff.pin_hash=generate_password_hash(pin)
                        staff.pin_digest=digest
                        # Retain the legacy required column without enabling password sign-in.
                        staff.password_hash=staff.pin_hash
                    db.session.add(staff); db.session.commit()
                    flash('Staff account and permissions saved. Changes apply on their next request.','success')
                except (ValueError,IntegrityError) as error:
                    db.session.rollback()
                    flash(str(error) if isinstance(error,ValueError) else 'That PIN is already allocated to another staff member.','error')
                return redirect(url_for('pos_staff_manage'))
            return render_template('pos_staff_manage.html',staff=Staff.query.order_by(Staff.name).all(),csrf=token,
                permission_areas=AREAS,staff_permissions=permissions)

    def check(self):
        token = request.form.get('csrf_token','') if not request.is_json else (request.get_json(silent=True) or {}).get('csrf_token','')
        if not session.get('client_csrf') or not isinstance(token,str) or not secrets.compare_digest(session['client_csrf'],token):
            abort(400)
