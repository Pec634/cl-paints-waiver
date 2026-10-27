"""Explicit admin deletion of unconfirmed booking requests."""
import json
import secrets
from flask import abort, redirect, request, session, url_for
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

DELETABLE = ('Under Review', 'Awaiting Payment', 'Declined', 'Cancelled')
PROTECTED = {
    'booking_financial_correction': 'This request has historical financial corrections.',
    'payment_entry': 'This request has payment or refund records.',
    'sumup_checkout': 'This request has a SumUp checkout that must be retained.',
    'booking_invoice': 'This request has an attached SumUp invoice that must be retained.',
    'booking_cashup': 'This request has cash-up records.',
    'event': 'This request has linked event records.',
    'connecteam_shift_link': 'This request has linked staff shifts.',
    'booking_follow_up': 'This request has event completion or feedback history.',
}
REQUEST_TABLES = {'booking_activity', 'booking_change', 'booking_date_proposal',
    'booking_message', 'booking_request', 'payment_plan', 'booking_design_media',
    'invoice_document', 'form_booking_record', 'form_field_file'}


def register(app, db, Booking, admin_required):
    def blocker(booking):
        if booking.status not in DELETABLE:
            return 'Confirmed bookings cannot be deleted.'
        for name, reason in PROTECTED.items():
            table = db.metadata.tables[name]
            if db.session.execute(select(table.c.booking_id).where(table.c.booking_id == booking.id).limit(1)).first():
                return reason
        changes = db.metadata.tables['booking_change']
        for raw in db.session.scalars(select(changes.c.changes_json).where(changes.c.booking_id == booking.id)):
            try:
                status = json.loads(raw).get('Status', {})
                if status.get('before') == 'Accepted' or status.get('after') == 'Accepted':
                    return 'This booking was previously confirmed. Keep its history.'
            except (ValueError, AttributeError):
                return 'This request has history that could not be checked for previous confirmation.'
        return None

    @app.context_processor
    def context():
        if request.endpoint != 'admin_bookings' or not session.get('admin_authenticated'):
            return {}
        return dict(booking_deletion_blocker=blocker, booking_deletable_statuses=DELETABLE,
                    booking_delete_csrf=session.setdefault('client_csrf', secrets.token_urlsafe(32)))

    @app.post('/admin/bookings/<int:booking_id>/delete')
    @admin_required
    def admin_delete_booking(booking_id):
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        if request.form.get('confirm_delete') != 'yes':
            abort(400, 'Confirm that you want to permanently delete this booking request.')
        booking = Booking.query.filter_by(id=booking_id).with_for_update().first_or_404()
        reason = blocker(booking)
        if reason:
            return redirect(url_for('admin_bookings', deletion_error=reason))
        reference = booking.public_reference
        try:
            # Keep import receipts/batches for duplicate detection without a broken FK.
            receipts = db.metadata.tables['record_import_receipt']
            db.session.execute(receipts.update().where(receipts.c.booking_id == booking.id).values(booking_id=None))
            # Reverse dependency order removes audit links before their change records.
            for table in reversed(db.metadata.sorted_tables):
                if table.name in REQUEST_TABLES:
                    db.session.execute(table.delete().where(table.c.booking_id == booking.id))
            notices = db.metadata.tables['client_notification']
            db.session.execute(notices.delete().where(notices.c.kind == 'booking',
                notices.c.reference == reference,
                db.func.lower(db.func.trim(notices.c.email)) == booking.email.strip().casefold()))
            db.session.delete(booking)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception('Booking request %s could not be deleted.', booking_id)
            return redirect(url_for('admin_bookings', deletion_error='The request has linked records and could not be deleted. Nothing was removed.'))
        return redirect(url_for('admin_bookings', deleted=reference))
