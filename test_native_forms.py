from datetime import datetime, timedelta
from io import BytesIO
import json
import unittest
from werkzeug.datastructures import MultiDict
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

    def test_duplicate_creates_unscheduled_draft_without_submissions(self):
        source=self.create('giveaway',[dict(label='Design',type='select',required=True,options=['Tiger','Butterfly'])])
        source.starts_at=datetime.utcnow()-timedelta(days=1)
        source.ends_at=datetime.utcnow()+timedelta(days=1)
        main.db.session.commit()
        response=self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='duplicate',id=source.id))
        copy=Form.query.order_by(Form.id.desc()).first()
        self.assertNotEqual(copy.id,source.id)
        self.assertFalse(copy.enabled)
        self.assertIsNone(copy.starts_at)
        self.assertIsNone(copy.ends_at)
        self.assertEqual(copy.fields_json,source.fields_json)
        self.assertEqual(copy.terms,source.terms)
        self.assertTrue(source.enabled)
        self.assertIn('edit='+str(copy.id),response.location)
        self.assertIn(b'Question',self.admin.get(response.location).data)
        self.assertEqual(self.client.get('/forms/'+str(copy.id)).status_code,404)

    def test_editor_preserves_invalid_input_and_displays_availability(self):
        response=self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='giveaway',
            title='Keep my draft title',description='Keep my introduction',terms='Entry rules',
            fields='Design | select | required | Tiger, Butterfly',starts_at='2099-02-02T10:00',ends_at='2099-02-01T10:00'))
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Closing time must follow opening time.',response.data)
        self.assertIn(b'Keep my draft title',response.data)
        self.assertIn(b'Tiger, Butterfly',response.data)
        self.assertEqual(Form.query.count(),0)
        scheduled=self.create('giveaway')
        scheduled.starts_at=datetime.utcnow()+timedelta(days=1)
        closed=self.create('photo')
        closed.ends_at=datetime.utcnow()-timedelta(days=1)
        main.db.session.commit()
        page=self.admin.get('/admin/native-forms')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'data-state="scheduled"',page.data)
        self.assertIn(b'data-state="closed"',page.data)

    def test_rich_blocks_render_and_submit_only_customer_answers(self):
        from native_form_fields import validate_fields
        fields=validate_fields([
            dict(label='Welcome',type='content',content='This text cannot be edited by the client.'),
            dict(label='Design',type='cards',required=True,options=['Tiger','Butterfly'],option_images={'Tiger':'https://example.com/tiger.jpg'}),
            dict(label='Extras',type='multiselect',required=True,options=['Glitter','Gems']),
            dict(label='Size',type='radio',required=False,options=['Small','Large']),
            dict(label='Contact',type='email',required=True),
        ])
        response=self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='giveaway',
            title='Rich form',terms='Entry rules',fields_json=json.dumps(fields)))
        self.assertEqual(response.status_code,302)
        form=Form.query.one()
        self.assertEqual(json.loads(form.fields_json),fields)
        form.enabled=True;main.db.session.commit()
        payload=self.data(form)
        page=self.client.get('/forms/'+str(form.id))
        self.assertIn(b'native-choice-card',page.data)
        self.assertIn(b'This text cannot be edited',page.data)
        self.assertNotIn(b'name="custom_0"',page.data)
        data=MultiDict(payload)
        data.update(dict(custom_0='FORGED CONTENT',custom_1='Tiger',custom_3='Small',custom_4='client@example.com'))
        data.setlist('custom_2',['Glitter','Gems'])
        self.client.post('/forms/'+str(form.id),data=data)
        saved=json.loads(Submission.query.one().answers_json)
        self.assertNotIn('Welcome',saved)
        self.assertEqual(saved['Extras'],['Glitter','Gems'])
        self.assertEqual(saved['Design'],'Tiger')

    def test_conditional_rules_and_answer_limits_are_enforced_on_server(self):
        from native_form_fields import validate_fields
        from native_forms import answers
        fields=validate_fields([
            dict(label='Service',type='radio',required=True,options=['Face paint','Glitter']),
            dict(label='Design details',type='text',required=True,max_length=5,show_if={'field':'Service','equals':'Face paint'}),
            dict(label='Guests',type='number',required=True,min='1',max='10'),
            dict(label='Extras',type='multiselect',required=True,options=['Gems','Stars']),
        ])
        form=self.create('booking',fields)
        values=MultiDict({'custom_0':'Glitter','custom_1':'FORGED HIDDEN VALUE','custom_2':'5','custom_3':'Gems'})
        saved=answers(form,values)
        self.assertNotIn('Design details',saved)
        values['custom_0']='Face paint'
        with self.assertRaises(ValueError):answers(form,values)
        values['custom_1']='Tiger'
        self.assertEqual(answers(form,values)['Design details'],'Tiger')
        for key,bad in [('custom_0','Unlisted'),('custom_2','11'),('custom_3','Unlisted')]:
            test=values.copy();test[key]=bad
            with self.assertRaises(ValueError):answers(form,test)
        missing=values.copy();missing.pop('custom_3')
        with self.assertRaises(ValueError):answers(form,missing)
        with self.assertRaises(ValueError):validate_fields([fields[1],fields[0]])
        with self.assertRaises(ValueError):validate_fields([dict(label='Picture',type='image',src='javascript:alert(1)',alt='Picture')])
        with self.assertRaises(ValueError):validate_fields([dict(label='Repeated',type='radio',options=['A','A'])])

    def test_image_upload_permissions_and_published_references(self):
        path='/admin/native-form-images'
        self.assertEqual(main.app.test_client().post(path).status_code,302)
        self.assertEqual(self.admin.post(path).status_code,400)
        invalid=self.admin.post(path,data=dict(csrf_token='admin-token',image=(BytesIO(b'<svg>not allowed</svg>'),'image.svg')))
        self.assertEqual(invalid.status_code,400)
        response=self.admin.post(path,data=dict(csrf_token='admin-token',image=(BytesIO(b'\x89PNG\r\n\x1a\nexample'),'image.png')))
        self.assertEqual(response.status_code,201)
        source=response.json['url']
        public=main.app.test_client()
        self.assertEqual(public.get(source).status_code,404)

        self.assertEqual(self.admin.get(source).status_code,200)
        fields=[dict(label='Picture',type='image',src=source,alt='A design example',align='right',size='small')]
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='booking',title='Image form',fields_json=json.dumps(fields)))
        form=Form.query.one()
        self.assertEqual(public.get(source).status_code,404)
        form.enabled=True;main.db.session.commit()
        image=public.get(source)
        self.assertEqual(image.status_code,200)
        self.assertEqual(image.mimetype,'image/png')
        self.assertEqual(image.headers['X-Content-Type-Options'],'nosniff')
        page=public.get('/booking?seasonal='+str(form.id))
        self.assertIn(b'native-align-right',page.data)
        self.assertIn(b'alt="A design example"',page.data)
        form.enabled=False;main.db.session.commit()
        self.assertEqual(public.get(source).status_code,404)

    def test_extended_fields_validate_and_escape_content(self):
        from native_form_fields import validate_fields
        from native_forms import answers
        fields=validate_fields([
            dict(label='Contact',type='email',required=True),
            dict(label='Website',type='url'),
            dict(label='Arrival',type='time',required=True),
            dict(label='Instructions',type='content',content='<script>alert(1)</script>'),
        ])
        form=self.create('giveaway',fields)
        valid={'custom_0':'client@example.com','custom_1':'https://example.com','custom_2':'10:30'}
        self.assertEqual(answers(form,valid)['Arrival'],'10:30')
        for key,value in [('custom_0','invalid'),('custom_1','javascript:alert(1)'),('custom_2','25:70')]:
            with self.assertRaises(ValueError):answers(form,dict(valid,**{key:value}))
        page=self.client.get('/forms/'+str(form.id))
        self.assertIn(b'&lt;script&gt;alert(1)&lt;/script&gt;',page.data)
        self.assertNotIn(b'<script>alert(1)</script>',page.data)
        with self.assertRaises(ValueError):validate_fields([dict(label='Invalid',type=[])])
        blocks=[dict(label='Block '+str(index),type='heading') for index in range(31)]
        with self.assertRaises(ValueError):validate_fields(blocks)

    def test_grid_layout_persists_and_rejects_overlaps_and_invalid_positions(self):
        from native_form_fields import validate_fields
        blocks=[
            dict(label='First name',type='text',layout=dict(row=1,column=1,width=6)),
            dict(label='Last name',type='text',layout=dict(row=1,column=7,width=6)),
            dict(label='Instructions',type='content',content='Details below',layout=dict(row=2,column=1,width=12)),
        ]
        response=self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='booking',title='Grid form',fields_json=json.dumps(blocks)))
        self.assertEqual(response.status_code,302)
        form=Form.query.one()
        saved=json.loads(form.fields_json)
        self.assertEqual(saved[1]['layout'],dict(row=1,column=7,width=6))
        form.enabled=True;main.db.session.commit()
        page=self.client.get('/booking?seasonal='+str(form.id))
        self.assertIn(b'--block-row: 1; --block-column: 7; --block-width: 6;',page.data)
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='duplicate',id=form.id))
        copied=Form.query.order_by(Form.id.desc()).first()
        self.assertEqual(copied.fields_json,form.fields_json)
        for bad in [dict(row=1,column=6,width=6),dict(row=1,column=8,width=6),dict(row=0,column=7,width=6),dict(row=61,column=7,width=6),dict(row=1,column=True,width=6)]:
            invalid=[blocks[0],dict(blocks[1],layout=bad)]
            with self.assertRaises(ValueError):validate_fields(invalid)
        with self.assertRaises(ValueError):validate_fields([
            dict(label='Show details',type='radio',options=['Yes','No'],layout=dict(row=2,column=1,width=12)),
            dict(label='Details',type='text',show_if=dict(field='Show details',equals='Yes'),layout=dict(row=1,column=1,width=12)),
        ])

    def test_choice_spacing_and_columns_save_and_render(self):
        from native_form_fields import validate_fields
        fields=[dict(label='Design',type='radio',options=['Tiger','Butterfly'],option_columns=2,option_spacing='spacious')]
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',kind='giveaway',title='Spaced choices',terms='Rules',fields_json=json.dumps(fields)))
        form=Form.query.one()
        self.assertEqual(json.loads(form.fields_json)[0]['option_columns'],2)
        form.enabled=True;main.db.session.commit()
        page=self.client.get('/forms/'+str(form.id))
        self.assertIn(b'native-spacing-spacious',page.data)
        self.assertIn(b'--choice-columns: 2;',page.data)
        for bad in [dict(option_columns=4),dict(option_columns=True),dict(option_spacing='invalid')]:
            with self.assertRaises(ValueError):validate_fields([dict(fields[0],**bad)])

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
