"""Account-owned studio submissions and an approval-only community gallery."""
import base64
import binascii
import io
import secrets
import struct
import zlib
from datetime import datetime
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file


def models(db):
    class StudioDesign(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False, index=True)
        title = db.Column(db.String(80), nullable=False)
        display_name = db.Column(db.String(40), nullable=False)
        theme = db.Column(db.String(30), nullable=False)
        template = db.Column(db.String(30), nullable=False)
        image = db.Column(db.LargeBinary, nullable=False)
        status = db.Column(db.String(20), nullable=False, default='pending', index=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    class StudioReport(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        design_id = db.Column(db.Integer, db.ForeignKey('studio_design.id'), nullable=False)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        reason = db.Column(db.String(500), nullable=False)
        resolved = db.Column(db.Boolean, nullable=False, default=False)
        __table_args__ = (db.UniqueConstraint('design_id', 'client_id'),)
    class StudioFavourite(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        design_id = db.Column(db.Integer, db.ForeignKey('studio_design.id'), nullable=False)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        __table_args__ = (db.UniqueConstraint('design_id', 'client_id'),)
    return StudioDesign, StudioReport, StudioFavourite


def png_bytes(value):
    """Accept bounded canvas PNGs only, validating chunks and inflated pixel size."""
    if not isinstance(value, str) or not value.startswith('data:image/png;base64,') or len(value)>2800000:
        abort(400, 'Invalid studio photograph.')
    try:
        data=base64.b64decode(value.split(',',1)[1],validate=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError()
        pos=8;compressed=bytearray();header=None;ended=False
        while pos<len(data):
            length=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8]
            payload=data[pos+8:pos+8+length];crc=data[pos+8+length:pos+12+length]
            if len(crc)!=4 or struct.unpack('>I',crc)[0] != binascii.crc32(kind+payload)&0xffffffff:raise ValueError()
            if kind==b'IHDR':
                if header is not None or pos!=8:raise ValueError()
                header=struct.unpack('>IIBBBBB',payload)
                if header[:2] not in ((600,720),(720,860)) or header[2]!=8 or header[3] not in (2,6) or header[4:]!=(0,0,0):raise ValueError()
            elif kind==b'IDAT':compressed.extend(payload)
            elif kind==b'IEND':
                if length or pos+12!=len(data):raise ValueError()
                ended=True;break
            elif kind not in (b'sRGB',b'gAMA',b'cHRM',b'pHYs'):raise ValueError()
            pos+=length+12
        if not ended or not header:raise ValueError()
        row=1+header[0]*(4 if header[3]==6 else 3);expected=row*header[1]
        decoder=zlib.decompressobj();pixels=decoder.decompress(bytes(compressed),expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data or any(pixels[i]>4 for i in range(0,expected,row)):raise ValueError()
        return data
    except (ValueError,struct.error,zlib.error,binascii.Error):
        abort(400, 'Invalid studio photograph.')


def register(app, portal, db, model_classes, Account, client_required, check_csrf, admin_required):
    Design,Report,Favourite=model_classes
    themes=('animals','flowers','fantasy','superheroes','other')
    templates={'illustrated','curly-man','curly-woman','red-haired-boy','plaited-girl','adult-male','adult-female','child-male','child-female'}
    def design_or_404(id):return db.get_or_404(Design,id)
    def admin_csrf():
        token=session.setdefault('studio_admin_csrf',secrets.token_urlsafe(32))
        if request.method=='POST' and not secrets.compare_digest(token,request.form.get('csrf_token','')):abort(400)
        return token
    @portal.get('/community-gallery')
    @client_required
    def community_gallery(account):
        theme=request.args.get('theme','');query=Design.query.filter_by(status='approved')
        if theme in themes:query=query.filter_by(theme=theme)
        favourites={f.design_id for f in Favourite.query.filter_by(client_id=account.id).all()}
        if request.args.get('favourites')=='1':query=query.filter(Design.id.in_(favourites))
        page=max(1,request.args.get('page',1,type=int))
        entries=query.order_by(Design.created_at.desc()).limit(24).offset((page-1)*24).all()
        mine=Design.query.filter_by(client_id=account.id).order_by(Design.created_at.desc()).all()
        return render_template('client/community_gallery.html',entries=entries,mine=mine,themes=themes,favourites=favourites,page=page,theme=theme)
    @portal.post('/community-gallery/share')
    @client_required
    def community_share(account):
        request.max_content_length=3500000
        request.max_form_memory_size=3000000
        check_csrf()
        if request.form.get('consent')!='yes':abort(400,'Confirm that you want to publish this design.')
        if request.form.get('guidelines')!='yes':abort(400,'Read and agree to the Community gallery guidelines before submitting.')
        title=request.form.get('title','').strip();name=request.form.get('display_name','').strip() or 'Anonymous painter'
        theme=request.form.get('theme');template=request.form.get('template')
        if not title or len(title)>80 or len(name)>40 or theme not in themes or template not in templates:abort(400)
        if Design.query.filter_by(client_id=account.id,status='pending').count()>=10:abort(429,'Wait for your pending designs to be reviewed.')
        if len(request.form.get('image',''))>2800000:abort(413)
        image=png_bytes(request.form.get('image'))
        db.session.add(Design(client_id=account.id,title=title,display_name=name,theme=theme,template=template,image=image));db.session.commit()
        flash('Design submitted for admin approval. Your email and account details are not shown in the gallery.','success')
        return redirect(url_for('client.community_gallery',embed='1' if request.form.get('embed')=='1' else ''))
    @portal.get('/community-gallery/<int:id>/image')
    @client_required
    def community_image(account,id):
        design=design_or_404(id)
        if design.status!='approved' and design.client_id!=account.id and not session.get('admin_authenticated'):abort(404)
        response=send_file(io.BytesIO(design.image),mimetype='image/png',max_age=0)
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    @portal.post('/community-gallery/<int:id>/<action>')
    @client_required
    def community_action(account,id,action):
        check_csrf();design=design_or_404(id)
        if action=='unpublish':
            if design.client_id!=account.id:abort(404)
            design.status='withdrawn'
        elif action=='favourite':
            if design.status!='approved':abort(404)
            record=Favourite.query.filter_by(design_id=id,client_id=account.id).first()
            if record:db.session.delete(record)
            else:db.session.add(Favourite(design_id=id,client_id=account.id))
        elif action=='report':
            if design.status!='approved':abort(404)
            reason=request.form.get('reason','').strip()
            if not reason or len(reason)>500:abort(400)
            record=Report.query.filter_by(design_id=id,client_id=account.id).first()
            if record:record.reason=reason;record.resolved=False
            else:db.session.add(Report(design_id=id,client_id=account.id,reason=reason))
            flash('Report sent to the admin team.','success')
        else:abort(404)
        db.session.commit();return redirect(url_for('client.community_gallery',embed='1' if request.form.get('embed')=='1' else ''))
    @app.get('/admin/studio-gallery')
    @admin_required
    def studio_gallery_admin():
        token=admin_csrf();page=max(1,request.args.get('page',1,type=int));status=request.args.get('status','pending')
        query=Design.query
        if status in ('pending','approved','rejected','withdrawn'):query=query.filter_by(status=status)
        entries=query.order_by(Design.created_at.desc()).limit(24).offset((page-1)*24).all()
        return render_template('admin_studio_gallery.html',entries=entries,accounts={a.id:a for a in Account.query.all()},reports=Report.query.filter_by(resolved=False).all(),csrf_token=token,page=page,status=status)
    @app.get('/admin/studio-gallery/<int:id>/image')
    @admin_required
    def studio_gallery_admin_image(id):
        response=send_file(io.BytesIO(design_or_404(id).image),mimetype='image/png',max_age=0)
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff';return response
    @app.post('/admin/studio-gallery/<int:id>/<action>')
    @admin_required
    def studio_gallery_moderate(id,action):
        admin_csrf();design=design_or_404(id)
        if action not in ('approve','reject','resolve'):abort(404)
        if action=='approve':
            if design.status!='pending':abort(400)
            design.status='approved'
        elif action=='reject':design.status='rejected'
        for report in Report.query.filter_by(design_id=id,resolved=False).all():report.resolved=True
        db.session.commit();return redirect(url_for('studio_gallery_admin'))
