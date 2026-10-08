"""Admin-managed media for booking and reward notification layouts."""
import base64
from io import BytesIO
import html
import secrets
from urllib.parse import urlsplit
from zipfile import ZipFile, BadZipFile
from flask import abort, flash, redirect, request, session, url_for, send_file
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError

def define_model(db):
    class EmailMedia(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        area = db.Column(db.String(10), nullable=False)
        kind = db.Column(db.String(10), nullable=False)
        label = db.Column(db.String(150), nullable=False)
        filename = db.Column(db.String(255), nullable=False, default='')
        content_type = db.Column(db.String(100), nullable=False, default='')
        content = db.Column(db.LargeBinary)
        url = db.Column(db.String(2000), nullable=False, default='')
    return EmailMedia

def file_type(filename, content, kind):
    suffix=filename.rsplit('.',1)[-1].lower()
    images={'png':('image/png',b'\x89PNG\r\n\x1a\n'),'jpg':('image/jpeg',b'\xff\xd8\xff'),
            'jpeg':('image/jpeg',b'\xff\xd8\xff'),'gif':('image/gif',b'GIF8')}
    if suffix in images and content.startswith(images[suffix][1]):
        return images[suffix][0]
    if kind=='image': raise ValueError('Use a PNG, JPEG or GIF image.')
    if suffix=='pdf' and content.startswith(b'%PDF-'): return 'application/pdf'
    if suffix=='txt':
        try: content.decode('utf-8')
        except UnicodeDecodeError: raise ValueError('Text attachments must use UTF-8.') from None
        if b'\0' in content: raise ValueError('Upload a plain text document.')
        return 'text/plain'
    office={'docx':('word/document.xml','application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            'xlsx':('xl/workbook.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            'pptx':('ppt/presentation.xml','application/vnd.openxmlformats-officedocument.presentationml.presentation')}
    if suffix in office:
        try:
            with ZipFile(BytesIO(content)) as archive:
                names=archive.namelist()
                if len(names)>1000 or sum(info.file_size for info in archive.infolist())>20_000_000:
                    raise ValueError('This document is too large when expanded.')
                if office[suffix][0] in names and '[Content_Types].xml' in names and not any('vbaProject' in name for name in names):
                    return office[suffix][1]
        except BadZipFile: pass
    raise ValueError('Use PDF, DOCX, XLSX, PPTX, UTF-8 TXT, PNG, JPEG or GIF files. Macro-enabled documents are not supported.')

def register(app,db,Media,admin_required):
    def rows(kind):
        return Media.query.filter(Media.area.in_(['both',kind])).order_by(Media.id).all()
    def check():
        if not session.get('settings_csrf') or not secrets.compare_digest(session['settings_csrf'],request.form.get('csrf_token','')):
            abort(400)
    @app.context_processor
    def context():
        return {'email_media':Media.query.order_by(Media.id).all()} if request.endpoint in ('admin_settings','communications_templates') else {}
    @app.post('/admin/settings/email-media')
    @admin_required
    def email_media_add():
        check()
        try:
            area,kind=request.form.get('area'),request.form.get('kind')
            label=request.form.get('label','').strip()
            if area not in ('both','booking','reward') or kind not in ('image','document','link') or not 1<=len(label)<=150:
                raise ValueError('Choose an email group, item type and label of up to 150 characters.')
            if Media.query.count()>=12: raise ValueError('Keep up to 12 email items. Remove an unused item first.')
            item=Media(area=area,kind=kind,label=label)
            if kind=='link':
                value=request.form.get('url','').strip()
                parsed=urlsplit(value)
                if (len(value)>2000 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.port not in (None,443) or any(c.isspace() for c in value)):
                    raise ValueError('Use a complete HTTPS link without login credentials.')
                item.url=value
            else:
                upload=request.files.get('file')
                filename=secure_filename(upload.filename or '') if upload else ''
                content=upload.stream.read(2_000_001) if upload else b''
                if not filename or not content or len(content)>2_000_000:
                    raise ValueError('Choose a non-empty file up to 2 MB.')
                if sum(len(row.content or b'') for row in Media.query.all())+len(content)>5_000_000:
                    raise ValueError('Email images and attachments can total up to 5 MB. Remove an unused file first.')
                item.filename,item.content_type,item.content=filename,file_type(filename,content,kind),content
            db.session.add(item); db.session.commit()
            flash('Email item added. Preview the layout before sending notifications.','success')
        except ValueError as exc:
            db.session.rollback(); flash(str(exc),'error')
        except SQLAlchemyError:
            db.session.rollback(); flash('The email item could not be saved. Please try again.','error')
        return redirect(url_for('communications_templates')+'#email-media')
    @app.post('/admin/settings/email-media/<int:media_id>/delete')
    @admin_required
    def email_media_delete(media_id):
        check(); db.session.delete(db.get_or_404(Media,media_id)); db.session.commit()
        return redirect(url_for('communications_templates')+'#email-media')
    @app.get('/admin/settings/email-media/<int:media_id>/file')
    @admin_required
    def email_media_file(media_id):
        item=db.get_or_404(Media,media_id)
        if not item.content: abort(404)
        response=send_file(BytesIO(item.content),mimetype=item.content_type,download_name=item.filename,as_attachment=item.kind!='image')
        response.headers['Cache-Control']='private, no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    def decorate(kind,message,body,preview=False):
        for item in rows(kind):
            label=html.escape(item.label)
            if item.kind=='image':
                source=url_for('email_media_file',media_id=item.id) if preview else f'cid:cl-paints-media-{item.id}'
                picture=f'<p><img src="{source}" alt="{label}" style="display:block;max-width:100%;height:auto;border-radius:8px"></p>'
                message=message.replace('</h1>','</h1>'+picture,1)
            elif item.kind=='link':
                link=f'<p><a href="{html.escape(item.url,quote=True)}">{label}</a></p>'
                message=message.replace('</div>',link+'</div>',1)
                body+='\n\n'+item.label+': '+item.url
            else:
                body+='\n\nAttached: '+item.label+' ('+item.filename+')'
                link=f'<p>Attachment: {label} ({html.escape(item.filename)})</p>'
                if preview: link=f'<p><a href="{url_for("email_media_file",media_id=item.id)}">Download attachment: {label}</a></p>'
                message=message.replace('</div>',link+'</div>',1)
        return message,body
    def attachments(kind):
        result=[]
        for item in rows(kind):
            if not item.content: continue
            row=dict(filename=item.filename,content=base64.b64encode(item.content).decode(),content_type=item.content_type)
            if item.kind=='image': row['content_id']=f'cl-paints-media-{item.id}'
            result.append(row)
        return result
    app.extensions['email_media_decorate']=decorate
    app.extensions['email_media_attachments']=attachments
