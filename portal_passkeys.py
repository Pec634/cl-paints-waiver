"""WebAuthn credentials for the three portal sign-in roles."""
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import json
import os
import secrets
from urllib.parse import urlsplit

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def define_models(db):
    class PortalPasskey(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        credential_id = db.Column(db.String(1400), nullable=False, unique=True)
        public_key = db.Column(db.LargeBinary, nullable=False)
        sign_count = db.Column(db.Integer, nullable=False)
        role = db.Column(db.String(10), nullable=False)
        principal_id = db.Column(db.Integer, nullable=False)
        name = db.Column(db.String(80), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    class PasskeyChallenge(db.Model):
        id = db.Column(db.String(64), primary_key=True)
        challenge = db.Column(db.LargeBinary, nullable=False)
        expires = db.Column(db.DateTime, nullable=False, index=True)
        role = db.Column(db.String(10), nullable=False)
        principal_id = db.Column(db.Integer)
        source = db.Column(db.String(64), nullable=False, index=True)

    return PortalPasskey, PasskeyChallenge


def register(app, db, Key, Challenge, Account, LoginEvent, Staff, current_client):
    from staff_permissions import permissions

    login_pages = {'client': 'client.login', 'staff': 'pos_staff_login', 'owner': 'admin_owner_login'}

    def configuration():
        try:
            parsed = urlsplit(os.getenv('PASSKEY_ORIGIN', '').strip())
            port = parsed.port
        except ValueError:
            return None
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname.lower()
        authority = f'[{host}]' if ':' in host else host
        if port not in (None, 443):
            authority = f'{authority}:{port}'
        return f'https://{authority}', host

    def principal(role, fresh=False):
        if role == 'client':
            account = current_client()
            identity, signed = (account.id if account else None), session.get('client_signed_in', 0)
        elif role == 'staff':
            staff = db.session.get(Staff, session.get('pos_staff_id') or 0)
            identity = staff.id if staff and staff.enabled else None
            signed = session.get('pos_signed_in_at', 0)
            now = datetime.utcnow().timestamp()
            if now - session.get('pos_last_activity', 0) > 1800 or now - signed > 28800:
                return None
        else:
            identity = 1 if session.get('admin_authenticated') and not session.get('pos_staff_id') else None
            signed = session.get('admin_signed_in_at', 0)
            if datetime.utcnow().timestamp() - session.get('admin_last_activity', 0) > 1800:
                return None
        clock = datetime.now() if role == 'client' else datetime.utcnow()
        return identity if not fresh or 0 <= clock.timestamp() - signed < 300 else None

    def csrf():
        return session.setdefault('passkey_csrf', secrets.token_urlsafe(32))

    def guard(view):
        @wraps(view)
        def protected(role, *args, **kwargs):
            if role not in login_pages or not configuration():
                abort(404)
            return view(role, *args, **kwargs)
        return protected

    @app.context_processor
    def passkey_context():
        configured = configuration()
        return {'passkeys_enabled': bool(configured and request.host == urlsplit(configured[0]).netloc)}

    @app.route('/account/passkeys/<role>', methods=['GET', 'POST'])
    @guard
    def portal_passkeys(role):
        identity = principal(role)
        if not identity:
            return redirect(url_for(login_pages[role]))
        keys = Key.query.filter_by(role=role, principal_id=identity)
        if request.method == 'POST':
            if not secrets.compare_digest(csrf().encode(), request.form.get('csrf_token', '').encode()):
                abort(400)
            if not principal(role, fresh=True):
                abort(403, 'Sign in again before removing a passkey.')
            key = keys.filter_by(id=request.form.get('key', type=int)).first_or_404()
            db.session.delete(key)
            db.session.commit()
            flash('Passkey removed.', 'success')
            return redirect(url_for('portal_passkeys', role=role))
        return render_template('passkeys.html', role=role, keys=keys.order_by(Key.id).all(), passkey_csrf=csrf(),
                               recent=bool(principal(role, fresh=True)))

    @app.post('/auth/passkeys/<role>/<operation>/<phase>')
    @guard
    def portal_passkey_ceremony(role, operation, phase):
        from webauthn import (base64url_to_bytes, generate_authentication_options, generate_registration_options,
                              options_to_json, verify_authentication_response, verify_registration_response)
        from webauthn.helpers import bytes_to_base64url
        from webauthn.helpers.exceptions import WebAuthnException
        from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                             ResidentKeyRequirement, UserVerificationRequirement)

        if operation not in ('signin', 'enrol') or phase not in ('start', 'finish'):
            abort(404)
        token = session.get('passkey_csrf', '')
        if not token or not secrets.compare_digest(token.encode(), request.headers.get('X-Passkey-CSRF', '').encode()):
            abort(400)
        origin, rp_id = configuration()
        if request.headers.get('Origin') != origin:
            abort(403)
        if request.content_length and request.content_length > 64_000:
            abort(413)
        identity = principal(role, fresh=True) if operation == 'enrol' else None
        if operation == 'enrol' and not identity:
            return jsonify(error='Sign in again before adding a passkey.'), 403
        now = datetime.utcnow()
        verification = UserVerificationRequirement.REQUIRED
        challenge_key = f'passkey:{role}:{operation}'
        handle = lambda identifier: f'{role}:{identifier}'.encode()
        if phase == 'start':
            source = hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
            if Challenge.query.filter(Challenge.source == source, Challenge.expires > now).count() >= 30:
                return jsonify(error='Too many passkey requests. Try again in two minutes.'), 429
            if identity:
                existing = Key.query.filter_by(role=role, principal_id=identity).all()
                if len(existing) >= 10:
                    return jsonify(error='Remove an old passkey before adding another.'), 409
                options = generate_registration_options(
                    rp_id=rp_id, rp_name='CL Paints', user_id=handle(identity),
                    user_name=f'CL Paints {role} {identity}',
                    exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id)) for key in existing],
                    authenticator_selection=AuthenticatorSelectionCriteria(
                        resident_key=ResidentKeyRequirement.REQUIRED, user_verification=verification))
            else:
                options = generate_authentication_options(rp_id=rp_id, user_verification=verification)
            Challenge.query.filter(Challenge.expires <= now).delete(synchronize_session=False)
            old = session.get(challenge_key)
            if old:
                Challenge.query.filter_by(id=old).delete(synchronize_session=False)
            row = Challenge(id=secrets.token_urlsafe(32), challenge=options.challenge,
                            expires=now + timedelta(minutes=2), role=role, principal_id=identity, source=source)
            db.session.add(row)
            db.session.commit()
            session[challenge_key] = row.id
            return jsonify(options=json.loads(options_to_json(options)))

        row = db.session.get(Challenge, session.pop(challenge_key, '') or '')
        if not row or row.expires <= now or row.role != role or row.principal_id != identity:
            return jsonify(error='Your request expired. Try again.'), 400
        challenge = row.challenge
        if Challenge.query.filter_by(id=row.id).delete(synchronize_session=False) != 1:
            db.session.rollback()
            return jsonify(error='Your request expired. Try again.'), 400
        db.session.commit()
        body = request.get_json(silent=True)
        try:
            credential = body['credential']
            if identity:
                result = verify_registration_response(credential=credential, expected_challenge=challenge,
                    expected_origin=origin, expected_rp_id=rp_id, require_user_verification=True)
                name = str(body.get('name') or 'Passkey').strip()[:80] or 'Passkey'
                db.session.add(Key(role=role, principal_id=identity, credential_id=bytes_to_base64url(result.credential_id),
                    public_key=result.credential_public_key, sign_count=result.sign_count, name=name))
                db.session.commit()
                return jsonify(next=url_for('portal_passkeys', role=role))
            key = Key.query.filter_by(role=role, credential_id=credential['id']).with_for_update().first()
            if not key or credential['response'].get('userHandle') != bytes_to_base64url(handle(key.principal_id)):
                raise ValueError()
            result = verify_authentication_response(credential=credential, expected_challenge=challenge,
                expected_origin=origin, expected_rp_id=rp_id, credential_public_key=key.public_key,
                credential_current_sign_count=key.sign_count, require_user_verification=True)
            account = db.session.get(Account, key.principal_id) if role == 'client' else None
            staff = db.session.get(Staff, key.principal_id) if role == 'staff' else None
            if (role == 'client' and not account) or (role == 'staff' and not (staff and staff.enabled)):
                raise ValueError()
            key.sign_count = result.new_sign_count
            if account:
                db.session.add(LoginEvent(client_id=account.id, method='passkey', remembered=False))
            db.session.commit()
        except (WebAuthnException, IntegrityError, KeyError, TypeError, ValueError, AttributeError):
            db.session.rollback()
            return jsonify(error='The passkey could not be verified. Try again or use your usual sign-in.'), 400

        if account:
            timestamp = datetime.now().timestamp()
            destination = url_for('client.dashboard')
            photo_id = session.pop('client_pending_participant_photo', None)
            scan = session.pop('loyalty_scan_token', None)
            form_id = session.pop('native_return_form', None)
            if scan:
                destination = url_for('loyalty.scan', token=scan)
            elif form_id:
                destination = url_for('native_form_open', form_id=form_id)
            elif type(photo_id) is int and photo_id > 0:
                destination = url_for('client_photos', participant_photo=photo_id)
            session.update(client_id=account.id, client_signed_in=timestamp, client_remember=False,
                           client_csrf=secrets.token_urlsafe(32))
            session.pop('client_challenge', None)
            session.permanent = False
        else:
            timestamp = datetime.utcnow().timestamp()
            session.clear()
            if staff:
                session.update(pos_staff_id=staff.id, pos_last_activity=timestamp, pos_signed_in_at=timestamp)
                destination = url_for('pos_home' if permissions(staff) == {'pos'} else 'staff_portal_home')
            else:
                session.update(admin_authenticated=True, admin_last_activity=timestamp, admin_signed_in_at=timestamp)
                destination = url_for('admin_dashboard')
        return jsonify(next=destination)

    @app.context_processor
    def passkey_options():
        return {'passkey_csrf_token': csrf} if configuration() else {}
