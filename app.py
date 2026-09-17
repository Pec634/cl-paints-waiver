from flask import Flask, render_template, request, jsonify, render_template_string, session, redirect, url_for
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from pathlib import Path
from dateutil.relativedelta import relativedelta
import secrets
import resend
import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

TERMS_VERSION = "2026-09-10"
TERMS_TEMPLATE_PATH = Path(__file__).parent / "templates" / "terms_and_liability.html"
resend.api_key = RESEND_API_KEY

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
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

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
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(200),
        nullable=False
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

def generate_customer_number():
    while True:
        number = secrets.randbelow(1000000)
        customer_number = f"CLP-C-{number:06d}"

        existing = Customer.query.filter_by(
            customer_number=customer_number
        ).first()

        if not existing:
            return customer_number

@app.get("/waiver")
def waiver():
    current_event = Event.query.filter_by(
        is_current=True
    ).first()

    return render_template(
        "waiver.html",
        current_event=current_event
    )

@app.post("/api/waivers")
def create_waiver():
    current_event = Event.query.filter_by(
        is_current=True
    ).first()

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

    if request.method == "POST":
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD:
            error = "Admin password has not been configured."
        elif secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["admin_authenticated"] = True
            return redirect(url_for("admin_waivers"))
        else:
            error = "Incorrect password."

    return render_template("admin_login.html", error=error)


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.get("/admin/waivers")
@admin_required

def admin_waivers():
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

    expiring_soon_count = Waiver.query.filter(
        Waiver.status == "Expiring Soon",
        Waiver.is_archived.is_(False)
    ).count()

    expired_count = Waiver.query.filter(
        Waiver.status == "Expired",
        Waiver.is_archived.is_(False)
    ).count()



    current_event = Event.query.filter_by(
        is_current=True
    ).first()

    return render_template(
        "admin_waivers.html",
        waivers=waivers,
        valid_count=valid_count,
        expiring_soon_count=expiring_soon_count,
        expired_count=expired_count,
        current_event=current_event
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

@app.post("/admin/events/current/status")
def update_current_event_status():
    current_event = Event.query.filter_by(
        is_current=True
    ).first()

    if not current_event:
        return jsonify({
            "success": False,
            "error": "No current event found."
        }), 404

    data = request.get_json()

    new_status = data.get("status")

    allowed_statuses = [
        "Open",
        "Closing Soon",
        "Closed"
    ]

    if new_status not in allowed_statuses:
        return jsonify({
            "success": False,
            "error": "Invalid event status."
        }), 400

    current_event.status = new_status
    db.session.commit()

    return jsonify({
        "success": True,
        "status": current_event.status
    })

@app.get("/admin/waivers/<int:waiver_id>")
@admin_required
def admin_waiver_detail(waiver_id):
    waiver = Waiver.query.get_or_404(waiver_id)

    return render_template(
        "admin_waiver_detail.html",
        waiver=waiver
)

if __name__ == '__main__':
    app.run(debug=True)