import base64
import json
import unittest
from unittest.mock import patch
from pywebpush import WebPushException
import test_booking_messages as fixtures
from phone_push import valid_subscription

main = fixtures.main
Subscription,Delivery = main.phone_push_models

def subscription(endpoint='https://fcm.googleapis.com/fcm/send/test'):
    encode=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
    return dict(endpoint=endpoint,keys=dict(p256dh=encode(b'\x04'+b'x'*64),auth=encode(b'x'*16)))

class PhonePushTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BookingMessagesTest(); self.fixture.setUp()
        self.admin,self.client=self.fixture.admin,self.fixture.client
        self.previous={key:main.app.config.get(key) for key in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT')}
        main.app.config.update(VAPID_PUBLIC_KEY='public',VAPID_PRIVATE_KEY='private',VAPID_SUBJECT='mailto:test@example.com')
    def tearDown(self):
        main.app.config.update(self.previous); self.fixture.tearDown()
    def enable(self,client,role,endpoint,preferences=None):
        path=f'/{role}/phone-notifications'
        csrf=client.get(path).json['csrf']
        return client.post(path,json=dict(subscription=subscription(endpoint),preferences=preferences or ['bookings','messages','payments','updates']),headers={'X-CSRF-Token':csrf})
    def test_subscription_security_and_preferences(self):
        self.assertEqual(main.app.test_client().get('/client/phone-notifications').status_code,401)
        self.assertEqual(self.client.post('/client/phone-notifications',json={}).status_code,400)
        for endpoint in ['http://fcm.googleapis.com/test','https://localhost/test','https://fcm.googleapis.com.evil.example/test','https://127.0.0.1/test','https://fcm.googleapis.com:443@evil.example/test']:
            with self.assertRaises(ValueError): valid_subscription(subscription(endpoint))
        valid_subscription(subscription('https://wns2-db5p.notify.windows.com/test'))
        valid_subscription(subscription('https://web.push.apple.com/test'))
        self.assertEqual(self.enable(self.admin,'admin','https://fcm.googleapis.com/test').status_code,200)
        self.assertEqual(Subscription.query.count(),1)
        response=self.admin.get('/admin/notifications')
        self.assertIn(b'Phone notifications',response.data)
        response=self.admin.get('/phone-push-worker.js')
        self.assertEqual(response.status_code,200); response.close()
    def test_booking_payment_preferences_and_disable(self):
        self.enable(self.admin,'admin','https://fcm.googleapis.com/admin',['bookings'])
        self.enable(self.client,'client','https://fcm.googleapis.com/client',['bookings','payments'])
        self.fixture.fixture.fixture.booking(self.fixture.fixture.account.email)
        self.assertEqual(Delivery.query.count(),2)
        main.db.session.query(Delivery).delete(); main.db.session.commit()
        from datetime import date
        Entry=main.tool_models[1]
        main.db.session.add(Entry(booking_id=self.fixture.booking.id,token='push-test-payment',
            amount=20,kind='payment',method='cash',paid_date=date.today()))
        main.db.session.commit()
        self.assertEqual(Delivery.query.count(),1)
        self.assertTrue(db_owner(Delivery.query.one()).startswith('client:'))
        csrf=self.client.get('/client/phone-notifications').json['csrf']
        self.assertEqual(self.client.delete('/client/phone-notifications',json={'subscription':subscription('https://fcm.googleapis.com/admin')},headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertTrue(Subscription.query.filter_by(owner='admin').one().enabled)
        self.client.delete('/client/phone-notifications',json={'subscription':subscription('https://fcm.googleapis.com/client')},headers={'X-CSRF-Token':csrf})
        self.assertEqual(Delivery.query.count(),0)
    def test_messages_commit_queue_retry_and_no_private_text(self):
        self.enable(self.admin,'admin','https://fcm.googleapis.com/admin')
        self.enable(self.client,'client','https://fcm.googleapis.com/client')
        data=self.fixture.data(self.client,self.fixture.client_path,'Very private message')
        for _ in range(2): self.client.post(self.fixture.client_path,data=data)
        self.assertEqual(Delivery.query.count(),1)
        item=Delivery.query.one()
        self.assertEqual(db_owner(item),'admin')
        self.assertNotIn('Very private',item.payload)
        with patch('pywebpush.webpush',side_effect=WebPushException('unavailable')):
            main.app.extensions['phone_push_deliver']()
        self.assertEqual(Delivery.query.one().attempts,1)
        from datetime import datetime,timedelta
        Delivery.query.one().due_at=datetime.utcnow()-timedelta(seconds=1); main.db.session.commit()
        with patch('pywebpush.webpush') as send:
            main.app.extensions['phone_push_deliver']()
            self.assertEqual(send.call_count,1)
        self.assertEqual(Delivery.query.count(),0)
        self.admin.post(self.fixture.admin_path,data=self.fixture.data(self.admin,self.fixture.admin_path))
        self.assertEqual(db_owner(Delivery.query.one()),'client:'+self.fixture.fixture.account.email)
    def test_rollback_and_disable_delete_pending_and_expired_endpoint(self):
        self.enable(self.admin,'admin','https://fcm.googleapis.com/admin')
        message=main.BookingMessage(booking_id=self.fixture.booking.id,sender='client',body='test',submission_key='rollback')
        main.db.session.add(message); main.db.session.flush()
        self.assertEqual(Delivery.query.count(),1)
        main.db.session.rollback()
        self.assertEqual(Delivery.query.count(),0)
        self.client.post(self.fixture.client_path,data=self.fixture.data(self.client,self.fixture.client_path))
        response=type('Response',(),{'status_code':410})()
        with patch('pywebpush.webpush',side_effect=WebPushException('gone',response=response)):
            main.app.extensions['phone_push_deliver']()
        self.assertFalse(Subscription.query.one().enabled)
        self.assertEqual(Delivery.query.count(),0)

def db_owner(item):
    return main.db.session.get(Subscription,item.subscription_id).owner
