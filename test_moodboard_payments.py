import os
import re
from html import unescape
import unittest
from decimal import Decimal
from unittest.mock import patch
import test_client_portal as fixtures

main = fixtures.main


class MoodboardPaymentTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.env = patch.dict(os.environ, {'SUMUP_API_KEY': 'test', 'SUMUP_MERCHANT_CODE': 'TEST'})
        self.env.start()
        self.event = main.Event(name='Test fair', status='Open')
        main.db.session.add(self.event)
        main.db.session.flush()
        self.images = []
        for size in ('small', 'large'):
            image = main.MoodboardImage(title='Internal name', image_url='https://example.com/design.png', design_type=size)
            main.db.session.add(image)
            main.db.session.flush()
            main.db.session.add(main.EventMoodboardImage(event_id=self.event.id, image_id=image.id))
            self.images.append(image)
        main.db.session.commit()
        self.client.get(f'/moodboard/event/{self.event.id}')
        with self.client.session_transaction() as state:
            self.data = dict(csrf_token=state['client_csrf'], basket_token=state[f'moodboard_basket_{self.event.id}'])
        self.data.update({f'quantity_{self.images[0].id}': '2', f'quantity_{self.images[1].id}': '1', 'amount': '0.01'})

    def tearDown(self):
        self.env.stop()
        self.fixture.tearDown()

    def provider(self, path, payload=None):
        order = main.MoodboardOrder.query.one()
        data = dict(id='abc123', checkout_reference='MB-' + order.token, merchant_code='TEST', currency='GBP',
                    amount=str(order.amount), status='PENDING', hosted_checkout_url='https://checkout.sumup.com/pay/abc123')
        return [data] if path.startswith('checkouts?') else data

    def create(self):
        review = self.client.post(f'/moodboard/event/{self.event.id}/pay', data=self.data)
        self.assertEqual(review.status_code, 200)
        self.data['review_token'] = unescape(re.search(r'name="review_token" value="([^"]+)"', review.get_data(as_text=True)).group(1))
        with patch('moodboard_payments.provider_request', side_effect=self.provider) as api:
            response = self.client.post(f'/moodboard/event/{self.event.id}/pay', data=self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, 'https://checkout.sumup.com/pay/abc123')
        self.assertEqual(api.call_args_list[0].args[1]['amount'], 12.0)
        return main.MoodboardOrder.query.one()

    def test_basket_prices_snapshot_and_duplicate_submission(self):
        order = self.create()
        self.assertEqual(order.amount, Decimal('12.00'))
        self.assertEqual([item['label'] for item in order.items], ['S - 1', 'L - 1'])
        self.assertEqual([item['quantity'] for item in order.items], [2, 1])
        with patch('moodboard_payments.provider_request') as api:
            self.client.post(f'/moodboard/event/{self.event.id}/pay', data=self.data)
            api.assert_not_called()
        self.assertEqual(main.MoodboardOrder.query.count(), 1)
        self.assertFalse(order.paid)

    def test_provider_verified_callback_and_tampering(self):
        order = self.create()
        path = f'/moodboard/payment/{order.token}/callback'
        data = self.provider('checkouts/abc123')
        data['status'] = 'PAID'
        for field, wrong in [('amount', '1'), ('currency', 'EUR'), ('merchant_code', 'OTHER'), ('checkout_reference', 'WRONG'), ('id', 'def456')]:
            with patch('moodboard_payments.provider_request', return_value=dict(data, **{field: wrong})):
                self.assertEqual(self.client.post(path, json={'status': 'PAID'}).status_code, 503)
                self.assertFalse(main.db.session.get(main.MoodboardOrder, order.id).paid)
        with patch('moodboard_payments.provider_request', return_value=data):
            self.assertEqual(self.client.post(path).json['status'], 'PAID')
            self.assertEqual(self.client.post(path).json['status'], 'PAID')
        page = self.client.get(f'/moodboard/payment/{order.token}')
        self.assertIn(b'Payment confirmed', page.data)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')

    def test_closed_event_invalid_quantities_and_csrf(self):
        path = f'/moodboard/event/{self.event.id}/pay'
        self.assertEqual(self.client.post(path).status_code, 400)
        for invalid in ('-1', '21', '1.5'):
            data = dict(self.data, **{f'quantity_{self.images[0].id}': invalid})
            self.assertEqual(self.client.post(path, data=data).status_code, 400)
        self.assertEqual(self.client.post(path, data=dict(self.data, quantity_99999='1')).status_code, 409)
        self.event.status = 'Closed'
        main.db.session.commit()
        self.assertEqual(self.client.post(path, data=self.data).status_code, 409)
        self.assertEqual(main.MoodboardOrder.query.count(), 0)

    def test_ambiguous_creation_preserves_order_and_does_not_retry_charge(self):
        path = f'/moodboard/event/{self.event.id}/pay'
        review = self.client.post(path, data=self.data)
        self.data['review_token'] = unescape(re.search(r'name="review_token" value="([^"]+)"', review.get_data(as_text=True)).group(1))
        with patch('moodboard_payments.provider_request', side_effect=ValueError('Unavailable')) as api:
            response = self.client.post(path, data=self.data)
            self.assertEqual(response.status_code, 302)
            self.client.post(path, data=self.data)
            self.assertEqual(api.call_count, 1)
        self.assertEqual(main.MoodboardOrder.query.count(), 1)

    def admin(self):
        with self.client.session_transaction() as state:
            state['admin_authenticated'] = True

    def test_review_creates_no_payment_and_price_changes_require_new_review(self):
        path = f'/moodboard/event/{self.event.id}/pay'
        with patch('moodboard_payments.provider_request') as api:
            page = self.client.post(path, data=self.data)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Review your designs', page.data)
            self.assertEqual(main.MoodboardOrder.query.count(), 0)
            token = unescape(re.search(r'name="review_token" value="([^"]+)"', page.get_data(as_text=True)).group(1))
            main.db.session.add(main.BusinessSetting(key='moodboard_price_small', value='4.00'))
            main.db.session.commit()
            page = self.client.post(path, data=dict(self.data, review_token=token))
            self.assertIn(b'updated summary', page.data)
            self.assertEqual(main.MoodboardOrder.query.count(), 0)
            api.assert_not_called()

    def test_pause_blocks_stale_baskets_and_keeps_gallery_visible(self):
        route = f'/admin/events/{self.event.id}/moodboard/payments'
        self.assertEqual(self.client.post(route).status_code, 302)
        self.admin()
        self.assertEqual(self.client.post(route, data={'action': 'pause'}).status_code, 400)
        self.client.post(route, data={'csrf_token': self.data['csrf_token'], 'action': 'pause'})
        page = self.client.get(f'/moodboard/event/{self.event.id}')
        self.assertIn(b'Online orders are paused', page.data)
        self.assertIn(b'View larger', page.data)
        self.assertNotIn(b'data-add-design=', page.data)
        self.assertEqual(self.client.post(f'/moodboard/event/{self.event.id}/pay', data=self.data).status_code, 409)
        self.client.post(route, data={'csrf_token': self.data['csrf_token'], 'action': 'resume'})
        self.assertIn(b'Review basket', self.client.get(f'/moodboard/event/{self.event.id}').data)

    def test_fulfilment_requires_paid_order_and_rejects_stale_updates(self):
        order = self.create()
        self.admin()
        route = f'/admin/events/{self.event.id}/moodboard/orders/{order.id}/fulfilment'
        data = {'csrf_token': self.data['csrf_token'], 'expected': 'Waiting', 'status': 'Being painted'}
        self.assertEqual(self.client.post(route, data=data).status_code, 409)
        order.paid = True
        main.db.session.commit()
        self.assertEqual(self.client.post(route, data=data).status_code, 302)
        self.assertEqual(self.client.post(route, data=data).status_code, 409)
        data.update(expected='Being painted', status='Completed')
        self.assertEqual(self.client.post(route, data=data).status_code, 302)
        self.assertEqual(self.client.post(route, data=data).status_code, 409)
        page = self.client.get(f'/moodboard/payment/{order.token}')
        self.assertIn(b'All paints in this order have been completed', page.data)

    def test_group_labels_and_controls(self):
        page = self.client.get(f'/moodboard/event/{self.event.id}')
        for label in (b'S - 1', b'L - 1', b'quantity-badge', b'data-adjust-design', b'design-preview', b'moodboard-sticky-basket'):
            self.assertIn(label, page.data)

    def test_paused_event_still_verifies_existing_payment(self):
        order = self.create()
        main.db.session.add(main.BusinessSetting(key=f'moodboard_paused_{self.event.id}', value='1'))
        main.db.session.commit()
        data = self.provider('checkouts/abc123')
        data['status'] = 'PAID'
        with patch('moodboard_payments.provider_request', return_value=data):
            response = self.client.post(f'/moodboard/payment/{order.token}/callback')
        self.assertEqual(response.json['status'], 'PAID')
        self.assertTrue(main.db.session.get(main.MoodboardOrder, order.id).paid)

    def test_schema_upgrade_keeps_existing_orders_and_is_repeatable(self):
        from types import SimpleNamespace
        from sqlalchemy import create_engine, text
        from moodboard_payments import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE moodboard_order (id INTEGER PRIMARY KEY, paid BOOLEAN)'))
                connection.execute(text('INSERT INTO moodboard_order (id, paid) VALUES (1, 1)'))
            ensure_schema(SimpleNamespace(engine=engine))
            ensure_schema(SimpleNamespace(engine=engine))
            with engine.connect() as connection:
                row = connection.execute(text('SELECT paid, fulfilment, fulfilment_updated_at FROM moodboard_order WHERE id=1')).one()
                self.assertEqual(tuple(row), (1, 'Waiting', None))
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
