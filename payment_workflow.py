"""Shared booking review and payment eligibility rules."""
from flask import current_app
from booking_on_behalf import pending_agreement

AWAITING_PAYMENT = 'Awaiting Payment'


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
