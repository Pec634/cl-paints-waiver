"""Reusable form blocks, completion counters and booking intake controls."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hashlib
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for, send_file
from email_validator import validate_email, EmailNotValidError
from native_form_fields import validate_fields, image_source


def define_models(db):
    class FormBlockTemplate(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(150), nullable=False)
        fields_json = db.Column(db.Text, nullable=False)
    class FormActivity(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False, index=True)
        visitor = db.Column(db.String(64), nullable=False)
        started = db.Column(db.Boolean, nullable=False, default=False)
        completed = db.Column(db.Boolean, nullable=False, default=False)
        steps_json = db.Column(db.Text, nullable=False, default='[]')
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('form_id', 'visitor'),)
    class FormWaitingEntry(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False, index=True)
        email = db.Column(db.String(255), nullable=False)
        name = db.Column(db.String(150), nullable=False)
        event_date = db.Column(db.Date)
        details = db.Column(db.Text, nullable=False, default='')
        status = db.Column(db.String(20), nullable=False, default='Waiting')
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    class FormIntakeAttempt(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        source = db.Column(db.String(64), nullable=False, index=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    db._form_workflow_models = (FormBlockTemplate, FormActivity, FormWaitingEntry, FormIntakeAttempt)


def catalog(text, label):
    result = []
    if len(text) > 15000: raise ValueError(label+' is too long.')
    for line in text.splitlines():
        if not line.strip(): continue
        parts = [part.strip() for part in line.split('|')]
        try:
            name, price, hours = parts[:3]
            price, hours = Decimal(price), Decimal(hours)
            if not price.is_finite() or not hours.is_finite() or not 0 <= price <= 100000 or not 0 <= hours <= 24:
                raise ValueError()
            if price != price.quantize(Decimal('.01')) or hours != hours.quantize(Decimal('.01')): raise ValueError()
        except (ValueError, InvalidOperation):
            raise ValueError(label+': use Name | price | hours | description, with positive numbers (0 hours for extras).')
        description = parts[3] if len(parts) > 3 else ''
        if len(parts) > 5 or not name or len(name) > 100 or len(description) > 500 or any(row['name'] == name for row in result):
            raise ValueError('Use unique names under 100 characters and descriptions under 500 characters.')
        row=dict(name=name, price=str(price), hours=str(hours), description=description)
        if len(parts)==5 and parts[4]:row['image']=image_source(parts[4])
        result.append(row)
    if len(result) > 12: raise ValueError('Use no more than twelve '+label.lower()+'.')
    return result


def validate_options(data):
    result = {}
    for key, maximum in [('cutoff_days',365), ('response_limit',100000)]:
        try: value = int(data.get(key,'0') or '0')
        except (ValueError, TypeError): raise ValueError('Use whole numbers for cutoff days and response limits.')
        if not 0 <= value <= maximum: raise ValueError('Check the cutoff days and response limit.')
        result[key] = str(value)
    result['waitlist_enabled'] = 'yes' if data.get('waitlist_enabled') == 'yes' else ''
    for key, label in [('packages','Packages'),('extras','Extras')]:
        text = data.get(key,'').strip()
        choices = catalog(text,label)
        if key == 'packages' and any(Decimal(row['hours']) <= 0 for row in choices):
            raise ValueError('Packages need a duration above zero.')
        if key == 'extras' and any(Decimal(row['hours']) != 0 for row in choices):
            raise ValueError('Use 0 hours for extras; extras are added once to the request.')
        result[key] = text
    return result


def booking_options(settings, data, events, hourly_total):
    """Authoritative package/extra pricing; posted estimates are never trusted."""
    packages = catalog(settings.get('packages',''),'Packages')
    extras = catalog(settings.get('extras',''),'Extras')
    selected = data.get('booking_package','')
    package = next((row for row in packages if row['name'] == selected),None)
    if selected and not package: raise ValueError('Choose a listed package.')
    chosen = data.getlist('booking_extras')
    if len(chosen) != len(set(chosen)) or any(name not in [row['name'] for row in extras] for name in chosen):
        raise ValueError('Choose listed extras once each.')
    total = hourly_total
    if package:
        for event in events:
            if Decimal(event['duration_hours']) != Decimal(package['hours']) or event['pitch_fee_required'] or event['charge_type'] != 'Client':
                raise ValueError('For this package, each event must use its stated duration, Client pays, and no pitch fee.')
            event['estimated_cost'] = package['price']
        total = Decimal(package['price']) * len(events)
    additions = [row for row in extras if row['name'] in chosen]
    extra_total = sum((Decimal(row['price']) for row in additions), Decimal(0))
    if additions and any(event['pitch_fee_required'] or event['charge_type'] != 'Client' for event in events):
        raise ValueError('Priced extras require Client pays and no pitch fee for every event.')
    # Mileage is assessed by staff; ignore any value supplied by a public form.
    miles = Decimal('0')
    captions = data.get('design_captions','').strip()
    if len(captions) > 3000: raise ValueError('Keep photo captions under 3,000 characters.')
    return total+extra_total, dict(package=package, extras=additions, extras_total=str(extra_total), travel_miles=str(miles), design_captions=captions)


def pdf_document(lines):
    """Small, paginated text PDF using the standard PDF Helvetica font."""
    import textwrap
    rows = []
    for line in lines:
        for paragraph in str(line).splitlines() or ['']:
            rows.extend(textwrap.wrap(paragraph, width=90, replace_whitespace=False) or [''])
    pages = [rows[index:index+48] for index in range(0,len(rows),48)] or [[]]
    objects = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    page_ids = []
    for page in pages:
        page_id = len(objects)+1; content_id = page_id+1; page_ids.append(page_id)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>'.encode())
        stream = b'BT /F1 11 Tf 45 795 Td 15 TL\n'
        for row in page:
            safe = row.encode('cp1252','replace').replace(b'\\',b'\\\\').replace(b'(',b'\\(').replace(b')',b'\\)')
            safe = bytes(value if value >= 32 else 32 for value in safe)
            stream += b'('+safe+b') Tj T*\n'
        stream += b'ET'
        objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(str(i)+" 0 R" for i in page_ids)}] >>'.encode()
    result = b'%PDF-1.4\n'; offsets = [0]
    for index, obj in enumerate(objects,1):
        offsets.append(len(result)); result += f'{index} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start = len(result); result += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    for offset in offsets[1:]: result += f'{offset:010d} 00000 n \n'.encode()
    return result+f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def register(app,db,models,Booking,current_client,admin_required,available,records,csrf,check):
    Form,Submission,_ = models
    Template,Activity,Waiting,Attempt = db._form_workflow_models

    def options(form): return records['settings'](form) if form else {}
    def count(form):
        return Submission.query.filter_by(form_id=form.id).count()+db._native_extra_models[3].query.filter_by(form_id=form.id).count()
    def full(form):
        limit = int(options(form).get('response_limit','0') or '0')
        return bool(limit and count(form) >= limit)
    def guard():
        if request.form.get('contact_website',''): raise ValueError('We could not accept this request. Please contact CL Paints directly.')
        source = hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
        now = datetime.utcnow()
        if Attempt.query.filter(Attempt.source==source,Attempt.created_at>now-timedelta(hours=1)).count() >= 30:
            raise ValueError('Too many requests. Please wait an hour before trying again.')
        Attempt.query.filter(Attempt.created_at<now-timedelta(days=1)).delete()
        db.session.add(Attempt(source=source)); db.session.commit()
    def visitor(): return session.setdefault('form_visitor',secrets.token_hex(24))
    def track(form,completed=False):
        item = Activity.query.filter_by(form_id=form.id,visitor=visitor()).first()
        if not item: item=Activity(form_id=form.id,visitor=visitor()); db.session.add(item)
        if completed: item.started=True; item.completed=True
        return item
    def booking_check(form,events,email):
        cutoff = int(options(form).get('cutoff_days','0') or '0')
        today = datetime.now(ZoneInfo('Europe/London')).date()
        if any(datetime.fromisoformat(event['date']).date() < today+timedelta(days=cutoff) for event in events):
            raise ValueError(f'Please allow at least {cutoff} days before the event. Contact CL Paints for shorter notice.')
        if form:
            Form.query.filter_by(id=form.id).with_for_update().first()
            if full(form): raise ValueError('This form has reached its response limit. Please use the waiting list if available.')
        candidates=Booking.query.filter(db.func.lower(Booking.email)==email.lower(),Booking.status.in_(['Accepted','Under Review'])).all()
        duplicates=[]
        for booking in candidates:
            dates={event['date'] for event in app.extensions['booking_schedule'](booking)}
            if dates.intersection(event['date'] for event in events):
                duplicates.append(booking.public_reference)
        return duplicates

    @app.context_processor
    def context():
        def intake(booking):
            try: return json.loads(booking.event_schedule or '{}').get('intake_options',{})
            except (ValueError,AttributeError): return {}
        return dict(form_workflow_options=options, form_workflow_full=full, form_catalog=catalog,workflow_csrf=csrf(),booking_intake_details=intake)

    @app.get('/admin/form-blocks')
    @admin_required
    def form_block_library(): return jsonify(blocks=[dict(id=row.id,title=row.title,fields=json.loads(row.fields_json)) for row in Template.query.order_by(Template.title).all()])

    @app.post('/admin/form-blocks')
    @admin_required
    def form_block_save():
        check()
        try:
            title=request.form.get('title','').strip()
            if not title or len(title)>150: raise ValueError('Name the reusable block group (up to 150 characters).')
            raw=request.form.get('fields_json','')
            if len(raw)>400000: raise ValueError('This block group is too large.')
            fields=validate_fields(json.loads(raw))
            if not fields: raise ValueError('Add at least one block.')
            row=Template(title=title,fields_json=json.dumps(fields));db.session.add(row);db.session.commit()
            return jsonify(id=row.id,title=row.title),201
        except (ValueError,TypeError) as error:
            db.session.rollback();return jsonify(error=str(error)),400

    @app.post('/admin/form-blocks/<int:template_id>/delete')
    @admin_required
    def form_block_delete(template_id):
        check();db.session.delete(db.get_or_404(Template,template_id));db.session.commit();return jsonify(success=True)

    @app.post('/forms/<int:form_id>/activity')
    def form_activity(form_id):
        form=db.get_or_404(Form,form_id)
        if not available(form): abort(404)
        if request.content_length and request.content_length>2048: abort(413)
        if not secrets.compare_digest(csrf(),request.headers.get('X-CSRF-Token','')): abort(400)
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict): abort(400)
        item=track(form);item.started=item.started or bool(data.get('started'))
        steps=data.get('steps',[])
        if not isinstance(steps,list) or len(steps)>30 or any(type(i)!=int or not 0<=i<len(json.loads(form.fields_json)) for i in steps): abort(400)
        definitions=json.loads(form.fields_json)
        item.steps_json=json.dumps(sorted(set(json.loads(item.steps_json)).union(definitions[i]['label'] for i in steps)));db.session.commit()
        return jsonify(success=True)

    @app.route('/forms/<int:form_id>/waiting-list',methods=['GET','POST'])
    def form_waiting_list(form_id):
        form=db.get_or_404(Form,form_id)
        if not form.enabled or options(form).get('waitlist_enabled')!='yes': abort(404)
        error=None;account=current_client()
        if request.method=='POST':
            check()
            try:
                guard()
                email=account.email if account else validate_email(request.form.get('email',''),check_deliverability=False).normalized
                name=request.form.get('name','').strip();details=request.form.get('details','').strip()
                if not name or len(name)>150 or len(details)>2000: raise ValueError('Enter your name and keep notes under 2,000 characters.')
                date=datetime.strptime(request.form['event_date'],'%Y-%m-%d').date() if request.form.get('event_date') else None
                if date and date<datetime.now(ZoneInfo('Europe/London')).date(): raise ValueError('Choose a future date.')
                if not Waiting.query.filter_by(form_id=form.id,email=email,event_date=date,status='Waiting').first():
                    db.session.add(Waiting(form_id=form.id,email=email,name=name,event_date=date,details=details));db.session.commit()
                return render_template('form_waiting_list.html',form=form,received=True)
            except (ValueError,EmailNotValidError) as err: error=str(err)
        return render_template('form_waiting_list.html',form=form,csrf=csrf(),error=error,account=account)

    @app.route('/admin/native-forms/<int:form_id>/insights',methods=['GET','POST'])
    @admin_required
    def form_insights(form_id):
        form=db.get_or_404(Form,form_id)
        if request.method=='POST':
            check();row=db.get_or_404(Waiting,request.form.get('id',type=int))
            if row.form_id!=form.id: abort(404)
            status=request.form.get('status')
            if status not in ('Waiting','Contacted','Closed'): abort(400)
            row.status=status;db.session.commit();return redirect(url_for('form_insights',form_id=form.id))
        activity=Activity.query.filter_by(form_id=form.id).all()
        fields=json.loads(form.fields_json)
        progress=[dict(label=f['label'],count=sum(f['label'] in json.loads(row.steps_json) for row in activity)) for f in fields if f['type'] not in ('content','heading','image','pagebreak')]
        booking_records=db._native_extra_models[3].query.filter_by(form_id=form.id).all()
        checklist=[]
        for record in booking_records:
            booking=db.session.get(Booking,record.booking_id)
            payment=app.extensions['payment_summary'](booking)
            missing=[]
            if booking.status=='Under Review': missing.append('Review availability and details')
            if payment['deposit']>payment['paid']: missing.append('Deposit outstanding')
            if not booking.phone: missing.append('Contact phone missing')
            if any(not event.get('event_address') for event in app.extensions['booking_schedule'](booking)): missing.append('Venue address missing')
            if record.review_status!='Reviewed':missing.append('Review form answers')
            try: duplicates=json.loads(booking.event_schedule or '{}').get('intake_options',{}).get('possible_duplicates',[])
            except (ValueError,AttributeError):duplicates=[]
            if duplicates:missing.append('Possible repeat request: '+', '.join(duplicates))
            checklist.append(dict(booking=booking,missing=missing))
        return render_template('form_insights.html',form=form,views=len(activity),starts=sum(row.started for row in activity),completions=sum(row.completed for row in activity),progress=progress,waiting=Waiting.query.filter_by(form_id=form.id).order_by(Waiting.created_at.desc()).all(),checklist=checklist,csrf=csrf())

    def download(lines,filename):
        response=send_file(BytesIO(pdf_document(lines)),mimetype='application/pdf',as_attachment=True,download_name=filename)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response

    @app.get('/forms/submissions/<token>/pdf')
    def native_submission_pdf(token):
        item=Submission.query.filter_by(token=token).first_or_404();account=current_client()
        if not account or account.id!=item.client_id: abort(404)
        record=records['submission_record'](item)
        snapshot=json.loads(record.snapshot_json) if record else {}
        lines=['CL Paints - '+item.title_snapshot,'Reference: F-'+str(item.id),'Submitted: '+str(item.created_at),'Name: '+item.name,'Email: '+item.email,'']
        for block in snapshot.get('fields',[]):
            if block['type'] in ('heading','content','pagebreak'):lines.extend([block['label'],block.get('content',''),''])
        for label,value in json.loads(item.answers_json).items():
            if isinstance(value,dict) and 'strokes' in value: value='Drawn signature supplied by '+value.get('name','')+'. Drawing retained with the original response.'
            elif isinstance(value,list): value='; '.join(', '.join(str(k)+': '+str(v) for k,v in row.items()) if isinstance(row,dict) else str(row) for row in value)
            lines.extend([label,str(value),''])
        lines+=['Accepted rules / permissions',item.terms_snapshot]
        return download(lines,'CL-Paints-form-response.pdf')

    @app.get('/client/bookings/<int:booking_id>/pdf')
    def booking_response_pdf(booking_id):
        booking=db.get_or_404(Booking,booking_id);account=current_client()
        if not account or account.email.casefold()!=booking.email.casefold(): abort(404)
        lines=['CL Paints booking request',booking.public_reference,'Status: '+booking.status,'Name: '+booking.first_name+' '+booking.last_name,'Email: '+booking.email,'Event estimate: £'+str(booking.total_event_cost),'Payment preference: '+booking.payment_preference]
        for i,event in enumerate(app.extensions['booking_schedule'](booking),1):
            lines+=['',f'Event {i}']+[str(key).replace('_',' ').title()+': '+str(value) for key,value in event.items() if value is not None]
        detail=records['booking_details'](booking)
        if detail:
            lines+=['',detail['snapshot'].get('title','')]
            for label,value in detail['answers'].items(): lines += [label+': '+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))]
            lines+=['Accepted seasonal information',detail['snapshot'].get('terms','')]
        try: intake=json.loads(booking.event_schedule or '{}').get('intake_options',{})
        except (ValueError,AttributeError):intake={}
        if intake:
            lines+=['','Package, extras and notes']
            if intake.get('package'):
                package=intake['package'];lines += [package['name']+' - £'+package['price']+' per event, '+package['hours']+' hours']
            for extra in intake.get('extras',[]): lines += [extra['name']+' - £'+extra['price']]
            if intake.get('travel_miles') and intake['travel_miles'] != '0':lines += ['Previously supplied one-way estimate: '+intake['travel_miles']]
            if intake.get('design_captions'):lines += ['Photo captions: '+intake['design_captions']]
        lines+=['Terms accepted: '+str(booking.terms_accepted_at)+' (version '+booking.terms_version+')','Liability acknowledged: '+str(booking.liability_acknowledged),'', 'This is a copy of your request. Current status appears above; estimates remain subject to review.']
        return download(lines,'CL-Paints-'+booking.public_reference+'.pdf')

    api=dict(options=options,full=full,guard=guard,track=track,booking_check=booking_check)
    app.extensions['form_workflows']=api
    return api
