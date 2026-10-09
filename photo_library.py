"""Signed client photo releases, private review and explicit website placements."""
from datetime import datetime
from io import BytesIO
import json
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, inspect, text
from sqlalchemy.orm import defer
from native_form_features import signature, signature_path

PHOTO_TERMS = '''Uploading photographs is optional and does not affect your bookings or services.
You give CL Paints permission to use the uploaded images in its portfolio, on its website and on its social media accounts to showcase and promote its face painting work. You confirm that you have permission from the photographer and every person shown. For a child, you must have appropriate parent or guardian authority and take their wishes into account. Do not upload images if anyone shown has not agreed.
Names and identifying descriptions are collected privately to record permission and identify the people in each image. They will not automatically appear in public captions. Your responsible person's name, verified account email, signature, consent wording and submission date are retained with the release.
Images published online may be viewed, downloaded or shared by other people. CL Paints cannot fully control third-party copies, reposts or the practices of social platforms. This does not remove your rights or CL Paints' responsibilities for its own use of your images.
You can withdraw permission from Upload photos in your client portal, or contact CL Paints. We will stop new use and remove the selected photographs from this website. Contact us so we can also remove copies from social accounts and other materials we control. We cannot guarantee removal of copies already made by others.
We review each submission before publication. We store uploads and release records privately while reviewing them and while needed to record the authorised use. Contact us about deletion or other privacy requests. See our privacy policy for contact details.'''


def ensure_schema(db):
    """Add website placements to existing libraries without changing their photos."""
    columns = {column['name'] for column in inspect(db.engine).get_columns('website_photo')}
    missing = [name for name in ('about', 'services', 'contact') if name not in columns]
    if missing:
        with db.engine.begin() as connection:
            for name in missing:
                connection.execute(text(f'ALTER TABLE website_photo ADD COLUMN {name} BOOLEAN NOT NULL DEFAULT FALSE'))


def define_models(db):
    class WebsitePhoto(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        media_id = db.Column(db.Integer, db.ForeignKey('consent_media.id'), nullable=False, unique=True)
        status = db.Column(db.String(20), nullable=False, default='pending')
        alt = db.Column(db.String(300), nullable=False, default='')
        caption = db.Column(db.String(500), nullable=False, default='')
        gallery = db.Column(db.Boolean, nullable=False, default=False)
        home = db.Column(db.Boolean, nullable=False, default=False)
        hero = db.Column(db.Boolean, nullable=False, default=False)
        about = db.Column(db.Boolean, nullable=False, default=False)
        services = db.Column(db.Boolean, nullable=False, default=False)
        contact = db.Column(db.Boolean, nullable=False, default=False)
        reviewed_at = db.Column(db.DateTime)
    class WebsiteStory(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(150), nullable=False)
        occasion = db.Column(db.String(150), nullable=False, default='')
        location = db.Column(db.String(150), nullable=False, default='')
        body = db.Column(db.Text, nullable=False)
        cover_id = db.Column(db.Integer, db.ForeignKey('website_photo.id'))
        published = db.Column(db.Boolean, nullable=False, default=False)
    return WebsitePhoto, WebsiteStory


def register(app, db, models, native_models, current_client, admin_required):
    Photo, Story = models
    Form, Submission, Media = native_models
    app.extensions['website_photo_models'] = models

    def csrf():
        return session.setdefault('client_csrf', secrets.token_urlsafe(32))

    def check():
        if not secrets.compare_digest(csrf(), request.form.get('csrf_token', '')):
            abort(400, 'Reload the page and try again.')

    def evidence(item):
        data = json.loads(item.answers_json)
        signed = data.get('signature') or next((v for k, v in data.items() if k.lower().startswith('signature') and v), None)
        return bool(item.terms_snapshot and data.get('authority_confirmed') and signed and not data.get('withdrawn_at'))

    def visible(photo):
        if not photo or photo.status != 'approved':
            return False
        media = Media.query.options(defer(Media.content)).filter_by(id=photo.media_id).first()
        item = db.session.get(Submission, media.submission_id) if media else None
        return bool(item and media.mime.startswith('image/') and evidence(item))

    def image_url(photo):
        return url_for('website_photo_image', photo_id=photo.id)

    @app.context_processor
    def library_context():
        photos = [p for p in Photo.query.filter_by(status='approved').order_by(Photo.id.desc()).all() if visible(p)]
        stories = [s for s in Story.query.filter_by(published=True).order_by(Story.id.desc()).all()
                   if not s.cover_id or visible(db.session.get(Photo, s.cover_id))]
        return dict(website_library_photos=photos, website_event_stories=stories,
                    website_library_image=image_url, website_story_cover=lambda s: db.session.get(Photo, s.cover_id) if s.cover_id else None)

    @app.route('/client/photos', methods=['GET', 'POST'])
    def client_photos():
        account = current_client()
        if not account:
            return redirect(url_for('client.login'))
        error = None
        if request.method == 'POST':
            check()
            try:
                if request.form.get('action') == 'withdraw':
                    item = db.get_or_404(Submission, request.form.get('submission_id', type=int))
                    if item.client_id != account.id or db.session.get(Form, item.form_id).kind != 'photo':
                        abort(404)
                    data = json.loads(item.answers_json)
                    data['withdrawn_at'] = datetime.utcnow().isoformat()
                    item.answers_json = json.dumps(data)
                    for media in Media.query.filter_by(submission_id=item.id):
                        photo = Photo.query.filter_by(media_id=media.id).first()
                        if photo:
                            photo.status = 'withdrawn'
                            photo.gallery = photo.home = photo.hero = photo.about = photo.services = photo.contact = False
                    db.session.commit()
                    flash('Permission withdrawn. Website images have been removed. Contact us about any social media or printed copies.', 'success')
                    return redirect(url_for('client_photos'))
                if request.content_length and request.content_length > 32_000_000:
                    abort(413)
                if request.form.get('contact_website'):
                    raise ValueError('We could not accept this request. Please contact CL Paints directly.')
                if request.form.get('terms_version') != '1':
                    raise ValueError('Reload this form to see the current permissions.')
                name = request.form.get('responsible_name', '').strip()
                if not name or len(name) > 150:
                    raise ValueError('Enter the responsible person’s full name.')
                signed = signature(request.form.get('custom_0', ''), True)
                if signed['name'].casefold() != name.casefold():
                    raise ValueError('The signature name must match the responsible person.')
                if any(request.form.get(key) != 'yes' for key in ('agree', 'authority', 'portfolio', 'website', 'social')):
                    raise ValueError('Confirm the permissions, authority and terms before uploading.')
                token = session.get('photo_upload_token')
                if not token or not secrets.compare_digest(token, request.form.get('submission_token', '')):
                    abort(400)
                if Submission.query.filter_by(token=token).first():
                    return redirect(url_for('client_photos'))
                uploads = []
                for index in range(3):
                    upload = request.files.get(f'photo_{index}')
                    if not upload or not upload.filename:
                        continue
                    people = request.form.get(f'people_{index}', '').strip()
                    if not people or len(people) > 2000:
                        raise ValueError(f'Photo {index+1}: name every person; identify each person by their position, clothing or design when there is more than one.')
                    count = request.form.get(f'people_count_{index}', type=int)
                    lines = [line.strip() for line in people.splitlines() if line.strip()]
                    if count is None or not 1 <= count <= 20 or len(lines) != count:
                        raise ValueError(f'Photo {index+1}: enter one line for each person and check the number of people.')
                    if any(not line.split('|', 1)[0].strip() or (count > 1 and ('|' not in line or not line.split('|', 1)[1].strip())) for line in lines):
                        raise ValueError(f'Photo {index+1}: include each name and an identifying description after | for group photographs.')
                    raw = upload.stream.read(10_000_001)
                    if not raw or len(raw) > 10_000_000:
                        raise ValueError('Each photograph must be under 10 MB.')
                    try:
                        with Image.open(BytesIO(raw)) as image:
                            if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 25_000_000:
                                raise ValueError('Use a JPG, PNG or WebP photograph up to 25 megapixels.')
                            image.load()
                            clean = ImageOps.exif_transpose(image).convert('RGB')
                            clean.thumbnail((1600, 1600))
                            content = BytesIO()
                            clean.save(content, 'JPEG', quality=88, optimize=True)
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                        raise ValueError('This photograph cannot be read. Choose a valid JPG, PNG or WebP image.')
                    uploads.append((content.getvalue(), people))
                if not uploads:
                    raise ValueError('Choose at least one photograph.')
                form = Form.query.filter_by(title='Client photo uploads', kind='photo').first()
                if not form:
                    form = Form(kind='photo', title='Client photo uploads', terms=PHOTO_TERMS, fields_json='[]', enabled=False)
                    db.session.add(form)
                    db.session.flush()
                item = Submission(form_id=form.id, client_id=account.id, token=token, email=account.email,
                    name=name, title_snapshot=form.title, terms_snapshot=PHOTO_TERMS,
                    answers_json=json.dumps(dict(signature=signed, authority_confirmed=True,
                        permissions=['portfolio', 'website', 'social'], terms_version='1',
                        photo_people=[people for _, people in uploads], account_number=account.account_number)))
                db.session.add(item)
                db.session.flush()
                form.terms = PHOTO_TERMS
                form.fields_json = json.dumps([dict(label='signature', type='signature', required=True)])
                app.extensions['native_form_records']['record_submission'](form, item, json.loads(item.answers_json), [])
                for index, (content, _) in enumerate(uploads):
                    media = Media(submission_id=item.id, content=content, mime='image/jpeg', filename=f'photo-{index+1}.jpg')
                    db.session.add(media)
                    db.session.flush()
                    db.session.add(Photo(media_id=media.id))
                db.session.commit()
                session.pop('photo_upload_token', None)
                flash(f'Photographs received. Reference F-{item.id}. They will be reviewed before publication.', 'success')
                return redirect(url_for('client_photos'))
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)
        entries = Submission.query.join(Form).filter(Submission.client_id == account.id, Form.kind == 'photo').order_by(Submission.id.desc()).all()
        return render_template('client/photos.html', client_account=account, client_csrf=csrf(), error=error,
            terms=PHOTO_TERMS, token=session.setdefault('photo_upload_token', secrets.token_urlsafe(32)),
            fields=[dict(type='signature', label='Signature', required=True)], entries=entries,
            photo_answers=lambda item: json.loads(item.answers_json))

    @app.route('/admin/photo-library', methods=['GET', 'POST'])
    @admin_required
    def admin_photo_library():
        check() if request.method == 'POST' else None
        if request.method == 'POST':
            media = db.get_or_404(Media, request.form.get('media_id', type=int))
            item = db.session.get(Submission, media.submission_id)
            if not media.mime.startswith('image/'):
                abort(400)
            photo = Photo.query.filter_by(media_id=media.id).first()
            if not photo:
                photo = Photo(media_id=media.id)
                db.session.add(photo)
            try:
                status = request.form.get('status')
                if status not in ('pending', 'approved', 'rejected'):
                    raise ValueError('Choose a review status.')
                if status == 'approved' and (not evidence(item) or request.form.get('reviewed_permissions') != 'yes'):
                    raise ValueError('Check the signed release and confirm it permits the selected website use. Unsigned or withdrawn releases cannot be published.')
                if status == 'approved':
                    try:
                        with Image.open(BytesIO(media.content)) as image:
                            if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 25_000_000:
                                raise ValueError('This image is not suitable for website publication.')
                            image.verify()
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                        raise ValueError('The uploaded file is not a readable photograph.')
                alt = request.form.get('alt', '').strip()
                caption = request.form.get('caption', '').strip()
                if len(alt) > 300 or len(caption) > 500 or (status == 'approved' and not alt):
                    raise ValueError('Add a description up to 300 characters and a caption up to 500 characters. Avoid private names.')
                photo.status, photo.alt, photo.caption = status, alt, caption
                photo.gallery = status == 'approved' and request.form.get('gallery') == 'yes'
                photo.home = status == 'approved' and request.form.get('home') == 'yes'
                photo.hero = status == 'approved' and request.form.get('hero') == 'yes'
                for placement in ('about', 'services', 'contact'):
                    setattr(photo, placement, status == 'approved' and request.form.get(placement) == 'yes')
                if photo.hero:
                    db.session.flush()
                    Photo.query.filter(Photo.id != photo.id).update({'hero': False})
                photo.reviewed_at = datetime.utcnow()
                db.session.commit()
                flash('Photo review and website placements saved.', 'success')
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), 'error')
            return redirect(url_for('admin_photo_library'))
        query = request.args.get('q', '').strip()[:100]
        rows = db.session.query(Media, Submission, Photo).options(defer(Media.content)).join(Submission, Media.submission_id == Submission.id).join(Form, Submission.form_id == Form.id).outerjoin(Photo, Photo.media_id == Media.id).filter(Form.kind == 'photo', Media.mime.in_(['image/jpeg', 'image/png', 'image/webp']))
        if query:
            rows = rows.filter(or_(Submission.name.ilike('%'+query+'%'), Submission.email.ilike('%'+query+'%'), Submission.answers_json.ilike('%'+query+'%')))
        pagination = rows.order_by(Media.id.desc()).paginate(page=max(1, request.args.get('page', 1, type=int)), per_page=24, error_out=False)
        return render_template('admin_photo_library.html', rows=pagination.items, pagination=pagination, query=query,
            csrf=csrf(), photo_answers=lambda item: json.loads(item.answers_json), signed_evidence=evidence, signature_path=signature_path)

    @app.get('/admin/photo-library/<int:media_id>/image')
    @admin_required
    def admin_photo_image(media_id):
        media = db.get_or_404(Media, media_id)
        if not media.mime.startswith('image/'):
            abort(404)
        response = send_file(BytesIO(media.content), mimetype=media.mime)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/website/photos/<int:photo_id>.jpg')
    def website_photo_image(photo_id):
        photo = db.get_or_404(Photo, photo_id)
        if not visible(photo):
            abort(404)
        media = db.session.get(Media, photo.media_id)
        # Re-encode legacy uploads too: metadata and unrelated bytes stay private.
        try:
            with Image.open(BytesIO(media.content)) as source:
                if source.width * source.height > 25_000_000:
                    abort(404)
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, 'JPEG', quality=85, optimize=True)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            abort(404)
        output.seek(0)
        response = send_file(output, mimetype='image/jpeg')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.route('/admin/website-stories', methods=['GET', 'POST'])
    @admin_required
    def admin_website_stories():
        if request.method == 'POST':
            check()
            try:
                story = db.get_or_404(Story, request.form.get('id', type=int)) if request.form.get('id') else Story()
                title, body = request.form.get('title', '').strip(), request.form.get('body', '').strip()
                occasion, location = request.form.get('occasion', '').strip(), request.form.get('location', '').strip()
                if not title or len(title) > 150 or not body or len(body) > 5000 or max(len(occasion), len(location)) > 150:
                    raise ValueError('Add a title, a story up to 5,000 characters and short occasion/location details.')
                cover_id = request.form.get('cover_id', type=int)
                if cover_id and not visible(db.session.get(Photo, cover_id)):
                    raise ValueError('Choose an approved photograph with active consent.')
                story.title, story.body, story.occasion, story.location = title, body, occasion, location
                story.cover_id, story.published = cover_id, request.form.get('published') == 'yes'
                db.session.add(story)
                db.session.commit()
                flash('Event story saved.', 'success')
                return redirect(url_for('admin_website_stories'))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), 'error')
        photos = [p for p in Photo.query.filter_by(status='approved').all() if visible(p)]
        return render_template('admin_website_stories.html', stories=Story.query.order_by(Story.id.desc()).all(), photos=photos, csrf=csrf())
