"""Private, searchable admin client profiles built from existing records."""
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_

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
            outstanding=sum(payments[b.id]['outstanding'] for b in active),unread=unread,
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
            tab=tab,rows=rows,pagination=pagination,payments=payments,invoices=invoices,members=members,
            upcoming=sorted(upcoming,key=lambda row:row['date'])[:3],
            enquiries=Enquiry.query.filter_by(client_id=account.id).order_by(Enquiry.created_at.desc()).limit(5).all(),
            owners=Owner.query.filter_by(client_id=account.id).all(),today=today,client_csrf=csrf))
        response.headers['Cache-Control']='private, no-store'
        return response
