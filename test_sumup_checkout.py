from datetime import datetime
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
        with self.admin.session_transaction() as state:state['admin_last_activity']=datetime.utcnow().timestamp()
        self.booking.status='Accepted'
        main.db.session.add(Plan(booking_id=self.booking.id,deposit=Decimal('50')));main.db.session.commit()
        self.client.get(f'/client/bookings/{self.booking.id}')
        with self.client.session_transaction() as state:self.csrf=state['client_csrf']
        self.env=patch.dict(os.environ,{'SUMUP_API_KEY':'test-key','SUMUP_MERCHANT_CODE':'TEST-MERCHANT'});self.env.start()
        main.BusinessSetting.query.filter_by(key='public_app_url').delete()
        main.db.session.add(main.BusinessSetting(key='public_app_url',value='https://example.com'));main.db.session.commit()

    def tearDown(self):self.env.stop();self.fixture.tearDown()

    def provider_data(self,row,status='PAID',**changes):
        return dict(id=row.provider_id,checkout_reference=row.reference,merchant_code=row.merchant,amount=str(row.amount),currency='GBP',status=status,**changes)

    def create(self):
        def response(path,payload=None):
            return dict(id='abc123',hosted_checkout_url='https://checkout.sumup.com/pay/abc123')
        with patch('sumup_checkout.provider_request',side_effect=response) as api:
            response=self.client.post(f'/client/bookings/{self.booking.id}/pay',data=dict(csrf_token=self.csrf,purpose='Deposit',amount='1'))
        self.assertEqual(response.status_code,302);self.assertEqual(response.location,'https://checkout.sumup.com/pay/abc123')
        payload=api.call_args.args[1];self.assertEqual(payload['amount'],50.0)
        self.assertEqual(payload['currency'],'GBP');self.assertTrue(payload['hosted_checkout']['enabled'])
        self.assertEqual(Entry.query.count(),0)
        return Checkout.query.one()

    def test_hosted_deposit_and_verified_callback_are_idempotent(self):
        row=self.create();route=f'/payments/sumup/callback/{row.token}'
        with patch('sumup_checkout.provider_request',return_value=self.provider_data(row)):
            self.assertTrue(self.client.post(route,json={'status':'FAILED'}).json['recorded'])
            self.assertTrue(self.client.post(route,json={'status':'PAID'}).json['recorded'])
        self.assertEqual(Entry.query.count(),1);self.assertEqual(Entry.query.one().amount,Decimal('50'))
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'],Decimal('50'))

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
        self.assertEqual(response.location,row.payment_url);self.assertEqual(Checkout.query.count(),1)
        self.assertTrue(all(call.args[0].startswith('checkouts/') for call in api.call_args_list))
        path=f'/bookings/{self.booking.id}/online-payment/{row.id}/refresh'
        self.assertEqual(main.app.test_client().post(path,data=dict(csrf_token=self.csrf)).status_code,404)


if __name__=='__main__':unittest.main()
