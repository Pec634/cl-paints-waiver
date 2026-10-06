from datetime import datetime, timedelta
import re
import unittest
from unittest.mock import patch
import test_loyalty as fixtures

main = fixtures.main


class KioskTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.event, _ = self.fixture.event()
        self.admin = self.fixture.admin
        self.admin.get('/admin/kiosk')
        self.admin.post('/admin/kiosk', data=dict(csrf_token='admin-token', event_id=self.event.id, pin='583729'))
        with self.admin.session_transaction() as session: self.kiosk_id = session['kiosk_id']

    def tearDown(self):
        self.fixture.tearDown()

    def test_existing_kiosk_table_is_upgraded_without_losing_session(self):
        from kiosk import ensure_schema
        from sqlalchemy import text, inspect
        main.db.session.remove()
        with main.db.engine.begin() as connection:
            connection.execute(text('ALTER TABLE kiosk_session DROP COLUMN completed_at'))
        ensure_schema(main.db)
        ensure_schema(main.db)
        self.assertIn('completed_at', {column['name'] for column in inspect(main.db.engine).get_columns('kiosk_session')})
        self.assertIsNotNone(main.db.session.get(main.KioskSession, self.kiosk_id))
        self.assertEqual(self.admin.get('/kiosk/customer').status_code, 200)

    def test_guest_waiver_auto_reset_and_later_account_link(self):
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'I already have a waiver', page.data)
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        self.admin.post('/kiosk/new-waiver', data={'csrf_token':item.csrf})
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'id="responsibleEmail"', page.data)
        self.assertNotIn(b'Email my verification code', page.data)
        self.assertEqual(self.admin.post('/client/signup', data={}).status_code, 403)
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        data = dict(responsible_first_name='Kiosk', responsible_last_name='Customer', responsible_email=self.fixture.account.email,
            signature_text='Kiosk Customer', liability_acknowledged=True, responsible_authority=True, responsible_accuracy=True,
            participants=[dict(first_name='Alex',last_name='Customer',age=8,gender='Gender Neutral')])
        self.assertEqual(self.admin.post('/kiosk/submit',json=data).status_code,400)
        with patch.object(main.resend.Emails,'send',return_value={}) as send:
            response = self.admin.post('/kiosk/submit',json=data,headers={'X-CSRF-Token':item.csrf})
            self.assertEqual(send.call_args.args[0]['to'],[self.fixture.account.email])
        self.assertEqual(response.status_code,200)
        self.assertEqual(item.phase,'complete')
        self.assertEqual(main.db.session.get(main.Waiver,item.waiver_id).responsible_email,self.fixture.account.email)
        with self.admin.session_transaction() as session: self.assertNotIn('client_id',session)
        self.assertIn(b'Next customer in',self.admin.get('/kiosk/customer').data)
        self.assertEqual(self.admin.post('/kiosk/submit',json=data,headers={'X-CSRF-Token':item.csrf}).status_code,403)
        portal = self.fixture.client.get('/client/waivers')
        self.assertIn(main.db.session.get(main.Waiver,item.waiver_id).public_reference.encode(), portal.data)
        item.completed_at=datetime.utcnow()-timedelta(seconds=31)
        main.db.session.commit()
        self.assertIn(b'I already have a waiver',self.admin.get('/kiosk/customer').data)
        self.assertEqual(item.phase,'signup')
        self.assertIsNone(item.waiver_id)

    def test_id_lookup_is_member_only_and_rejects_wrong_or_expired_ids(self):
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        path = '/kiosk/lookup-id'
        self.assertEqual(self.admin.post(path, data={'reference':self.fixture.waiver.public_reference}).status_code,400)
        self.admin.post(path, data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'Alex Client',page.data)
        self.assertIn(b'Sam Client',page.data)
        self.assertNotIn(self.fixture.account.email.encode(),page.data)
        self.assertNotIn(b'Original signature',page.data)
        with self.admin.session_transaction() as state:
            self.assertNotIn('client_id',state)
        self.assertEqual(self.admin.get('/client/account').status_code,302)
        self.assertEqual(self.admin.post('/kiosk/confirm-members',data={'csrf_token':item.csrf,'member_id':'999999'}).status_code,400)
        self.admin.post('/kiosk/confirm-members',data={'csrf_token':item.csrf,'member_id':self.fixture.person.id})
        complete=self.admin.get('/kiosk/customer')
        self.assertIn(b'Waiver members confirmed',complete.data)
        self.assertIn(b'Alex Client',complete.data)
        self.assertNotIn(b'Sam Client',complete.data)
        item.completed_at=datetime.utcnow()-timedelta(seconds=31);main.db.session.commit()
        self.admin.get('/kiosk/customer')
        with self.admin.session_transaction() as state:
            self.assertNotIn('kiosk_waivers',state)
            self.assertNotIn('kiosk_selected_members',state)
        self.fixture.waiver.expiry_date=datetime.utcnow()-timedelta(days=1);main.db.session.commit()
        self.admin.post(path,data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        self.assertEqual(item.phase,'signup')
        self.assertNotIn(b'Alex Client',self.admin.get('/kiosk/customer').data)

    def test_forged_reference_dates_and_archived_waivers_are_rejected(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        reference=self.fixture.waiver.public_reference
        wrong_date=('01/01/2000' if not reference.startswith('01/01/2000') else '02/01/2000')+reference[10:]
        for value in (wrong_date, str(self.fixture.waiver.id)):
            self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':value})
            self.assertEqual(item.phase,'signup')
        self.fixture.waiver.is_archived=True;main.db.session.commit()
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':reference})
        self.assertEqual(item.phase,'signup')

    def test_email_lookup_verifies_without_portal_signin_and_members_timeout(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        main.ClientLoginCode.query.filter_by(email=self.fixture.account.email).delete();main.db.session.commit()
        with patch.object(main,'send_client_email',return_value=True) as send:
            self.admin.post('/kiosk/email-code',data={'csrf_token':item.csrf,'email':self.fixture.account.email})
            raw=re.search(r'code is (\d{6})',send.call_args.args[2]).group(1)
        self.assertIn(b'Check your email',self.admin.get('/kiosk/customer').data)
        self.admin.post('/kiosk/verify-email',data={'csrf_token':item.csrf,'code':'WRONG'})
        self.assertEqual(item.phase,'signup')
        self.admin.post('/kiosk/verify-email',data={'csrf_token':item.csrf,'code':raw})
        self.assertIn(b'Alex Client',self.admin.get('/kiosk/customer').data)
        with self.admin.session_transaction() as state:
            self.assertNotIn('client_id',state)
            state['kiosk_lookup_expires']=0
        self.assertEqual(self.admin.get('/kiosk/customer').status_code,302)
        self.assertEqual(item.phase,'signup')

    def test_transferred_members_and_lookup_throttle(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        Custodian=main.loyalty_models[3]
        target=self.fixture.make_waiver('someone@example.com','TARGET-KIOSK')
        main.db.session.add(Custodian(participant_id=self.fixture.person.id,client_id=self.fixture.account.id,waiver_id=target.id));main.db.session.commit()
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        page=self.admin.get('/kiosk/customer')
        self.assertNotIn(b'Alex Client',page.data)
        self.assertIn(b'Sam Client',page.data)
        self.admin.post('/kiosk/start-over',data={'csrf_token':item.csrf})
        for _ in range(10):
            self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':'NOT-FOUND'})
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        self.assertEqual(item.phase,'signup')
        self.assertIn(b'Please wait a minute',self.admin.get('/kiosk/customer').data)

    def test_pin_exit_route_guard_lockout_and_reset_removed(self):
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        self.assertEqual(self.admin.get('/admin/bookings').status_code,302)
        self.assertEqual(self.admin.post('/client/logout',data={}).status_code,403)
        self.assertEqual(self.admin.post('/kiosk/staff',data=dict(pin='583729',action='exit')).status_code,400)
        for _ in range(5): self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='0000',action='exit'))
        self.assertIsNotNone(item.locked_until)
        self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='583729',action='exit'))
        self.assertEqual(item.phase,'signup')
        item.locked_until=datetime.utcnow()-timedelta(seconds=1)
        main.db.session.commit()
        self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='583729',action='exit'))
        self.assertEqual(item.phase,'closed')
        self.assertEqual(self.admin.get('/admin/bookings').status_code,200)
        self.assertNotIn(b'staffResetButton',self.fixture.client.get(f'/waiver/event/{self.event.id}').data)

    def test_normal_admin_pages_do_not_require_kiosk_table(self):
        from sqlalchemy import text
        with main.db.engine.begin() as connection:
            connection.execute(text('DROP TABLE kiosk_session'))
        admin = main.app.test_client()
        with admin.session_transaction() as session: session['admin_authenticated'] = True
        self.assertEqual(admin.get('/admin/bookings').status_code,200)
        self.assertEqual(admin.get('/admin/dashboard').status_code,200)


if __name__ == '__main__': unittest.main()
