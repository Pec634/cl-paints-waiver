from datetime import date, datetime
from decimal import Decimal
import os
import unittest
from unittest.mock import patch
import test_business_tools as fixtures

main=fixtures.main
Plan,Entry,*_=main.tool_models
Checkout=main.SumupCheckout


class SumupCheckoutTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp()
        self.booking=self.fixture.booking;self.client=self.fixture.client;self.admin=self.fixture.admin
        with self.admin.session_transaction() as state:
            state['admin_last_activity']=datetime.utcnow().timestamp()
            state['client_csrf']='admin-payment-token'
        self.booking.status='Awaiting Payment'
        main.db.session.add(Plan(booking_id=self.booking.id,deposit=Decimal('50')));main.db.session.commit()
        self.client.get(f'/client/bookings/{self.booking.id}')
        with self.client.session_transaction() as state:self.csrf=state['client_csrf']
        self.env=patch.dict(os.environ,{'SUMUP_API_KEY':'test-key','SUMUP_MERCHANT_CODE':'TEST-MERCHANT'});self.env.start()
        main.BusinessSetting.query.filter_by(key='public_app_url').delete()
        main.db.session.add(main.BusinessSetting(key='public_app_url',value='https://example.com'));main.db.session.commit()

    def tearDown(self):self.env.stop();self.fixture.tearDown()

    def provider_data(self,row,status='PAID',**changes):
        return dict(id=row.provider_id,checkout_reference=row.reference,merchant_code=row.merchant,amount=str(row.amount),currency='GBP',status=status,**changes)

    def create(self, *, hosted=False):
        def response(path,payload=None):
            if hosted:
                return dict(id='abc123',hosted_checkout_url='https://checkout.sumup.com/pay/abc123')
            return dict(id='abc123')
        with patch('sumup_checkout.provider_request',side_effect=response) as api:
            if hosted:
                response=self.admin.post(f'/admin/bookings/{self.booking.id}/online-payment',
                    data=dict(csrf_token='admin-payment-token',purpose='Deposit',amount='1'))
            else:
                response=self.client.post(f'/client/bookings/{self.booking.id}/pay',
                    data=dict(csrf_token=self.csrf,purpose='Deposit',amount='1'))
        row=Checkout.query.one()
        self.assertEqual(response.status_code,302)
        payload=api.call_args.args[1];self.assertEqual(payload['amount'],50.0)
        self.assertEqual(payload['currency'],'GBP')
        if hosted:
            self.assertEqual(row.payment_url,'https://checkout.sumup.com/pay/abc123')
            self.assertTrue(payload['hosted_checkout']['enabled'])
        else:
            self.assertEqual(response.location,f'/client/bookings/{self.booking.id}/pay/{row.id}')
            self.assertTrue(payload['redirect_url'].endswith(response.location+'?returned=1'))
            self.assertIn('valid_until',payload)
            self.assertNotIn('hosted_checkout',payload)
        self.assertEqual(Entry.query.count(),0)
        return row

    def test_hosted_deposit_and_verified_callback_are_idempotent(self):
        row=self.create(hosted=True);route=f'/payments/sumup/callback/{row.token}'
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row,status='PENDING')) as api:
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay',
                data=dict(csrf_token=self.csrf,purpose='Deposit'))
        self.assertEqual(response.location,row.payment_url)
        api.assert_called_once_with('checkouts/'+row.provider_id)
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row)):
            self.assertTrue(self.client.post(route,json={'status':'FAILED'}).json['recorded'])
            self.assertTrue(self.client.post(route,json={'status':'PAID'}).json['recorded'])
        self.assertEqual(Entry.query.count(),1);self.assertEqual(Entry.query.one().amount,Decimal('50'))
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'],Decimal('50'))
        self.assertEqual(self.booking.status, 'Awaiting Payment', 'Payment must not automatically confirm or complete a booking')

    def test_pending_or_mismatched_provider_result_never_posts_money(self):
        row=self.create();route=f'/payments/sumup/callback/{row.token}'
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row,status='PENDING')):
            self.assertFalse(self.client.post(route,json={'status':'PAID'}).json['recorded'])
        for key,value in [('amount','1'),('merchant_code','OTHER'),('currency','EUR'),('checkout_reference','WRONG'),('id','WRONG')]:
            data=self.provider_data(row);data[key]=value
            with patch('sumup_checkout.provider_request',return_value=data):
                self.assertEqual(self.client.post(route).status_code,503)
        self.assertEqual(Entry.query.count(),0)

    def test_ownership_csrf_accepted_status_and_provider_failure(self):
        route=f'/client/bookings/{self.booking.id}/pay'
        data=dict(csrf_token=self.csrf,purpose='Deposit')
        self.assertEqual(main.app.test_client().post(route,data=data).status_code,404)
        self.assertEqual(self.client.post(route,data=dict(data,csrf_token='bad')).status_code,400)
        self.booking.status='Under Review';main.db.session.commit()
        with patch('sumup_checkout.provider_request') as api:self.client.post(route,data=data);api.assert_not_called()
        self.assertEqual(Checkout.query.count(),0)
        self.booking.status='Accepted';main.db.session.commit()
        with patch('sumup_checkout.provider_request',side_effect=ValueError('Provider unavailable')):
            self.client.post(route,data=data)
        self.assertEqual(Checkout.query.count(),1);self.assertEqual(Entry.query.count(),0)
        with patch('sumup_checkout.provider_request',return_value=[]):self.client.post(route,data=data)
        self.assertEqual(Checkout.query.count(),1,'unresolved checkout should prevent a duplicate payment attempt')

    def test_existing_pending_checkout_reused_without_second_charge_creation(self):
        row=self.create()
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row,status='PENDING')) as api:
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay',data=dict(csrf_token=self.csrf,purpose='Deposit'))
            self.assertEqual(response.location,f'/client/bookings/{self.booking.id}/pay/{row.id}')
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay',data=dict(csrf_token=self.csrf,purpose='Balance'))
            self.assertEqual(response.location,f'/client/bookings/{self.booking.id}')
            self.admin.post(f'/admin/bookings/{self.booking.id}/online-payment',data=dict(csrf_token='admin-payment-token',purpose='Deposit'))
        self.assertEqual(Checkout.query.count(),1)
        self.assertTrue(all(call.args[0].startswith('checkouts/') for call in api.call_args_list))
        path=f'/bookings/{self.booking.id}/online-payment/{row.id}/refresh'
        self.assertEqual(main.app.test_client().post(path,data=dict(csrf_token=self.csrf)).status_code,404)

    def test_widget_visible_only_while_awaiting_payment_and_verifies_banked_return(self):
        row=self.create()
        path=f'/client/bookings/{self.booking.id}/pay/{row.id}'
        self.assertEqual(main.app.test_client().get(path).status_code,404)
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row,status='PENDING')):
            page=self.client.get(path)
            self.assertIn(b'gateway/ecom/card/v2/sdk.js',page.data)
            self.assertIn(b'data-checkout-id="abc123"',page.data)
            self.assertIn(f'name="csrf_token" value="{self.csrf}"'.encode(), page.data)
            self.assertEqual(page.headers['Cache-Control'],'no-store')
            self.assertNotIn(b'booking-payment-checkmark', self.client.get(path+'?approved=1').data)
            self.assertEqual(self.client.get(path+'?returned=1').status_code,302)
        self.booking.status='Accepted'
        main.db.session.commit()
        with patch('sumup_checkout.provider_request') as api:
            self.assertEqual(self.client.get(path).status_code,302)
            api.assert_not_called()
        self.assertEqual(Entry.query.count(),0)
        data=self.provider_data(row, transaction_id='sale',
            transactions=[dict(id='sale', status='SUCCESSFUL', timestamp='2025-04-05T23:30:00Z')])
        with patch('sumup_checkout.provider_request',return_value=data):
            approved = self.client.get(path+'?returned=1')
            self.assertEqual(approved.status_code, 200)
            self.assertIn(b'Payment approved', approved.data)
            self.assertIn(b'booking-payment-checkmark', approved.data)
            self.assertNotIn(b'gateway/ecom/card/v2/sdk.js', approved.data)
        with patch('sumup_checkout.provider_request') as api:
            self.assertIn(b'Payment approved', self.client.get(path).data)
            self.assertEqual(main.app.test_client().get(path).status_code, 404)
            api.assert_not_called()
        self.assertEqual(Entry.query.count(),1)
        self.assertEqual(Entry.query.one().paid_date,date(2025,4,6))

    def test_widget_refresh_shows_approval_only_after_provider_verifies(self):
        row = self.create()
        refresh = f'/bookings/{self.booking.id}/online-payment/{row.id}/refresh'
        widget = f'/client/bookings/{self.booking.id}/pay/{row.id}'
        form = dict(csrf_token=self.csrf, return_to_checkout='yes')
        for data in (self.provider_data(row, status='PENDING'), self.provider_data(row, status='FAILED'),
                     {**self.provider_data(row), 'amount': '1.00'}):
            with patch('sumup_checkout.provider_request', return_value=data):
                response = self.client.post(refresh, data=form)
                self.assertEqual(response.location, f'/client/bookings/{self.booking.id}')
            self.assertEqual(Entry.query.count(), 0)
        with patch('sumup_checkout.provider_request', return_value=self.provider_data(row)) as api:
            response = self.client.post(refresh, data=form)
            self.assertEqual((response.status_code, response.location), (303, widget))
            approved = self.client.get(widget)
            api.assert_called_once()
        self.assertIn(b'Payment approved', approved.data)
        self.assertIn(b'50.00', approved.data)
        self.assertIn(b'CL Paints will confirm your booking', approved.data)
        self.assertNotIn(b'Your booking is confirmed.', approved.data)
        self.assertEqual(approved.headers['Cache-Control'], 'no-store')
        self.assertEqual(Entry.query.count(), 1)
        self.assertEqual(self.booking.status, 'Awaiting Payment')
        self.booking.status = 'Accepted'
        main.db.session.commit()
        self.assertIn(b'Your booking is confirmed.', self.client.get(widget).data)

    def test_confirmed_booking_uses_hosted_checkout(self):
        self.booking.status='Accepted'
        main.db.session.commit()
        hosted_url='https://checkout.sumup.com/pay/abc123'
        with patch('sumup_checkout.provider_request',return_value=dict(id='abc123',hosted_checkout_url=hosted_url)) as api:
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay', data=dict(csrf_token=self.csrf,purpose='Balance'))
        self.assertEqual(response.location,hosted_url)
        self.assertTrue(api.call_args.args[1]['hosted_checkout']['enabled'])

    def test_expired_widget_can_be_replaced_by_a_balance_checkout(self):
        row=self.create()
        expired=self.provider_data(row,status='EXPIRED')
        with patch('sumup_checkout.provider_request',side_effect=[expired,dict(id='def456')]) as api:
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay',
                data=dict(csrf_token=self.csrf,purpose='Balance'))
        new=Checkout.query.filter_by(purpose='Balance').one()
        self.assertEqual(response.location,f'/client/bookings/{self.booking.id}/pay/{new.id}')
        self.assertEqual(api.call_args.args[0],'checkouts')
        self.assertEqual(Entry.query.count(),0)

    def test_superseded_checkout_is_not_looked_up_again(self):
        old=self.create()
        path=f'/client/bookings/{self.booking.id}/pay'
        data=dict(csrf_token=self.csrf,purpose='Deposit')
        with patch('sumup_checkout.provider_request',side_effect=[self.provider_data(old,status='EXPIRED'),dict(id='def456')]):
            self.client.post(path,data=data)
        active=Checkout.query.filter_by(provider_id='def456').one()
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(active,status='PENDING')) as api:
            response=self.client.post(path,data=data)
        self.assertEqual(response.location,path+'/'+str(active.id))
        api.assert_called_once_with('checkouts/def456')

    def test_review_gate_applies_to_client_admin_and_invoice_links(self):
        main.db.session.add(main.BookingInvoice(booking_id=self.booking.id, reference='REVIEW-INVOICE',
            purpose='Deposit', amount=Decimal('50'), due_date=datetime.now().date(),
            payment_url='https://pay.sumup.com/review-invoice'))
        self.booking.status = 'Under Review'
        main.db.session.commit()
        route = f'/client/bookings/{self.booking.id}/pay'
        with self.admin.session_transaction() as state:
            state['client_csrf'] = 'review-token'
        with patch('sumup_checkout.provider_request') as api:
            for status in ('Under Review', 'Declined', 'Cancelled'):
                self.booking.status = status
                main.db.session.commit()
                self.client.post(route, data=dict(csrf_token=self.csrf, purpose='Deposit'))
                self.admin.post(f'/admin/bookings/{self.booking.id}/online-payment',
                    data=dict(csrf_token='review-token', purpose='Balance'))
                page = self.client.get(f'/client/bookings/{self.booking.id}').data
                self.assertNotIn(b'https://pay.sumup.com/review-invoice', page)
                self.assertNotIn(b'Pay remaining deposit</button>', page)
            api.assert_not_called()
        self.booking.status = 'Under Review'
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True):
            self.admin.post(f'/admin/bookings/{self.booking.id}/manage', data=dict(action='request_payment'))
        self.assertEqual(self.booking.status, 'Awaiting Payment')
        self.assertIn(b'Pay remaining deposit</button>', self.client.get(f'/client/bookings/{self.booking.id}').data)
        self.assertIn(self.booking.public_reference.encode(), self.admin.get('/admin/bookings?filter=payment').data)
        month = self.booking.event_date.strftime('%Y-%m')
        self.assertIn(self.booking.public_reference.encode(), self.admin.get('/admin/calendar?month='+month).data)
        self.assertIn(self.booking.public_reference.encode(), self.admin.get('/admin/payments').data)
        self.create()

    def test_confirmation_requires_review_and_recorded_deposit(self):
        path = f'/admin/bookings/{self.booking.id}/manage'
        self.admin.post(path, data=dict(action='accept'))
        self.assertEqual(self.booking.status, 'Awaiting Payment')
        row = self.create()
        with patch('sumup_checkout.provider_request', return_value=self.provider_data(row)):
            self.client.post(f'/payments/sumup/callback/{row.token}')
        self.assertEqual(self.booking.status, 'Awaiting Payment')
        self.booking.status = 'Under Review'
        main.db.session.commit()
        self.admin.post(path, data=dict(action='update', status='Accepted'))
        self.assertEqual(self.booking.status, 'Under Review', 'Payment alone cannot bypass admin review')
        with patch.object(main, 'send_client_email', return_value=True):
            self.admin.post(path, data=dict(action='request_payment'))
            self.admin.post(path, data=dict(action='accept'))
        self.assertEqual(self.booking.status, 'Accepted')
        self.assertIsNone(main.db.session.get(main.booking_lifecycle_models[2], self.booking.id))

    def test_no_deposit_requires_full_payment_and_completed_bookings_cannot_pay(self):
        plan = main.db.session.get(Plan, self.booking.id)
        plan.deposit = Decimal('0')
        main.db.session.add(Entry(booking_id=self.booking.id, token='partial-payment', amount=Decimal('50'),
            kind='payment', method='Cash', paid_date=datetime.now().date()))
        main.db.session.commit()
        path = f'/admin/bookings/{self.booking.id}/manage'
        self.admin.post(path, data=dict(action='accept'))
        self.assertEqual(self.booking.status, 'Awaiting Payment')
        main.db.session.add(Entry(booking_id=self.booking.id, token='remaining-payment', amount=Decimal('50'),
            kind='payment', method='Cash', paid_date=datetime.now().date()))
        main.db.session.commit()
        with patch.object(main, 'send_client_email', return_value=True):
            self.admin.post(path, data=dict(action='accept'))
        self.assertEqual(self.booking.status, 'Accepted')
        FollowUp = main.booking_lifecycle_models[2]
        main.db.session.add(FollowUp(booking_id=self.booking.id, completed_at=datetime.utcnow(), completed_by='admin'))
        main.db.session.commit()
        with patch('sumup_checkout.provider_request') as api:
            self.client.post(f'/client/bookings/{self.booking.id}/pay', data=dict(csrf_token=self.csrf, purpose='Balance'))
            api.assert_not_called()


if __name__=='__main__':unittest.main()
