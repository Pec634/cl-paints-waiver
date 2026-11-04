import unittest
from io import BytesIO
from unittest.mock import patch
import test_client_portal as fixtures
import test_native_form_browser as browser_helpers

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
    browser = browser_helpers.NativeFormBrowserTest.browser
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

    def test_customer_search_groups_full_history_without_merging_names(self):
        saved=[]
        for email in ['alex@example.com','alex@example.com','another@example.com']:
            data=self.form();data['email']=email
            self.client.post('/cl-creates',data=data)
            saved.append(self.Order.query.order_by(self.Order.id.desc()).first())
        saved[1].email='Alex@Example.com'
        saved[1].first_name='Alexander'
        main.db.session.commit()
        for search in [saved[0].number,'alex@example.com','Alexander']:
            response=self.admin.get('/admin/cl-creates',query_string={'q':search})
            self.assertEqual(response.status_code,200)
            self.assertIn(saved[0].number.encode(),response.data)
            self.assertIn(saved[1].number.encode(),response.data)
            self.assertNotIn(saved[2].number.encode(),response.data)
            self.assertEqual(response.data.count(b'class="creates-customer-heading"'),1)
            self.assertIn(b'2 orders',response.data)
        response=self.admin.get('/admin/cl-creates',query_string={'q':'Smith'})
        self.assertEqual(response.data.count(b'class="creates-customer-heading"'),2)
        self.assertEqual(self.admin.get('/admin/cl-creates').status_code,200)

    def form(self):
        self.assertEqual(self.client.get('/cl-creates').status_code, 200)
        with self.client.session_transaction() as session:
            return dict(csrf_token=session['creates_csrf'], submission_token=session['creates_submission'],
                        first_name='Alex', last_name='Smith', email='alex@example.com', fulfilment='postage',
                        address_line1='1', address_street='Test Road', town='London', county='Greater London', country='United Kingdom', postcode='SW1A 1AA', mainland='on',
                        consent='on', custom_order_declaration='yes', product=str(self.product.id), wording='HELLO WORLD', word_shape='Heart', quantity='2')

    def test_colour_and_glitter_saved_for_each_headband(self):
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BLUE', 'MY PARTY'], word_shape=['Heart', ''], quantity=['2', '1'],
                    colour=['Blue', 'Pink'], letter_finish=['Plain', 'Glitter'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        order = self.Order.query.one()
        self.assertEqual([item['colour'] for item in order.items], ['Blue', 'Pink'])
        self.assertEqual([item['letter_finish'] for item in order.items], ['Plain', 'Glitter'])
        self.assertEqual(float(order.total), 21)
        self.assertIn(b'Glitter', response.data)
        self.assertIn(b'Pink', self.admin.get(f'/admin/cl-creates/orders/{order.id}').data)

    def test_invalid_colour_or_finish_is_rejected(self):
        for colour, finish in [('Unknown', 'Plain'), ('Black', 'Unknown')]:
            data = self.form()
            data.update(colour=colour, letter_finish=finish)
            self.client.post('/cl-creates', data=data)
            self.assertEqual(self.Order.query.count(), 0)

    def test_admin_manages_colours_and_glitter_letter_choices(self):
        token = self.admin_token()
        path = '/admin/cl-creates/colours'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.post(path, data={'kind':'headband','action':'add','name':'Orange'}).status_code, 400)
        for kind, colour in [('headband','Orange'), ('glitter','Rose gold')]:
            response = self.admin.post(path, data={'csrf_token':token,'kind':kind,'action':'add','name':colour})
            self.assertEqual(response.status_code, 302)
            self.assertIn(colour.encode(), self.client.get('/cl-creates').data)
        data = self.form()
        data.update(colour='Orange', letter_finish='Glitter', glitter_colour='Rose gold')
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['glitter_colour'], 'Rose gold')
        self.admin.post(path, data={'csrf_token':token,'kind':'glitter','action':'remove','name':'Rose gold'})
        data = self.form()
        data.update(colour='Orange', letter_finish='Glitter', glitter_colour='Rose gold')
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        self.assertEqual(order.items[0]['glitter_colour'], 'Rose gold')

    def test_admin_manages_word_shapes_and_orders_preserve_selection(self):
        token = self.admin_token()
        path = '/admin/cl-creates/shapes'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.admin.post(path, data={'csrf_token':token,'action':'add','name':'Butterfly'})
        self.assertIn(b'Butterfly', self.client.get('/cl-creates').data)
        data = self.form()
        data.update(word_shape='Butterfly')
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertIn(b'Separator: Butterfly', response.data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['word_shape'], 'Butterfly')
        self.admin.post(path, data={'csrf_token':token,'action':'remove','name':'Butterfly'})
        data = self.form()
        data.update(word_shape='Butterfly')
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        self.assertEqual(order.items[0]['word_shape'], 'Butterfly')

    def test_custom_order_refund_declaration_is_required_and_saved(self):
        data = self.form()
        data.pop('custom_order_declaration')
        page = self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 0)
        self.assertIn(b'Please read and acknowledge', page.data)
        data['custom_order_declaration'] = 'yes'
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertIn('change of mind', order.acknowledgement)
        self.assertIn('statutory rights', order.acknowledgement)

    def admin_token(self):
        self.assertEqual(self.admin.get('/admin/cl-creates').status_code, 200)
        with self.admin.session_transaction() as session:
            return session['creates_csrf']

    def review_order(self):
        order = self.Order(first_name='Delete', last_name='Test', email='delete@example.com',
            address='Test address', fulfilment='collection', items_json='[]', total=10, paid=0,
            status='Under review')
        main.db.session.add(order)
        main.db.session.commit()
        return order

    def test_delete_review_order_removes_communications_and_preserves_other_orders(self):
        order = self.review_order()
        other = self.review_order()
        order_id, other_id = order.id, other.id
        main.db.session.add(self.Message(order_id=order_id, subject='Test', body='Message', result='sent'))
        main.db.session.commit()
        token = self.admin_token()
        path = f'/admin/cl-creates/orders/{order_id}'
        self.assertIn(b'Delete order', self.admin.get(path+'?popup=1').data)
        response = self.admin.post(path, data=dict(csrf_token=token, action='delete', confirm_delete='yes'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('deleted=1', response.location)
        self.assertIsNone(main.db.session.get(self.Order, order_id))
        self.assertEqual(self.Message.query.filter_by(order_id=order_id).count(), 0)
        self.assertIsNotNone(main.db.session.get(self.Order, other_id))
        self.assertEqual(self.admin.get(path).status_code, 404)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_delete_order_layout_in_popup_and_standalone(self):
        order = self.review_order()
        for width, popup in ((1280, ''), (390, '?popup=1')):
            page = self.admin.get(f'/admin/cl-creates/orders/{order.id}'+popup)
            self.browser(page.data, '''
                const section = document.querySelector('.creates-order-delete');
                assert(!section.open, 'Delete section should start collapsed');
                section.querySelector('summary').click();
                const checkbox = section.querySelector('[name=confirm_delete]');
                assert(checkbox.offsetWidth === 20 && checkbox.offsetHeight === 20, 'Checkbox should have normal dimensions');
                const button = section.querySelector('button');
                assert(button.offsetWidth < section.clientWidth, 'Delete button should be compact');
                const bounds = button.getBoundingClientRect();
                assert(bounds.left >= 0 && bounds.right <= innerWidth, 'Delete button should fit the viewport');
                assert(!section.querySelector('form').checkValidity(), 'Confirmation must still be required');
                checkbox.click();
                assert(section.querySelector('form').checkValidity(), 'Checked confirmation should validate');
                assert(section.querySelector('form').target === '_top', 'Popup deletion should return to full order list');
            ''', width=width)

    def test_delete_requires_admin_csrf_confirmation_and_unpaid_review_status(self):
        order = self.review_order()
        token = self.admin_token()
        path = f'/admin/cl-creates/orders/{order.id}'
        data = dict(csrf_token=token, action='delete', confirm_delete='yes')
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.assertEqual(self.admin.post(path, data=dict(data, csrf_token='bad')).status_code, 400)
        response = self.admin.post(path, data=dict(data, confirm_delete=''))
        self.assertIn(b'Confirm that you want', response.data)
        for field, value in [('paid', 1), ('status', 'Paid'), ('status', 'In production'),
                             ('invoice_url', 'https://pay.sumup.com/test'), ('invoice_reference', '2026-001')]:
            original = getattr(order, field)
            setattr(order, field, value)
            main.db.session.commit()
            response = self.admin.post(path, data=data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(main.db.session.get(self.Order, order.id))
            self.assertNotIn(b'name="action" value="delete"', response.data)
            setattr(order, field, original)
            main.db.session.commit()

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
        confirmation = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertIn(b'href="/services">&larr; Back</a>', confirmation.data)
        for destination in ['https://example.com', '//example.com', '/\\example.com']:
            fallback = self.client.get('/cl-creates', query_string={'return_to': destination})
            self.assertIn(b'href="/">&larr; Back</a>', fallback.data)
        self.fixture.signup()
        portal = self.client.get('/cl-creates', query_string={'return_to': '/client/bookings'})
        self.assertIn(b'href="/client/bookings">&larr; Back</a>', portal.data)

    def test_order_totals_duplicate_and_private_details(self):
        data = self.form()
        data.update(product=[str(self.product.id)] * 2, wording=['HELLO WORLD', 'A B C'], word_shape=['Heart','Star'], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertNotIn(b'O-000001', response.data)
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
        self.assertEqual(self.Message.query.count(), 0)
        for search in ['O-000001', 'Alex Smith', 'alex@example.com', 'Test Road']:
            self.assertIn(b'O-000001', self.admin.get('/admin/cl-creates', query_string={'q': search}).data)

    def test_custom_order_form_works_without_catalogue_products(self):
        main.db.session.delete(self.product)
        main.db.session.commit()
        page = self.client.get('/cl-creates')
        self.assertIn(b'id="creates-form"', page.data)
        self.assertIn(b'Order your custom headbands', page.data)
        self.assertIn(b'More items coming soon', page.data)
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BRIDE', 'BRIDE SQUAD'], word_shape=['Heart',''], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertNotIn(b'O-000001', response.data)
        order = self.Order.query.one()
        self.assertEqual(float(order.total), 31)
        self.assertEqual([item['wording'] for item in order.items], ['TEAM BRIDE', 'BRIDE SQUAD'])
        self.assertEqual(order.status, 'Awaiting payment')

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

    def test_seven_character_single_word_is_accepted(self):
        data = self.form()
        data['wording'] = 'PAINTER'
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.one().items[0]['wording'], 'PAINTER')

    def test_postage_is_per_five_headbands_across_all_designs(self):
        for quantity, expected in [(1, 11), (5, 31), (6, 42), (7, 47), (10, 62), (11, 73)]:
            with self.subTest(quantity=quantity):
                data = self.form()
                data['quantity'] = str(quantity)
                response = self.client.post('/cl-creates', data=data)
                self.assertEqual(response.status_code, 302)
                order = self.Order.query.order_by(self.Order.id.desc()).first()
                self.assertEqual(float(order.total), expected)
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BLUE', 'TEAM PINK'],
                    word_shape=['', ''], quantity=['3', '4'])
        self.client.post('/cl-creates', data=data)
        self.assertEqual(float(self.Order.query.order_by(self.Order.id.desc()).first().total), 47)

    def test_postage_preview_counts_boxes_across_designs(self):
        self.browser(self.client.get('/cl-creates').data, '''
            const quantity = document.querySelector('[name=quantity]');
            const summary = document.getElementById('creates-total');
            quantity.value = '5'; input(quantity);
            assert(summary.textContent.includes('£31.00') && summary.textContent.includes('for 1 box,'), 'Five headbands use one box');
            quantity.value = '7'; input(quantity);
            assert(summary.textContent.includes('£47.00') && summary.textContent.includes('for 2 boxes,'), 'Seven headbands use two boxes');
            document.getElementById('add-line').click();
            const second = document.querySelectorAll('[name=quantity]')[1];
            second.value = '4'; input(second);
            assert(summary.textContent.includes('£73.00') && summary.textContent.includes('for 3 boxes,'), 'All designs share the box count');
            document.querySelectorAll('.remove-line')[1].click();
            assert(summary.textContent.includes('£47.00'), 'Removing a design recalculates postage');
        ''')

    def test_validation_and_paid_status(self):
        data = self.form()
        for changes in [dict(wording='ABCDEF'), dict(wording='A B C D'), dict(quantity='0'), dict(postcode='BT1 1AA')]:
            self.client.post('/cl-creates', data=dict(data, **changes))
            self.assertEqual(self.Order.query.count(), 0)
        self.assertEqual(self.client.post('/cl-creates', data={}).status_code, 400)
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        path = f'/admin/cl-creates/orders/{order.id}'
        token = self.admin_token()
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='0'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://evil.example/invoice'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://invoices.sumup.com/test'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.assertEqual(float(order.paid), 0)
        order.paid=16;order.status='Paid';main.db.session.commit()
        self.admin.post(path, data=dict(csrf_token=token, status='Ready for collection', paid='16'))
        self.assertEqual(order.status, 'Paid')
        self.admin.post(path, data=dict(csrf_token=token, status='Shipped', paid='16'))
        self.assertEqual(order.status, 'Shipped')

    def test_settings_snapshot_and_email_failure(self):
        data = self.form()
        with patch.object(main, 'send_client_email', return_value=False):
            self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Message.query.count(), 0)
        token = self.admin_token()
        self.admin.post('/admin/cl-creates/settings', data=dict(csrf_token=token, price='8', postage='7',
                        subject='{order_number}: {status}', body='Hello {first_name}'))
        self.assertEqual(float(self.Order.query.one().total), 16)
        data = self.form()
        data['quantity'] = '2'
        self.client.post('/cl-creates', data=data)
        self.assertEqual(float(self.Order.query.order_by(self.Order.id.desc()).first().total), 23)
        self.assertEqual(self.Message.query.count(), 0)
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
