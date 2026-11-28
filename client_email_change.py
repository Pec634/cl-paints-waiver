"""Verified changes of the email used to sign in to a client account."""
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets

from email_validator import EmailNotValidError, validate_email
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class ClientEmailChange(db.Model):
        id = db.Column(db.String(64), primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False, index=True)
        old_email = db.Column(db.String(255), nullable=False)
        new_email = db.Column(db.String(255), nullable=False)
        old_hash = db.Column(db.String(64), nullable=False)
        new_hash = db.Column(db.String(64), nullable=False)
        requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        completed_at = db.Column(db.DateTime)
        attempts = db.Column(db.Integer, nullable=False, default=0)
        active = db.Column(db.Boolean, nullable=False, default=True)
    return ClientEmailChange


def waiver_owner_filter(db, Waiver, account):
    return db.or_(Waiver.responsible_account_id == account.id,
        db.and_(Waiver.responsible_account_id.is_(None),
               db.func.lower(db.func.trim(Waiver.responsible_email)) == account.email.strip().casefold()))


def register(app, db, Change, Account, Code, Waiver, email_records, current_client, send_email):
    def digest(change_id, purpose, code):
        return hmac.new(str(app.secret_key).encode(), f'{change_id}:{purpose}:{code}'.encode(), hashlib.sha256).hexdigest()

    def matching(column, email):
        return db.func.lower(db.func.trim(column)) == email

    def address_in_use(email):
        return (Account.query.filter(matching(Account.email, email)).first() is not None
                or Waiver.query.filter(Waiver.responsible_account_id.is_(None),
                                        matching(Waiver.responsible_email, email)).first() is not None
                or any(Model.query.filter(matching(column, email)).first() is not None
                       for Model, column in email_records))

    @app.route('/client/account/email', methods=['GET', 'POST'])
    def client_change_email():
        account = current_client()
        if not account:
            return redirect(url_for('client.login'))
        now = datetime.utcnow()
        change = Change.query.filter_by(id=session.get('client_email_change'), client_id=account.id, active=True).first()
        if change and change.requested_at <= now - timedelta(minutes=10):
            change = None
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(csrf.encode(), request.form.get('csrf_token', '').encode()):
                abort(400)
            action = request.form.get('action')
            if action == 'start':
                try:
                    email = validate_email(request.form.get('new_email', '').strip(), check_deliverability=False).normalized.casefold()
                    if email == account.email or address_in_use(email):
                        raise ValueError('Use a different address that is available for this account.')
                    recent = Change.query.filter(Change.client_id == account.id, Change.requested_at > now - timedelta(hours=1)).count()
                    if recent >= 3:
                        raise ValueError('You’ve requested several changes. Try again in an hour.')
                    old_code, new_code = (f'{secrets.randbelow(1_000_000):06d}' for _ in range(2))
                    request_id = secrets.token_urlsafe(32)
                    Change.query.filter_by(client_id=account.id, active=True).update({'active': False})
                    change = Change(id=request_id, client_id=account.id, old_email=account.email, new_email=email,
                        old_hash=digest(request_id, 'old', old_code), new_hash=digest(request_id, 'new', new_code))
                    db.session.add(change)
                    db.session.commit()
                    if not all([
                        send_email(change.old_email, 'Confirm the change of your CL Paints email',
                                   f'Your current-address code is {old_code}. It expires in 10 minutes. If this was not you, ignore this message.'),
                        send_email(change.new_email, 'Verify your new CL Paints email',
                                   f'Your new-address code is {new_code}. It expires in 10 minutes.'),
                    ]):
                        change.active = False
                        db.session.commit()
                        change = None
                        raise ValueError('Both verification emails are needed. Try again later.')
                    session['client_email_change'] = request_id
                    return redirect(url_for('client_change_email'))
                except (ValueError, EmailNotValidError) as problem:
                    error = str(problem)
            elif action == 'confirm' and change:
                if Change.query.filter(Change.id == change.id, Change.active.is_(True), Change.attempts < 5,
                        Change.requested_at > now - timedelta(minutes=10)).update(
                        {Change.attempts: Change.attempts + 1}, synchronize_session=False) != 1:
                    db.session.rollback()
                    error = 'This request is unavailable. Request new codes.'
                    change = None
                else:
                    old_match = secrets.compare_digest(change.old_hash, digest(change.id, 'old', request.form.get('old_code', '').strip()))
                    new_match = secrets.compare_digest(change.new_hash, digest(change.id, 'new', request.form.get('new_code', '').strip()))
                    if not (old_match and new_match):
                        db.session.commit()
                        error = 'Check the codes from both inboxes and try again.'
                    else:
                        account = Account.query.filter_by(id=account.id).populate_existing().with_for_update().first()
                        if not account or account.email != change.old_email or address_in_use(change.new_email):
                            db.session.rollback()
                            error = 'This address is no longer available for the change.'
                        else:
                            try:
                                Waiver.query.filter(Waiver.responsible_account_id.is_(None),
                                    matching(Waiver.responsible_email, change.old_email)).update(
                                    {Waiver.responsible_account_id: account.id}, synchronize_session=False)
                                for Model, column in email_records:
                                    Model.query.filter(matching(column, change.old_email)).update(
                                        {column: change.new_email}, synchronize_session=False)
                                Code.query.filter(Code.email.in_((change.old_email, change.new_email))).update(
                                    {'consumed': True}, synchronize_session=False)
                                now = datetime.utcnow()
                                account.email, account.email_changed_at = change.new_email, now
                                change.active, change.completed_at = False, now
                                db.session.commit()
                            except IntegrityError:
                                db.session.rollback()
                                error = 'This address is no longer available for the change.'
                            else:
                                send_email(change.old_email, 'Your CL Paints login email changed',
                                           'Your CL Paints sign-in email was changed. Contact CL Paints if you did not make this change.')
                                for key in ('client_id', 'client_signed_in', 'client_remember', 'client_csrf',
                                            'client_challenge', 'client_pending_remember', 'client_email_change'):
                                    session.pop(key, None)
                                flash('Email changed. Sign in with your new email address.', 'success')
                                return redirect(url_for('client.login'))
            elif action != 'confirm':
                abort(400)
            else:
                error = 'This request expired. Request new codes.'
        response = app.make_response(render_template('client/change_email.html', client_account=account, client_csrf=csrf,
                                                    change=change, error=error))
        response.cache_control.no_store = True
        return response
