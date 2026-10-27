from datetime import datetime, timedelta
from decimal import Decimal
import re
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import test_business_tools as fixtures

main=fixtures.main


class HistoricalFinancesTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.booking=self.fixture.booking
        self.booking.status='Accepted'
        self.booking.event_date=datetime.now(ZoneInfo('Europe/London')).date()-timedelta(days=20)
        self.booking.total_event_cost=Decimal('0')
        self.booking.travel_charge=Decimal('0')
        main.db.session.commit()
        self.page=f'/admin/bookings/{self.booking.id}/payments'
        self.path=f'/admin/bookings/{self.booking.id}/historical-finances'

    def tearDown(self):
        self.fixture.tearDown()

    def data(self,**changes):
        page=self.fixture.admin.get(self.page).get_data(as_text=True)
        value=lambda name: re.search('name="'+name+'" value="([^"]*)"',page).group(1)
        data=dict(csrf_token='admin-token',correction_token=value('correction_token'),version=value('version'),
            event_cost='200.00',travel_charge='20.00',received_amount='220.00',
            paid_date=self.booking.event_date.isoformat(),method='Bank transfer',
            receipt_reference='BANK-123',reason='PRIVATE: Imported totals and historical receipt missing')
        data.update(changes)
        return data

    def test_corrects_price_and_historical_receipt_without_reconfirming_charging_or_email(self):
        data=self.data()
        with patch('sumup_checkout.provider_request') as provider, patch.object(main,'send_client_email') as mail:
            response=self.fixture.admin.post(self.path,data=data)
            self.assertEqual(response.status_code,302)
            provider.assert_not_called(); mail.assert_not_called()
        payment=main.app.extensions['payment_summary'](self.booking)
        self.assertEqual(payment['total'],Decimal('220'))
        self.assertEqual(payment['paid'],Decimal('220'))
        self.assertEqual(payment['outstanding'],0)
        self.assertEqual(self.booking.status,'Accepted')
        self.assertEqual(main.tool_models[1].query.one().paid_date,self.booking.event_date)
        self.assertEqual(main.tool_models[1].query.one().method,'Bank transfer')
        self.assertEqual(main.BookingFinancialCorrection.query.count(),1)
        self.fixture.admin.post(self.path,data=data)
        self.assertEqual(main.tool_models[1].query.count(),1)
        self.assertEqual(main.BookingFinancialCorrection.query.count(),1)
        client=self.fixture.client.get(f'/client/bookings/{self.booking.id}').data
        self.assertIn(b'220.00',client)
        self.assertNotIn(b'PRIVATE:',client)
        self.assertIn(b'Historical financial correction',self.fixture.admin.get(f'/admin/bookings/{self.booking.id}/activity').data)

    def test_price_only_and_additional_payments_preserve_existing_ledger(self):
        received=main.tool_models[1](booking_id=self.booking.id,token='existing-receipt',amount=Decimal('50'),
            kind='payment',method='Cash',paid_date=self.booking.event_date)
        main.db.session.add(received);main.db.session.commit()
        self.fixture.admin.post(self.path,data=self.data(received_amount='0'))
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['outstanding'],Decimal('170'))
        self.fixture.admin.post(self.path,data=self.data(received_amount='170'))
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'],Decimal('220'))
        self.assertEqual(main.tool_models[1].query.count(),2)
        self.assertEqual(received.amount,Decimal('50'))

    def test_admin_csrf_stale_and_invalid_inputs_cannot_change_money(self):
        data=self.data()
        self.assertEqual(self.fixture.client.post(self.path,data=data).status_code,302)
        self.assertEqual(main.app.test_client().post(self.path,data=data).status_code,302)
        self.assertEqual(self.fixture.admin.post(self.path,data=dict(data,csrf_token='bad')).status_code,400)
        self.assertEqual(self.fixture.admin.post(self.path,data=dict(data,correction_token='wrong')).status_code,400)
        for changes in (dict(reason=''),dict(event_cost='NaN'),dict(travel_charge='-1'),dict(received_amount='1.001'),
                        dict(paid_date='2099-01-01'),dict(method='bad'),dict(version='stale')):
            self.fixture.admin.post(self.path,data=dict(data,**changes))
        self.assertEqual(self.booking.total_event_cost,Decimal('0'))
        self.assertEqual(main.tool_models[1].query.count(),0)
        self.assertEqual(main.BookingFinancialCorrection.query.count(),0)
        self.booking.event_date=datetime.now(ZoneInfo('Europe/London')).date()+timedelta(days=20)
        main.db.session.commit()
        self.fixture.admin.post(self.path,data=data)
        self.assertEqual(main.BookingFinancialCorrection.query.count(),0)

    def test_pending_checkout_protects_ledger_and_deposit_cannot_exceed_corrected_price(self):
        data=self.data()
        main.db.session.add(main.SumupCheckout(booking_id=self.booking.id,token='unresolved-old-payment',
            reference='OLD-PAYMENT',amount=Decimal('25'),purpose='Deposit',merchant='TEST'))
        main.db.session.commit()
        self.fixture.admin.post(self.path,data=data)
        self.assertEqual(main.BookingFinancialCorrection.query.count(),0)
        main.SumupCheckout.query.delete()
        main.db.session.add(main.tool_models[0](booking_id=self.booking.id,deposit=Decimal('300')))
        main.db.session.commit()
        self.fixture.admin.post(self.path,data=self.data())
        self.assertEqual(main.BookingFinancialCorrection.query.count(),0)
        self.assertEqual(main.tool_models[1].query.count(),0)


if __name__=='__main__': unittest.main()
