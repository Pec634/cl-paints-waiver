"""Native giveaway, private consent uploads, and seasonal booking definitions."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file
from sqlalchemy.exc import IntegrityError


def define_models(db):
    class BookingDesignMedia(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        booking_id=db.Column(db.Integer,db.ForeignKey('booking.id'),nullable=False,index=True)
        content=db.Column(db.LargeBinary,nullable=False)
        mime=db.Column(db.String(50),nullable=False)
        filename=db.Column(db.String(150),nullable=False)
    db._native_booking_media=BookingDesignMedia
    class NativeForm(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        kind=db.Column(db.String(20),nullable=False)
        title=db.Column(db.String(150),nullable=False)
        description=db.Column(db.Text,nullable=False,default='')
        terms=db.Column(db.Text,nullable=False,default='')
        fields_json=db.Column(db.Text,nullable=False,default='[]')
        enabled=db.Column(db.Boolean,nullable=False,default=False)
        starts_at=db.Column(db.DateTime)
        ends_at=db.Column(db.DateTime)
    class NativeSubmission(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        form_id=db.Column(db.Integer,db.ForeignKey('native_form.id'),nullable=False,index=True)
        client_id=db.Column(db.Integer,db.ForeignKey('client_account.id'),nullable=False)
        token=db.Column(db.String(64),nullable=False,unique=True)
        giveaway_key=db.Column(db.String(100),unique=True)
        email=db.Column(db.String(255),nullable=False)
        name=db.Column(db.String(255),nullable=False)
        answers_json=db.Column(db.Text,nullable=False)
        terms_snapshot=db.Column(db.Text,nullable=False)
        title_snapshot=db.Column(db.String(150),nullable=False)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
        email_sent=db.Column(db.Boolean,nullable=False,default=False)
    class ConsentMedia(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        submission_id=db.Column(db.Integer,db.ForeignKey('native_submission.id'),nullable=False,index=True)
        content=db.Column(db.LargeBinary,nullable=False)
        mime=db.Column(db.String(50),nullable=False)
        filename=db.Column(db.String(150),nullable=False)
    return NativeForm,NativeSubmission,ConsentMedia


def available(form, now=None):
    now=now or datetime.utcnow()
    return form and form.enabled and (not form.starts_at or form.starts_at<=now) and (not form.ends_at or now<form.ends_at)


def answers(form, submitted):
    result={}
    for index,field in enumerate(json.loads(form.fields_json)):
        value=submitted.get('custom_'+str(index),'').strip()
        if field['required'] and not value:raise ValueError('Complete '+field['label']+'.')
        if len(value)>2000:raise ValueError(field['label']+' is too long.')
        if value and field['type']=='number':
            try:
                if not Decimal(value).is_finite():raise ValueError('Enter a valid number for '+field['label']+'.')
            except InvalidOperation:raise ValueError('Enter a valid number for '+field['label']+'.')
        if value and field['type']=='date':
            try:datetime.strptime(value,'%Y-%m-%d')
            except ValueError:raise ValueError('Enter a valid date for '+field['label']+'.')
        if value and field['type']=='select' and value not in field.get('options',[]):raise ValueError('Choose a listed option for '+field['label']+'.')
        if value and field['type']=='checkbox' and value!='yes':raise ValueError('Confirm '+field['label']+'.')
        result[field['label']]=value
    return result


def register(app,db,models,Account,Booking,current_client,admin_required,send_email):
    Form,Submission,Media=models
    from native_form_presets import PRESETS
    if app.config.get('MAX_CONTENT_LENGTH') is None:app.config['MAX_CONTENT_LENGTH']=100_000_000
    app.extensions['native_form_models']=models
    app.extensions['native_booking_media']=db._native_booking_media
    @app.context_processor
    def native_context():
        return dict(native_forms=[f for f in Form.query.order_by(Form.id.desc()).all() if available(f)],native_form_fields=lambda f: json.loads(f.fields_json))

    def csrf():return session.setdefault('client_csrf',secrets.token_urlsafe(32))
    def check():
        if not secrets.compare_digest(csrf(),request.form.get('csrf_token','')):abort(400)

    @app.route('/admin/native-forms',methods=['GET','POST'])
    @admin_required
    def native_forms_admin():
        if request.method=='POST':
            check()
            try:
                if request.form.get('action')=='preset':
                    preset=PRESETS.get(request.form.get('preset'))
                    if not preset:raise ValueError('Choose a listed template.')
                    form=Form(kind=preset['kind'],title=preset['title'],description=preset['description'],terms=preset['terms'],fields_json=json.dumps(preset['fields']))
                    db.session.add(form)
                elif request.form.get('action')=='toggle':
                    form=db.get_or_404(Form,request.form.get('id',type=int));form.enabled=not form.enabled
                else:
                    kind=request.form.get('kind');title=request.form.get('title','').strip()
                    terms=request.form.get('terms','').strip();description=request.form.get('description','').strip()
                    if kind not in ('giveaway','photo','booking') or not title or len(title)>150 or len(description)>2000 or len(terms)>10000:
                        raise ValueError('Check the form type, title and text lengths.')
                    if kind in ('giveaway','photo') and not terms:raise ValueError('Add the giveaway rules or photography permissions before creating this form.')
                    fields=[]
                    for line in request.form.get('fields','').splitlines():
                        if not line.strip():continue
                        parts=[p.strip() for p in line.split('|')]
                        if len(parts) not in (3,4) or not parts[0] or len(parts[0])>150 or parts[1] not in ('text','textarea','number','date','checkbox','select') or parts[2] not in ('required','optional'):
                            raise ValueError('Use Question | type | required/optional; select questions also need | choices separated by commas.')
                        if any(f['label']==parts[0] for f in fields):raise ValueError('Question labels must be unique.')
                        fields.append(dict(label=parts[0],type=parts[1],required=parts[2]=='required'))
                        if parts[1]=='select':
                            choices=[v.strip() for v in parts[3].split(',') if v.strip()] if len(parts)==4 else []
                            if not choices or len(choices)>20 or any(len(v)>150 for v in choices):raise ValueError('Provide up to twenty short choices for each select question.')
                            fields[-1]['options']=choices
                    if len(fields)>10:raise ValueError('Use up to ten extra questions.')
                    def stamp(value):
                        if not value:return None
                        parsed=datetime.fromisoformat(value)
                        if parsed.tzinfo:raise ValueError('Use UK local times.')
                        return parsed.replace(tzinfo=ZoneInfo('Europe/London')).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                    start=stamp(request.form.get('starts_at'));end=stamp(request.form.get('ends_at'))
                    if start and end and end<=start:raise ValueError('Closing time must follow opening time.')
                    form_id=request.form.get('id',type=int)
                    form=db.get_or_404(Form,form_id) if form_id else Form(kind=kind)
                    if form.enabled or form.kind!=kind:raise ValueError('Unpublish before editing; form type cannot change.')
                    form.title=title;form.description=description;form.terms=terms;form.fields_json=json.dumps(fields);form.starts_at=start;form.ends_at=end
                    db.session.add(form)
                db.session.commit();flash('Saved. New forms start as drafts; publish when ready.','success')
            except ValueError as error:
                db.session.rollback();flash(str(error),'error')
            return redirect(url_for('native_forms_admin'))
        edit_id=request.args.get('edit',type=int)
        edit_form=db.get_or_404(Form,edit_id) if edit_id else None
        def local(value):return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/London')).strftime('%Y-%m-%dT%H:%M') if value else ''
        return render_template('admin_native_forms.html',forms=Form.query.order_by(Form.id.desc()).all(),csrf=csrf(),edit_form=edit_form,
            edit_fields='\n'.join(f"{f['label']} | {f['type']} | {'required' if f['required'] else 'optional'}"+(' | '+', '.join(f['options']) if f.get('options') else '') for f in json.loads(edit_form.fields_json)) if edit_form else '',local=local)

    @app.get('/forms/<int:form_id>')
    def native_form_open(form_id):
        form=db.get_or_404(Form,form_id)
        if not available(form):abort(404)
        if form.kind=='booking':return redirect(url_for('booking_request',seasonal=form.id))
        if not current_client():
            session['native_return_form']=form.id
            return redirect(url_for('client.login'))
        return render_template('native_form.html',form=form,fields=json.loads(form.fields_json),csrf=csrf(),
            submission_token=session.setdefault('native_form_'+str(form.id),secrets.token_urlsafe(32)))

    @app.post('/forms/<int:form_id>')
    def native_form_submit(form_id):
        form=db.get_or_404(Form,form_id);account=current_client()
        if not account:abort(401)
        check()
        if not available(form) or form.kind=='booking':abort(404)
        token=session.get('native_form_'+str(form.id),'')
        if not token or not secrets.compare_digest(token,request.form.get('submission_token','')):abort(400)
        if request.content_length and request.content_length>32_000_000:abort(413)
        try:
            data=answers(form,request.form)
            if request.form.get('agree')!='yes':raise ValueError('Confirm that you accept the displayed rules or permissions.')
            uploads=[]
            if form.kind=='photo':
                people=request.form.get('people','').strip()
                data['Relationship to participants']=people
                if any(field['label']=='Signature — type your full name' for field in json.loads(form.fields_json)) and not request.form.get('participants'):
                    raise ValueError('Add the participant names and their individual photography permissions.')
                if request.form.get('participants'):
                    try:participants=json.loads(request.form['participants'])
                    except ValueError:raise ValueError('Check the participant details.')
                    if not isinstance(participants,list) or not 1<=len(participants)<=20:raise ValueError('Add one to twenty participants.')
                    if any(not isinstance(p,dict) or not isinstance(p.get('name'),str) or not p['name'].strip() or len(p['name'])>150 or p.get('consent') is not True for p in participants):raise ValueError('Name every participant and confirm their photography permission.')
                    data['Participants']=participants
                    people='; '.join(p['name'].strip() for p in participants)
                if not people or len(people)>2000 or request.form.get('authority')!='yes':raise ValueError('Name the people shown and confirm you have authority to submit their media and consent.')
                data.update(people=people,authority_confirmed=True)
                files=[f for f in request.files.getlist('media') if f.filename]
                if not 1<=len(files)<=3:raise ValueError('Choose one to three photos or videos.')
                for upload in files:
                    content=upload.stream.read(10_000_001)
                    if not content or len(content)>10_000_000:raise ValueError('Each file must be smaller than 10 MB.')
                    if content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
                    elif content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
                    elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
                    elif content[4:8]==b'ftyp':mime,extension='video/mp4','mp4'
                    else:raise ValueError('Use JPG, PNG, WebP or MP4 media.')
                    uploads.append((content,mime,'upload-'+str(len(uploads)+1)+'.'+extension))
            item=Submission(form_id=form.id,client_id=account.id,token=token,giveaway_key=f'{form.id}:{account.id}' if form.kind=='giveaway' else None,
                email=account.email,name=(account.first_name+' '+account.last_name).strip(),answers_json=json.dumps(data),terms_snapshot=form.terms,title_snapshot=form.title)
            db.session.add(item);db.session.flush()
            for content,mime,filename in uploads:db.session.add(Media(submission_id=item.id,content=content,mime=mime,filename=filename))
            db.session.commit()
            item.email_sent=send_email(account.email,'CL Paints: '+form.title+' received',f'Hello {account.first_name},\n\nWe received your submission for {form.title}. Reference: F-{item.id}.\n\nThis is not a booking confirmation or notification of a giveaway win.\n\nCL Paints')
            db.session.commit();session.pop('native_form_'+str(form.id),None)
            flash('Submission received. Reference F-'+str(item.id)+'.','success')
            return redirect(url_for('native_form_submission',submission_id=item.id))
        except IntegrityError:
            db.session.rollback();flash('This entry has already been received. Giveaway entry is limited to one per account per giveaway.','error')
        except ValueError as error:
            db.session.rollback();flash(str(error),'error')
        return redirect(url_for('native_form_open',form_id=form.id))

    @app.get('/client/form-submissions/<int:submission_id>')
    def native_form_submission(submission_id):
        account=current_client();item=db.get_or_404(Submission,submission_id)
        if not account or item.client_id!=account.id:abort(404)
        return render_template('native_submission.html',item=item,answers=json.loads(item.answers_json),media=Media.query.filter_by(submission_id=item.id).all())

    @app.get('/client/form-submissions')
    def native_my_submissions():
        account=current_client()
        if not account:return redirect(url_for('client.login'))
        return render_template('native_my_submissions.html',entries=Submission.query.filter_by(client_id=account.id).order_by(Submission.id.desc()).all())

    @app.get('/admin/native-forms/<int:form_id>/submissions')
    @admin_required
    def native_form_entries(form_id):
        form=db.get_or_404(Form,form_id)
        entries=Submission.query.filter_by(form_id=form.id).order_by(Submission.id.desc()).all()
        booking_entries=[]
        if form.kind=='booking':
            for booking in Booking.query.order_by(Booking.id.desc()).all():
                try:details=json.loads(booking.event_schedule or '{}').get('seasonal_form')
                except (ValueError,AttributeError):continue
                if details and details.get('id')==form.id:booking_entries.append(dict(booking=booking,details=details,media=db._native_booking_media.query.filter_by(booking_id=booking.id).all()))
        return render_template('admin_native_entries.html',form=form,entries=[dict(item=item,answers=json.loads(item.answers_json),media=Media.query.filter_by(submission_id=item.id).all()) for item in entries],booking_entries=booking_entries)

    @app.get('/form-media/<int:media_id>')
    def native_media(media_id):
        media=db.get_or_404(Media,media_id);item=db.session.get(Submission,media.submission_id);account=current_client()
        if not session.get('admin_authenticated') and (not account or account.id!=item.client_id):abort(404)
        if session.get('admin_authenticated'):
            last=session.get('admin_last_activity',datetime.utcnow().timestamp())
            if datetime.utcnow().timestamp()-last>1800:abort(403)
        response=send_file(BytesIO(media.content),mimetype=media.mime,as_attachment=True,download_name=media.filename)
        response.headers['Cache-Control']='no-store';return response

    @app.get('/admin/booking-design-media/<int:media_id>')
    @admin_required
    def native_booking_media(media_id):
        media=db.get_or_404(db._native_booking_media,media_id)
        response=send_file(BytesIO(media.content),mimetype=media.mime,as_attachment=True,download_name=media.filename)
        response.headers['Cache-Control']='no-store'
        return response


def design_uploads(files):
    files=[file for file in files if file.filename]
    if len(files)>6:raise ValueError('Upload up to six design images.')
    uploads=[]
    for file in files:
        content=file.stream.read(15_000_001)
        if not content or len(content)>15_000_000:raise ValueError('Each design image must be no larger than 15 MB.')
        if content.startswith(b'\x89PNG\r\n\x1a\n'):mime,extension='image/png','png'
        elif content.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','jpg'
        elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime,extension='image/webp','webp'
        else:raise ValueError('Design ideas must be JPG, PNG or WebP images.')
        uploads.append(dict(content=content,mime=mime,filename=f'design-{len(uploads)+1}.{extension}'))
    return uploads
