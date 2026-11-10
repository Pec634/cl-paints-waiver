"""Participant/account isolation, safe image storage and mobile upload controls."""
from datetime import datetime
from io import BytesIO
import json
import unittest
from PIL import Image
import test_loyalty as fixtures
import test_native_form_browser as browsers

main = fixtures.main


class ParticipantPhotosTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.admin, self.client = self.fixture.admin, self.fixture.client
        self.person, self.account = self.fixture.person, self.fixture.account
        self.path = f'/client/members/{self.person.id}/photos'
        self.admin_path = f'/admin/participants/{self.person.id}/photos'

    def tearDown(self):
        self.fixture.tearDown()

    def upload(self, client=None, path=None, **extra):
        client = client or self.client
        image = BytesIO()
        exif = Image.Exif()
        exif[270] = 'PRIVATE CAMERA METADATA'
        Image.new('RGB', (90, 60), 'purple').save(image, 'JPEG', exif=exif)
        image.seek(0)
        with client.session_transaction() as session:
            token = session['client_csrf']
        data = dict(csrf_token=token, action='upload', image=(image, 'camera.jpg'))
        data.update(extra)
        return client.post(path or self.path, data=data)

    def test_upload_links_participant_and_account_strips_metadata_and_stays_private(self):
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        photo = main.ParticipantPhoto.query.one()
        self.assertEqual((photo.participant_id, photo.client_id, photo.uploaded_by),
                         (self.person.id, self.account.id, 'client'))
        with Image.open(BytesIO(photo.content)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertFalse(image.getexif())
        self.assertNotIn(b'PRIVATE CAMERA METADATA', photo.content)
        path = f'/participant-photos/{photo.id}/image'
        for client in (self.client, self.admin):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/jpeg')
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertNotIn('ETag', response.headers)
        self.assertIn('no-store', self.client.get(self.path).headers['Cache-Control'])
        self.assertIn(b'YOUR CLIENT PORTAL', self.client.get(self.path).data)
        self.assertEqual(main.app.test_client().get(path).status_code, 401)
        self.assertEqual(main.photo_library_models[0].query.count(), 0)

    def test_admin_upload_and_entry_points(self):
        self.assertEqual(self.upload(self.admin, self.admin_path).status_code, 302)
        self.assertEqual(main.ParticipantPhoto.query.one().uploaded_by, 'admin')
        for path in ('/admin/participants', f'/admin/waivers/{self.person.waiver_id}',
                     f'/admin/clients/{self.account.id}?tab=rewards'):
            page = self.admin.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'data-photo-open', page.data)
            self.assertIn(self.admin_path.encode(), page.data)
        for path in ('/client/account', '/client/waivers'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(self.path.encode(), page.data)
            self.assertIn(b'capture="environment"', page.data)
        self.assertEqual(self.client.get(self.admin_path).status_code, 302)

    def test_other_accounts_and_transfers_cannot_access_old_photos(self):
        self.upload()
        photo = main.ParticipantPhoto.query.one()
        image_path = f'/participant-photos/{photo.id}/image'
        other = main.app.test_client()
        account = main.ClientAccount(email='other-photo@example.com', first_name='Other', last_name='Client')
        main.db.session.add(account)
        main.db.session.commit()
        with self.client.session_transaction() as session:
            session['client_id'] = account.id
            session['client_signed_in'] = datetime.now().timestamp()
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.assertEqual(self.client.get(image_path).status_code, 404)
        self.assertEqual(self.upload().status_code, 404)
        new_waiver = self.fixture.make_waiver(account.email, 'PHOTO-TRANSFER')
        main.db.session.add(fixtures.Custodian(participant_id=self.person.id,
                                             client_id=account.id, waiver_id=new_waiver.id))
        main.db.session.commit()
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertNotIn(image_path.encode(), self.client.get(self.path).data)
        self.assertEqual(self.client.get(image_path).status_code, 404)
        with other.session_transaction() as session:
            session['client_id'] = self.account.id
            session['client_signed_in'] = datetime.now().timestamp()
        self.assertEqual(other.get(self.path).status_code, 404)
        self.assertEqual(other.get(image_path).status_code, 404)
        self.assertEqual(self.admin.get(image_path).status_code, 200)

    def test_csrf_invalid_images_and_delete(self):
        self.assertEqual(self.upload(csrf_token='wrong').status_code, 400)
        self.assertEqual(self.upload(image=(BytesIO(b'<script>not an image</script>'), 'fake.jpg')).status_code, 400)
        self.assertEqual(self.upload(image=(BytesIO(b'x' * 10_000_001), 'huge.jpg')).status_code, 400)
        self.assertEqual(main.ParticipantPhoto.query.count(), 0)
        self.upload()
        photo = main.ParticipantPhoto.query.one()
        data = dict(action='delete', photo_id=photo.id, csrf_token=self.fixture.fixture.csrf())
        self.assertEqual(self.client.post(self.path, data=dict(data, csrf_token='bad')).status_code, 400)
        self.assertEqual(self.client.post(self.path, data=data).status_code, 302)
        self.assertEqual(main.ParticipantPhoto.query.count(), 0)

    def test_expired_admin_session_cannot_read_photo(self):
        self.upload()
        photo = main.ParticipantPhoto.query.one()
        with self.admin.session_transaction() as session:
            session['admin_last_activity'] = datetime.utcnow().timestamp() - 1900
        self.assertEqual(self.admin.get(f'/participant-photos/{photo.id}/image').status_code, 302)

    def test_mobile_dialog_preview_cancel_and_file_choices(self):
        if not browsers.EDGE.is_file():
            self.skipTest('Microsoft Edge is not installed')
        browsers.NativeFormBrowserTest().browser(self.client.get(self.path).data, '''
            const control = document.querySelector('[data-participant-photo]');
            const dialog = control.querySelector('dialog');
            control.querySelector('[data-photo-open]').click();
            assert(dialog.open, 'Add image opens dialog');
            assert(control.querySelector('[data-photo-camera-input]').getAttribute('capture') === 'environment', 'rear camera offered');
            let picked = false;
            const input = control.querySelector('[data-photo-input]');
            input.click = () => { picked = true; };
            control.querySelector('[data-photo-device]').click();
            assert(picked, 'device button opens upload picker');
            const files = new DataTransfer();
            files.items.add(new File(['test'], 'photo.jpg', {type:'image/jpeg'}));
            input.files = files.files;
            change(input);
            assert(!control.querySelector('[data-photo-preview]').hidden, 'selected image preview');
            assert(control.querySelector('[data-photo-status]').textContent.includes('photo.jpg'), 'selected filename');
            control.querySelector('[data-photo-close]').click();
            await new Promise(resolve => setTimeout(resolve, 50));
            assert(!dialog.open && !input.files.length, 'cancel closes and resets');
            assert(control.querySelector('[data-photo-preview]').hidden, 'cancel clears preview');
        ''', width=390)

    def test_missing_account_and_waiver_deletion(self):
        orphan_waiver = self.fixture.make_waiver('no-account@example.com', 'PHOTO-NO-ACCOUNT')
        person = main.Participant(waiver_id=orphan_waiver.id, first_name='No', last_name='Account', age=7, gender='Other')
        main.db.session.add(person)
        main.db.session.commit()
        path = f'/admin/participants/{person.id}/photos'
        self.assertIn(b'Create a client account', self.admin.get(path).data)
        self.assertEqual(self.upload(self.admin, path).status_code, 409)
        self.upload()
        self.assertEqual(main.ParticipantPhoto.query.count(), 1)
        self.assertEqual(self.admin.post(f'/admin/waivers/{self.person.waiver_id}/delete').status_code, 200)
        self.assertEqual(main.ParticipantPhoto.query.count(), 0)

    def share(self, photo, **changes):
        path = f'/client/photos?participant_photo={photo.id}'
        self.assertEqual(self.client.get(path).status_code, 200)
        with self.client.session_transaction() as session:
            token, csrf = session['photo_upload_token'], session['client_csrf']
        name = self.account.first_name + ' ' + self.account.last_name
        data = dict(csrf_token=csrf, submission_token=token, terms_version='1', responsible_name=name,
                    agree='yes', authority='yes', portfolio='yes', website='yes', social='yes',
                    custom_0=json.dumps(dict(name=name, strokes=[[[0.1, 0.2], [0.8, 0.5]]])),
                    people_count_0='1', people_0='Alex Client | Butterfly face paint')
        data.update(changes)
        return self.client.post(path, data=data)

    def test_send_saved_photo_through_signed_release_review_and_withdrawal(self):
        self.upload()
        source = main.ParticipantPhoto.query.one()
        self.assertIn(b'Send to image library', self.client.get(self.path).data)
        permission_page = self.client.get(f'/client/photos?participant_photo={source.id}').data
        self.assertIn(f'/participant-photos/{source.id}/image'.encode(), permission_page)
        self.assertNotIn(b'name="photo_0"', permission_page)
        self.assertEqual(self.share(source).status_code, 302)
        Form, Submission, Media = main.native_form_models
        item, media = Submission.query.one(), Media.query.one()
        website_photo = main.photo_library_models[0].query.one()
        self.assertEqual(json.loads(item.answers_json)['participant_photo_id'], source.id)
        self.assertEqual(media.submission_id, item.id)
        self.assertEqual(website_photo.status, 'pending')
        self.assertIsNotNone(main.app.extensions['native_form_records']['submission_record'](item))
        self.assertIn(b'Signed photo permission recorded', self.admin.get(self.admin_path).data)
        # Reopening or resubmitting cannot duplicate an existing active release.
        self.assertEqual(self.client.get(f'/client/photos?participant_photo={source.id}').status_code, 302)
        self.client.post(f'/client/photos?participant_photo={source.id}', data={'csrf_token':self.fixture.fixture.csrf()})
        self.assertEqual(Submission.query.count(), 1)
        self.assertEqual(self.admin.post(self.admin_path, data=dict(csrf_token='admin-token',
            action='send_library', photo_id=source.id)).status_code, 302)
        public_path = f'/website/photos/{website_photo.id}.jpg'
        guest = main.app.test_client()
        self.assertEqual(guest.get(public_path).status_code, 404)
        self.assertEqual(self.admin.post('/admin/photo-library', data=dict(csrf_token='admin-token',
            media_id=media.id, status='approved', reviewed_permissions='yes',
            alt='Colourful face paint', gallery='yes')).status_code, 302)
        self.assertEqual(guest.get(public_path).status_code, 200)
        self.assertIn(public_path.encode(), guest.get('/gallery').data)
        self.client.post('/client/photos', data=dict(csrf_token=self.fixture.fixture.csrf(),
            action='withdraw', submission_id=item.id))
        self.assertEqual(guest.get(public_path).status_code, 404)
        self.assertNotIn(public_path.encode(), guest.get('/gallery').data)
        self.assertNotIn(b'Signed photo permission recorded', self.admin.get(self.admin_path).data)

    def test_library_requires_photo_specific_signed_permission_and_ownership(self):
        self.upload()
        source = main.ParticipantPhoto.query.one()
        for invalid in (dict(authority=''), dict(website=''), dict(custom_0='')):
            self.assertEqual(self.share(source, **invalid).status_code, 200)
            self.assertEqual(main.native_form_models[1].query.count(), 0)
        self.admin.post(self.admin_path, data=dict(csrf_token='admin-token',
            action='send_library', photo_id=source.id))
        self.assertEqual(main.photo_library_models[0].query.count(), 0)
        self.assertEqual(self.client.post(self.path, data=dict(csrf_token=self.fixture.fixture.csrf(),
            action='send_library', photo_id=source.id)).status_code, 403)
        self.assertEqual(self.admin.post(self.admin_path, data=dict(action='send_library', photo_id=source.id)).status_code, 400)
        other_waiver = self.fixture.make_waiver('unrelated@example.com', 'OTHER-PHOTO')
        other_person = main.Participant(waiver_id=other_waiver.id, first_name='Other', last_name='Person', age=8, gender='Other')
        main.db.session.add(other_person)
        main.db.session.flush()
        foreign = main.ParticipantPhoto(participant_id=other_person.id, client_id=self.account.id,
            content=source.content, uploaded_by='admin')
        main.db.session.add(foreign)
        main.db.session.commit()
        self.assertEqual(self.client.get(f'/client/photos?participant_photo={foreign.id}').status_code, 404)
        self.assertEqual(self.client.post(f'/client/photos?participant_photo={foreign.id}').status_code, 404)

    def test_deleting_private_photo_withdraws_linked_public_copy(self):
        self.upload()
        source = main.ParticipantPhoto.query.one()
        self.share(source)
        item = main.native_form_models[1].query.one()
        media = main.native_form_models[2].query.one()
        photo = main.photo_library_models[0].query.one()
        self.admin.post('/admin/photo-library', data=dict(csrf_token='admin-token',
            media_id=media.id, status='approved', reviewed_permissions='yes', alt='Face paint', gallery='yes'))
        public_path = f'/website/photos/{photo.id}.jpg'
        self.assertEqual(main.app.test_client().get(public_path).status_code, 200)
        self.client.post(self.path, data=dict(csrf_token=self.fixture.fixture.csrf(), action='delete', photo_id=source.id))
        self.assertIn('withdrawn_at', json.loads(item.answers_json))
        self.assertEqual(main.app.test_client().get(public_path).status_code, 404)
        self.assertEqual(photo.status, 'withdrawn')
