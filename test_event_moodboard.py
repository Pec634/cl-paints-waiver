import unittest
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
        events = self.client.get(f'/admin/events?moodboard_event_id={self.event.id}')
        self.assertEqual(events.status_code, 200)
        self.assertIn((root + '/print').encode(), events.data)
        self.assertIn(f'/moodboard/event/{self.event.id}'.encode(), events.data)

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
