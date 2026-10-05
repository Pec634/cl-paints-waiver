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
        self.assertIn(b'id="responsibleEmail"',self.admin.get('/kiosk/customer').data)
        self.assertEqual(item.phase,'waiver')
        self.assertIsNone(item.waiver_id)

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
