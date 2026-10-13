import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import unittest
from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError
import app as main


class QRAnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.context = main.app.app_context()
        self.context.push()
        main.db.drop_all()
        main.db.create_all()
        self.client = main.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.client.get('/admin/settings')
        with self.client.session_transaction() as session:
            self.token = session['settings_csrf']
        self.Code, self.Scan = main.qr_models

    def tearDown(self):
        main.db.session.remove()
        self.context.pop()

    def generate(self):
        return self.client.post('/admin/settings/qr-code', data={
            'csrf_token': self.token, 'url': 'https://example.com/booking', 'track': '1', 'name': 'Flyers'})

    def test_create_reuse_count_and_report(self):
        self.assertEqual(self.generate().status_code, 200)
        self.assertEqual(self.generate().status_code, 200)
        self.assertEqual(self.Code.query.count(), 1)
        code = self.Code.query.one()
        path = '/q/' + code.token
        visitor = main.app.test_client()
        response = visitor.get(path, headers={'User-Agent': 'Mozilla/5.0 iPhone'})
        self.assertEqual(response.location, 'https://example.com/booking')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        visitor.get(path)
        visitor.head(path)
        visitor.get(path, headers={'User-Agent': 'PreviewBot'})
        self.client.get(path)
        self.assertEqual(self.Scan.query.count(), 2)
        report = self.client.get('/admin/reports/qr-codes')
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'Flyers', report.data)
        self.assertIn(b'2</strong> scans', report.data)
        self.assertEqual(visitor.get('/admin/reports/qr-codes').status_code, 302)
        self.assertEqual(visitor.get('/q/missing').status_code, 404)
        self.assertEqual(self.client.get('/admin/settings/qr-code', query_string={'code': code.token, 'download': '1'}).mimetype, 'image/png')

    def test_redirect_survives_analytics_failure(self):
        self.generate()
        path = '/q/' + self.Code.query.one().token
        with patch.object(main.db.session, 'commit', side_effect=SQLAlchemyError('unavailable')):
            response = main.app.test_client().get(path)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, 'https://example.com/booking')

    def test_validation_and_dates(self):
        response = self.client.post('/admin/settings/qr-code', data={
            'csrf_token': self.token, 'url': 'https://example.com', 'track': '1', 'name': ''})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.Code.query.count(), 0)
        self.assertEqual(self.client.get('/admin/reports/qr-codes?start=invalid').status_code, 400)
        self.assertEqual(self.client.get('/admin/reports/qr-codes?start=2026-10-13&end=2026-10-01').status_code, 400)

    def test_campaign_archive_restore_and_print_sign(self):
        self.generate()
        code = self.Code.query.one()
        self.client.get('/admin/reports/qr-codes')
        with self.client.session_transaction() as session:
            csrf = session['qr_manage_csrf']
        path = f'/admin/reports/qr-codes/{code.id}/organise'
        self.assertEqual(self.client.post(path, data={'archived': '1'}).status_code, 400)
        response = self.client.post(path, data={'csrf_token': csrf, 'campaign': 'Autumn posters', 'archived': '1'})
        self.assertEqual(response.status_code, 302)
        Meta = main.app.extensions['qr_metadata_model']
        self.assertTrue(main.db.session.get(Meta, code.id).archived)
        active = self.client.get('/admin/reports/qr-codes')
        self.assertNotIn(b'<h3>Flyers</h3>', active.data)
        archived = self.client.get('/admin/reports/qr-codes?state=archived&q=Autumn')
        self.assertIn(b'<h3>Flyers</h3>', archived.data)
        self.assertEqual(main.app.test_client().get('/q/' + code.token).location, code.destination)
        sign = self.client.get(f'/admin/reports/qr-codes/{code.id}/sign')
        self.assertEqual(sign.status_code, 200)
        self.assertIn(b'Print / save as PDF', sign.data)
        self.assertEqual(main.app.test_client().get(f'/admin/reports/qr-codes/{code.id}/sign').status_code, 302)
        self.client.post(path, data={'csrf_token': csrf, 'campaign': 'Autumn posters', 'archived': '0'})
        self.assertIn(b'<h3>Flyers</h3>', self.client.get('/admin/reports/qr-codes?q=Autumn').data)
        self.assertNotIn(b'<h3>Flyers</h3>', self.client.get('/admin/reports/qr-codes?q=unmatched').data)
        self.assertEqual(self.client.get('/admin/reports/qr-codes?state=invalid').status_code, 400)

    def test_qr_list_pagination(self):
        main.db.session.add_all([self.Code(name=f'Campaign {index}', destination='https://example.com') for index in range(13)])
        main.db.session.commit()
        self.assertIn(b'Page 1 of 2', self.client.get('/admin/reports/qr-codes').data)
        self.assertIn(b'Page 2 of 2', self.client.get('/admin/reports/qr-codes?page=2').data)


if __name__ == '__main__':
    unittest.main()
