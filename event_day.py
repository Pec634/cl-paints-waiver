"""Event-day shortcuts and operational counts, without awarding attendance."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from flask import abort, render_template, request
from connecteam_rota import api


def register(app, db, Event, Booking, Waiver, Setting, loyalty_models, schedule, admin_required):
    Code, _, Visit, _, _ = loyalty_models

    @app.get('/admin/event-day')
    @admin_required
    def event_day_dashboard():
        today = datetime.now(ZoneInfo('Europe/London')).date()
        try:
            selected = date.fromisoformat(request.args.get('date', today.isoformat()))
        except ValueError:
            abort(400)
        rows = []
        booking_rows = []
        day_bookings = {}
        for booking in Booking.query.filter_by(status='Accepted').all():
            for index, event in enumerate(schedule(booking)):
                if event.get('date') == selected.isoformat():
                    day_bookings[(booking.id, index + 1)] = (booking, event)
                    booking_rows.append(dict(booking=booking, event=event))
        corrections = app.extensions['loyalty_correction_model']
        for event in Event.query.filter_by(event_date=selected).order_by(Event.name).all():
            if event.booking_id and (event.booking_id, event.booking_day_number) not in day_bookings:
                continue
            public = app.extensions['kiosk_public_event'](event)
            visits = Visit.query.filter_by(event_id=event.id).outerjoin(corrections, corrections.visit_id == Visit.id).filter(corrections.visit_id.is_(None)).all() if public else []
            linked = day_bookings.get((event.booking_id, event.booking_day_number))
            rows.append(dict(event=event, public=public, open=public and event.status in ('Open', 'Closing Soon'),
                             code=db.session.get(Code, event.id) if public else None,
                             points=sum(v.status == 'point' for v in visits), free=sum(v.status == 'free' for v in visits),
                             waivers=Waiver.query.filter_by(event_name=event.name, event_date=selected).count() if public else 0,
                             booking=linked[0] if linked else None, details=linked[1] if linked else {}))
        shifts = []; rota_error = None
        rota_loaded = request.args.get('rota') == '1'
        if rota_loaded:
            setting = db.session.get(Setting, 'connecteam_scheduler_id')
            if not setting or not setting.value.isdigit():
                rota_error = 'Choose your schedule in Staff rota first.'
            else:
                start = datetime.combine(selected, time.min, ZoneInfo('Europe/London'))
                query = urlencode(dict(startTime=int(start.timestamp()), endTime=int((start + timedelta(days=1)).timestamp()), limit=100))
                try:
                    shifts = api(f'/scheduler/v1/schedulers/{int(setting.value)}/shifts?{query}').get('shifts', [])
                    for shift in shifts:
                        shift['start'] = datetime.fromtimestamp(shift['startTime'], ZoneInfo('Europe/London')).strftime('%H:%M')
                        shift['finish'] = datetime.fromtimestamp(shift['endTime'], ZoneInfo('Europe/London')).strftime('%H:%M')
                except (ValueError, TypeError, KeyError, OverflowError):
                    rota_error = 'Staff rota could not be loaded. Open Staff rota to check the connection.'
        return render_template('admin_event_day.html', selected=selected, today=today, rows=rows, bookings=booking_rows,
                               shifts=shifts, rota_error=rota_error, rota_loaded=rota_loaded)
