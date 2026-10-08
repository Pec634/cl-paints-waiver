"""Opt-in Web Push subscriptions and a transactional delivery queue."""
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import click
from flask import abort, jsonify, request, session, has_request_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

CATEGORIES = ('bookings', 'messages', 'payments', 'updates')
# Never send requests to arbitrary URLs supplied by a browser.
PUSH_HOSTS = ('fcm.googleapis.com', 'updates.push.services.mozilla.com',
              'web.push.apple.com', 'notify.windows.com')

def define_models(db):
    class PhoneSubscription(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        owner = db.Column(db.String(320), nullable=False, index=True)
        endpoint_hash = db.Column(db.String(64), unique=True, nullable=False)
        subscription = db.Column(db.Text, nullable=False)
        preferences = db.Column(db.Text, nullable=False)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
    class PhoneDelivery(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        subscription_id = db.Column(db.Integer, db.ForeignKey('phone_subscription.id'), nullable=False)
        category = db.Column(db.String(20), nullable=False)
        payload = db.Column(db.Text, nullable=False)
        attempts = db.Column(db.Integer, nullable=False, default=0)
        due_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    return PhoneSubscription, PhoneDelivery

def valid_subscription(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid browser subscription.')
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError('Invalid push endpoint.')
    parts = urlsplit(endpoint)
    host = parts.hostname or ''
    if (parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None,443)
            or parts.fragment or not any(host == allowed or
            (allowed in ('web.push.apple.com','notify.windows.com') and host.endswith('.'+allowed)) for allowed in PUSH_HOSTS)):
        raise ValueError('Unsupported push provider. Use Safari, Chrome, Edge or Firefox.')
    keys = value.get('keys', {})
    for key, length in [('p256dh',65), ('auth',16)]:
        raw = keys.get(key, '') if isinstance(keys,dict) else ''
        try:
            decoded = base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True)
        except (ValueError, TypeError):
            raise ValueError('Invalid browser subscription keys.') from None
        if len(decoded) != length or (key == 'p256dh' and decoded[0] != 4):
            raise ValueError('Invalid browser subscription keys.')
    return {'endpoint': endpoint, 'keys': {key: keys[key] for key in ('p256dh','auth')}}

def register(app, db, models, Booking, current_client, admin_required):
    Subscription, Delivery = models
    def config(key):
        return app.config.get(key) or os.getenv(key, '')
    def ready():
        return all(config(key) for key in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'))
    def owner(role):
        if role == 'admin':
            return 'admin'
        account = current_client()
        if not account:
            abort(401)
        return 'client:' + account.email.strip().casefold()
    @app.after_request
    def private_api(response):
        if request.path in ('/admin/phone-notifications','/client/phone-notifications'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response
    def api(role):
        who = owner(role)
        if request.method == 'GET':
            session.setdefault('client_csrf', secrets.token_urlsafe(32))
            digest = hashlib.sha256(request.args.get('endpoint','').encode()).hexdigest()
            saved = Subscription.query.filter_by(owner=who,endpoint_hash=digest,enabled=True).first()
            return jsonify(ready=ready(), public_key=config('VAPID_PUBLIC_KEY'), csrf=session['client_csrf'],
                           preferences=json.loads(saved.preferences) if saved else None)
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.headers.get('X-CSRF-Token','')):
            abort(400)
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict):
            abort(400)
        try:
            sub = valid_subscription(data.get('subscription'))
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        digest = hashlib.sha256(sub['endpoint'].encode()).hexdigest()
        saved = Subscription.query.filter_by(endpoint_hash=digest).first()
        if request.method == 'DELETE':
            if saved and saved.owner == who:
                saved.enabled = False
                Delivery.query.filter_by(subscription_id=saved.id).delete()
                db.session.commit()
            return jsonify(ok=True)
        if not ready():
            return jsonify(error='Phone notifications have not been configured on the server yet.'),503
        prefs = data.get('preferences')
        if not isinstance(prefs,list) or any(key not in CATEGORIES for key in prefs):
            return jsonify(error='Choose valid notification categories.'),400
        if saved and saved.owner != who:
            # A shared device explicitly registering under another signed-in account.
            Delivery.query.filter_by(subscription_id=saved.id).delete()
        if saved is None:
            if Subscription.query.filter_by(owner=who,enabled=True).count() >= 10:
                return jsonify(error='This account already has ten notification devices enabled.'),400
            saved = Subscription(endpoint_hash=digest)
            db.session.add(saved)
        saved.owner, saved.subscription, saved.preferences, saved.enabled = who,json.dumps(sub),json.dumps(prefs),True
        db.session.commit()
        return jsonify(ok=True)
    @app.route('/admin/phone-notifications',methods=['GET','POST','DELETE'])
    @admin_required
    def admin_phone_notifications():
        return api('admin')
    @app.route('/client/phone-notifications',methods=['GET','POST','DELETE'])
    def client_phone_notifications():
        return api('client')
    @app.get('/phone-push-worker.js')
    def phone_push_worker():
        response = app.send_static_file('phone-push-worker.js')
        response.headers['Cache-Control'] = 'no-cache'
        return response
    @app.get('/portal.webmanifest')
    def phone_manifest():
        return jsonify(name='CL Paints portal',short_name='CL Paints',start_url='/client/',
                       display='standalone',icons=[dict(src='/static/cl-paints-logo.jpg',sizes='any',type='image/jpeg')])

    def queue(who,category,title,path):
        for sub in Subscription.query.filter_by(owner=who,enabled=True).all():
            if category in json.loads(sub.preferences):
                db.session.add(Delivery(subscription_id=sub.id,category=category,
                    payload=json.dumps(dict(title=title,body='Open your portal to view the details.',url=path))))

    @event.listens_for(Session, 'after_flush')
    def capture(saved_session, context):
        if saved_session is not db.session() or (has_request_context() and request.path.startswith('/admin/imports')):
            return
        for obj in list(saved_session.new) + list(saved_session.dirty):
            name = type(obj).__name__
            new = obj in saved_session.new
            def changed(key):
                return key in inspect(obj).attrs and inspect(obj).attrs[key].history.has_changes()
            category,title,audience = None,None,None
            booking = obj if name == 'Booking' else None
            if name == 'Booking' and new:
                category,title,audience='bookings','New booking request','admin'
                queue('client:'+obj.email.strip().casefold(),'bookings','Your booking request was received',f'/client/bookings/{obj.id}')
            elif name == 'BookingMessage' and new:
                category,title,audience='messages','New booking message',('client' if obj.sender == 'admin' else 'admin')
            elif name == 'BookingChange' and new:
                category,title,audience='bookings','Your booking has been updated','client'
            elif name == 'BookingRequest' and (new or changed('status')):
                category,title,audience='bookings','Booking change request' if new else 'Booking request reviewed','admin' if new else 'client'
            elif name == 'BookingDateProposal' and (new or changed('status')):
                category,title,audience='bookings','New proposed booking date' if new else 'Booking date proposal updated','client' if new else 'both'
            elif name == 'PaymentEntry' and new:
                category,title,audience='payments','Booking payment record updated','both'
            elif name == 'BookingInvoice' and (new or changed('status')):
                category,title,audience='payments','Booking invoice updated','client'
            elif name == 'ClientNotification' and new and obj.kind != 'booking':
                queue('client:'+obj.email.strip().casefold(),'updates','Rewards update','/client/notifications')
            elif name == 'BookingFollowUp' and (changed('requested_at') or changed('responded_at')):
                category,title,audience='updates','Event feedback update','both'
            elif name == 'ClientEnquiry' and new:
                queue('admin','updates','New client enquiry','/admin/notifications')
            if not category:
                continue
            booking = booking or saved_session.get(Booking,getattr(obj,'booking_id',None))
            if audience in ('admin','both'):
                queue('admin',category,title,'/admin/notifications')
            if booking and audience in ('client','both'):
                queue('client:'+booking.email.strip().casefold(),category,title,f'/client/bookings/{booking.id}')

    def deliver():
        from pywebpush import webpush, WebPushException
        if not ready():
            raise click.ClickException('Configure VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT first.')
        now = datetime.utcnow()
        for delivery in Delivery.query.filter(Delivery.due_at <= now).order_by(Delivery.id).limit(50).all():
            sub = db.session.get(Subscription,delivery.subscription_id)
            if not sub or not sub.enabled or delivery.category not in json.loads(sub.preferences):
                db.session.delete(delivery); continue
            try:
                webpush(subscription_info=json.loads(sub.subscription),data=delivery.payload,
                    vapid_private_key=config('VAPID_PRIVATE_KEY'),vapid_claims={'sub':config('VAPID_SUBJECT')},
                    ttl=3600,timeout=10)
                db.session.delete(delivery)
            except WebPushException as exc:
                code = getattr(getattr(exc,'response',None),'status_code',None)
                if code in (404,410):
                    sub.enabled=False
                    Delivery.query.filter_by(subscription_id=sub.id).delete(synchronize_session=False)
                else:
                    delivery.attempts += 1
                    if delivery.attempts >= 5:
                        db.session.delete(delivery)
                    else:
                        delivery.due_at=now+timedelta(seconds=30*2**delivery.attempts)
                    app.logger.warning('Push delivery failed (status %s); booking remains saved.',code)
            except Exception:
                delivery.attempts += 1
                if delivery.attempts >= 5: db.session.delete(delivery)
                else: delivery.due_at=now+timedelta(minutes=5)
                app.logger.warning('Push provider unavailable; booking remains saved.')
        db.session.commit()
    @app.cli.command('push-worker')
    @click.option('--once',is_flag=True,help='Send one batch and exit.')
    def worker(once):
        """Run ONE delivery worker alongside the web server."""
        while True:
            deliver()
            if once: break
            db.session.remove()
            time.sleep(5)
    @app.cli.command('push-keys')
    def keys():
        """Generate persistent keys in the ignored instance directory (never overwrite)."""
        from pathlib import Path
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        directory = Path(app.instance_path)
        directory.mkdir(parents=True,exist_ok=True)
        private_path,public_path = directory/'push-private.pem',directory/'push-public.txt'
        if private_path.exists() or public_path.exists():
            raise click.ClickException('Push keys already exist. Keep them stable for existing subscriptions.')
        key = ec.generate_private_key(ec.SECP256R1())
        with private_path.open('xb') as output:
            output.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        public = key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        public_path.write_text(base64.urlsafe_b64encode(public).decode().rstrip('='),encoding='ascii')
        click.echo('Saved push-private.pem and push-public.txt in instance/. Configure VAPID settings using these files; keep the private key secret.')
    app.extensions['phone_push_deliver'] = deliver
