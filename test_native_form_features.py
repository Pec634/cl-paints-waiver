"""Advanced form workflows use the same authenticated clients and isolated database."""
from datetime import datetime
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_native_forms as fixtures
from native_form_fields import validate_fields
from native_form_features import amount, accessibility_issues
from native_form_records import csv_cell

main=fixtures.main
Form,Submission,Media=main.native_form_models
Settings,Version,SubmissionRecord,BookingRecord,Draft,FieldFile=main.db._native_extra_models


class AdvancedFormTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeFormsTest();self.fixture.setUp()
        self.client=self.fixture.client;self.admin=self.fixture.admin
        with self.admin.session_transaction() as state: state['admin_last_activity']=datetime.utcnow().timestamp()

    def tearDown(self): self.fixture.tearDown()

    def create(self,fields,kind='giveaway'):
        return self.fixture.create(kind,validate_fields(fields))

    def other_client(self):
        account=main.ClientAccount(email='other@example.com',first_name='Other',last_name='Client')
        main.db.session.add(account);main.db.session.commit()
        client=main.app.test_client()
        with self.client.session_transaction() as state: existing=dict(state)
        with client.session_transaction() as state: state.update(existing);state['client_id']=account.id
        return client

    def test_calculations_are_server_computed_and_support_choice_amounts(self):
        form=self.create([
            dict(label='Guests',type='number',required=True,min='1',max='20'),
            dict(label='Design',type='select',required=True,options=['Standard','Deluxe'],option_values={'Standard':'10','Deluxe':'15'}),
            dict(label='Extras',type='multiselect',options=['Gems','Glitter'],option_values={'Gems':'2.50','Glitter':'1'}),
            dict(label='Estimate',type='calculation',calculation=dict(operation='product',sources=['Guests','Design'],base='1',precision=2,prefix='£')),
            dict(label='Extras total',type='calculation',calculation=dict(operation='sum',sources=['Extras'],base='0',precision=2)),
            dict(label='Discount',type='calculation',calculation=dict(operation='percentage',sources=['Estimate'],base='10',precision=2)),
        ])
        payload=MultiDict(self.fixture.data(form))
        payload.update(dict(custom_0='3',custom_1='Deluxe',custom_3='FORGED TOTAL',custom_5='0'))
        payload.setlist('custom_2',['Gems','Glitter'])
        response=self.client.post('/forms/'+str(form.id),data=payload)
        self.assertEqual(response.status_code,302)
        data=json.loads(Submission.query.one().answers_json)
        self.assertEqual(data['Estimate'],'45.00')
        self.assertEqual(data['Extras total'],'3.50')
        self.assertEqual(data['Discount'],'4.50')
        self.assertIn('£45.00',self.client.get(response.location).data.decode())

    def test_repeating_sections_validate_each_row_and_count_rows(self):
        form=self.create([
            dict(label='Participants',type='repeat',required=True,max_items=3,children=[
                dict(label='Name',type='text',required=True),dict(label='Age',type='number',required=True,min='1',max='100')]),
            dict(label='People count',type='calculation',calculation=dict(operation='count',sources=['Participants'],base='0',precision=0)),
        ])
        from native_forms import answers
        valid={'custom_0':json.dumps([{'Name':'Alex','Age':'8'},{'Name':'Sam','Age':'10'}])}
        result=answers(form,valid)
        self.assertEqual(result['People count'],'2')
        self.assertEqual(result['Participants'][1]['Name'],'Sam')
        for rows in [[],[{'Name':'','Age':'8'}],[{'Name':'Alex','Age':'101'}],[{'Name':'Alex','Age':'8'}]*4]:
            with self.assertRaises(ValueError):answers(form,{'custom_0':json.dumps(rows)})
        with self.assertRaises(ValueError):answers(form,{'custom_0':'not json'})

    def test_multiple_conditions_and_conditional_required_answers(self):
        form=self.create([
            dict(label='Guests',type='number',required=True),
            dict(label='Design',type='radio',required=True,options=['Standard','Deluxe']),
            dict(label='Details',type='text',show_if=dict(mode='any',rules=[dict(field='Guests',operator='greater',value='2'),dict(field='Design',operator='equals',value='Deluxe')]),
                required_if=dict(mode='all',rules=[dict(field='Guests',operator='greater',value='2'),dict(field='Design',operator='equals',value='Deluxe')])),
        ])
        from native_forms import answers
        self.assertNotIn('Details',answers(form,{'custom_0':'1','custom_1':'Standard','custom_2':'FORGED HIDDEN'}))
        self.assertEqual(answers(form,{'custom_0':'3','custom_1':'Standard'})['Details'],'')
        with self.assertRaises(ValueError):answers(form,{'custom_0':'3','custom_1':'Deluxe'})
        self.assertEqual(answers(form,{'custom_0':'3','custom_1':'Deluxe','custom_2':'Venue notes'})['Details'],'Venue notes')

    def test_drawn_signature_is_validated_stored_and_rendered(self):
        form=self.create([dict(label='Signature',type='signature',required=True)])
        payload=self.fixture.data(form)
        payload['custom_0']=json.dumps(dict(name='Test Client',strokes=[[[.1,.1],[.2,.4],[.8,.3]]]))
        response=self.client.post('/forms/'+str(form.id),data=payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(json.loads(Submission.query.one().answers_json)['Signature']['name'],'Test Client')
        self.assertIn(b'<svg',self.client.get(response.location).data)
        from native_forms import answers
        for data in [dict(name='',strokes=[[[0,0],[1,1]]]),dict(name='Client',strokes=[]),dict(name='Client',strokes=[[[0,0],[99,1]]])]:
            with self.assertRaises(ValueError):answers(form,{'custom_0':json.dumps(data)})

    def test_private_field_uploads_allow_owner_and_admin_only(self):
        form=self.create([dict(label='Brief',type='file',required=True,file_types=['pdf'],max_files=1)])
        payload=self.fixture.data(form)
        payload['custom_0']=(BytesIO(b'%PDF-1.4\nExample document'),'brief.pdf')
        response=self.client.post('/forms/'+str(form.id),data=payload,content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        file=FieldFile.query.one();path='/form-files/'+str(file.id)
        self.assertEqual(file.label,'Brief')
        self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.admin.get(path).status_code,200)
        self.assertEqual(main.app.test_client().get(path).status_code,404)
        self.assertEqual(self.other_client().get(path).status_code,404)
        self.assertEqual(self.client.get(path).headers['Cache-Control'],'no-store')
        self.assertIn(b'brief.pdf',self.client.get(response.location).data)
        second=self.create([dict(label='Brief',type='file',required=True,file_types=['pdf'],max_files=1)])
        payload=self.fixture.data(second);payload['custom_0']=(BytesIO(b'<script>bad</script>'),'bad.pdf')
        self.client.post('/forms/'+str(second.id),data=payload,content_type='multipart/form-data')
        self.assertEqual(FieldFile.query.count(),1)

    def test_drafts_are_owned_and_require_csrf_and_current_version(self):
        form=self.create([dict(label='Notes',type='text'),dict(label='Sign',type='signature'),dict(label='Agreement',type='checkbox')])
        path='/forms/'+str(form.id)+'/draft'
        self.assertEqual(main.app.test_client().get(path).status_code,401)
        data=self.client.get(path).json
        payload=dict(fingerprint=data['fingerprint'],answers={'custom_0':'Unfinished','custom_1':'Signature must not persist','custom_2':'yes','agree':'yes','csrf_token':'PRIVATE TOKEN'})
        self.assertEqual(self.client.post(path,json=payload).status_code,400)
        response=self.client.post(path,json=payload,headers={'X-CSRF-Token':data['csrf_token']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get(path).json['answers'],{'custom_0':'Unfinished'})
        self.assertEqual(self.other_client().get(path).json['answers'],{})
        form.description='Changed wording';main.db.session.commit()
        self.assertTrue(self.client.get(path).json['outdated'])
        self.assertEqual(self.client.post(path,json=payload,headers={'X-CSRF-Token':data['csrf_token']}).status_code,409)
        self.assertEqual(self.client.delete(path,headers={'X-CSRF-Token':data['csrf_token']}).status_code,200)
        self.assertEqual(Draft.query.count(),0)

    def test_anonymous_booking_drafts_are_limited_to_the_same_browser(self):
        form=self.create([dict(label='Design',type='text')],kind='booking')
        client=main.app.test_client();path='/forms/'+str(form.id)+'/draft';data=client.get(path).json
        payload=dict(fingerprint=data['fingerprint'],answers={'first_name':'Alex','custom_0':'Tiger','signature':'Do not retain','terms_accepted':'yes'})
        response=client.post(path,json=payload,headers={'X-CSRF-Token':data['csrf_token']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.get(path).json['answers'],{'first_name':'Alex','custom_0':'Tiger'})
        self.assertEqual(main.app.test_client().get(path).json['answers'],{})

    def test_versions_restore_drafts_and_keep_submission_confirmation_snapshot(self):
        payload=dict(csrf_token='admin-token',kind='giveaway',title='Original title',terms='Original wording',fields='Notes | text | optional',
            confirmation_text='Thank you {first_name}: {reference}',email_subject='Receipt {reference}',email_body='Saved {form_title}')
        self.admin.post('/admin/native-forms',data=payload)
        form=Form.query.one();original=Version.query.filter_by(form_id=form.id).one()
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='toggle',id=form.id))
        with patch.object(main,'send_client_email',return_value=True) as send:
            data=self.fixture.data(form);data['custom_0']='An answer'
            response=self.client.post('/forms/'+str(form.id),data=data)
        item=Submission.query.one();meta=SubmissionRecord.query.one()
        self.assertEqual(json.loads(meta.snapshot_json)['terms'],'Original wording')
        self.assertEqual(send.call_args.args[1],'Receipt F-'+str(item.id))
        self.assertEqual(send.call_args.args[2],'Saved Original title')
        restore='/admin/native-forms/'+str(form.id)+'/restore/'+str(original.id)
        self.admin.post(restore,data=dict(csrf_token='admin-token'))
        self.assertTrue(form.enabled)
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='toggle',id=form.id))
        self.admin.post('/admin/native-forms',data=dict(payload,id=form.id,title='Updated title',terms='Updated wording',confirmation_text='Different acknowledgement'))
        page=self.client.get(response.location)
        self.assertIn(b'Original wording',page.data)
        self.assertIn(('Thank you Test: F-'+str(item.id)).encode(),page.data)
        self.assertNotIn(b'Different acknowledgement',page.data)
        self.admin.post(restore,data=dict(csrf_token='admin-token'))
        self.assertEqual(form.title,'Original title')
        self.assertFalse(form.enabled)
        self.assertGreaterEqual(Version.query.filter_by(form_id=form.id).count(),5)
        self.assertEqual(json.loads(meta.snapshot_json)['title'],'Original title')

    def test_review_search_and_export_are_admin_only_and_csv_safe(self):
        form=self.create([dict(label='Notes',type='text')])
        data=self.fixture.data(form);data['custom_0']='=SUM(A1:A2)'
        self.client.post('/forms/'+str(form.id),data=data)
        item=Submission.query.one()
        path='/admin/native-forms/'+str(form.id)
        self.assertEqual(self.client.get(path+'/export').status_code,302)
        self.assertEqual(self.admin.post(path+'/review',data={}).status_code,400)
        response=self.admin.post(path+'/review',data=dict(csrf_token='admin-token',entry_id=item.id,entry_type='submission',review_status='Reviewed',note='Private reviewer note'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(SubmissionRecord.query.one().review_status,'Reviewed')
        self.assertIn(b'Private reviewer note',self.admin.get(path+'/submissions?status=Reviewed&q=SUM').data)
        self.assertNotIn(b'Private reviewer note',self.client.get('/client/form-submissions/'+str(item.id)).data)
        csv=self.admin.get(path+'/export?status=Reviewed').data.decode('utf-8-sig')
        self.assertIn("'=SUM(A1:A2)",csv)
        self.assertIn('Reviewed',csv)
        self.assertNotIn('=SUM',self.admin.get(path+'/export?status=New').data.decode())
        for value in ['=1+1','+SUM(A1)','-1+2','@formula','\t=SUM(A1)']:
            self.assertTrue(csv_cell(value).startswith("'"))

    def test_gallery_pagebreak_and_accessibility_checks(self):
        form=self.create([dict(label='Pick a design',type='gallery',options=['Tiger','Butterfly'],option_images={'Tiger':'https://example.com/tiger.jpg','Butterfly':'https://example.com/butterfly.jpg'}),dict(label='Second step',type='pagebreak'),dict(label='Notes',type='text')])
        page=self.client.get('/forms/'+str(form.id))
        self.assertIn(b'native-image-gallery',page.data)
        self.assertIn(b'pagebreak',page.data)
        issues=accessibility_issues([dict(label='Question',type='text',layout={'width':1}),dict(label='Photo',type='image',alt='')])
        self.assertTrue(any('description' in issue for issue in issues))
        self.assertTrue(any('Widen' in issue for issue in issues))
        with self.assertRaises(ValueError):validate_fields([dict(label='Gallery',type='gallery',options=['Tiger'],option_images={})])

    def test_hostile_calculations_and_nested_repeats_are_rejected(self):
        for value in ['NaN','Infinity','1e999999999','1e-999999999','1000000001']:
            with self.assertRaises(ValueError):amount(value)
        with self.assertRaises(ValueError):validate_fields([dict(label='Unsafe',type='calculation',calculation=dict(operation='eval',sources=['__import__'] ))])
        with self.assertRaises(ValueError):validate_fields([dict(label='Nested',type='repeat',children=[dict(label='Nested again',type='repeat')])])
        with self.assertRaises(ValueError):validate_fields([dict(label='Repeat',type='repeat',children=[dict(label='Name',type='text')]),dict(label='Wrong',type='calculation',calculation=dict(operation='sum',sources=['Repeat']))])

    def test_seasonal_booking_stores_advanced_answers_files_and_version(self):
        form=self.create([
            dict(label='Guests',type='number',required=True),
            dict(label='Estimate',type='calculation',calculation=dict(operation='product',sources=['Guests'],base='15',precision=2,prefix='£')),
            dict(label='People',type='repeat',required=True,children=[dict(label='Name',type='text',required=True)]),
            dict(label='Brief',type='file',required=True,file_types=['pdf'],max_files=1),
            dict(label='Additional signature',type='signature',required=True),
        ],kind='booking')
        portal=self.fixture.fixture.fixture.fixture
        event=dict(date='2099-01-01',start_time='10:00',finish_time='12:00',event_address='Venue',event_type='Seasonal',theme='Spooky',pitch_fee_required='no',publicity_type='Private',location_type='Indoors',charge_type='Client')
        data=dict(csrf_token=portal.csrf(),seasonal_id=form.id,seasonal_agree='yes',custom_0='3',custom_1='FORGED',custom_2=json.dumps([{'Name':'Alex'}]),
            custom_3=(BytesIO(b'%PDF-1.4\nExample'),'brief.pdf'),custom_4=json.dumps(dict(name='Test Client',strokes=[[[0,0],[.5,.5]]])),
            request_type='booking',client_type='individual',first_name='Test',last_name='Client',email='client@example.com',phone='+447911123456',address_property='10',address_street='Abbey Road',address_city='London',address_postcode='NW10 7TR',address_country='United Kingdom',signature='Test Client',date_of_birth='1990-01-01',is_over_18='yes',ethnicity='Prefer not to say',religion='Prefer not to say',single_date='yes',payment_preference='Full payment',liability_acknowledged='yes',terms_accepted='yes',event_schedule=json.dumps({'events':[event]}))
        with patch.object(main,'send_booking_request_confirmation',return_value=True):response=self.client.post('/booking',data=data,content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        record=BookingRecord.query.one();booking=main.db.session.get(main.Booking,record.booking_id)
        answers=json.loads(booking.event_schedule)['seasonal_form']['answers']
        self.assertEqual(answers['Estimate'],'45.00')
        self.assertEqual(answers['People'],[{'Name':'Alex'}])
        self.assertTrue(record.version_id)
        file=FieldFile.query.one();self.assertEqual(file.booking_id,booking.id)
        self.assertEqual(self.client.get('/form-files/'+str(file.id)).status_code,200)
        self.assertEqual(self.other_client().get('/form-files/'+str(file.id)).status_code,404)
        self.assertIn(b'brief.pdf',self.client.get(response.location).data)


if __name__=='__main__':unittest.main()
