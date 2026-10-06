from datetime import datetime
import secrets
import unittest
from sqlalchemy import text
import test_loyalty as fixtures

main = fixtures.main


class EventDeletionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        main.db.session.commit()
        main.db.session.execute(text('PRAGMA foreign_keys=ON'))
        self.event, _ = self.fixture.event()
        self.event_id = self.event.id
        self.path = f'/admin/events/{self.event.id}/delete'

    def tearDown(self):
        main.db.session.rollback()
        main.db.session.execute(text('PRAGMA foreign_keys=OFF'))
        self.fixture.tearDown()

    def test_deletion_clears_qr_moodboard_and_closed_kiosk_links(self):
        image = main.MoodboardImage(title='Saved art', image_url='https://example.com/art.png')
        main.db.session.add(image); main.db.session.flush()
        image_id = image.id
        main.db.session.add(main.EventMoodboardImage(event_id=self.event_id, image_id=image.id))
        main.db.session.add(main.KioskSession(id=secrets.token_hex(24), event_id=self.event_id,
            csrf=secrets.token_hex(24), phase='closed'))
        main.db.session.commit()
        response = self.fixture.admin.post(self.path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Event deleted', response.data)
        self.assertIsNone(main.db.session.get(main.Event, self.event_id))
        self.assertIsNone(main.db.session.get(main.loyalty_models[0], self.event_id))
        self.assertEqual(main.EventMoodboardImage.query.filter_by(event_id=self.event_id).count(), 0)
        self.assertEqual(main.KioskSession.query.filter_by(event_id=self.event_id).count(), 0)
        self.assertIsNotNone(main.db.session.get(main.MoodboardImage, image_id))
        self.assertIsNotNone(main.db.session.get(main.Waiver, self.fixture.waiver.id))

    def test_loyalty_history_blocks_deletion(self):
        Visit = main.loyalty_models[2]
        main.db.session.add(Visit(participant_id=self.fixture.person.id, event_id=self.event_id,
            client_id=self.fixture.account.id, status='point', confirmed_at=datetime.utcnow()))
        main.db.session.commit()
        response = self.fixture.admin.post(self.path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'recorded loyalty visits', response.data)
        self.assertIsNotNone(main.db.session.get(main.Event, self.event_id))
        self.assertEqual(Visit.query.count(), 1)

    def test_active_kiosk_blocks_deletion(self):
        main.db.session.add(main.KioskSession(id=secrets.token_hex(24), event_id=self.event_id,
            csrf=secrets.token_hex(24), phase='signup'))
        main.db.session.commit()
        response = self.fixture.admin.post(self.path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'active kiosk', response.data)
        self.assertIsNotNone(main.db.session.get(main.Event, self.event_id))

    def test_deletion_requires_admin(self):
        self.assertEqual(self.fixture.client.post(self.path).status_code, 302)
        self.assertIsNotNone(main.db.session.get(main.Event, self.event_id))

    def test_archive_preserves_loyalty_history_closes_links_and_can_restore(self):
        EventCode, Balance, Visit, _, _ = main.loyalty_models
        main.db.session.add(Visit(participant_id=self.fixture.person.id,event_id=self.event_id,
            client_id=self.fixture.account.id,status='point'))
        main.db.session.add(Balance(participant_id=self.fixture.person.id,points=1))
        self.event.is_current=True; main.db.session.commit()
        token=main.db.session.get(EventCode,self.event_id).token
        path=f'/admin/events/{self.event_id}/archive'
        self.assertEqual(self.fixture.admin.post(path,data={}).status_code,400)
        response=self.fixture.admin.post(path,data={'csrf_token':'admin-token'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.event.status,'Archived')
        self.assertFalse(self.event.is_current)
        self.assertNotIn(self.event.name.encode(),response.data)
        self.assertIn(self.event.name.encode(),self.fixture.admin.get('/admin/events?view=archived').data)
        self.assertEqual(self.fixture.client.get(f'/waiver/event/{self.event_id}').status_code,410)
        self.assertEqual(self.fixture.client.post(f'/api/waivers/event/{self.event_id}',json={}).status_code,403)
        self.assertEqual(self.fixture.client.get(f'/client/loyalty/scan/{token}').status_code,410)
        self.assertEqual(Visit.query.count(),1)
        self.assertEqual(main.db.session.get(Balance,self.fixture.person.id).points,1)
        self.fixture.admin.post(f'/admin/events/{self.event_id}/status',data={'status':'Open'})
        self.assertEqual(self.event.status,'Archived')
        self.fixture.admin.post(f'/admin/events/{self.event_id}/restore',data={'csrf_token':'admin-token'})
        self.assertEqual(self.event.status,'Closed')
        self.assertIn(self.event.name.encode(),self.fixture.admin.get('/admin/events').data)

    def test_archive_refuses_active_kiosk(self):
        main.db.session.add(main.KioskSession(id=secrets.token_hex(24),event_id=self.event_id,
            csrf=secrets.token_hex(24),phase='signup'));main.db.session.commit()
        response=self.fixture.admin.post(f'/admin/events/{self.event_id}/archive',data={'csrf_token':'admin-token'},follow_redirects=True)
        self.assertIn(b'active kiosk',response.data)
        self.assertEqual(self.event.status,'Open')


if __name__ == '__main__':
    unittest.main()
