"""Private participant photographs, separate from marketing photo releases."""
from datetime import datetime
from io import BytesIO
import secrets
import warnings

from flask import abort, flash, redirect, render_template, request, session, url_for, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import defer


def define_model(db):
    class ParticipantPhoto(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False, index=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False, index=True)
        content = db.Column(db.LargeBinary, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        uploaded_by = db.Column(db.String(10), nullable=False)
    return ParticipantPhoto


def register(app, db, Photo, Participant, Account, Custodian, current_client, admin_required):
    @app.context_processor
    def photo_context():
        if request.endpoint in ('admin_participants', 'admin_waiver_detail'):
            return dict(client_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)))
        return {}

    def account_for(person):
        custodian = db.session.get(Custodian, person.id)
        if custodian:
            return db.session.get(Account, custodian.client_id)
        return Account.query.filter(db.func.lower(db.func.trim(Account.email)) ==
                                    person.waiver.responsible_email.strip().casefold()).first()

    def client_person(participant_id):
        account = current_client()
        if not account:
            abort(401)
        person = db.get_or_404(Participant, participant_id)
        owner = account_for(person)
        if not owner or owner.id != account.id:
            abort(404)
        return person, owner

    def release_source(photo_id, account):
        photo = db.get_or_404(Photo, photo_id)
        person, owner = client_person(photo.participant_id)
        if owner.id != account.id or photo.client_id != account.id:
            abort(404)
        return photo, person

    app.extensions['participant_photo_release_source'] = release_source

    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def check_csrf():
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)

    def gallery(person, owner, admin=False):
        endpoint = 'admin_participant_photos' if admin else 'client_participant_photos'
        target = url_for(endpoint, participant_id=person.id)
        error = None
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if request.content_length and request.content_length > 12_000_000:
                abort(413)
            check_csrf()
            if not owner:
                abort(409, description='Create a client account for the responsible person before adding photographs.')
            if request.form.get('action') == 'delete':
                photo = Photo.query.filter_by(id=request.form.get('photo_id', type=int), participant_id=person.id).first_or_404()
                if not admin and photo.client_id != owner.id:
                    abort(404)
                app.extensions['participant_photo_withdraw'](photo)
                db.session.delete(photo)
                db.session.commit()
                flash('Participant photograph deleted.', 'success')
                return redirect(target)
            if request.form.get('action') == 'send_library':
                if not admin:
                    abort(403)
                photo = Photo.query.filter_by(id=request.form.get('photo_id', type=int), participant_id=person.id).first_or_404()
                release = app.extensions['participant_photo_release'](photo)
                if not release:
                    flash('The responsible account must sign photo permission for this image before it can enter the library.', 'error')
                    return redirect(target)
                return redirect(url_for('admin_photo_library', q=release.email))
            if request.form.get('action') != 'upload':
                abort(400)
            try:
                upload = request.files.get('image')
                if not upload or not upload.filename:
                    raise ValueError('Choose a photograph or take one with your camera.')
                raw = upload.stream.read(10_000_001)
                if not raw or len(raw) > 10_000_000:
                    raise ValueError('Choose a photograph under 10 MB.')
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(BytesIO(raw)) as source:
                        if source.format not in ('JPEG', 'MPO', 'PNG', 'WEBP'):
                            raise ValueError('Choose a JPG, PNG or WebP photograph. Export HEIC photos as JPG first.')
                        if source.width * source.height > 25_000_000:
                            raise ValueError('Choose a photograph with no more than 25 megapixels.')
                        image = ImageOps.exif_transpose(source)
                        image.thumbnail((1600, 1600))
                        # Copy pixels into a fresh image so camera/location metadata is removed.
                        clean = Image.new('RGB', image.size, 'white')
                        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                            rgba = image.convert('RGBA')
                            clean.paste(rgba, mask=rgba.getchannel('A'))
                        else:
                            clean.paste(image.convert('RGB'))
                        output = BytesIO()
                        clean.save(output, 'JPEG', quality=88, optimize=True)
                db.session.add(Photo(participant_id=person.id, client_id=owner.id,
                                     content=output.getvalue(), uploaded_by='admin' if admin else 'client'))
                db.session.commit()
                flash('Photograph saved to this participant and account.', 'success')
                return redirect(target)
            except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as problem:
                db.session.rollback()
                error = str(problem) if isinstance(problem, ValueError) else 'This photograph could not be read. Choose a JPG, PNG or WebP image.'
        query = Photo.query.options(defer(Photo.content)).filter_by(participant_id=person.id)
        if not admin:
            query = query.filter_by(client_id=owner.id)
        pagination = query.order_by(Photo.created_at.desc(), Photo.id.desc()).paginate(per_page=24, error_out=False)
        releases = {photo.id: app.extensions['participant_photo_release'](photo) for photo in pagination.items}
        response = app.make_response(render_template('participant_photos.html', person=person, photo_account=owner,
            pagination=pagination, is_admin=admin, client_account=None if admin else owner,
            client_csrf=token, error=error, gallery_endpoint=endpoint, photo_releases=releases))
        if error:
            response.status_code = 400
        return private(response)

    @app.route('/admin/participants/<int:participant_id>/photos', methods=['GET', 'POST'])
    @admin_required
    def admin_participant_photos(participant_id):
        person = db.get_or_404(Participant, participant_id)
        return gallery(person, account_for(person), admin=True)

    @app.route('/client/members/<int:participant_id>/photos', methods=['GET', 'POST'])
    def client_participant_photos(participant_id):
        if not current_client():
            return redirect(url_for('client.login'))
        person, owner = client_person(participant_id)
        return gallery(person, owner)

    @app.get('/participant-photos/<int:photo_id>/image')
    def participant_photo_image(photo_id):
        photo = db.get_or_404(Photo, photo_id)
        def response():
            return private(send_file(BytesIO(photo.content), mimetype='image/jpeg', conditional=False,
                                     download_name='participant-photo.jpg', max_age=0))
        if session.get('admin_authenticated'):
            return admin_required(response)()
        else:
            _, owner = client_person(photo.participant_id)
            if photo.client_id != owner.id:
                abort(404)
        return response()
