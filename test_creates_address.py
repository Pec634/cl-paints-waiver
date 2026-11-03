import os
import unittest
from unittest.mock import patch
import test_cl_creates as fixtures
import test_native_form_browser as browsers

main=fixtures.main


class CreatesAddressTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CreatesTest();self.fixture.setUp();self.client=self.fixture.client
    def tearDown(self):self.fixture.tearDown()

    def test_manual_entry_remains_available_without_maps_key(self):
        with patch.dict(os.environ,{'GOOGLE_MAPS_API_KEY':''}):page=self.client.get('/cl-creates')
        self.assertIn(b'type it into the fields below',page.data)
        self.assertIn(b'Address lookup is unavailable',page.data)
        self.assertNotIn(b'src="https://maps.googleapis.com',page.data)
        data=self.fixture.form();self.client.post('/cl-creates',data=data)
        self.assertIn('1 Test Road',self.fixture.Order.query.one().address)

    def test_complete_postage_address_is_saved_and_printed(self):
        data=self.fixture.form()
        data.update(address_line1='Rose Cottage',address_line2='Suite 4',address_street='Test Lane',village='Little Village',
            town='Sheffield',county='South Yorkshire',postcode='S1 1AA',country='United Kingdom')
        self.client.post('/cl-creates',data=data)
        order=self.fixture.Order.query.one()
        expected='Suite 4\nRose Cottage Test Lane\nLittle Village\nSheffield\nSouth Yorkshire\nS1 1AA\nUnited Kingdom'
        self.assertEqual(order.address,expected)
        page=self.fixture.admin.get(f'/admin/cl-creates/orders/{order.id}/shipping-label')
        self.assertEqual(page.status_code,200)
        self.assertIn(expected.encode(),page.data)

    def test_required_postage_fields_and_country_are_validated(self):
        data=self.fixture.form()
        for field in ('address_line1','address_street','town','county','postcode','country'):
            self.client.post('/cl-creates',data=dict(data,**{field:''}))
            self.assertEqual(self.fixture.Order.query.count(),0)
        self.client.post('/cl-creates',data=dict(data,country='France'))
        self.assertEqual(self.fixture.Order.query.count(),0)
        self.client.post('/cl-creates',data=dict(data,address_line2='',village=''))
        self.assertEqual(self.fixture.Order.query.count(),1)

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_suggestion_fills_fields_and_manual_override_is_preserved(self):
        with patch.dict(os.environ,{'GOOGLE_MAPS_API_KEY':'test-browser-key'}):page=self.client.get('/cl-creates')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const root=document.querySelector('[data-creates-address-lookup]');
            const form=document.getElementById('creates-form');
            assert(window.mapsLoads>0,'Load Google lookup automatically for delivery');

            await new Promise(resolve=>setTimeout(resolve,0));
            const widget=root.querySelector('test-creates-autocomplete');
            assert(widget && widget.includedRegionCodes[0]==='gb','Restrict lookup to UK');
            const components=[['street_number','42'],['route','Rainbow Road'],['subpremise','Flat 5'],['locality','Test village'],['postal_town','Sheffield'],['administrative_area_level_2','South Yorkshire'],['postal_code','S1 1AA'],['country','United Kingdom','GB']].map(([type,longText,shortText])=>({types:[type],longText,shortText:shortText||longText}));
            widget.dispatchEvent(Object.assign(new Event('gmp-select'),{placePrediction:{toPlace:()=>({addressComponents:components,fetchFields:async()=>{}})}}));
            await new Promise(resolve=>setTimeout(resolve,0));
            assert(form.elements.address_line1.value==='42'&&form.elements.address_street.value==='Rainbow Road','Fill house and street separately');
            assert(form.elements.address_line2.value==='Flat 5','Fill flat details');
            assert(form.elements.town.value==='Sheffield'&&form.elements.postcode.value==='S1 1AA','Fill town and postcode');
            assert(form.elements.village.value==='Test village'&&form.elements.county.value==='South Yorkshire','Fill village and county');
            assert(form.elements.country.value==='United Kingdom','Fill country');
            assert(!form.elements.mainland.checked,'Do not silently confirm mainland delivery');

            form.elements.address_line1.value='43 Manual Road';input(form.elements.address_line1);
            assert(!root.querySelector('[data-address-search-host]').hidden,'Google search stays visible alongside manual fields');
            assert(form.elements.address_line1.value==='43 Manual Road','Allow manual correction');
            assert(document.documentElement.scrollWidth<=innerWidth+1,'Address lookup fits phone');
        ''',width=390,setup='''
            window.mapsLoads=0;
            class TestCreatesAutocomplete extends HTMLElement{};
            customElements.define('test-creates-autocomplete',TestCreatesAutocomplete);
            window.google={maps:{importLibrary:async()=>{window.mapsLoads++;return {PlaceAutocompleteElement:TestCreatesAutocomplete};}}};
        ''')

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_lookup_failure_leaves_manual_address_and_delivery_validation(self):
        with patch.dict(os.environ,{'GOOGLE_MAPS_API_KEY':'test-browser-key'}):page=self.client.get('/cl-creates')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const root=document.querySelector('[data-creates-address-lookup]');
            const form=document.getElementById('creates-form');
            form.elements.address_line1.value='My manually entered street';

            await new Promise(resolve=>setTimeout(resolve,0));
            assert(form.elements.address_line1.value==='My manually entered street','Google failure must not erase manual input');
            assert(root.querySelector('[data-address-status]').textContent.includes('unavailable'),'Explain manual fallback');
            assert(form.elements.address_line1.required&&form.elements.postcode.required,'Keep required delivery fields');
            form.fulfilment.value='collection';change(form.fulfilment);
            assert(document.getElementById('shipping').disabled,'Collection must not require delivery address');
        ''',width=390,setup="window.google={maps:{importLibrary:async()=>{throw new Error('Maps unavailable');}}};")
