"""Exercise staff grants through the complete registered portal, without real email/payments."""
import json
import re
import unittest
from datetime import datetime
from werkzeug.security import generate_password_hash
import test_client_portal as fixtures
from staff_permissions import AREAS
from test_admin_polish_browser import BrowserChecks, EDGE

main=fixtures.main

def url_for(endpoint):
    return main.app.url_map.bind('localhost').build(endpoint,{})


class StaffPortalIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ClientPortalTest();self.f.setUp()
        self.access=main.app.extensions['pos_access']
        digest=generate_password_hash('0')
        self.person=self.access.Staff(username='permissions-test',name='Staff Example',role='cashier',
            enabled=True,password_hash=digest,pin_hash=digest,pin_digest=self.access.pin_digest('0'),permissions_json='[]')
        main.db.session.add(self.person);main.db.session.commit()
        self.client=main.app.test_client()

    def tearDown(self):self.f.tearDown()

    def grants(self,*grants):
        self.person.permissions_json=json.dumps(grants);main.db.session.commit()
        with self.client.session_transaction() as state:
            state.clear();state.update(pos_staff_id=self.person.id,pos_last_activity=datetime.utcnow().timestamp(),
                pos_signed_in_at=datetime.utcnow().timestamp(),client_csrf='test-token')

    def test_main_admin_login_accepts_staff_pin(self):
        login = self.client.get('/admin/login')
        self.assertEqual(login.status_code, 200)
        self.assertIn(b'name="pin"', login.data)
        self.assertNotIn(b'name="password"', login.data)
        self.assertIn(b'href="/admin/owner-login"', login.data)
        with self.client.session_transaction() as state:
            token = state['pos_login_csrf']
        signed_in = self.client.post('/admin/login', data={'pin': '0', 'csrf_token': token})
        self.assertEqual(signed_in.location, url_for('staff_portal_home'))
        self.assertEqual(self.client.get(url_for('pos_staff_manage')).status_code, 403)

    def test_every_assignable_area_loads_without_owner_privileges(self):
        for key,label,endpoint,description in AREAS:
            with self.subTest(area=key):
                self.grants(*(['pos','pos_manager'] if key=='pos_manager' else [key]))
                path=url_for(endpoint)
                response=self.client.get(path)
                self.assertIn(response.status_code,(200,302),f'{path}: {response.status_code}')
                with self.client.session_transaction() as state:self.assertNotIn('admin_authenticated',state)

    def test_all_areas_block_without_grants_and_owner_routes_stay_private(self):
        self.grants()
        for key,label,endpoint,description in AREAS:
            with self.subTest(area=key):self.assertEqual(self.client.get(url_for(endpoint)).status_code,403)
        self.grants(*(row[0] for row in AREAS))
        for endpoint in ('pos_staff_manage','admin_settings','backups','admin_global_search'):
            with self.subTest(owner_area=endpoint):self.assertEqual(self.client.get(url_for(endpoint)).status_code,403)

    def test_staff_navigation_contains_only_assigned_areas(self):
        self.grants('bookings')
        response=self.client.get(url_for('admin_bookings'))
        self.assertEqual(response.status_code,200)
        nav=re.search(r'<aside>.*?<nav[^>]*>(.*?)</nav>',response.get_data(as_text=True),re.S)
        self.assertIsNotNone(nav)
        self.assertEqual(re.findall(r'<a[^>]*>(.*?)</a>',nav.group(1)),['My workspace','Bookings'])
        self.assertIn('data-nav-group="Bookings &amp; events"', nav.group(1))
        self.assertNotIn(b'portal-admin-toolbar',response.data)

    def test_email_template_grant_cannot_change_owner_account(self):
        self.grants('email_templates')
        self.assertEqual(self.client.get(url_for('communications_templates')).status_code,200)
        response=self.client.post(url_for('communications_templates'),data={'section':'account','new_password':'not-permitted'})
        self.assertEqual(response.status_code,403)

    def test_private_invoice_and_form_files_check_staff_scope_and_client_owner(self):
        account=self.f.signup()
        booking=self.f.booking(account.email)
        document=main.InvoiceDocument(booking_id=booking.id,filename='private.pdf',mime='application/pdf',content=b'%PDF-private')
        file_model=main.db._native_extra_models[-1]
        file=file_model(booking_id=booking.id,label='Booking attachment',filename='details.txt',mime='text/plain',content=b'Private booking details')
        main.db.session.add_all([document,file]);main.db.session.commit()
        invoice_path=f'/invoice-documents/{document.id}'
        file_path=f'/form-files/{file.id}'
        self.grants('payments')
        self.assertEqual(self.client.get(invoice_path).status_code,200)
        self.assertEqual(self.client.get(file_path).status_code,403)
        self.grants('bookings')
        self.assertEqual(self.client.get(invoice_path).status_code,403)
        self.assertEqual(self.client.get(file_path).status_code,200)
        self.grants('forms')
        self.assertEqual(self.client.get(file_path).status_code,403)
        for path in (invoice_path,file_path):
            self.assertEqual(self.f.client.get(path).status_code,200)
            self.assertEqual(main.app.test_client().get(path).status_code,404)

    def test_staff_handover_records_named_operator(self):
        self.grants('handovers')
        path='/admin/handovers'
        # Resolve the actual registered path rather than assuming its spelling.
        path=url_for('admin_daily_handovers')
        self.client.get(path)
        with self.client.session_transaction() as state:token=state['client_csrf']
        response=self.client.post(path,data=dict(csrf_token=token,action='draft',manager_name='Shift lead',version='',handover_date=datetime.utcnow().date().isoformat()))
        self.assertEqual(response.status_code,302)
        model=main.db.Model.registry._class_registry.get('DailyHandover')
        self.assertEqual(model.query.one().recorded_by,'Staff Example')

    @unittest.skipUnless(EDGE.is_file(),'Edge is not installed')
    def test_permission_editor_and_staff_navigation_fit_phone(self):
        owner=main.app.test_client()
        with owner.session_transaction() as state:state.update(admin_authenticated=True,admin_last_activity=datetime.utcnow().timestamp())
        markup=owner.get(url_for('pos_staff_manage')).data
        BrowserChecks.browser(self,markup,'''
            const form=document.querySelector('form:has(input[name=permissions_version])');
            assert(form,'permission editor missing');
            const choices=[...form.querySelectorAll('input[name=permissions]')];
            assert(choices.length===30,'portal areas missing from editor');
            choices.forEach(field=>{field.checked=field.value==='bookings';});
            form.querySelector('input[name=pin]').value='0';
            const data=new FormData(form);
            assert(data.getAll('permissions').join(',')==='bookings','form grants unchecked areas');
            assert(data.get('pin')==='0','single digit PIN is not accepted');
            assert(document.documentElement.scrollWidth<=innerWidth,'permission editor overflows phone');
        ''',width=390)
        self.grants('bookings')
        markup=self.client.get('/admin/staff').data
        BrowserChecks.browser(self,markup,'''
            const menu=document.querySelector('.admin-menu-toggle');
            assert(menu,'staff mobile navigation is unavailable');
            menu.click();
            const nav=document.querySelector('#admin-tool-navigation');
            const groups=[...nav.querySelectorAll('.admin-navigation-group')];
            assert(groups.length===1,'unassigned groups appear in staff menu');
            assert(groups[0].querySelector('summary').textContent==='Bookings & events','staff group differs from owner menu');
            assert([...groups[0].querySelectorAll('a')].map(link=>link.textContent).join(',')==='Bookings','wrong staff areas displayed');
            assert(!document.getElementById('portal-admin-toolbar'),'owner quick actions exposed');
            assert(document.documentElement.scrollWidth<=innerWidth,'staff workspace overflows phone');
        ''',width=390)


if __name__=='__main__':unittest.main()
