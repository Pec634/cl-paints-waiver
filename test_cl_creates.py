import unittest
from io import BytesIO
from unittest.mock import patch
import test_client_portal as fixtures

main = fixtures.main


class CreatesSchemaTest(unittest.TestCase):
    def test_legacy_upgrade_preserves_orders_and_can_run_twice(self):
        from types import SimpleNamespace
        from sqlalchemy import create_engine, inspect, text
        from cl_creates import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE creates_order (id INTEGER PRIMARY KEY, total NUMERIC NOT NULL)'))
                connection.execute(text('INSERT INTO creates_order (id, total) VALUES (42, 16.00)'))
            database = SimpleNamespace(engine=engine)
            ensure_schema(database)
            ensure_schema(database)
            with engine.connect() as connection:
                row = connection.execute(text('SELECT id, total, acknowledgement FROM creates_order')).one()
                self.assertEqual(row.id, 42)
                self.assertEqual(float(row.total), 16)
                self.assertEqual(row.acknowledgement, 'Acknowledgement was not recorded for this legacy order.')
                column = next(c for c in inspect(connection).get_columns('creates_order') if c['name'] == 'acknowledgement')
                self.assertFalse(column['nullable'])
        finally:
            engine.dispose()


class CreatesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True
        self.Order, self.Message, self.Product, self.Image = main.creates_models
        self.product = self.Product(name='Rainbow headband')
        main.db.session.add(self.product)
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def form(self):
        self.assertEqual(self.client.get('/cl-creates').status_code, 200)
        with self.client.session_transaction() as session:
            return dict(csrf_token=session['creates_csrf'], submission_token=session['creates_submission'],
                        first_name='Alex', last_name='Smith', email='alex@example.com', fulfilment='postage',
                        address_line1='1 Test Road', town='London', postcode='SW1A 1AA', mainland='on',
                        consent='on', product=str(self.product.id), wording='HELLO WORLD', quantity='2')

    def admin_token(self):
        self.assertEqual(self.admin.get('/admin/cl-creates').status_code, 200)
        with self.admin.session_transaction() as session:
            return session['creates_csrf']

    def test_portal_shop_prefills_signup_details_and_keeps_edits(self):
        account = self.fixture.signup()
        Address = main.app.extensions['client_billing_address_model']
        main.db.session.add(Address(client_id=account.id, details={
            'address_property': '42', 'address_street': 'Rainbow Road',
            'address_city': 'Doncaster', 'address_postcode': 'DN1 1AA',
            'address_country': 'United Kingdom'}))
        main.db.session.commit()
        page = self.client.get('/cl-creates')
        for value in [b'Client navigation', b'>CL Creates</a>', b'value="Test"',
                      b'value="client@example.com"', b'value="42"', b'value="Rainbow Road"',
                      b'value="Doncaster"', b'value="DN1 1AA"', b'autocomplete="postal-code"']:
            self.assertIn(value, page.data)
        data = self.form()
        data.update(address_line1='99 Changed Road', wording='')
        invalid = self.client.post('/cl-creates', data=data)
        self.assertIn(b'value="99 Changed Road"', invalid.data)
        self.assertNotIn(b'value="42"', invalid.data)
        anonymous = main.app.test_client().get('/cl-creates')
        self.assertNotIn(b'value="Rainbow Road"', anonymous.data)
        self.assertNotIn(b'aria-label="Client navigation"', anonymous.data)

    def test_shop_back_link_preserves_source_and_rejects_external_urls(self):
        page = self.client.get('/cl-creates', query_string={'return_to': '/services'})
        self.assertIn(b'href="/services">&larr; Back</a>', page.data)
        data = self.form()
        data['return_to'] = '/services'
        data['wording'] = ''
        invalid = self.client.post('/cl-creates', data=data)
        self.assertIn(b'href="/services">&larr; Back</a>', invalid.data)
        data['wording'] = 'HELLO'
        confirmation = self.client.post('/cl-creates', data=data)
        self.assertIn(b'href="/services">&larr; Back</a>', confirmation.data)
        for destination in ['https://example.com', '//example.com', '/\\example.com']:
            fallback = self.client.get('/cl-creates', query_string={'return_to': destination})
            self.assertIn(b'href="/">&larr; Back</a>', fallback.data)
        self.fixture.signup()
        portal = self.client.get('/cl-creates', query_string={'return_to': '/client/bookings'})
        self.assertIn(b'href="/client/bookings">&larr; Back</a>', portal.data)

    def test_order_totals_duplicate_and_private_details(self):
        data = self.form()
        data.update(product=[str(self.product.id)] * 2, wording=['HELLO WORLD', 'A B C'], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data)
        self.assertIn(b'O-000001', response.data)
        order = self.Order.query.one()
        self.assertEqual(float(order.total), 31)
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        path = f'/admin/cl-creates/orders/{order.id}'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.get(path).status_code, 200)
        self.assertIn(b'aria-label="Admin navigation"', self.admin.get(path).data)
        popup = self.admin.get(path + '?popup=1')
        self.assertEqual(popup.status_code, 200)
        self.assertNotIn(b'aria-label="Admin navigation"', popup.data)
        self.assertNotIn(b'aria-label="CL Creates navigation"', popup.data)
        saved = self.admin.post(path + '?popup=1', data=dict(csrf_token=self.admin_token(), status='Under review', paid='0'))
        self.assertEqual(saved.status_code, 302)
        self.assertIn('popup=1', saved.location)
        self.assertEqual(self.Message.query.one().result, 'Sent')
        for search in ['O-000001', 'Alex Smith', 'alex@example.com', 'Test Road']:
            self.assertIn(b'O-000001', self.admin.get('/admin/cl-creates', query_string={'q': search}).data)

    def test_custom_order_form_works_without_catalogue_products(self):
        main.db.session.delete(self.product)
        main.db.session.commit()
        page = self.client.get('/cl-creates')
        self.assertIn(b'id="creates-form"', page.data)
        self.assertIn(b'Order your custom headbands', page.data)
        self.assertNotIn(b'coming soon', page.data)
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BRIDE', 'BRIDESMAID'], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data)
        self.assertIn(b'O-000001', response.data)
        order = self.Order.query.one()
        self.assertEqual(float(order.total), 31)
        self.assertEqual([item['wording'] for item in order.items], ['TEAM BRIDE', 'BRIDESMAID'])
        self.assertEqual(order.status, 'Under review')

    def test_shipping_label_is_private_and_only_available_for_postage(self):
        self.client.post('/cl-creates', data=self.form())
        order = self.Order.query.one()
        path = f'/admin/cl-creates/orders/{order.id}'
        label_path = path + '/shipping-label'
        self.assertEqual(self.client.get(label_path).status_code, 302)
        label = self.admin.get(label_path)
        self.assertEqual(label.status_code, 200)
        self.assertEqual(label.headers['Cache-Control'], 'no-store')
        self.assertIn(b'Alex Smith', label.data)
        self.assertIn(b'1 Test Road', label.data)
        self.assertIn(b'SW1A 1AA', label.data)
        self.assertNotIn(b'alex@example.com', label.data)
        self.assertNotIn(b'HELLO WORLD', label.data)
        self.assertIn(b'Print shipping address', self.admin.get(path + '?popup=1').data)
        order.fulfilment = 'collection'
        main.db.session.commit()
        self.assertEqual(self.admin.get(label_path).status_code, 404)
        self.assertNotIn(b'Print shipping address', self.admin.get(path + '?popup=1').data)

    def test_validation_and_paid_status(self):
        data = self.form()
        for changes in [dict(wording='ABCDEFGHIJKL'), dict(wording='A B C D'), dict(quantity='0'), dict(postcode='BT1 1AA')]:
            self.client.post('/cl-creates', data=dict(data, **changes))
            self.assertEqual(self.Order.query.count(), 0)
        self.assertEqual(self.client.post('/cl-creates', data={}).status_code, 400)
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        path = f'/admin/cl-creates/orders/{order.id}'
        token = self.admin_token()
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='0'))
        self.assertEqual(order.status, 'Under review')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://evil.example/invoice'))
        self.assertEqual(order.status, 'Under review')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://invoices.sumup.com/test'))
        self.assertEqual(order.status, 'Paid')
        self.assertEqual(float(order.paid), 16)
        self.admin.post(path, data=dict(csrf_token=token, status='Ready for collection', paid='16'))
        self.assertEqual(order.status, 'Paid')
        self.admin.post(path, data=dict(csrf_token=token, status='Shipped', paid='16'))
        self.assertEqual(order.status, 'Shipped')

    def test_settings_snapshot_and_email_failure(self):
        data = self.form()
        with patch.object(main, 'send_client_email', return_value=False):
            self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Message.query.one().result, 'Failed')
        token = self.admin_token()
        self.admin.post('/admin/cl-creates/settings', data=dict(csrf_token=token, price='8', postage='7',
                        subject='{order_number}: {status}', body='Hello {first_name}'))
        self.assertEqual(float(self.Order.query.one().total), 16)
        data = self.form()
        data['fulfilment'] = 'collection'
        self.client.post('/cl-creates', data=data)
        self.assertEqual(float(self.Order.query.order_by(self.Order.id.desc()).first().total), 16)
        self.assertEqual(self.Message.query.order_by(self.Message.id.desc()).first().result, 'Disabled')
        for path in ['/admin/cl-creates', '/admin/cl-creates/settings', '/admin/cl-creates/communications']:
            self.assertEqual(main.app.test_client().get(path).status_code, 302)

    def image_file(self, name='headband.png'):
        from PIL import Image
        output = BytesIO()
        Image.new('RGB', (30, 30), 'pink').save(output, 'PNG')
        output.seek(0)
        return output, name

    def test_image_library_upload_visibility_and_delete(self):
        token = self.admin_token()
        path = '/admin/cl-creates/images'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.post(path, data={'action': 'delete'}).status_code, 400)
        response = self.admin.post(path, data=dict(csrf_token=token, action='upload',
                                   images=[self.image_file(), self.image_file('example.png')]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.Image.query.count(), 2)
        image = self.Image.query.order_by(self.Image.id).first()
        image_path = f'/cl-creates/library/{image.id}'
        self.assertEqual(self.client.get(image_path).mimetype, 'image/jpeg')
        self.assertIn(b'headband', self.client.get('/cl-creates').data)
        self.admin.post(path, data=dict(csrf_token=token, action='update', image_id=image.id, name='Private example'))
        self.assertEqual(self.client.get(image_path).status_code, 404)
        self.assertEqual(self.admin.get(image_path).status_code, 200)
        self.assertNotIn(b'Private example', self.client.get('/cl-creates').data)
        self.admin.post('/admin/cl-creates/settings', data=dict(csrf_token=token, action='product_image',
                        product_id=self.product.id, library_image=image.id))
        self.assertIsNotNone(self.product.image)
        image_id = image.id
        self.admin.post(path, data=dict(csrf_token=token, action='delete', image_id=image_id))
        self.assertIsNone(main.db.session.get(self.Image, image_id))
        self.assertIsNone(self.product.image)
        self.assertIsNotNone(main.db.session.get(self.Product, self.product.id))
        self.assertEqual(self.client.get(image_path).status_code, 404)

    def test_invalid_image_batch_is_not_partially_saved(self):
        token = self.admin_token()
        response = self.admin.post('/admin/cl-creates/images', data=dict(csrf_token=token, action='upload',
                                   images=[self.image_file(), (BytesIO(b'not an image'), 'fake.png')]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Upload a valid', response.data)
        self.assertEqual(self.Image.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
