from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from zoneinfo import ZoneInfo
import test_loyalty as loyalty_tests
from restore_database import validate, restore

main=loyalty_tests.main
Plan, Entry, Block, Workflow, Reminder, Correction=main.tool_models

class BusinessToolsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=loyalty_tests.LoyaltyTest()
        self.fixture.setUp()
        self.admin=self.fixture.admin
        self.client=self.fixture.client
        self.booking=self.fixture.fixture.booking(self.fixture.account.email,total_event_cost=Decimal('100'))

    def tearDown(self):
        self.fixture.tearDown()

    def payment_form(self):
        self.assertEqual(self.admin.get(f'/admin/bookings/{self.booking.id}/payments').status_code,200)
        with self.admin.session_transaction() as session:
            return dict(csrf_token=session['client_csrf'],entry_token=session[f'payment_entry_{self.booking.id}'])

    def test_payment_deposit_refund_idempotency_and_client_privacy(self):
        path=f'/admin/bookings/{self.booking.id}/payments'
        token=self.payment_form()
        data=dict(token,action='entry',kind='payment',amount='25.00',method='SumUp',note='INTERNAL PAYMENT NOTE',paid_date=datetime.now(ZoneInfo('Europe/London')).date().isoformat())
        self.assertEqual(self.admin.post(path,data=data).status_code,302)
        self.admin.post(path,data=data)
        self.assertEqual(Entry.query.count(),1)
        summary=main.app.extensions['payment_summary'](self.booking)
        self.assertEqual(summary['outstanding'],Decimal('75'))
        detail=self.client.get(f'/client/bookings/{self.booking.id}')
        self.assertIn(b'75.00',detail.data)
        self.assertNotIn(b'INTERNAL PAYMENT NOTE',detail.data)
        token=self.payment_form()
        self.admin.post(path,data=dict(token,action='entry',kind='refund',amount='26',method='Cash',paid_date=data['paid_date']))
        self.assertEqual(Entry.query.count(),1)
        token=self.payment_form()
        self.admin.post(path,data=dict(token,action='entry',kind='refund',amount='5',method='Cash',paid_date=data['paid_date']))
        self.assertEqual(main.app.extensions['payment_summary'](self.booking)['paid'],Decimal('20'))
        self.admin.post(path,data={'csrf_token':'admin-token','action':'plan','deposit':'30','deposit_due':'2099-01-01','balance_due':'2099-01-02'})
        self.assertEqual(main.db.session.get(Plan,self.booking.id).deposit,Decimal('30'))
        self.assertEqual(main.app.test_client().get(path).status_code,302)

    def test_calendar_buffers_and_unavailability(self):
        self.booking.status='Accepted'
        other=self.fixture.fixture.booking('other@example.com',status='Accepted',start_time='12:30',finish_time='14:00')
        main.db.session.commit()
        rows=main.app.extensions['calendar_rows']()
        self.assertTrue(all(row['conflicts'] for row in rows))
        self.admin.post('/admin/calendar',data={'csrf_token':'admin-token','starts_at':'2099-01-01T08:00','ends_at':'2099-01-01T10:00','reason':'Travel'})
        self.assertEqual(Block.query.count(),1)
        self.assertEqual(self.admin.get('/admin/calendar?month=2099-01').status_code,200)
        self.assertEqual(self.admin.get('/admin/calendar?month=bad').status_code,400)
        block=Block.query.one()
        self.assertEqual(self.admin.post(f'/admin/calendar/blocks/{block.id}/delete',data={}).status_code,400)
        self.admin.post(f'/admin/calendar/blocks/{block.id}/delete',data={'csrf_token':'admin-token'})
        self.assertEqual(Block.query.count(),0)

    def test_enquiry_status_reply_saved_and_emailed_once(self):
        self.client.post('/client/contact',data={'csrf_token':self.fixture.fixture.csrf(),'subject':'Access','message':'Where do we meet?'})
        enquiry=main.ClientEnquiry.query.one()
        path=f'/admin/enquiries/{enquiry.id}/update'
        with patch.object(main,'send_client_email',return_value=True) as send:
            self.admin.post(path,data={'csrf_token':'admin-token','status':'replied','reply':'Meet at the entrance.'})
            self.admin.post(path,data={'csrf_token':'admin-token','status':'resolved','reply':'Meet at the entrance.'})
            send.assert_called_once()
        self.assertEqual(main.db.session.get(Workflow,enquiry.id).status,'resolved')
        self.assertIn(b'Meet at the entrance.',self.client.get('/client/contact').data)
        self.assertEqual(main.app.test_client().post(path,data={'csrf_token':'admin-token'}).status_code,302)

    def test_loyalty_correction_latest_first_and_no_reclaim(self):
        _, path1=self.fixture.event()
        self.fixture.post_scan(path1)
        _, path2=self.fixture.event()
        self.fixture.post_scan(path2)
        visits=loyalty_tests.Visit.query.order_by(loyalty_tests.Visit.id).all()
        self.admin.post(f'/admin/loyalty/visits/{visits[0].id}/reverse',data={'csrf_token':'admin-token','reason':'Wrong selection'})
        self.assertEqual(Correction.query.count(),0)
        for visit in reversed(visits):
            self.admin.post(f'/admin/loyalty/visits/{visit.id}/reverse',data={'csrf_token':'admin-token','reason':'Wrong selection'})
        self.assertEqual(Correction.query.count(),2)
        self.assertEqual(main.db.session.get(loyalty_tests.Balance,self.fixture.person.id).points,0)
        self.fixture.post_scan(path1)
        self.assertEqual(main.db.session.get(loyalty_tests.Balance,self.fixture.person.id).points,0)
        self.assertIn(b'Wrong selection',self.client.get(path1).data)

    def test_reminder_dry_run_delivery_deduplication_and_retry(self):
        self.booking.status='Accepted'
        self.booking.event_date=datetime.now(ZoneInfo('Europe/London')).date()+timedelta(days=1)
        main.db.session.add(main.BusinessSetting(key='public_app_url',value='https://example.com'))
        main.db.session.commit()
        function=main.app.extensions['send_due_reminders']
        self.assertEqual(len(function()),1)
        self.assertEqual(Reminder.query.count(),0)
        with patch.object(main,'send_client_email',return_value=False): function(dry_run=False)
        self.assertIsNone(Reminder.query.one().sent_at)
        with patch.object(main,'send_client_email',return_value=True) as send:
            function(dry_run=False)
            function(dry_run=False)
            send.assert_called_once()
        self.assertIsNotNone(Reminder.query.one().sent_at)

    def test_previews_history_backup_and_restore_with_synthetic_data(self):
        self.assertEqual(self.admin.get('/admin/email-preview/booking').status_code,200)
        self.assertEqual(self.admin.get('/admin/email-preview/reward').status_code,200)
        self.assertEqual(self.admin.get('/admin/email-history').status_code,200)
        self.assertEqual(self.admin.get('/admin/backups').status_code,200)
        self.assertEqual(self.admin.post('/admin/backups',data={}).status_code,400)
        response=self.admin.post('/admin/backups',data={'csrf_token':'admin-token'})
        self.assertEqual(response.status_code,200)
        with tempfile.TemporaryDirectory() as folder:
            backup=Path(folder)/'backup.db'
            backup.write_bytes(response.data)
            validate(backup)
            target=Path(folder)/'target.db'
            with closing(sqlite3.connect(target)) as connection:
                connection.execute('CREATE TABLE previous(value TEXT)')
                connection.execute("INSERT INTO previous VALUES ('preserved')")
                connection.commit()
            safety=restore(backup,target)
            validate(target)
            with closing(sqlite3.connect(safety)) as connection:
                self.assertEqual(connection.execute('SELECT value FROM previous').fetchone()[0],'preserved')
            invalid=Path(folder)/'invalid.db'
            invalid.write_text('not a database')
            with self.assertRaises(sqlite3.DatabaseError): validate(invalid)

if __name__=='__main__': unittest.main()
