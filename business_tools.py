"""Operational tools: payment ledger, availability, reminders and enquiry workflow."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from contextlib import closing
from io import BytesIO
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file
from sqlalchemy.exc import IntegrityError
import click

def define_models(db):
    class PaymentPlan(db.Model):
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), primary_key=True)
        deposit = db.Column(db.Numeric(10, 2), nullable=False, default=0)
        deposit_due = db.Column(db.Date)
        balance_due = db.Column(db.Date)
    class PaymentEntry(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        token = db.Column(db.String(64), unique=True, nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        kind = db.Column(db.String(20), nullable=False)
        method = db.Column(db.String(100), nullable=False)
        note = db.Column(db.String(500), nullable=False, default='')
        paid_date = db.Column(db.Date, nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    class AvailabilityBlock(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        starts_at = db.Column(db.DateTime, nullable=False)
        ends_at = db.Column(db.DateTime, nullable=False)
        reason = db.Column(db.String(200), nullable=False)
    class EnquiryWorkflow(db.Model):
        enquiry_id = db.Column(db.Integer, db.ForeignKey('client_enquiry.id'), primary_key=True)
        status = db.Column(db.String(20), nullable=False, default='new')
        reply = db.Column(db.Text, nullable=False, default='')
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    class ReminderSend(db.Model):
        key = db.Column(db.String(150), primary_key=True)
        sent_at = db.Column(db.DateTime)
        claimed_at = db.Column(db.DateTime)
    class LoyaltyCorrection(db.Model):
        visit_id = db.Column(db.Integer, db.ForeignKey('loyalty_visit.id'), primary_key=True)
        reason = db.Column(db.String(500), nullable=False)
        corrected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return PaymentPlan, PaymentEntry, AvailabilityBlock, EnquiryWorkflow, ReminderSend, LoyaltyCorrection

def register_tools(app, db, models, Booking, Account, Enquiry, Participant, loyalty_models, notification_models,
                   current_client, admin_required, settings, send_email, schedule):
    Plan, Entry, Block, Workflow, Reminder, Correction = models
    _, Balance, Visit, Custodian, _ = loyalty_models
    _, Notice = notification_models
    app.extensions['loyalty_correction_model'] = Correction
    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))
    def check():
        if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400)
    def money(value):
        amount = Decimal(value)
        if not amount.is_finite() or not 0 <= amount <= Decimal('999999.99') or amount != amount.quantize(Decimal('.01')):
            raise ValueError('Use a non-negative amount with no more than two decimal places.')
        return amount
    def parse_date(value):
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    def summary(booking):
        plan = db.session.get(Plan, booking.id)
        entries = Entry.query.filter_by(booking_id=booking.id).order_by(Entry.recorded_at.desc()).all()
        total = booking.total_event_cost + booking.travel_charge
        paid = sum((e.amount if e.kind == 'payment' else -e.amount for e in entries), Decimal(0))
        return dict(total=total, paid=paid, outstanding=max(Decimal(0), total-paid), credit=max(Decimal(0), paid-total),
            deposit=plan.deposit if plan else Decimal(0), deposit_due=plan.deposit_due if plan else None,
            balance_due=plan.balance_due if plan else None, entries=entries)
    def payment_fields(booking):
        data = summary(booking)
        return {'Payments received': f'£{data["paid"]:.2f}', 'Balance outstanding': f'£{data["outstanding"]:.2f}',
                'Deposit requested': f'£{data["deposit"]:.2f}', 'Deposit due': str(data['deposit_due'] or 'Not set'),
                'Balance due': str(data['balance_due'] or 'Not set')}
    app.extensions['payment_summary'] = summary
    app.extensions['payment_fields'] = payment_fields

    @app.context_processor
    def tools_context():
        result = {}
        if request.endpoint == 'client.booking_detail':
            account = current_client()
            booking = db.session.get(Booking, request.view_args['booking_id'])
            if account and booking and booking.email.strip().casefold() == account.email:
                result['payment'] = summary(booking)
        if request.endpoint in ['admin_clients', 'client.contact']:
            result['enquiry_workflows'] = {w.enquiry_id:w for w in Workflow.query.all()}
            if request.endpoint == 'client.contact':
                account = current_client()
                result['own_enquiries'] = Enquiry.query.filter_by(client_id=account.id).order_by(Enquiry.id.desc()).all() if account else []
        if request.endpoint in ['loyalty.event_admin','loyalty.scan']:
            result['loyalty_corrections'] = {c.visit_id:c for c in Correction.query.all()}
        return result

    @app.route('/admin/bookings/<int:booking_id>/payments', methods=['GET','POST'])
    @admin_required
    def admin_payments(booking_id):
        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        if request.method == 'POST':
            check()
            from client_notifications import booking_snapshot
            before = booking_snapshot(booking, schedule)
            try:
                if request.form.get('action') == 'plan':
                    deposit = money(request.form.get('deposit','0'))
                    if deposit > summary(booking)['total']:
                        raise ValueError('Deposit cannot exceed the estimated total.')
                    plan = db.session.get(Plan, booking.id)
                    if not plan:
                        plan = Plan(booking_id=booking.id)
                        db.session.add(plan)
                    plan.deposit = deposit
                    plan.deposit_due = parse_date(request.form.get('deposit_due',''))
                    plan.balance_due = parse_date(request.form.get('balance_due',''))
                    if plan.deposit_due and plan.balance_due and plan.deposit_due > plan.balance_due:
                        raise ValueError('The deposit due date must be before the balance due date.')
                elif request.form.get('action') == 'entry':
                    token = request.form.get('entry_token','')
                    if token != session.get(f'payment_entry_{booking.id}'):
                        raise ValueError('This payment form is out of date. Reload and try again.')
                    if Entry.query.filter_by(token=token).first():
                        flash('This payment entry is already recorded.', 'success')
                        return redirect(url_for('admin_payments',booking_id=booking.id))
                    amount = money(request.form.get('amount',''))
                    kind = request.form.get('kind','')
                    if amount <= 0 or kind not in ['payment','refund']:
                        raise ValueError('Choose a payment or refund and enter a positive amount.')
                    if kind == 'refund' and amount > summary(booking)['paid']:
                        raise ValueError('A refund cannot exceed payments received.')
                    method = request.form.get('method','').strip()
                    if method not in ('SumUp', 'Cash'):
                        raise ValueError('Choose SumUp or Cash as the payment method.')
                    note = request.form.get('note','').strip()
                    paid_date = parse_date(request.form.get('paid_date',''))
                    if not method or len(method)>100 or len(note)>500 or not paid_date or paid_date>datetime.now(ZoneInfo('Europe/London')).date():
                        raise ValueError('Enter a payment method and valid past or current payment date; keep notes under 501 characters.')
                    db.session.add(Entry(booking_id=booking.id,token=token,amount=amount,kind=kind,method=method,note=note,paid_date=paid_date))
                else:
                    abort(400)
                db.session.commit()
                app.extensions['client_booking_updated'](booking,before,schedule)
                flash('Payment records saved; the client has an updated balance.', 'success')
                return redirect(url_for('admin_payments',booking_id=booking.id))
            except (ValueError, InvalidOperation, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if not isinstance(error, IntegrityError) else 'This payment was already recorded.', 'error')
        token = secrets.token_urlsafe(32)
        session[f'payment_entry_{booking.id}'] = token
        return render_template('admin_payments.html',booking=booking,payment=summary(booking),client_csrf=csrf(),entry_token=token,today=datetime.now(ZoneInfo('Europe/London')).date())

    @app.get('/admin/payments')
    @admin_required
    def payments_overview():
        today = datetime.now(ZoneInfo('Europe/London')).date()
        selected = request.args.get('filter', 'outstanding')
        if selected not in ('all','outstanding','deposit','overdue'): abort(400)
        rows = []
        totals = dict(received=Decimal(0), outstanding=Decimal(0), deposits=Decimal(0), overdue=Decimal(0))
        for booking in Booking.query.order_by(Booking.submitted_at.desc()).all():
            payment = summary(booking)
            active = booking.status in ('Accepted', 'Under Review')
            remaining = min(payment['outstanding'], max(Decimal(0), payment['deposit']-payment['paid'])) if active else Decimal(0)
            deposit_due = bool(remaining and payment['deposit_due'] and payment['deposit_due'] <= today)
            overdue = active and payment['outstanding'] > 0 and bool(payment['balance_due']) and payment['balance_due'] < today
            totals['received'] += payment['paid']
            if active: totals['outstanding'] += payment['outstanding']
            if deposit_due: totals['deposits'] += remaining
            if overdue: totals['overdue'] += payment['outstanding']
            match = selected == 'all' or (selected == 'outstanding' and active and payment['outstanding'] > 0) or (selected == 'deposit' and deposit_due) or (selected == 'overdue' and overdue)
            if match: rows.append(dict(booking=booking, payment=payment, deposit_remaining=remaining, overdue=overdue, deposit_due=deposit_due))
        return render_template('admin_payments_overview.html', rows=rows, totals=totals, selected=selected)

    def calendar_rows():
        buffer = int(settings().get('calendar_buffer_minutes','60'))
        rows=[]
        for booking in Booking.query.filter(Booking.status.in_(['Accepted','Under Review'])).all():
            for index, event in enumerate(schedule(booking),1):
                try:
                    start=datetime.fromisoformat(event['date']+'T'+event['start_time'])
                    end=datetime.fromisoformat(event['date']+'T'+event['finish_time'])
                except (KeyError,ValueError,TypeError):
                    continue
                rows.append(dict(booking=booking,label=booking.public_reference,start=start,end=end,
                    occupied_start=start-timedelta(minutes=buffer),occupied_end=end+timedelta(minutes=buffer),day=index,conflicts=[]))
        for block in Block.query.all():
            rows.append(dict(booking=None,label=block.reason,start=block.starts_at,end=block.ends_at,
                occupied_start=block.starts_at,occupied_end=block.ends_at,day=None,conflicts=[]))
        for row in rows:
            if row['booking'] and row['booking'].status=='Under Review':
                others=[other for other in rows if not other['booking'] or other['booking'].status=='Accepted']
            else:
                others=rows
            row['conflicts']=[other['label'] for other in others if other is not row and not (row['booking'] and other['booking'] and row['booking'].id==other['booking'].id and row['day']==other['day']) and row['occupied_start']<other['occupied_end'] and other['occupied_start']<row['occupied_end']]
        return sorted(rows,key=lambda row:row['start'])
    app.extensions['calendar_rows']=calendar_rows

    @app.get('/booking/calendar')
    def client_availability_calendar():
        import calendar
        try:
            month = datetime.strptime(request.args.get('month', datetime.now(ZoneInfo('Europe/London')).strftime('%Y-%m')), '%Y-%m')
            if not 1900 <= month.year <= 2100: raise ValueError()
        except ValueError:
            abort(400)
        # Only publish occupied intervals; never names, addresses, references or block reasons.
        occupied = [(row['occupied_start'], row['occupied_end']) for row in calendar_rows()
                    if not row['booking'] or row['booking'].status == 'Accepted']
        weeks = []
        for week in calendar.Calendar().monthdatescalendar(month.year, month.month):
            cells = []
            for date in week:
                start = datetime.combine(date, datetime.min.time())
                end = start + timedelta(days=1)
                intervals = sorted((max(a, start), min(b, end)) for a, b in occupied if a < end and b > start)
                merged = []
                for a, b in intervals:
                    if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                    else: merged.append((a, b))
                cells.append(dict(date=date, in_month=date.month == month.month,
                    times=[a.strftime('%H:%M') + '–' + ('24:00' if b == end else b.strftime('%H:%M')) for a, b in merged]))
            weeks.append(cells)
        return render_template('client/availability_calendar.html', weeks=weeks, month=month,
            previous=(month-timedelta(days=1)).strftime('%Y-%m'),
            next_month=(month.replace(day=28)+timedelta(days=4)).strftime('%Y-%m'))

    @app.route('/admin/calendar',methods=['GET','POST'])
    @admin_required
    def admin_calendar():
        if request.method=='POST':
            check()
            try:
                start=datetime.fromisoformat(request.form.get('starts_at',''))
                end=datetime.fromisoformat(request.form.get('ends_at',''))
                reason=request.form.get('reason','').strip()
                if start.tzinfo or end.tzinfo or end<=start or not reason or len(reason)>200:
                    raise ValueError('Enter a reason and an end time after the start time. Times are UK local time.')
                db.session.add(Block(starts_at=start,ends_at=end,reason=reason))
                db.session.commit()
                flash('Unavailable time added.', 'success')
            except ValueError as error:
                flash(str(error),'error')
            return redirect(url_for('admin_calendar'))
        import calendar
        try:
            month=datetime.strptime(request.args.get('month',datetime.now(ZoneInfo('Europe/London')).strftime('%Y-%m')),'%Y-%m')
            if not 1900 <= month.year <= 2100: raise ValueError()
        except ValueError: abort(400)
        rows=calendar_rows()
        weeks=[]
        for week in calendar.Calendar().monthdatescalendar(month.year,month.month):
            cells=[]
            for date in week:
                start=datetime.combine(date,datetime.min.time())
                cells.append(dict(date=date,in_month=date.month==month.month,items=[row for row in rows if row['start']<start+timedelta(days=1) and row['end']>start]))
            weeks.append(cells)
        previous=(month-timedelta(days=1)).strftime('%Y-%m')
        next_month=(month.replace(day=28)+timedelta(days=4)).strftime('%Y-%m')
        return render_template('admin_calendar.html',rows=rows,client_csrf=csrf(),blocks=Block.query.order_by(Block.starts_at).all(),weeks=weeks,month=month,previous=previous,next_month=next_month)
    @app.post('/admin/calendar/blocks/<int:block_id>/delete')
    @admin_required
    def delete_availability_block(block_id):
        check()
        block=db.session.get(Block,block_id)
        if block:
            db.session.delete(block)
            db.session.commit()
        return redirect(url_for('admin_calendar'))

    @app.post('/admin/enquiries/<int:enquiry_id>/update')
    @admin_required
    def update_enquiry(enquiry_id):
        check()
        enquiry=db.session.get(Enquiry,enquiry_id)
        if not enquiry: abort(404)
        status=request.form.get('status','')
        reply=request.form.get('reply','').strip()
        if status not in ['new','replied','resolved'] or len(reply)>3000:
            abort(400)
        workflow=db.session.get(Workflow,enquiry.id)
        if not workflow:
            workflow=Workflow(enquiry_id=enquiry.id)
            db.session.add(workflow)
        changed=reply and reply!=workflow.reply
        workflow.status=status
        workflow.reply=reply
        workflow.updated_at=datetime.utcnow()
        db.session.commit()
        if changed:
            account=db.session.get(Account,enquiry.client_id)
            sent=send_email(account.email,'CL Paints: reply to your enquiry',f'Hello {account.first_name},\n\n{reply}\n\nView your enquiry: {url_for("client.contact",_external=True)}')
            db.session.add(Notice(email=account.email,kind='enquiry',reference=f'Enquiry #{enquiry.id}',details=reply,email_sent=sent))
            db.session.commit()
            flash('Reply saved and emailed.' if sent else 'Reply saved; email delivery failed. Contact the client.', 'success' if sent else 'error')
        else:
            flash('Enquiry status saved.','success')
        return redirect(url_for('admin_clients')+'#enquiry-'+str(enquiry.id))

    @app.post('/admin/loyalty/visits/<int:visit_id>/reverse')
    @admin_required
    def reverse_loyalty(visit_id):
        check()
        visit=Visit.query.filter_by(id=visit_id).with_for_update().first_or_404()
        reason=request.form.get('reason','').strip()
        if not reason or len(reason)>500: abort(400)
        if db.session.get(Correction,visit.id):
            flash('This visit has already been reversed.','error')
        else:
            later=Visit.query.filter(Visit.participant_id==visit.participant_id,Visit.id>visit.id).all()
            if any(not db.session.get(Correction,v.id) for v in later):
                flash('Reverse later visits first so the point history stays consistent.','error')
                return redirect(url_for('loyalty.event_admin',event_id=visit.event_id))
            balance=db.session.get(Balance,visit.participant_id)
            expected=0 if visit.status=='free' else balance.points
            if visit.status not in ['point','free'] or (visit.status=='point' and expected<1): abort(409)
            updated=Balance.query.filter_by(participant_id=visit.participant_id,points=expected).update({'points':3 if visit.status=='free' else expected-1},synchronize_session=False)
            if not updated: db.session.rollback(); abort(409)
            db.session.add(Correction(visit_id=visit.id,reason=reason))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                abort(409)
            person=db.session.get(Participant,visit.participant_id)
            owner=db.session.get(Custodian,person.id)
            account=db.session.get(Account,owner.client_id if owner else visit.client_id)
            app.extensions['client_reward_notice'](account.email,account.first_name,person.loyalty_reference,f'Loyalty visit corrected: {reason}. Check Rewards for the updated balance.')
            flash('Visit reversed with its reason recorded. The event cannot be scanned again for this member.','success')
        return redirect(url_for('loyalty.event_admin',event_id=visit.event_id))

    @app.get('/admin/email-history')
    @admin_required
    def email_history():
        return render_template('admin_email_history.html',notices=Notice.query.order_by(Notice.id.desc()).limit(100).all())

    @app.get('/admin/email-preview/<kind>')
    @admin_required
    def email_preview(kind):
        if kind not in ['booking','reward']: abort(404)
        from client_notifications import render_notification
        subject, body, footer, message=render_notification(settings(),'Sample client',kind,'05/10/2026 - B - 0001' if kind=='booking' else '05/10/2026 - L - 0001',
            'Travel charge: £0.00 → £15.00' if kind=='booking' else 'One loyalty point earned. Current balance: 1/3.',url_for('client.login',_external=True),preview=True)
        response=app.make_response(render_template('email_preview_embed.html' if request.args.get('embed')=='1' else 'admin_email_preview.html',subject=subject,message=message))
        response.headers['Cache-Control']='private, no-store'
        return response

    def reminders(dry_run=True):
        today=datetime.now(ZoneInfo('Europe/London')).date()
        days=int(settings().get('reminder_days','2'))
        base=settings().get('public_app_url','').rstrip('/')
        if not dry_run and not base.startswith('https://'):
            raise ValueError('Set an HTTPS public app URL in Settings before sending reminders.')
        due=[]
        for booking in Booking.query.filter_by(status='Accepted').all():
            for event in schedule(booking):
                try: date=datetime.strptime(event['date'],'%Y-%m-%d').date()
                except (KeyError,TypeError,ValueError): continue
                key=f'{booking.id}:{date.isoformat()}:event-reminder'
                existing=db.session.get(Reminder,key)
                if not today<=date<=today+timedelta(days=days) or (existing and existing.sent_at): continue
                due.append(booking.public_reference+' · '+date.isoformat())
                if dry_run: continue
                if not existing:
                    existing=Reminder(key=key)
                    db.session.add(existing)
                    try: db.session.commit()
                    except IntegrityError: db.session.rollback(); existing=db.session.get(Reminder,key)
                cutoff=datetime.utcnow()-timedelta(minutes=10)
                claimed=Reminder.query.filter_by(key=key,sent_at=None).filter(db.or_(Reminder.claimed_at.is_(None),Reminder.claimed_at<cutoff)).update({'claimed_at':datetime.utcnow()},synchronize_session=False)
                db.session.commit()
                if not claimed: continue
                balance=summary(booking)
                body=(f'Hello {booking.first_name},\n\nYour CL Paints event is coming up on {date:%d/%m/%Y}.\n'
                    f'Time: {event.get("start_time", "")}–{event.get("finish_time", "")}\nAddress: {event.get("event_address", "")}\n'
                    f'Balance outstanding: £{balance["outstanding"]:.2f}\n\nPlease confirm access and a suitable setup space with us.\n'
                    f'View your booking: {base}/client/bookings/{booking.id}\n\nBringing colour to life - One face at time')
                sent=send_email(booking.email,'CL Paints: your event reminder',body)
                db.session.add(Notice(email=booking.email,kind='reminder',reference=booking.public_reference,details=f'Event reminder for {date:%d/%m/%Y}',email_sent=sent))
                Reminder.query.filter_by(key=key).update({'sent_at':datetime.utcnow() if sent else None,'claimed_at':None},synchronize_session=False)
                db.session.commit()
        return due
    app.extensions['send_due_reminders']=reminders
    @app.cli.command('send-booking-reminders')
    @click.option('--send',is_flag=True,help='Send due reminders; default is a dry run.')
    def send_reminders(send):
        try:
            due=reminders(dry_run=not send)
            click.echo(('Processed: ' if send else 'Dry run: ')+str(len(due)))
            for row in due: click.echo(row)
        except ValueError as error: raise click.ClickException(str(error))

    @app.route('/admin/backups',methods=['GET','POST'])
    @admin_required
    def backups():
        if request.method=='POST':
            check()
            if db.engine.dialect.name!='sqlite':
                abort(400,'Use your PostgreSQL provider backups and point-in-time recovery.')
            database=Path(db.engine.url.database).resolve()
            output=BytesIO()
            with tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'backup.db'
                raw=db.engine.raw_connection()
                try:
                    with closing(sqlite3.connect(str(target))) as destination:
                        raw.driver_connection.backup(destination)
                        if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok': abort(500)
                finally:
                    raw.close()
                output.write(target.read_bytes())
            output.seek(0)
            return send_file(output,mimetype='application/octet-stream',as_attachment=True,download_name='cl-paints-backup-'+datetime.utcnow().strftime('%Y%m%d-%H%M%S')+'.db')
        return render_template('admin_backups.html',sqlite=db.engine.dialect.name=='sqlite',client_csrf=csrf())
