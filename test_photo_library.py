from io import BytesIO
import json
import unittest
from types import SimpleNamespace
from sqlalchemy import create_engine, text, inspect
from PIL import Image
import test_native_forms as fixtures
import test_native_form_browser as browsers

main = fixtures.main
Photo, Story = main.photo_library_models
Form, Submission, Media = main.native_form_models


class PhotoLibraryTest(unittest.TestCase):
    def test_existing_library_schema_upgrade_preserves_rows(self):
        from photo_library import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE website_photo (id INTEGER PRIMARY KEY, caption TEXT)'))
                connection.execute(text("INSERT INTO website_photo (id, caption) VALUES (7, 'Saved photograph')"))
            ensure_schema(SimpleNamespace(engine=engine))
            ensure_schema(SimpleNamespace(engine=engine))
            self.assertTrue({'about','services','contact'}.issubset({c['name'] for c in inspect(engine).get_columns('website_photo')}))
            with engine.connect() as connection:
                self.assertEqual(tuple(connection.execute(text('SELECT caption, about, services, contact FROM website_photo WHERE id=7')).one()), ('Saved photograph',0,0,0))
        finally:
            engine.dispose()

    def setUp(self):
        self.fixture = fixtures.NativeFormsTest()
        self.fixture.setUp()
        self.client, self.admin = self.fixture.client, self.fixture.admin
        self.guest = main.app.test_client()

    def tearDown(self):
        self.fixture.tearDown()

    def upload(self, **changes):
        self.assertEqual(self.client.get('/client/photos').status_code, 200)
        with self.client.session_transaction() as session:
            token, csrf = session['photo_upload_token'], session['client_csrf']
        account = self.fixture.fixture.fixture.account
        name = account.first_name + ' ' + account.last_name
        content = BytesIO()
        exif = Image.Exif()
        exif[270] = 'PRIVATE IMAGE METADATA'
        Image.new('RGB', (80, 100), 'pink').save(content, 'JPEG', exif=exif)
        content.seek(0)
        data = dict(csrf_token=csrf, submission_token=token, terms_version='1', responsible_name=name,
                    agree='yes', authority='yes', portfolio='yes', website='yes', social='yes',
                    custom_0=json.dumps(dict(name=name, strokes=[[[0.1,0.2],[0.8,0.5]]])),
                    photo_0=(content,'private-file-name.jpg'), people_count_0='2',
                    people_0='Private Alex | Left, blue top\nPrivate Sam | Right, tiger face paint')
        data.update(changes)
        return self.client.post('/client/photos', data=data, content_type='multipart/form-data')

    def approve(self, media, **changes):
        data = dict(csrf_token='admin-token', media_id=str(media.id), status='approved',
                    reviewed_permissions='yes', alt='Pink butterfly face paint', caption='A colourful celebration', gallery='yes')
        data.update(changes)
        return self.admin.post('/admin/photo-library', data=data)

    def test_release_review_publish_and_withdraw(self):
        self.assertEqual(self.upload().status_code, 302)
        item, media, photo = Submission.query.one(), Media.query.one(), Photo.query.one()
        data = json.loads(item.answers_json)
        self.assertEqual(data['signature']['name'], item.name)
        self.assertIn('third-party copies', item.terms_snapshot)
        self.assertNotIn(b'PRIVATE IMAGE METADATA', media.content)
        self.assertIsNotNone(main.app.extensions['native_form_records']['submission_record'](item))
        self.assertEqual(self.client.get(f'/client/form-submissions/{item.id}').status_code,200)
        path = f'/website/photos/{photo.id}.jpg'
        self.assertEqual(self.guest.get(path).status_code, 404)
        self.assertEqual(self.guest.get('/admin/photo-library').status_code, 302)
        self.assertEqual(self.guest.get(f'/admin/photo-library/{media.id}/image').status_code,302)
        self.assertIn(b'Private Alex', self.admin.get('/admin/photo-library?q=Private+Alex').data)
        self.approve(media, hero='yes', about='yes')
        self.assertEqual(self.guest.get(path).status_code, 200)
        gallery = self.guest.get('/gallery').data
        self.assertIn(path.encode(), gallery)
        self.assertNotIn(b'Private Alex', gallery)
        self.assertNotIn(item.email.encode(), gallery)
        self.assertIn(path.encode(), self.guest.get('/').data)
        self.assertIn(path.encode(), self.guest.get('/about').data)
        self.admin.post('/admin/website-stories', data=dict(csrf_token='admin-token', title='Community celebration', body='An actual event story.', location='Doncaster', cover_id=str(photo.id), published='yes'))
        self.assertIn(b'Community celebration', self.guest.get('/').data)
        with self.client.session_transaction() as session: csrf=session['client_csrf']
        self.client.post('/client/photos', data=dict(csrf_token=csrf, action='withdraw', submission_id=item.id))
        self.assertEqual(self.guest.get(path).status_code,404)
        self.assertNotIn(path.encode(),self.guest.get('/gallery').data)
        self.assertNotIn(b'Community celebration',self.guest.get('/').data)
        self.approve(media)
        self.assertEqual(self.guest.get(path).status_code,404)

    def test_required_fields_file_validation_and_csrf(self):
        self.assertEqual(self.guest.get('/client/photos').status_code,302)
        self.assertEqual(self.client.post('/client/photos',data={}).status_code,400)
        for invalid in [dict(agree=''),dict(authority=''),dict(custom_0=''),dict(people_0='Two names without descriptions'),dict(photo_0=(BytesIO(b'<svg>not a photograph</svg>'),'bad.png'))]:
            self.assertEqual(self.upload(**invalid).status_code,200)
            self.assertEqual(Submission.query.count(),0)
        self.upload()
        self.assertEqual(Submission.query.count(),1)
        media=Media.query.one()
        self.approve(media,reviewed_permissions='')
        self.assertEqual(Photo.query.one().status,'pending')

    def test_legacy_photography_forms_enter_library_and_story_drafts(self):
        form=self.fixture.create('photo')
        item=Submission(form_id=form.id,client_id=self.fixture.fixture.fixture.account.id,token='legacy-token',name='Legacy responsible person',email='legacy@example.com',title_snapshot=form.title,terms_snapshot='Website permission',answers_json=json.dumps(dict(people='Person shown',authority_confirmed=True)))
        main.db.session.add(item);main.db.session.flush()
        image=BytesIO();Image.new('RGB',(50,50),'blue').save(image,'PNG')
        media=Media(submission_id=item.id,content=image.getvalue(),mime='image/png',filename='upload-1.png')
        main.db.session.add(media);main.db.session.commit()
        self.assertIn(b'Legacy responsible person',self.admin.get('/admin/photo-library').data)
        self.approve(media)
        self.assertNotEqual(Photo.query.first().status if Photo.query.first() else 'pending','approved')
        self.admin.post('/admin/website-stories',data=dict(csrf_token='admin-token',title='Draft event',body='Real event details'))
        self.assertNotIn(b'Draft event',self.guest.get('/').data)
        story=Story.query.one()
        self.admin.post('/admin/website-stories',data=dict(csrf_token='admin-token',id=story.id,title='Published event',body='Real event details',published='yes'))
        self.assertIn(b'Published event',self.guest.get('/').data)

    def test_clients_cannot_withdraw_another_accounts_release(self):
        self.upload()
        item=Submission.query.one()
        other=main.ClientAccount(email='another-photo-owner@example.com',first_name='Other',last_name='Client')
        main.db.session.add(other);main.db.session.commit()
        with self.client.session_transaction() as session:
            session['client_id']=other.id
            csrf=session['client_csrf']
        self.assertNotIn(f'F-{item.id} ·'.encode(),self.client.get('/client/photos').data)
        response=self.client.post('/client/photos',data=dict(csrf_token=csrf,action='withdraw',submission_id=item.id))
        self.assertEqual(response.status_code,404)
        self.assertNotIn('withdrawn_at',json.loads(item.answers_json))

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_mobile_upload_signature_and_admin_layout(self):
        browsers.NativeFormBrowserTest().browser(self.client.get('/client/photos').data, '''
            assert(document.documentElement.scrollWidth<=innerWidth,'Photo form fits a phone');
            assert(document.querySelector('canvas.native-signature-canvas'),'Drawing signature available');
            assert(document.querySelector('[name="responsible_name"]').value,'Account name transferred');
            assert(document.querySelector('[name="photo_0"]').required,'First photograph required');
        ''', width=390)
        self.upload()
        browsers.NativeFormBrowserTest().browser(self.admin.get('/admin/photo-library').data, '''
            assert(document.documentElement.scrollWidth<=innerWidth,'Photo library fits a phone');
            assert(document.querySelector('[name="reviewed_permissions"]'),'Consent review control available');
        ''', width=390)
