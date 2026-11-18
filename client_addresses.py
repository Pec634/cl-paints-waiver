"""Structured billing addresses, keeping the existing printable address snapshot."""
FIELDS = [('address_property', 'House / flat / suite name or number', 'address-line1', 150),
          ('address_street', 'Street name', 'address-line2', 150),
          ('address_city', 'City / town', 'address-level2', 100),
          ('address_postcode', 'Postcode', 'postal-code', 20),
          ('address_country', 'Country', 'country-name', 100)]


def define_model(db):
    class ClientBillingAddress(db.Model):
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), primary_key=True)
        details = db.Column(db.JSON, nullable=False)
    return ClientBillingAddress


def read_address(form):
    if not any(key in form for key, _, _, _ in FIELDS):
        raise ValueError('This form is missing the separate billing-address fields. Reload the page, then complete house/flat/suite, street, city, postcode and country.')
    # Browser autofill can supply line breaks or tabs in an address component.
    # Store printable single-line components rather than treating those as missing.
    values = {key: ' '.join(form.get(key, '').split()) for key, _, _, _ in FIELDS}
    for key, label, _, limit in FIELDS:
        if not values[key]:
            raise ValueError(f'No {label.lower()} was received. Enter it in the billing-address field and submit again.')
        if len(values[key]) > limit:
            raise ValueError(f'{label} is too long. Use up to {limit} characters.')
        if any(ord(c) < 32 for c in values[key]):
            raise ValueError(f'{label} contains an unsupported character. Please retype this field.')
    return values


def format_address(values):
    return '\n'.join(values[key] for key, _, _, _ in FIELDS)


def booking_prefill(account, billing, latest_booking=None, previous_bookings=None):
    """Prefer the account profile, with older booking details as a fallback."""
    import json
    values = {}
    bookings = list(previous_bookings) if previous_bookings is not None else ([latest_booking] if latest_booking else [])
    for source in bookings:
        for key in ('client_type', 'title', 'job_title', 'date_of_birth', 'ethnicity',
                    'ethnicity_detail', 'religion', 'phone'):
            value = getattr(source, key)
            if not values.get(key) and value:
                values[key] = value.isoformat() if hasattr(value, 'isoformat') else value
    if billing:
        values.update({key: value for key, value in billing.details.items() if value is not None and str(value).strip()})
    values.update(first_name=account.first_name, last_name=account.last_name, email=account.email)
    values['phone'] = account.phone or values.get('phone', '')
    address = account.address or next((source.client_address for source in bookings if source.client_address), '')
    values['client_address'] = address
    if not billing or not all(billing.details.get(key) for key, *_ in FIELDS):
        lines = address.splitlines()
        if len(lines) == len(FIELDS):
            values.update(zip((key for key, *_ in FIELDS), lines))
        else:
            for source in bookings:
                if address != source.client_address:
                    continue
                try:
                    saved = json.loads(source.event_schedule or '{}')
                    structured = saved.get('billing_address', {})
                    if all(structured.get(key) for key, *_ in FIELDS):
                        values.update(structured)
                        break
                except (ValueError, TypeError, AttributeError):
                    pass
    if values.get('date_of_birth'):
        values['is_over_18'] = 'yes'
    return values


def profile_details(form, ethnicities):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    values = {key: form.get(key, '').strip() for key in
              ['client_type', 'title', 'job_title', 'date_of_birth', 'ethnicity', 'ethnicity_detail', 'religion']}
    if 'business_name' in form:
        values['business_name'] = form.get('business_name', '').strip()
        if len(values['business_name']) > 200:
            raise ValueError('Enter a business name of 200 characters or fewer.')
    if values['client_type'] not in ('individual', 'business'):
        raise ValueError('Choose your client type.')
    if values['title'] not in ('', 'Mr', 'Mrs', 'Miss', 'Ms', 'Mx', 'Dr', 'Other'):
        raise ValueError('Choose a valid title.')
    if len(values['job_title']) > 120 or (values['client_type'] == 'business' and not values['job_title']):
        raise ValueError('Enter your job title for a business profile (up to 120 characters).')
    from booking_birth_dates import birth_date
    born = birth_date(values['date_of_birth'], values['client_type'])
    values['date_of_birth'] = born.isoformat() if born else ''
    today = datetime.now(ZoneInfo('Europe/London')).date()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day)) if born else None
    if age is not None and (age < 18 or age > 120):
        raise ValueError('The responsible client must be aged 18 or over; check your date of birth.')
    if values['ethnicity'] == 'Prefer not to say':
        values['ethnicity_detail'] = 'Prefer not to say'
    elif values['ethnicity'] not in ethnicities or values['ethnicity_detail'] not in ethnicities[values['ethnicity']]:
        raise ValueError('Choose a matching ethnic group and background, or Prefer not to say.')
    if values['religion'] not in ('Christian', 'Muslim', 'Hindu', 'Sikh', 'Buddhist', 'Jewish', 'Other', 'No Religion', 'Prefer not to say'):
        raise ValueError('Choose a religion response, or Prefer not to say.')
    return values
