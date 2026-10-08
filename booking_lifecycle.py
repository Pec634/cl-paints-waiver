"""Booking audit history, agreed date changes and event follow-up."""
from datetime import datetime, timedelta
import hashlib
import json
import secrets
from zoneinfo import ZoneInfo

from flask import abort, flash, has_request_context, redirect, render_template, request, session, url_for
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError


def define_models(db):
    class BookingActivity(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        change_id = db.Column(db.Integer, db.ForeignKey('booking_change.id'), unique=True)
        change = db.relationship('BookingChange')
        actor = db.Column(db.String(255), nullable=False)
        role = db.Column(db.String(10), nullable=False)
        details = db.Column(db.Text, nullable=False, default='')
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    class BookingDateProposal(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        event_index = db.Column(db.Integer, nullable=False)
        starts_at = db.Column(db.DateTime, nullable=False)
        ends_at = db.Column(db.DateTime, nullable=False)
        original_hash = db.Column(db.String(64), nullable=False)
        reason = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(20), nullable=False, default='Pending')
        pending_key = db.Column(db.String(60), unique=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        expires_at = db.Column(db.DateTime, nullable=False)
        decided_at = db.Column(db.DateTime)
        proposed_by = db.Column(db.String(255), nullable=False)
        @property
        def display_status(self):
            return 'Expired' if self.status == 'Pending' and self.expires_at <= datetime.utcnow() else self.status
    class BookingFollowUp(db.Model):
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), primary_key=True)
        completed_at = db.Column(db.DateTime, nullable=False)
        completed_by = db.Column(db.String(255), nullable=False)
        requested_at = db.Column(db.DateTime)
        email_sent = db.Column(db.Boolean, nullable=False, default=False)
        rating = db.Column(db.Integer)
        feedback = db.Column(db.Text)
        responded_at = db.Column(db.DateTime)
    return BookingActivity, BookingDateProposal, BookingFollowUp


def register(app, db, models, Booking, Event, Change, Message, BookingRequest, Entry,
             current_client, admin_required, schedule, admin_email, send_email, settings):
    Activity, Proposal, FollowUp = models
    zone = ZoneInfo('Europe/London')

    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))

    def check():
        if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400)

    def actor():
        if has_request_context():
            if request.path.startswith('/admin') and session.get('admin_authenticated'):
                return admin_email or 'CL Paints admin', 'admin'
            account = current_client()
            if account:
                return account.email, 'client'
        return 'System', 'system'

    @event.listens_for(db.session.session_factory, 'before_flush')
    def audit(session_db, flush_context, instances):
        # Recorded in the same transaction as the change; rollback removes both.
        who, role = actor()
        for item in list(session_db.new):
            if isinstance(item, Change):
                session_db.add(Activity(booking_id=item.booking_id, change=item, actor=who, role=role))
        for booking in list(session_db.dirty):
            if not isinstance(booking, Booking):
                continue
            changes = {}
            for field in ('internal_notes', 'company_signature'):
                history = inspect(booking).attrs[field].history
                if history.has_changes():
                    changes[field.replace('_', ' ').capitalize()] = {
                        'before': history.deleted[0] if history.deleted else '',
                        'after': getattr(booking, field) or ''}
            if changes:
                session_db.add(Activity(booking_id=booking.id, actor=who, role=role,
                                        details=json.dumps(changes)))

    def owner(booking_id):
        account = current_client()
        if not account:
            return None, None
        booking = Booking.query.filter(Booking.id == booking_id,
            db.func.lower(Booking.email) == account.email).first_or_404()
        return account, booking

    def fingerprint(booking):
        return hashlib.sha256(json.dumps([booking.status, schedule(booking)], sort_keys=True).encode()).hexdigest()

    def interval(item):
        start = datetime.fromisoformat(item['date'] + 'T' + item['start_time'])
        end = datetime.fromisoformat(item['date'] + 'T' + item['finish_time'])
        if start.tzinfo or end.tzinfo or end <= start:
            raise ValueError('This event needs valid same-day start and finish times.')
        return start, end

    def available(booking, index, start, end):
        buffer = timedelta(minutes=int(settings()['calendar_buffer_minutes']))
        for row in app.extensions['calendar_rows']():
            if row['booking'] and row['booking'].id == booking.id and row['day'] == index + 1:
                continue
            if row['booking'] and row['booking'].status != 'Accepted':
                continue
            if start - buffer < row['occupied_end'] and row['occupied_start'] < end + buffer:
                return False
        return True

    def timeline(booking, admin=False):
        rows = [dict(at=booking.submitted_at, label='Booking request received', actor='Client', details='')]
        audits = {a.change_id: a for a in Activity.query.filter_by(booking_id=booking.id).all() if a.change_id}
        for change in Change.query.filter_by(booking_id=booking.id).all():
            audit = audits.get(change.id)
            who = audit.actor if admin and audit else ('You' if audit and audit.role == 'client' else 'CL Paints')
            rows.append(dict(at=change.created_at, label='Booking details updated', actor=who,
                details='\n'.join(f'{key}: {value["before"]} → {value["after"]}' for key, value in sorted(change.changes.items()))))
        if admin:
            for audit in Activity.query.filter_by(booking_id=booking.id, change_id=None).all():
                changes = json.loads(audit.details)
                rows.append(dict(at=audit.created_at, label='Internal booking details updated', actor=audit.actor,
                    details='\n'.join(f'{key}: {value["before"]} → {value["after"]}' for key, value in changes.items())))
        for message in Message.query.filter_by(booking_id=booking.id).all():
            rows.append(dict(at=message.created_at, label='Booking message', actor='CL Paints' if message.sender == 'admin' else 'Client',
                details=message.body[:250], link=url_for('admin_booking_messages' if admin else 'client_booking_messages', booking_id=booking.id)))
        for item in BookingRequest.query.filter_by(booking_id=booking.id).all():
            rows.append(dict(at=item.created_at, label=f'{item.kind.capitalize()} requested', actor='Client', details=item.details))
            if item.reviewed_at:
                rows.append(dict(at=item.reviewed_at, label=f'{item.kind.capitalize()} request {item.status.lower()}', actor='CL Paints', details=item.response))
        for entry in Entry.query.filter_by(booking_id=booking.id).all():
            rows.append(dict(at=entry.recorded_at, label=f'{entry.kind.capitalize()} recorded', actor='CL Paints',
                details=f'£{entry.amount:.2f} · {entry.method} · Payment date {entry.paid_date}'))
        for proposal in Proposal.query.filter_by(booking_id=booking.id).all():
            rows.append(dict(at=proposal.created_at, label='Replacement date proposed', actor=proposal.proposed_by if admin else 'CL Paints',
                details=f'Event day {proposal.event_index + 1}: {proposal.starts_at:%d/%m/%Y %H:%M} – {proposal.ends_at:%H:%M} · {proposal.reason}'))
            if proposal.decided_at:
                rows.append(dict(at=proposal.decided_at, label=f'Date proposal {proposal.status.lower()}', actor='Client' if proposal.status in ('Accepted', 'Declined') else 'CL Paints', details=''))
        followup = db.session.get(FollowUp, booking.id)
        if followup:
            rows.append(dict(at=followup.completed_at, label='Event completed', actor=followup.completed_by if admin else 'CL Paints', details=''))
            if followup.requested_at:
                rows.append(dict(at=followup.requested_at, label='Feedback requested', actor='CL Paints', details=''))
            if followup.responded_at:
                rows.append(dict(at=followup.responded_at, label='Feedback received', actor='Client', details=f'{followup.rating}/5 · {followup.feedback}'))
        return sorted(rows, key=lambda row: row['at'], reverse=True)

    @app.context_processor
    def booking_context():
        if request.endpoint != 'client.booking_detail':
            return {}
        account = current_client()
        booking = db.session.get(Booking, request.view_args['booking_id'])
        if not account or not booking or booking.email.casefold() != account.email:
            return {}
        return dict(booking_timeline=timeline(booking), date_proposals=Proposal.query.filter_by(booking_id=booking.id).order_by(Proposal.created_at.desc()).all(),
                    booking_followup=db.session.get(FollowUp, booking.id))

    @app.route('/admin/bookings/<int:booking_id>/activity', methods=['GET', 'POST'])
    @admin_required
    def admin_booking_activity(booking_id):
        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        events = schedule(booking)
        if request.method == 'POST':
            check()
            try:
                action = request.form.get('action')
                who, _ = actor()
                followup = db.session.get(FollowUp, booking.id)
                if action == 'propose':
                    if booking.status != 'Accepted' or followup:
                        raise ValueError('Choose a confirmed booking that has not been completed.')
                    index = int(request.form.get('event_index', ''))
                    if not 0 <= index < len(events):
                        raise ValueError('Choose an event day from this booking.')
                    old_start, old_end = interval(events[index])
                    start = datetime.fromisoformat(request.form.get('starts_at', ''))
                    end = start + (old_end - old_start)
                    if start.tzinfo or start <= datetime.now(zone).replace(tzinfo=None) or start.date() != end.date() or start == old_start:
                        raise ValueError('Choose a different future date and time. The event must finish on the same day.')
                    reason = request.form.get('reason', '').strip()
                    if not reason or len(reason) > 1000:
                        raise ValueError('Explain the proposal in up to 1,000 characters.')
                    if not available(booking, index, start, end):
                        raise ValueError('That time overlaps a confirmed booking or unavailable time, including setup buffers.')
                    key = f'{booking.id}:{index}'
                    pending = Proposal.query.filter_by(pending_key=key).first()
                    if pending and pending.display_status == 'Expired':
                        pending.status = 'Expired'; pending.pending_key = None
                        db.session.flush()
                    elif pending:
                        raise ValueError('Withdraw the existing proposal for this day before proposing another.')
                    db.session.add(Proposal(booking_id=booking.id, event_index=index, starts_at=start, ends_at=end,
                        original_hash=fingerprint(booking), reason=reason, pending_key=key, proposed_by=who,
                        expires_at=datetime.utcnow() + timedelta(days=7)))
                    flash('Replacement date proposed. The original booking stays in place until the client accepts.', 'success')
                elif action == 'withdraw':
                    proposal = Proposal.query.filter_by(id=request.form.get('proposal_id', type=int), booking_id=booking.id).first_or_404()
                    if proposal.status != 'Pending':
                        raise ValueError('This proposal has already been decided.')
                    proposal.status = 'Withdrawn'; proposal.pending_key = None; proposal.decided_at = datetime.utcnow()
                    flash('Date proposal withdrawn.', 'success')
                elif action == 'complete':
                    if followup:
                        return redirect(url_for('admin_booking_activity', booking_id=booking.id))
                    if booking.status != 'Accepted' or not events or max(interval(e)[1] for e in events) >= datetime.now(zone).replace(tzinfo=None):
                        raise ValueError('Only mark a confirmed booking completed after all its event times have passed.')
                    if any(p.display_status == 'Pending' for p in Proposal.query.filter_by(booking_id=booking.id, status='Pending').all()):
                        raise ValueError('Withdraw pending date proposals before marking this event completed.')
                    db.session.add(FollowUp(booking_id=booking.id, completed_at=datetime.utcnow(), completed_by=who))
                    flash('Event marked completed. You can now request feedback.', 'success')
                elif action == 'feedback':
                    if not followup or followup.responded_at:
                        raise ValueError('Feedback can be requested after completion, before a response is received.')
                    if followup.requested_at and followup.email_sent:
                        return redirect(url_for('admin_booking_activity', booking_id=booking.id))
                    followup.requested_at = followup.requested_at or datetime.utcnow()
                    db.session.commit()
                    followup.email_sent = send_email(booking.email, 'How was your CL Paints event?',
                        f'Hello {booking.first_name},\n\nThank you for choosing CL Paints. Please share your feedback for booking {booking.public_reference}:\n'
                        + url_for('client_booking_feedback', booking_id=booking.id, _external=True))
                    flash('Feedback request is available in the client portal. ' + ('Email sent.' if followup.email_sent else 'Email could not be sent; you can retry.'), 'success')
                else:
                    abort(400)
                db.session.commit()
                return redirect(url_for('admin_booking_activity', booking_id=booking.id))
            except (ValueError, KeyError, TypeError, IntegrityError) as problem:
                db.session.rollback()
                flash(str(problem) if not isinstance(problem, IntegrityError) else 'A proposal is already pending. Refresh to review it.', 'error')
        return render_template('admin_booking_activity.html', booking=booking, events=events,
            booking_timeline=timeline(booking, True), date_proposals=Proposal.query.filter_by(booking_id=booking.id).order_by(Proposal.created_at.desc()).all(),
            booking_followup=db.session.get(FollowUp, booking.id), client_csrf=csrf())

    @app.post('/client/bookings/<int:booking_id>/date-proposals/<int:proposal_id>')
    def client_decide_date(booking_id, proposal_id):
        account, booking = owner(booking_id)
        if not account:
            return redirect(url_for('client.login'))
        check()
        # Lock confirmed bookings in a consistent order before checking shared availability.
        Booking.query.filter(Booking.status == 'Accepted').order_by(Booking.id).with_for_update().all()
        app.extensions['availability_block_model'].query.order_by(app.extensions['availability_block_model'].id).with_for_update().all()
        db.session.refresh(booking)
        proposal = Proposal.query.filter_by(id=proposal_id, booking_id=booking.id).with_for_update().first_or_404()
        target = url_for('client.booking_detail', booking_id=booking.id)
        decision = request.form.get('decision')
        if decision not in ('accept', 'decline'):
            abort(400)
        if proposal.status != 'Pending':
            flash('This proposal has already been decided.', 'error')
            return redirect(target)
        if proposal.display_status == 'Expired' or fingerprint(booking) != proposal.original_hash or db.session.get(FollowUp, booking.id):
            proposal.status = 'Expired' if proposal.display_status == 'Expired' else 'Stale'
            proposal.pending_key = None; proposal.decided_at = datetime.utcnow()
            db.session.commit()
            flash('This proposal is out of date. Ask CL Paints for a fresh proposal.', 'error')
            return redirect(target)
        if decision == 'accept':
            if proposal.starts_at <= datetime.now(zone).replace(tzinfo=None) or not available(booking, proposal.event_index, proposal.starts_at, proposal.ends_at):
                flash('That time is no longer available. Your original booking remains in place; message CL Paints for another date.', 'error')
                return redirect(target)
            from client_notifications import booking_snapshot
            before = booking_snapshot(booking, schedule)
            events = [dict(e) for e in schedule(booking)]
            item = events[proposal.event_index]
            item.update(date=proposal.starts_at.date().isoformat(), start_time=proposal.starts_at.strftime('%H:%M'), finish_time=proposal.ends_at.strftime('%H:%M'))
            try:
                data = json.loads(booking.event_schedule or '{}')
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data['events'] = events
            booking.event_schedule = json.dumps(data)
            booking.event_date = datetime.fromisoformat(events[0]['date']).date()
            booking.start_time = events[0]['start_time']; booking.finish_time = events[0]['finish_time']
            booking.additional_event_dates = ','.join(e['date'] for e in events[1:]) or None
            linked = Event.query.filter_by(booking_id=booking.id, booking_day_number=proposal.event_index + 1).first()
            if linked:
                linked.event_date = proposal.starts_at.date()
            proposal.status = 'Accepted'
        else:
            proposal.status = 'Declined'
        proposal.pending_key = None; proposal.decided_at = datetime.utcnow()
        db.session.commit()
        if decision == 'accept':
            app.extensions['client_booking_updated'](booking, before, schedule)
        flash('Replacement date accepted.' if decision == 'accept' else 'Proposal declined. Your original booking remains in place.', 'success')
        return redirect(target)

    @app.route('/client/bookings/<int:booking_id>/feedback', methods=['GET', 'POST'])
    def client_booking_feedback(booking_id):
        account, booking = owner(booking_id)
        if not account:
            return redirect(url_for('client.login'))
        followup = FollowUp.query.filter_by(booking_id=booking.id).with_for_update().first_or_404()
        if not followup.requested_at:
            abort(404)
        error = None
        if request.method == 'POST':
            check()
            rating = request.form.get('rating', type=int)
            feedback = request.form.get('feedback', '').strip()
            if followup.responded_at:
                return redirect(url_for('client_booking_feedback', booking_id=booking.id))
            if rating not in range(1, 6) or len(feedback) > 3000:
                error = 'Choose a rating from 1 to 5 and keep comments under 3,001 characters.'
            else:
                followup.rating = rating; followup.feedback = feedback; followup.responded_at = datetime.utcnow()
                db.session.commit()
                flash('Thank you. Your feedback has been shared privately with CL Paints.', 'success')
                return redirect(url_for('client_booking_feedback', booking_id=booking.id))
        return render_template('client/feedback.html', booking=booking, booking_followup=followup,
                               client_account=account, client_csrf=csrf(), error=error)

    def repeat_details(account, booking_id):
        booking = Booking.query.filter(Booking.id == booking_id, db.func.lower(Booking.email) == account.email).first_or_404()
        fields = ('client_type', 'title', 'job_title', 'date_of_birth', 'ethnicity', 'ethnicity_detail', 'religion', 'payment_preference')
        result = {key: str(getattr(booking, key) or '') for key in fields}
        events = [dict(e) for e in schedule(booking)]
        for item in events:
            for field in ('event_address', 'event_type', 'theme', 'pitch_fee_required', 'publicity_type',
                          'charge_type', 'location_type', 'expected_attendees', 'celebrates_christmas_easter', 'additional_info'):
                item.setdefault(field, getattr(booking, field))
            item['date'] = ''
            # Reuse event details; estimates, extras, discounts and consent are chosen anew.
            for key in ('package', 'extras', 'travel_charge', 'travel_miles'):
                item.pop(key, None)
            for key in ('pitch_fee_required', 'celebrates_christmas_easter'):
                if isinstance(item.get(key), bool):
                    item[key] = 'yes' if item[key] else 'no'
        result['event_schedule'] = json.dumps(dict(events=events, same_details=False))
        result['single_date'] = 'yes' if len(events) == 1 else 'no'
        result['is_over_18'] = 'yes'
        return result

    app.extensions['repeat_booking_details'] = repeat_details
    app.extensions['booking_lifecycle'] = dict(timeline=timeline, models=models)
