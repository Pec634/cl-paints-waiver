import json
from io import BytesIO
import unittest
import test_business_tools as fixtures
from staff_reports import SCHEMAS


class StaffReportsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp()
        self.admin=self.fixture.admin;self.client=self.fixture.client
        self.Report,self.Media=fixtures.main.staff_report_models

    def tearDown(self):self.fixture.tearDown()

    def test_reports_validation_and_private_evidence(self):
        for kind in SCHEMAS:
            path='/admin/staff-reports/new/'+kind
            self.assertEqual(self.client.get(path).status_code,302)
            self.assertEqual(self.admin.get(path).status_code,200)
            with self.admin.session_transaction() as session:token=session['staff_report_token']
            self.assertEqual(self.admin.post(path,data={}).status_code,400)
            payload=dict(csrf_token='admin-token',submission_token=token)
            self.admin.post(path,data=payload)
            self.assertEqual(self.Report.query.filter_by(kind=kind).count(),0)
            for index,f in enumerate(SCHEMAS[kind][1]):
                if f['required']:
                    payload['field_'+str(index)]='2026-10-05' if f['type']=='date' else '12:30' if f['type']=='time' else f['choices'][0] if f['type']=='select' else 'Test details'
            payload['images']=(BytesIO(b'\x89PNG\r\n\x1a\nexample'),'evidence.png')
            response=self.admin.post(path,data=payload)
            self.assertEqual(response.status_code,302)
            report=self.Report.query.filter_by(kind=kind).one()
            self.assertEqual(json.loads(report.answers_json)['Incident date'],'2026-10-05')
            self.assertEqual(self.admin.get(response.location).status_code,200)
            self.assertEqual(self.client.get(response.location).status_code,302)
            media=self.Media.query.filter_by(report_id=report.id).one()
            file_path='/admin/staff-report-media/'+str(media.id)
            self.assertEqual(self.client.get(file_path).status_code,302)
            self.assertEqual(self.admin.get(file_path).headers['Cache-Control'],'no-store')
        self.assertEqual(self.admin.get('/admin/staff-reports?kind=collision').status_code,200)
        self.assertNotIn(b'cognitoforms',self.admin.get('/admin/forms-offers').data.lower())
