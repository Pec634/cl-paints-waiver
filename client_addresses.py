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
    values = {key: form.get(key, '').strip() for key, _, _, _ in FIELDS}
    for key, label, _, limit in FIELDS:
        if not values[key] or len(values[key]) > limit or any(ord(c) < 32 for c in values[key]):
            raise ValueError(f'Complete {label.lower()} (up to {limit} characters).')
    return values


def format_address(values):
    return '\n'.join(values[key] for key, _, _, _ in FIELDS)
