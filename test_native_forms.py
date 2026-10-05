from datetime import datetime, timedelta
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import test_business_tools as fixtures

main=fixtures.main
Form,Submission,Media=main.native_form_models


class NativeFormsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp()
        self.client=self.fixture.client;self.admin=self.fixture.admin

    def tearDown(self):self.fixture.tearDown()

    def create(self,kind,fields=None):
        form=Form(kind=kind,title='Test '+kind,terms='Actual consent or entry rules',enabled=True,
            fields_json=json.dumps(fields or []))
        main.db.session.add(form);main.db.session.commit();return form

    def data(self,form):
        self.assertEqual(self.client.get('/forms/'+str(form.id)).status_code,200)
        with self.client.session_transaction() as session:
            return dict(csrf_token=session['client_csrf'],submission_token=session['native_form_'+str(form.id)],agree='yes')

    def test_giveaway_duplicate_terms_and_access(self):
        form=self.create('giveaway',[dict(label='Favourite design',type='text',required=True)])
        payload=self.data(form)
        self.client.post('/forms/'+str(form.id),data=payload)
        self.assertEqual(Submission.query.count(),0)
        payload['custom_0']='Butterfly'
        response=self.client.post('/forms/'+str(form.id),data=payload)
        self.assertEqual(response.status_code,302)
        item=Submission.query.one()
        self.assertEqual(item.terms_snapshot,form.terms)
        self.assertIn(b'Butterfly',self.client.get(response.location).data)
        self.assertEqual(main.app.test_client().get(response.location).status_code,404)
        payload=self.data(form);payload['custom_0']='Another'
        self.client.post('/forms/'+str(form.id),data=payload)
        self.assertEqual(Submission.query.count(),1)
        self.assertEqual(self.admin.get(f'/admin/native-forms/{form.id}/submissions').status_code,200)
        form.ends_at=datetime.utcnow()-timedelta(seconds=1);main.db.session.commit()
        self.assertEqual(self.client.get('/forms/'+str(form.id)).status_code,404)

    def test_photo_upload_privacy_and_validation(self):
        form=self.create('photo');payload=self.data(form)
        payload.update(people='Alex; I am their parent',authority='yes',media=(BytesIO(b'\x89PNG\r\n\x1a\nexample'),'photo.png'))
        response=self.client.post('/forms/'+str(form.id),data=payload,content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        media=Media.query.one()
        path='/form-media/'+str(media.id)
        self.assertEqual(main.app.test_client().get(path).status_code,404)
        self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.admin.get(path).status_code,200)
        self.assertEqual(self.client.get(path).headers['Cache-Control'],'no-store')
        payload=self.data(form);payload.update(people='Alex',authority='yes',media=(BytesIO(b'<svg>bad</svg>'),'fake.png'))
        self.client.post('/forms/'+str(form.id),data=payload,content_type='multipart/form-data')
        self.assertEqual(Submission.query.count(),1)
        other=main.ClientAccount(email='other@example.com',first_name='Other',last_name='Client')
        main.db.session.add(other);main.db.session.commit()
        with self.client.session_transaction() as session:session['client_id']=other.id
        self.assertEqual(self.client.get(path).status_code,404)

    def test_editor_draft_and_custom_fields_validation(self):
        self.assertEqual(main.app.test_client().get('/admin/native-forms').status_code,302)
        self.assertEqual(self.admin.post('/admin/native-forms',data={}).status_code,400)
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='booking',title='Halloween',terms='Seasonal information',fields='Design | text | required'))
        form=Form.query.one();self.assertFalse(form.enabled)
        self.assertEqual(self.client.get('/forms/'+str(form.id)).status_code,404)
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='toggle',id=form.id))
        response=self.client.get('/forms/'+str(form.id));self.assertIn('seasonal=',response.location)
        page=self.client.get(response.location)
        self.assertEqual(page.status_code,200);self.assertIn(b'name="seasonal_id"',page.data)
        self.assertIn(b'Design',page.data)
        self.assertIn(b'Halloween',self.client.get('/client/bookings').data)

    def test_screenshot_templates_and_participant_consent(self):
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='preset',preset='giveaway'))
        form=Form.query.one()
        self.assertFalse(form.enabled)
        self.assertIn('two-hour',form.terms)
        from native_forms import answers
        with self.assertRaises(ValueError):answers(form,{'custom_0':'yes','custom_1':'yes','custom_2':'Invalid'})
        self.assertEqual(answers(form,{'custom_0':'yes','custom_1':'yes','custom_2':'No'})['I would like marketing updates and news from CL Paints by email'],'No')
        photo=self.create('photo')
        payload=self.data(photo)
        payload.update(participants=json.dumps([{'name':'Alex','consent':False}]),people='Parent',authority='yes',media=(BytesIO(b'\x89PNG\r\n\x1a\nexample'),'photo.png'))
        self.client.post('/forms/'+str(photo.id),data=payload,content_type='multipart/form-data')
        self.assertEqual(Submission.query.count(),0)

    def test_seasonal_request_saves_answers_in_booking(self):
        form=self.create('booking',[dict(label='Preferred design',type='text',required=True)])
        portal=self.fixture.fixture.fixture
        event=dict(date='2099-01-01',start_time='10:00',finish_time='12:00',event_address='Venue',event_type='Halloween',theme='Spooky',pitch_fee_required='no',publicity_type='Private',location_type='Indoors',charge_type='Client')
        with patch.object(main,'send_booking_request_confirmation',return_value=True):
            response=self.client.post('/booking',data=dict(csrf_token=portal.csrf(),seasonal_id=form.id,seasonal_agree='yes',custom_0='Skeleton',design_images=(BytesIO(b'\x89PNG\r\n\x1a\nexample'),'idea.png'),request_type='booking',client_type='individual',first_name='Test',last_name='Client',email='client@example.com',phone='+447911123456',address_property='10',address_street='Abbey Road',address_city='London',address_postcode='NW10 7TR',address_country='United Kingdom',signature='Test Client',date_of_birth='1990-01-01',is_over_18='yes',ethnicity='Prefer not to say',religion='Prefer not to say',single_date='yes',payment_preference='Full payment',liability_acknowledged='yes',terms_accepted='yes',event_schedule=json.dumps({'events':[event]})))
        self.assertEqual(response.status_code,302)
        booking=main.Booking.query.order_by(main.Booking.id.desc()).first()
        saved=json.loads(booking.event_schedule)['seasonal_form']
        self.assertEqual(saved['answers']['Preferred design'],'Skeleton')
        self.assertEqual(saved['terms'],form.terms)
        media=main.app.extensions['native_booking_media'].query.one()
        self.assertEqual(self.client.get(f'/admin/booking-design-media/{media.id}').status_code,302)
        self.assertEqual(self.admin.get(f'/admin/booking-design-media/{media.id}').status_code,200)
        self.assertIn(b'Skeleton',self.admin.get(f'/admin/native-forms/{form.id}/submissions').data)


if __name__=='__main__':unittest.main()
