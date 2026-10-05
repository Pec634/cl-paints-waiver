"""Persistent login throttling and optional email verification for administrators."""
from datetime import datetime, timedelta
import hashlib
import secrets
from flask import abort, redirect, render_template, request, session, url_for


def define_models(db):
    class AdminLoginAttempt(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        source=db.Column(db.String(64),nullable=False,index=True)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow,index=True)
    class AdminLoginChallenge(db.Model):
        id=db.Column(db.String(64),primary_key=True)
        digest=db.Column(db.String(64),nullable=False)
        expires_at=db.Column(db.DateTime,nullable=False)
        attempts=db.Column(db.Integer,nullable=False,default=0)
        consumed=db.Column(db.Boolean,nullable=False,default=False)
    return AdminLoginAttempt,AdminLoginChallenge


def register(app,db,models,send_email,email_address):
    Attempt,Challenge=models
    def check_login():
        token=session.setdefault('admin_login_csrf',secrets.token_urlsafe(32))
        if not secrets.compare_digest(token,request.form.get('csrf_token','')):abort(400)
        source=hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
        now=datetime.utcnow(); window=now-timedelta(minutes=15)
        if Attempt.query.filter(Attempt.source==source,Attempt.created_at>window).count()>=5:
            return False
        db.session.add(Attempt(source=source)); db.session.commit()
        return True
    def start_verification():
        email=email_address()
        if not email: return False
        identity=secrets.token_urlsafe(32); code=f'{secrets.randbelow(1000000):06d}'
        item=Challenge(id=identity,digest=hashlib.sha256((identity+':'+code).encode()).hexdigest(),expires_at=datetime.utcnow()+timedelta(minutes=10))
        db.session.add(item);db.session.commit()
        if not send_email(email,'CL Paints admin verification code',f'Your admin sign-in code is {code}. It expires in 10 minutes. Do not share this code.'):
            item.consumed=True;db.session.commit();return False
        session.clear();session['admin_challenge']=identity
        return True
    app.extensions['admin_login_check']=check_login
    app.extensions['admin_start_verification']=start_verification

    @app.route('/admin/verify',methods=['GET','POST'])
    def admin_verify():
        item=db.session.get(Challenge,session.get('admin_challenge')) if session.get('admin_challenge') else None
        if not item or item.consumed or item.expires_at<=datetime.utcnow() or item.attempts>=5:
            session.pop('admin_challenge',None);return redirect(url_for('admin_login'))
        token=session.setdefault('admin_verify_csrf',secrets.token_urlsafe(32));error=None
        if request.method=='POST':
            if not secrets.compare_digest(token,request.form.get('csrf_token','')):abort(400)
            code=request.form.get('code','').strip()
            claimed=Challenge.query.filter(Challenge.id==item.id,Challenge.consumed.is_(False),Challenge.attempts<5,Challenge.expires_at>datetime.utcnow()).update({'attempts':Challenge.attempts+1},synchronize_session=False)
            db.session.commit()
            if not claimed:return redirect(url_for('admin_login'))
            if secrets.compare_digest(item.digest,hashlib.sha256((item.id+':'+code).encode()).hexdigest()):
                claimed=Challenge.query.filter_by(id=item.id,consumed=False).update({'consumed':True},synchronize_session=False);db.session.commit()
                if claimed:
                    session.clear();session['admin_authenticated']=True;session['admin_last_activity']=datetime.utcnow().timestamp()
                    return redirect(url_for('admin_dashboard'))
            error='Code incorrect or unavailable. Try again.'
        return render_template('admin_verify.html',csrf=token,error=error)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options','nosniff')
        response.headers.setdefault('X-Frame-Options','SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin')
        if request.path.startswith(('/admin','/client','/kiosk')):
            response.headers['Cache-Control']='no-store'
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers.setdefault('Strict-Transport-Security','max-age=31536000')
        return response
