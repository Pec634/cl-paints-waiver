"""New moodboard checkout is removed; old payments remain verifiable."""
import os
import unittest
from unittest.mock import patch
import test_client_portal as fixtures
main=fixtures.main

class MoodboardPaymentTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ClientPortalTest();self.fixture.setUp();self.client=self.fixture.client
        self.env=patch.dict(os.environ,{'SUMUP_API_KEY':'test','SUMUP_MERCHANT_CODE':'TEST'});self.env.start()
        self.event=main.Event(name='Test fair',status='Open');main.db.session.add(self.event);main.db.session.flush()
        image=main.MoodboardImage(title='Butterfly',image_url='https://example.com/design.png',active=True,design_type='small')
        main.db.session.add(image);main.db.session.flush()
        main.db.session.add(main.EventMoodboardImage(event_id=self.event.id,image_id=image.id));main.db.session.commit()
    def tearDown(self):
        self.env.stop();self.fixture.tearDown()
    def legacy(self):
        order=main.MoodboardOrder(event_id=self.event.id,token='old-order-token',items=[],amount=12,merchant='TEST',provider_id='abc123')
        main.db.session.add(order);main.db.session.commit();return order
    def test_new_checkout_removed_without_provider_call(self):
        page=self.client.get(f'/moodboard/event/{self.event.id}')
        self.assertIn(b'View larger',page.data);self.assertIn(b'Download entire moodboard',page.data)
        self.assertNotIn(b'Review basket',page.data)
        with patch('moodboard_payments.provider_request') as provider:
            response=self.client.post(f'/moodboard/event/{self.event.id}/pay',data={'quantity_1':1})
        self.assertEqual(response.status_code,410);provider.assert_not_called()
        self.assertEqual(main.MoodboardOrder.query.count(),0)
    def test_legacy_callback_requires_matching_provider_details(self):
        order=self.legacy()
        data=dict(id='abc123',checkout_reference='MB-'+order.token,merchant_code='TEST',currency='GBP',amount='12.00',status='PAID')
        with patch('moodboard_payments.provider_request',return_value=dict(data,amount='0.01')):
            response=self.client.post(f'/moodboard/payment/{order.token}/callback')
        self.assertEqual(response.status_code,503);self.assertFalse(order.paid)
        with patch('moodboard_payments.provider_request',return_value=data):
            response=self.client.post(f'/moodboard/payment/{order.token}/callback')
        self.assertEqual(response.status_code,200);self.assertTrue(order.paid)
    def test_legacy_history_requires_admin(self):
        self.legacy();path=f'/admin/events/{self.event.id}/moodboard/orders'
        self.assertEqual(self.client.get(path).status_code,302)
        with self.client.session_transaction() as state:state['admin_authenticated']=True
        page=self.client.get(path);self.assertEqual(page.status_code,200)
        self.assertIn(b'New moodboard payments have been removed',page.data)
