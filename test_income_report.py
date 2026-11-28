import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
import json
import unittest

from flask import template_rendered

import test_business_tools as fixtures


main = fixtures.main


class IncomeReportTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.booking = self.fixture.booking

    def tearDown(self):
        self.fixture.tearDown()

    def report(self, **query):
        contexts = []

        def capture(sender, template, context, **unused):
            if template.name == 'admin_income.html':
                contexts.append(context)

        with template_rendered.connected_to(capture, main.app):
            response = self.admin.get('/admin/income', query_string=query)
        self.assertEqual(response.status_code, 200)
        return contexts[-1]

    def add_manual(self, source='other', order_id=None, **fields):
        path = '/admin/income/record'
        if order_id:
            path += f'?source={source}&order_id={order_id}'
        self.assertEqual(self.admin.get(path).status_code, 200)
        with self.admin.session_transaction() as state:
            data = dict(csrf_token=state['client_csrf'], entry_token=state[f'income_receipt_{source}_{order_id or 0}'])
        data.update(dict(paid_date='2025-04-06', amount='10.00', method='Bank transfer',
                         kind='payment', reference='BANK-101', description='Payment from bank statement'))
        data.update(fields)
        return self.admin.post(path, data=data), path, data

    def test_tax_year_totals_use_receipts_and_refunds_once(self):
        self.booking.status = 'Awaiting Payment'
        old_date, new_date = date(2025, 4, 5), date(2025, 4, 6)
        for token, amount, kind, day in [('manual-receipt', '34', 'payment', old_date),
                                            ('sumup-invoice-test', '60', 'payment', new_date),
                                            ('manual-refund', '4', 'refund', new_date)]:
            main.db.session.add(fixtures.Entry(booking_id=self.booking.id, token=token,
                amount=Decimal(amount), kind=kind, method='Cash', note='', paid_date=day))
        paid = main.PosSale(reference='TILL-PAID', items_json='[]', amount=Decimal('30'), method='Card', status='Paid',
            paid_at=datetime(2025, 4, 5, 23, 40))
        main.db.session.add_all([paid, main.PosSale(reference='TILL-PENDING', items_json='[]', amount=Decimal('99'),
            method='Card', status='Awaiting verification', created_at=datetime(2025, 4, 6))])
        main.db.session.flush()
        main.db.session.add(main.PosRefund(sale_id=paid.id, token='till-refund-test', items_json='[]', amount=Decimal('5'),
            method='Card', status='Refunded', completed_at=datetime(2025, 4, 6), reason='Test', recorded_by='Admin'))
        for revision, cash in [(1, '25.00'), (2, '20.00')]:
            main.db.session.add(main.BookingCashup(booking_id=self.booking.id, event_index=0,
                event_date=new_date.isoformat(), revision=revision, phase='Closed', recorded_by='Admin',
                data_json=json.dumps(dict(cash_sales=cash, pos_card_sales='30.00', pos_card_refunds='5.00',
                                          invoice_cash_till='60.00', till_other_in='140.00', share_till='10.00'))))
        main.db.session.commit()
        report = self.report(tax_year='2025', sort='highest')
        self.assertEqual(report['totals'], dict(received=Decimal(110), refunds=Decimal(9), net=Decimal(101), count=5))
        self.assertEqual([item['amount'] for item in report['rows']], [60, 30, 20, 5, 4])
        self.assertEqual(self.report(tax_year='2024')['totals']['received'], 34)
        self.assertEqual(self.report(tax_year='custom', start='2025-04-06', end='2025-04-06', source='pos',
                                     method='Card', kind='refund')['totals']['net'], -5)

    def test_undated_order_instalments_and_void_preserve_totals(self):
        order = main.creates_models[0](first_name='Test', last_name='Buyer', email='test@example.com', address='',
            fulfilment='collection', items_json='[]', total=Decimal(24), paid=Decimal(24))
        main.db.session.add(order)
        main.db.session.commit()
        before = self.report(tax_year='2025')
        self.assertEqual((before['totals']['count'], before['undated_total']), (0, 24))
        result, path, data = self.add_manual('creates', order.id, amount='15', paid_date='2025-04-05')
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.admin.post(path, data=data).status_code, 302)
        self.assertEqual(main.IncomeReceipt.query.count(), 1)
        self.assertEqual(self.report(tax_year='2024')['totals']['net'], 15)
        self.assertEqual(self.report(tax_year='undated')['totals']['net'], 9)
        reject, _, _ = self.add_manual('creates', order.id, amount='10')
        self.assertEqual(reject.status_code, 400)
        valid, _, _ = self.add_manual('creates', order.id, amount='9', reference='BANK-102')
        self.assertEqual(valid.status_code, 302)
        self.assertEqual(self.report(tax_year='all')['totals']['net'], 24)
        self.assertEqual(self.report(tax_year='undated')['totals']['count'], 0)
        receipt = main.IncomeReceipt.query.filter_by(reference='BANK-102').one()
        detail = f'/admin/income/receipts/{receipt.id}'
        self.assertEqual(self.admin.get(detail).status_code, 200)
        self.assertEqual(self.admin.post(detail, data={'csrf_token': data['csrf_token'],
            'reason': 'Wrong date on first review'}).status_code, 302)
        self.assertEqual(self.report(tax_year='undated')['totals']['net'], 9)
        self.assertIn(b'Wrong date on first review', self.admin.get(detail).data)

    def test_export_filters_spreadsheet_values_and_access(self):
        self.assertEqual(self.add_manual(reference='=1+1')[0].status_code, 302)
        self.assertEqual(self.add_manual(kind='refund', amount='3.25', reference='REF123')[0].status_code, 302)
        self.assertEqual(self.report(tax_year='2025', q='REF123')['totals']['net'], Decimal('-3.25'))
        path = '/admin/income/export.csv?tax_year=2025&method=Bank+transfer'
        response = self.admin.get(path)
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual([item['Signed amount (GBP)'] for item in rows], ['-3.25', '10.00'])
        self.assertEqual(rows[1]['Reference'], "'=1+1")
        self.assertEqual(self.admin.get('/admin/income?tax_year=custom&start=2026-02-01&end=2026-01-01').status_code, 400)
        self.assertEqual(self.admin.get('/admin/income/export.csv?source=invalid').status_code, 400)
        self.assertEqual(main.app.test_client().get(path).status_code, 302)


if __name__ == '__main__':
    unittest.main()
