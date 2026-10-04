"""Aggregate management reports; location lookups send outward postcodes only."""
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from decimal import Decimal
from io import StringIO
import csv
import json
import re
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from flask import request, render_template, Response, redirect, url_for, flash
from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import SQLAlchemyError


def extract_outcode(address):
    text = (address or '').upper()
    match = re.search(r'\b([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}\b', text)
    if match:
        return match.group(1)
    match = re.fullmatch(r'\s*([A-Z]{1,2}\d[A-Z\d]?)\s*', text)
    return match.group(1) if match else None


def date_range(args):
    today = date.today()
    period = args.get('period', 'month')
    if period == 'custom':
        try:
            start = date.fromisoformat(args.get('start', ''))
            end = date.fromisoformat(args.get('end', ''))
        except ValueError:
            raise ValueError('Choose valid start and end dates.') from None
    elif period == 'quarter':
        start, end = today.replace(day=1) - relativedelta(months=2), today
    elif period == 'year':
        start, end = today.replace(month=1, day=1), today
    elif period == 'month':
        start, end = today.replace(day=1), today
    else:
        raise ValueError('Choose a supported reporting period.')
    if start > end:
        raise ValueError('The start date must be on or before the end date.')
    if end == date.max:
        raise ValueError('Choose an end date earlier than 31 December 9999.')
    if end.year - start.year > 10:
        raise ValueError('Choose a reporting period of 10 years or less.')
    return period, start, end


def month_keys(start, end):
    current = start.replace(day=1)
    keys = []
    while current <= end:
        keys.append(current.strftime('%Y-%m'))
        current += relativedelta(months=1)
    return keys


def chart_rows(counter, keys=None):
    items = [(key, counter.get(key, 0)) for key in keys] if keys is not None else counter.most_common()
    maximum = max((value for _, value in items), default=0)
    return [{'label': key, 'value': value, 'width': round(value / maximum * 100, 2) if maximum else 0} for key, value in items]


def lookup_outcode(outcode):
    # Never send names, street addresses, emails or full postcodes to the provider.
    with urlopen('https://api.postcodes.io/outcodes/' + outcode, timeout=5) as response:
        result = json.load(response).get('result')
    if not result or result.get('latitude') is None or result.get('longitude') is None:
        raise ValueError('No coordinates found')
    return {'latitude': float(result['latitude']), 'longitude': float(result['longitude']),
            'town': ', '.join(result.get('admin_district') or [])}


def register_reports(app, db, Booking, Waiver, Participant, Location, schedule_events, admin_required):
    def build_data(args):
        period, start, end = date_range(args)
        lower = datetime.combine(start, datetime.min.time())
        upper = datetime.combine(end + timedelta(days=1), datetime.min.time())
        setting = args.get('setting', 'all')
        if setting not in {'all', 'Public', 'Private'}:
            raise ValueError('Choose All, Public or Private events.')
        def matching_events(booking):
            return [event for event in schedule_events(booking)
                    if setting == 'all' or event.get('publicity_type', booking.publicity_type) == setting]
        bookings = Booking.query.filter(Booking.submitted_at >= lower, Booking.submitted_at < upper).order_by(Booking.submitted_at.desc()).all()
        setting_counts = Counter()
        for booking in bookings:
            settings = {event.get('publicity_type', booking.publicity_type) for event in schedule_events(booking)}
            label = 'Mixed public/private' if {'Public', 'Private'} <= settings else next(iter(settings), 'Unspecified')
            setting_counts[label] += 1
        bookings = [booking for booking in bookings if matching_events(booking)]
        waivers = Waiver.query.filter(Waiver.signed_date >= lower, Waiver.signed_date < upper, Waiver.status != 'Superseded').all()
        participants = Participant.query.join(Waiver).filter(Waiver.signed_date >= lower, Waiver.signed_date < upper, Waiver.status != 'Superseded').all()
        if setting == 'Private':
            waivers = []
            participants = []
        keys = month_keys(start, end)
        booking_trend = Counter(b.submitted_at.strftime('%Y-%m') for b in bookings)
        waiver_trend = Counter(w.signed_date.strftime('%Y-%m') for w in waivers)
        participant_trend = Counter(p.waiver.signed_date.strftime('%Y-%m') for p in participants)
        outcomes = Counter(b.status for b in bookings)
        event_types = Counter(str(matching_events(b)[0].get('event_type', b.event_type)).strip() or 'Unspecified' for b in bookings)
        ages = [p.age for p in participants if p.age is not None and 0 <= p.age <= 120]
        bands = Counter({'0–4': 0, '5–9': 0, '10–15': 0, '16–17': 0, '18+': 0})
        for age in ages:
            bands['0–4' if age < 5 else '5–9' if age < 10 else '10–15' if age < 16 else '16–17' if age < 18 else '18+'] += 1
        workload = Counter()
        for booking in Booking.query.filter_by(status='Accepted').all():
            for event in matching_events(booking):
                try:
                    day = date.fromisoformat(event['date'])
                    begin = datetime.strptime(event['start_time'], '%H:%M')
                    finish = datetime.strptime(event['finish_time'], '%H:%M')
                except (KeyError, TypeError, ValueError):
                    continue
                if start <= day <= end and finish > begin:
                    workload[day.strftime('%Y-%m')] += round((finish - begin).total_seconds() / 3600, 2)
        from rewards import fetch_all
        referrals = fetch_all('SELECT * FROM referrals')
        cohort = [r for r in referrals if start.isoformat() <= r['original_event_date'] <= end.isoformat()]
        code_bookings = Booking.query.filter(Booking.promo_code.isnot(None), Booking.submitted_at < upper).all()
        used = {b.promo_code for b in code_bookings}
        def by_end(value):
            return bool(value and str(value)[:10] <= end.isoformat())
        referral_flow = [
            {'label': 'Codes issued', 'value': len(cohort)},
            {'label': 'Used in bookings', 'value': sum(r['code'] in used for r in cohort)},
            {'label': 'Rewards earned', 'value': sum(by_end(r['reward_earned_date']) or by_end(r['friend_event_date']) for r in cohort)},
            {'label': 'Rewards redeemed', 'value': sum(by_end(r['reward_redeemed_date']) for r in cohort)},
        ]
        source = args.get('location', 'client')
        if source not in {'client', 'venue'}:
            source = 'client'
        groups = defaultdict(lambda: {'clients': set(), 'bookings': set(), 'accepted': set()})
        latest_clients = set()
        missing_bookings = set()
        for booking in bookings:
            identity = booking.email.strip().casefold()
            addresses = [booking.client_address] if source == 'client' else [e.get('event_address', '') for e in matching_events(booking)]
            codes = {extract_outcode(address) for address in addresses}
            if None in codes:
                missing_bookings.add(booking.id)
            codes.discard(None)
            for code in codes:
                group = groups[code]
                group['bookings'].add(booking.id)
                if booking.status == 'Accepted':
                    group['accepted'].add(booking.id)
                if source == 'venue' or identity not in latest_clients:
                    group['clients'].add(identity)
            latest_clients.add(identity)
        locations = {location.outcode: location for location in Location.query.all()}
        areas = []
        for code, values in groups.items():
            cached = locations.get(code)
            areas.append({'outcode': code, 'clients': len(values['clients']), 'bookings': len(values['bookings']),
                          'accepted': len(values['accepted']), 'town': cached.town if cached else '',
                          'latitude': cached.latitude if cached else None, 'longitude': cached.longitude if cached else None})
        areas.sort(key=lambda item: (-item['clients'], -item['bookings'], item['outcode']))
        estimated_value = sum((Decimal(b.total_event_cost or 0) + Decimal(b.travel_charge or 0) for b in bookings if b.status == 'Accepted'), Decimal(0))
        return dict(period=period, start=start, end=end, location_source=source, setting=setting,
                    setting_comparison=chart_rows(setting_counts),
                    booking_count=len(bookings), waiver_count=len(waivers), participant_count=len(participants),
                    average_age=round(sum(ages) / len(ages), 1) if ages else None,
                    age_sample=len(ages), estimated_value=f'{estimated_value:.2f}',
                    booking_trend=chart_rows(booking_trend, keys), waiver_trend=chart_rows(waiver_trend, keys),
                    participant_trend=chart_rows(participant_trend, keys), outcomes=chart_rows(outcomes),
                    event_types=chart_rows(event_types), ages=chart_rows(bands, list(bands)),
                    workload=chart_rows(workload, keys), referral_flow=referral_flow,
                    areas=areas, markers=[area for area in areas if area['latitude'] is not None],
                    missing_addresses=len(missing_bookings), unmapped_areas=sum(area['latitude'] is None for area in areas),
                    unique_clients=len(latest_clients))

    @app.get('/admin/reports')
    @admin_required
    def admin_reports():
        error = None
        try:
            data = build_data(request.args)
        except ValueError as problem:
            error = str(problem)
            data = build_data({})
        return render_template('admin_reports.html', **data, error=error)

    @app.get('/admin/reports/export')
    @admin_required
    def export_reports():
        try:
            data = build_data(request.args)
        except ValueError as problem:
            return Response(str(problem), status=400, mimetype='text/plain')
        output = StringIO()
        writer = csv.writer(output)
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        writer.writerow(['Report', 'Category', 'Value', 'Start date', 'End date'])
        def row(report, label, value):
            writer.writerow([safe(report), safe(label), safe(value), data['start'], data['end']])
        for field in ['booking_count', 'waiver_count', 'participant_count', 'average_age', 'estimated_value', 'unique_clients', 'missing_addresses']:
            if data['setting'] == 'Private' and field in {'waiver_count', 'participant_count', 'average_age'}:
                continue
            row('Summary', field, data[field] if data[field] is not None else '')
        row('Filters', 'Event setting', data['setting'])
        for field in ['booking_trend', 'waiver_trend', 'participant_trend', 'outcomes', 'event_types', 'ages', 'workload', 'referral_flow', 'setting_comparison']:
            if data['setting'] == 'Private' and field in {'waiver_trend', 'participant_trend', 'ages'}:
                continue
            for item in data[field]:
                row(field, item['label'], item['value'])
        for area in data['areas']:
            for field in ['clients', 'bookings', 'accepted']:
                row('Locations (' + data['location_source'] + ')', area['outcode'] + ' ' + field, area[field])
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="CL_Paints_Reports_{data["start"]}_{data["end"]}.csv"'})

    @app.post('/admin/reports/locations/refresh')
    @admin_required
    def refresh_report_locations():
        try:
            data = build_data(request.form)
        except ValueError as problem:
            flash(str(problem), 'error')
            return redirect(url_for('admin_reports'))
        pending = [area for area in data['areas'] if area['latitude'] is None][:10]
        saved = failed = 0
        for area in pending:
            try:
                found = lookup_outcode(area['outcode'])
                cached = db.session.get(Location, area['outcode'])
                if cached is None:
                    cached = Location(outcode=area['outcode'])
                    db.session.add(cached)
                for field, value in found.items():
                    setattr(cached, field, value)
                cached.updated_at = datetime.now()
                db.session.commit()
                saved += 1
            except (URLError, HTTPError, ValueError, TypeError, KeyError, OSError, SQLAlchemyError):
                db.session.rollback()
                failed += 1
        flash(f'Mapped {saved} postcode districts. {failed} could not be located. Each refresh handles up to 10 new districts.', 'error' if failed else 'success')
        return redirect(url_for('admin_reports', period=data['period'], start=data['start'].isoformat(), end=data['end'].isoformat(), location=data['location_source'], setting=data['setting']))
