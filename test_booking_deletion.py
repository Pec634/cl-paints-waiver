from datetime import datetime
from decimal import Decimal
import json
import unittest
from sqlalchemy import text
import test_business_tools as fixtures
import test_native_form_browser as browser_helpers

main = fixtures.main


class BookingDeletionTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.status = 'Under Review'
        main.db.session.commit()
        main.db.session.execute(text('PRAGMA foreign_keys=ON'))
        self.path = f'/admin/bookings/{self.booking.id}/delete'
        self.data = dict(csrf_token='admin-token', confirm_delete='yes')

    def tearDown(self):
        main.db.session.rollback()
        main.db.session.execute(text('PRAGMA foreign_keys=OFF'))
        self.fixture.tearDown()

    def test_delete_cleans_request_dependencies_and_preserves_account_and_other_booking(self):
        Change, Notice = main.notification_models
        Activity = main.booking_lifecycle_models[0]
        change = Change(booking_id=self.booking.id, changes_json=json.dumps({'Theme': {'before':'Old','after':'New'}}))
        main.db.session.add(change)
        main.db.session.flush()
        # Lifecycle auditing creates the activity referencing the change.
        main.db.session.add(main.BookingMessage(booking_id=self.booking.id, sender='client', body='Request message', submission_key='delete-message'))
        main.db.session.add(main.InvoiceDocument(booking_id=self.booking.id, filename='invoice.pdf', mime='application/pdf',content=b'%PDF-1.4'))
        main.db.session.add(main.tool_models[0](booking_id=self.booking.id,deposit=Decimal('50')))
        main.db.session.add(Notice(email=self.booking.email,kind='booking',reference=self.booking.public_reference,details='Request updated'))
        other = self.fixture.fixture.fixture.booking(self.booking.email)
        Batch, Receipt = main.record_import_models
        batch=Batch(id='deletion-test-batch',owner='admin',kind='bookings',filename='import.csv',
            payload='[]',expires_at=datetime.utcnow())
        main.db.session.add(batch)
        main.db.session.flush()
        receipt=Receipt(key='deletion-test-receipt',batch_id=batch.id,booking_id=self.booking.id,
            client_id=self.fixture.fixture.account.id,source_reference='OLD-REFERENCE')
        main.db.session.add(receipt)
        main.db.session.commit()
        booking_id=self.booking.id
        response=self.fixture.admin.post(self.path,data=self.data,follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'deleted.',response.data)
        self.assertIsNone(main.db.session.get(main.Booking,booking_id))
        self.assertEqual(Change.query.filter_by(booking_id=booking_id).count(),0)
        self.assertEqual(Activity.query.filter_by(booking_id=booking_id).count(),0)
        self.assertEqual(main.BookingMessage.query.filter_by(booking_id=booking_id).count(),0)
        self.assertEqual(main.InvoiceDocument.query.filter_by(booking_id=booking_id).count(),0)
        self.assertEqual(Notice.query.filter_by(reference=self.booking.public_reference).count(),0)
        self.assertIsNotNone(main.db.session.get(main.ClientAccount,self.fixture.fixture.account.id))
        self.assertIsNotNone(main.db.session.get(main.Booking,other.id))
        main.db.session.refresh(receipt)
        self.assertIsNone(receipt.booking_id)
        self.assertEqual(receipt.source_reference,'OLD-REFERENCE')
        self.assertEqual(self.fixture.client.get(f'/client/bookings/{booking_id}').status_code,404)

    def test_admin_csrf_confirmation_and_post_required(self):
        self.assertEqual(main.app.test_client().post(self.path,data=self.data).status_code,302)
        self.assertEqual(self.fixture.client.post(self.path,data=self.data).status_code,302)
        self.assertEqual(self.fixture.admin.get(self.path).status_code,405)
        self.assertEqual(self.fixture.admin.post(self.path,data=dict(self.data,csrf_token='bad')).status_code,400)
        self.assertEqual(self.fixture.admin.post(self.path,data=dict(csrf_token='admin-token')).status_code,400)
        self.assertIsNotNone(main.db.session.get(main.Booking,self.booking.id))

    def test_confirmed_and_previously_confirmed_bookings_are_protected(self):
        self.booking.status='Accepted'
        main.db.session.commit()
        response=self.fixture.admin.post(self.path,data=self.data)
        self.assertIn('deletion_error=',response.location)
        self.assertIsNotNone(main.db.session.get(main.Booking,self.booking.id))
        self.booking.status='Cancelled'
        main.db.session.add(main.notification_models[0](booking_id=self.booking.id,
            changes_json=json.dumps({'Status':dict(before='Accepted',after='Cancelled')})))
        main.db.session.commit()
        response=self.fixture.admin.post(self.path,data=self.data,follow_redirects=True)
        self.assertIn(b'previously confirmed',response.data)
        self.assertIsNotNone(main.db.session.get(main.Booking,self.booking.id))

    def test_financial_history_and_pending_sumup_checkout_block_deletion(self):
        entry=main.tool_models[1](booking_id=self.booking.id,token='delete-protected',amount=Decimal('10'),
            kind='payment',method='Cash',paid_date=datetime.now().date())
        main.db.session.add(entry)
        main.db.session.commit()
        response=self.fixture.admin.post(self.path,data=self.data,follow_redirects=True)
        self.assertIn(b'payment or refund records',response.data)
        self.assertIsNotNone(main.db.session.get(main.Booking,self.booking.id))
        main.db.session.delete(entry)
        main.db.session.add(main.SumupCheckout(booking_id=self.booking.id,token='pending-delete',reference='CL-delete',
            amount=Decimal('10'),purpose='Deposit',merchant='TEST'))
        main.db.session.commit()
        response=self.fixture.admin.post(self.path,data=self.data,follow_redirects=True)
        self.assertIn(b'SumUp checkout',response.data)
        self.assertIsNotNone(main.db.session.get(main.Booking,self.booking.id))

    def test_nonconfirmed_statuses_have_delete_option_and_can_be_removed(self):
        for status in ('Under Review','Awaiting Payment','Declined','Cancelled'):
            booking=self.fixture.fixture.fixture.booking(self.booking.email,status=status)
            main.db.session.commit()
            path=f'/admin/bookings/{booking.id}/delete'
            self.assertIn(path.encode(),self.fixture.admin.get('/admin/bookings').data)
            response=self.fixture.admin.post(path,data=self.data)
            self.assertEqual(response.status_code,302)
            self.assertIsNone(main.db.session.get(main.Booking,booking.id))

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_delete_requires_confirmation_without_opening_booking_popup(self):
        self.browser(self.fixture.admin.get('/admin/bookings').data, '''
            const form=document.querySelector('form[action$="/delete"]');
            assert(form,'Eligible booking needs a delete control');
            form.closest('details').querySelector('summary').click();
            let submitted=false;
            form.addEventListener('submit',event=>{event.preventDefault();submitted=true;});
            const button=form.querySelector('button');
            button.click();
            assert(!submitted,'Deletion must require explicit checkbox confirmation');
            form.querySelector('[name="confirm_delete"]').click();
            button.click();
            assert(submitted,'Confirmed deletion must submit');
            assert(!document.querySelector('#calendar-event-dialog').open,'Delete controls must not open booking details');
        ''')


if __name__ == '__main__':
    unittest.main()
