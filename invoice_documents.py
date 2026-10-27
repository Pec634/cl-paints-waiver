"""Private invoice attachments shared with the booking's client."""
from datetime import datetime
from io import BytesIO
import json
import secrets
from flask import abort, flash, redirect, request, send_file, session, url_for
from werkzeug.utils import secure_filename


def define_model(db):
    class InvoiceDocument(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
        filename = db.Column(db.String(150), nullable=False)
        mime = db.Column(db.String(50), nullable=False)
        content = db.deferred(db.Column(db.LargeBinary, nullable=False))
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return InvoiceDocument


def register(app, db, Document, Invoice, Booking, Account, admin_required, current_client):
    @app.context_processor
    def context():
        def detail_row(booking):
            events = app.extensions['booking_schedule'](booking)
            try:
                saved = json.loads(booking.event_schedule or '{}')
            except (ValueError, TypeError):
                saved = {}
            return dict(events=events, same_details=saved.get('same_details', False) if isinstance(saved, dict) else False,
                        total_hours=sum(float(event.get('duration_hours', 0)) for event in events),
                        final_total=booking.total_event_cost + booking.travel_charge)
        return dict(invoice_documents=lambda booking: Document.query.filter_by(booking_id=booking.id).order_by(Document.created_at.desc()).all(),
                    admin_booking_detail_row=detail_row,
                    invoice_links=lambda booking: Invoice.query.filter_by(booking_id=booking.id).order_by(Invoice.created_at.desc()).all())

    @app.post('/admin/clients/<int:client_id>/invoice-documents')
    @admin_required
    def upload_invoice_document(client_id):
        account = db.get_or_404(Account, client_id)
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        booking = db.get_or_404(Booking, request.form.get('booking_id', type=int))
        if booking.email.strip().casefold() != account.email.strip().casefold():
            abort(403)
        upload = request.files.get('invoice_document')
        try:
            if not upload or not upload.filename:
                raise ValueError()
            content = upload.stream.read(10_000_001)
            if not content or len(content) > 10_000_000:
                raise ValueError()
            if content.startswith(b'%PDF-'): mime, ext = 'application/pdf', 'pdf'
            elif content.startswith(b'\x89PNG\r\n\x1a\n'): mime, ext = 'image/png', 'png'
            elif content.startswith(b'\xff\xd8\xff'): mime, ext = 'image/jpeg', 'jpg'
            elif content[:4] == b'RIFF' and content[8:12] == b'WEBP': mime, ext = 'image/webp', 'webp'
            else: raise ValueError()
            filename = (secure_filename(upload.filename).rsplit('.', 1)[0][:135] or 'invoice') + '.' + ext
            db.session.add(Document(booking_id=booking.id, filename=filename, mime=mime, content=content))
            db.session.commit()
            flash('Invoice uploaded and available in the client portal.', 'success')
        except ValueError:
            flash('Choose a PDF, JPG, PNG or WebP invoice up to 10 MB.', 'error')
        return redirect(url_for('admin_client_profile', client_id=client_id, tab='payments'))

    @app.get('/invoice-documents/<int:document_id>')
    def invoice_document(document_id):
        document = db.get_or_404(Document, document_id)
        booking = db.get_or_404(Booking, document.booking_id)
        def download():
            response = send_file(BytesIO(document.content), mimetype=document.mime, download_name=document.filename, as_attachment=True)
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        if session.get('admin_authenticated'):
            return admin_required(download)()
        account = current_client()
        if not account or booking.email.strip().casefold() != account.email.strip().casefold():
            abort(404)
        return download()
