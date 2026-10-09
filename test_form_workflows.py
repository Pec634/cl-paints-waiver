from datetime import datetime, timedelta
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_native_forms as fixtures
from form_workflows import catalog, validate_options, booking_options, pdf_document
from native_form_fields import validate_fields

main=fixtures.main
Form,Submission,_=main.native_form_models
Template,Activity,Waiting,Attempt=main.db._form_workflow_models


class FormWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeFormsTest();self.fixture.setUp()
        self.client=self.fixture.client;self.admin=self.fixture.admin
        with self.admin.session_transaction() as state:state['admin_last_activity']=datetime.utcnow().timestamp()

    def tearDown(self):self.fixture.tearDown()

    def options(self,form,**settings):
        records=main.app.extensions['native_form_records']
        records['set_settings'](form,validate_options(settings));main.db.session.commit()

    def booking_data(self,form):
        self.client.get('/booking?seasonal='+str(form.id))
        with self.client.session_transaction() as state:csrf=state['client_csrf']
        event=dict(date='2099-02-01',start_time='10:00',finish_time='12:00',event_address='Venue',event_type='Birthday',theme='Butterflies',pitch_fee_required='no',publicity_type='Private',location_type='Indoors',charge_type='Client')
        return MultiDict(dict(csrf_token=csrf,seasonal_id=str(form.id),seasonal_agree='yes',request_type='booking',client_type='individual',first_name='Test',last_name='Client',phone='+447911123456',address_property='10',address_street='Abbey Road',address_city='London',address_postcode='NW10 7TR',address_country='United Kingdom',signature='Test Client',date_of_birth='1990-01-01',is_over_18='yes',ethnicity='Prefer not to say',religion='Prefer not to say',single_date='yes',payment_preference='50% deposit',liability_acknowledged='yes',terms_accepted='yes',event_schedule=json.dumps({'events':[event]})))

    def test_catalog_and_server_price_reject_tampering(self):
        settings=validate_options(dict(packages='Party | 120 | 2 | Two hours',extras='Glitter | 15 | 0 | Sparkles'))
        events=[dict(duration_hours='2',pitch_fee_required=False,charge_type='Client',estimated_cost='90')]
        data=MultiDict(dict(booking_package='Party',booking_extras='Glitter',posted_total='1'))
        total,details=booking_options(settings,data,events,Decimal('90'))
        self.assertEqual(total,Decimal('135'));self.assertEqual(events[0]['estimated_cost'],'120')
        self.assertEqual(details['extras_total'],'15')
        for changes in [dict(booking_package='Unlisted'),dict(booking_extras='Unlisted')]:
            with self.assertRaises(ValueError):booking_options(settings,MultiDict(dict(data,**changes)),events,Decimal('90'))
        for posted_miles in ['12','NaN','-100','100000']:
            _, details = booking_options(settings,MultiDict(dict(data,travel_miles=posted_miles)),events,Decimal('90'))
            self.assertEqual(details['travel_miles'],'0')
        for text in ['Bad | NaN | 2','Bad | 1e9999 | 2','Bad | 1 | -2','Bad | 1.111 | 2','Bad | 1 | 2\nBad | 2 | 3']:
            with self.assertRaises(ValueError):catalog(text,'Packages')
        with self.assertRaises(ValueError):validate_options(dict(extras='Extra | 20 | 2'))
        self.assertEqual(catalog('Party | 120 | 2 | Painting | https://example.com/party.jpg','Packages')[0]['image'],'https://example.com/party.jpg')
        with self.assertRaises(ValueError):catalog('Party | 120 | 2 | Painting | javascript:bad','Packages')

    def test_revenue_sharing_percentage_is_validated_and_saved(self):
        form=self.fixture.create('booking')
        for percentage in ['', '7', '30']:
            data=self.booking_data(form)
            schedule=json.loads(data['event_schedule'])
            schedule['events'][0].update(charge_type='Revenue sharing',revenue_share_percent=percentage)
            data['event_schedule']=json.dumps(schedule)
            self.assertEqual(self.client.post('/booking',data=data).status_code,200)
        before=main.Booking.query.count()
        for percentage in ['5','10','15','20','25']:
            data=self.booking_data(form)
            schedule=json.loads(data['event_schedule'])
            schedule['events'][0].update(charge_type='Revenue sharing',revenue_share_percent=percentage)
            data['event_schedule']=json.dumps(schedule)
            with patch.object(main,'send_booking_request_confirmation',return_value=True):
                self.assertEqual(self.client.post('/booking',data=data).status_code,302)
            booking=main.Booking.query.order_by(main.Booking.id.desc()).first()
            self.assertEqual(json.loads(booking.event_schedule)['events'][0]['revenue_share_percent'],int(percentage))
            self.assertEqual(booking.total_event_cost,Decimal('0'))
        self.assertEqual(main.Booking.query.count(),before+5)

    def test_customers_pay_has_zero_client_cost(self):
        form=self.fixture.create('booking')
        data=self.booking_data(form)
        schedule=json.loads(data['event_schedule'])
        schedule['events'][0]['charge_type']='Customers'
        data['event_schedule']=json.dumps(schedule)
        with patch.object(main,'send_booking_request_confirmation',return_value=True):
            self.assertEqual(self.client.post('/booking',data=data).status_code,302)
        booking=main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertEqual(booking.total_event_cost,Decimal('0'))
        self.assertEqual(json.loads(booking.event_schedule)['events'][0]['estimated_cost'],'0.00')

    def test_booking_package_snapshots_captions_pdf_and_duplicate_flags(self):
        form=self.fixture.create('booking')
        self.options(form,packages='Party | 120 | 2 | Two hours',extras='Glitter | 15 | 0 | Sparkles')
        data=self.booking_data(form);data.update(dict(booking_package='Party',booking_extras='Glitter',design_captions='Photo 1: pink butterflies',travel_miles='12'))
        with patch.object(main,'send_booking_request_confirmation',return_value=True):
            response=self.client.post('/booking',data=data)
        self.assertEqual(response.status_code,302)
        booking=main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertEqual(booking.total_event_cost,Decimal('135'))
        options=json.loads(booking.event_schedule)['intake_options']
        self.assertEqual(options['design_captions'],'Photo 1: pink butterflies')
        self.assertEqual(options['travel_miles'],'0')
        path=f'/client/bookings/{booking.id}/pdf'
        pdf=self.client.get(path)
        self.assertEqual(pdf.status_code,200);self.assertTrue(pdf.data.startswith(b'%PDF-'))
        self.assertIn(b'pink butterflies',pdf.data);self.assertEqual(pdf.headers['Cache-Control'],'no-store')
        self.assertEqual(main.app.test_client().get(path).status_code,404)
        self.options(form,packages='Party | 999 | 2')
        self.assertIn(b'120',self.client.get(f'/client/bookings/{booking.id}').data)
        with patch.object(main,'send_booking_request_confirmation',return_value=True):self.client.post('/booking',data=self.booking_data(form))
        repeat=main.Booking.query.order_by(main.Booking.id.desc()).first()
        self.assertIn(booking.public_reference,json.loads(repeat.event_schedule)['intake_options']['possible_duplicates'])
        self.assertIn(b'Possible repeat request',self.admin.get('/admin/bookings').data)

    def test_cutoff_response_limit_and_waiting_list(self):
        form=self.fixture.create('giveaway')
        self.options(form,response_limit='1',waitlist_enabled='yes')
        payload=self.fixture.data(form)
        with patch('test_native_forms.main.send_client_email',return_value=True):
            self.client.post(f'/forms/{form.id}',data=payload)
        self.assertEqual(Submission.query.count(),1)
        response=self.client.get(f'/forms/{form.id}')
        self.assertTrue(response.location.endswith('/waiting-list'))
        self.client.get(response.location)
        with self.client.session_transaction() as state:csrf=state['client_csrf']
        path=f'/forms/{form.id}/waiting-list'
        payload=dict(csrf_token=csrf,name='Alex',email='forged@example.com',event_date='2099-02-01',details='Birthday party')
        self.assertEqual(self.client.post(path,data=payload).status_code,200)
        self.client.post(path,data=payload)
        self.assertEqual(Waiting.query.count(),1)
        self.assertNotEqual(Waiting.query.one().email,'forged@example.com')
        self.assertEqual(self.client.post(path,data=dict(payload,csrf_token='bad')).status_code,400)
        booking=self.fixture.create('booking');self.options(booking,cutoff_days='30')
        tomorrow=(datetime.now()+timedelta(days=1)).date().isoformat()
        with self.assertRaises(ValueError):main.app.extensions['form_workflows']['booking_check'](booking,[dict(date=tomorrow)],'alex@example.com')

    def test_block_library_permissions_validation_and_delete(self):
        self.assertEqual(main.app.test_client().get('/admin/form-blocks').status_code,302)
        fields=validate_fields([dict(label='Venue shelter',type='checkbox',required=True)])
        data=dict(csrf_token='admin-token',title='Venue checks',fields_json=json.dumps(fields))
        self.assertEqual(self.admin.post('/admin/form-blocks',data=data).status_code,201)
        self.assertEqual(self.admin.get('/admin/form-blocks').json['blocks'][0]['fields'][0]['label'],'Venue shelter')
        self.assertEqual(self.admin.post('/admin/form-blocks',data=dict(data,csrf_token='wrong')).status_code,400)
        self.assertEqual(self.admin.post('/admin/form-blocks',data=dict(data,fields_json='{}')).status_code,400)
        row=Template.query.one()
        self.assertEqual(self.admin.post(f'/admin/form-blocks/{row.id}/delete',data={'csrf_token':'admin-token'}).status_code,200)
        self.assertEqual(Template.query.count(),0)

    def test_analytics_only_accepts_progress_not_answers_and_admin_waitlist(self):
        form=self.fixture.create('giveaway',validate_fields([dict(label='Favourite design',type='text')]))
        self.options(form,waitlist_enabled='yes')
        self.client.get(f'/forms/{form.id}')
        with self.client.session_transaction() as state:csrf=state['client_csrf']
        route=f'/forms/{form.id}/activity'
        self.assertEqual(self.client.post(route,json={'steps':[0],'started':True},headers={'X-CSRF-Token':csrf}).status_code,200)
        self.client.post(route,json={'steps':[0],'started':True,'answers':'SECRET'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(Activity.query.count(),1);self.assertEqual(json.loads(Activity.query.one().steps_json),['Favourite design'])
        self.assertEqual(self.client.post(route,json={'steps':[99]},headers={'X-CSRF-Token':csrf}).status_code,400)
        self.assertEqual(self.client.post(route,json={'steps':[0]},headers={'X-CSRF-Token':'bad'}).status_code,400)
        entry=Waiting(form_id=form.id,email='alex@example.com',name='Alex');main.db.session.add(entry);main.db.session.commit()
        route=f'/admin/native-forms/{form.id}/insights'
        self.assertEqual(self.client.get(route).status_code,302)
        self.assertIn(b'Favourite design',self.admin.get(route).data)
        self.admin.post(route,data=dict(csrf_token='admin-token',id=entry.id,status='Contacted'))
        self.assertEqual(entry.status,'Contacted')

    def test_spam_and_pdf_owner_and_pagination(self):
        form=self.fixture.create('giveaway')
        payload=self.fixture.data(form);payload['contact_website']='https://spam.invalid'
        self.client.post(f'/forms/{form.id}',data=payload)
        self.assertEqual(Submission.query.count(),0)
        payload['contact_website']=''
        with patch.object(main,'send_client_email',return_value=True):self.client.post(f'/forms/{form.id}',data=payload)
        item=Submission.query.one()
        route=f'/forms/submissions/{item.token}/pdf'
        self.assertEqual(self.client.get(route).status_code,200)
        self.assertEqual(main.app.test_client().get(route).status_code,404)
        pdf=pdf_document(['Text (with parentheses) \\ and £']*100)
        self.assertIn(b'/Count 3',pdf);self.assertIn(b'\\(with parentheses\\)',pdf);self.assertTrue(pdf.endswith(b'%%EOF\n'))

    def test_admin_autosave_creates_and_updates_draft_and_detects_conflict(self):
        payload=dict(action='autosave',csrf_token='admin-token',kind='giveaway',title='Autosaved draft',terms='Giveaway rules',fields_json='[]')
        response=self.admin.post('/admin/native-forms',data=payload)
        self.assertEqual(response.status_code,200);identity=response.json['id'];revision=response.json['revision']
        form=main.db.session.get(Form,identity);self.assertFalse(form.enabled)
        payload.update(id=identity,revision=revision,title='Edited draft')
        response=self.admin.post('/admin/native-forms',data=payload)
        self.assertEqual(response.status_code,200);self.assertNotEqual(revision,response.json['revision'])
        payload['title']='Stale draft'
        self.assertEqual(self.admin.post('/admin/native-forms',data=payload).status_code,409)
        self.assertEqual(form.title,'Edited draft')
        payload['revision']=response.json['revision'];payload['title']=''
        self.assertEqual(self.admin.post('/admin/native-forms',data=payload).status_code,400)
        self.assertEqual(form.title,'Edited draft')
        self.assertEqual(self.client.post('/admin/native-forms',data=payload).status_code,302)

    def test_publish_checklist_rejects_invalid_form_and_expired_date(self):
        form=self.fixture.create('giveaway');form.enabled=False;form.terms='';main.db.session.commit()
        path=f'/admin/native-forms/{form.id}/checklist'
        self.assertFalse(self.admin.get(path).json['ready'])
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='toggle',id=form.id))
        self.assertFalse(form.enabled)
        form.terms='Rules';form.ends_at=datetime.utcnow()-timedelta(days=1);main.db.session.commit()
        self.assertTrue(any('passed' in error for error in self.admin.get(path).json['errors']))
        form.ends_at=None;form.fields_json=json.dumps([dict(label='Design',type='select',options=[])]);main.db.session.commit()
        self.assertFalse(self.admin.get(path).json['ready'])
        form.fields_json='[]';main.db.session.commit()
        self.assertTrue(self.admin.get(path).json['ready'])
        self.admin.post('/admin/native-forms',data=dict(csrf_token='admin-token',action='toggle',id=form.id))
        self.assertTrue(form.enabled)


if __name__=='__main__':unittest.main()
