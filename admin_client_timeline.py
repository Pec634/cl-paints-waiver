"""A private, read-only timeline of records linked to a client."""
from math import ceil
from flask import render_template, request, url_for


def register(app, db, Account, Booking, Message, Enquiry, Invoice, Payment, Order, OrderMessage, admin_required):
    @app.get('/admin/clients/<int:client_id>/timeline')
    @admin_required
    def admin_client_timeline(client_id):
        account = db.get_or_404(Account, client_id)
        email = account.email.strip().casefold()
        booking_ids = Booking.query.filter(db.func.lower(db.func.trim(Booking.email)) == email).with_entities(Booking.id)
        orders = Order.query.filter(db.func.lower(db.func.trim(Order.email)) == email)
        entries = []

        def add(at, title, detail, link):
            entries.append(dict(at=at, title=title, detail=detail, link=link))

        add(account.created_at, 'Account created', account.account_number,
            url_for('admin_client_profile', client_id=account.id))
        for booking in Booking.query.filter(Booking.id.in_(booking_ids)).order_by(Booking.submitted_at.desc()).limit(100):
            add(booking.submitted_at, 'Booking requested', f'{booking.public_reference} · {booking.event_type} · Current status: {booking.status}',
                url_for('admin_booking_activity', booking_id=booking.id))
        for message in Message.query.filter(Message.booking_id.in_(booking_ids)).order_by(Message.created_at.desc()).limit(100):
            add(message.created_at, 'Client message' if message.sender == 'client' else 'Admin message', message.body,
                url_for('admin_booking_messages', booking_id=message.booking_id))
        for enquiry in Enquiry.query.filter_by(client_id=account.id).order_by(Enquiry.created_at.desc()).limit(100):
            add(enquiry.created_at, 'Enquiry received', enquiry.subject,
                url_for('communications_messages', view='enquiries', q=account.email))
        for invoice in Invoice.query.filter(Invoice.booking_id.in_(booking_ids)).order_by(Invoice.created_at.desc()).limit(100):
            add(invoice.created_at, 'Invoice created', f'{invoice.reference} · £{invoice.amount:.2f}',
                url_for('admin_booking_invoices', booking_id=invoice.booking_id))
        for payment in Payment.query.filter(Payment.booking_id.in_(booking_ids)).order_by(Payment.recorded_at.desc()).limit(100):
            add(payment.recorded_at, 'Payment ledger entry', f'{payment.kind} · £{payment.amount:.2f} · {payment.method}',
                url_for('admin_payments', booking_id=payment.booking_id))
        for order in orders.order_by(Order.created_at.desc()).limit(100):
            add(order.created_at, 'CL Creates order placed', f'{order.number} · £{order.total:.2f} · Current status: {order.status}',
                url_for('creates_order', order_id=order.id))
        for message in OrderMessage.query.filter(OrderMessage.order_id.in_(orders.with_entities(Order.id))).order_by(OrderMessage.created_at.desc()).limit(100):
            add(message.created_at, 'CL Creates email', f'{message.subject} · {message.result}',
                url_for('creates_order', order_id=message.order_id))
        entries.sort(key=lambda item: item['at'], reverse=True)
        pages = max(1, ceil(len(entries) / 25))
        page = min(pages, max(1, request.args.get('page', 1, type=int)))
        response = app.make_response(render_template('admin_client_timeline.html', account=account,
            entries=entries[(page-1)*25:page*25], page=page, pages=pages))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
