"""Staff till, consent lookup and independently verified reader payments."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import csv
from io import StringIO
import json
import os
import secrets
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, render_template, request, session, url_for, jsonify, Response
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
        reserved_stock_json = db.Column(db.Text)
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
        'event_index':'INTEGER', 'reserved_stock_json':'TEXT', 'refund_version':'INTEGER NOT NULL DEFAULT 0',
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
        for name,definition in {'category':"VARCHAR(60) NOT NULL DEFAULT 'General'",'shortcut':'BOOLEAN NOT NULL DEFAULT FALSE', 'variations_text':'TEXT', 'variation_colours_json':'TEXT', 'tile_colour':'VARCHAR(7)', 'tile_position':'INTEGER', 'stock_quantity':'INTEGER', 'stock_warning':'INTEGER', 'loyalty_reward':'BOOLEAN NOT NULL DEFAULT FALSE'}.items():
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
        variations_text = db.Column(db.Text)
        variation_colours_json = db.Column(db.Text)
        tile_colour = db.Column(db.String(7))
        tile_position = db.Column(db.Integer)
        stock_quantity = db.Column(db.Integer)
        stock_warning = db.Column(db.Integer)
        loyalty_reward = db.Column(db.Boolean, nullable=False, default=False)

        @property
        def variations(self):
            return (self.variations_text or '').splitlines()

        @property
        def variation_colours(self):
            return json.loads(self.variation_colours_json or '{}')

        @property
        def low_stock(self):
            return self.stock_quantity is not None and self.stock_quantity <= (self.stock_warning or 0)

    class PosCategory(db.Model):
        name = db.Column(db.String(60), primary_key=True)

    class PosTileLayout(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        columns = db.Column(db.Integer, nullable=False)

    PosProduct.Category = PosCategory
    PosProduct.Layout = PosTileLayout
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
            if item.get('variation'):
                variation = item['variation']
                if not isinstance(variation, str) or len(variation) > 60:
                    raise ValueError()
                cleaned[-1]['variation'] = variation
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
        recent = request.args.get('recent') == '1'
        records = Waiver.query.filter(Waiver.is_archived.is_(False), Waiver.status != 'Superseded')
        if query:
            records = records.filter(matching_waivers(search_pattern(query)))
        if recent:
            records = records.filter(Waiver.signed_date >= datetime.now() - timedelta(hours=24))
        matches = records.order_by(Waiver.signed_date.desc(), Waiver.id.desc()).limit(30).all() if query or recent else []
        waiver_people = {waiver.id:(loyalty.people(waiver) if loyalty else list(waiver.participants)) for waiver in matches}
        people = [person for records in waiver_people.values() for person in records]
        return dict(q=query, recent=recent, matches=matches, waiver_people=waiver_people,
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
        if sale.method in ('Cash', 'Loyalty'):
            return redirect(url_for('pos_home', completed=sale.id, _anchor='pos-cash-receipt'))
        return redirect(url_for('pos_sale', sale_id=sale.id))

    def payment_time_left(sale):
        if sale.status not in ('Ready', 'Awaiting verification'):
            return None
        return max(0, int((sale.created_at + timedelta(seconds=30) - datetime.utcnow()).total_seconds() * 1000))

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
        history = Sale.query.filter_by(status='Paid')
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
        if completed and (completed.method not in ('Cash', 'Loyalty') or completed.status != 'Paid'):
            completed = None
        timed_out_id = request.args.get('timed_out', type=int)
        timed_out = db.session.get(Sale, timed_out_id) if timed_out_id else None
        if timed_out and (timed_out.status != 'Awaiting verification' or payment_time_left(timed_out) != 0):
            timed_out = None
        tile_layout = db.session.get(Product.Layout, 1)
        return render_template('admin_pos.html', **search_context,
            tile_columns=tile_layout.columns if tile_layout else 2,
            loyalty_events=loyalty.events() if loyalty else [], loyalty_enabled=bool(loyalty),
            trading_events=ledger.events() if ledger else [],
            pending_loyalty_reviews=ledger.Refund.query.filter_by(loyalty_review_status='Needs review').order_by(ledger.Refund.id.desc()).limit(50).all() if ledger else [],
            products=Product.query.order_by(Product.tile_position.is_(None), Product.tile_position,
                Product.name, Product.id).all(),
            product_categories=sorted({'General'} | {row.name for row in Product.Category.query.all()} |
                {row[0] for row in db.session.query(Product.category).distinct().all()}, key=str.casefold),
            configured=configured(),card_settings=card_settings(),
            library_open=request.args.get('manage') == '1', sale_token=secrets.token_urlsafe(24),
            sales=sales_page.items, sales_page=sales_page, sale_q=sale_query,
            history_waiver=history_waiver, completed_sale=completed, timed_out_sale=timed_out)

    @app.post('/admin/pos/library/order')
    @admin_required
    def pos_library_order():
        check()
        if access:
            access.require_manager()
        raw_ids = request.form.getlist('product_id')
        ids = request.form.getlist('product_id', type=int)
        raw_columns = request.form.get('columns')
        if raw_columns is not None and raw_columns not in ('2', '3'):
            return jsonify(error='Choose two or three columns.'), 400
        if len(raw_ids) != len(ids) or len(set(ids)) != len(ids):
            return jsonify(error='The tile order is invalid.'), 400
        products = {product.id: product for product in Product.query.order_by(Product.id).with_for_update().all()}
        if not ids or set(ids) != products.keys():
            db.session.rollback()
            return jsonify(error='The library changed. Reopen the till page before rearranging tiles.'), 409
        for position, identity in enumerate(ids):
            products[identity].tile_position = position
        layout = db.session.get(Product.Layout, 1)
        if raw_columns is not None:
            if layout is None:
                layout = Product.Layout(id=1)
                db.session.add(layout)
            layout.columns = int(raw_columns)
        db.session.commit()
        return jsonify(product_ids=ids, columns=layout.columns if layout else 2)

    @app.get('/admin/pos/stock')
    @admin_required
    def pos_stock():
        return jsonify({product.id: {'available': product.stock_quantity, 'low': product.low_stock}
            for product in Product.query.filter(Product.stock_quantity.isnot(None)).all()})

    @app.get('/admin/pos/cash-export')
    @admin_required
    def pos_cash_export():
        if access:
            access.require_manager()
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['CL Paints reference', 'Paid (UK time)', 'Currency', 'Total', 'Tender', 'Change', 'Refunded'])
        for sale in Sale.query.filter_by(method='Cash', status='Paid').order_by(Sale.id):
            writer.writerow([sale.reference, format_sale_time(sale.paid_at or sale.created_at),
                'GBP', sale.amount, sale.cash_tender, sale.change_due, sale.refunded_total])
        return Response(output.getvalue(), mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename="cl-paints-cash-sales.csv"'})

    @app.post('/admin/pos/library/categories')
    @admin_required
    def pos_category_save():
        check()
        if access:
            access.require_manager()
        name = request.form.get('category', '').strip()
        if not name or len(name) > 60:
            flash('Enter a category name of up to 60 characters.', 'error')
        elif name != 'General' and not db.session.get(Product.Category, name):
            db.session.add(Product.Category(name=name))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
        return redirect(url_for('pos_home', manage=1, _anchor='pos-library'))

    def take_stock(items):
        quantities = {}
        for item in items:
            identity = item.get('product_id')
            if identity:
                quantities[identity] = quantities.get(identity, 0) + item['quantity']
        reserved = {}
        for identity, quantity in sorted(quantities.items()):
            updated = Product.query.filter(Product.id == identity, Product.stock_quantity >= quantity).update(
                {Product.stock_quantity: Product.stock_quantity - quantity}, synchronize_session=False)
            if updated:
                reserved[identity] = quantity
            else:
                available = db.session.query(Product.stock_quantity).filter_by(id=identity).first()
                if available and available[0] is not None:
                    raise ValueError('Insufficient stock for an item in this basket. Check the library and adjust the quantity.')
        return reserved

    def valid_tile_colour(colour):
        return isinstance(colour, str) and len(colour) == 7 and colour[0] == '#' and all(
            digit in '0123456789abcdefABCDEF' for digit in colour[1:])

    @app.post('/admin/pos/library/<int:product_id>/variation-colours')
    @admin_required
    def pos_variation_colours_save(product_id):
        check()
        if access:
            access.require_manager()
        try:
            changes = json.loads(request.form.get('changes', ''))
        except ValueError:
            return jsonify(error='Choose valid variation colours.'), 400
        if not isinstance(changes, dict) or not changes or any(
                colour is not None and not valid_tile_colour(colour) for colour in changes.values()):
            return jsonify(error='Choose valid variation colours.'), 400
        product = Product.query.filter_by(id=product_id).with_for_update().first_or_404()
        if not changes.keys() <= set(product.variations):
            db.session.rollback()
            return jsonify(error='The variations changed. Reopen the till before saving colours.'), 409
        colours = product.variation_colours
        for variation, colour in changes.items():
            if colour is None:
                colours.pop(variation, None)
            else:
                colours[variation] = colour
        product.variation_colours_json = json.dumps(colours)
        db.session.commit()
        return jsonify(colours=colours)

    def update_library_item(product, fields):
        items, _ = parse_items(json.dumps([dict(name=fields.get('name', ''),
            quantity=1, price=fields.get('price', ''))]))
        product.name = items[0]['name']
        product.price = Decimal(items[0]['price'])
        category = fields.get('category','General').strip() or 'General'
        if len(category)>60: raise ValueError('Use a category of up to 60 characters.')
        product.category = category
        product.shortcut = fields.get('shortcut')=='yes'
        if 'variations' in fields:
            options = list(dict.fromkeys(line.strip() for line in fields['variations'].splitlines() if line.strip()))
            if len(options) > 50 or any(len(option) > 60 or len(product.name) + len(option) + 3 > 120 for option in options):
                raise ValueError('Use up to 50 variations with names that fit the 120-character sale line.')
            product.variations_text = '\n'.join(options)
            colour = fields.get('tile_colour', '')
            if colour and not valid_tile_colour(colour):
                raise ValueError('Choose a valid tile colour.')
            product.tile_colour = colour or None
            colours = json.loads(fields['variation_colours']) if 'variation_colours' in fields else product.variation_colours
            if not isinstance(colours, dict) or any(not valid_tile_colour(value) for value in colours.values()):
                raise ValueError('Choose a valid colour for each variation.')
            product.variation_colours_json = json.dumps({name: colours[name] for name in options if name in colours})
            for field in ('stock_quantity', 'stock_warning'):
                raw = fields.get(field, '').strip()
                if raw and (not raw.isascii() or not raw.isdecimal() or len(raw) > 7):
                    raise ValueError('Stock values must be whole numbers from 0 to 9,999,999.')
                value = int(raw) if raw else None
                original = fields.get('original_stock_quantity')
                if field != 'stock_quantity' or product.id is None or original is None:
                    setattr(product, field, value)
                elif raw != original:
                    if original and (not original.isascii() or not original.isdecimal() or len(original) > 7):
                        raise ValueError('Reload the library before changing stock.')
                    updated = Product.query.filter_by(id=product.id,
                        stock_quantity=int(original) if original else None).update(
                        {Product.stock_quantity: value}, synchronize_session=False)
                    if not updated:
                        raise ValueError('Stock changed while the library was open. Check the latest quantity and try again.')
                    db.session.expire(product, ['stock_quantity'])
            if product.stock_quantity is None and product.stock_warning is not None:
                raise ValueError('Enter stock on hand to use a low-stock warning.')
            product.loyalty_reward = fields.get('loyalty_reward') == 'yes'

    @app.post('/admin/pos/library')
    @admin_required
    def pos_library_save():
        check()
        if access:
            access.require_manager()
        product_id = request.form.get('product_id')
        product = db.get_or_404(Product, product_id) if product_id else Product()
        try:
            update_library_item(product, request.form)
            db.session.add(product)
            db.session.commit()
            flash('Library item saved.', 'success')
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        return redirect(url_for('pos_home', manage=1, _anchor='pos-library'))

    @app.post('/admin/pos/library/batch')
    @admin_required
    def pos_library_batch():
        check()
        if access:
            access.require_manager()
        try:
            edits = json.loads(request.form.get('edits', ''))
            if not isinstance(edits, list) or not edits:
                raise ValueError()
            updates = {}
            for fields in edits:
                if not isinstance(fields, dict) or not all(isinstance(value, str) for value in fields.values()):
                    raise ValueError()
                identity = int(fields.get('product_id', ''))
                if identity < 1 or identity > 2147483647 or identity in updates:
                    raise ValueError()
                updates[identity] = fields
        except ValueError:
            return jsonify(error='The item changes are invalid.'), 400

        products = Product.query.filter(Product.id.in_(updates)).order_by(Product.id).with_for_update().all()
        if len(products) != len(updates):
            db.session.rollback()
            return jsonify(error='An edited item has been removed. Discard its changes before saving.'), 409
        for product in products:
            name = product.name
            try:
                update_library_item(product, updates[product.id])
            except ValueError as error:
                db.session.rollback()
                return jsonify(error=f'{name}: {error}'), 400
        db.session.commit()
        flash(f"Changes saved to {len(products)} {'item' if len(products) == 1 else 'items'}.", 'success')
        return jsonify(location=url_for('pos_home', manage=1, _anchor='pos-library'))

    @app.post('/admin/pos/library/<int:product_id>/delete')
    @admin_required
    def pos_library_delete(product_id):
        check()
        if access: access.require_manager()
        product = db.get_or_404(Product, product_id)
        db.session.delete(product)
        db.session.commit()
        flash('Item removed from the library. Existing sales and baskets are unchanged.', 'success')
        return redirect(url_for('pos_home', manage=1, _anchor='pos-library'))

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
            original_total = total
            has_custom_item = False
            reward_index = None
            for index, item in enumerate(items):
                if 'product_id' not in item:
                    if access and not access.manager():
                        raise ValueError('A manager must enter custom items.')
                    has_custom_item = True
                    continue
                product = db.session.get(Product, item['product_id'])
                if not product:
                    raise ValueError('A basket item was removed from the library. Remove it from the basket to continue.')
                variation = item.get('variation')
                if (product.variations or variation) and variation not in product.variations:
                    raise ValueError('Choose a saved variation for this item.')
                expected_name = f'{product.name} · {variation}' if variation else product.name
                if Decimal(item['price']) != product.price or item['name'] != expected_name:
                    raise ValueError('A basket item differs from its saved details. Remove it and add it again from the library.')
                if product.loyalty_reward and reward_index is None:
                    reward_index = index
            method = request.form.get('method')
            if method not in ('Cash', 'Card', 'Loyalty'):
                raise ValueError('Choose cash or card.')
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
            reward_person = None
            if loyalty and reward_index is not None and participant and loyalty.balances([participant]).get(participant.id) == 3:
                reward_person = participant
                line = items[reward_index]
                total -= Decimal(line['price'])
                reward_line = dict(line, quantity=1, price='0.00', reward_participant_id=participant.id)
                if line['quantity'] == 1:
                    items[reward_index] = reward_line
                else:
                    line['quantity'] -= 1
                    items.insert(reward_index, reward_line)
                loyalty_ids = [identity for identity in loyalty_ids if identity != participant.id]
                if event_id is None:
                    selected_event = request.form.get('loyalty_event_id', type=int)
                    if selected_event in {event.id for event in loyalty.events()}:
                        event_id = selected_event
            expected_discount = request.form.get('reward_discount')
            if expected_discount is not None and expected_discount != str(int((original_total - total) * 100)):
                raise ValueError('The loyalty discount changed. Link the waiver again and check the total before payment.')
            if total == 0 and reward_person:
                method = 'Loyalty'
            elif method == 'Loyalty':
                raise ValueError('Choose a payment method for the remaining balance.')
            if method == 'Card' and not configured():
                raise ValueError('SumUp reader payments need configuration before use.')
            tender = parse_tender(request.form.get('cash_tender', ''), total) if method == 'Cash' else None
            if method != 'Card':
                take_stock(items)
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
                price_override=has_custom_item,
                participant_name=f'{participant.first_name} {participant.last_name}' if participant else None,
                customer_label=customer_label, customer_search=customer_search,
                waiver_id=waiver.id if waiver else None, method=method,
                status='Ready' if method == 'Card' else 'Paid',
                merchant=os.getenv('SUMUP_MERCHANT_CODE', '') if method == 'Card' else '',
                paid_at=None if method == 'Card' else datetime.utcnow())
            db.session.add(sale)
            db.session.flush()
            if loyalty:
                if reward_person and method != 'Card':
                    loyalty.claim_reward(sale, reward_person.id)
                loyalty.award(sale)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = Sale.query.filter_by(reference=reference).first()
            if not existing:
                flash('Stock or loyalty changed. Review the basket and try again.', 'error')
                return redirect(url_for('pos_home'))
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
        time_left = payment_time_left(sale)
        if time_left == 0 and sale.status == 'Ready':
            return redirect(url_for('pos_home'))
        from pos_finances import refund_lines
        return render_template('pos_sale.html', sale=sale, items=json.loads(sale.items_json),
            payment_time_left=time_left,
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
        cutoff = datetime.utcnow() - timedelta(seconds=30)
        changed = Sale.query.filter_by(id=sale.id, method='Card', status='Ready').filter(
            Sale.created_at > cutoff).update({'status': 'Awaiting verification'})
        if changed:
            try:
                items = json.loads(sale.items_json)
                sale.reserved_stock_json = json.dumps(take_stock(items))
                for item in items:
                    if loyalty and item.get('reward_participant_id'):
                        waiver = db.session.get(Waiver, sale.waiver_id)
                        if not waiver or waiver_status(waiver) != 'Valid' or item['reward_participant_id'] not in {p.id for p in loyalty.people(waiver)}:
                            raise ValueError('The participant needs a current linked waiver to redeem their reward.')
                        loyalty.claim_reward(sale, item['reward_participant_id'])
                db.session.commit()
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(str(error) if isinstance(error, ValueError) else 'Stock or loyalty changed. Review the basket and try again.', 'error')
                return redirect(url_for('pos_home'))
        else:
            db.session.rollback()
            if sale.status == 'Ready' and payment_time_left(sale) == 0:
                return redirect(url_for('pos_home'))
            flash('Check the existing payment with SumUp before taking another payment.', 'error')
            return redirect(url_for('pos_sale', sale_id=sale.id))
        uri = 'sumupmerchant://pay/1.0?' + urlencode({
            'affiliate-key': os.environ['SUMUP_POS_AFFILIATE_KEY'],
            'app-id': os.getenv('SUMUP_POS_APP_ID', 'com.clpaints.pos.preview'),
            'total': str(sale.amount), 'currency': 'GBP', 'title': 'CL Paints ' + sale.reference,
            'merchant-code': sale.merchant,
            'foreign-tx-id': sale.reference, 'callback': 'clpaintspos://sumup-callback'})
        return render_template('pos_sale.html', sale=sale, items=json.loads(sale.items_json),
            payment_time_left=payment_time_left(sale),
            waiver=db.session.get(Waiver, sale.waiver_id) if sale.waiver_id else None, payment_uri=uri)

    @app.post('/admin/pos/sales/<int:sale_id>/verify')
    @admin_required
    def pos_verify_payment(sale_id):
        check()
        sale = db.get_or_404(Sale, sale_id)
        if sale.method != 'Card' or sale.status == 'Ready':
            abort(409)
        if sale.status == 'Awaiting verification':
            try:
                if not os.getenv('SUMUP_API_KEY'):
                    raise ValueError('SumUp verification is not configured.')
                data = reader_transaction(sale.merchant, sale.reference)
                status = data.get('status')
                reserved_stock = json.loads(sale.reserved_stock_json or '{}')
                reward_ids = [item['reward_participant_id'] for item in json.loads(sale.items_json)
                    if item.get('reward_participant_id')]
                can_release = bool(reserved_stock or reward_ids)
                if (status not in ('SUCCESSFUL', 'FAILED', 'CANCELLED') or data.get('currency') != 'GBP'
                        or data.get('foreign_transaction_id') != sale.reference
                        or Decimal(str(data.get('amount'))) != sale.amount
                        or (status != 'SUCCESSFUL' and not can_release)
                        or (status == 'SUCCESSFUL' and (not isinstance(data.get('transaction_code'), str)
                            or not 1 <= len(data['transaction_code']) <= 100))):
                    raise ValueError('Payment is not confirmed. Check SumUp before taking another payment.')
                settled = Sale.query.filter_by(id=sale.id, status='Awaiting verification').update(
                    {'status': 'Paid' if status == 'SUCCESSFUL' else 'Failed'})
                if not settled:
                    db.session.rollback()
                    return redirect(url_for('pos_sale', sale_id=sale_id))
                if status != 'SUCCESSFUL':
                    for identity, quantity in reserved_stock.items():
                        Product.query.filter_by(id=int(identity)).update(
                            {Product.stock_quantity: Product.stock_quantity + quantity}, synchronize_session=False)
                    if loyalty:
                        for person_id in reward_ids:
                            loyalty.release_reward(sale, person_id)
                    sale.reserved_stock_json = None
                    db.session.commit()
                    flash('SumUp confirmed that payment failed or was cancelled.', 'error')
                    return redirect(url_for('pos_sale', sale_id=sale_id))
                sale.reserved_stock_json = None
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
