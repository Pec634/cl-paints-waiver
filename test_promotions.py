from datetime import datetime, timedelta
from decimal import Decimal
import unittest
import json
from unittest.mock import patch
import test_business_tools as fixtures
from business_promotions import active_discount

main=fixtures.main
Form, Offer=main.promotion_models


class PromotionTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin=self.fixture.admin

    def tearDown(self): self.fixture.tearDown()

    def test_discount_boundaries_best_offer_and_saved_booking(self):
        now=datetime.utcnow(); cost=self.fixture.booking.total_event_cost
        offer=Offer(title='Black Friday',reduction=Decimal('5'),starts_at=now,ends_at=now+timedelta(hours=1))
        main.db.session.add(offer);main.db.session.commit()
        self.assertIsNone(active_discount(Offer,'45',now-timedelta(seconds=1)))
        self.assertEqual(active_discount(Offer,'45',now)['hourly_rate'],'40.00')
        self.assertIsNone(active_discount(Offer,'45',offer.ends_at))
        main.db.session.add(Offer(title='Larger offer',reduction=Decimal('10'),starts_at=now,ends_at=now+timedelta(hours=1)));main.db.session.commit()
        self.assertEqual(active_discount(Offer,'45',now)['hourly_rate'],'35.00')
        self.assertEqual(self.fixture.booking.total_event_cost,cost)
        page=self.fixture.client.get('/booking')
        self.assertIn(b'Larger offer',page.data)
        self.assertIn(b'35.00',page.data)

    def test_admin_forms_and_uk_offer_time_validation(self):
        path='/admin/forms-offers'
        self.assertEqual(main.app.test_client().get(path).status_code,302)
        self.assertEqual(self.admin.post(path,data={}).status_code,400)
        self.admin.post(path,data=dict(csrf_token='admin-token',action='form',title='Christmas',url='https://www.cognitoforms.com/CLPaints/Christmas',description='Festive faces'))
        self.assertEqual(Form.query.count(),1)
        self.assertIn(b'Christmas',self.fixture.client.get('/client/bookings').data)
        self.admin.post(path,data=dict(csrf_token='admin-token',action='toggle_form',id=Form.query.one().id))
        self.assertNotIn(b'Festive faces',self.fixture.client.get('/client/bookings').data)
        self.admin.post(path,data=dict(csrf_token='admin-token',action='form',title='Bad',url='javascript:alert(1)'))
        self.assertEqual(Form.query.count(),1)
        self.admin.post(path,data=dict(csrf_token='admin-token',action='offer',title='Summer',reduction='5',starts_at='2026-07-01T10:00',ends_at='2026-07-02T10:00'))
        self.assertEqual(Offer.query.one().starts_at.hour,9)
        self.admin.post(path,data=dict(csrf_token='admin-token',action='offer',title='Bad',reduction='NaN',starts_at='2026-07-01T10:00',ends_at='2026-07-02T10:00'))
        self.assertEqual(Offer.query.count(),1)
        client=self.fixture.client.get('/client/rewards').data
        self.assertIn(b'Give-away',client);self.assertIn(b'/CLPaints/Photo',client)
        self.assertNotIn(b'RoadTrafficCollision',client)
        self.assertIn(b'RoadTrafficCollision',self.admin.get(path).data)

    def test_new_booking_saves_discounted_price_and_offer(self):
        now=datetime.utcnow()
        main.db.session.add(Offer(title='Save five',reduction=Decimal('5'),starts_at=now-timedelta(minutes=1),ends_at=now+timedelta(hours=1)));main.db.session.commit()
        portal=self.fixture.fixture.fixture
        event=dict(date='2099-01-01',start_time='10:00',finish_time='12:00',event_address='Test venue',event_type='Birthday',theme='N/A',pitch_fee_required='no',publicity_type='Private',location_type='Indoors',charge_type='Client')
        with patch.object(main,'send_booking_request_confirmation',return_value=True):
            response=portal.client.post('/booking',data=dict(csrf_token=portal.csrf(),request_type='booking',client_type='individual',first_name='Test',last_name='Client',email='client@example.com',phone='+447911123456',address_property='10',address_street='Abbey Road',address_city='London',address_postcode='NW10 7TR',address_country='United Kingdom',signature='Test Client',date_of_birth='1990-01-01',is_over_18='yes',ethnicity='Prefer not to say',religion='Prefer not to say',single_date='yes',payment_preference='Full payment',liability_acknowledged='yes',terms_accepted='yes',event_schedule=json.dumps({'events':[event]})))
        self.assertEqual(response.status_code,302)
        booking=main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertEqual(booking.total_event_cost,Decimal('80.00'))
        self.assertEqual(json.loads(booking.event_schedule)['pricing_rules']['promotion']['title'],'Save five')


if __name__=='__main__':unittest.main()
