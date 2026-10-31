"""Independent custom headband orders, catalogue and correspondence."""
import json
import re
import secrets
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from flask import abort, redirect, render_template, request, session, url_for
from email_validator import validate_email, EmailNotValidError

STATUSES = ('Under review', 'Paid', 'In production', 'Shipped', 'Ready for collection')
HEADBAND_COLOURS = ('Black', 'White', 'Red', 'Blue', 'Green', 'Pink', 'Purple', 'Gold', 'Silver')
LETTER_FINISHES = ('Plain', 'Glitter')
CUSTOM_REFUND_POLICY = ('Each headband is personalised and custom-made to your order. We do not accept returns or offer refunds for a change of mind or mistakes in the wording or options you approve. '
                        'This does not affect your statutory rights if an item is faulty, not as described or otherwise fails to meet your legal rights. Please check all wording and selections before ordering.')


def next_order_action(order):
    if order.status in ('Shipped', 'Ready for collection'):
        return 'View order and delivery details'
    if order.status == 'Under review':
        return 'Review order and send invoice'
    if order.paid < order.total:
        return 'Review invoice and outstanding payment'
    if order.status == 'In production':
        return 'Arrange collection' if order.fulfilment == 'collection' else 'Add tracking and arrange dispatch'
    return 'Start production'


def ensure_schema(db):
    """Upgrade existing orders; create_all only creates missing tables."""
    from sqlalchemy import inspect, text
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('creates_order'):
            return
        columns = {column['name'] for column in inspector.get_columns('creates_order')}
        if 'acknowledgement' not in columns:
            connection.execute(text(
                "ALTER TABLE creates_order ADD COLUMN acknowledgement TEXT NOT NULL "
                "DEFAULT 'Acknowledgement was not recorded for this legacy order.'"
            ))


def define_models(db):
    class CreatesOrder(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        first_name = db.Column(db.String(100), nullable=False)
        last_name = db.Column(db.String(100), nullable=False)
        email = db.Column(db.String(254), nullable=False)
        address = db.Column(db.Text, nullable=False)
        fulfilment = db.Column(db.String(20), nullable=False)
        items_json = db.Column(db.Text, nullable=False)
        total = db.Column(db.Numeric(10, 2), nullable=False)
        paid = db.Column(db.Numeric(10, 2), default=0, nullable=False)
        status = db.Column(db.String(40), default='Under review', nullable=False)
        invoice_url = db.Column(db.Text, default='', nullable=False)
        invoice_reference = db.Column(db.String(100), default='', nullable=False)
        tracking = db.Column(db.String(200), default='', nullable=False)
        acknowledgement = db.Column(db.Text, nullable=False, default='Customer confirmed custom wording and acknowledged order and privacy information (CL Creates v1).')
        @property
        def number(self):
            return f'O-{self.id:06d}'
        @property
        def items(self):
            return json.loads(self.items_json)
    class CreatesMessage(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        order_id = db.Column(db.Integer, db.ForeignKey('creates_order.id'), nullable=False, index=True)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        subject = db.Column(db.Text, nullable=False)
        body = db.Column(db.Text, nullable=False)
        result = db.Column(db.String(40), nullable=False)
    class CreatesProduct(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(100), nullable=False)
        image = db.Column(db.LargeBinary, nullable=True)
        mimetype = db.Column(db.String(40))
        active = db.Column(db.Boolean, default=True, nullable=False)
    class CreatesImage(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(150), nullable=False)
        data = db.Column(db.LargeBinary, nullable=False)
        mimetype = db.Column(db.String(40), nullable=False)
        visible = db.Column(db.Boolean, default=True, nullable=False)
    return CreatesOrder, CreatesMessage, CreatesProduct, CreatesImage


def register(app, db, models, Setting, admin_required, send_email, get_current_client=lambda: None):
    app.jinja_env.globals['next_order_action'] = next_order_action
    app.jinja_env.globals['creates_refund_policy'] = CUSTOM_REFUND_POLICY
    Order, Message, Product, LibraryImage = models
    defaults = {'price': '5.00', 'postage': '6.00', 'emails': True,
                'subject': 'CL Creates {order_number}: {status}',
                'body': 'Hello {first_name},\n\nYour order {order_number} is {status}.\nTotal: £{total}\n{invoice_url}\n{tracking}\n\nThank you, CL Creates'}

    def read_image(upload):
        from PIL import Image
        from io import BytesIO
        data = upload.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('Images must be under 5 MB.')
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 20000000:
                    raise ValueError('Unsupported image size or format.')
                image.load()
                from PIL import ImageOps
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.convert('RGB').save(output, 'JPEG', quality=90)
                return output.getvalue(), 'image/jpeg'
        except Exception as exc:
            raise ValueError('Upload a valid JPEG, PNG or WebP image up to 20 megapixels.') from exc

    # Import supplied examples once. Deleting them in the library is permanent.
    with app.app_context():
        if not db.session.get(Setting, 'creates_examples_v1'):
            for filename, name in [('maid-of-honor.png', 'Maid of honor'), ('bridesmaid.png', 'Bridesmaid'), ('team-bride.png', 'Team bride')]:
                path = Path(app.root_path) / 'assets' / 'cl-creates-examples' / filename
                if path.exists():
                    with path.open('rb') as source:
                        data, mimetype = read_image(source)
                    db.session.add(LibraryImage(name=name, data=data, mimetype=mimetype))
            for product in Product.query.filter(Product.image.isnot(None)).all():
                db.session.add(LibraryImage(name=product.name, data=product.image, mimetype=product.mimetype, visible=False))
            db.session.add(Setting(key='creates_examples_v1', value='imported'))
            db.session.commit()

    def settings():
        row = db.session.get(Setting, 'cl_creates')
        return dict(defaults, **(json.loads(row.value) if row else {}))

    def colour_options():
        row = db.session.get(Setting, 'cl_creates_colours')
        return json.loads(row.value) if row else dict(headband=list(HEADBAND_COLOURS), glitter=['Gold', 'Silver', 'Pink', 'Blue', 'Purple', 'Red', 'Green'])

    def shape_options():
        row = db.session.get(Setting, 'cl_creates_shapes')
        return json.loads(row.value) if row else ['Heart', 'Star']

    @app.route('/admin/cl-creates/shapes', methods=['GET', 'POST'])
    @admin_required
    def creates_shapes():
        token = csrf()
        shapes = shape_options()
        error = None
        if request.method == 'POST':
            try:
                name = request.form.get('name', '').strip()
                action = request.form.get('action')
                if action == 'add':
                    if not name or len(name) > 40 or any(not char.isprintable() for char in name):
                        raise ValueError('Enter a shape name between 1 and 40 characters.')
                    if name.casefold() in {shape.casefold() for shape in shapes}:
                        raise ValueError('That shape is already available.')
                    if len(shapes) >= 50:
                        raise ValueError('You can list up to 50 shapes.')
                    shapes.append(name)
                elif action == 'remove':
                    if name in shapes:
                        shapes.remove(name)
                else:
                    abort(400)
                db.session.merge(Setting(key='cl_creates_shapes', value=json.dumps(shapes)))
                db.session.commit()
                return redirect(url_for('creates_shapes'))
            except ValueError as exc:
                error = str(exc)
        return render_template('creates_shapes.html', shapes=shapes, csrf=token, error=error)

    @app.route('/admin/cl-creates/colours', methods=['GET', 'POST'])
    @admin_required
    def creates_colours():
        token = csrf()
        options = colour_options()
        error = None
        if request.method == 'POST':
            try:
                kind = request.form.get('kind')
                action = request.form.get('action')
                name = request.form.get('name', '').strip()
                if kind not in ('headband', 'glitter') or action not in ('add', 'remove'):
                    abort(400)
                if action == 'add':
                    if not name or len(name) > 40 or any(not char.isprintable() for char in name):
                        raise ValueError('Enter a colour name between 1 and 40 characters.')
                    if name.casefold() in {value.casefold() for value in options[kind]}:
                        raise ValueError('That colour is already available.')
                    if len(options[kind]) >= 50:
                        raise ValueError('You can list up to 50 colours in each category.')
                    options[kind].append(name)
                elif name in options[kind]:
                    if kind == 'headband' and len(options[kind]) == 1:
                        raise ValueError('Keep at least one headband colour available.')
                    options[kind].remove(name)
                db.session.merge(Setting(key='cl_creates_colours', value=json.dumps(options)))
                db.session.commit()
                return redirect(url_for('creates_colours'))
            except ValueError as exc:
                error = str(exc)
        return render_template('creates_colours.html', options=options, csrf=token, error=error)

    def csrf():
        token = session.setdefault('creates_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST' and not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)
        return token

    def money(value):
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0 or amount > 999999 or amount != amount.quantize(Decimal('.01')):
                raise ValueError('Enter a valid amount with up to two decimal places.')
            return amount
        except InvalidOperation:
            raise ValueError('Enter a valid amount.')

    def communicate(order, subject, body, automated=False):
        result = 'Disabled' if automated and not settings()['emails'] else 'Pending'
        message = Message(order_id=order.id, subject=subject, body=body, result=result)
        db.session.add(message)
        db.session.commit()
        if result == 'Pending':
            try:
                message.result = 'Sent' if send_email(order.email, subject, body) else 'Failed'
            except Exception:
                message.result = 'Failed'
            db.session.commit()

    def status_email(order):
        config = settings()
        values = dict(order_number=order.number, first_name=order.first_name, status=order.status,
                      total=f'{order.total:.2f}', invoice_url=order.invoice_url, tracking=order.tracking)
        communicate(order, config['subject'].format(**values), config['body'].format(**values), True)

    @app.route('/cl-creates', methods=['GET', 'POST'])
    def creates_shop():
        token = csrf()
        account = get_current_client()
        back_url = request.form.get('return_to', '') if request.method == 'POST' else request.args.get('return_to', '')
        if (not back_url.startswith('/') or back_url.startswith('//') or
                chr(92) in back_url or any(ord(char) < 32 for char in back_url) or
                back_url.split('?', 1)[0].startswith('/cl-creates')):
            back_url = url_for('client.dashboard' if account else 'website_home')
        defaults = {}
        if account:
            defaults = {key: getattr(account, key) for key in ('first_name', 'last_name', 'email')}
            billing = db.session.get(app.extensions['client_billing_address_model'], account.id)
            if billing:
                details = billing.details
                defaults.update(address_line1=details.get('address_property', ''),
                                address_line2=details.get('address_street', ''),
                                town=details.get('address_city', ''), postcode=details.get('address_postcode', ''))
        shop_context = dict(client_account=account, client_csrf=session.get('client_csrf', ''),
                            shop_base='client/base.html' if account else 'base.html', defaults=defaults, back_url=back_url)
        config = settings()
        products = Product.query.filter_by(active=True).all()
        error = None
        if request.method == 'POST':
            try:
                if not session.get('creates_submission') or request.form.get('submission_token') != session.get('creates_submission'):
                    raise ValueError('This form has already been submitted. Please reload before placing another order.')
                first, last = (request.form.get(k, '').strip() for k in ('first_name', 'last_name'))
                if not first or not last or max(len(first), len(last)) > 100:
                    raise ValueError('Enter your first and last name (up to 100 characters each).')
                email = validate_email(request.form.get('email', ''), check_deliverability=False).normalized
                fulfilment = request.form.get('fulfilment')
                if fulfilment not in ('postage', 'collection'):
                    raise ValueError('Choose postage or collection.')
                address = ''
                if fulfilment == 'postage':
                    parts = [request.form.get(k, '').strip() for k in ('address_line1', 'address_line2', 'town', 'postcode')]
                    postcode = re.sub(r'\s+', '', parts[-1]).upper()
                    if not parts[0] or not parts[2] or not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}', postcode):
                        raise ValueError('Enter a full UK delivery address and postcode.')
                    if postcode.startswith(('BT', 'GY', 'JE', 'IM', 'HS', 'ZE')) or not request.form.get('mainland'):
                        raise ValueError('Delivery is available to UK mainland addresses only. Choose collection for other locations.')
                    address = '\n'.join(p for p in parts if p) + '\nUnited Kingdom'
                if len(address) > 1000 or not request.form.get('consent'):
                    raise ValueError('Please acknowledge the order and privacy information.')
                if request.form.get('custom_order_declaration') != 'yes':
                    raise ValueError('Please read and acknowledge the custom-made order and refunds declaration.')
                ids, words, quantities = (request.form.getlist(k) for k in ('product', 'wording', 'quantity'))
                if not 1 <= len(ids) <= 30 or len(ids) != len(words) or len(ids) != len(quantities):
                    raise ValueError('Add between 1 and 30 headband lines.')
                items = []
                options = colour_options()
                colours = request.form.getlist('colour') or [options['headband'][0]] * len(ids)
                finishes = request.form.getlist('letter_finish') or ['Plain'] * len(ids)
                glitter_colours = request.form.getlist('glitter_colour') or [(options['glitter'][0] if options['glitter'] else '')] * len(ids)
                shapes = request.form.getlist('word_shape') or [''] * len(ids)
                available_shapes = shape_options()
                if len(colours) != len(ids) or len(finishes) != len(ids) or len(glitter_colours) != len(ids) or len(shapes) != len(ids):
                    raise ValueError('Choose a colour and letter finish for each headband.')
                for pid, wording, quantity, colour, finish, glitter_colour, shape in zip(ids, words, quantities, colours, finishes, glitter_colours, shapes):
                    if shape and shape not in available_shapes:
                        raise ValueError('Choose an available shape between words.')
                    if colour not in options['headband'] or finish not in LETTER_FINISHES or (finish == 'Glitter' and glitter_colour not in options['glitter']):
                        raise ValueError('Choose an available headband colour and letter finish.')
                    if pid == 'custom':
                        product_name = 'Custom wording headband'
                    else:
                        product = db.session.get(Product, int(pid))
                        if not product or not product.active:
                            raise ValueError('Choose an available headband.')
                        product_name = product.name
                    if not wording.strip() or sum(c != ' ' for c in wording) > 11 or wording.count(' ') > 2 or any(not c.isprintable() for c in wording):
                        raise ValueError('Wording allows 11 characters plus up to two spaces.')
                    qty = int(quantity)
                    if not 1 <= qty <= 100:
                        raise ValueError('Each quantity must be between 1 and 100.')
                    items.append(dict(product=product_name, wording=wording, colour=colour, letter_finish=finish, glitter_colour=glitter_colour if finish == 'Glitter' else '', word_shape=shape if len(wording.split()) > 1 else '', quantity=qty, price=config['price']))
                total = sum(i['quantity'] * money(i['price']) for i in items) + (money(config['postage']) if fulfilment == 'postage' else 0)
                order = Order(first_name=first, last_name=last, email=email, address=address,
                              fulfilment=fulfilment, items_json=json.dumps(items), total=total,
                              acknowledgement='Customer confirmed wording, selections, order and privacy information, and accepted the custom-made refund declaration (CL Creates v2): ' + CUSTOM_REFUND_POLICY)
                db.session.add(order)
                db.session.commit()
                session.pop('creates_submission', None)
                status_email(order)
                return render_template('creates_confirmation.html', order=order, **shop_context)
            except (ValueError, EmailNotValidError) as exc:
                error = str(exc)
        session.setdefault('creates_submission', secrets.token_urlsafe(32))
        return render_template('creates_shop.html', products=products, config=config, csrf=token, error=error,
                               headband_colours=colour_options()['headband'], glitter_colours=colour_options()['glitter'], letter_finishes=LETTER_FINISHES if colour_options()['glitter'] else ('Plain',),
                               word_shapes=shape_options(),
                               gallery=LibraryImage.query.filter_by(visible=True).order_by(LibraryImage.id).all(), **shop_context)

    @app.get('/cl-creates/library/<int:image_id>')
    def creates_library_image(image_id):
        from flask import Response
        image = LibraryImage.query.get_or_404(image_id)
        if not image.visible and not session.get('admin_authenticated'):
            abort(404)
        return Response(image.data, mimetype=image.mimetype,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})

    @app.route('/admin/cl-creates/images', methods=['GET', 'POST'])
    @admin_required
    def creates_library():
        token = csrf()
        error = None
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'upload':
                    uploads = [f for f in request.files.getlist('images') if f.filename]
                    if not 1 <= len(uploads) <= 10:
                        raise ValueError('Select between 1 and 10 images to upload.')
                    prepared = []
                    for upload in uploads:
                        data, mimetype = read_image(upload)
                        name = Path(upload.filename.replace('\\', '/')).stem[:150] or 'Headband example'
                        prepared.append(LibraryImage(name=name, data=data, mimetype=mimetype))
                    db.session.add_all(prepared)
                elif action in ('delete', 'update'):
                    image = LibraryImage.query.get_or_404(request.form.get('image_id', type=int))
                    if action == 'delete':
                        # Remove catalogue copies too, without altering products or orders.
                        for product in Product.query.filter(Product.image == image.data).all():
                            product.image, product.mimetype = None, None
                        db.session.delete(image)
                    else:
                        name = request.form.get('name', '').strip()
                        if not name or len(name) > 150:
                            raise ValueError('Enter a caption up to 150 characters.')
                        image.name, image.visible = name, bool(request.form.get('visible'))
                else:
                    abort(400)
                db.session.commit()
                return redirect(url_for('creates_library'))
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)
        return render_template('creates_library.html', images=LibraryImage.query.order_by(LibraryImage.id.desc()).all(), csrf=token, error=error)

    @app.get('/cl-creates/images/<int:product_id>')
    def creates_image(product_id):
        from flask import Response
        product = Product.query.get_or_404(product_id)
        if not product.image:
            abort(404)
        return Response(product.image, mimetype=product.mimetype, headers={'X-Content-Type-Options': 'nosniff'})

    @app.get('/admin/cl-creates')
    @admin_required
    def creates_admin():
        token = csrf()
        query = Order.query
        search = request.args.get('q', '').strip()
        if search:
            pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            fields = [Order.first_name, Order.last_name, Order.email, Order.address, Order.first_name + ' ' + Order.last_name]
            conditions = [f.ilike(pattern, escape='\\') for f in fields]
            if re.fullmatch(r'(?:O-)?\d+', search, re.I):
                conditions.append(Order.id == int(search.upper().removeprefix('O-')))
            query = query.filter(db.or_(*conditions))
        page = query.order_by(Order.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=50, error_out=False)
        now = datetime.now(ZoneInfo('Europe/London')).date()
        counts = dict(day=0, week=0, month=0, year=0)
        paid = Decimal(0)
        outstanding = Decimal(0)
        completed = 0
        for order in Order.query.yield_per(200):
            date = order.created_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/London')).date()
            counts['day'] += date == now
            counts['week'] += date.isocalendar()[:2] == now.isocalendar()[:2]
            counts['month'] += (date.year, date.month) == (now.year, now.month)
            counts['year'] += date.year == now.year
            paid += order.paid
            outstanding += order.total - order.paid
            completed += order.status in ('Shipped', 'Ready for collection')
        return render_template('creates_admin.html', orders=page.items, pagination=page, counts=counts, paid=paid,
                               outstanding=outstanding, completed=completed, csrf=token, statuses=STATUSES, search=search)

    @app.route('/admin/cl-creates/orders/<int:order_id>', methods=['GET', 'POST'])
    @admin_required
    def creates_order(order_id):
        token = csrf()
        order = Order.query.filter_by(id=order_id).with_for_update().first_or_404()
        error = None
        if request.method == 'POST':
            try:
                if request.form.get('action') == 'delete':
                    if order.status != 'Under review' or order.paid != 0:
                        raise ValueError('Only unpaid orders under review can be deleted.')
                    if order.invoice_url or order.invoice_reference:
                        raise ValueError('This order has an attached invoice. Resolve the invoice in SumUp and remove its details before deleting the order.')
                    if request.form.get('confirm_delete') != 'yes':
                        raise ValueError('Confirm that you want to permanently delete this order.')
                    Message.query.filter_by(order_id=order.id).delete(synchronize_session=False)
                    db.session.delete(order)
                    db.session.commit()
                    return redirect(url_for('creates_admin', deleted='1'))
                elif request.form.get('action') == 'message':
                    subject, body = (request.form.get(k, '').strip() for k in ('subject', 'body'))
                    if not subject or not body or len(subject) > 200 or len(body) > 10000:
                        raise ValueError('Enter a subject and message (maximum 200 / 10,000 characters).')
                    communicate(order, subject, body)
                else:
                    status = request.form.get('status', order.status)
                    paid = money(request.form.get('paid', str(order.paid)))
                    invoice = request.form.get('invoice_url', order.invoice_url).strip()
                    if invoice:
                        parsed = urlparse(invoice)
                        if parsed.scheme != 'https' or not parsed.hostname or not (parsed.hostname == 'sumup.com' or parsed.hostname.endswith('.sumup.com') or parsed.hostname == 'sumup.me' or parsed.hostname.endswith('.sumup.me')) or parsed.username or parsed.password:
                            raise ValueError('Use an HTTPS SumUp invoice link.')
                    if status not in STATUSES or paid > order.total:
                        raise ValueError('Check the status and payment amount.')
                    if status != 'Under review' and paid != order.total:
                        raise ValueError(f'Record the full payment of £{order.total:.2f} in Payment received before selecting {status}. Check the invoice before recording payment.')
                    if (status == 'Shipped' and order.fulfilment != 'postage') or (status == 'Ready for collection' and order.fulfilment != 'collection'):
                        raise ValueError('The status must match the delivery method.')
                    changed = status != order.status
                    order.status, order.paid, order.invoice_url = status, paid, invoice
                    order.invoice_reference = request.form.get('invoice_reference', order.invoice_reference)[:100]
                    order.tracking = request.form.get('tracking', order.tracking)[:200]
                    db.session.commit()
                    if changed:
                        status_email(order)
                return redirect(url_for('creates_order', order_id=order.id, **({'popup': '1'} if request.args.get('popup') == '1' else {})))
            except ValueError as exc:
                error = str(exc)
        messages = Message.query.filter_by(order_id=order.id).order_by(Message.id.desc()).all()
        return render_template('creates_order.html', order=order, messages=messages, statuses=STATUSES, csrf=token, error=error)

    @app.get('/admin/cl-creates/orders/<int:order_id>/shipping-label')
    @admin_required
    def creates_shipping_label(order_id):
        order = Order.query.get_or_404(order_id)
        if order.fulfilment != 'postage':
            abort(404)
        return render_template('creates_shipping_label.html', order=order), 200, {'Cache-Control': 'no-store'}

    @app.get('/admin/cl-creates/communications')
    @admin_required
    def creates_communications():
        page = Message.query.order_by(Message.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=50, error_out=False)
        return render_template('creates_communications.html', messages=page.items, pagination=page)

    @app.route('/admin/cl-creates/settings', methods=['GET', 'POST'])
    @admin_required
    def creates_settings():
        token = csrf()
        config = settings()
        error = None
        if request.method == 'POST':
            try:
                action = request.form.get('action')
                if action == 'product':
                    name = request.form.get('name', '').strip()
                    if not name or len(name) > 100:
                        raise ValueError('Enter a product name up to 100 characters.')
                    product = Product(name=name)
                    upload = request.files.get('image')
                    if upload and upload.filename:
                        product.image, product.mimetype = read_image(upload)
                        db.session.add(LibraryImage(name=name, data=product.image, mimetype=product.mimetype, visible=False))
                    elif request.form.get('library_image'):
                        image = LibraryImage.query.get_or_404(request.form.get('library_image', type=int))
                        product.image, product.mimetype = image.data, image.mimetype
                    db.session.add(product)
                elif action == 'product_image':
                    product = Product.query.get_or_404(request.form.get('product_id', type=int))
                    if request.form.get('library_image'):
                        image = LibraryImage.query.get_or_404(request.form.get('library_image', type=int))
                        product.image, product.mimetype = image.data, image.mimetype
                    else:
                        product.image, product.mimetype = None, None
                elif action == 'toggle':
                    product = Product.query.get_or_404(request.form.get('product_id', type=int))
                    product.active = not product.active
                else:
                    config = dict(price=str(money(request.form.get('price', ''))), postage=str(money(request.form.get('postage', ''))),
                                  emails=bool(request.form.get('emails')), subject=request.form.get('subject', ''), body=request.form.get('body', ''))
                    values = dict.fromkeys(('order_number', 'first_name', 'status', 'total', 'invoice_url', 'tracking'), 'Example')
                    try:
                        config['subject'].format(**values)
                        config['body'].format(**values)
                    except (KeyError, ValueError, IndexError, AttributeError):
                        raise ValueError('Use only the supported email placeholders.')
                    if not config['subject'].strip() or not config['body'].strip() or len(config['subject']) > 200 or len(config['body']) > 10000:
                        raise ValueError('Enter an email subject and body within 200 / 10,000 characters.')
                    db.session.merge(Setting(key='cl_creates', value=json.dumps(config)))
                db.session.commit()
                return redirect(url_for('creates_settings'))
            except ValueError as exc:
                error = str(exc)
        return render_template('creates_settings.html', config=config, products=Product.query.all(), csrf=token, error=error,
                               library=LibraryImage.query.order_by(LibraryImage.id.desc()).all())
