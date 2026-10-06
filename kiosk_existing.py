"""Restricted existing-waiver lookup on staff-controlled kiosks."""
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from zoneinfo import ZoneInfo
from email_validator import validate_email, EmailNotValidError
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func


def register(app, db, Waiver, Participant, Account, Code, Custodian, active, clear_client, send_email):
    def digest(value):
        return hmac.new(str(app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()

    def check():
        item = active()
        if not item or item.phase not in ('signup', 'members'):
            abort(403)
        if not secrets.compare_digest(item.csrf, request.form.get('csrf_token', '')):
            abort(400)
        return item

    def valid(waiver):
        return waiver and not waiver.is_archived and waiver.status != 'Superseded' and waiver.expiry_date.date() >= datetime.now(ZoneInfo('Europe/London')).date()

    def people(waiver, email=None):
        originals = Participant.query.filter_by(waiver_id=waiver.id).all()
        transferred = Participant.query.join(Custodian, Custodian.participant_id == Participant.id).filter(Custodian.waiver_id == waiver.id).all()
        result = []
        for person in {p.id: p for p in originals + transferred}.values():
            custodian = db.session.get(Custodian, person.id)
            if (custodian.waiver_id if custodian else person.waiver_id) != waiver.id:
                continue
            if email and custodian:
                account = db.session.get(Account, custodian.client_id)
                if not account or account.email.casefold() != email:
                    continue
            result.append(person)
        return sorted(result, key=lambda p: (p.first_name, p.last_name))

    def clear_lookup():
        for key in ('kiosk_waivers', 'kiosk_email', 'kiosk_code', 'kiosk_lookup_expires', 'kiosk_selected_members', 'kiosk_existing_complete'):
            session.pop(key, None)

    def grant(item, waivers, email=None):
        clear_client()
        clear_lookup()
        session['kiosk_waivers'] = [waiver.id for waiver in waivers]
        session['kiosk_lookup_expires'] = (datetime.now() + timedelta(minutes=2)).timestamp()
        if email:
            session['kiosk_email'] = email
        item.phase = 'members'
        db.session.commit()

    def lookup_rate(item):
        now = datetime.now()
        ip = digest('kiosk:' + item.id + ':' + (request.remote_addr or 'unknown'))
        if Code.query.filter(Code.ip_hash == ip, Code.created_at > now - timedelta(minutes=1)).count() >= 10:
            flash('Please wait a minute before trying again, or ask staff for help.', 'error')
            return None
        db.session.add(Code(id=secrets.token_hex(24), email='kiosk-lookup@example.invalid', mode='kiosk_id',
            code_hash=digest(secrets.token_hex(24)), ip_hash=ip, created_at=now,
            expires_at=now + timedelta(minutes=1), consumed=True))
        db.session.commit()
        return ip

    @app.post('/kiosk/new-waiver')
    def kiosk_new_waiver():
        item = check()
        clear_client(); clear_lookup()
        item.phase = 'waiver'; db.session.commit()
        return redirect(url_for('kiosk_customer'))

    @app.post('/kiosk/lookup-id')
    def kiosk_lookup_id():
        item = check()
        if not lookup_rate(item):
            return redirect(url_for('kiosk_customer'))
        from record_ids import reference_record_id
        reference = request.form.get('reference', '').strip().upper()
        record_id = reference_record_id(reference, 'W') if len(reference) <= 100 else None
        waiver = db.session.get(Waiver, record_id) if record_id else Waiver.query.filter(func.upper(Waiver.waiver_reference) == reference).first() if len(reference) <= 100 else None
        if waiver and record_id and waiver.public_reference != reference:
            waiver = None
        if not valid(waiver) or not people(waiver):
            flash('We could not find a current waiver with members for that ID. Check your confirmation email, use email verification, or ask staff.', 'error')
            return redirect(url_for('kiosk_customer'))
        grant(item, [waiver])
        return redirect(url_for('kiosk_customer'))

    @app.post('/kiosk/email-code')
    def kiosk_email_code():
        item = check()
        ip = lookup_rate(item)
        if not ip:
            return redirect(url_for('kiosk_customer'))
        try:
            email = validate_email(request.form.get('email', '').strip(), check_deliverability=False).normalized.casefold()
        except EmailNotValidError:
            flash('Enter a valid email address.', 'error')
            return redirect(url_for('kiosk_customer'))
        now = datetime.now()
        if Code.query.filter(Code.email == email, Code.created_at > now - timedelta(seconds=60)).first() or Code.query.filter(Code.email == email, Code.created_at > now - timedelta(minutes=15)).count() >= 3:
            flash('Please wait before requesting another code. Check your inbox and spam folder.', 'error')
            return redirect(url_for('kiosk_customer'))
        raw = f'{secrets.randbelow(1000000):06d}'
        challenge_id = secrets.token_hex(24)
        clear_client(); clear_lookup()
        item.phase = 'signup'
        Code.query.filter_by(email=email, mode='kiosk', consumed=False).update({'consumed': True})
        challenge = Code(id=challenge_id, email=email, mode='kiosk', code_hash=digest(challenge_id + ':' + raw),
            ip_hash=ip, created_at=now, expires_at=now + timedelta(minutes=10))
        db.session.add(challenge); db.session.commit()
        if not send_email(email, 'Your CL Paints kiosk verification code', f'Your kiosk verification code is {raw}. It expires in 10 minutes. Enter it only on the CL Paints kiosk where you requested it.'):
            challenge.consumed = True; db.session.commit()
            flash('We could not send your code. Use your waiver ID or ask staff for help.', 'error')
        else:
            session['kiosk_code'] = challenge.id
        return redirect(url_for('kiosk_customer'))

    @app.post('/kiosk/verify-email')
    def kiosk_verify_email():
        item = check()
        challenge = db.session.get(Code, session.get('kiosk_code', ''))
        now = datetime.now()
        changed = Code.query.filter(Code.id == (challenge.id if challenge else ''), Code.mode == 'kiosk',
            Code.consumed.is_(False), Code.expires_at > now, Code.attempts < 5).update({'attempts': Code.attempts + 1}, synchronize_session=False)
        if not changed:
            flash('This code is unavailable. Request a new code or use your waiver ID.', 'error')
            session.pop('kiosk_code', None); db.session.commit()
            return redirect(url_for('kiosk_customer'))
        if not secrets.compare_digest(challenge.code_hash, digest(challenge.id + ':' + request.form.get('code', '').strip())):
            db.session.commit(); flash('That code is incorrect. Try again.', 'error')
            return redirect(url_for('kiosk_customer'))
        consumed = Code.query.filter_by(id=challenge.id, consumed=False).update({'consumed': True}, synchronize_session=False)
        db.session.commit()
        if not consumed:
            abort(409)
        email = challenge.email
        waivers = Waiver.query.filter(func.lower(func.trim(Waiver.responsible_email)) == email).all()
        account = Account.query.filter_by(email=email).first()
        if account:
            waivers += Waiver.query.join(Custodian, Custodian.waiver_id == Waiver.id).filter(Custodian.client_id == account.id).all()
        waivers = [w for w in {w.id:w for w in waivers}.values() if valid(w) and people(w, email)]
        if not waivers:
            clear_lookup(); flash('No current waiver members were found. Complete a waiver or ask staff.', 'error')
        else:
            grant(item, waivers, email)
        return redirect(url_for('kiosk_customer'))

    def member_page(item):
        if session.get('kiosk_lookup_expires', 0) <= datetime.now().timestamp():
            clear_lookup(); item.phase = 'signup'; db.session.commit()
            return redirect(url_for('kiosk_customer'))
        rows = []
        for waiver_id in session.get('kiosk_waivers', []):
            waiver = db.session.get(Waiver, waiver_id)
            if valid(waiver):
                rows.append(dict(reference=waiver.public_reference, members=people(waiver, session.get('kiosk_email'))))
        return render_template('kiosk_members.html', rows=rows, item=item)

    @app.post('/kiosk/confirm-members')
    def kiosk_confirm_members():
        item = check()
        if item.phase != 'members' or session.get('kiosk_lookup_expires', 0) <= datetime.now().timestamp():
            abort(403)
        candidates = {}
        for waiver_id in session.get('kiosk_waivers', []):
            waiver = db.session.get(Waiver, waiver_id)
            if valid(waiver):
                candidates.update({p.id:(p,waiver.id) for p in people(waiver, session.get('kiosk_email'))})
        try:
            ids = {int(value) for value in request.form.getlist('member_id')}
        except ValueError:
            abort(400)
        if not ids or not ids.issubset(candidates):
            abort(400)
        names = [candidates[index][0].first_name + ' ' + candidates[index][0].last_name for index in sorted(ids)]
        item.waiver_id = candidates[min(ids)][1]
        item.phase = 'complete'; item.completed_at = datetime.utcnow(); db.session.commit()
        clear_client(); clear_lookup()
        session['kiosk_existing_complete'] = True
        session['kiosk_selected_members'] = names
        return redirect(url_for('kiosk_customer'))

    @app.post('/kiosk/start-over')
    def kiosk_start_over():
        item = active()
        if not item or not secrets.compare_digest(item.csrf, request.form.get('csrf_token', '')):
            abort(400)
        clear_client(); clear_lookup()
        item.phase = 'signup'; item.waiver_id = None; item.completed_at = None; db.session.commit()
        return redirect(url_for('kiosk_customer'))

    return member_page, clear_lookup
