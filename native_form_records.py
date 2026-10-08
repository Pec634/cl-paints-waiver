"""Versioned form settings, private files, drafts and administrator review tools."""
import csv
from datetime import datetime
from io import BytesIO, StringIO
import hashlib
import json
import re
import secrets
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for, send_file
from werkzeug.utils import secure_filename
from sqlalchemy.orm import defer

STATUSES = ('New', 'In progress', 'Reviewed', 'Follow up')


def define_models(db):
    class FormSettings(db.Model):
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), primary_key=True)
        settings_json = db.Column(db.Text, nullable=False, default='{}')
    class FormVersion(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False, index=True)
        number = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('form_id', 'number'),)
    class FormSubmissionRecord(db.Model):
        submission_id = db.Column(db.Integer, db.ForeignKey('native_submission.id'), primary_key=True)
        version_id = db.Column(db.Integer, db.ForeignKey('form_version.id'))
        snapshot_json = db.Column(db.Text, nullable=False, default='{}')
        review_status = db.Column(db.String(30), nullable=False, default='New')
        note = db.Column(db.Text, nullable=False, default='')
    class FormBookingRecord(db.Model):
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False, index=True)
        version_id = db.Column(db.Integer, db.ForeignKey('form_version.id'))
        snapshot_json = db.Column(db.Text, nullable=False, default='{}')
        review_status = db.Column(db.String(30), nullable=False, default='New')
        note = db.Column(db.Text, nullable=False, default='')
    class FormDraft(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False)
        owner_key = db.Column(db.String(100), nullable=False)
        fingerprint = db.Column(db.String(64), nullable=False)
        answers_json = db.Column(db.Text, nullable=False, default='{}')
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        __table_args__ = (db.UniqueConstraint('form_id', 'owner_key'),)
    class FormFieldFile(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        submission_id = db.Column(db.Integer, db.ForeignKey('native_submission.id'), index=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), index=True)
        label = db.Column(db.String(150), nullable=False)
        filename = db.Column(db.String(150), nullable=False)
        mime = db.Column(db.String(50), nullable=False)
        content = db.Column(db.LargeBinary, nullable=False)
    db._native_extra_models = (FormSettings, FormVersion, FormSubmissionRecord, FormBookingRecord, FormDraft, FormFieldFile)


def read_form_files(form, files):
    uploads = []; size = 0
    for index, field in enumerate(json.loads(form.fields_json)):
        if field['type'] != 'file': continue
        chosen = [file for file in files.getlist('custom_'+str(index)) if file.filename]
        if len(chosen) > field['max_files']: raise ValueError('Too many files for '+field['label']+'.')
        for file in chosen:
            content = file.stream.read(10_000_001); size += len(content)
            if not content or len(content) > 10_000_000 or size > 30_000_000:
                raise ValueError('Each attachment must be under 10 MB; combined uploads must be under 30 MB.')
            if content.startswith(b'\x89PNG\r\n\x1a\n'): mime, extension, group = 'image/png', 'png', 'images'
            elif content.startswith(b'\xff\xd8\xff'): mime, extension, group = 'image/jpeg', 'jpg', 'images'
            elif content[:4] == b'RIFF' and content[8:12] == b'WEBP': mime, extension, group = 'image/webp', 'webp', 'images'
            elif content.startswith(b'%PDF-'): mime, extension, group = 'application/pdf', 'pdf', 'pdf'
            else: raise ValueError('Use JPG, PNG, WebP or PDF attachments.')
            if group not in field['file_types']: raise ValueError('That file type is not allowed for '+field['label']+'.')
            filename = secure_filename(file.filename).rsplit('.', 1)[0][:135] or 'attachment'
            uploads.append(dict(label=field['label'], filename=filename+'.'+extension, mime=mime, content=content))
    return uploads


def upload_names(uploads):
    result = {}
    for upload in uploads: result.setdefault(upload['label'], []).append(upload['filename'])
    return result


def validate_settings(submitted):
    result = {}
    for key, limit in [('confirmation_text', 2000), ('email_subject', 150), ('email_body', 5000)]:
        value = submitted.get(key, '').strip()
        if len(value) > limit or (key == 'email_subject' and ('\n' in value or '\r' in value)):
            raise ValueError('Check the confirmation text and email lengths.')
        result[key] = value
    from form_workflows import validate_options
    result.update(validate_options(submitted))
    return result


def confirmation(settings, name, title, reference):
    tokens = {'first_name': name, 'form_title': title, 'reference': reference}
    result = {}
    for key in ('confirmation_text','email_subject','email_body'):
        value = settings.get(key,'')
        for token, text in tokens.items(): value = value.replace('{'+token+'}', str(text))
        if key=='email_subject': value=' '.join(value.splitlines())
        result[key] = value
    return result


def csv_cell(value):
    if isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False)
    text = str(value or '')
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')): text = "'"+text
    return text


def register(app, db, models, Account, Booking, current_client, admin_required, available, csrf, check):
    Form, Submission, Media = models
    Settings, Version, SubmissionRecord, BookingRecord, Draft, FieldFile = db._native_extra_models

    def settings(form):
        row = db.session.get(Settings, form.id)
        return json.loads(row.settings_json) if row else {}

    def set_settings(form, values):
        row = db.session.get(Settings, form.id) or Settings(form_id=form.id)
        row.settings_json = json.dumps(values); db.session.add(row)

    def snapshot(form):
        return dict(title=form.title, description=form.description, terms=form.terms, kind=form.kind,
            fields=json.loads(form.fields_json), settings=settings(form), enabled=bool(form.enabled),
            starts_at=form.starts_at.isoformat() if form.starts_at else None,
            ends_at=form.ends_at.isoformat() if form.ends_at else None)

    def record_version(form):
        db.session.flush()
        data = json.dumps(snapshot(form), sort_keys=True)
        latest = Version.query.filter_by(form_id=form.id).order_by(Version.number.desc()).first()
        if latest and latest.snapshot_json == data: return latest
        version = Version(form_id=form.id, number=latest.number+1 if latest else 1, snapshot_json=data)
        db.session.add(version); db.session.flush(); return version

    def save_files(uploads, values, submission_id=None, booking_id=None):
        for upload in uploads:
            if upload['label'] in values:
                db.session.add(FieldFile(submission_id=submission_id, booking_id=booking_id, **upload))

    def record_submission(form, item, values, uploads):
        version = record_version(form)
        db.session.add(SubmissionRecord(submission_id=item.id, version_id=version.id, snapshot_json=version.snapshot_json))
        save_files(uploads, values, submission_id=item.id)

    def record_booking(form, booking, values, uploads):
        db.session.flush(); version = record_version(form)
        db.session.add(BookingRecord(booking_id=booking.id, form_id=form.id, version_id=version.id, snapshot_json=version.snapshot_json))
        save_files(uploads, values, booking_id=booking.id)

    def owner():
        account = current_client()
        if account: return 'client:'+str(account.id)
        return 'browser:'+session.setdefault('native_draft_owner', secrets.token_urlsafe(32))

    def fingerprint(form):
        return hashlib.sha256(json.dumps(snapshot(form), sort_keys=True).encode()).hexdigest()

    def clear_draft(form):
        Draft.query.filter_by(form_id=form.id, owner_key=owner()).delete()

    def booking_details(booking):
        record=db.session.get(BookingRecord,booking.id)
        if not record: return None
        data=json.loads(record.snapshot_json)
        detail=json.loads(booking.event_schedule or '{}').get('seasonal_form',{})
        data=data or detail.get('snapshot') or dict(title=detail.get('title','Seasonal form'),terms=detail.get('terms',''),fields=[])
        return dict(snapshot=data,answers=detail.get('answers',{}),files=FieldFile.query.options(defer(FieldFile.content)).filter_by(booking_id=booking.id).all(),
            confirmation=confirmation(data.get('settings',{}),booking.first_name,data.get('title',''),booking.public_reference).get('confirmation_text',''))

    @app.route('/forms/<int:form_id>/draft', methods=['GET', 'POST', 'DELETE'])
    def native_form_draft(form_id):
        form = db.get_or_404(Form, form_id)
        if not available(form): abort(404)
        if form.kind != 'booking' and not current_client(): abort(401)
        key = owner(); stamp = fingerprint(form)
        draft = Draft.query.filter_by(form_id=form.id, owner_key=key).first()
        if request.method == 'GET':
            return jsonify(answers=json.loads(draft.answers_json) if draft and draft.fingerprint == stamp else {},
                outdated=bool(draft and draft.fingerprint != stamp), csrf_token=csrf(), fingerprint=stamp,
                updated_at=draft.updated_at.isoformat() if draft else None, cross_device=bool(current_client())),200,{'Cache-Control':'no-store'}
        if not secrets.compare_digest(csrf(), request.headers.get('X-CSRF-Token', '')): abort(400)
        if request.method == 'DELETE':
            if draft: db.session.delete(draft); db.session.commit()
            return jsonify(saved=False)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('fingerprint') != stamp: return jsonify(error='The form changed. Reload before saving a new draft.'),409
        data = payload.get('answers')
        if not isinstance(data, dict) or len(data) > 250 or len(json.dumps(data)) > 150_000: return jsonify(error='The draft is too large.'),400
        fields = json.loads(form.fields_json)
        allowed_custom = {'custom_'+str(index) for index, field in enumerate(fields) if field['type'] not in ('signature', 'file', 'checkbox', 'calculation', 'content', 'heading', 'image', 'pagebreak')}
        allowed_booking = {'title','first_name','last_name','phone','email','client_type','job_title','company_name','company_number','vat_number','date_of_birth','ethnicity','ethnicity_detail','religion','single_date','all_dates_same_details','event_schedule','payment_preference','promo_code','additional_info'}
        allowed_booking.update({'address_'+part for part in ('property','street','city','postcode','country')})
        allowed_booking.update({'booking_package','booking_extras','travel_miles','design_captions'})
        clean = {}
        for name, value in data.items():
            if name not in allowed_custom and not (form.kind == 'booking' and name in allowed_booking): continue
            if isinstance(value, str) and len(value) <= 100_000:
                if name in allowed_custom and fields[int(name.rsplit('_',1)[1])]['type']=='repeat':
                    field=fields[int(name.rsplit('_',1)[1])]
                    try: rows=json.loads(value or '[]')
                    except ValueError: return jsonify(error='Check the saved repeating rows.'),400
                    if not isinstance(rows,list) or len(rows)>field['max_items'] or any(not isinstance(row,dict) for row in rows): return jsonify(error='Check the saved repeating rows.'),400
                    rows=[{child['label']:row.get(child['label'],'') for child in field['children'] if child['type']!='checkbox'} for row in rows]
                    if any(not isinstance(answer,str) or len(answer)>2000 for row in rows for answer in row.values()): return jsonify(error='Check the saved repeating answers.'),400
                    value=json.dumps(rows)
                clean[name] = value
            elif isinstance(value, list) and len(value) <= 20 and all(isinstance(v, str) and len(v) <= 2000 for v in value): clean[name] = value
            else: return jsonify(error='Check the draft answers.'),400
        draft = draft or Draft(form_id=form.id, owner_key=key)
        draft.fingerprint=stamp; draft.answers_json=json.dumps(clean); draft.updated_at=datetime.utcnow()
        db.session.add(draft); db.session.commit()
        return jsonify(saved=True, updated_at=draft.updated_at.isoformat())

    @app.get('/form-files/<int:file_id>')
    def native_field_file(file_id):
        file = db.get_or_404(FieldFile, file_id)
        admin = session.get('admin_authenticated') and datetime.utcnow().timestamp()-session.get('admin_last_activity',0)<1800
        if not admin:
            account = current_client()
            if not account: abort(404)
            if file.submission_id:
                item = db.session.get(Submission, file.submission_id)
                if not item or item.client_id != account.id: abort(404)
            elif file.booking_id:
                booking = db.session.get(Booking, file.booking_id)
                if not booking or booking.email.lower() != account.email.lower(): abort(404)
            else: abort(404)
        response = send_file(BytesIO(file.content), mimetype=file.mime, as_attachment=True, download_name=file.filename)
        response.headers['Cache-Control']='no-store'; response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.post('/admin/native-forms/<int:form_id>/restore/<int:version_id>')
    @admin_required
    def native_form_restore(form_id, version_id):
        check(); form=db.get_or_404(Form, form_id); version=db.get_or_404(Version, version_id)
        if version.form_id != form.id: abort(404)
        if form.enabled:
            flash('Unpublish the form before restoring an earlier version.', 'error')
        else:
            data=json.loads(version.snapshot_json)
            form.title=data['title']; form.description=data['description']; form.terms=data['terms']; form.fields_json=json.dumps(data['fields'])
            form.starts_at=datetime.fromisoformat(data['starts_at']) if data['starts_at'] else None
            form.ends_at=datetime.fromisoformat(data['ends_at']) if data['ends_at'] else None
            set_settings(form, data['settings']); record_version(form); db.session.commit()
            flash('Restored as a new draft version. Review dates and wording before publishing.', 'success')
        return redirect(url_for('native_forms_admin', edit=form.id))

    def entries(form):
        result=[]
        for item in Submission.query.filter_by(form_id=form.id).order_by(Submission.id.desc()).all():
            meta=db.session.get(SubmissionRecord,item.id)
            result.append(dict(type='submission',id=item.id,reference='F-'+str(item.id),name=item.name,email=item.email,
                created_at=item.created_at,answers=json.loads(item.answers_json),meta=meta,
                status=meta.review_status if meta else 'New',item=item,media=Media.query.options(defer(Media.content)).filter_by(submission_id=item.id).all(),
                files=FieldFile.query.options(defer(FieldFile.content)).filter_by(submission_id=item.id).all(),snapshot=json.loads(meta.snapshot_json) if meta else {},
                version=db.session.get(Version,meta.version_id) if meta and meta.version_id else None))
        if form.kind == 'booking':
            for booking in Booking.query.order_by(Booking.id.desc()).all():
                try: details=json.loads(booking.event_schedule or '{}').get('seasonal_form')
                except (ValueError,AttributeError): continue
                if not details or details.get('id') != form.id: continue
                meta=db.session.get(BookingRecord,booking.id)
                result.append(dict(type='booking',id=booking.id,reference=booking.public_reference,name=booking.first_name+' '+booking.last_name,
                    email=booking.email,created_at=booking.submitted_at,answers=details['answers'],meta=meta,status=meta.review_status if meta else 'New',
                    booking=booking,media=db._native_booking_media.query.options(defer(db._native_booking_media.content)).filter_by(booking_id=booking.id).all(),
                    files=FieldFile.query.options(defer(FieldFile.content)).filter_by(booking_id=booking.id).all(),snapshot=json.loads(meta.snapshot_json) if meta else {},
                    version=db.session.get(Version,meta.version_id) if meta and meta.version_id else None))
        selected_submission=request.args.get('submission',type=int)
        if selected_submission is not None:
            result=[row for row in result if row['type']=='submission' and row['id']==selected_submission]
        query=request.args.get('q','').strip().lower(); status=request.args.get('status','')
        return [row for row in result if (not status or row['status']==status) and (not query or query in (row['reference']+' '+row['name']+' '+row['email']+' '+json.dumps(row['answers'],ensure_ascii=False)).lower())]

    @app.get('/admin/native-forms/<int:form_id>/export')
    @admin_required
    def native_form_export(form_id):
        form=db.get_or_404(Form,form_id); rows=entries(form)
        labels=list(dict.fromkeys(label for row in rows for label in row['answers']))
        output=StringIO(); writer=csv.writer(output)
        writer.writerow(['Reference','Name','Email','Received UTC','Review status','Form version']+labels)
        for row in rows:
            writer.writerow([csv_cell(value) for value in [row['reference'],row['name'],row['email'],row['created_at'].isoformat(),row['status'],row['version'].number if row['version'] else 'Legacy']+[row['answers'].get(label,'') for label in labels]])
        response=send_file(BytesIO(output.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name='form-'+str(form.id)+'-responses.csv')
        response.headers['Cache-Control']='no-store'; return response

    @app.post('/admin/native-forms/<int:form_id>/review')
    @admin_required
    def native_form_review(form_id):
        check(); form=db.get_or_404(Form,form_id)
        status=request.form.get('review_status'); note=request.form.get('note','').strip()
        if status not in STATUSES or len(note)>2000: abort(400)
        identifier=request.form.get('entry_id',type=int)
        if request.form.get('entry_type')=='submission':
            item=db.get_or_404(Submission,identifier)
            if item.form_id!=form.id: abort(404)
            meta=db.session.get(SubmissionRecord,item.id) or SubmissionRecord(submission_id=item.id)
        elif request.form.get('entry_type')=='booking':
            booking=db.get_or_404(Booking,identifier)
            try: details=json.loads(booking.event_schedule or '{}').get('seasonal_form')
            except (ValueError,AttributeError): details=None
            if not details or details.get('id')!=form.id: abort(404)
            meta=db.session.get(BookingRecord,booking.id) or BookingRecord(booking_id=booking.id,form_id=form.id)
        else: abort(400)
        meta.review_status=status; meta.note=note; db.session.add(meta); db.session.commit()
        flash('Review status saved.','success'); return redirect(url_for('native_form_entries',form_id=form.id))

    api=dict(settings=settings,set_settings=set_settings,snapshot=snapshot,record_version=record_version,
        record_submission=record_submission,record_booking=record_booking,clear_draft=clear_draft,entries=entries,
        versions=lambda form: Version.query.filter_by(form_id=form.id).order_by(Version.number.desc()).all(),
        files=lambda submission_id: FieldFile.query.options(defer(FieldFile.content)).filter_by(submission_id=submission_id).all(),
        submission_record=lambda item: db.session.get(SubmissionRecord,item.id),booking_details=booking_details)
    app.extensions['native_form_records']=api
    return api
