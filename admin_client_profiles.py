"""Private, searchable admin client profiles built from existing records."""
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError

def define_model(db):
    class AdminClientNote(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False, index=True)
        body = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return AdminClientNote

def register(app, db, Note, Account, Booking, Waiver, Participant, Message, Enquiry,
             Owner, Invoice, loyalty, admin_required):
    _, Balance, _, Custodian, _ = loyalty
    def booking_account(booking):
        return Account.query.filter(db.func.lower(db.func.trim(Account.email)) == booking.email.strip().casefold()).first()

    @app.context_processor
    def booking_profile_context():
        return dict(booking_client_account=booking_account)

    @app.get('/admin/bookings/create-client')
    @admin_required
    def admin_choose_client_booking():
        term = request.args.get('q', '').strip()
        if len(term) > 100:
            abort(400)
        linked = Account.query.filter(db.func.lower(db.func.trim(Account.email)) ==
                                      db.func.lower(db.func.trim(Booking.email))).exists()
        query = Booking.query.filter(~linked)
        if term:
            pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.filter(or_(*[column.ilike(pattern, escape='\\') for column in
                (Booking.first_name, Booking.last_name, Booking.email, Booking.first_name + ' ' + Booking.last_name)]))
        pagination = query.order_by(Booking.submitted_at.desc(), Booking.id.desc()).paginate(per_page=25, error_out=False)
        response = app.make_response(render_template('admin_choose_client_booking.html', pagination=pagination, query=term))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/admin/bookings/<int:booking_id>/client', methods=['GET', 'POST'])
    @admin_required
    def admin_client_from_booking(booking_id):
        booking = db.get_or_404(Booking, booking_id)
        csrf = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST' and not secrets.compare_digest(csrf, request.form.get('csrf_token', '')):
            abort(400)
        account = booking_account(booking)
        if account:
            return redirect(url_for('admin_client_profile', client_id=account.id, tab='payments'))
        error = None
        values = dict(first_name=booking.first_name, last_name=booking.last_name,
                      phone=booking.phone or '', address=booking.client_address or '')
        if request.method == 'POST':
            values = {key: request.form.get(key, value).strip() for key, value in values.items()}
            try:
                email = validate_email(booking.email.strip(), check_deliverability=False).normalized.casefold()
                if any(not values[key] or len(values[key]) > 100 for key in ('first_name', 'last_name')):
                    raise ValueError('Enter a first name and surname, up to 100 characters each.')
                if len(values['phone']) > 50 or len(values['address']) > 4000:
                    raise ValueError('Keep the phone number within 50 characters and the address within 4,000 characters.')
                account = Account(email=email, **values)
                db.session.add(account)
                db.session.commit()
                flash('Client created from booking. Existing bookings, prices and payments are unchanged. No email was sent.', 'success')
                return redirect(url_for('admin_client_profile', client_id=account.id, tab='payments'))
            except IntegrityError:
                db.session.rollback()
                account = booking_account(booking)
                if account:
                    return redirect(url_for('admin_client_profile', client_id=account.id, tab='payments'))
                error = 'The client could not be created. Reload and check the booking email before trying again.'
            except (EmailNotValidError, ValueError) as exc:
                db.session.rollback()
                error = str(exc)
        response = app.make_response(render_template('admin_client_from_booking.html', booking=booking,
            values=values, client_csrf=csrf, error=error))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/admin/clients/<int:client_id>', methods=['GET','POST'])
    @admin_required
    def admin_client_profile(client_id):
        account = db.get_or_404(Account,client_id)
        csrf = session.setdefault('client_csrf',secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(csrf,request.form.get('csrf_token','')):
                abort(400)
            body = request.form.get('note','').strip()
            if not body or len(body) > 4000:
                flash('Enter an internal note of up to 4,000 characters.','error')
            else:
                db.session.add(Note(client_id=account.id,body=body))
                db.session.commit()
                flash('Internal note added. It is visible only to admins.','success')
            return redirect(url_for('admin_client_profile',client_id=account.id,tab='notes'))
        tab=request.args.get('tab','bookings')
        if tab not in ('bookings','payments','waivers','messages','rewards','notes'):
            abort(400)
        page=max(1,request.args.get('page',1,type=int))
        email=account.email.strip().casefold()
        booking_query=Booking.query.filter(db.func.lower(db.func.trim(Booking.email))==email)
        ids=booking_query.with_entities(Booking.id)
        bookings=booking_query.order_by(Booking.submitted_at.desc(),Booking.id.desc()).all()
        payments={b.id:app.extensions['payment_summary'](b) for b in bookings}
        active=[b for b in bookings if b.status=='Accepted']
        unread=Message.query.filter(Message.booking_id.in_(ids),Message.sender=='client',Message.read_at.is_(None)).count()
        today=datetime.now(ZoneInfo('Europe/London')).date()
        upcoming=[]
        for booking in active:
            dates=[str(day.get('date','')) for day in app.extensions['booking_schedule'](booking)]
            future=[value for value in dates if value >= today.isoformat()]
            if future: upcoming.append(dict(booking=booking,date=min(future)))
        summary=dict(bookings=len(bookings),confirmed=len(active),repeat=len(bookings)>=2,
            loyal=len(active)>=2,paid=sum(p['paid'] for p in payments.values()),
            outstanding=sum(payments[b.id]['outstanding'] for b in bookings if b.status in ('Accepted', 'Awaiting Payment')),unread=unread,
            review=sum(b.status=='Under Review' for b in bookings))
        query=None
        if tab in ('bookings','payments'):
            query=booking_query.order_by(Booking.submitted_at.desc(),Booking.id.desc())
        elif tab=='waivers':
            query=Waiver.query.filter(db.func.lower(db.func.trim(Waiver.responsible_email))==email).order_by(Waiver.signed_date.desc(),Waiver.id.desc())
        elif tab=='messages':
            query=Message.query.filter(Message.booking_id.in_(ids)).order_by(Message.created_at.desc(),Message.id.desc())
        elif tab=='notes':
            query=Note.query.filter_by(client_id=account.id).order_by(Note.created_at.desc(),Note.id.desc())
        members=[]
        if tab=='rewards':
            legacy_ids=Waiver.query.filter(db.func.lower(db.func.trim(Waiver.responsible_email))==email).with_entities(Waiver.id)
            people=Participant.query.filter(or_(Participant.id.in_(Custodian.query.filter_by(client_id=account.id).with_entities(Custodian.participant_id)),
                db.and_(Participant.waiver_id.in_(legacy_ids),~Participant.id.in_(Custodian.query.with_entities(Custodian.participant_id)))))
            query=people.order_by(Participant.first_name,Participant.id)
        pagination=query.paginate(page=page,per_page=25,error_out=False)
        rows=pagination.items
        if tab=='rewards':
            members=[dict(person=p,points=(db.session.get(Balance,p.id).points if db.session.get(Balance,p.id) else 0)) for p in rows]
        invoices=Invoice.query.filter(Invoice.booking_id.in_([b.id for b in rows])).order_by(Invoice.created_at.desc()).all() if tab=='payments' else []
        response=app.make_response(render_template('admin_client_profile.html',account=account,summary=summary,
            tab=tab,rows=rows,pagination=pagination,payments=payments,invoices=invoices,members=members,client_bookings=bookings,
            upcoming=sorted(upcoming,key=lambda row:row['date'])[:3],
            enquiries=Enquiry.query.filter_by(client_id=account.id).order_by(Enquiry.created_at.desc()).limit(5).all(),
            owners=Owner.query.filter_by(client_id=account.id).all(),today=today,client_csrf=csrf))
        response.headers['Cache-Control']='private, no-store'
        return response
