"""Reusable equipment lists for different kinds of events."""
from io import BytesIO
from datetime import date, datetime, time, timedelta, timezone
import secrets
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from record_ids import record_reference

LONDON = ZoneInfo('Europe/London')


def define_models(db):
    class EquipmentCategory(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(100), nullable=False)
        name_key = db.Column(db.String(300), nullable=False, unique=True)
        needed_ids = db.Column(db.JSON, nullable=False, default=list)

    class EquipmentItem(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(100), nullable=False)
        name_key = db.Column(db.String(300), nullable=False, unique=True)
        image = db.deferred(db.Column(db.LargeBinary))

    class EquipmentChecklistEntry(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        category_name = db.Column(db.String(100), nullable=False)
        recorded_by = db.Column(db.String(255), nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False, index=True)
        needed = db.Column(db.JSON, nullable=False)
        not_needed = db.Column(db.JSON, nullable=False)

        @property
        def local_time(self):
            return self.recorded_at.replace(tzinfo=timezone.utc).astimezone(LONDON)

    class EquipmentBookingCheck(db.Model):
        entry_id = db.Column(db.Integer, db.ForeignKey('equipment_checklist_entry.id'), primary_key=True)
        booking_id = db.Column(db.Integer, nullable=False, index=True)
        category_id = db.Column(db.Integer, nullable=False)
        booking_label = db.Column(db.String(255), nullable=False)
        needed_ids = db.Column(db.JSON, nullable=False)

    return EquipmentCategory, EquipmentItem, EquipmentChecklistEntry, EquipmentBookingCheck


def read_image(upload):
    raw = upload.read(10_000_001)
    if not raw or len(raw) > 10_000_000:
        raise ValueError('Choose an image up to 10 MB.')
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 25_000_000:
                raise ValueError('Choose a JPG, PNG or WebP image up to 25 megapixels.')
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1200, 1200))
            output = BytesIO()
            image.save(output, 'JPEG', quality=86)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Choose a readable JPG, PNG or WebP image.') from error


def register(app, db, models, admin_required, Booking):
    Category, Item, Entry, BookingCheck = models

    def check_csrf():
        token = session.get('equipment_csrf')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)

    def destination(category_id=None, booking_id=None):
        return redirect(url_for('admin_equipment', category=category_id, booking=booking_id))

    def bookings():
        return db.session.query(Booking.id, Booking.submitted_at, Booking.event_date, Booking.event_type).filter_by(status='Accepted')

    def booking_label(booking):
        reference = record_reference('B', booking.id, booking.submitted_at)
        return f'{reference} · {booking.event_type} · {booking.event_date:%d %b %Y}'

    def set_name(record):
        name = ' '.join(request.form.get('name', '').split())
        if not 1 <= len(name) <= 100:
            raise ValueError('Enter a name between 1 and 100 characters.')
        record.name = name
        record.name_key = name.casefold()

    @app.get('/admin/equipment')
    @admin_required
    def admin_equipment():
        categories = Category.query.order_by(Category.name_key).all()
        category_id = request.args.get('category', type=int)
        booking_id = request.args.get('booking', type=int)
        options = bookings().order_by(Booking.event_date.desc(), Booking.id.desc()).all() if categories else []
        booking = next((option for option in options if option.id == booking_id), None)
        if category_id:
            category = db.get_or_404(Category, category_id)
        else:
            match = ' '.join(booking.event_type.split()).casefold() if booking else None
            category = next((option for option in categories if option.name_key == match), next(iter(categories), None))
        items = db.session.query(Item.id, Item.name, Item.image.is_not(None).label('has_image')).order_by(Item.name_key).all()
        needed_ids = set(category.needed_ids) if category else set()
        checker = app.extensions['pos_access'].staff() if session.get('pos_staff_id') else None
        if booking and category:
            latest = BookingCheck.query.filter_by(booking_id=booking.id, category_id=category.id).order_by(
                BookingCheck.entry_id.desc()).first()
            if latest:
                needed_ids = set(latest.needed_ids)
        return render_template('admin_equipment.html', categories=categories, category=category,
                               items=items, needed_ids=needed_ids, checker=checker,
                               booking_id=booking.id if booking else None,
                               booking_options=[(option.id, booking_label(option)) for option in options],
                               csrf=session.setdefault('equipment_csrf', secrets.token_urlsafe(32)))

    @app.get('/admin/equipment/history')
    @admin_required
    def equipment_history():
        filters = {key: request.args.get(key, '') for key in ('event_category', 'staff', 'from_date', 'to_date')}
        query = Entry.query
        if filters['event_category']:
            query = query.filter_by(category_name=filters['event_category'])
        if filters['staff']:
            query = query.filter_by(recorded_by=filters['staff'])
        for field, end in (('from_date', False), ('to_date', True)):
            if filters[field]:
                try:
                    day = date.fromisoformat(filters[field]) + timedelta(days=end)
                    cutoff = datetime.combine(day, time.min, LONDON).astimezone(timezone.utc).replace(tzinfo=None)
                except (ValueError, OverflowError):
                    abort(400, 'Choose a valid history date.')
                query = query.filter(Entry.recorded_at < cutoff if end else Entry.recorded_at >= cutoff)
        history = query.order_by(Entry.recorded_at.desc(), Entry.id.desc()).paginate(
            page=request.args.get('page', 1, type=int), per_page=15, error_out=False)
        event_labels = dict(db.session.query(BookingCheck.entry_id, BookingCheck.booking_label).filter(
            BookingCheck.entry_id.in_([entry.id for entry in history.items])).all())
        category_names = db.session.scalars(db.select(Entry.category_name).distinct().order_by(Entry.category_name)).all()
        staff_names = db.session.scalars(db.select(Entry.recorded_by).distinct().order_by(Entry.recorded_by)).all()
        category_id = request.args.get('category', type=int)
        category = db.session.get(Category, category_id) if category_id else None
        return render_template('equipment_history.html', history=history,
                               filters=filters, category_names=category_names, staff_names=staff_names,
                               event_labels=event_labels,
                               category_id=category.id if category else None)

    @app.post('/admin/equipment/categories')
    @app.post('/admin/equipment/categories/<int:category_id>')
    @admin_required
    def save_equipment_category(category_id=None):
        check_csrf()
        category = db.get_or_404(Category, category_id) if category_id else Category()
        try:
            set_name(category)
            db.session.add(category)
            db.session.commit()
            flash('Event category saved.', 'success')
            return destination(category.id)
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else 'That event category already exists.', 'error')
            return destination(category_id)

    @app.post('/admin/equipment/items')
    @app.post('/admin/equipment/items/<int:item_id>')
    @admin_required
    def save_equipment_item(item_id=None):
        check_csrf()
        item = db.get_or_404(Item, item_id) if item_id else Item()
        category_id = request.form.get('category', type=int)
        try:
            set_name(item)
            upload = request.files.get('image')
            if upload and upload.filename:
                item.image = read_image(upload)
            elif request.form.get('remove_image'):
                item.image = None
            db.session.add(item)
            db.session.commit()
            flash('Equipment item saved.', 'success')
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else 'That equipment item already exists.', 'error')
        return destination(category_id)

    @app.post('/admin/equipment/categories/<int:category_id>/delete')
    @admin_required
    def delete_equipment_category(category_id):
        check_csrf()
        category = db.get_or_404(Category, category_id)
        db.session.delete(category)
        db.session.commit()
        flash('Event category deleted.', 'success')
        return destination()

    @app.post('/admin/equipment/categories/<int:category_id>/checklist')
    @admin_required
    def save_equipment_checklist(category_id):
        checker = app.extensions['pos_access'].staff()
        if checker is None:
            abort(403, 'Sign in with a staff PIN and Equipment checklist permission to save a check.')
        check_csrf()
        if request.form.get('checked_by') != str(checker.id):
            abort(400, 'Select your staff account before saving the checklist.')
        category = db.get_or_404(Category, category_id)
        booking_id = request.form.get('booking', type=int)
        booking = bookings().filter_by(id=booking_id).first() if booking_id else None
        if request.form.get('booking') and booking is None:
            abort(400, 'Choose an accepted booking before saving the checklist.')
        selected = set(request.form.getlist('needed'))
        items = db.session.query(Item.id, Item.name).order_by(Item.name_key).all()
        needed_ids = sorted(item.id for item in items if str(item.id) in selected)
        entry = Entry(
            category_name=category.name,
            recorded_by=checker.name,
            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
            needed=[item.name for item in items if str(item.id) in selected],
            not_needed=[item.name for item in items if str(item.id) not in selected],
        )
        db.session.add(entry)
        if booking:
            db.session.flush()
            db.session.add(BookingCheck(entry_id=entry.id, booking_id=booking.id, category_id=category.id,
                                       booking_label=booking_label(booking), needed_ids=needed_ids))
        else:
            category.needed_ids = needed_ids
        db.session.commit()
        flash('Equipment checklist saved.', 'success')
        return destination(category.id, booking_id)

    @app.get('/admin/equipment/items/<int:item_id>/image')
    @admin_required
    def equipment_item_image(item_id):
        item = db.get_or_404(Item, item_id)
        if item.image is None:
            abort(404)
        response = send_file(BytesIO(item.image), mimetype='image/jpeg')
        response.cache_control.no_store = True
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
