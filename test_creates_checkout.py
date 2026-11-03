import json
import os
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import test_cl_creates as fixtures
import test_native_form_browser as browser_helpers
from creates_collection import parse_calendar

main = fixtures.main


class CreatesCheckoutTest(unittest.TestCase):
    @unittest.skipUnless(browser_helpers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_fixed_coils_and_word_mounting(self):
        browser_helpers.NativeFormBrowserTest().browser(self.client.get('/cl-creates').data, '''
            const wording=document.querySelector('[name=wording]');
            const shape=document.querySelector('[name=word_shape]');
            const render=value=>{window.coilPaths=[];window.paintedLetters=[];wording.value=value;input(wording);};
            shape.value='';render('TEAM BRIDE');
            const fixed=JSON.stringify(window.coilPaths);
            assert(new Set(window.coilPaths.map(path=>path[0])).size===2,'Exactly two spring positions required');
            assert(window.paintedLetters.map(letter=>letter[0]).join('')==='TEAMBRIDE','Words must retain typed order');
            const left=window.paintedLetters.slice(0,4),right=window.paintedLetters.slice(4);
            assert(Math.max(...left.map(letter=>letter[1]))<Math.min(...right.map(letter=>letter[1])),'Words must occupy separate coils');
            assert(right[0][2]-left[left.length-1][3]>4,'Two-word designs must retain a gap between words');
            shape.value='Heart';render('LOVE MY TEAM');
            assert(JSON.stringify(window.coilPaths)===fixed,'Changing words must not change the coils');
            assert(window.paintedLetters.map(letter=>letter[0]).join('')==='LOVEMYTEAM','Suspended word must remain in the middle');
            const label=document.querySelector('.headband-preview canvas').getAttribute('aria-label');
            assert(label.includes('Left coil: LOVE.')&&label.includes('Suspended middle word: MY')&&label.includes('Right coil: TEAM.'),'Mounting description must match design');
            const colour=document.querySelector('[name=background_colour]');colour.value='Blue';change(colour);
            window.coilPaths=[];input(wording);
            assert(JSON.stringify(window.coilPaths)===fixed,'Design colours must not change spring hardware');
            for(const sample of ['LETS GO STEELERS','STEELERS GO LETS']){
                render(sample);
                const words=sample.split(' '),letters=window.paintedLetters;
                const first=letters.slice(0,words[0].length),last=letters.slice(-words[2].length);
                const bounds=group=>[Math.min(...group.map(letter=>letter[2])),Math.max(...group.map(letter=>letter[3]))];
                const a=bounds(first),b=bounds(last);
                assert(letters.every(letter=>Math.abs(letter[4]-letters[0][4])<0.001&&Math.abs(letter[4]-letter[5])<0.001),'Every word must use the same undistorted letter size');
                assert(Math.abs((a[0]+b[1])/2-800)<8,'Lettering must be centred over the headband');
                assert(letters[0][6]<0&&letters[letters.length-1][6]>0,'Lettering must follow the headband curve');
            }
            colour.value='Black';render('LETS GO STEELERS');
            const blackLayout=JSON.stringify(window.paintedLetters);
            for(const option of colour.options){
                colour.value=option.value;render('LETS GO STEELERS');
                assert(JSON.stringify(window.paintedLetters)===blackLayout,'Backing colour must preserve black padding and placement: '+option.value);
            }
        ''',setup='''
            window.coilPaths=[];window.paintedLetters=[];
            const ellipse=CanvasRenderingContext2D.prototype.ellipse,fillText=CanvasRenderingContext2D.prototype.fillText;
            CanvasRenderingContext2D.prototype.ellipse=function(...args){
                if(this.canvas.closest('.headband-preview'))window.coilPaths.push(args);
                return ellipse.apply(this,args);
            };
            CanvasRenderingContext2D.prototype.fillText=function(...args){
                if(this.canvas.closest('.headband-preview')&&args[0].length===1){
                    const transform=this.getTransform(),metrics=this.measureText(args[0]);
                    window.paintedLetters.push([args[0],transform.e,
                        transform.e-(metrics.actualBoundingBoxLeft+5.5)*transform.a,
                        transform.e+(metrics.actualBoundingBoxRight+5.5)*transform.a,Math.hypot(transform.a,transform.b),Math.hypot(transform.c,transform.d),transform.b]);
                }
                return fillText.apply(this,args);
            };
        ''')

    def setUp(self):
        self.fixture=fixtures.CreatesTest();self.fixture.setUp()
        self.client=self.fixture.client;self.admin=self.fixture.admin
        self.Order,self.Message,_,_=main.creates_models
        self.env=patch.dict(os.environ,{'SUMUP_API_KEY':'test','SUMUP_MERCHANT_CODE':'TEST'});self.env.start()
        self.status='PENDING'

    def tearDown(self):
        self.env.stop();self.fixture.tearDown()

    def provider(self,path,payload=None):
        order=self.Order.query.one()
        data=dict(id='abc123',checkout_reference='CC-'+order.checkout_token,merchant_code='TEST',currency='GBP',
            amount=str(order.total),status=self.status,hosted_checkout_url='https://checkout.sumup.com/pay/abc123')
        return [data] if path.startswith('checkouts?') else data

    def draft(self,**changes):
        data=self.fixture.form();data.update(background_colour='Blue',bold_colour='Pink',colour='White',letter_finish='Glitter',glitter_colour='Gold')
        data.update(changes)
        response=self.client.post('/cl-creates',data=data)
        return response,self.Order.query.order_by(self.Order.id.desc()).first()

    def checkout(self,order):
        with self.client.session_transaction() as state:token=state['creates_csrf']
        with patch('creates_payments.provider_request',side_effect=self.provider) as provider:
            response=self.client.post(f'/cl-creates/payment/{order.checkout_token}',data={'csrf_token':token})
        return response,provider

    def test_paid_confirmation_requires_provider_and_is_sent_once(self):
        response,order=self.draft(amount='0.01')
        page=self.client.get(response.location)
        self.assertNotIn(order.number.encode(),page.data)
        self.assertEqual(self.Message.query.count(),0)
        self.assertEqual(order.total,Decimal('16'))
        response,provider=self.checkout(order)
        self.assertEqual(response.location,'https://checkout.sumup.com/pay/abc123')
        self.assertEqual(provider.call_args.args[1]['amount'],16.0)
        self.status='PAID'
        with patch('creates_payments.provider_request',side_effect=self.provider):
            self.client.post(f'/cl-creates/payment-callback/{order.checkout_token}',json={'status':'FAILED'})
            self.client.post(f'/cl-creates/payment-callback/{order.checkout_token}')
            page=self.client.get(f'/cl-creates/payment/{order.checkout_token}')
        main.db.session.refresh(order)
        self.assertEqual(order.paid,Decimal('16'))
        self.assertIn(order.number.encode(),page.data)
        self.assertEqual(self.Message.query.count(),1)
        self.assertIn('/cl-creates/payment/',self.Message.query.one().body)
        self.assertEqual(order.items[0]['background_colour'],'Blue')
        self.assertEqual(order.items[0]['bold_colour'],'Pink')

    def test_forged_callback_wrong_merchant_currency_amount_and_reference_do_not_confirm(self):
        _,order=self.draft();self.checkout(order)
        for field,value in [('merchant_code','WRONG'),('amount','0.01'),('currency','EUR'),('checkout_reference','CC-other')]:
            data=self.provider('checkouts/abc123');data.update(status='PAID');data[field]=value
            with patch('creates_payments.provider_request',return_value=data):
                response=self.client.post(f'/cl-creates/payment-callback/{order.checkout_token}',json={'status':'PAID'})
            self.assertEqual(response.status_code,503)
            main.db.session.refresh(order);self.assertEqual(order.paid,0)
        self.assertEqual(self.Message.query.count(),0)

    def test_admin_dashboard_recovers_missed_callback_once(self):
        _,order=self.draft();self.checkout(order)
        self.status='PAID'
        with patch('creates_payments.provider_request',side_effect=self.provider) as provider:
            self.assertEqual(self.admin.get('/admin/cl-creates').status_code,200)
            self.assertEqual(self.admin.get(f'/admin/cl-creates/orders/{order.id}').status_code,200)
        main.db.session.refresh(order)
        self.assertEqual(order.paid,order.total)
        self.assertEqual(order.status,'Paid')
        self.assertEqual(self.Message.query.count(),1)
        self.assertEqual(provider.call_count,1)

    def test_automatic_sync_does_not_assign_another_orders_payment(self):
        _,order=self.draft();self.checkout(order)
        data=self.provider('checkouts/abc123')
        data.update(status='PAID',checkout_reference='CC-another-order')
        with patch('creates_payments.provider_request',return_value=data):
            self.assertEqual(self.admin.get('/admin/cl-creates').status_code,200)
        main.db.session.refresh(order)
        self.assertEqual(order.paid,0)
        self.assertEqual(self.Message.query.count(),0)

    def test_order_view_recovers_checkout_identity_and_preserves_production_status(self):
        _,order=self.draft();self.checkout(order)
        order.provider_id=None
        main.db.session.commit()
        self.status='PAID'
        with patch('creates_payments.provider_request',side_effect=self.provider):
            self.admin.get(f'/admin/cl-creates/orders/{order.id}')
        main.db.session.refresh(order)
        self.assertEqual(order.provider_id,'abc123')
        self.assertEqual(order.paid,order.total)
        order.status='In production';main.db.session.commit()
        with patch('creates_payments.provider_request') as provider:
            self.admin.get('/admin/cl-creates')
            provider.assert_not_called()
        self.assertEqual(order.status,'In production')

    def test_scheduled_sync_reports_provider_failure_without_recording_payment(self):
        _,order=self.draft();self.checkout(order)
        with patch('creates_payments.provider_request',side_effect=ValueError('Unavailable')):
            result=main.app.test_cli_runner().invoke(args=['sync-creates-payments'])
        self.assertNotEqual(result.exit_code,0)
        self.assertIn(order.number,result.output)
        main.db.session.refresh(order)
        self.assertEqual(order.paid,0)

    def test_pending_and_failed_payment_never_show_confirmation_or_send_email(self):
        response,order=self.draft();self.checkout(order)
        for status in ('PENDING','FAILED'):
            self.status=status
            with patch('creates_payments.provider_request',side_effect=self.provider):
                page=self.client.get(f'/cl-creates/payment/{order.checkout_token}')
            self.assertNotIn(order.number.encode(),page.data)
            self.assertEqual(self.Message.query.count(),0)
        self.assertEqual(self.client.post(response.location,data={}).status_code,400)
        self.assertEqual(main.app.test_client().get('/cl-creates/payment/not-real').status_code,404)

    def test_spaces_require_selected_shape_before_checkout(self):
        response,order=self.draft(wording='HELLO',word_shape='')
        self.assertIsNone(order)
        self.assertIn(b'at least two words',response.data)
        response,order=self.draft(wording='A B C',word_shape='')
        self.assertIsNone(order)
        self.assertIn(b'Choose a separator shape',response.data)
        response,order=self.draft(wording='A B C',word_shape='Star')
        self.assertEqual(order.items[0]['word_shape'],'Star')
        self.assertEqual(order.items[0]['wording'],'A B C')
        response,order=self.draft(wording='TWO WORDS',word_shape='')
        self.assertIsNotNone(order)
        self.assertEqual(order.items[0]['word_shape'],'')

    def test_sixteen_character_limit_excludes_spaces(self):
        response,order=self.draft(wording='ABCDEFGHI JKLMNOPQ',word_shape='')
        self.assertIsNone(order)
        self.assertIn(b'16 characters',response.data)
        response,order=self.draft(wording='ABCDEFGH IJKLMNOP',word_shape='')
        self.assertIsNotNone(order)
        self.assertEqual(order.items[0]['wording'],'ABCDEFGH IJKLMNOP')

    @unittest.skipUnless(browser_helpers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_shape_selection_required_for_spaces_and_preview_updates(self):
        browser_helpers.NativeFormBrowserTest().browser(self.client.get('/cl-creates').data, '''
            const line=document.querySelector('.creates-line');
            const wording=line.querySelector('[name=wording]'),shape=line.querySelector('[name=word_shape]');
            wording.value='A B C';input(wording);
            assert(shape.required&&!shape.checkValidity(),'A space must require a chosen shape');
            assert(shape.getAttribute('aria-invalid')==='true'&&shape.closest('label').classList.contains('creates-shape-warning'),'Missing shape must flag red immediately');
            assert(!line.querySelector('[data-shape-warning]').hidden,'Show an explanation alongside the red warning');
            shape.value='Star';change(shape);
            assert(shape.checkValidity(),'Selected shape satisfies validation');
            assert(shape.getAttribute('aria-invalid')==='false'&&!shape.closest('label').classList.contains('creates-shape-warning'),'Clear red warning after choosing a shape');
            assert(line.querySelector('canvas').getAttribute('aria-label').includes('Star between words'),'Preview uses selected separator');
            wording.value='ABC';input(wording);
            assert(!shape.required,'Single-word wording does not require a separator');
            assert(!wording.checkValidity(),'Single-word wording must be rejected');
            shape.value='';wording.value='TWO WORDS';input(wording);
            assert(!shape.required&&shape.checkValidity(),'Two words may use plain spaces');
            assert(line.querySelector('[data-shape-warning]').hidden,'Two words must not show a red warning');
        ''',width=390)

    def test_official_calendar_import_idempotent_and_changes_preserve_order_snapshot(self):
        raw=(Path(__file__).parent/'assets'/'steelers-home-fixtures.ics').read_bytes().decode()
        rows=parse_calendar(raw)
        self.assertGreater(len(rows),20)
        self.assertTrue(all('Steelers' in row['title'] for row in rows))
        self.assertTrue(any('S9 2DF' in row['venue'] for row in rows))
        sync=main.app.extensions['creates_collection_sync'];sync(raw);sync(raw)
        self.assertEqual(main.CreatesCollectionSlot.query.count(),len(rows))
        slot=main.CreatesCollectionSlot.query.first();slot.starts_at=datetime.utcnow()+timedelta(days=14);slot.ends_at=slot.starts_at+timedelta(hours=3);main.db.session.commit()
        response,order=self.draft(fulfilment='collection',collection_slot_id=slot.id)
        self.assertEqual(order.total,Decimal('10'))
        snapshot=order.collection_snapshot
        slot.starts_at += timedelta(days=1);main.db.session.commit()
        page,_=self.checkout(order)
        self.assertIn(b'collection game changed',page.data)
        self.assertEqual(order.collection_snapshot,snapshot)
        self.assertFalse(order.checkout_started)

    def test_seven_day_notice_and_unavailable_slot_validation(self):
        slot=main.CreatesCollectionSlot(uid='test',title='Steelers vs Test',starts_at=datetime.utcnow()+timedelta(days=3),
            ends_at=datetime.utcnow()+timedelta(days=3,hours=3),venue='Arena')
        main.db.session.add(slot);main.db.session.commit()
        response,order=self.draft(fulfilment='collection',collection_slot_id=slot.id)
        self.assertIsNone(order)
        self.assertIn(b'available home game',response.data)
        slot.starts_at=datetime.utcnow()+timedelta(days=14);slot.ends_at=slot.starts_at+timedelta(hours=3);slot.enabled=False;main.db.session.commit()
        self.draft(fulfilment='collection',collection_slot_id=slot.id)
        self.assertEqual(self.Order.query.count(),0)

    def test_calendar_shares_home_games_without_blocking_face_painting(self):
        slot=main.CreatesCollectionSlot(uid='test',title='Steelers vs Test',starts_at=datetime.utcnow()+timedelta(days=14),
            ends_at=datetime.utcnow()+timedelta(days=14,hours=3),venue='Arena')
        main.db.session.add(slot);main.db.session.commit()
        rows=[row for row in main.app.extensions['calendar_rows']() if row.get('collection')]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['conflicts'],[])
        self.assertEqual(self.admin.get('/admin/calendar').status_code,200)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_letter_backings_do_not_overlap_and_zoom_works_for_cloned_lines(self):
        browser_helpers.NativeFormBrowserTest().browser(self.client.get('/cl-creates').data, '''
            const line=document.querySelector('.creates-line');
            const wording=line.querySelector('[name=wording]');
            for(const sample of ['HI','YOUR WORDS','WWWWWWWWWWW','IIIIIIIIIII','WIWIWIWIWIW','TEAM BRIDE']) {
                wording.value=sample;input(wording);
                assert(window.previewOverlap===0,'Bold outline pixels overlap for '+sample);
                if(sample==='HI')assert(window.backingContacts>0,'Backing edges must actually touch, without bridging distant glyphs');
                let letterIndex=0;
                for(const word of sample.split(' ')){
                    for(let index=0;index<word.length;index++,letterIndex++){
                        if(index)assert(window.backingPerGlyph[letterIndex]>0,'Curved backing gap within '+sample+' at letter '+letterIndex);
                        else assert(window.backingPerGlyph[letterIndex]===0,'Words must remain separate');
                    }
                }
            }
            const viewport=line.querySelector('.headband-preview-viewport');
            viewport.dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));
            assert(viewport.classList.contains('is-hoverzoom'),'Hover activates zoom');
            viewport.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'}));
            assert(!viewport.classList.contains('is-hoverzoom'),'Leaving restores preview');
            assert(!line.querySelector('[data-preview-zoom]'),'No zoom preview button');
            document.getElementById('add-line').click();
            const cloned=document.querySelectorAll('.creates-line')[1];
            cloned.querySelector('.headband-preview-viewport').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));
            assert(cloned.querySelector('.headband-preview-viewport').classList.contains('is-hoverzoom'),'New headband lines have working hover zoom');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Zoom must stay inside preview');
        ''',width=390,setup='''
            window.previewOverlap=0;
            window.backingContacts=0;
            const originalStroke=CanvasRenderingContext2D.prototype.strokeText;
            const originalClear=CanvasRenderingContext2D.prototype.clearRect;
            const masks=new WeakMap();
            CanvasRenderingContext2D.prototype.clearRect=function(...args){
                if(this.canvas.closest('.headband-preview')){masks.set(this.canvas,{inner:new Uint8Array(this.canvas.width*this.canvas.height),backing:new Uint8Array(this.canvas.width*this.canvas.height)});window.previewOverlap=0;window.backingContacts=0;window.backingPerGlyph=[];}
                return originalClear.apply(this,args);
            };
            CanvasRenderingContext2D.prototype.strokeText=function(text,x,y){
                if(this.canvas.closest('.headband-preview') && [7,11].includes(this.lineWidth)){
                    const mask=document.createElement('canvas');mask.width=this.canvas.width;mask.height=this.canvas.height;
                    const paint=mask.getContext('2d');paint.setTransform(this.getTransform());
                    for(const key of ['font','textAlign','textBaseline','lineWidth','lineJoin','lineCap'])paint[key]=this[key];
                    paint.strokeStyle='white';paint.fillStyle='white';
                    originalStroke.call(paint,text,x,y);paint.fillText(text,x,y);
                    const pixels=paint.getImageData(0,0,mask.width,mask.height).data;
                    const occupied=this.lineWidth===7?masks.get(this.canvas).inner:masks.get(this.canvas).backing;
                    const before=window.backingContacts;
                    for(let index=0;index<occupied.length;index++)if(pixels[index*4+3]>127){if(occupied[index]){if(this.lineWidth===7)window.previewOverlap++;else window.backingContacts++;}occupied[index]=1;}
                    if(this.lineWidth===11)window.backingPerGlyph.push(window.backingContacts-before);
                }
                return originalStroke.call(this,text,x,y);
            };
        ''')

    @unittest.skipUnless(browser_helpers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_live_layers_and_collection_picker_work_on_phone(self):
        slot=main.CreatesCollectionSlot(uid='test',title='Steelers vs Test',starts_at=datetime.utcnow()+timedelta(days=14),
            ends_at=datetime.utcnow()+timedelta(days=14,hours=3),venue='Arena')
        main.db.session.add(slot);main.db.session.commit()
        browser_helpers.NativeFormBrowserTest().browser(self.client.get('/cl-creates').data, '''
            const line=document.querySelector('.creates-line');
            const canvas=line.querySelector('canvas');const before=canvas.toDataURL();
            line.querySelector('[name=background_colour]').value='Blue';input(line.querySelector('[name=background_colour]'));
            line.querySelector('[name=bold_colour]').value='Pink';input(line.querySelector('[name=bold_colour]'));
            assert(canvas.toDataURL()!==before,'Layer edits must change preview pixels');
            assert(canvas.getAttribute('aria-label').includes('Blue background')&&canvas.getAttribute('aria-label').includes('Pink bold'),'Describe each layer');
            const form=document.getElementById('creates-form');form.fulfilment.value='collection';change(form.fulfilment);
            const root=document.getElementById('collection');assert(!root.hidden&&!root.disabled,'Show collection calendar');
            root.querySelector('[data-collection-calendar] button:not([disabled])').click();
            assert(form.elements.collection_slot_id.value!=='','Clicking a game selects it');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Checkout fits phone');
        ''',width=390)
