"""Staff till, consent lookup and independently verified reader payments."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import secrets
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, session, url_for, jsonify
from sqlalchemy import or_, inspect
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError


def format_sale_time(value):
    if value is None:
        return 'Not recorded'
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M:%S %Z')


def define_model(db):
    class PosSale(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        reference = db.Column(db.String(64), nullable=False, unique=True)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        items_json = db.Column(db.Text, nullable=False)
        amount = db.Column(db.Numeric(10, 2), nullable=False)
        waiver_id = db.Column(db.Integer, db.ForeignKey('waiver.id'), nullable=True)
        method = db.Column(db.String(12), nullable=False)
        status = db.Column(db.String(32), nullable=False)
        merchant = db.Column(db.String(100), nullable=False, default='')
        transaction_code = db.Column(db.String(100), unique=True, nullable=True)
        paid_at = db.Column(db.DateTime, nullable=True)
        cash_tender = db.Column(db.Numeric(10, 2), nullable=True)
        participant_id = db.Column(db.Integer, db.ForeignKey('participant.id', ondelete='SET NULL'), nullable=True)
        participant_name = db.Column(db.String(255), nullable=True)
        customer_label = db.Column(db.Text, nullable=True)
        customer_search = db.Column(db.Text, nullable=True)
        receipt_email = db.Column(db.String(320), nullable=True)
        receipt_status = db.Column(db.String(20), nullable=True)
        receipt_sent_at = db.Column(db.DateTime, nullable=True)
        loyalty_event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
        loyalty_participants_json = db.Column(db.Text, nullable=True)
        loyalty_result_json = db.Column(db.Text, nullable=True)
        trading_event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
        event_index = db.Column(db.Integer, nullable=True)
        refund_version = db.Column(db.Integer, nullable=False, default=0)
        staff_id = db.Column(db.Integer, db.ForeignKey('pos_staff.id'), nullable=True)
        staff_name = db.Column(db.String(255), nullable=True)
        price_override = db.Column(db.Boolean, nullable=False, default=False)
        refunds = db.relationship('PosRefund', lazy='select', order_by='PosRefund.id')

        @property
        def refunded_total(self):
            return sum((row.amount for row in self.refunds if row.status=='Refunded'), Decimal('0.00'))

        @property
        def loyalty_results(self):
            return json.loads(self.loyalty_result_json or '[]')

        @property
        def change_due(self):
            return self.cash_tender - self.amount if self.cash_tender is not None else None
    return PosSale


def ensure_schema(db):
    sale_columns = inspect(db.engine).get_columns('pos_sale')
    columns = {column['name'] for column in sale_columns}
    status_column = next(column for column in sale_columns if column['name']=='status')
    status_length = getattr(status_column['type'],'length',None)
    if db.engine.dialect.name=='postgresql' and status_length is not None and status_length<32:
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE pos_sale ALTER COLUMN status TYPE VARCHAR(32)')
    additions = {'cash_tender': 'NUMERIC(10, 2)',
        'participant_id': 'INTEGER REFERENCES participant(id) ON DELETE SET NULL',
        'participant_name': 'VARCHAR(255)', 'customer_label': 'TEXT', 'customer_search': 'TEXT',
        'receipt_email': 'VARCHAR(320)', 'receipt_status': 'VARCHAR(20)', 'receipt_sent_at': 'TIMESTAMP',
        'loyalty_event_id':'INTEGER REFERENCES event(id)', 'loyalty_participants_json':'TEXT', 'loyalty_result_json':'TEXT',
        'trading_event_id':'INTEGER REFERENCES event(id)', 'booking_id':'INTEGER REFERENCES booking(id)',
        'event_index':'INTEGER', 'refund_version':'INTEGER NOT NULL DEFAULT 0',
        'staff_id':'INTEGER REFERENCES pos_staff(id)', 'staff_name':'VARCHAR(255)', 'price_override':'BOOLEAN NOT NULL DEFAULT FALSE'}
    with db.engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE pos_sale ADD COLUMN {name} {definition}')
    if 'loyalty_visit' in inspect(db.engine).get_table_names() and 'pos_sale_id' not in {
            column['name'] for column in inspect(db.engine).get_columns('loyalty_visit')}:
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE loyalty_visit ADD COLUMN pos_sale_id INTEGER REFERENCES pos_sale(id)')
    product_columns = {column['name'] for column in inspect(db.engine).get_columns('pos_product')}
    with db.engine.begin() as connection:
        for name,definition in {'category':"VARCHAR(60) NOT NULL DEFAULT 'General'",'shortcut':'BOOLEAN NOT NULL DEFAULT FALSE'}.items():
            if name not in product_columns:
                connection.exec_driver_sql(f'ALTER TABLE pos_product ADD COLUMN {name} {definition}')
    if 'pos_refund' in inspect(db.engine).get_table_names():
        refund_columns = {column['name'] for column in inspect(db.engine).get_columns('pos_refund')}
        with db.engine.begin() as connection:
            for name,definition in {'receipt_email':'VARCHAR(320)','receipt_status':'VARCHAR(20)','receipt_sent_at':'TIMESTAMP',
                    'loyalty_review_status':'VARCHAR(30)','loyalty_review_note':'TEXT','loyalty_reviewed_by':'VARCHAR(255)',
                    'loyalty_reviewed_at':'TIMESTAMP'}.items():
                if name not in refund_columns:
                    connection.exec_driver_sql(f'ALTER TABLE pos_refund ADD COLUMN {name} {definition}')
            if 'loyalty_review_status' not in refund_columns:
                rows=connection.execute(db.text("SELECT r.id,s.loyalty_result_json FROM pos_refund r JOIN pos_sale s ON s.id=r.sale_id WHERE r.status='Refunded' AND s.loyalty_result_json IS NOT NULL")).all()
                for identity,raw in rows:
                    try: awarded=any(item.get('points',0)>0 for item in json.loads(raw))
                    except (ValueError,TypeError,AttributeError): awarded=False
                    if awarded:
                        connection.execute(db.text("UPDATE pos_refund SET loyalty_review_status='Needs review' WHERE id=:identity"),{'identity':identity})
    if 'pos_staff' in inspect(db.engine).get_table_names():
        staff_columns={column['name'] for column in inspect(db.engine).get_columns('pos_staff')}
        with db.engine.begin() as connection:
            for name,definition in {'pin_hash':'TEXT','pin_digest':'VARCHAR(64)','permissions_json':'TEXT'}.items():
                if name not in staff_columns:
                    connection.exec_driver_sql(f'ALTER TABLE pos_staff ADD COLUMN {name} {definition}')
            connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_pos_staff_pin_digest ON pos_staff(pin_digest)')


def parse_tender(raw, total):
    try:
        tender = Decimal(raw)
        if (not tender.is_finite() or tender < total or tender > Decimal('999999.99')
                or tender != tender.quantize(Decimal('.01'))):
            raise ValueError()
        return tender
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Enter cash received covering the total, with at most two decimal places (maximum £999,999.99).')


def define_product_model(db):
    class PosProduct(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        price = db.Column(db.Numeric(10, 2), nullable=False)
        category = db.Column(db.String(60), nullable=False, default='General')
        shortcut = db.Column(db.Boolean, nullable=False, default=False)
    return PosProduct


def reader_transaction(merchant, reference):
    path = 'https://api.sumup.com/v2.1/merchants/' + quote(merchant, safe='') + '/transactions?'
    req = Request(path + urlencode({'foreign_transaction_id': reference}), headers={
        'Authorization': 'Bearer ' + os.environ['SUMUP_API_KEY'], 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read(100001))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (URLError, TimeoutError, ValueError):
        raise ValueError('Payment is not yet verified. Check SumUp before taking another payment.')


def waiver_status(waiver):
    today = datetime.now(ZoneInfo('Europe/London')).date()
    if waiver.is_archived:
        return 'Archived'
    if waiver.expiry_date.date() < today:
        return 'Expired'
    if waiver.status not in ('Valid', 'Expiring Soon'):
        return waiver.status
    return 'Valid'


def parse_items(raw):
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise ValueError()
        cleaned, total = [], Decimal('0.00')
        for item in items:
            name = item['name'].strip()
            quantity = int(str(item['quantity']))
            price = Decimal(str(item['price']))
            if (not name or len(name) > 120 or not 1 <= quantity <= 999
                    or not price.is_finite() or price <= 0 or price > 99999
                    or price != price.quantize(Decimal('.01'))):
                raise ValueError()
            cleaned.append(dict(name=name, quantity=quantity, price=str(price)))
            if item.get('product_id') is not None:
                cleaned[-1]['product_id'] = int(str(item['product_id']))
            total += quantity * price
        if total > Decimal('99999.99'):
            raise ValueError()
        return cleaned, total
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, OverflowError):
        raise ValueError('Add an item with a name, whole quantity and a positive price with at most two decimal places.')


def register(app, db, Sale, Waiver, Participant, admin_required, Product, send_email=None, loyalty=None):
    app.add_template_filter(format_sale_time, 'pos_timestamp')
    ledger = app.extensions.get('pos_ledger')
    access = app.extensions.get('pos_access')
    if not access:
        @app.context_processor
        def default_pos_permissions():
            return dict(pos_manager=True,pos_actor='Portal administrator')
    def send_receipt(sale, retry=False):
        # Claim delivery before contacting the provider so concurrent requests cannot send twice.
        states = ['Requested', 'Failed'] if retry else ['Requested']
        claimed = Sale.query.filter(Sale.id == sale.id, Sale.status == 'Paid',
            Sale.receipt_email.isnot(None), Sale.receipt_status.in_(states)).update(
                {'receipt_status':'Sending'}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            return
        db.session.refresh(sale)
        try:
            items = json.loads(sale.items_json)
            lines = [f'CL Paints receipt — Sale #{sale.id}', f'Reference: {sale.reference}',
                f'Paid: {format_sale_time(sale.paid_at)}', f'Payment: {sale.method}', '']
            lines.extend(f"{item['quantity']} x {item['name']} @ £{item['price']}" for item in items)
            lines.append(f'\nTotal paid: £{sale.amount:.2f}')
            if sale.cash_tender is not None:
                lines.extend([f'Cash received: £{sale.cash_tender:.2f}', f'Change: £{sale.change_due:.2f}'])
            lines.extend(['', 'Thank you for visiting CL Paints.', 'Questions about your receipt? Contact info@clpaints.com with the sale reference.'])
            accepted = send_email and send_email(sale.receipt_email, f'CL Paints receipt — Sale #{sale.id}',
                '\n'.join(lines), render_template('pos_receipt_email.html', sale=sale, items=items))
        except Exception:
            app.logger.warning('POS receipt sending failed for sale %s', sale.id)
            accepted = False
        sale.receipt_status = 'Sent' if accepted else 'Failed'
        sale.receipt_sent_at = datetime.utcnow() if accepted else None
        db.session.commit()
        if not accepted:
            flash('Payment is recorded, but the email receipt could not be sent. Retry from the saved sale.', 'error')

    def matching_waivers(pattern):
        fields = [Waiver.waiver_reference, Waiver.responsible_email,
                  Waiver.responsible_first_name + ' ' + Waiver.responsible_last_name]
        person_name = Participant.first_name + ' ' + Participant.last_name
        return or_(*(field.ilike(pattern, escape='\\') for field in fields),
            Waiver.participants.any(person_name.ilike(pattern, escape='\\')))

    def search_pattern(value):
        return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

    def waiver_search_context():
        query = request.args.get('q', '').strip()[:150]
        matches = Waiver.query.filter(Waiver.is_archived.is_(False),
            matching_waivers(search_pattern(query))).order_by(Waiver.signed_date.desc()).limit(30).all() if query else []
        waiver_people = {waiver.id:(loyalty.people(waiver) if loyalty else list(waiver.participants)) for waiver in matches}
        people = [person for records in waiver_people.values() for person in records]
        return dict(q=query, matches=matches, waiver_people=waiver_people,
            loyalty_balances=loyalty.balances(people) if loyalty else {}, waiver_status=waiver_status)

    @app.get('/admin/pos/waivers')
    @admin_required
    def pos_waiver_search():
        context = waiver_search_context()
        return jsonify(html=render_template('_pos_waiver_results.html', **context), count=len(context['matches']))

    @app.get('/admin/pos/waivers/<int:waiver_id>')
    @admin_required
    def pos_waiver_detail(waiver_id):
        waiver=db.get_or_404(Waiver,waiver_id)
        return render_template('pos_waiver_detail.html',waiver=waiver,status=waiver_status(waiver),
            people=loyalty.people(waiver) if loyalty else waiver.participants)

    def sale_destination(sale):
        if sale.method == 'Cash':
            return redirect(url_for('pos_home', completed=sale.id, _anchor='pos-cash-receipt'))
        return redirect(url_for('pos_sale', sale_id=sale.id))

    def card_settings():
        return [dict(key=key,label=label,present=bool(os.getenv(key,'').strip())) for key,label in (
            ('SUMUP_API_KEY','SumUp API key'),('SUMUP_MERCHANT_CODE','SumUp merchant code'),('SUMUP_POS_AFFILIATE_KEY','SumUp Affiliate Key'))]

    def configured():
        return all(setting['present'] for setting in card_settings())

    def check():
        token = session.get('client_csrf', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)

    @app.after_request
    def pos_no_cache(response):
        if request.path.startswith('/admin/pos'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/admin/pos')
    @admin_required
    def pos_home():
        session.setdefault('client_csrf', secrets.token_urlsafe(32))
        search_context = waiver_search_context()
        sale_query = request.args.get('sale_q', '').strip()[:150]
        history = Sale.query
        if sale_query:
            pattern = search_pattern(sale_query)
            criteria = [Sale.reference.ilike(pattern, escape='\\'),
                Sale.transaction_code.ilike(pattern, escape='\\'),
                Sale.customer_search.ilike(pattern, escape='\\'),
                Sale.waiver_id.in_(db.session.query(Waiver.id).filter(matching_waivers(pattern)))]
            if sale_query.isdecimal() and len(sale_query) <= 18:
                criteria.append(Sale.id == int(sale_query))
            history = history.filter(or_(*criteria))
        history_waiver = request.args.get('history_waiver', type=int)
        if history_waiver:
            history = history.filter_by(waiver_id=history_waiver)
        sales_page = history.order_by(Sale.id.desc()).paginate(page=max(1, request.args.get('sales_page', 1, type=int)), per_page=25, error_out=False)
        completed = db.session.get(Sale, request.args.get('completed', type=int)) if request.args.get('completed', type=int) else None
        if completed and (completed.method != 'Cash' or completed.status != 'Paid'):
            completed = None
        return render_template('admin_pos.html', **search_context,
            loyalty_events=loyalty.events() if loyalty else [], loyalty_enabled=bool(loyalty),
            trading_events=ledger.events() if ledger else [],
            pending_loyalty_reviews=ledger.Refund.query.filter_by(loyalty_review_status='Needs review').order_by(ledger.Refund.id.desc()).limit(50).all() if ledger else [],
            products=Product.query.order_by(Product.name, Product.id).all(),
            product_categories=[row[0] for row in db.session.query(Product.category).distinct().order_by(Product.category).all()],
            configured=configured(),card_settings=card_settings(),
            sale_token=secrets.token_urlsafe(24),
            sales=sales_page.items, sales_page=sales_page, sale_q=sale_query,
            history_waiver=history_waiver, completed_sale=completed)

    @app.post('/admin/pos/library')
    @admin_required
    def pos_library_save():
        check()
        if access: access.require_manager()
        product_id = request.form.get('product_id', '', type=str)
        product = db.get_or_404(Product, product_id) if product_id else Product()
        try:
            items, _ = parse_items(json.dumps([dict(name=request.form.get('name', ''),
                quantity=1, price=request.form.get('price', ''))]))
            product.name = items[0]['name']
            product.price = Decimal(items[0]['price'])
            category = request.form.get('category','General').strip() or 'General'
            if len(category)>60: raise ValueError('Use a category of up to 60 characters.')
            product.category = category
            product.shortcut = request.form.get('shortcut')=='yes'
            db.session.add(product)
            db.session.commit()
            flash('Library item saved. New taps use the updated price; existing basket prices stay as entered.', 'success')
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        return redirect(url_for('pos_home', _anchor='pos-library'))

    @app.post('/admin/pos/library/<int:product_id>/delete')
    @admin_required
    def pos_library_delete(product_id):
        check()
        if access: access.require_manager()
        product = db.get_or_404(Product, product_id)
        db.session.delete(product)
        db.session.commit()
        flash('Item removed from the library. Existing sales and baskets are unchanged.', 'success')
        return redirect(url_for('pos_home', _anchor='pos-library'))

    @app.post('/admin/pos/sales')
    @admin_required
    def pos_create_sale():
        check()
        token = request.form.get('sale_token', '')
        if not 20 <= len(token) <= 50 or not all(c.isalnum() or c in '-_' for c in token):
            abort(400)
        reference = 'POS-' + token
        existing = Sale.query.filter_by(reference=reference).first()
        if existing:
            send_receipt(existing)
            return sale_destination(existing)
        try:
            items, total = parse_items(request.form.get('items', ''))
            override = False
            for item in items:
                product = db.session.get(Product,item.get('product_id')) if item.get('product_id') else None
                changed_price = not product or Decimal(item['price']) != product.price or item['name'] != product.name
                if changed_price and access and not access.manager():
                    raise ValueError('A manager must enter custom items or approve price changes. Refresh library prices before checkout.')
                override = override or changed_price
            method = request.form.get('method')
            if method not in ('Cash', 'Card'):
                raise ValueError('Choose cash or card.')
            if method == 'Card' and not configured():
                raise ValueError('SumUp reader payments need configuration before use.')
            tender = parse_tender(request.form.get('cash_tender', ''), total) if method == 'Cash' else None
            receipt_email = None
            if request.form.get('receipt_requested') == '1':
                try:
                    receipt_email = validate_email(request.form.get('receipt_email', '').strip(), check_deliverability=False).normalized
                except EmailNotValidError:
                    raise ValueError('Enter a valid customer email address for the requested receipt.')
            waiver_id = request.form.get('waiver_id', '')
            waiver = db.session.get(Waiver, int(waiver_id)) if waiver_id else None
            if waiver_id and (not waiver or waiver_status(waiver) != 'Valid'):
                raise ValueError('Select a current, valid waiver or clear the selection.')
            participant_id = request.form.get('participant_id', '')
            participant = db.session.get(Participant, int(participant_id)) if participant_id else None
            allowed_people = loyalty.people(waiver) if loyalty and waiver else (list(waiver.participants) if waiver else [])
            if participant_id and (not participant or participant.id not in {person.id for person in allowed_people}):
                raise ValueError('Choose a participant belonging to the linked waiver.')
            event_id, loyalty_ids = loyalty.prepare(waiver, request.form) if loyalty else (None, [])
            trading_id, booking_id, event_index = ledger.prepare(request.form) if ledger else (None, None, None)
            customer_label = f'{waiver.waiver_reference} — {waiver.responsible_first_name} {waiver.responsible_last_name}' if waiver else None
            customer_search = '\n'.join([customer_label, waiver.responsible_email or ''] +
                [f'{person.first_name} {person.last_name}' for person in allowed_people]) if waiver else None
            sale = Sale(reference=reference, items_json=json.dumps(items), amount=total,
                cash_tender=tender, participant_id=participant.id if participant else None,
                receipt_email=receipt_email, receipt_status='Requested' if receipt_email else None,
                loyalty_event_id=event_id, loyalty_participants_json=json.dumps(loyalty_ids),
                trading_event_id=trading_id, booking_id=booking_id, event_index=event_index,
                staff_id=session.get('pos_staff_id'), staff_name=access.actor() if access else app.config.get('ADMIN_EMAIL') or 'Portal administrator',
                price_override=override,
                participant_name=f'{participant.first_name} {participant.last_name}' if participant else None,
                customer_label=customer_label, customer_search=customer_search,
                waiver_id=waiver.id if waiver else None, method=method,
                status='Paid' if method == 'Cash' else 'Ready',
                merchant=os.getenv('SUMUP_MERCHANT_CODE', '') if method == 'Card' else '',
                paid_at=datetime.utcnow() if method == 'Cash' else None)
            db.session.add(sale)
            db.session.flush()
            if loyalty:
                loyalty.award(sale)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = Sale.query.filter_by(reference=reference).first()
            if not existing:
                abort(409)
            send_receipt(existing)
            return sale_destination(existing)
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
            return redirect(url_for('pos_home'))
        send_receipt(sale)
        return sale_destination(sale)

    @app.post('/admin/pos/sales/<int:sale_id>/receipt/retry')
    @admin_required
    def pos_retry_receipt(sale_id):
        check()
        sale = db.get_or_404(Sale, sale_id)
        if sale.status != 'Paid' or not sale.receipt_email or sale.receipt_status not in ('Failed', 'Requested'):
            abort(409)
        send_receipt(sale, retry=True)
        return sale_destination(sale)

    @app.get('/admin/pos/sales/<int:sale_id>')
    @admin_required
    def pos_sale(sale_id):
        sale = db.get_or_404(Sale, sale_id)
        session.setdefault('client_csrf', secrets.token_urlsafe(32))
        from pos_finances import refund_lines
        return render_template('pos_sale.html', sale=sale, items=json.loads(sale.items_json),
            refund_items=refund_lines(sale), refund_token=secrets.token_urlsafe(24),
            refund_blocked=any(row.status in ('Processing','Awaiting verification') for row in sale.refunds),
            waiver=db.session.get(Waiver, sale.waiver_id) if sale.waiver_id else None, payment_uri=None)

    @app.post('/admin/pos/sales/<int:sale_id>/start')
    @admin_required
    def pos_start_payment(sale_id):
        check()
        sale = db.get_or_404(Sale, sale_id)
        if not configured() or sale.merchant != os.getenv('SUMUP_MERCHANT_CODE'):
            abort(409)
        # A lost response must never silently create a second card charge.
        changed = Sale.query.filter_by(id=sale.id, method='Card', status='Ready').update({'status': 'Awaiting verification'})
        db.session.commit()
        if not changed:
            flash('Check the existing payment with SumUp before taking another payment.', 'error')
            return redirect(url_for('pos_sale', sale_id=sale.id))
        uri = 'sumupmerchant://pay/1.0?' + urlencode({
            'affiliate-key': os.environ['SUMUP_POS_AFFILIATE_KEY'],
            'app-id': os.getenv('SUMUP_POS_APP_ID', 'com.clpaints.pos.preview'),
            'total': str(sale.amount), 'currency': 'GBP', 'title': 'CL Paints ' + sale.reference,
            'merchant-code': sale.merchant,
            'foreign-tx-id': sale.reference, 'callback': 'clpaintspos://sumup-callback'})
        return render_template('pos_sale.html', sale=sale, items=json.loads(sale.items_json),
            waiver=db.session.get(Waiver, sale.waiver_id) if sale.waiver_id else None, payment_uri=uri)

    @app.post('/admin/pos/sales/<int:sale_id>/verify')
    @admin_required
    def pos_verify_payment(sale_id):
        check()
        sale = db.get_or_404(Sale, sale_id)
        if sale.method != 'Card' or sale.status == 'Ready':
            abort(409)
        if sale.status != 'Paid':
            try:
                if not os.getenv('SUMUP_API_KEY'):
                    raise ValueError('SumUp verification is not configured.')
                data = reader_transaction(sale.merchant, sale.reference)
                if (data.get('status') != 'SUCCESSFUL' or data.get('currency') != 'GBP'
                        or data.get('foreign_transaction_id') != sale.reference
                        or Decimal(str(data.get('amount'))) != sale.amount
                        or not isinstance(data.get('transaction_code'), str)
                        or not 1 <= len(data['transaction_code']) <= 100):
                    raise ValueError('Payment is not confirmed. Check SumUp before taking another payment.')
                sale.transaction_code = data['transaction_code']
                sale.status = 'Paid'
                sale.paid_at = datetime.utcnow()
                if loyalty:
                    loyalty.award(sale)
                db.session.commit()
                flash('Card payment verified with SumUp.', 'success')
            except (ValueError, InvalidOperation, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if not isinstance(error, IntegrityError) else 'Transaction already belongs to another sale.', 'error')
        send_receipt(sale)
        return redirect(url_for('pos_sale', sale_id=sale.id))
