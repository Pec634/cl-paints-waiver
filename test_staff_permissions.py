"""PIN staff permissions at the real admin decorator and request boundaries."""
import ast
import json
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from flask import abort, redirect, request, session, url_for
import test_pos_library as fixtures
from staff_permissions import AREAS, OWNER_ONLY, permissions, required_area


class StaffPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PosLibraryTest();self.f.setUp()
        self.app,self.db,self.client=self.f.app,self.f.db,self.f.client
        # Compile the production decorator without importing unrelated integrations.
        tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admin_required')
        namespace=dict(app=self.app,wraps=wraps,datetime=datetime,abort=abort,redirect=redirect,
            request=request,session=session,url_for=url_for)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),namespace)
        decorator=namespace['admin_required']
        self.writes=[]
        for endpoint in ('admin_bookings','admin_dashboard','admin_settings','backups','admin_global_search'):
            def view():
                if request.method=='POST':self.writes.append(request.endpoint)
                return 'Allowed '+request.endpoint
            self.app.add_url_rule('/permission-test/'+endpoint,endpoint,decorator(view),methods=['GET','POST'])
        self.app.add_url_rule('/admin/future-feature','future_feature',lambda:'Private future data',methods=['GET','POST'])
        self.app.add_url_rule('/admin',endpoint='admin_dashboard')

    def tearDown(self):self.f.tearDown()

    def staff(self,grants,role='cashier'):
        person=self.f.named_staff(role,'staff-'+str(self.f.staff_models[0].query.count()))
        person.permissions_json=json.dumps(grants);self.db.session.commit();self.f.as_staff(person)
        return person

    def test_only_granted_pages_and_actions_run_and_owner_is_unchanged(self):
        person=self.staff(['bookings'])
        self.assertEqual(self.client.get('/permission-test/admin_bookings').status_code,200)
        self.assertEqual(self.client.post('/permission-test/admin_bookings').status_code,200)
        for route in ('admin_settings','backups','admin_global_search'):
            self.assertEqual(self.client.get('/permission-test/'+route).status_code,403)
            self.assertEqual(self.client.post('/permission-test/'+route).status_code,403)
        self.assertEqual(self.client.get('/admin/pos').status_code,403)
        self.assertEqual(self.client.post('/admin/future-feature').status_code,403)
        self.assertEqual(self.writes,['admin_bookings'])
        with self.client.session_transaction() as state:
            self.assertNotIn('admin_authenticated',state)
            state.clear();state.update(staff=True,admin_authenticated=True,client_csrf='token')
        for endpoint in ('admin_bookings','admin_settings','backups','admin_global_search'):
            self.assertEqual(self.client.get('/permission-test/'+endpoint).status_code,200)

    def test_permissions_change_immediately_and_staff_cannot_manage_accounts(self):
        person=self.staff(['pos','pos_manager','bookings'],role='manager')
        self.assertEqual(self.client.get('/permission-test/admin_bookings').status_code,200)
        self.assertEqual(self.client.get('/admin/pos/reconciliation').status_code,200)
        self.assertEqual(self.client.get('/admin/pos/staff').status_code,403)
        self.assertEqual(self.client.post('/admin/pos/staff',data={'csrf_token':'token','name':'Escalated','pin':'99','permissions_version':'1','permissions':['pos_manager']}).status_code,403)
        person.permissions_json='["pos"]';self.db.session.commit()
        self.assertEqual(self.client.get('/permission-test/admin_bookings').status_code,403)
        self.assertEqual(self.client.get('/admin/pos/reconciliation').status_code,403)
        self.assertEqual(self.client.get('/admin/pos').status_code,200)
        self.assertEqual(self.client.post('/admin/pos/library',data={'csrf_token':'token'}).status_code,403)
        person.enabled=False;self.db.session.commit()
        self.assertEqual(self.client.get('/admin/staff').status_code,302)
        with self.client.session_transaction() as state:self.assertNotIn('pos_staff_id',state)

    def test_owner_assigns_exact_permissions_and_can_clear_all(self):
        response=self.client.post('/admin/pos/staff',data=dict(csrf_token='token',name='Office',pin='0',enabled='yes',permissions_version='1',permissions=['bookings','calendar']))
        self.assertEqual(response.status_code,302)
        person=self.f.staff_models[0].query.one()
        self.assertEqual(permissions(person),{'bookings','calendar'})
        self.client.post('/admin/pos/staff',data=dict(csrf_token='token',staff_id=person.id,name='Office',pin='',enabled='yes',permissions_version='1'))
        self.assertEqual(permissions(person),set())
        self.client.post('/admin/pos/staff',data=dict(csrf_token='token',staff_id=person.id,name='Office',pin='',enabled='yes',permissions_version='1',permissions=['pos_manager']))
        self.assertEqual(permissions(person),{'pos','pos_manager'})
        self.client.post('/admin/pos/staff',data=dict(csrf_token='token',staff_id=person.id,name='Office',pin='',enabled='yes',permissions_version='1',permissions=['owner']))
        self.assertEqual(permissions(person),{'pos','pos_manager'})

    def test_pin_login_loads_only_assigned_workspace_and_nav(self):
        self.app.jinja_loader.loaders[0].mapping.pop('_admin_sidebar.html')
        person=self.staff(['bookings'])
        login=self.app.test_client();page=login.get('/admin/pos/staff/login')
        csrf=page.data.decode().split('name="csrf_token" value="')[1].split('"')[0]
        response=login.post('/admin/pos/staff/login',data={'csrf_token':csrf,'pin':'1'})
        self.assertTrue(response.location.endswith('/admin/staff'))
        page=login.get(response.location)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Bookings',page.data)
        self.assertIn(b'aria-label="Admin navigation"',page.data)
        self.assertIn(b'data-nav-group="Bookings &amp; events"',page.data)
        self.assertNotIn(b'Point of sale',page.data)
        self.assertNotIn(b'Backup',page.data)
        self.assertNotIn(b'Staff accounts',page.data)
        self.assertEqual(login.get('/permission-test/admin_dashboard').status_code,403)
        self.assertEqual(login.get('/admin').status_code,302)
        person.permissions_json='[]';self.db.session.commit()
        self.assertIn(b'No areas assigned',login.get('/admin/staff').data)

    def test_session_expiry_json_denial_and_unknown_routes_fail_closed(self):
        person=self.staff(['bookings'])
        self.assertEqual(self.client.get('/admin/future-feature',headers={'Accept':'application/json'}).status_code,403)
        with self.client.session_transaction() as state:state['pos_last_activity']=(datetime.utcnow()-timedelta(minutes=31)).timestamp()
        response=self.client.get('/permission-test/admin_bookings',headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,401)
        self.assertIn('PIN',response.json['error'])

    def test_legacy_accounts_remain_till_only_and_invalid_data_denies_access(self):
        person=self.staff([]);person.permissions_json=None
        self.assertEqual(permissions(person),{'pos'})
        person.role='manager';self.assertEqual(permissions(person),{'pos','pos_manager'})
        for value in ('{}','null','broken','[123]','["owner"]'):
            person.permissions_json=value;self.assertEqual(permissions(person),set())
        for endpoint in OWNER_ONLY:self.assertIsNone(required_area(endpoint))


if __name__=='__main__':unittest.main()
