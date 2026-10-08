"""Notification centres, admin search and recovery screens."""
from datetime import datetime
from functools import wraps
import re
import secrets

from flask import abort, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy import or_
from werkzeug.exceptions import HTTPException


def define_model(db):
    class PortalRead(db.Model):
        owner = db.Column(db.String(60), primary_key=True)
        seen_at = db.Column(db.DateTime, nullable=False)
    return PortalRead


def register(app, db, Read, Booking, Account, Waiver, Message, Request, Change, Notice,
             Entry, Form, Submission, lifecycle, current_client, admin_required, Enquiry, Workflow, Invoice):
    _, Proposal, FollowUp = lifecycle
    signer = URLSafeTimedSerializer(app.secret_key, salt='portal-notifications')

    def client_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            account = current_client()
            if not account:
                return redirect(url_for('client.login'))
            return view(account, *args, **kwargs)
        return wrapped

    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))

    def centre(admin, account=None):
        key = 'admin' if admin else f'client:{account.id}'
        marker = db.session.get(Read, key)
        if request.method == 'POST':
            if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
                abort(400)
            try:
                token = signer.loads(request.form.get('read_token', ''), max_age=86400)
                if token['owner'] != key or token['csrf'] != csrf():
                    abort(400)
                cutoff = datetime.fromisoformat(token['at'])
            except (BadSignature, KeyError, TypeError, ValueError):
                abort(400)
            if marker:
                marker.seen_at = max(marker.seen_at, cutoff)
            else:
                db.session.add(Read(owner=key, seen_at=cutoff))
            if account:
                latest = Notice.query.filter(db.func.lower(Notice.email) == account.email,
                    Notice.created_at <= cutoff).order_by(Notice.id.desc()).first()
                if latest:
                    OldRead = app.extensions['notification_read_model']
                    old = db.session.get(OldRead, account.id)
                    if old:
                        old.last_notice_id = max(old.last_notice_id, latest.id)
                    else:
                        db.session.add(OldRead(client_id=account.id, last_notice_id=latest.id))
            db.session.commit()
            return redirect(url_for('admin_notification_centre' if admin else 'client_notification_centre'))
        bookings = Booking.query
        if account:
            bookings = bookings.filter(db.func.lower(Booking.email) == account.email)
        lookup = {b.id: b for b in bookings.all()}
        ids = list(lookup)
        rows = []

        def add(at, category, title, detail, link, action=False):
            rows.append(dict(at=at, category=category, title=title, detail=detail, link=link,
                             action=action, new=marker is None or at > marker.seen_at))

        def booking_link(booking_id):
            return url_for('admin_booking_activity' if admin else 'client.booking_detail', booking_id=booking_id)

        for booking in sorted(lookup.values(), key=lambda b: b.submitted_at, reverse=True)[:50]:
            add(booking.submitted_at, 'bookings', 'Booking request received', booking.public_reference + ' · ' + booking.status,
                url_for('admin_bookings') + f'#booking-{booking.id}' if admin else booking_link(booking.id), admin and booking.status == 'Under Review')
        for message in Message.query.filter(Message.booking_id.in_(ids), Message.sender == ('client' if admin else 'admin')).order_by(Message.id.desc()).limit(50).all():
            add(message.created_at, 'messages', 'Booking message', lookup[message.booking_id].public_reference + ' · ' + message.body[:180],
                url_for('admin_booking_messages' if admin else 'client_booking_messages', booking_id=message.booking_id), message.read_at is None)
        enquiries = Enquiry.query
        if account:
            enquiries = enquiries.filter_by(client_id=account.id)
        linked_enquiries = db.session.query(Request.enquiry_id)
        for enquiry in enquiries.filter(~Enquiry.id.in_(linked_enquiries)).order_by(Enquiry.id.desc()).limit(50).all():
            workflow = db.session.get(Workflow, enquiry.id)
            status = workflow.status if workflow else 'new'
            add(workflow.updated_at if workflow else enquiry.created_at, 'messages', 'General enquiry · ' + status,
                enquiry.subject + ' · ' + (workflow.reply if account and workflow and workflow.reply else enquiry.message[:180]),
                url_for('admin_clients') + f'#enquiry-{enquiry.id}' if admin else url_for('client.contact'), admin and status == 'new')
        for change in Change.query.filter(Change.booking_id.in_(ids)).order_by(Change.id.desc()).limit(50).all():
            add(change.created_at, 'updates', 'Booking details updated', lookup[change.booking_id].public_reference + ' · ' + ', '.join(sorted(change.changes)),
                booking_link(change.booking_id), not admin and change.acknowledged_at is None)
        for entry in Entry.query.filter(Entry.booking_id.in_(ids)).order_by(Entry.id.desc()).limit(50).all():
            add(entry.recorded_at, 'payments', entry.kind.capitalize() + ' recorded',
                f'{lookup[entry.booking_id].public_reference} · £{entry.amount:.2f} · {entry.method}', booking_link(entry.booking_id))
        for item in Request.query.filter(Request.booking_id.in_(ids)).order_by(Request.id.desc()).limit(50).all():
            add(item.reviewed_at or item.created_at, 'bookings', item.kind.capitalize() + ' request · ' + item.status,
                lookup[item.booking_id].public_reference, url_for('admin_booking_request', request_id=item.id) if admin else booking_link(item.booking_id),
                admin and item.status == 'Pending')
        for proposal in Proposal.query.filter(Proposal.booking_id.in_(ids)).order_by(Proposal.id.desc()).limit(50).all():
            add(proposal.decided_at or proposal.created_at, 'bookings', 'Date proposal · ' + proposal.display_status,
                f'{lookup[proposal.booking_id].public_reference} · {proposal.starts_at:%d/%m/%Y %H:%M} UK time', booking_link(proposal.booking_id),
                not admin and proposal.display_status == 'Pending')
        for followup in FollowUp.query.filter(FollowUp.booking_id.in_(ids)).order_by(FollowUp.completed_at.desc()).limit(50).all():
            if followup.responded_at:
                add(followup.responded_at, 'updates', 'Feedback received', f'{lookup[followup.booking_id].public_reference} · {followup.rating}/5', booking_link(followup.booking_id))
            elif followup.requested_at:
                add(followup.requested_at, 'updates', 'Share event feedback', lookup[followup.booking_id].public_reference,
                    booking_link(followup.booking_id) if admin else url_for('client_booking_feedback', booking_id=followup.booking_id), not admin)
        if account:
            for notice in Notice.query.filter(db.func.lower(Notice.email) == account.email, Notice.kind != 'booking').order_by(Notice.id.desc()).limit(50).all():
                add(notice.created_at, 'updates', notice.reference, notice.details, url_for('client.rewards'))
        else:
            for submission in Submission.query.order_by(Submission.id.desc()).limit(50).all():
                add(submission.created_at, 'updates', 'Form submission', f'#{submission.id} · {submission.title_snapshot} · {submission.name}',
                    url_for('native_form_entries', form_id=submission.form_id, submission=submission.id) + f'#submission-{submission.id}')
        selected = request.args.get('category', 'all')
        state = request.args.get('state', 'all')
        if selected not in ('all', 'bookings', 'messages', 'payments', 'updates') or state not in ('all', 'new', 'actions'):
            abort(400)
        counts = dict(new=sum(r['new'] for r in rows), actions=sum(r['action'] for r in rows))
        filtered = [r for r in rows if (selected == 'all' or r['category'] == selected)
                    and (state == 'all' or (state == 'new' and r['new']) or (state == 'actions' and r['action']))]
        filtered.sort(key=lambda r: r['at'], reverse=True)
        token = signer.dumps(dict(owner=key, csrf=csrf(), at=datetime.utcnow().isoformat()))
        response = app.make_response(render_template('portal_notifications.html', rows=filtered[:100], total=len(filtered),
            counts=counts, selected=selected, state=state, is_admin=admin, client_account=account,
            client_csrf=csrf(), read_token=token))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/admin/notifications', methods=['GET', 'POST'])
    @admin_required
    def admin_notification_centre():
        return centre(True)

    @app.route('/client/notifications', methods=['GET', 'POST'])
    @client_required
    def client_notification_centre(account):
        return centre(False, account)

    @app.get('/client/payments')
    @client_required
    def client_payments(account):
        bookings = Booking.query.filter(db.func.lower(Booking.email) == account.email).order_by(Booking.submitted_at.desc()).all()
        rows = [dict(booking=b, payment=app.extensions['payment_summary'](b),
                     invoices=Invoice.query.filter_by(booking_id=b.id).order_by(Invoice.created_at.desc()).all()) for b in bookings]
        response = app.make_response(render_template('client/payments.html', rows=rows,
            client_account=account, client_csrf=csrf()))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/admin/search')
    @admin_required
    def admin_global_search():
        query = request.args.get('q', '').strip()
        if len(query) > 100:
            abort(400)
        groups = []
        if query:
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_').lower() + '%'
            match = re.search(r'(?:^|[-#\s])0*(\d+)$', query)
            number = int(match[1]) if match and len(match[1]) <= 10 else None
            account_query = re.fullmatch(r'CL-A-\d+',query,re.I) is not None

            def search(model, fields):
                expressions = [db.func.lower(field).like(pattern, escape='\\') for field in fields]
                if number is not None and (not account_query or model is Account):
                    expressions.append(model.id == number)
                return model.query.filter(or_(*expressions)).order_by(model.id.desc()).limit(20).all()

            groups.append(('Bookings', [dict(title=b.public_reference, detail=f'{b.first_name} {b.last_name} · {b.event_type} · {b.status}',
                link=url_for('admin_booking_activity', booking_id=b.id)) for b in search(Booking, [Booking.email, Booking.first_name + ' ' + Booking.last_name, Booking.phone, Booking.event_type, Booking.event_address])]))
            groups.append(('Clients', [dict(title=f'{a.first_name} {a.last_name}', detail=f'{a.account_number} · {a.email}',
                link=url_for('admin_client_profile',client_id=a.id)) for a in search(Account, [Account.first_name + ' ' + Account.last_name, Account.email, Account.phone])]))
            groups.append(('Waivers', [dict(title=w.waiver_reference, detail=f'{w.responsible_first_name} {w.responsible_last_name}',
                link=url_for('admin_waiver_detail', waiver_id=w.id)) for w in search(Waiver, [Waiver.waiver_reference, Waiver.responsible_first_name, Waiver.responsible_last_name, Waiver.responsible_email])]))
            groups.append(('Form submissions', [dict(title=f'#{s.id} · {s.title_snapshot}', detail=f'{s.name} · {s.email}',
                link=url_for('native_form_entries', form_id=s.form_id, submission=s.id) + f'#submission-{s.id}') for s in search(Submission, [Submission.title_snapshot, Submission.name, Submission.email])]))
            groups.append(('Forms', [dict(title=f.title, detail=f.kind, link=url_for('native_forms_admin', edit=f.id)) for f in search(Form, [Form.title, Form.description])]))
        response = app.make_response(render_template('admin_search.html', query=query, groups=groups))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.errorhandler(HTTPException)
    def recoverable_error(error):
        if request.path.startswith('/api/') or request.is_json or request.accept_mimetypes.best == 'application/json':
            return error.get_response()
        if error.code not in (400, 403, 404, 409, 413, 429, 500):
            return error.get_response()
        if error.code == 500:
            db.session.rollback()
        account = current_client() if error.code != 500 and request.path.startswith('/client/') else None
        admin = request.path.startswith('/admin/') and session.get('admin_authenticated')
        messages = {
            400: ('Please open a fresh form', 'This form may be out of date, or some information could not be accepted. Open the page again before retrying. Your last request may not have been saved.'),
            403: ('This page needs permission', 'Sign in with the account that owns this record, or contact CL Paints for help.'),
            404: ('We could not find that page', 'The link may have expired, or this record may belong to another account. Return to your portal to find the latest link.'),
            409: ('Something changed while you were editing', 'Open the latest version and review it before saving again.'),
            413: ('That upload is too large', 'Choose smaller files and try again. Check the size limits beside the upload field.'),
            429: ('Please wait before trying again', 'Too many requests arrived in a short time. Wait a little, then retry.'),
            500: ('We could not finish that request', 'Return to your portal and check whether your changes were saved before trying again.')}
        title, detail = messages[error.code]
        if error.code == 500:
            # A database failure must not trigger database-backed page context again.
            markup = app.jinja_env.get_template('portal_error.html').render(error_title=title,
                error_detail=detail, error_code=500, is_admin=False, client_account=None, client_csrf=csrf())
            response = app.make_response((markup, 500))
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        response = app.make_response((render_template('portal_error.html', error_title=title, error_detail=detail,
            error_code=error.code, is_admin=bool(admin), client_account=account, client_csrf=csrf()), error.code))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
