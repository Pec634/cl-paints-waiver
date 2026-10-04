from flask import Flask, render_template, request, jsonify, render_template_string, session, redirect, url_for, abort
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from dateutil.relativedelta import relativedelta
from werkzeug.security import check_password_hash, generate_password_hash
import hashlib
import json
import csv
import phonenumbers
import secrets
import resend
import os
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from business_settings import DEFAULTS as DEFAULT_BUSINESS_SETTINGS

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

TERMS_VERSION = "2026-09-10"
TERMS_TEMPLATE_PATH = Path(__file__).parent / "templates" / "terms_and_liability.html"
resend.api_key = RESEND_API_KEY

ETHNICITY_BREAKDOWNS = {
    "Asian or Asian British": [
        "Bangladeshi", "Chinese", "Indian", "Pakistani", "Other Asian background",
    ],
    "Black, Black British, Caribbean or African": [
        "African", "Caribbean", "Other Black background",
    ],
    "Mixed or multiple ethnic groups": [
        "White and Asian", "White and Black African", "White and Black Caribbean",
        "Other mixed or multiple ethnic background",
    ],
    "White": [
        "English, Welsh, Scottish, Northern Irish or British", "Irish",
        "Gypsy or Irish Traveller", "Roma", "Other White background",
    ],
    "Other ethnic group": ["Arab", "Any other ethnic group"],
}

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


def admin_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view_function(*args, **kwargs)

    return wrapped_view

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Render/PostgreSQL production database
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql+psycopg2://",
            1
        )
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgresql://",
            "postgresql+psycopg2://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    # Local development database
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cl_paints_waivers.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class Waiver(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
    db.Integer,
    db.ForeignKey("customer.id"),
    nullable=True
    )

    customer = db.relationship(
        "Customer",
        backref=db.backref("waivers", lazy=True)
    )

    waiver_reference = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    responsible_first_name = db.Column(db.String(100), nullable=False)
    responsible_last_name = db.Column(db.String(100), nullable=False)
    responsible_email = db.Column(db.String(255), nullable=False)

    signed_date = db.Column(db.DateTime, nullable=False)
    expiry_date = db.Column(db.DateTime, nullable=False)

    status = db.Column(
        db.String(30),
        nullable=False,
        default="Valid"

    )
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime, nullable=True)
    archived_by = db.Column(db.String(100), nullable=True)

    event_name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=True)

    marketing_consent = db.Column(
        db.Boolean,
        nullable=False,
        default=False

    )

    terms_version = db.Column(db.String(50), nullable=False)
    terms_snapshot = db.Column(db.Text, nullable=False)

    liability_acknowledged = db.Column(
        db.Boolean,
        nullable=False,
        default=False
        )


    responsible_authority = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    responsible_accuracy = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    signature_text = db.Column(
        db.String(255),
        nullable=False
    )

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    waiver_id = db.Column(
        db.Integer,
        db.ForeignKey("waiver.id"),
        nullable=False
    )

    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(30), nullable=False)

    waiver = db.relationship(
        "Waiver",
        backref=db.backref("participants", lazy=True)
    )

class Event(db.Model):
    __tablename__ = "event"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=True)
    booking_day_number = db.Column(db.Integer, nullable=True)
    event_address = db.Column(db.Text, nullable=True)

    name = db.Column(
        db.String(200),
        nullable=False
    )

    event_date = db.Column(
        db.Date,
        nullable=True
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="Open"
    )

    is_current = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "booking_id",
            "booking_day_number",
            name="uq_event_booking_day",
        ),
    )

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    request_type = db.Column(db.String(30), nullable=False)
    client_type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(30), nullable=True)
    job_title = db.Column(db.String(120), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    is_over_18 = db.Column(db.Boolean, nullable=False)
    ethnicity = db.Column(db.String(100), nullable=False)
    ethnicity_detail = db.Column(db.String(150), nullable=True)
    religion = db.Column(db.String(100), nullable=False)
    client_address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    single_date = db.Column(db.Boolean, nullable=False)
    additional_event_dates = db.Column(db.Text, nullable=True)
    event_schedule = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.String(5), nullable=False)
    finish_time = db.Column(db.String(5), nullable=False)
    event_address = db.Column(db.Text, nullable=False)
    publicity_type = db.Column(db.String(30), nullable=False)
    charge_type = db.Column(db.String(30), nullable=False)
    location_type = db.Column(db.String(30), nullable=False)
    event_type = db.Column(db.String(150), nullable=False)
    theme = db.Column(db.String(200), nullable=False)
    expected_attendees = db.Column(db.Integer, nullable=True)
    celebrates_christmas_easter = db.Column(db.Boolean, nullable=True)
    additional_info = db.Column(db.Text, nullable=True)
    pitch_fee_required = db.Column(db.Boolean, nullable=False)
    payment_preference = db.Column(db.String(40), nullable=False)
    promo_code = db.Column(db.String(100), nullable=True)
    signature = db.Column(db.String(200), nullable=False)
    company_signature = db.Column(db.String(200), nullable=True)
    liability_acknowledged = db.Column(db.Boolean, nullable=False)
    terms_accepted_at = db.Column(db.DateTime, nullable=False)
    terms_version = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Under Review")
    travel_charge = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_event_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    internal_notes = db.Column(db.Text, nullable=True)
    referral_verified = db.Column(db.Boolean, nullable=True)

class ReferralCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)


class ReferralCodeUse(db.Model):
    code = db.Column(db.String(100), primary_key=True)
    used_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class ReportLocation(db.Model):
    outcode = db.Column(db.String(10), primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    town = db.Column(db.String(255), nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class BusinessSetting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=False)


class ClientAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50), nullable=False, default="")
    address = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class ClientLoginCode(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False, default="")
    last_name = db.Column(db.String(100), nullable=False, default="")
    mode = db.Column(db.String(10), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False)
    ip_hash = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed = db.Column(db.Boolean, nullable=False, default=False)


class ClientRewardOwner(db.Model):
    code = db.Column(db.String(100), primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False, index=True)


class ClientEnquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

class AdminCredential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    password_hash = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

class AdminPasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    customer_number = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    first_name = db.Column(
        db.String(100),
        nullable=False
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    email_verified = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now
    )

class MoodboardImage(db.Model):
    __tablename__ = "moodboard_image"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(
        db.String(200),
        nullable=False
    )

    image_url = db.Column(
        db.String(500),
        nullable=False
    )

    storage_id = db.Column(
        db.String(300),
        nullable=True
    )

    active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    design_type = db.Column(
    db.String(20),
    nullable=False,
    default="large"
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now
    )

class EventMoodboardImage(db.Model):
    __tablename__ = "event_moodboard_image"

    id = db.Column(db.Integer, primary_key=True)

    event_id = db.Column(
        db.Integer,
        db.ForeignKey("event.id"),
        nullable=False
    )

    image_id = db.Column(
        db.Integer,
        db.ForeignKey("moodboard_image.id"),
        nullable=False
    )

    sort_order = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    event = db.relationship("Event")

    image = db.relationship("MoodboardImage")

    __table_args__ = (
        db.UniqueConstraint(
            "event_id",
            "image_id",
            name="uq_event_moodboard_image"
        ),
    )

with app.app_context():
    db.create_all()
    event_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("event")
    }
    event_column_migrations = {
        "booking_id": "INTEGER REFERENCES booking(id)",
        "booking_day_number": "INTEGER",
        "event_address": "TEXT",
    }
    with db.engine.begin() as connection:
        for column_name, column_definition in event_column_migrations.items():
            if column_name not in event_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE event ADD COLUMN {column_name} {column_definition}"
                )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_booking_day "
            "ON event (booking_id, booking_day_number)"
        )

    waiver_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("waiver")
    }

    if "event_date" not in waiver_columns:
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE waiver ADD COLUMN event_date DATE"
            )
            connection.exec_driver_sql(
                """
                UPDATE waiver
                SET event_date = (
                    SELECT event_record.event_date
                    FROM event AS event_record
                    WHERE event_record.name = waiver.event_name
                    ORDER BY event_record.id
                    LIMIT 1
                )
                WHERE event_date IS NULL
                """
            )

    booking_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("booking")
    }

    booking_column_migrations = {
        "single_date": "BOOLEAN NOT NULL DEFAULT 1",
        "job_title": "VARCHAR(120)",
        "ethnicity_detail": "VARCHAR(150)",
        "event_schedule": "TEXT",
        "company_signature": "VARCHAR(200)",
        "travel_charge": "NUMERIC(10, 2) NOT NULL DEFAULT 0",
        "total_event_cost": "NUMERIC(10, 2) NOT NULL DEFAULT 0",
        "internal_notes": "TEXT",
        "referral_verified": "BOOLEAN",
    }

    with db.engine.begin() as connection:
        for column_name, column_definition in booking_column_migrations.items():
            if column_name not in booking_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE booking ADD COLUMN {column_name} {column_definition}"
                )
        connection.exec_driver_sql(
            "UPDATE booking SET status = 'Under Review' WHERE status = 'New'"
        )

def generate_customer_number():
    while True:
        number = secrets.randbelow(1000000)
        customer_number = f"CLP-C-{number:06d}"

        existing = Customer.query.filter_by(
            customer_number=customer_number
        ).first()

        if not existing:
            return customer_number

@app.get("/")
@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    from rewards import fetch_one
    today = datetime.now().date()
    tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
    expiry_limit = tomorrow + timedelta(days=30)
    # Include waivers valid through today, matching booking code date semantics.
    valid_waivers = Waiver.query.filter(
        Waiver.is_archived.is_(False), Waiver.status != "Superseded",
        Waiver.expiry_date >= datetime.combine(today, datetime.min.time()))
    expiring_query = valid_waivers.filter(Waiver.expiry_date < expiry_limit)
    pending_query = Booking.query.filter_by(status="Under Review")
    upcoming = []
    for booking in Booking.query.filter_by(status="Accepted").all():
        for event in booking_schedule_events(booking):
            try:
                event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                continue
            if event_date >= today:
                upcoming.append({"booking": booking, "event": event, "date": event_date})
    upcoming.sort(key=lambda item: (item["date"], item["event"].get("start_time", "")))
    reward_count = fetch_one("SELECT COUNT(*) AS total FROM referrals WHERE status = 'earned'")["total"]
    return render_template(
        "admin_dashboard.html", today=today,
        pending_count=pending_query.count(),
        upcoming_event_count=Event.query.filter(Event.event_date >= today, Event.status != "Closed").count(),
        valid_waiver_count=valid_waivers.count(), reward_count=reward_count,
        pending_bookings=pending_query.order_by(Booking.submitted_at.asc()).limit(5).all(),
        expiring_count=expiring_query.count(),
        expiring_waivers=expiring_query.order_by(Waiver.expiry_date.asc()).limit(5).all(),
        upcoming_bookings=upcoming[:5], upcoming_booking_count=len(upcoming))


@app.get("/waiver")
def waiver():
    return """
    <!doctype html>
    <html>
    <head>
        <title>CL Paints Waiver</title>
    </head>
    <body style="font-family: Arial, sans-serif; text-align:center; padding:60px 20px;">
        <h1>CL Paints</h1>
        <p>Please use the waiver link or QR code provided for your event.</p>
    </body>
    </html>
    """


@app.get("/waiver/event/<int:event_id>")
def waiver_event(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return "Event not found.", 404

    moodboard_rows = EventMoodboardImage.query.filter_by(
        event_id=event.id
    ).order_by(
        EventMoodboardImage.sort_order.asc()
    ).all()

    moodboard_images = [
        row.image
        for row in moodboard_rows
        if row.image is not None and row.image.active
    ]

    large_moodboard_images = [
    image
    for image in moodboard_images
    if image.design_type == "large"
    ]

    small_moodboard_images = [
    image
    for image in moodboard_images
    if image.design_type == "small"
    ]

    for image in moodboard_images:
        print("IMAGE:", image.id, image.title, image.image_url)

    return render_template(
    "waiver.html",
    current_event=event,
    moodboard_images=moodboard_images,
    large_moodboard_images=large_moodboard_images,
    small_moodboard_images=small_moodboard_images
    )

@app.post("/admin/moodboard/upload")
@admin_required
def admin_moodboard_upload():
    files = request.files.getlist("images")

    design_type = request.form.get("design_type", "large").strip().lower()

    if design_type not in ("large", "small"):
        design_type = "large"

    allowed_extensions = {"jpg", "jpeg", "png", "webp"}

    uploaded_count = 0

    for file in files:
        if not file or not file.filename:
            continue

        extension = (
            file.filename.rsplit(".", 1)[1].lower()
            if "." in file.filename
            else ""
        )

        if extension not in allowed_extensions:
            continue

        result = cloudinary.uploader.upload(
            file,
            folder="cl-paints/moodboard",
            resource_type="image"
        )

        title = os.path.splitext(file.filename)[0]
        title = title.replace("_", " ").replace("-", " ").strip()

        image = MoodboardImage(
            title=title or "Moodboard Image",
            image_url=result["secure_url"],
            storage_id=result["public_id"],
            active=True,
            design_type=design_type

        )

        db.session.add(image)
        uploaded_count += 1

    if uploaded_count:
        db.session.commit()

    return redirect(url_for("admin_moodboard"))

@app.post("/admin/moodboard/<int:image_id>/rename")
@admin_required
def admin_moodboard_rename(image_id):
    image = db.session.get(MoodboardImage, image_id)

    if image is None:
        return redirect(url_for("admin_moodboard"))

    title = request.form.get("title", "").strip()
    design_type = request.form.get("design_type", "").strip().lower()

    if title:
        image.title = title

    if design_type in ("large", "small"):
        image.design_type = design_type

    db.session.commit()

    return redirect(url_for("admin_moodboard"))


@app.post("/admin/moodboard/<int:image_id>/delete")
@admin_required
def admin_moodboard_delete(image_id):
    image = db.session.get(MoodboardImage, image_id)

    if image is None:
        return redirect(url_for("admin_moodboard"))

    # Remove this image from any events first
    EventMoodboardImage.query.filter_by(
        image_id=image.id
    ).delete()

    # Remove the actual image from Cloudinary
    if image.storage_id:
        cloudinary.uploader.destroy(
            image.storage_id,
            resource_type="image"
        )

    db.session.delete(image)
    db.session.commit()

    return redirect(url_for("admin_moodboard"))

@app.get("/admin/moodboard")
@admin_required
def admin_moodboard():
    images = MoodboardImage.query.order_by(
        MoodboardImage.created_at.desc()
    ).all()

    return render_template(
        "admin_moodboard.html",
        images=images
    )

@app.get("/admin/events/<int:event_id>/moodboard")
@admin_required
def admin_event_moodboard(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return redirect(url_for("admin_events"))

    images = MoodboardImage.query.filter_by(
        active=True
    ).order_by(
        MoodboardImage.created_at.desc()
    ).all()

    selected_rows = EventMoodboardImage.query.filter_by(
        event_id=event.id
    ).all()

    selected_image_ids = {
        row.image_id for row in selected_rows
    }

    return render_template(
        "admin_event_moodboard.html",
        event=event,
        images=images,
        selected_image_ids=selected_image_ids
    )

@app.post("/admin/events/<int:event_id>/moodboard")
@admin_required
def admin_event_moodboard_save(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return redirect(url_for("admin_events"))

    selected_ids = request.form.getlist("image_ids")

    # Remove the event's existing selections
    EventMoodboardImage.query.filter_by(
        event_id=event.id
    ).delete()

    # Save the newly selected images
    for sort_order, image_id in enumerate(selected_ids):

        try:
            image_id = int(image_id)
        except ValueError:
            continue

        image = db.session.get(MoodboardImage, image_id)

        if image is None or not image.active:
            continue

        assignment = EventMoodboardImage(
            event_id=event.id,
            image_id=image.id,
            sort_order=sort_order
        )

        db.session.add(assignment)

    db.session.commit()

    return redirect(
        url_for(
            "admin_event_moodboard",
            event_id=event.id
        )
    )

@app.post("/api/waivers/event/<int:event_id>")
def create_waiver(event_id):
    current_event = db.session.get(Event, event_id)

    if current_event is None:
        return jsonify({
            "success": False,
            "error": "Event not found."
        }), 404

    if not current_event or current_event.status == "Closed":
        return jsonify({
            "success": False,
            "error": "New waiver submissions are currently closed."
        }), 403

    data = request.get_json()
    if not data:
        return jsonify({
            "success": False,
            "error": "No waiver data received."
        }), 400

    required_fields = [
        "responsible_first_name",
        "responsible_last_name",
        "responsible_email",
        "signature_text"
    ]

    for field in required_fields:
        if not str(data.get(field, "")).strip():
            return jsonify({
                "success": False,
                "error": f"Missing required field: {field}"
            }), 400

        participants = data.get("participants", [])

        if not isinstance(participants, list) or not 1 <= len(participants) <= 4:
            return jsonify({
                "success": False,
                "error": "A waiver must contain between 1 and 4 participants."
            }), 400

        allowed_genders = {
    "Male",
    "Female",
    "Gender Neutral"
    }

        email = str(
        data.get("responsible_email", "")
    ).strip()

    if (
        "@" not in email
        or "." not in email.split("@")[-1]
    ):
        return jsonify({
            "success": False,
            "error": "Please enter a valid email address."
        }), 400

    for person in participants:
        first_name = str(
            person.get("first_name", "")
        ).strip()

        last_name = str(
            person.get("last_name", "")
        ).strip()

        age = person.get("age")
        gender = person.get("gender")

        if not first_name or not last_name:
            return jsonify({
                "success": False,
                "error": "Each participant must have a first and last name."
            }), 400

        try:
            age = int(age)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "error": "Each participant must have a valid age."
            }), 400

        if age < 2 or age > 120:
            return jsonify({
                "success": False,
                "error": "Participant age must be between 2 and 120."
            }), 400

        if gender not in allowed_genders:
            return jsonify({
                "success": False,
                "error": "Invalid participant gender."
            }), 400

        person["first_name"] = first_name
        person["last_name"] = last_name
        person["age"] = age
        person["gender"] = gender

        required_acknowledgements = [
            "liability_acknowledged",
            "responsible_authority",
            "responsible_accuracy"
        ]

    for acknowledgement in required_acknowledgements:
        if data.get(acknowledgement) is not True:
            return jsonify({
                "success": False,
                "error": "All required declarations must be confirmed."
            }), 400

        marketing_consent = data.get("marketing_consent", False)

        if not isinstance(marketing_consent, bool):
            return jsonify({
                "success": False,
                "error": "Invalid marketing consent value."
            }), 400

        now = datetime.now()
        expiry = now + relativedelta(months=12)

        while True:
            waiver_reference = (
                f"CLP-W-{now.strftime('%Y%m%d')}-"
                f"{secrets.token_hex(2).upper()}"
            )

            existing_waiver = Waiver.query.filter_by(
                waiver_reference=waiver_reference
            ).first()

            if existing_waiver is None:
                break
            
        try:
            terms_snapshot = TERMS_TEMPLATE_PATH.read_text(
                encoding="utf-8"
            )
        except OSError:
            return jsonify({
                "success": False,
                "error": "The waiver terms could not be loaded. Please try again."
            }), 500

        customer = Customer.query.filter(
        db.func.lower(Customer.email) == email.lower()
        ).first()

        if not customer:
            customer = Customer(
                customer_number=generate_customer_number(),
                first_name=str(
                    data.get("responsible_first_name", "")
                ).strip(),
                last_name=str(
                    data.get("responsible_last_name", "")
                ).strip(),
                email=email,
                email_verified=False
            )

            db.session.add(customer)
            db.session.flush()


    
        waiver = Waiver(
            customer_id=customer.id,
            waiver_reference=waiver_reference,
            responsible_first_name=data["responsible_first_name"],
            responsible_last_name=data["responsible_last_name"],
            responsible_email=data["responsible_email"],
            signed_date=now,
            expiry_date=expiry,
            status="Valid",
            event_name=current_event.name,
            event_date=current_event.event_date,
            marketing_consent=marketing_consent,
            terms_version=TERMS_VERSION,
            terms_snapshot=terms_snapshot,
            liability_acknowledged=data.get(
            "liability_acknowledged",
            False
        ),
        responsible_authority=data.get(
            "responsible_authority",
            False
        ),
        responsible_accuracy=data.get(
            "responsible_accuracy",
            False
        ),
        signature_text=data["signature_text"]
    )

    db.session.add(waiver)
    db.session.flush()

    for person in data.get("participants", []):
        participant = Participant(
            waiver_id=waiver.id,
            first_name=person["first_name"],
            last_name=person["last_name"],
            age=person["age"],
            gender=person["gender"]
        )

        db.session.add(participant)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": "The waiver could not be saved. Please try again."
        }), 500

    participant_names = ", ".join(
    f"{person.first_name} {person.last_name}"
    for person in waiver.participants
)

    confirmation_subject = (
        f"CL Paints Waiver Confirmation - {waiver.waiver_reference}"
    )

    confirmation_body = f"""
Hello {waiver.responsible_first_name},

Thank you for completing your CL Paints waiver.

Waiver Reference: {waiver.waiver_reference}
Event: {waiver.event_name}
People Covered: {participant_names}
Date Completed: {waiver.signed_date.strftime('%d/%m/%Y')}
Valid Until: {waiver.expiry_date.strftime('%d/%m/%Y')}

This waiver remains valid for 12 months from the date completed, subject to the information provided remaining accurate.

Please keep this email for your records.

CL Paints
Bringing colour to life, one face at a time!
www.clpaints.com
info@clpaints.com
"""

    try:
        resend.Emails.send({
            "from": "CL Paints <info@clpaints.com>",
            "to": [waiver.responsible_email],
            "subject": confirmation_subject,
            "text": confirmation_body
        })
    except Exception as email_error:
        print(
            "Waiver confirmation email failed:",
            email_error
        )

    return jsonify({
        "success": True,
        "waiver_reference": waiver.waiver_reference,
        "confirmation_subject": confirmation_subject,
        "confirmation_body": confirmation_body
    })

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    credential = AdminCredential.query.order_by(AdminCredential.id.asc()).first()

    if request.method == "POST":
        password = request.form.get("password", "")
        password_is_valid = (
            check_password_hash(credential.password_hash, password)
            if credential
            else bool(ADMIN_PASSWORD) and secrets.compare_digest(password, ADMIN_PASSWORD)
        )

        if not credential and not ADMIN_PASSWORD:
            error = "Admin password has not been configured."
        elif password_is_valid:
            session.clear()
            session["admin_authenticated"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Incorrect password."

    return render_template(
        "admin_login.html",
        error=error,
        reset_success=request.args.get("reset") == "success",
    )


@app.route("/admin/password-reset", methods=["GET", "POST"])
def admin_password_reset_request():
    recovery_email = get_business_settings()["recovery_email"]
    recovery_configured = bool(recovery_email and RESEND_API_KEY)
    requested = False

    if request.method == "POST":
        requested = True
        submitted_email = request.form.get("email", "").strip()
        try:
            normalized_email = validate_email(
                submitted_email,
                check_deliverability=False,
            ).normalized.lower()
            configured_email = validate_email(
                recovery_email,
                check_deliverability=False,
            ).normalized.lower() if recovery_email else ""
        except EmailNotValidError:
            normalized_email = ""
            configured_email = ""

        if recovery_configured and normalized_email and secrets.compare_digest(
            normalized_email,
            configured_email,
        ):
            now = datetime.now()
            recent_reset = AdminPasswordReset.query.filter(
                AdminPasswordReset.created_at >= now - timedelta(minutes=5)
            ).first()
            if recent_reset is None:
                raw_token = secrets.token_urlsafe(32)
                reset = AdminPasswordReset(
                    token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                    created_at=now,
                    expires_at=now + timedelta(minutes=30),
                )
                db.session.add(reset)
                db.session.commit()
                reset_url = url_for(
                    "admin_password_reset",
                    token=raw_token,
                    _external=True,
                )
                try:
                    resend.Emails.send({
                        "from": "CL Paints <info@clpaints.com>",
                        "to": [configured_email],
                        "subject": "Reset your CL Paints admin password",
                        "text": (
                            "A password reset was requested for the CL Paints admin account.\n\n"
                            f"Use this one-time link within 30 minutes:\n{reset_url}\n\n"
                            "If you did not request this, ignore this email."
                        ),
                    })
                except Exception as email_error:
                    reset.used_at = datetime.now()
                    db.session.commit()
                    print("Admin password reset email failed:", email_error)

    return render_template(
        "admin_password_reset_request.html",
        requested=requested,
        recovery_configured=recovery_configured,
    )


@app.route("/admin/password-reset/<token>", methods=["GET", "POST"])
def admin_password_reset(token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    reset = AdminPasswordReset.query.filter_by(token_hash=token_hash).first()
    now = datetime.now()
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        return render_template(
            "admin_password_reset.html",
            invalid_link=True,
            error=None,
            token=None,
        ), 410

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        if len(password) < 12:
            error = "Choose a password with at least 12 characters."
        elif len(password) > 256:
            error = "Choose a shorter password."
        elif password != confirmation:
            error = "The passwords do not match."
        else:
            credential = AdminCredential.query.order_by(AdminCredential.id.asc()).first()
            if credential is None:
                credential = AdminCredential(password_hash=generate_password_hash(password))
                db.session.add(credential)
            else:
                credential.password_hash = generate_password_hash(password)
                credential.updated_at = now
            reset.used_at = now
            AdminPasswordReset.query.filter(
                AdminPasswordReset.id != reset.id,
                AdminPasswordReset.used_at.is_(None),
            ).update({AdminPasswordReset.used_at: now})
            db.session.commit()
            session.clear()
            return redirect(url_for("admin_login", reset="success"))

    return render_template(
        "admin_password_reset.html",
        invalid_link=False,
        error=error,
        token=token,
    )


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.post("/api/bookings/availability-check")
def booking_availability_check():
    data = request.get_json(silent=True) or {}

    try:
        event_date = datetime.strptime(data.get("date", ""), "%Y-%m-%d").date()
        requested_start = datetime.strptime(data.get("start_time", ""), "%H:%M")
        requested_finish = datetime.strptime(data.get("finish_time", ""), "%H:%M")
    except ValueError:
        return jsonify({"success": False, "error": "Enter a valid event date and time."}), 400

    if event_date < datetime.now().date():
        return jsonify({"success": False, "error": "Choose a future event date."}), 400
    if requested_finish <= requested_start:
        return jsonify({"success": False, "error": "Finish time must be after start time."}), 400
    if not data.get("address", "").strip() or not data.get("event_type", "").strip():
        return jsonify({"success": False, "error": "Enter the event address and event type."}), 400

    for booking in Booking.query.filter_by(status="Accepted").all():
        try:
            saved_schedule = json.loads(booking.event_schedule or "{}")
            saved_events = saved_schedule.get("events", []) if isinstance(saved_schedule, dict) else saved_schedule
        except (TypeError, ValueError):
            saved_events = []

        if not saved_events:
            saved_events = [{
                "date": booking.event_date.isoformat(),
                "start_time": booking.start_time,
                "finish_time": booking.finish_time,
            }]

        for saved_event in saved_events:
            if saved_event.get("date") != event_date.isoformat():
                continue
            try:
                existing_start = datetime.strptime(saved_event["start_time"], "%H:%M")
                existing_finish = datetime.strptime(saved_event["finish_time"], "%H:%M")
            except (KeyError, TypeError, ValueError):
                continue
            if requested_start < existing_finish and requested_finish > existing_start:
                return jsonify({
                    "success": True,
                    "available": False,
                    "message": "That time overlaps an accepted booking. Please choose another time.",
                })

    return jsonify({
        "success": True,
        "available": True,
        "message": "No accepted booking overlaps that time. Availability remains subject to confirmation by CL Paints.",
    })


def booking_code_is_valid(code):
    from rewards import fetch_one, parse_date
    if db.session.get(ReferralCodeUse, code) is not None or Booking.query.filter_by(promo_code=code).first() is not None:
        return False
    referral = fetch_one("SELECT * FROM referrals WHERE code = :code", {"code": code})
    if referral:
        return (referral["status"] == "active"
                and parse_date(referral["original_event_date"]) <= datetime.now().date()
                <= parse_date(referral["expires_date"]))
    return False


def claim_booking_code(code):
    # The unique key arbitrates concurrent submissions; the claim commits with the booking.
    if not booking_code_is_valid(code):
        raise ValueError("Code invalid. It has already been used, is expired or is unavailable.")
    try:
        db.session.add(ReferralCodeUse(code=code))
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("Code invalid. This referral code has already been used.") from None


@app.post("/api/referrals/verify")
def verify_referral_code():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("code", ""), str):
        return jsonify({"status": "invalid", "message": "Enter a valid referral code."}), 400
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"status": "empty", "message": "Enter a referral code."}), 400
    if not booking_code_is_valid(code):
        return jsonify({"status": "invalid", "message": "Code invalid. Check the code and try again; used, expired or already processed codes cannot be used."})
    return jsonify({"status": "valid", "message": "Code confirmed. It will be recorded with your booking."})


@app.get("/admin/rewards")
@admin_required
def admin_rewards():
    return redirect(url_for("rewards.dashboard"))


def send_booking_request_confirmation(booking):
    if not RESEND_API_KEY:
        print("Booking acknowledgement email was not sent: RESEND_API_KEY is not configured.")
        return False

    try:
        schedule_data = json.loads(booking.event_schedule or "{}")
        events = schedule_data.get("events", [])
    except (TypeError, ValueError):
        events = []

    lines = [
        f"Booking request #{booking.id}",
        "Status: Under Review",
        "",
        "We have received your booking request. The request is under review, and CL Paints will contact you after checking the details.",
        "",
        "CLIENT DETAILS",
        f"Name: {booking.title + ' ' if booking.title else ''}{booking.first_name} {booking.last_name}",
        f"Client type: {booking.client_type.title()}",
        f"Job title: {booking.job_title or 'Not provided'}",
        f"Date of birth: {booking.date_of_birth.strftime('%d/%m/%Y')}",
        f"18 or over confirmed: {'Yes' if booking.is_over_18 else 'No'}",
        f"Ethnicity: {booking.ethnicity}{' / ' + booking.ethnicity_detail if booking.ethnicity_detail else ''}",
        f"Religion: {booking.religion}",
        f"Address: {booking.client_address}",
        f"Phone: {booking.phone}",
        f"Email: {booking.email}",
        "",
        "EVENT DETAILS",
    ]

    for index, event in enumerate(events, start=1):
        lines.extend([
            f"Event day {index}",
            f"Date: {event.get('date', '')}",
            f"Time: {event.get('start_time', '')} to {event.get('finish_time', '')}",
            f"Duration: {event.get('duration_hours', '')} hours",
            f"Address: {event.get('event_address', '')}",
            f"Event type: {event.get('event_type', '')}",
            f"Theme: {event.get('theme', '')}",
            f"Expected attendees: {event.get('expected_attendees') if event.get('expected_attendees') is not None else 'Not provided'}",
            f"Event setting: {event.get('publicity_type', '')}",
            f"Painting location: {event.get('location_type', '')}",
            f"Who pays for face painting: {event.get('charge_type', '')}",
            f"CL Paints pitch fee: {'Yes' if event.get('pitch_fee_required') else 'No'}",
            f"Pitch fee payable by CL Paints (excluded from client cost): {'£' + str(event['pitch_fee_amount']) if event.get('pitch_fee_amount') is not None else 'Not applicable or not recorded'}",
            f"Estimated event cost: £{Decimal(event.get('estimated_cost', '0')):.2f}",
            f"Christmas and Easter celebrated: {event.get('celebrates_christmas_easter') or 'Not provided'}",
            f"Additional information: {event.get('additional_info') or 'None'}",
            "",
        ])

    lines.extend([
        "PAYMENT AND TOTALS",
        f"Estimated event subtotal: £{Decimal(booking.total_event_cost or 0):.2f}",
        f"Preferred payment arrangement: {booking.payment_preference}",
        f"Referral code: {booking.promo_code or 'None'}",
        "Travel charges are not included in this estimate and will be calculated by CL Paints during review.",
        "No payment has been taken and this request is not yet a confirmed booking.",
        "",
        "LIABILITY AND AGREEMENT",
        f"Liability statement acknowledged: {'Yes' if booking.liability_acknowledged else 'No'}",
        f"Booking terms accepted: Yes (version {booking.terms_version})",
        f"Client signature: {booking.signature}",
        "",
        "CL Paints",
        "info@clpaints.com",
    ])

    try:
        resend.Emails.send({
            "from": "CL Paints <info@clpaints.com>",
            "to": [booking.email],
            "subject": f"Booking request received - #{booking.id} (Under Review)",
            "text": "\n".join(lines),
        })
        return True
    except Exception as email_error:
        print("Booking acknowledgement email failed:", email_error)
        return False


@app.route("/booking", methods=["GET", "POST"])
def booking_request():
    settings = get_business_settings()
    pricing_rules = {key: settings[key] for key in ['hourly_rate', 'minimum_hours', 'max_event_dates', 'free_miles', 'mile_rate', 'travel_cap']}
    portal_account = get_current_client()
    if portal_account and request.method == 'POST':
        import hmac
        if not session.get('client_csrf') or not hmac.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)
    form_data = request.form if request.method == "POST" else ({
        'first_name': portal_account.first_name, 'last_name': portal_account.last_name,
        'email': portal_account.email, 'phone': portal_account.phone,
        'client_address': portal_account.address,
    } if portal_account else {})
    error = None

    if request.method == "POST":
        try:
            request_type = request.form.get("request_type", "")
            if request_type != "booking":
                raise ValueError("Use the quick availability checker for availability requests.")

            client_type = request.form.get("client_type", "")
            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            email = portal_account.email if portal_account else request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            client_address = request.form.get("client_address", "").strip()
            job_title = request.form.get("job_title", "").strip()
            signature = request.form.get("signature", "").strip()

            if client_type not in {"individual", "business"}:
                raise ValueError("Choose whether you are a private individual or a business.")
            if client_type == "business" and not job_title:
                raise ValueError("Enter your job title for the business booking.")
            if not all((first_name, last_name, email, phone, client_address, signature)):
                raise ValueError("Complete all required client details.")

            try:
                email = validate_email(email, check_deliverability=False).normalized
            except EmailNotValidError:
                raise ValueError("Enter a valid email address.")

            try:
                parsed_phone = phonenumbers.parse(phone, "GB")
            except phonenumbers.NumberParseException:
                raise ValueError("Enter a valid phone number, including its country code if needed.")
            if not phonenumbers.is_valid_number(parsed_phone):
                raise ValueError("Enter a valid phone number.")

            try:
                date_of_birth = datetime.strptime(
                    request.form.get("date_of_birth", ""), "%Y-%m-%d"
                ).date()
            except ValueError:
                raise ValueError("Enter a valid date of birth.")

            if request.form.get("is_over_18") != "yes":
                raise ValueError("The person making the booking must confirm they are 18 or over.")
            today = datetime.now().date()
            age = today.year - date_of_birth.year - (
                (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
            )
            if age < 18:
                raise ValueError("The person making the booking must be aged 18 or over.")

            ethnicity = request.form.get("ethnicity", "")
            ethnicity_detail = request.form.get("ethnicity_detail", "")
            religion = request.form.get("religion", "")
            if ethnicity not in {*ETHNICITY_BREAKDOWNS, "Prefer not to say"}:
                raise ValueError("Choose an ethnicity response.")
            if ethnicity in ETHNICITY_BREAKDOWNS and ethnicity_detail not in ETHNICITY_BREAKDOWNS[ethnicity]:
                raise ValueError("Choose a more specific ethnicity response.")
            if ethnicity == "Prefer not to say":
                ethnicity_detail = "Prefer not to say"
            allowed_religions = {
                "Christian", "Muslim", "Hindu", "Sikh", "Buddhist",
                "Jewish", "Other", "No Religion", "Prefer not to say",
            }
            if religion not in allowed_religions:
                raise ValueError("Choose a religion response.")

            try:
                submitted_schedule = json.loads(request.form.get("event_schedule", ""))
            except ValueError:
                submitted_schedule = None
            if isinstance(submitted_schedule, dict):
                submitted_events = submitted_schedule.get("events", [])
                all_dates_same_details = bool(submitted_schedule.get("same_details"))
            else:
                submitted_events = []
                all_dates_same_details = False
            if not submitted_events:
                submitted_events = [{
                    "date": request.form.get("event_date", ""),
                    "start_time": request.form.get("start_time", ""),
                    "finish_time": request.form.get("finish_time", ""),
                    "event_address": request.form.get("event_address", ""),
                    "event_type": request.form.get("event_type", ""),
                    "theme": request.form.get("theme", ""),
                    "pitch_fee_required": request.form.get("pitch_fee_required", ""),
                    "pitch_fee_amount": request.form.get("pitch_fee_amount", ""),
                }]

            single_date = request.form.get("single_date", "")
            if single_date not in {"yes", "no"}:
                raise ValueError("Choose whether this booking is for one or multiple dates.")
            if len(submitted_events) > int(pricing_rules["max_event_dates"]):
                raise ValueError(f"A booking can include up to {pricing_rules['max_event_dates']} event dates.")
            if (single_date == "yes" and len(submitted_events) != 1) or (single_date == "no" and len(submitted_events) < 2):
                raise ValueError("The selected number of dates does not match your event schedule.")

            normalized_schedule = []
            total_event_cost = Decimal("0.00")
            for day_number, event_item in enumerate(submitted_events, start=1):
                try:
                    event_date = datetime.strptime(event_item.get("date", ""), "%Y-%m-%d").date()
                    start_time = datetime.strptime(event_item.get("start_time", ""), "%H:%M")
                    finish_time = datetime.strptime(event_item.get("finish_time", ""), "%H:%M")
                except (TypeError, ValueError):
                    raise ValueError(f"Enter a valid date and start and finish times for event day {day_number}.")
                if event_date < today:
                    raise ValueError(f"Choose a future date for event day {day_number}.")
                if finish_time <= start_time:
                    raise ValueError(f"Finish time must be after start time for event day {day_number}.")
                duration_hours = Decimal(str((finish_time - start_time).total_seconds())) / Decimal("3600")
                if duration_hours < Decimal(pricing_rules["minimum_hours"]):
                    raise ValueError(f"Event day {day_number} must be at least {pricing_rules['minimum_hours']} hours long.")
                event_address = str(event_item.get("event_address", "")).strip()
                event_type = str(event_item.get("event_type", "")).strip()
                theme = str(event_item.get("theme", "")).strip()
                pitch_value = str(event_item.get("pitch_fee_required", "")).lower()
                publicity_type = str(event_item.get("publicity_type", ""))
                location_type = str(event_item.get("location_type", ""))
                charge_type = str(event_item.get("charge_type", ""))
                if pitch_value not in {"yes", "no"}:
                    raise ValueError(f"Choose the pitch-fee option for event day {day_number}.")
                if not all((event_address, event_type, theme)):
                    raise ValueError(f"Complete the address, event type, and theme for event day {day_number}.")
                if publicity_type not in {"Public", "Private"}:
                    raise ValueError(f"Choose the event setting for event day {day_number}.")
                if location_type not in {"Indoors", "Outdoors"}:
                    raise ValueError(f"Choose the painting location for event day {day_number}.")
                if charge_type not in {"Client", "Customers"}:
                    raise ValueError(f"Choose who pays for event day {day_number}.")
                attendees_raw = str(event_item.get("expected_attendees", "")).strip()
                try:
                    expected_attendees = int(attendees_raw) if attendees_raw else None
                except ValueError:
                    raise ValueError(f"Enter a valid attendee count for event day {day_number}.")
                if expected_attendees is not None and expected_attendees < 0:
                    raise ValueError(f"Attendee count cannot be negative for event day {day_number}.")
                celebrates = str(event_item.get("celebrates_christmas_easter", "")) if publicity_type == "Private" else ""
                if celebrates not in {"", "yes", "no"}:
                    raise ValueError(f"Choose the holiday preference for event day {day_number}.")
                pitch_fee_required = pitch_value == "yes"
                pitch_fee_amount = None
                if pitch_fee_required:
                    try:
                        pitch_fee_amount = Decimal(str(event_item.get("pitch_fee_amount", "")))
                    except InvalidOperation:
                        raise ValueError(f"Enter a valid pitch fee for event day {day_number}.")
                    if not pitch_fee_amount.is_finite() or pitch_fee_amount < 0 or pitch_fee_amount > Decimal("999999.99"):
                        raise ValueError(f"Enter a pitch fee between £0 and £999,999.99 for event day {day_number}.")
                    if pitch_fee_amount != pitch_fee_amount.quantize(Decimal("0.01")):
                        raise ValueError(f"Enter the pitch fee with no more than two decimal places for event day {day_number}.")
                day_cost = Decimal("0.00") if pitch_fee_required else (duration_hours * Decimal(pricing_rules["hourly_rate"])).quantize(Decimal("0.01"))
                total_event_cost += day_cost
                normalized_schedule.append({
                    "date": event_date.isoformat(),
                    "start_time": start_time.strftime("%H:%M"),
                    "finish_time": finish_time.strftime("%H:%M"),
                    "duration_hours": str(duration_hours.normalize()),
                    "event_address": event_address,
                    "event_type": event_type,
                    "theme": theme,
                    "pitch_fee_required": pitch_fee_required,
                    "pitch_fee_amount": str(pitch_fee_amount.quantize(Decimal("0.01"))) if pitch_fee_amount is not None else None,
                    "expected_attendees": expected_attendees,
                    "publicity_type": publicity_type,
                    "location_type": location_type,
                    "charge_type": charge_type,
                    "celebrates_christmas_easter": celebrates or None,
                    "additional_info": str(event_item.get("additional_info", "")).strip() or None,
                    "estimated_cost": str(day_cost),
                })

            payment_preference = request.form.get("payment_preference", "")
            if payment_preference not in {"Full payment", "50% deposit"}:
                raise ValueError("Choose a payment preference.")
            if request.form.get("liability_acknowledged") != "yes":
                raise ValueError("Read and acknowledge the liability statement.")
            if request.form.get("terms_accepted") != "yes":
                raise ValueError("Accept the booking terms and conditions to continue.")

            promo_code = request.form.get("promo_code", "").strip() or None
            referral_verified = None
            if promo_code:
                referral_verified = booking_code_is_valid(promo_code)
                if not referral_verified:
                    raise ValueError("The referral code is invalid, already processed or expired. Remove it or enter a valid code.")
                claim_booking_code(promo_code)

            first_event = normalized_schedule[0]
            booking = Booking(
                request_type=request_type,
                client_type=client_type,
                title=request.form.get("title", "").strip() or None,
                job_title=job_title or None,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                is_over_18=True,
                ethnicity=ethnicity,
                ethnicity_detail=ethnicity_detail or None,
                religion=religion,
                client_address=client_address,
                phone=phone,
                email=email,
                event_date=datetime.strptime(first_event["date"], "%Y-%m-%d").date(),
                single_date=single_date == "yes",
                additional_event_dates=", ".join(item["date"] for item in normalized_schedule[1:]) or None,
                event_schedule=json.dumps({
                    "pricing_rules": pricing_rules,
                    "same_details": all_dates_same_details,
                    "events": normalized_schedule,
                }),
                start_time=first_event["start_time"],
                finish_time=first_event["finish_time"],
                event_address=first_event["event_address"],
                publicity_type=first_event["publicity_type"],
                charge_type=first_event["charge_type"],
                location_type=first_event["location_type"],
                event_type=first_event["event_type"],
                theme=first_event["theme"],
                expected_attendees=first_event["expected_attendees"],
                celebrates_christmas_easter=(
                    first_event["celebrates_christmas_easter"] == "yes"
                    if first_event["celebrates_christmas_easter"]
                    else None
                ),
                additional_info=first_event["additional_info"],
                pitch_fee_required=first_event["pitch_fee_required"],
                payment_preference=payment_preference,
                promo_code=promo_code,
                referral_verified=referral_verified,
                signature=signature,
                liability_acknowledged=True,
                terms_accepted_at=datetime.now(),
                terms_version="2026-10-01",
                total_event_cost=total_event_cost,
                status="Under Review",
            )
            db.session.add(booking)
            db.session.commit()
            email_sent = send_booking_request_confirmation(booking)
            if portal_account:
                return redirect(url_for('client.booking_detail', booking_id=booking.id, submitted='yes'))
            return redirect(url_for(
                "booking_request",
                submitted=booking.id,
                email_sent="yes" if email_sent else "no",
            ))

        except ValueError as validation_error:
            db.session.rollback()
            error = str(validation_error)
        except SQLAlchemyError:
            db.session.rollback()
            error = "We could not save your request. Please try again."

    return render_template(
        "booking_form.html",
        error=error,
        form_data=form_data,
        submitted=request.args.get("submitted"),
        portal_account=portal_account,
        google_maps_api_key=GOOGLE_MAPS_API_KEY,
    )


def booking_schedule_events(booking):
    try:
        schedule_data = json.loads(booking.event_schedule or "{}")
        schedule_events = schedule_data.get("events", []) if isinstance(schedule_data, dict) else schedule_data
    except (TypeError, ValueError):
        schedule_events = []

    if not schedule_events:
        schedule_events = [{
            "date": booking.event_date.isoformat(),
            "start_time": booking.start_time,
            "finish_time": booking.finish_time,
            "event_address": booking.event_address,
            "event_type": booking.event_type,
            "theme": booking.theme,
            "pitch_fee_required": booking.pitch_fee_required,
            "publicity_type": booking.publicity_type,
        }]
    return schedule_events


def send_booking_status_email(booking):
    if not RESEND_API_KEY:
        print("Booking status email was not sent: RESEND_API_KEY is not configured.")
        return False

    accepted = booking.status == "Accepted"
    status_text = "accepted" if accepted else "declined"
    lines = [
        f"Booking request #{booking.id} has been {status_text}.",
        "",
        f"Hello {booking.first_name},",
        "",
        (
            "We are pleased to accept your booking request. CL Paints will contact you to confirm the final arrangements."
            if accepted
            else "Thank you for your booking request. Unfortunately, CL Paints is unable to accept it at this time. Please reply if you would like to discuss alternatives."
        ),
        "",
        "BOOKING DETAILS",
        f"Client: {booking.first_name} {booking.last_name}",
        f"Phone: {booking.phone}",
        f"Email: {booking.email}",
    ]

    for index, event in enumerate(booking_schedule_events(booking), start=1):
        lines.extend([
            "",
            f"Event day {index}",
            f"Date: {event.get('date', '')}",
            f"Time: {event.get('start_time', '')} to {event.get('finish_time', '')}",
            f"Address: {event.get('event_address', '')}",
            f"Event: {event.get('event_type', '')} - {event.get('theme', '')}",
            f"Event setting: {event.get('publicity_type', '')}",
        ])

    total = Decimal(booking.total_event_cost or 0) + Decimal(booking.travel_charge or 0)
    lines.extend([
        "",
        f"Payment preference: {booking.payment_preference}",
        f"Event estimate: £{Decimal(booking.total_event_cost or 0):.2f}",
        f"Travel: £{Decimal(booking.travel_charge or 0):.2f}",
        f"Current total: £{total:.2f}",
        "",
        "CL Paints",
        "info@clpaints.com",
    ])

    try:
        resend.Emails.send({
            "from": "CL Paints <info@clpaints.com>",
            "to": [booking.email],
            "subject": f"Booking request #{booking.id} {status_text}",
            "text": "\n".join(lines),
        })
        return True
    except Exception as email_error:
        print("Booking status email failed:", email_error)
        return False

@app.get("/admin/waivers")
@admin_required

def admin_waivers():
    return redirect(url_for("admin_participants"))

@app.get("/admin/bookings")
@admin_required
def admin_bookings():
    bookings = Booking.query.order_by(Booking.submitted_at.desc()).all()
    booking_rows = []
    for booking in bookings:
        try:
            saved_schedule = json.loads(booking.event_schedule or "{}")
            events = saved_schedule.get("events", []) if isinstance(saved_schedule, dict) else saved_schedule
            same_details = bool(saved_schedule.get("same_details")) if isinstance(saved_schedule, dict) else False
        except (TypeError, ValueError):
            events = []
            same_details = False
        if not events:
            events = [{
                "date": booking.event_date.isoformat(),
                "start_time": booking.start_time,
                "finish_time": booking.finish_time,
                "event_address": booking.event_address,
                "event_type": booking.event_type,
                "theme": booking.theme,
                "pitch_fee_required": booking.pitch_fee_required,
                "estimated_cost": str(booking.total_event_cost or 0),
            }]
        hours = sum(float(event.get("duration_hours", 0)) for event in events)
        booking_rows.append({
            "booking": booking,
            "events": events,
            "same_details": same_details,
            "total_hours": hours,
            "final_total": Decimal(booking.total_event_cost or 0) + Decimal(booking.travel_charge or 0),
            "pricing_rules": saved_schedule.get("pricing_rules", DEFAULT_BUSINESS_SETTINGS) if isinstance(saved_schedule, dict) else DEFAULT_BUSINESS_SETTINGS,
            "public_event_count": sum(event.get("publicity_type") == "Public" for event in events),
            "created_events": Event.query.filter_by(booking_id=booking.id).order_by(Event.booking_day_number.asc()).all(),
        })

    referral_codes = ReferralCode.query.order_by(ReferralCode.code.asc()).all()
    return render_template(
        "admin_bookings.html",
        bookings=bookings,
        booking_rows=booking_rows,
        referral_codes=referral_codes,
        booking_count=len(bookings),
        new_booking_count=sum(booking.status == "Under Review" for booking in bookings),
        accepted_booking_count=sum(booking.status == "Accepted" for booking in bookings),
        declined_booking_count=sum(booking.status == "Declined" for booking in bookings),
    )


@app.post("/admin/bookings/<int:booking_id>/manage")
@admin_required
def admin_manage_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if booking is None:
        return redirect(url_for("admin_bookings"))

    previous_status = booking.status
    action = request.form.get("action", "update")
    if action == "accept":
        booking.status = "Accepted"
    elif action == "decline":
        booking.status = "Declined"
    elif action == "update":
        requested_status = request.form.get("status", booking.status)
        if requested_status in {"Under Review", "Accepted", "Declined"}:
            booking.status = requested_status
    else:
        return redirect(url_for("admin_bookings"))

    try:
        schedule_data = json.loads(booking.event_schedule or "{}")
        schedule_events = schedule_data.get("events", []) if isinstance(schedule_data, dict) else schedule_data
    except (TypeError, ValueError):
        schedule_data = {"same_details": False, "events": []}
        schedule_events = []
    if isinstance(schedule_data, list):
        schedule_data = {"same_details": False, "events": schedule_events}
    if not schedule_events:
        schedule_events = [{
            "date": booking.event_date.isoformat(),
            "start_time": booking.start_time,
            "finish_time": booking.finish_time,
            "event_address": booking.event_address,
            "event_type": booking.event_type,
            "theme": booking.theme,
            "pitch_fee_required": booking.pitch_fee_required,
        }]
        schedule_data = {"same_details": False, "events": schedule_events}

    from business_settings import DEFAULTS
    pricing_rules = dict(DEFAULTS, **schedule_data.get("pricing_rules", {}))
    remaining_travel_cap = Decimal(pricing_rules["travel_cap"])
    total_travel_charge = Decimal("0.00")
    for index, event in enumerate(schedule_events):
        try:
            travel_miles = Decimal(request.form.get(
                f"travel_miles_{index}", str(event.get("travel_miles", "0"))
            ) or "0")
        except InvalidOperation:
            return redirect(url_for("admin_bookings", update_error="travel"))
        if travel_miles < 0 or travel_miles > Decimal("10000"):
            return redirect(url_for("admin_bookings", update_error="travel"))
        charge_before_cap = max(Decimal("0.00"), travel_miles - Decimal(pricing_rules["free_miles"])) * Decimal(pricing_rules["mile_rate"])
        day_travel_charge = min(charge_before_cap, remaining_travel_cap)
        event["travel_miles"] = str(travel_miles.normalize())
        event["travel_charge"] = str(day_travel_charge.quantize(Decimal("0.01")))
        total_travel_charge += day_travel_charge
        remaining_travel_cap -= day_travel_charge

    schedule_data["events"] = schedule_events
    booking.event_schedule = json.dumps(schedule_data)
    booking.travel_charge = total_travel_charge.quantize(Decimal("0.01"))
    booking.internal_notes = request.form.get("internal_notes", "").strip() or None

    if request.form.get("sign_on_behalf") == "yes":
        company_signature = request.form.get("company_signature", "").strip()
        if not company_signature:
            return redirect(url_for("admin_bookings", update_error="signature"))
        booking.company_signature = company_signature

    db.session.commit()
    status_email_sent = None
    if booking.status != previous_status and booking.status in {"Accepted", "Declined"}:
        status_email_sent = send_booking_status_email(booking)
    return redirect(url_for(
        "admin_bookings",
        updated=booking.id,
        status_email="sent" if status_email_sent else ("failed" if status_email_sent is False else None),
    ))


@app.post("/admin/bookings/<int:booking_id>/create-events")
@admin_required
def admin_create_booking_events(booking_id):
    booking = db.session.get(Booking, booking_id)
    if booking is None:
        return redirect(url_for("admin_bookings"))
    if booking.status != "Accepted":
        return redirect(url_for("admin_bookings", event_error="not_accepted"))

    public_days = [
        (day_number, event_data)
        for day_number, event_data in enumerate(booking_schedule_events(booking), start=1)
        if event_data.get("publicity_type") == "Public"
    ]
    if not public_days:
        return redirect(url_for("admin_bookings", event_error="not_public"))

    created_count = 0
    for day_number, event_data in public_days:
        existing = Event.query.filter_by(
            booking_id=booking.id,
            booking_day_number=day_number,
        ).first()
        if existing is not None:
            continue
        try:
            event_date = datetime.strptime(event_data.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            return redirect(url_for("admin_bookings", event_error="date"))

        event_name = (
            f"{event_data.get('event_type', 'Public event')} - "
            f"{booking.first_name} {booking.last_name} "
            f"(Booking #{booking.id}, Day {day_number})"
        )[:200]
        db.session.add(Event(
            name=event_name,
            event_date=event_date,
            event_address=event_data.get("event_address", ""),
            status="Closed",
            is_current=False,
            booking_id=booking.id,
            booking_day_number=day_number,
        ))
        created_count += 1

    db.session.commit()
    return redirect(url_for(
        "admin_bookings",
        events_created=created_count,
        booking=booking.id,
    ))


@app.post("/admin/referral-codes")
@admin_required
def admin_create_referral_code():
    code = request.form.get("code", "").strip().upper()
    expires_raw = request.form.get("expires_at", "").strip()
    if not code:
        return redirect(url_for("admin_rewards", referral_error="code"))

    try:
        expires_at = datetime.strptime(expires_raw, "%Y-%m-%d").date() if expires_raw else None
    except ValueError:
        return redirect(url_for("admin_rewards", referral_error="date"))

    referral = ReferralCode.query.filter_by(code=code).first()
    if referral is None:
        referral = ReferralCode(code=code, expires_at=expires_at, active=True)
        db.session.add(referral)
    else:
        referral.expires_at = expires_at
        referral.active = True
    db.session.commit()
    return redirect(url_for("admin_rewards", referral_added=code))


@app.post("/admin/referral-codes/import")
@admin_required
def admin_import_referral_codes():
    upload = request.files.get("referral_csv")
    if upload is None or not upload.filename:
        return redirect(url_for("admin_rewards", referral_error="file"))

    try:
        contents = upload.stream.read(2_000_001)
        if len(contents) > 2_000_000:
            return redirect(url_for("admin_rewards", referral_error="size"))
        reader = csv.DictReader(StringIO(contents.decode("utf-8-sig")))
    except (UnicodeDecodeError, csv.Error):
        return redirect(url_for("admin_rewards", referral_error="file"))

    headers = {
        header.strip().lower().replace(" ", "").replace("_", ""): header
        for header in (reader.fieldnames or [])
    }
    code_header = next(
        (headers[key] for key in ("code", "referralcode") if key in headers),
        None,
    )
    expiry_header = next(
        (headers[key] for key in ("expires", "expiresat", "expiry", "expirydate") if key in headers),
        None,
    )
    active_header = headers.get("active") or headers.get("status")
    if code_header is None:
        return redirect(url_for("admin_rewards", referral_error="header"))

    imported_count = 0
    skipped_count = 0
    for row_number, row in enumerate(reader, start=1):
        if row_number > 5000:
            skipped_count += 1
            continue
        code = (row.get(code_header) or "").strip().upper()
        if not code:
            skipped_count += 1
            continue

        expires_at = None
        expiry_text = (row.get(expiry_header) or "").strip() if expiry_header else ""
        if expiry_text:
            for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    expires_at = datetime.strptime(expiry_text, date_format).date()
                    break
                except ValueError:
                    continue
            if expires_at is None:
                skipped_count += 1
                continue

        active_text = (row.get(active_header) or "active").strip().lower() if active_header else "active"
        active = active_text not in {"no", "false", "0", "inactive", "expired", "disabled"}
        if expires_at and expires_at < datetime.now().date():
            active = False

        referral = ReferralCode.query.filter_by(code=code).first()
        if referral is None:
            referral = ReferralCode(code=code)
            db.session.add(referral)
        referral.expires_at = expires_at
        referral.active = active
        imported_count += 1

    db.session.commit()
    return redirect(url_for(
        "admin_rewards",
        referral_imported=imported_count,
        referral_skipped=skipped_count,
    ))


@app.post("/admin/referral-codes/<int:code_id>/deactivate")
@admin_required
def admin_deactivate_referral_code(code_id):
    referral = db.session.get(ReferralCode, code_id)
    if referral is not None:
        referral.active = False
        db.session.commit()
    return redirect(url_for("admin_rewards"))

@app.get("/admin/participants")
@admin_required
def admin_participants():
    now = datetime.now()
    expiring_soon_date = now + relativedelta(days=30)

    waivers = Waiver.query.filter(
        Waiver.status != "Superseded",
        Waiver.is_archived.is_(False)
    ).order_by(
        Waiver.signed_date.desc()
    ).all()

    for waiver in waivers:
        if waiver.status == "Superseded":
            continue

        if waiver.expiry_date < now:
            waiver.status = "Expired"

        elif waiver.expiry_date <= expiring_soon_date:
            waiver.status = "Expiring Soon"

        else:
            waiver.status = "Valid"

    db.session.commit()

    valid_count = Waiver.query.filter(
        Waiver.status == "Valid",
        Waiver.is_archived.is_(False)
    ).count()

    participant_count = Participant.query.join(Waiver).filter(
    Waiver.is_archived.is_(False),
    Waiver.status != "Superseded"
    ).count()

    expiring_soon_count = Waiver.query.filter(
        Waiver.status == "Expiring Soon",
        Waiver.is_archived.is_(False)
    ).count()

    expired_count = Waiver.query.filter(
        Waiver.status == "Expired",
        Waiver.is_archived.is_(False)
    ).count()

    participants = (
        Participant.query
        .join(Waiver)
        .filter(
            Waiver.is_archived.is_(False),
            Waiver.status != "Superseded"
        )
        .order_by(
            Waiver.signed_date.desc(),
            Participant.last_name.asc()
        )
        .all()
    )

    event_groups = {}

    for participant in participants:
        event_name = participant.waiver.event_name or "Unknown Event"
        event_date = participant.waiver.event_date
        event_date = event_date.strftime("%d/%m/%Y") if event_date else None
        event_key = (event_name, event_date)

        if event_key not in event_groups:
            event_groups[event_key] = {
            "event": event_name,
           "event_date": event_date,
            "participants": []
        }

        event_groups[event_key]["participants"].append(participant)

    return render_template(
        "admin_participants.html",
        participants=participants,
        event_groups=event_groups,
        participant_count=participant_count,
        valid_count=valid_count,
        expiring_soon_count=expiring_soon_count,
        expired_count=expired_count,
    )

@app.get("/admin/waivers/archived")
@admin_required
def admin_archived_waivers():
    archived_waivers = (
        Waiver.query
        .filter(Waiver.is_archived.is_(True))
        .order_by(Waiver.archived_at.desc())
        .all()
    )

    return render_template(
        "admin_archived_waivers.html",
        waivers=archived_waivers
    )

@app.post("/admin/waivers/<int:waiver_id>/archive")
@admin_required
def archive_waiver(waiver_id):
    waiver = db.session.get(Waiver, waiver_id)

    if waiver is None:
        return jsonify({"error": "Waiver not found."}), 404

    if waiver.is_archived:
        return jsonify({"error": "Waiver is already archived."}), 400

    waiver.is_archived = True
    waiver.archived_at = datetime.now()
    waiver.archived_by = "Admin"

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Unable to archive waiver."}), 500

    return jsonify({
        "success": True,
        "message": "Waiver archived successfully."
    })

@app.post("/admin/waivers/<int:waiver_id>/delete")
@admin_required
def delete_waiver(waiver_id):
    waiver = db.session.get(Waiver, waiver_id)

    if waiver is None:
        return jsonify({"error": "Waiver not found."}), 404

    try:
        Participant.query.filter_by(
            waiver_id=waiver.id
        ).delete(synchronize_session=False)

        db.session.delete(waiver)
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(
            {"error": "Unable to delete waiver."}
        ), 500

    return jsonify({
        "success": True,
        "message": "Waiver permanently deleted."
    })

@app.get("/admin/events")
@admin_required
def admin_events():
    events = Event.query.order_by(Event.id.desc()).all()

    current_event = Event.query.filter_by(
        is_current=True
    ).first()

    return render_template(
        "admin_events.html",
        events=events,
        current_event=current_event
    )


@app.post("/admin/events/create")
@admin_required
def admin_create_event():
    name = request.form.get("name", "").strip()

    event_date_raw = request.form.get("event_date", "").strip()
    event_date = (
    datetime.strptime(event_date_raw, "%Y-%m-%d").date()
    if event_date_raw
    else None
)

    if name:
        event = Event(
            name=name,
            event_date=event_date,
            status="Closed",
            is_current=False
        )
        db.session.add(event)
        db.session.commit()

    return redirect(url_for("admin_events"))


@app.post("/admin/events/<int:event_id>/rename")
@admin_required
def admin_rename_event(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return redirect(url_for("admin_events"))

    new_name = request.form.get("name", "").strip()

    if new_name:
        event.name = new_name
        db.session.commit()

    return redirect(url_for("admin_events"))


@app.post("/admin/events/<int:event_id>/status")
@admin_required
def admin_set_event_status(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return redirect(url_for("admin_events"))

    new_status = request.form.get("status", "")

    if new_status in ["Open", "Closing Soon", "Closed"]:
        event.status = new_status
        db.session.commit()

    return redirect(url_for("admin_events"))

@app.post("/admin/events/<int:event_id>/delete")
@admin_required
def admin_delete_event(event_id):
    event = db.session.get(Event, event_id)

    if event is None:
        return redirect(url_for("admin_events"))

    db.session.delete(event)
    db.session.commit()

    return redirect(url_for("admin_events"))

@app.get("/admin/waivers/<int:waiver_id>")
@admin_required
def admin_waiver_detail(waiver_id):
    waiver = Waiver.query.get_or_404(waiver_id)

    return render_template(
        "admin_waiver_detail.html",
        waiver=waiver
)

import rewards as rewards_module
with app.app_context():
    rewards_module.engine = db.engine
    rewards_module.init_db()
app.register_blueprint(rewards_module.app)
from rewards_transfer import register_transfer
register_transfer(app, rewards_module.engine, admin_required)

from reports import register_reports
register_reports(app, db, Booking, Waiver, Participant, ReportLocation, booking_schedule_events, admin_required)


from business_settings import register_settings
get_business_settings = register_settings(app, db, BusinessSetting, AdminCredential, AdminPasswordReset, admin_required, ADMIN_PASSWORD, ADMIN_EMAIL)


def send_client_email(to, subject, body):
    if not RESEND_API_KEY:
        return False
    try:
        resend.Emails.send({'from': 'CL Paints <info@clpaints.com>', 'to': [to], 'subject': subject, 'text': body})
        return True
    except Exception:
        app.logger.warning('Client verification email delivery failed.')
        return False


from client_portal import register_client_portal
get_current_client = register_client_portal(app, db, ClientAccount, ClientLoginCode, ClientRewardOwner, ClientEnquiry,
    Booking, get_business_settings, lambda *args: send_client_email(*args), booking_schedule_events, admin_required)

if __name__ == '__main__':
    app.run(debug=True)
