"""Private booking conversations and dashboard next steps."""
from datetime import datetime, timedelta
import secrets
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class BookingMessage(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        sender = db.Column(db.String(10), nullable=False)
        body = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        read_at = db.Column(db.DateTime)
        submission_key = db.Column(db.String(64), unique=True, nullable=False)
    return BookingMessage


def register(app, db, Message, Booking, Change, current_client, admin_required):
    signer = URLSafeTimedSerializer(app.secret_key, salt='booking-message')

    def unread(role, ids=None):
        query = Message.query.filter(Message.sender != role, Message.read_at.is_(None))
        if ids is not None:
            query = query.filter(Message.booking_id.in_(ids))
        return query

    def thread(booking, role, account=None):
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        endpoint = 'admin_booking_messages' if role == 'admin' else 'client_booking_messages'
        target = url_for(endpoint, booking_id=booking.id)
        if request.method == 'POST':
            if not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
                abort(400)
            try:
                submission = signer.loads(request.form.get('message_token', ''), max_age=86400)
                if submission['booking'] != booking.id or submission['role'] != role or submission['csrf'] != csrf:
                    abort(400)
            except (BadSignature, KeyError, TypeError):
                abort(400)
            if Message.query.filter_by(submission_key=submission['key']).first():
                return redirect(target)
            body = request.form.get('body', '').strip()
            if not body or len(body) > 4000:
                flash('Enter a message of up to 4,000 characters.', 'error')
            else:
                db.session.add(Message(booking_id=booking.id, sender=role, body=body,
                                       submission_key=submission['key']))
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                flash('Message saved in this booking conversation.', 'success')
                return redirect(target)
        query = Message.query.filter_by(booking_id=booking.id)
        before = request.args.get('before', type=int)
        if before:
            query = query.filter(Message.id < before)
        recent = query.order_by(Message.id.desc()).limit(101).all()
        older = len(recent) > 100
        messages = list(reversed(recent[:100]))
        now = datetime.utcnow()
        for message in messages:
            if message.sender != role and message.read_at is None:
                message.read_at = now
        db.session.commit()
        token = signer.dumps(dict(booking=booking.id, role=role, csrf=csrf, key=secrets.token_hex(32)))
        response = app.make_response(render_template('booking_messages.html', booking=booking,
            messages=messages, older=older, thread_url=target, is_admin=role == 'admin',
            client_account=account, client_csrf=csrf, message_token=token))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/client/bookings/<int:booking_id>/messages', methods=['GET', 'POST'])
    def client_booking_messages(booking_id):
        account = current_client()
        if not account:
            return redirect(url_for('client.login'))
        booking = Booking.query.filter(Booking.id == booking_id,
            func.lower(Booking.email) == account.email).first_or_404()
        return thread(booking, 'client', account)

    @app.route('/admin/bookings/<int:booking_id>/messages', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_messages(booking_id):
        return thread(db.get_or_404(Booking, booking_id), 'admin')

    @app.context_processor
    def next_steps():
        endpoint = request.endpoint
        if endpoint not in ('admin_dashboard', 'admin_bookings', 'client.dashboard', 'client.booking_detail', 'admin_notification_centre', 'client_notification_centre'):
            return {}
        admin = endpoint in ('admin_dashboard', 'admin_bookings', 'admin_notification_centre')
        account = None if admin else current_client()
        if (admin and not session.get('admin_authenticated')) or (not admin and not account):
            return {}
        bookings = Booking.query
        if not admin:
            bookings = bookings.filter(func.lower(Booking.email) == account.email)
        bookings = bookings.order_by(Booking.submitted_at.desc()).all()
        lookup = {b.id: b for b in bookings}
        counts = dict(unread('admin' if admin else 'client', list(lookup)).with_entities(
            Message.booking_id, func.count(Message.id)).group_by(Message.booking_id).all())
        context = dict(booking_message_counts=counts)
        if endpoint not in ('admin_dashboard', 'client.dashboard', 'admin_notification_centre', 'client_notification_centre'):
            return context
        rows = []
        for booking_id, count in counts.items():
            booking = lookup[booking_id]
            rows.append(dict(label=f'{count} unread booking message' + ('s' if count != 1 else ''),
                detail=booking.public_reference, link=url_for('admin_booking_messages' if admin else
                    'client_booking_messages', booking_id=booking_id)))
        if admin:
            for item in Change.query.filter_by(status='Pending').order_by(Change.created_at).all():
                rows.append(dict(label=f'Review {item.kind} request', detail=f'Booking #{item.booking_id}',
                    link=url_for('admin_booking_request', request_id=item.id)))
        elif not account.phone or not account.address:
            rows.append(dict(label='Complete your contact details', detail='Add a phone number and address.',
                             link=url_for('client.account')))
        lifecycle = app.extensions.get('booking_lifecycle')
        FollowUp = None
        if lifecycle:
            _, Proposal, FollowUp = lifecycle['models']
            if not admin:
                for proposal in Proposal.query.filter(Proposal.booking_id.in_(list(lookup)), Proposal.status == 'Pending').order_by(Proposal.created_at).all():
                    if proposal.display_status == 'Pending':
                        rows.append(dict(label='Review a replacement date', detail=lookup[proposal.booking_id].public_reference,
                            link=url_for('client.booking_detail', booking_id=proposal.booking_id) + '#date-proposals'))
                for followup in FollowUp.query.filter(FollowUp.booking_id.in_(list(lookup)), FollowUp.requested_at.isnot(None), FollowUp.responded_at.is_(None)).all():
                    rows.append(dict(label='Share event feedback', detail=lookup[followup.booking_id].public_reference,
                        link=url_for('client_booking_feedback', booking_id=followup.booking_id)))
                BookingChange = app.extensions['portal_booking_change_model']
                for change in BookingChange.query.filter(BookingChange.booking_id.in_(list(lookup)), BookingChange.acknowledged_at.is_(None)).order_by(BookingChange.created_at).all():
                    if not any(r.get('change_booking') == change.booking_id for r in rows):
                        rows.append(dict(label='Review updated booking details', detail=lookup[change.booking_id].public_reference,
                            link=url_for('client.booking_detail', booking_id=change.booking_id), change_booking=change.booking_id))
        today = datetime.now(ZoneInfo('Europe/London')).date()
        for booking in bookings:
            if booking.status != 'Accepted':
                continue
            payment = app.extensions['payment_summary'](booking)
            deposit_remaining = min(payment['outstanding'], max(0, payment['deposit'] - payment['paid']))
            due = None
            if deposit_remaining and payment['deposit_due'] and payment['deposit_due'] <= today:
                due = ('Deposit due', deposit_remaining)
            elif payment['outstanding'] and payment['balance_due'] and payment['balance_due'] <= today:
                due = ('Balance due', payment['outstanding'])
            if due:
                rows.append(dict(label=due[0], detail=f'{booking.public_reference} · £{due[1]:.2f}',
                    link=url_for('admin_payments' if admin else 'client.booking_detail', booking_id=booking.id)))
        approaching = []
        for booking in bookings:
            if booking.status != 'Accepted' or (FollowUp and db.session.get(FollowUp, booking.id)):
                continue
            for item in app.extensions['booking_schedule'](booking):
                try:
                    day = datetime.fromisoformat(item['date']).date()
                except (ValueError, KeyError, TypeError):
                    continue
                if today <= day <= today + timedelta(days=7):
                    approaching.append((day, booking, item))
        for day, booking, item in sorted(approaching, key=lambda row: (row[0], row[2].get('start_time', ''))):
            rows.append(dict(label='Prepare for an approaching event', detail=f'{booking.public_reference} · {day:%d/%m/%Y} · {item.get("start_time", "")}',
                link=url_for('admin_booking_activity' if admin else 'client.booking_detail', booking_id=booking.id)))
        context.update(portal_next_steps=rows[:8], portal_next_steps_total=len(rows))
        return context
