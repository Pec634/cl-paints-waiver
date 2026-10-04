"""Referral scheme reused from the standalone CL Paints referral app."""
import secrets
from datetime import datetime, date
from pathlib import Path
from flask import Blueprint, flash, redirect, render_template, request, url_for, send_file
from sqlalchemy import text

REWARD_TEXT = "30 minutes free face painting"
CODE_LENGTH = 5
DATE_FORMAT = "%Y-%m-%d"
DISPLAY_DATE_FORMAT = "%d/%m/%Y"
app = Blueprint("rewards", __name__, url_prefix="/admin/rewards")
engine = None


def admin_required(view):
    from functools import wraps
    from flask import session
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def init_db():
    index_sql = "CREATE INDEX IF NOT EXISTS idx_referrals_code ON referrals(code)"
    customer_index_sql = "CREATE INDEX IF NOT EXISTS idx_referrals_customer ON referrals(customer_name)"

    if engine.dialect.name == "postgresql":
        ddl = """
        CREATE TABLE IF NOT EXISTS referrals (
            id BIGSERIAL PRIMARY KEY,
            customer_name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            original_event_date TEXT NOT NULL,
            expires_date TEXT NOT NULL,
            friend_event_date TEXT,
            reward_earned_date TEXT,
            reward_redeemed_date TEXT,
            reward_text TEXT NOT NULL DEFAULT '30 minutes free face painting',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """

        with engine.begin() as conn:
            conn.execute(text(ddl))
            conn.execute(text("""
                ALTER TABLE referrals
                ADD COLUMN IF NOT EXISTS friend_event_date TEXT
            """))
            conn.execute(text("""
                ALTER TABLE referrals
                ADD COLUMN IF NOT EXISTS reward_earned_date TEXT
            """))
            conn.execute(text("""
                ALTER TABLE referrals
                ADD COLUMN IF NOT EXISTS reward_redeemed_date TEXT
            """))
            conn.execute(text("""
                ALTER TABLE referrals
                ADD COLUMN IF NOT EXISTS reward_text TEXT
                DEFAULT '30 minutes free face painting'
            """))
            conn.execute(text("""
                ALTER TABLE referrals
                ADD COLUMN IF NOT EXISTS status TEXT
                DEFAULT 'active'
            """))
            conn.execute(text(index_sql))
            conn.execute(text(customer_index_sql))
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            original_event_date TEXT NOT NULL,
            expires_date TEXT NOT NULL,
            friend_event_date TEXT,
            reward_earned_date TEXT,
            reward_redeemed_date TEXT,
            reward_text TEXT NOT NULL DEFAULT '30 minutes free face painting',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """

        with engine.begin() as conn:
            conn.execute(text(ddl))
            existing_columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(referrals)")).fetchall()
            }
            sqlite_migrations = {
                "friend_event_date": "ALTER TABLE referrals ADD COLUMN friend_event_date TEXT",
                "reward_earned_date": "ALTER TABLE referrals ADD COLUMN reward_earned_date TEXT",
                "reward_redeemed_date": "ALTER TABLE referrals ADD COLUMN reward_redeemed_date TEXT",
                "reward_text": (
                    "ALTER TABLE referrals ADD COLUMN reward_text TEXT "
                    "DEFAULT '30 minutes free face painting'"
                ),
                "status": "ALTER TABLE referrals ADD COLUMN status TEXT DEFAULT 'active'",
            }
            for column_name, migration_sql in sqlite_migrations.items():
                if column_name not in existing_columns:
                    conn.execute(text(migration_sql))
            conn.execute(text(index_sql))
            conn.execute(text(customer_index_sql))


def fetch_one(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        row = result.mappings().first()
        return dict(row) if row else None


def fetch_all(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(r) for r in result.mappings().all()]


def execute(sql, params=None):
    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount


def parse_date(value):
    return datetime.strptime(value, DATE_FORMAT).date()


def parse_display_date(value):
    return datetime.strptime(value.strip(), DISPLAY_DATE_FORMAT).date()


def display_date(value):
    if not value:
        return ""
    if isinstance(value, date):
        return value.strftime(DISPLAY_DATE_FORMAT)
    try:
        return parse_date(value).strftime(DISPLAY_DATE_FORMAT)
    except (ValueError, TypeError):
        return value


def add_12_months(start):
    try:
        return start.replace(year=start.year + 1)
    except ValueError:
        return start.replace(year=start.year + 1, day=28)


def generate_code():
    characters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        code = "".join(secrets.choice(characters) for _ in range(CODE_LENGTH))
        exists = fetch_one("SELECT 1 AS found FROM referrals WHERE code = :code", {"code": code})
        if not exists:
            return code


def current_status(row):
    if row["status"] == "earned":
        return "Reward Available"
    if row["status"] == "redeemed":
        return "Reward Redeemed"
    try:
        if date.today() > parse_date(row["expires_date"]):
            return "Expired"
    except ValueError:
        return "Date Error"
    return "Code Active"


def row_to_dict(row):
    item = dict(row)
    item["display_original_event_date"] = display_date(item["original_event_date"])
    item["display_expires_date"] = display_date(item["expires_date"])
    item["display_friend_event_date"] = display_date(item["friend_event_date"])
    item["display_reward_earned_date"] = display_date(item["reward_earned_date"])
    item["display_reward_redeemed_date"] = display_date(item["reward_redeemed_date"])
    item["display_status"] = current_status(row)
    return item



def split_legacy_label(part):
    if ": " not in part:
        return None, None
    label, value = part.split(": ", 1)
    return label.strip().lower(), value.strip()


def parse_legacy_record(line):
    """
    Parse records created by both the original CL Paints referral program
    and the later desktop GUI.

    Examples include:
      Name - CODE - Made: 2026-09-01 - Expires: 2027-09-01
      Name - CODE - Event Date: 2026-09-01 - Expires: 2027-09-01
      ... - Friend Event Date: ... - Reward Earned: ... - Reward: ...
      ... - Reward Redeemed: ...
    """
    parts = [part.strip() for part in line.strip().split(" - ")]
    if len(parts) < 2:
        return None

    record = {
        "customer_name": parts[0],
        "code": parts[1],
        "original_event_date": "",
        "expires_date": "",
        "friend_event_date": "",
        "reward_earned_date": "",
        "reward_redeemed_date": "",
        "reward_text": REWARD_TEXT,
    }

    for part in parts[2:]:
        label, value = split_legacy_label(part)
        if not label:
            continue

        if label in ("made", "event date"):
            record["original_event_date"] = value
        elif label in ("expires", "referral expires"):
            record["expires_date"] = value
        elif label == "friend event date":
            record["friend_event_date"] = value
        elif label == "reward earned":
            record["reward_earned_date"] = value
        elif label == "reward redeemed":
            record["reward_redeemed_date"] = value
        elif label == "reward" and value:
            record["reward_text"] = value

    return record


def normalise_legacy_date(value, required=False):
    """
    Convert legacy YYYY-MM-DD or DD/MM/YYYY dates into YYYY-MM-DD.
    Empty optional dates remain NULL.
    """
    value = (value or "").strip()
    if not value or value.lower() == "legacy record":
        if required:
            raise ValueError("required date is missing")
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().strftime(DATE_FORMAT)
        except ValueError:
            pass

    raise ValueError(f"unrecognised date: {value}")


def import_legacy_lines(text, source_status):
    """
    Import a legacy text-file payload into SQLite.

    Existing referral codes are skipped rather than overwritten.
    Returns a summary and row-level warnings for the import screen.
    """
    summary = {"imported": 0, "skipped": 0, "failed": 0}
    warnings = []

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line_number, line in enumerate(lines, start=1):
        record = parse_legacy_record(line)

        if not record or not record["customer_name"] or not record["code"]:
            summary["failed"] += 1
            warnings.append(f"Line {line_number}: could not read the customer name or referral code.")
            continue

        existing = fetch_one(
            "SELECT id FROM referrals WHERE code = :code",
            {"code": record["code"]},
        )

        if existing:
            summary["skipped"] += 1
            warnings.append(
                f"Line {line_number}: {record['code']} already exists, so it was not imported again."
            )
            continue

        try:
            original_event = normalise_legacy_date(
                record["original_event_date"], required=True
            )
            expires = normalise_legacy_date(
                record["expires_date"], required=True
            )
            friend_event = normalise_legacy_date(record["friend_event_date"])
            reward_earned = normalise_legacy_date(record["reward_earned_date"])
            reward_redeemed = normalise_legacy_date(record["reward_redeemed_date"])
        except ValueError as exc:
            summary["failed"] += 1
            warnings.append(
                f"Line {line_number}: {record['customer_name']} ({record['code']}) was not imported — {exc}."
            )
            continue

        status = source_status

        if reward_redeemed:
            status = "redeemed"
        elif reward_earned or friend_event:
            status = "earned"

        if source_status == "earned":
            status = "earned"
        elif source_status == "redeemed":
            status = "redeemed"

        execute(
            """
            INSERT INTO referrals
            (
                customer_name, code, original_event_date, expires_date,
                friend_event_date, reward_earned_date, reward_redeemed_date,
                reward_text, status
            )
            VALUES (
                :customer_name, :code, :original_event_date, :expires_date,
                :friend_event_date, :reward_earned_date, :reward_redeemed_date,
                :reward_text, :status
            )
            """,
            {
                "customer_name": record["customer_name"],
                "code": record["code"],
                "original_event_date": original_event,
                "expires_date": expires,
                "friend_event_date": friend_event,
                "reward_earned_date": reward_earned,
                "reward_redeemed_date": reward_redeemed,
                "reward_text": record["reward_text"] or REWARD_TEXT,
                "status": status,
            },
        )
        summary["imported"] += 1

    return summary, warnings



@app.context_processor
def inject_helpers():
    return {"reward_text": REWARD_TEXT}


@app.route("/")
@admin_required
def dashboard():
    section = request.args.get("section", "active")
    if section not in {"active", "earned", "redeemed", "all"}:
        section = "active"
    query = request.args.get("q", "").strip()

    sql = "SELECT * FROM referrals"

    if section == "earned":
        sql += " WHERE status = 'earned'"
    elif section == "redeemed":
        sql += " WHERE status = 'redeemed'"
    elif section == "active":
        sql += " WHERE status = 'active'"

    named_params = {}
    if query:
        sql += " WHERE" if section == "all" else " AND"
        sql += """
            (
                LOWER(customer_name) LIKE :q1
                OR LOWER(code) LIKE :q2
            )
        """
        named_params["q1"] = f"%{query.lower()}%"
        named_params["q2"] = f"%{query.lower()}%"

    sql += " ORDER BY LOWER(customer_name), original_event_date DESC"
    rows = fetch_all(sql, named_params)
    all_rows = fetch_all("SELECT * FROM referrals")

    records = [row_to_dict(r) for r in rows]
    booking_usage = {}
    for booking in fetch_all(
        "SELECT id, promo_code, first_name, last_name, submitted_at, status "
        "FROM booking WHERE promo_code IS NOT NULL ORDER BY submitted_at DESC"
    ):
        submitted = booking["submitted_at"]
        if isinstance(submitted, str):
            submitted = datetime.fromisoformat(submitted)
        booking["display_submitted_at"] = submitted.strftime("%d/%m/%Y %H:%M")
        booking_usage.setdefault(booking["promo_code"], []).append(booking)
    for record in records:
        record["booking_usage"] = booking_usage.get(record["code"], [])
    all_records = [row_to_dict(r) for r in all_rows]

    counts = {
        "active": sum(1 for r in all_records if r["status"] == "active" and r["display_status"] == "Code Active"),
        "expired": sum(1 for r in all_records if r["status"] == "active" and r["display_status"] == "Expired"),
        "earned": sum(1 for r in all_records if r["status"] == "earned"),
        "redeemed": sum(1 for r in all_records if r["status"] == "redeemed"),
        "total": len(all_records),
    }

    return render_template(
        "rewards/dashboard.html",
        section=section,
        query=query,
        records=records,
        counts=counts,
    )


@app.route("/referral/new", methods=["GET", "POST"])
@admin_required
def create_referral():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        surname = request.form.get("surname", "").strip()
        event_date_text = request.form.get("event_date", "").strip()

        if not first_name or not surname:
            flash("Please enter both first name and surname.", "error")
            return render_template("rewards/create_referral.html", event_date=event_date_text)

        try:
            original_event_date = parse_display_date(event_date_text)
        except ValueError:
            flash("Please enter the event date as DD/MM/YYYY.", "error")
            return render_template("rewards/create_referral.html", event_date=event_date_text)

        expires = add_12_months(original_event_date)
        code = generate_code()
        customer_name = f"{first_name} {surname}"

        execute(
            """
            INSERT INTO referrals
            (customer_name, code, original_event_date, expires_date, reward_text, status)
            VALUES (:customer_name, :code, :original_event_date, :expires_date, :reward_text, 'active')
            """,
            {
                "customer_name": customer_name,
                "code": code,
                "original_event_date": original_event_date.strftime(DATE_FORMAT),
                "expires_date": expires.strftime(DATE_FORMAT),
                "reward_text": REWARD_TEXT,
            },
        )

        flash(
            f"Referral {code} created for {customer_name}. "
            f"Valid until {display_date(expires)}.",
            "success",
        )
        return redirect(url_for("rewards.dashboard", section="active"))

    return render_template(
        "rewards/create_referral.html",
        event_date=date.today().strftime(DISPLAY_DATE_FORMAT),
    )


@app.route("/referral/<int:referral_id>/validate", methods=["GET", "POST"])
@admin_required
def validate_referral(referral_id):
    row = fetch_one(
        "SELECT * FROM referrals WHERE id = :id",
        {"id": referral_id},
    )

    if not row:
        flash("Referral not found.", "error")
        return redirect(url_for("rewards.dashboard"))

    record = row_to_dict(row)

    if record["status"] != "active":
        flash("This referral has already been processed.", "error")
        return redirect(url_for("rewards.dashboard"))

    if request.method == "POST":
        friend_event_text = request.form.get("friend_event_date", "").strip()

        try:
            friend_event = parse_display_date(friend_event_text)
            original_event = parse_date(record["original_event_date"])
            expires = parse_date(record["expires_date"])
        except ValueError:
            flash("Please enter the friend's attended event date as DD/MM/YYYY.", "error")
            return render_template(
                "rewards/validate_referral.html",
                record=record,
                friend_event_date=friend_event_text,
            )

        if friend_event < original_event:
            flash(
                "The referred friend's attended event cannot be before the "
                "original referral became valid.",
                "error",
            )
            return render_template(
                "rewards/validate_referral.html",
                record=record,
                friend_event_date=friend_event_text,
            )

        if friend_event > expires:
            flash(
                "The referred friend's booking was attended after the referral "
                "expired, so the reward cannot be earned.",
                "error",
            )
            return render_template(
                "rewards/validate_referral.html",
                record=record,
                friend_event_date=friend_event_text,
            )

        friend_storage = friend_event.strftime(DATE_FORMAT)

        execute(
            """
            UPDATE referrals
            SET friend_event_date = :friend_event_date,
                reward_earned_date = :reward_earned_date,
                status = 'earned'
            WHERE id = :id AND status = 'active'
            """,
            {
                "friend_event_date": friend_storage,
                "reward_earned_date": friend_storage,
                "id": referral_id,
            },
        )

        flash(
            f"{record['customer_name']} has earned {REWARD_TEXT}. "
            "The earned reward does not expire under the current scheme.",
            "success",
        )
        return redirect(url_for("rewards.dashboard", section="earned"))

    return render_template(
        "rewards/validate_referral.html",
        record=record,
        friend_event_date=date.today().strftime(DISPLAY_DATE_FORMAT),
    )


@app.route("/referral/<int:referral_id>/redeem", methods=["GET", "POST"])
@admin_required
def redeem_reward(referral_id):
    row = fetch_one(
        "SELECT * FROM referrals WHERE id = :id",
        {"id": referral_id},
    )

    if not row:
        flash("Reward not found.", "error")
        return redirect(url_for("rewards.dashboard", section="earned"))

    record = row_to_dict(row)

    if record["status"] != "earned":
        flash("This reward is not available to redeem.", "error")
        return redirect(url_for("rewards.dashboard", section="earned"))

    if request.method == "POST":
        redemption_text = request.form.get("redeemed_date", "").strip()

        try:
            redemption_date = parse_display_date(redemption_text)
        except ValueError:
            flash("Please enter the redemption date as DD/MM/YYYY.", "error")
            return render_template(
                "rewards/redeem_reward.html",
                record=record,
                redeemed_date=redemption_text,
            )

        earned_date = None
        if record["reward_earned_date"]:
            try:
                earned_date = parse_date(record["reward_earned_date"])
            except (ValueError, TypeError):
                earned_date = None

        if earned_date and redemption_date < earned_date:
            flash("The reward cannot be redeemed before it was earned.", "error")
            return render_template(
                "rewards/redeem_reward.html",
                record=record,
                redeemed_date=redemption_text,
            )

        execute(
            """
            UPDATE referrals
            SET reward_redeemed_date = :reward_redeemed_date,
                status = 'redeemed'
            WHERE id = :id AND status = 'earned'
            """,
            {
                "reward_redeemed_date": redemption_date.strftime(DATE_FORMAT),
                "id": referral_id,
            },
        )

        flash("Reward marked as redeemed.", "success")
        return redirect(url_for("rewards.dashboard", section="redeemed"))

    return render_template(
        "rewards/redeem_reward.html",
        record=record,
        redeemed_date=date.today().strftime(DISPLAY_DATE_FORMAT),
    )


@app.route("/referral/<int:referral_id>/delete", methods=["POST"])
@admin_required
def delete_referral(referral_id):
    row = fetch_one(
        "SELECT customer_name, code FROM referrals WHERE id = :id",
        {"id": referral_id},
    )

    if not row:
        flash("Record not found.", "error")
        return redirect(url_for("rewards.dashboard"))

    execute("DELETE FROM referrals WHERE id = :id", {"id": referral_id})

    flash(f"Removed referral {row['code']} for {row['customer_name']}.", "success")
    return redirect(url_for("rewards.dashboard"))



@app.route("/import", methods=["GET", "POST"])
@admin_required
def import_legacy_data():
    results = []
    warnings = []

    if request.method == "POST":
        uploads = [
            ("active_file", "active", "Active Referral Codes"),
            ("earned_file", "earned", "30-Minute Rewards Available"),
            ("redeemed_file", "redeemed", "Redeemed Rewards"),
        ]

        selected = False

        for field_name, source_status, label in uploads:
            uploaded = request.files.get(field_name)

            if not uploaded or not uploaded.filename:
                continue

            selected = True

            try:
                raw = uploaded.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    flash("Each import file must be under 2 MB.", "error")
                    continue
                payload = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                flash(
                    f"{uploaded.filename} could not be read as a normal text file.",
                    "error",
                )
                continue

            summary, file_warnings = import_legacy_lines(payload, source_status)
            results.append(
                {
                    "filename": uploaded.filename,
                    "label": label,
                    **summary,
                }
            )
            warnings.extend(file_warnings)

        if not selected:
            flash("Choose at least one legacy .txt file to import.", "error")
        elif results:
            imported_total = sum(item["imported"] for item in results)
            flash(
                f"Import finished. {imported_total} record(s) were added to the web app.",
                "success",
            )

    return render_template(
        "rewards/import.html",
        results=results,
        warnings=warnings[:50],
    )


@app.route("/backup/database")
@admin_required
def download_database_backup():
    if engine.dialect.name != "sqlite":
        flash("Use your database provider's backup tools for PostgreSQL backups.", "error")
        return redirect(url_for("rewards.import_legacy_data"))
    import sqlite3
    import tempfile
    from contextlib import closing
    from io import BytesIO
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "backup.db"
        with engine.connect() as connection:
            with closing(sqlite3.connect(target)) as backup:
                connection.connection.driver_connection.backup(backup)
        payload = BytesIO(target.read_bytes())
    return send_file(payload, as_attachment=True,
                     download_name=f"CL_Paints_Backup_{date.today().isoformat()}.db",
                     mimetype="application/octet-stream")

