from io import BytesIO
import unittest
import test_loyalty as fixtures
import test_native_form_browser as browser_helpers

main = fixtures.main


class InvoiceDocumentsTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.booking = self.fixture.fixture.booking(self.fixture.account.email)
        self.path = f'/admin/clients/{self.fixture.account.id}/invoice-documents'
        self.fixture.admin.get(f'/admin/clients/{self.fixture.account.id}')
        with self.fixture.admin.session_transaction() as session:
            self.token = session['client_csrf']

    def tearDown(self):
        self.fixture.tearDown()

    def upload(self, content=b'%PDF-1.4\ninvoice', **values):
        data = dict(csrf_token=self.token, booking_id=str(self.booking.id),
                    invoice_document=(BytesIO(content), 'invoice.pdf'))
        data.update(values)
        return self.fixture.admin.post(self.path, data=data)

    def test_upload_visible_across_views_and_private_download(self):
        self.assertEqual(self.upload().status_code, 302)
        document = main.InvoiceDocument.query.one()
        path = f'/invoice-documents/{document.id}'
        for client, url in [(self.fixture.client, f'/client/bookings/{self.booking.id}'),
                            (self.fixture.client, '/client/bookings'),
                            (self.fixture.client, '/client/payments'),
                            (self.fixture.admin, '/admin/bookings'),
                            (self.fixture.admin, f'/admin/clients/{self.fixture.account.id}')]:
            response = client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn(b'invoice.pdf', response.data, url)
        response = self.fixture.client.get(path)
        self.assertEqual(response.data, b'%PDF-1.4\ninvoice')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(main.app.test_client().get(path).status_code, 404)
        other = self.fixture.fixture.booking('other@example.com')
        document.booking_id = other.id
        main.db.session.commit()
        self.assertEqual(self.fixture.client.get(path).status_code, 404)
        self.assertEqual(self.fixture.admin.get(path).status_code, 200)

    def test_rejects_csrf_wrong_client_and_invalid_files(self):
        self.assertEqual(self.upload(csrf_token='wrong').status_code, 400)
        other = self.fixture.fixture.booking('other@example.com')
        self.assertEqual(self.upload(booking_id=str(other.id)).status_code, 403)
        self.upload(b'<html>not an invoice</html>')
        self.upload(b'%PDF-' + b'x' * 10_000_000)
        self.assertEqual(main.InvoiceDocument.query.count(), 0)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_booking_row_modal_and_calendar_scroll_in_browser(self):
        self.upload()
        self.browser(self.fixture.admin.get('/admin/bookings').data, '''
            const row = document.querySelector('.booking-row');
            const dialog = document.querySelector('#calendar-event-dialog');
            row.querySelector('td').click();
            assert(dialog.open, 'Clicking the booking field must open its details');
            assert(dialog.textContent.includes('invoice.pdf'), 'Invoice missing from popup');
            assert(dialog.textContent.includes('Client signature'), 'Full details missing');
            dialog.querySelector('[data-calendar-close]').click();
            assert(!dialog.open, 'Close did not dismiss popup');
            row.focus();
            row.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
            assert(dialog.open, 'Keyboard did not open popup');
        ''')
        month = self.booking.event_date.strftime('%Y-%m')
        self.browser(self.fixture.admin.get('/admin/calendar?month='+month).data, '''
            const calendar = document.querySelector('.calendar-scroll');
            assert(getComputedStyle(calendar).overflowY === 'auto', 'Calendar must scroll vertically');
            assert(getComputedStyle(calendar).maxHeight !== 'none', 'Calendar height must be bounded');
            document.querySelector('[data-calendar-detail]').click();
            const dialog = document.querySelector('#calendar-event-dialog');
            assert(dialog.open, 'Calendar popup did not open');
            assert(dialog.textContent.includes('invoice.pdf'), 'Calendar invoice missing');
            assert(!dialog.textContent.includes('Open full booking'), 'Redundant button still present');
        ''')


if __name__ == '__main__':
    unittest.main()
