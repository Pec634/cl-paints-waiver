"""Shared booking review and payment eligibility rules."""
from flask import current_app
from booking_on_behalf import pending_agreement

AWAITING_PAYMENT = 'Awaiting Payment'
NO_PAYMENT_REQUIRED = 'No payment required'
PAYMENT_PREFERENCES = ('Full payment', '50% deposit', NO_PAYMENT_REQUIRED)


def validate_payment_preference(preference, event_total):
    if preference not in PAYMENT_PREFERENCES:
        raise ValueError('Choose a payment preference.')
    if preference == NO_PAYMENT_REQUIRED and event_total > 0:
        raise ValueError('Choose a payment arrangement for bookings with an event charge.')


def payments_allowed(booking):
    if booking.status not in (AWAITING_PAYMENT, 'Accepted') or pending_agreement(booking):
        return False
    FollowUp = current_app.extensions.get('booking_followup_model')
    if FollowUp is not None:
        from sqlalchemy.orm import object_session
        session = object_session(booking)
        if session and session.get(FollowUp, booking.id):
            return False
    return True


def confirmation_ready(booking):
    payment = current_app.extensions['payment_summary'](booking)
    required = min(payment['deposit'], payment['total']) if payment['deposit'] > 0 else payment['total']
    return payment['paid'] >= required
