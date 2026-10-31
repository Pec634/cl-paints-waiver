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
        self.assertIn(f'/moodboard/event/{self.event.id}'.encode(), page.data)


if __name__ == '__main__':
    unittest.main()
