import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import test_client_portal as portal_tests

main = portal_tests.main


class EventMoodboardTest(unittest.TestCase):
    def setUp(self):
        self.fixture = portal_tests.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.event = main.Event(name='Summer fair', status='Open')
        self.other = main.Event(name='Other fair', status='Open')
        main.db.session.add_all([self.event, self.other])
        main.db.session.flush()
        for title, event, active in [('Butterfly', self.event, True),
                                     ('Hidden design', self.event, False),
                                     ('Other design', self.other, True)]:
            image = main.MoodboardImage(title=title, image_url='https://example.com/design.png', active=active)
            main.db.session.add(image)
            main.db.session.flush()
            main.db.session.add(main.EventMoodboardImage(event_id=event.id, image_id=image.id))
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def test_public_gallery_is_event_specific_and_updates(self):
        path = f'/moodboard/event/{self.event.id}'
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Butterfly', page.data)
        self.assertNotIn(b'Hidden design', page.data)
        self.assertNotIn(b'Other design', page.data)
        main.EventMoodboardImage.query.filter_by(event_id=self.event.id).delete()
        main.db.session.commit()
        self.assertIn(b'not been added yet', self.client.get(path).data)
        self.event.status = 'Archived'
        main.db.session.commit()
        self.assertEqual(self.client.get(path).status_code, 410)
        self.assertEqual(self.client.get('/moodboard/event/99999').status_code, 404)

    def test_admin_qr_preview_and_print(self):
        root = f'/admin/events/{self.event.id}/moodboard'
        for suffix in ('', '/qr', '/print'):
            self.assertEqual(self.client.get(root + suffix).status_code, 302)
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.assertIn(b'Preview event moodboard', self.client.get(root).data)
        qr = self.client.get(root + '/qr')
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, 'image/svg+xml')
        self.assertIn(b'<svg', qr.data)
        page = self.client.get(root + '/print')
        self.assertEqual(page.status_code, 200)
        self.assertIn((root + '/qr').encode(), page.data)
        self.assertIn(b'Moodboard sign editor', page.data)
        self.assertIn(b'data-sign-kind="moodboard"', page.data)
        self.assertNotIn(b'gain loyalty points', page.data)
        self.assertEqual(page.data.count(b'class="moodboard-sheet"'), 2)
        for code in ('waiver', 'account'):
            qr_url = f'/admin/events/{self.event.id}/{code}/qr'
            self.assertEqual(page.data.count(qr_url.encode()), 2)
            self.assertEqual(self.client.get(qr_url).mimetype, 'image/svg+xml')
        self.assertIn(b'id="sign-qr"', self.client.get(root + '/print?layout=sign').data)
        events = self.client.get(f'/admin/events?moodboard_event_id={self.event.id}')
        self.assertEqual(events.status_code, 200)
        self.assertIn((root + '/print').encode(), events.data)
        self.assertIn(f'/moodboard/event/{self.event.id}'.encode(), events.data)

    def test_print_sheets_group_only_saved_active_event_designs(self):
        butterfly = main.MoodboardImage.query.filter_by(title='Butterfly').one()
        butterfly.design_type = 'large'
        butterfly.image_url = '/butterfly-print.png'
        small = main.MoodboardImage(title='Heart', image_url='/heart-print.png', design_type='small')
        main.db.session.add(small)
        main.db.session.flush()
        main.db.session.add(main.EventMoodboardImage(event_id=self.event.id, image_id=small.id))
        main.db.session.commit()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        page = self.client.get(f'/admin/events/{self.event.id}/moodboard/print')
        self.assertEqual(page.status_code, 200)
        large_sheet, small_sheet = page.data.split(b'data-sheet="2"')
        self.assertIn(b'src="/butterfly-print.png" alt="Design L - 1"', large_sheet)
        self.assertIn(b'src="/heart-print.png" alt="Design S - 1"', small_sheet)
        self.assertNotIn(b'example.com/design.png', page.data)

    def test_upload_without_cloudinary_can_be_printed_and_deleted(self):
        buffer = BytesIO()
        Image.new('RGB', (16, 16), 'pink').save(buffer, format='PNG')
        content = buffer.getvalue()
        buffer.seek(0)
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        config = SimpleNamespace(cloud_name=None, api_key=None, api_secret=None)
        with patch.object(main.cloudinary, 'config', return_value=config), patch.object(main.cloudinary.uploader, 'upload') as upload:
            response = self.client.post('/admin/moodboard/upload', data={
                'images': [(buffer, 'Test-design.png'), (BytesIO(content), 'renamed-copy.png'), (BytesIO(b'invalid'), 'broken.png')],
                'design_type': 'small',
            }, follow_redirects=True)
        upload.assert_not_called()
        self.assertIn(b'1 image(s) could not be uploaded', response.data)
        self.assertIn(b'Uploaded 1 image(s)', response.data)
        self.assertIn(b'Skipped 1 duplicate image(s)', response.data)
        self.assertIn(b'aria-label="Preview Test design"', response.data)
        self.assertIsNone(main.MoodboardImage.query.filter_by(title='renamed copy').first())
        image = main.MoodboardImage.query.filter_by(title='Test design').one()
        image_id, image_url = image.id, image.image_url
        main.db.session.add(main.EventMoodboardImage(event_id=self.event.id, image_id=image_id))
        main.db.session.commit()
        printable = self.client.get(f'/admin/events/{self.event.id}/moodboard/print')
        self.assertIn(image_url.encode(), printable.data)
        served = main.app.test_client().get(image_url)
        self.assertEqual((served.mimetype, served.data), ('image/png', content))
        self.assertEqual(self.client.post(f'/admin/moodboard/{image_id}/delete').status_code, 302)
        self.assertIsNone(main.db.session.get(main.MoodboardImageFile, image_id))
        self.assertEqual(self.client.get(image_url).status_code, 404)

    def test_editable_prices_and_waiver_labels(self):
        path = '/admin/moodboard/prices'
        self.assertEqual(self.client.post(path).status_code, 302)
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
        self.assertEqual(self.client.post(path).status_code, 400)
        self.client.get('/admin/moodboard')
        token = self.fixture.csrf()
        for invalid in ('NaN', 'Infinity', '-1', '3.555', '10000'):
            response = self.client.post(path, data={'csrf_token': token, 'small_price': invalid, 'large_price': '6'})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(main.get_moodboard_prices()['large'], '5.00')
        response = self.client.post(path, data={'csrf_token': token, 'small_price': '4', 'large_price': '6.50'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(main.get_moodboard_prices(), {'small': '4.00', 'large': '6.50'})
        gallery = self.client.get(f'/moodboard/event/{self.event.id}')
        self.assertIn(b'&pound;6.50', gallery.data)
        waiver = self.client.get(f'/waiver/event/{self.event.id}')
        self.assertIn(b'Large Designs', waiver.data)
        self.assertNotIn(b'Full Face', waiver.data)
        self.assertNotIn(b'Half Face', waiver.data)
        self.assertIn(b'&pound;6.50', waiver.data)


if __name__ == '__main__':
    unittest.main()
