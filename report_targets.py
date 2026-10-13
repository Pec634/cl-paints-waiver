"""Financial-year management targets using the records held by this app."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import json
import secrets
from dateutil.relativedelta import relativedelta
from flask import abort, flash, redirect, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError

METRICS = {
    'booking_count': ('Booking requests', False),
    'accepted_count': ('Accepted requests', False),
    'estimated_value': ('Estimated accepted booking value', True),
    'net_payments': ('Recorded payments less refunds', True),
    'unique_clients': ('Booking clients', False),
    'waiver_count': ('Waivers signed', False),
    'qr_scans': ('Tracked QR link opens', False),
}


def financial_year(day):
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def progress(actual, annual, elapsed, length):
    if annual is None:
        return dict(percent=None, expected=None, status='No target set')
    expected = annual * Decimal(elapsed) / Decimal(length)
    percent = float(actual / annual * 100) if annual else (100.0 if actual >= 0 else 0.0)
    return dict(percent=round(percent, 1), expected=expected,
                status='Target achieved' if actual >= annual else 'On track' if actual >= expected else 'Behind pace')


def register(app, db, Setting, Booking, Waiver, PaymentEntry, Scan, admin_required):
    def totals(start, end):
        lower = datetime.combine(start, datetime.min.time())
        upper = datetime.combine(end + timedelta(days=1), datetime.min.time())
        bookings = Booking.query.filter(Booking.submitted_at >= lower, Booking.submitted_at < upper).all()
        accepted = [b for b in bookings if b.status == 'Accepted']
        entries = PaymentEntry.query.filter(PaymentEntry.paid_date >= start, PaymentEntry.paid_date <= end).all()
        # Scan timestamps are UTC; financial-year boundaries are UK local dates.
        from datetime import timezone
        london = ZoneInfo('Europe/London')
        scan_lower = lower.replace(tzinfo=london).astimezone(timezone.utc).replace(tzinfo=None)
        scan_upper = upper.replace(tzinfo=london).astimezone(timezone.utc).replace(tzinfo=None)
        return {
            'booking_count': Decimal(len(bookings)),
            'accepted_count': Decimal(len(accepted)),
            'estimated_value': sum((Decimal(b.total_event_cost or 0) + Decimal(b.travel_charge or 0) for b in accepted), Decimal(0)),
            'net_payments': sum((Decimal(e.amount) * (1 if e.kind == 'payment' else -1) for e in entries), Decimal(0)),
            'unique_clients': Decimal(len({(b.email or '').strip().casefold() for b in bookings} - {''})),
            'waiver_count': Decimal(Waiver.query.filter(Waiver.signed_date >= lower, Waiver.signed_date < upper, Waiver.status != 'Superseded').count()),
            'qr_scans': Decimal(Scan.query.filter(Scan.scanned_at >= scan_lower, Scan.scanned_at < scan_upper).count()),
        }

    def data():
        today = datetime.now(ZoneInfo('Europe/London')).date()
        start = financial_year(today)
        finish = start + relativedelta(years=1) - timedelta(days=1)
        previous_start = start - relativedelta(years=1)
        previous_end = today - relativedelta(years=1)
        current, previous = totals(start, today), totals(previous_start, previous_end)
        history = []
        for offset in (1, 2, 3):
            begin = start - relativedelta(years=offset)
            end = begin + relativedelta(years=1) - timedelta(days=1)
            history.append(dict(label=f'{begin.year}/{str(end.year)[-2:]}', values=totals(begin, end)))
        row = db.session.get(Setting, f'report_targets_{start.year}')
        saved = json.loads(row.value) if row else {}
        elapsed, length = (today - start).days + 1, (finish - start).days + 1
        metrics = []
        for key, (label, money) in METRICS.items():
            target = Decimal(saved[key]) if key in saved else None
            change = round(float((current[key] - previous[key]) / previous[key] * 100), 1) if previous[key] > 0 else None
            metrics.append(dict(key=key, label=label, money=money, current=current[key], previous=previous[key],
                                change=change, target=target, history=[item['values'][key] for item in history],
                                **progress(current[key], target, elapsed, length)))
        return dict(today=today, start=start, finish=finish, previous_start=previous_start, previous_end=previous_end,
                    history=history, metrics=metrics, elapsed=elapsed, length=length,
                    csrf=session.setdefault('report_targets_csrf', secrets.token_urlsafe(32)))

    app.extensions['report_targets_data'] = data

    @app.post('/admin/reports/targets')
    @admin_required
    def save_report_targets():
        if not session.get('report_targets_csrf') or not secrets.compare_digest(
                session['report_targets_csrf'], request.form.get('csrf_token', '')):
            abort(400, 'Reload Reports before saving targets.')
        start = financial_year(datetime.now(ZoneInfo('Europe/London')).date())
        if request.form.get('year') != str(start.year):
            abort(400, 'The financial year has changed. Reload Reports before saving targets.')
        try:
            values = {}
            for key, (_, money) in METRICS.items():
                raw = request.form.get(key, '').strip()
                if not raw:
                    continue
                value = Decimal(raw)
                if not value.is_finite() or not 0 <= value <= Decimal('999999999'):
                    raise ValueError('Enter non-negative targets below one billion.')
                if value != value.quantize(Decimal('.01') if money else Decimal('1')):
                    raise ValueError('Use whole numbers for counts and up to two decimal places for money.')
                values[key] = str(value)
            key = f'report_targets_{start.year}'
            row = db.session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value='{}')
                db.session.add(row)
            row.value = json.dumps(values)
            db.session.commit()
            flash('Financial-year targets saved.', 'success')
        except (ValueError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else 'Enter valid target numbers.', 'error')
        except SQLAlchemyError:
            db.session.rollback()
            flash('Targets could not be saved. Please try again.', 'error')
        return redirect(url_for('admin_reports', view='targets') + '#report-targets')
