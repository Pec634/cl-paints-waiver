import csv
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import unittest
from openpyxl import Workbook

import test_business_tools as fixtures
from record_imports import read_table

main = fixtures.main
Batch, Receipt = main.record_import_models


class RecordImportsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest(); self.fixture.setUp()
        self.admin = self.fixture.admin; self.client = self.fixture.client

    def tearDown(self): self.fixture.tearDown()

    def upload(self, kind, content, filename='records.csv'):
        return self.admin.post('/admin/imports', data=dict(csrf_token='admin-token', kind=kind,
            file=(BytesIO(content), filename)), content_type='multipart/form-data')

    def save(self, path, rows=('0',)):
        return self.admin.post(path, data=dict(csrf_token='admin-token',action='save',confirm='yes',row=list(rows)))

    def booking_file(self):
        output=StringIO(); writer=csv.writer(output)
        writer.writerow(['email','first_name','last_name','date_of_birth','event_date','start_time','finish_time','event_address','event_type','total_event_cost','source_reference'])
        writer.writerow(['imported@example.com','Imported','Client','1990-01-01','2027-06-01','10:00','12:00','Venue, London','Birthday party','125.50','OLD-BOOKING-12'])
        return output.getvalue().encode()

    def test_clients_review_mapping_duplicate_and_idempotence(self):
        initial=main.ClientAccount.query.count()
        response=self.upload('clients',b'Contact,Given name,Family name\nNEW@example.com,New,Client\nnew@example.com,Duplicate,Client\n')
        self.assertEqual(response.status_code,302)
        self.assertEqual(main.ClientAccount.query.count(),initial)
        route=response.location
        self.admin.post(route,data=dict(csrf_token='admin-token',action='map',email='0',first_name='1',last_name='2'))
        page=self.admin.get(route)
        self.assertIn(b'Duplicate',page.data)
        self.assertIn('no-store',page.headers['Cache-Control'])
        self.assertEqual(self.save(route,('0','1')).status_code,302)
        batch=Batch.query.one()
        self.assertEqual(batch.imported,1); self.assertEqual(batch.skipped,1)
        self.assertEqual(batch.payload,'{}')
        self.assertEqual(main.ClientAccount.query.count(),initial+1)
        self.assertEqual(main.ClientAccount.query.filter_by(email='new@example.com').one().first_name,'New')
        self.save(route)
        self.assertEqual(main.ClientAccount.query.count(),initial+1)
        second=self.upload('clients',b'email,first_name,last_name\nnew@example.com,Changed,Client\n')
        self.save(second.location)
        self.assertEqual(main.ClientAccount.query.filter_by(email='new@example.com').one().first_name,'New')

    def test_booking_import_preserves_estimate_without_consent_or_payment(self):
        response=self.upload('bookings',self.booking_file())
        self.save(response.location)
        booking=main.Booking.query.filter_by(email='imported@example.com').one()
        self.assertEqual(booking.status,'Under Review')
        self.assertEqual(booking.total_event_cost,125.50)
        self.assertFalse(booking.liability_acknowledged)
        self.assertEqual(booking.terms_version,'imported-unverified')
        self.assertEqual(booking.signature,'')
        self.assertEqual(main.tool_models[1].query.count(),0)
        self.assertEqual(main.notification_models[1].query.count(),0)
        self.assertEqual(Receipt.query.one().source_reference,'OLD-BOOKING-12')
        repeat=self.upload('bookings',self.booking_file())
        self.save(repeat.location)
        self.assertEqual(main.Booking.query.filter_by(email='imported@example.com').count(),1)

    def test_auth_csrf_batch_ownership_expiry_and_invalid_rows(self):
        self.assertEqual(self.client.get('/admin/imports').status_code,302)
        self.assertEqual(self.admin.post('/admin/imports',data={}).status_code,400)
        response=self.upload('clients',b'email,first_name,last_name\nnot-an-email,Wrong,Client\n')
        route=response.location
        self.assertEqual(self.admin.post(route,data=dict(csrf_token='bad',action='save')).status_code,400)
        self.assertIn(b'valid email',self.admin.get(route).data)
        self.save(route)
        self.assertEqual(Batch.query.one().state,'Pending')
        other=main.app.test_client()
        with other.session_transaction() as session: session['admin_authenticated']=True
        self.assertEqual(other.get(route).status_code,404)
        batch=Batch.query.one(); batch.expires_at=datetime.utcnow()-timedelta(seconds=1)
        main.db.session.commit()
        self.assertEqual(self.admin.get(route).status_code,410)
        self.admin.get('/admin/imports')
        self.assertEqual(batch.payload,'{}')
        self.assertEqual(self.upload('clients',b'%PDF-content','records.pdf').status_code,200)

    def test_xlsx_reader_and_formula_size_and_structure_limits(self):
        workbook=Workbook(); sheet=workbook.active
        sheet.append(['email','first_name','last_name'])
        sheet.append(['excel@example.com','Excel','Client'])
        output=BytesIO(); workbook.save(output)
        response=self.upload('clients',output.getvalue(),'records.xlsx')
        self.assertEqual(response.status_code,302)
        self.save(response.location)
        self.assertIsNotNone(main.ClientAccount.query.filter_by(email='excel@example.com').first())
        sheet['B2']='=1+1'; output=BytesIO(); workbook.save(output)
        with self.assertRaisesRegex(ValueError,'formulas'): read_table('records.xlsx',output.getvalue())
        with self.assertRaises(ValueError): read_table('records.csv',b'email,email\na,b\n')
        with self.assertRaises(ValueError): read_table('records.csv',b'a,b\n'+b'x,y\n'*501)
        with self.assertRaises(ValueError): read_table('records.csv',b'a'*5_000_001)


if __name__ == '__main__': unittest.main()
