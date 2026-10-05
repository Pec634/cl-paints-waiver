import unittest
from io import BytesIO
from datetime import datetime, timedelta
from unittest.mock import patch
import test_loyalty as fixtures

main = fixtures.main
Preference, Campaign, Delivery = main.marketing_models


class MarketingTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.admin = self.fixture.admin
        self.waiver = self.fixture.waiver
        self.waiver.marketing_consent = True
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def post(self, campaign, action, **extra):
        return self.admin.post(f'/admin/marketing/{campaign.id}', data=dict(csrf_token='admin-token', action=action, **extra))

    def campaign(self):
        response = self.admin.post('/admin/marketing', data=dict(csrf_token='admin-token', subject='Summer colours', body='<script>alert(1)</script>\nNew designs'))
        self.assertEqual(response.status_code, 302)
        return Campaign.query.one()

    def test_deduplication_withdrawal_and_admin_access(self):
        self.assertEqual(main.app.test_client().get('/admin/marketing').status_code, 302)
        self.assertEqual(self.admin.post('/admin/marketing', data={}).status_code, 400)
        duplicate = self.fixture.make_waiver('  ' + self.waiver.responsible_email.upper() + '  ', 'SECOND')
        duplicate.marketing_consent = True
        duplicate.signed_date = datetime.utcnow() + timedelta(seconds=1)
        main.db.session.commit()
        campaign = self.campaign()
        self.post(campaign, 'start'); self.post(campaign, 'start')
        self.assertEqual(Delivery.query.count(), 1)
        duplicate.marketing_consent = False
        main.db.session.commit()
        with patch.object(main, 'send_client_email') as sender:
            self.post(campaign, 'send')
            sender.assert_not_called()
        self.assertEqual(Delivery.query.one().status, 'skipped')

    def test_sending_unsubscribe_and_failure_history(self):
        campaign = self.campaign()
        preview = self.admin.get(f'/admin/marketing/{campaign.id}')
        self.assertIn(b'&lt;script&gt;', preview.data)
        with patch.object(main, 'send_client_email', return_value=True) as sender:
            self.post(campaign, 'test', test_email='staff@example.com')
            self.assertIn('/marketing/unsubscribe-preview', sender.call_args.args[2])
            self.assertEqual(Delivery.query.count(), 0)
            self.post(campaign, 'start')
            self.post(campaign, 'send')
            self.assertIn('/marketing/unsubscribe/', sender.call_args.args[2])
            self.assertIn('&lt;script&gt;', sender.call_args.args[3])
            self.post(campaign, 'send')
            self.assertEqual(sender.call_count, 2)
        self.assertEqual(Delivery.query.one().status, 'accepted')
        pref = Preference.query.one()
        anonymous = main.app.test_client()
        link = '/marketing/unsubscribe/' + pref.token
        self.assertEqual(anonymous.get(link).status_code, 200)
        self.assertIsNone(pref.unsubscribed_at)
        self.assertEqual(anonymous.post(link).status_code, 200)
        self.assertIsNotNone(pref.unsubscribed_at)
        self.assertTrue(self.waiver.marketing_consent)
        next_campaign = Campaign(subject='Another', body='Hello')
        main.db.session.add(next_campaign); main.db.session.commit()
        self.post(next_campaign, 'start')
        self.assertEqual(Delivery.query.filter_by(campaign_id=next_campaign.id).count(), 0)

    def test_failed_attempt_is_not_repeated(self):
        campaign = self.campaign(); self.post(campaign, 'start')
        with patch.object(main, 'send_client_email', return_value=False) as sender:
            self.post(campaign, 'send'); self.post(campaign, 'send')
            self.assertEqual(sender.call_count, 1)
        self.assertEqual(Delivery.query.one().status, 'failed')

    def test_design_images_preview_and_started_campaign_lock(self):
        Design, Image = main.app.extensions['marketing_design_models']
        campaign = self.campaign()
        self.post(campaign, 'edit', subject='New designs', body='Come along!', heading='A splash of colour',
                  colour='#123456', layout='simple', button_label='Book now', button_url='https://clpaints.com/book', image_position='below')
        self.assertEqual(campaign.subject, 'New designs')
        self.assertIsNotNone(main.db.session.get(Design, campaign.id))
        with patch('marketing.cloudinary.uploader.upload', return_value={'secure_url':'https://res.cloudinary.com/demo/image/upload/paint.png'}) as uploader:
            response = self.admin.post(f'/admin/marketing/{campaign.id}', data=dict(csrf_token='admin-token', action='upload',
                image=(BytesIO(b'image bytes'), 'paint.png'), alt='Butterfly face paint'), content_type='multipart/form-data')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(uploader.call_args.kwargs['allowed_formats'], ['jpg', 'png', 'webp'])
        preview = self.admin.get(f'/admin/marketing/{campaign.id}/preview')
        self.assertIn(b'https://res.cloudinary.com/demo/image/upload/paint.png', preview.data)
        self.assertIn(b'Butterfly face paint', preview.data)
        self.assertIn(b'#123456', preview.data)
        self.assertIn(b'https://clpaints.com/book', preview.data)
        with patch.object(main, 'send_client_email', return_value=True) as sender:
            self.post(campaign, 'test', test_email='staff@example.com')
            self.assertIn('Butterfly face paint', sender.call_args.args[3])
        self.post(campaign, 'edit', subject='Unsafe', body='Test', button_label='Click', button_url='javascript:alert(1)')
        self.assertEqual(campaign.subject, 'New designs')
        image = Image.query.one()
        self.post(campaign, 'remove_image', image_id=image.id)
        self.assertEqual(Image.query.count(), 0)
        self.post(campaign, 'start')
        self.assertEqual(self.post(campaign, 'edit', subject='Changed', body='Changed').status_code, 409)
        self.assertEqual(main.app.test_client().get(f'/admin/marketing/{campaign.id}/preview').status_code, 302)

    def test_upload_limits_and_failure(self):
        _, Image = main.app.extensions['marketing_design_models']
        campaign = self.campaign()
        with patch('marketing.cloudinary.uploader.upload', side_effect=ValueError('not an image')) as uploader:
            self.admin.post(f'/admin/marketing/{campaign.id}', data=dict(csrf_token='admin-token', action='upload',
                image=(BytesIO(b'x' * 2_000_001), 'large.png')), content_type='multipart/form-data')
            uploader.assert_not_called()
            self.admin.post(f'/admin/marketing/{campaign.id}', data=dict(csrf_token='admin-token', action='upload',
                image=(BytesIO(b'invalid'), 'fake.png')), content_type='multipart/form-data')
            self.assertEqual(uploader.call_count, 1)
        self.assertEqual(Image.query.count(), 0)

    def test_creation_page_saves_design_and_optional_image(self):
        Design, Image = main.app.extensions['marketing_design_models']
        page = self.admin.get('/admin/marketing')
        self.assertIn(b'name="colour"', page.data)
        self.assertIn(b'name="image"', page.data)
        with patch('marketing.cloudinary.uploader.upload', return_value={'secure_url':'https://res.cloudinary.com/demo/paint.png'}):
            response = self.admin.post('/admin/marketing', data=dict(csrf_token='admin-token', subject='Hello', body='New colours',
                heading='Welcome!', colour='#123456', image=(BytesIO(b'image'), 'paint.png'), alt='Face paint'), content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.query.one()
        self.assertIn('#123456', main.db.session.get(Design, campaign.id).config_json)
        self.assertEqual(Image.query.one().campaign_id, campaign.id)
        self.assertIsNone(campaign.started_at)


if __name__ == '__main__':
    unittest.main()
