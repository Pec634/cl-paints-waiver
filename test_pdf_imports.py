from io import BytesIO
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import test_record_imports as fixtures
from record_imports import read_table

main = fixtures.main


def pdf(lines=None, pages=1, password=None):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612,height=792)
        if lines:
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream = DecodedStreamObject()
            instructions = 'BT /F1 12 Tf 40 750 Td 14 TL\n'
            for line in lines:
                escaped = line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
                instructions += '(' + escaped + ') Tj T*\n'
            stream.set_data((instructions+'ET').encode('latin-1'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if password: writer.encrypt(password)
    output=BytesIO(); writer.write(output)
    return output.getvalue()


class PdfImportsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RecordImportsTest(); self.fixture.setUp()

    def tearDown(self): self.fixture.tearDown()

    def test_labelled_client_pdf_review_and_import(self):
        content=pdf(['Client name: Alice Example','Email address: alice@example.com','Phone: 0123456789','Address: 1 Example Road'])
        payload=read_table('clients.pdf',content,'clients')
        self.assertEqual(payload['format'],'pdf')
        self.assertEqual(payload['rows'][0][:3],['alice@example.com','Alice','Example'])
        response=self.fixture.upload('clients',content,'clients.pdf')
        self.assertEqual(response.status_code,302)
        page=self.fixture.admin.get(response.location)
        self.assertIn(b'Correct extracted records',page.data)
        self.assertIn(b'Alice Example',page.data)
        self.assertIn(b'Page 1',page.data)
        self.assertIsNone(main.ClientAccount.query.filter_by(email='alice@example.com').first())
        self.fixture.save(response.location)
        self.assertIsNotNone(main.ClientAccount.query.filter_by(email='alice@example.com').first())
        self.assertEqual(main.record_import_models[0].query.one().payload,'{}')

    def test_incomplete_booking_can_be_corrected_before_import(self):
        content=pdf(['First name: Bob','Surname: Example','Email: bob@example.com','Event name: Birthday party',
            'Event date: 2027-07-01','Start time: 10:00','End time: 12:00','Venue: Example hall'])
        response=self.fixture.upload('bookings',content,'booking.pdf')
        route=response.location
        self.assertIn(b'Date of birth is required',self.fixture.admin.get(route).data)
        self.fixture.save(route)
        self.assertIsNone(main.Booking.query.filter_by(email='bob@example.com').first())
        payload=read_table('booking.pdf',content,'bookings')
        data={'csrf_token':'admin-token','action':'edit_pdf'}
        data.update({f'pdf_0_{key}':value for key,value in zip(payload['headers'],payload['rows'][0])})
        data['pdf_0_date_of_birth']='1990-01-01'
        data['pdf_0_event_type']='Corrected birthday party'
        self.fixture.admin.post(route,data=data)
        self.assertIn(b'Corrected birthday party',self.fixture.admin.get(route).data)
        self.fixture.save(route)
        booking=main.Booking.query.filter_by(email='bob@example.com').one()
        self.assertEqual(booking.event_type,'Corrected birthday party')
        self.assertFalse(booking.liability_acknowledged)
        self.assertEqual(main.tool_models[1].query.count(),0)

    def test_simple_table_multiple_records_and_source_escaping(self):
        payload=read_table('table.pdf',pdf(['Email | First name | Surname','one@example.com | One | Client','two@example.com | Two | Client']),'clients')
        self.assertEqual(len(payload['rows']),2)
        self.assertEqual(payload['rows'][1][:3],['two@example.com','Two','Client'])
        response=self.fixture.upload('clients',pdf(['First name: <script>alert(1)</script>','Surname: Client','Email: safe@example.com']),'text.pdf')
        page=self.fixture.admin.get(response.location)
        self.assertNotIn(b'<script>alert(1)</script>',page.data)
        self.assertIn(b'&lt;script&gt;',page.data)

    def test_scanned_encrypted_malformed_and_page_limits_are_clear(self):
        with self.assertRaisesRegex(ValueError,'OCR'): read_table('scan.pdf',pdf(),'clients')
        with self.assertRaisesRegex(ValueError,'Unlock'): read_table('locked.pdf',pdf(['Email: user@example.com'],password='secret'),'clients')
        with self.assertRaisesRegex(ValueError,'20 pages'): read_table('large.pdf',pdf(pages=21),'clients')
        with self.assertRaises(ValueError): read_table('broken.pdf',b'%PDF-broken','clients')
        response=self.fixture.upload('clients',pdf(),'scan.pdf')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'OCR',response.data)


if __name__ == '__main__': unittest.main()
