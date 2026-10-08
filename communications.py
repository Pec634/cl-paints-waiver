"""One admin workspace for messages, notification history and configuration."""
import secrets
from flask import abort, render_template, request, session
from sqlalchemy import or_

def register(app,db,Booking,Message,Notice,marketing,settings,admin_required,Enquiry,Account,Workflow):
    _,Campaign,Delivery=marketing
    def private(template,**values):
        response=app.make_response(render_template(template,**values))
        response.headers['Cache-Control']='private, no-store'
        return response
    @app.route('/admin/communications/templates',methods=['GET','POST'])
    @admin_required
    def communications_templates():
        return app.view_functions['admin_settings']()
    @app.get('/admin/communications/messages')
    @admin_required
    def communications_messages():
        mode=request.args.get('view','inbox')
        if mode not in ('inbox','sent','unread','all','enquiries'): abort(400)
        term=request.args.get('q','').strip()
        if len(term)>100: abort(400)
        query=db.session.query(Message,Booking).join(Booking,Message.booking_id==Booking.id)
        if mode in ('inbox','unread'): query=query.filter(Message.sender=='client')
        elif mode=='sent': query=query.filter(Message.sender=='admin')
        if mode=='unread': query=query.filter(Message.read_at.is_(None))
        if term:
            match='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            query=query.filter(or_(*[column.ilike(match,escape='\\') for column in
                (Booking.email,Booking.first_name+' '+Booking.last_name,Booking.event_type,Message.body)]))
        if mode=='enquiries':
            query=db.session.query(Enquiry,Account,Workflow).join(Account,Enquiry.client_id==Account.id).outerjoin(Workflow,Workflow.enquiry_id==Enquiry.id)
            if term: query=query.filter(or_(Account.email.ilike(match,escape='\\'),Enquiry.subject.ilike(match,escape='\\'),Enquiry.message.ilike(match,escape='\\')))
            query=query.order_by(Enquiry.created_at.desc(),Enquiry.id.desc())
        else: query=query.order_by(Message.created_at.desc(),Message.id.desc())
        pagination=query.paginate(page=max(1,request.args.get('page',1,type=int)),per_page=25,error_out=False)
        return private('admin_communications_messages.html',pagination=pagination,mode=mode,query=term,
                       client_csrf=session.setdefault('client_csrf',secrets.token_urlsafe(32)))
    @app.get('/admin/communications/history')
    @admin_required
    def communications_history():
        source=request.args.get('source','notifications')
        if source not in ('notifications','campaigns'): abort(400)
        term=request.args.get('q','').strip()
        if len(term)>100: abort(400)
        state=request.args.get('state','all')
        if state not in ('all','accepted','failed','pending'): abort(400)
        match='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        if source=='notifications':
            records=Notice.query
            if term: records=records.filter(or_(Notice.email.ilike(match,escape='\\'),Notice.reference.ilike(match,escape='\\')))
            if state=='accepted': records=records.filter_by(email_sent=True)
            elif state=='failed': records=records.filter_by(email_sent=False)
            elif state=='pending': records=records.filter(db.false())
            records=records.order_by(Notice.created_at.desc(),Notice.id.desc())
        else:
            records=db.session.query(Delivery,Campaign).join(Campaign,Delivery.campaign_id==Campaign.id)
            if term: records=records.filter(or_(Delivery.email.ilike(match,escape='\\'),Campaign.subject.ilike(match,escape='\\')))
            if state!='all': records=records.filter(Delivery.status==state)
            records=records.order_by(Delivery.id.desc())
        pagination=records.paginate(page=max(1,request.args.get('page',1,type=int)),per_page=25,error_out=False)
        return private('admin_communications_history.html',pagination=pagination,source=source,state=state,query=term)
    @app.get('/admin/communications/configuration')
    @admin_required
    def communications_configuration():
        session.setdefault('settings_csrf',secrets.token_urlsafe(32))
        session.setdefault('client_csrf',secrets.token_urlsafe(32))
        return private('admin_communications_configuration.html',is_admin=True,settings=settings(),
            csrf_token=session['settings_csrf'],client_csrf=session['client_csrf'])
