"""Native giveaway, private consent uploads, and seasonal booking definitions."""
from datetime import datetime
from io import BytesIO
import json
import secrets
import hashlib
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file, jsonify
from sqlalchemy.exc import IntegrityError
from native_form_fields import parse_fields, field_answers
from native_form_records import define_models as define_record_models, register as register_records, validate_settings, confirmation, read_form_files, upload_names, STATUSES
from native_form_features import signature_path, accessibility_issues


def define_models(db):
    define_record_models(db)
    from form_workflows import define_models as define_workflow_models
    define_workflow_models(db)
    class NativeFormImage(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        content=db.Column(db.LargeBinary,nullable=False)
        mime=db.Column(db.String(50),nullable=False)
    db._native_form_image=NativeFormImage
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


def answers(form, submitted, uploads=None):
    return field_answers(form, submitted, uploads)


def register(app,db,models,Account,Booking,current_client,admin_required,send_email):
    Form,Submission,Media=models
    from native_form_presets import PRESETS
    if app.config.get('MAX_CONTENT_LENGTH') is None:app.config['MAX_CONTENT_LENGTH']=100_000_000
    app.extensions['native_form_models']=models
    app.extensions['native_booking_media']=db._native_booking_media
    @app.context_processor
    def native_context():
        return dict(native_forms=[f for f in Form.query.order_by(Form.id.desc()).all() if available(f)],native_form_fields=lambda f: json.loads(f.fields_json),native_signature_path=signature_path,
            native_form_settings=lambda f: records['settings'](f),native_booking_details=lambda booking: records['booking_details'](booking))

    def csrf():return session.setdefault('client_csrf',secrets.token_urlsafe(32))
    def check():
        if not secrets.compare_digest(csrf(),request.form.get('csrf_token','')):abort(400)
    records=register_records(app,db,models,Account,Booking,current_client,admin_required,available,csrf,check)
    from form_workflows import register as register_workflows
    workflows=register_workflows(app,db,models,Booking,current_client,admin_required,available,records,csrf,check)
    def revision(form):return hashlib.sha256(json.dumps(records['snapshot'](form),sort_keys=True).encode()).hexdigest()
    def publish_checks(form):
        from form_publish_checks import checklist
        return checklist(form,records['settings'](form),lambda identity:db.session.get(db._native_form_image,identity) is not None)

    @app.get('/admin/native-forms/<int:form_id>/checklist')
    @admin_required
    def native_form_checklist(form_id):
        response=jsonify(publish_checks(db.get_or_404(Form,form_id)));response.headers['Cache-Control']='no-store';return response

    @app.post('/admin/native-form-images')
    @admin_required
    def native_form_image_upload():
        check()
        upload=request.files.get('image')
        if not upload or not upload.filename:return jsonify(error='Choose a JPG, PNG or WebP image.'),400
        content=upload.stream.read(5_000_001)
        if not content or len(content)>5_000_000:return jsonify(error='Images must be no larger than 5 MB.'),400
        if content.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
        elif content.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
        elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':mime='image/webp'
        else:return jsonify(error='Use JPG, PNG or WebP images.'),400
        image=db._native_form_image(content=content,mime=mime)
        db.session.add(image);db.session.commit()
        return jsonify(url=url_for('native_form_image',image_id=image.id),mime=mime),201

    @app.get('/form-images/<int:image_id>')
    def native_form_image(image_id):
        image=db.get_or_404(db._native_form_image,image_id)
        source=url_for('native_form_image',image_id=image.id)
        admin=session.get('admin_authenticated') and datetime.utcnow().timestamp()-session.get('admin_last_activity',0)<1800
        if not admin:
            referenced=False
            for form in Form.query.filter_by(enabled=True).all():
                if not available(form):continue
                for field in json.loads(form.fields_json):
                    if field.get('src')==source or source in field.get('option_images',{}).values():referenced=True;break
                from form_workflows import catalog
                settings=records['settings'](form)
                if any(row.get('image')==source for key in ('packages','extras') for row in catalog(settings.get(key,''),key)):referenced=True
                if referenced:break
            if not referenced:abort(404)
        response=send_file(BytesIO(image.content),mimetype=image.mime)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.route('/admin/native-forms',methods=['GET','POST'])
    @admin_required
    def native_forms_admin():
        submitted = None
        if request.method=='POST':
            check()
            try:
                if request.form.get('action')=='preset':
                    preset=PRESETS.get(request.form.get('preset'))
                    if not preset:raise ValueError('Choose a listed template.')
                    form=Form(kind=preset['kind'],title=preset['title'],description=preset['description'],terms=preset['terms'],fields_json=json.dumps(preset['fields']))
                    db.session.add(form)
                elif request.form.get('action')=='duplicate':
                    source=db.get_or_404(Form,request.form.get('id',type=int))
                    form=Form(kind=source.kind,title=source.title[:143]+' (copy)',description=source.description,
                        terms=source.terms,fields_json=source.fields_json,enabled=False)
                    db.session.add(form)
                    db.session.flush();records['set_settings'](form,records['settings'](source))
                elif request.form.get('action')=='toggle':
                    form=db.get_or_404(Form,request.form.get('id',type=int))
                    if not form.enabled:
                        result=publish_checks(form)
                        if not result['ready']:raise ValueError('Before publishing: '+' '.join(result['errors']))
                    form.enabled=not form.enabled
                else:
                    kind=request.form.get('kind');title=request.form.get('title','').strip()
                    terms=request.form.get('terms','').strip();description=request.form.get('description','').strip()
                    if kind not in ('giveaway','photo','booking') or not title or len(title)>150 or len(description)>2000 or len(terms)>10000:
                        raise ValueError('Check the form type, title and text lengths.')
                    if kind in ('giveaway','photo') and not terms:raise ValueError('Add the giveaway rules or photography permissions before creating this form.')
                    fields=parse_fields(request.form)
                    settings_data=validate_settings(request.form)
                    from form_workflows import catalog
                    for key in ('packages','extras'):
                        for row in catalog(settings_data.get(key,''),key):
                            source=row.get('image','')
                            if source.startswith('/form-images/') and not db.session.get(db._native_form_image,int(source.rsplit('/',1)[1])):
                                raise ValueError('A package image is missing. Upload it again before saving.')
                    for field in fields:
                        sources=[field.get('src','')]+list(field.get('option_images',{}).values())
                        for source in sources:
                            if source.startswith('/form-images/') and not db.session.get(db._native_form_image,int(source.rsplit('/',1)[1])):
                                raise ValueError('An uploaded image is missing. Upload it again before saving.')
                    def stamp(value):
                        if not value:return None
                        parsed=datetime.fromisoformat(value)
                        if parsed.tzinfo:raise ValueError('Use UK local times.')
                        return parsed.replace(tzinfo=ZoneInfo('Europe/London')).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                    start=stamp(request.form.get('starts_at'));end=stamp(request.form.get('ends_at'))
                    if start and end and end<=start:raise ValueError('Closing time must follow opening time.')
                    form_id=request.form.get('id',type=int)
                    form=db.get_or_404(Form,form_id) if form_id else Form(kind=kind)
                    if request.form.get('action')=='autosave' and form_id:
                        form=Form.query.filter_by(id=form_id).populate_existing().with_for_update().first()
                        if request.form.get('revision')!=revision(form):
                            return jsonify(error='This draft changed in another tab. Reload before continuing; your current edits have not been overwritten.'),409
                    if form.enabled or form.kind!=kind:raise ValueError('Unpublish before editing; form type cannot change.')
                    form.title=title;form.description=description;form.terms=terms;form.fields_json=json.dumps(fields);form.starts_at=start;form.ends_at=end
                    db.session.add(form)
                    db.session.flush();records['set_settings'](form,settings_data)
                records['record_version'](form)
                db.session.commit()
                action=request.form.get('action')
                if action=='autosave':return jsonify(id=form.id,revision=revision(form),saved_at=datetime.utcnow().isoformat()+'Z')
                if action=='toggle':
                    message='Published. Responses are accepted during the availability window.' if form.enabled else 'Unpublished. Responses are paused; you can now edit the draft.'
                elif action=='duplicate':message='Created a draft copy. Set new opening and closing dates before publishing.'
                else:message='Draft saved. Review it, then publish from Your forms when ready.'
                flash(message,'success')
                if request.form.get('action') in ('preset','duplicate') or not request.form.get('action'):
                    return redirect(url_for('native_forms_admin',edit=form.id))
            except ValueError as error:
                db.session.rollback()
                if request.form.get('action')=='autosave':
                    return jsonify(error=str(error)),400
                flash(str(error),'error')
                if not request.form.get('action'):submitted=request.form
            if submitted is None:return redirect(url_for('native_forms_admin'))
        edit_id=submitted.get('id',type=int) if submitted is not None else request.args.get('edit',type=int)
        edit_form=db.get_or_404(Form,edit_id) if edit_id else None
        def local(value):return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/London')).strftime('%Y-%m-%dT%H:%M') if value else ''
        builder_fields=submitted.get('fields_json','') if submitted is not None else (edit_form.fields_json if edit_form else '[]')
        return render_template('admin_native_forms.html',forms=Form.query.order_by(Form.id.desc()).all(),csrf=csrf(),edit_form=edit_form,submitted=submitted,available=available,now=datetime.utcnow(),builder_fields=builder_fields,
            form_settings=records['settings'](edit_form) if edit_form else {},versions=records['versions'](edit_form) if edit_form else [],builder_revision=revision(edit_form) if edit_form else '',
            edit_fields='\n'.join(f"{f['label']} | {f['type']} | {'required' if f['required'] else 'optional'}"+(' | '+', '.join(f['options']) if f.get('options') else '') for f in json.loads(edit_form.fields_json)) if edit_form else '',local=local)

    @app.get('/forms/<int:form_id>')
    def native_form_open(form_id):
        form=db.get_or_404(Form,form_id)
        if not available(form):
            if form.enabled and records['settings'](form).get('waitlist_enabled')=='yes':return redirect(url_for('form_waiting_list',form_id=form.id))
            abort(404)
        if workflows['full'](form):
            if records['settings'](form).get('waitlist_enabled')=='yes':return redirect(url_for('form_waiting_list',form_id=form.id))
            abort(404)
        if form.kind=='booking':return redirect(url_for('booking_request',seasonal=form.id))
        if not current_client():
            session['native_return_form']=form.id
            return redirect(url_for('client.login'))
        workflows['track'](form);db.session.commit()
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
            workflows['guard']()
            Form.query.filter_by(id=form.id).with_for_update().first()
            if workflows['full'](form):raise ValueError('This form has reached its response limit. Contact CL Paints or join its waiting list.')
            field_uploads=read_form_files(form,request.files)
            data=answers(form,request.form,upload_names(field_uploads))
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
            records['record_submission'](form,item,data,field_uploads)
            for content,mime,filename in uploads:db.session.add(Media(submission_id=item.id,content=content,mime=mime,filename=filename))
            records['clear_draft'](form);workflows['track'](form,completed=True);db.session.commit()
            messages=confirmation(records['settings'](form),account.first_name,form.title,'F-'+str(item.id))
            item.email_sent=send_email(account.email,messages.get('email_subject') or 'CL Paints: '+form.title+' received',messages.get('email_body') or f'Hello {account.first_name},\n\nWe received your submission for {form.title}. Reference: F-{item.id}.\n\nThis is not a booking confirmation or notification of a giveaway win.\n\nCL Paints')
            db.session.commit();session.pop('native_form_'+str(form.id),None)
            flash('Submission received. Reference F-'+str(item.id)+'.','success')
            return redirect(url_for('native_form_submission',submission_id=item.id))
        except IntegrityError:
            db.session.rollback();flash('This entry has already been received. Giveaway entry is limited to one per account per giveaway.','error')
        except ValueError as error:
            db.session.rollback();flash(str(error),'error')
            return render_template('native_form.html',form=form,fields=json.loads(form.fields_json),csrf=csrf(),submission_token=token)
        return redirect(url_for('native_form_open',form_id=form.id))

    @app.get('/client/form-submissions/<int:submission_id>')
    def native_form_submission(submission_id):
        account=current_client();item=db.get_or_404(Submission,submission_id)
        if not account or item.client_id!=account.id:abort(404)
        meta=records['submission_record'](item)
        snapshot=json.loads(meta.snapshot_json) if meta else {}
        return render_template('native_submission.html',item=item,answers=json.loads(item.answers_json),media=Media.query.filter_by(submission_id=item.id).all(),
            files=records['files'](item.id),snapshot=snapshot,confirmation_message=confirmation(snapshot.get('settings',{}),account.first_name,item.title_snapshot,'F-'+str(item.id)).get('confirmation_text',''))

    @app.get('/client/form-submissions')
    def native_my_submissions():
        account=current_client()
        if not account:return redirect(url_for('client.login'))
        return render_template('native_my_submissions.html',entries=Submission.query.filter_by(client_id=account.id).order_by(Submission.id.desc()).all())

    @app.get('/admin/native-forms/<int:form_id>/submissions')
    @admin_required
    def native_form_entries(form_id):
        form=db.get_or_404(Form,form_id)
        rows=records['entries'](form);page=max(1,request.args.get('page',1,type=int))
        return render_template('admin_native_entries.html',form=form,rows=rows[(page-1)*25:page*25],total=len(rows),page=page,statuses=STATUSES,csrf=csrf())

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
