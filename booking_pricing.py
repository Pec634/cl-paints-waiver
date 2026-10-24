"""One server-side calculation for review-stage price previews and saves."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from booking_import import normalize_time


def money(value, label):
    try:
        amount = Decimal(str(value or '0').replace('£', '').replace(',', ''))
        if not amount.is_finite() or amount < 0 or amount > Decimal('99999999.99'):
            raise ValueError()
        return amount.quantize(Decimal('.01'))
    except (ValueError, InvalidOperation):
        raise ValueError(f'Enter a valid non-negative {label}.')


def pricing_key(day):
    return tuple(str(day.get(field, '')).strip().lower() for field in
        ('start_time', 'finish_time', 'charge_type', 'pitch_fee_required', 'pitch_fee_amount', 'travel_miles'))


def calculate(booking, raw_events, original_events, data, settings, payment_preference, paid=0):
    from business_settings import DEFAULTS
    rules = dict(DEFAULTS, **settings)
    rules.update(data.get('pricing_rules', {}))
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= 10:
        raise ValueError('Keep between one and ten event days.')
    intake = deepcopy(data.get('intake_options', {}))
    events, notes = [], []
    mileage_known = any(day.get('travel_miles') not in (None, '') for day in raw_events) or any(day.get('travel_miles') not in (None, '') for day in original_events)
    changed = len(raw_events) != len(original_events)
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            raise ValueError('Invalid event details.')
        original_index = raw.get('_original_index')
        old = original_events[original_index] if type(original_index) is int and 0 <= original_index < len(original_events) else {}
        day = dict(old, **raw)
        day['start_time'] = normalize_time(raw.get('start_time', ''))
        day['finish_time'] = normalize_time(raw.get('finish_time', ''))
        start = datetime.strptime(day['start_time'], '%H:%M')
        end = datetime.strptime(day['finish_time'], '%H:%M')
        if end <= start:
            raise ValueError(f'Event day {index + 1}: finish time must be later than start time.')
        hours = Decimal(str((end - start).total_seconds())) / Decimal(3600)
        day['duration_hours'] = str(hours)
        pitch = str(day.get('pitch_fee_required', False)).strip().lower()
        if pitch not in ('yes', 'no', 'true', 'false', '1', '0', ''):
            raise ValueError(f'Event day {index + 1}: choose Yes or No for pitch fees.')
        day['pitch_fee_required'] = pitch in ('yes', 'true', '1')
        charge = str(day.get('charge_type') or 'Client').strip()
        charge = next((option for option in ('Client', 'Customers', 'Revenue sharing') if option.lower() == charge.lower()), None)
        if charge is None:
            raise ValueError(f'Event day {index + 1}: choose Client, Customers or Revenue sharing as the charge type.')
        day['charge_type'] = charge
        day['pitch_fee_amount'] = str(money(day.get('pitch_fee_amount'), 'pitch fee')) if day['pitch_fee_required'] else None
        day['travel_miles'] = str(money(day.get('travel_miles'), 'travel mileage'))
        if Decimal(day['travel_miles']) > 10000:
            raise ValueError(f'Event day {index + 1}: travel mileage must not exceed 10,000 miles.')
        # Compare normalized pricing inputs, not presentation formats.
        old_pitch = str(old.get('pitch_fee_required', False)).strip().lower() in ('yes','true','1')
        baseline = dict(old, pitch_fee_required=old_pitch,
            pitch_fee_amount=str(money(old.get('pitch_fee_amount'), 'pitch fee')) if old_pitch else None,
            travel_miles=str(money(old.get('travel_miles'), 'travel mileage')),
            charge_type=old.get('charge_type') or 'Client')
        if not old or pricing_key(day) != pricing_key(baseline):
            changed = True
        if day.get('event_address', '') != old.get('event_address', ''):
            notes.append(f'Day {index + 1}: venue changed; check the one-way travel miles.')
        events.append(day)
    # Calculate on every preview/save: an unchanged imported Client-pays row
    # may still contain a stale zero estimate.
    for index, day in enumerate(events, 1):
        if Decimal(day['duration_hours']) < Decimal(rules['minimum_hours']):
            raise ValueError(f'Event day {index}: minimum booking duration is {rules["minimum_hours"]} hours.')
        day['estimated_cost'] = str((Decimal(day['duration_hours']) * Decimal(rules['hourly_rate'])).quantize(Decimal('.01'))
            if day['charge_type'] == 'Client' and not day['pitch_fee_required'] else Decimal('0.00'))
    package = intake.get('package')
    if package:
        compatible = all(day['charge_type'] == 'Client' and not day['pitch_fee_required'] and Decimal(day['duration_hours']) == Decimal(package['hours']) for day in events)
        if compatible:
            for day in events:
                day['estimated_cost'] = str(money(package['price'], 'package price'))
        else:
            intake['package'] = None
            notes.append('The package no longer matches these event details. Standard hourly pricing now applies.')
    extras = intake.get('extras') or []
    if extras and any(day['charge_type'] != 'Client' or day['pitch_fee_required'] for day in events):
        extras = []; intake['extras'] = []
        notes.append('Priced extras no longer apply because an event is not Client pays without a pitch fee.')
    extras_total = sum((money(extra['price'], 'extra price') for extra in extras), Decimal(0))
    intake['extras_total'] = str(extras_total)
    event_total = sum((Decimal(day['estimated_cost']) for day in events), Decimal(0)) + extras_total
    remaining = Decimal(rules['travel_cap']); travel = Decimal(0)
    for day in events:
        charge = min(max(Decimal(0), Decimal(day['travel_miles']) - Decimal(rules['free_miles'])) * Decimal(rules['mile_rate']), remaining)
        charge = charge.quantize(Decimal('.01'))
        day['travel_charge'] = str(charge); travel += charge; remaining -= charge
    if not mileage_known:
        travel = Decimal(booking.travel_charge)
        for index, day in enumerate(events):
            day['travel_charge'] = str(travel if index == 0 else Decimal(0))
        if travel:
            notes.append('Existing travel charge retained. Enter one-way mileage to recalculate travel.')
    changed = changed or event_total != Decimal(booking.total_event_cost) or travel != Decimal(booking.travel_charge)
    total = event_total + travel
    if not mileage_known:
        for day in events:
            day['travel_miles'] = ''
    if total > Decimal('99999999.99'):
        raise ValueError('The booking total is too large.')
    quote = dict(event_total=f'{event_total:.2f}', travel=f'{travel:.2f}', total=f'{total:.2f}',
        extras=f'{extras_total:.2f}', pitch_cost=f'{sum((money(day.get("pitch_fee_amount"), "pitch fee") for day in events), Decimal(0)):.2f}',
        deposit=f'{(total / 2).quantize(Decimal(".01")):.2f}' if payment_preference == '50% deposit' else None,
        outstanding=f'{max(Decimal(0), total - Decimal(paid)):.2f}', rate=str(rules['hourly_rate']),
        notes=notes, recalculated=changed,
        days=[dict(hours=day['duration_hours'], cost=day['estimated_cost'], travel=day['travel_charge']) for day in events])
    return events, intake, rules, quote
