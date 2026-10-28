"""A current-day operational summary without exposing private records to clients."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import request
from booking_cashup import totals


def register(app, db, Booking, Handover, Cashup, schedule):
    @app.context_processor
    def context():
        if request.endpoint != 'admin_dashboard':
            return {}
        now = datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=None)
        today = now.date()
        handover = Handover.query.filter_by(handover_date=today).order_by(Handover.revision.desc()).first()
        latest_ids = db.session.query(db.func.max(Cashup.id)).group_by(Cashup.booking_id, Cashup.event_index, Cashup.event_date)
        cashups = {(row.booking_id, row.event_index, row.event_date): row for row in Cashup.query.filter(Cashup.id.in_(latest_ids)).all()}
        due = []; todays = []; issues = []
        for booking in Booking.query.filter_by(status='Accepted').all():
            for index, event in enumerate(schedule(booking)):
                try:
                    start = datetime.fromisoformat(event['date']+'T'+event['start_time'])
                    end = datetime.fromisoformat(event['date']+'T'+event['finish_time'])
                    if end <= start:
                        end += timedelta(days=1)
                except (KeyError, TypeError, ValueError):
                    continue
                row = cashups.get((booking.id, index, event['date']))
                item = dict(booking=booking, event=event, index=index, cashup=row)
                if start.date() == today:
                    todays.append(item)
                if end <= now and (not row or row.phase != 'Closed'):
                    due.append(item)
        # Keep unresolved financial issues visible even if a booking is later cancelled
        # or its event date changes. Every link identifies the saved event date.
        for row in cashups.values():
            if row.phase != 'Closed':
                continue
            result = totals(row.values)
            variance = bool(result['till_variance'] or result['safe_variance'])
            if result['share_remaining'] or (variance and not row.values.get('reviewed_at')):
                booking = db.session.get(Booking, row.booking_id)
                if booking:
                    issues.append(dict(booking=booking, cashup=row, totals=result, variance=variance))
        todays.sort(key=lambda item: item['event']['start_time'])
        due.sort(key=lambda item: (item['event']['date'], item['event']['start_time']))
        return dict(daily_ops=dict(today=today, handover=handover, bookings=todays,
            staff=handover.details.get('staff', []) if handover else [], cashups_due=due,
            cashup_issues=issues, awaiting_payment=Booking.query.filter_by(status='Awaiting Payment').count()))
