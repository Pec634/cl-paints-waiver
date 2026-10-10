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
    def test_upload_json_errors_and_expired_session(self):
        response=self.guest.post('/admin/photo-library/upload',headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,401)
        self.assertIn('Sign in',response.json['error'])
        response=self.admin.post('/admin/photo-library/upload',headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,400)
        self.assertIn('fresh form',response.json['error'])
        with self.admin.session_transaction() as state:
            state['admin_last_activity']=0
        response=self.admin.post('/admin/photo-library/upload',headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,401)
        self.assertIn('expired',response.json['error'])

    def test_camera_multi_picture_jpeg_upload(self):
        image=BytesIO()
        Image.new('RGB',(60,60),'pink').save(image,format='MPO',save_all=True,append_images=[Image.new('RGB',(60,60),'blue')])
        image.seek(0)
        self.assertEqual(Image.open(image).format,'MPO')
        image.seek(0)
        response=self.admin.post('/admin/photo-library/upload',headers={'Accept':'application/json'},data=dict(csrf_token='admin-token',permissions='Permission recorded',authority='yes',images=(image,'camera.jpeg')))
        self.assertEqual(response.status_code,200)
        self.assertEqual(Image.open(BytesIO(main.db._website_admin_photo.query.one().content)).format,'JPEG')

    def test_website_editor_drafts_versions_seo_and_safe_blocks(self):
        base=dict(csrf_token='admin-token',page='about')
        layout={'_blocks':[{'cells':[{'kind':'heading','text':'New colourful section','animation':{'kind':'slide-up','duration':2,'delay':0.5,'repeat':2,'trigger':'scroll','easing':'ease-out'}},{'kind':'button','text':'Plan it','link':'/booking'}],'style':{'gap':32,'background':'#ffffff'}}], '_seo':{'title':'Custom face painting title','description':'Our custom description'}}
        response=self.admin.post('/admin/website-builder',data=dict(base,action='draft',layout=json.dumps(layout)))
        self.assertEqual(response.status_code,200)
        self.assertNotIn('New colourful section',self.guest.get('/about').text)
        self.assertIn('New colourful section',self.admin.get('/admin/website-builder?page=about').text)
        response=self.admin.post('/admin/website-builder',data=dict(base,action='publish',layout=json.dumps(layout)))
        self.assertEqual(response.status_code,200)
        public=self.guest.get('/about').text
        self.assertIn('<title>Custom face painting title</title>',public)
        self.assertIn('New colourful section',public)
        revision=main.db._website_revision.query.one()
        response=self.admin.post('/admin/website-builder',data=dict(base,action='restore',revision=revision.id))
        self.assertEqual(response.status_code,200)
        self.assertIn('New colourful section',self.guest.get('/about').text)
        self.assertNotIn('New colourful section',self.admin.get('/admin/website-builder?page=about').text)
        for malicious in ({'_blocks':[{'cells':[{'kind':'button','link':'javascript:alert(1)'}]}]}, {'_blocks':[{'cells':[{'kind':'video','video':'https://evil.example/embed/1'}]}]}, {'0':{'style':{'background':'url(evil)'}}}, {'0':{'animation':{'kind':'flash'}}}, {'0':{'animation':{'duration':0}}}, {'0':{'desktop':{'x':float('nan')}}}):
            self.assertEqual(self.admin.post('/admin/website-builder',data=dict(base,action='publish',layout=json.dumps(malicious))).status_code,400)
        self.assertIn('New colourful section',self.guest.get('/about').text)

    def test_website_editor_grid_and_animation_browser(self):
        browser=browsers.NativeFormBrowserTest()
        browser.browser(self.guest.get('/').data, '''
            window.websiteEditor.apply({_blocks:[{cells:[{kind:'heading',text:'Live new block',animation:{kind:'pulse',duration:2,delay:0,repeat:2,easing:'linear',trigger:'load'}},{kind:'text',text:'Next column'}]}]});
            const row=document.querySelector('.wb-row'),cell=row.firstElementChild;
            assert(row.children.length===2,'columns missing');
            assert(cell.classList.contains('wb-pulse'),'animation missing');
            assert(getComputedStyle(cell).animationDuration==='2s','animation speed incorrect');
            assert(row.textContent.includes('Live new block'),'block text missing');
            assert(getComputedStyle(row).gridTemplateColumns.split(' ').length===1,'mobile columns must stack');
            window.websiteEditor.apply({});
            assert(!document.querySelector('.wb-row'),'reset rows failed');
        ''',width=390)

    def test_website_editor_full_browser_editing_flow(self):
        import html
        import re
        from pathlib import Path
        public=self.guest.get('/').text
        public=public.replace('<head>','<head><script>window.onerror=(message)=>window.previewError=message;</script>',1)
        static=(Path(__file__).resolve().parent/'static').as_uri()+'/'
        public=public.replace('src="/static/','src="'+static).replace('href="/static/','href="'+static)
        for name in ('website-layout.js','website.js'):
            public=re.sub(r'<script src="[^"]*/'+re.escape(name)+r'" defer></script>',lambda match:'<script>'+ (Path(__file__).resolve().parent/'static'/name).read_text(encoding='utf-8')+'</script>',public)
        public=public.replace('</head>','<style>'+(Path(__file__).resolve().parent/'static'/'website-editor.css').read_text(encoding='utf-8')+'</style></head>')
        public=re.sub(r'<link\b[^>]*>','',public)
        markup=self.admin.get('/admin/website-builder').text
        markup=markup.replace('src="/"', 'srcdoc="'+html.escape(public,quote=True)+'"')
        browsers.NativeFormBrowserTest().browser(markup.encode(), '''
            await new Promise(resolve=>setTimeout(resolve,400));
            const iframe=document.getElementById('builder-preview');
            assert(iframe.contentWindow.websiteEditor,'preview failed: '+iframe.contentWindow.previewError);
            document.getElementById('builder-columns').value='2';
            document.getElementById('builder-kind').value='heading';
            document.getElementById('builder-add').click();
            assert(iframe.contentDocument.querySelector('.wb-row').children.length===2,'add row failed');
            const text=document.getElementById('builder-text');text.value='My new headline';input(text);
            assert(iframe.contentDocument.querySelector('.wb-row h2').textContent==='My new headline','live block edit failed');
            const animation=document.getElementById('builder-animation');animation.value='float';input(animation);
            assert(iframe.contentDocument.querySelector('.wb-cell').classList.contains('wb-float'),'live animation failed');
            document.getElementById('builder-undo').click();
            assert(!iframe.contentDocument.querySelector('.wb-cell').classList.contains('wb-float'),'undo animation failed');
            document.getElementById('builder-redo').click();
            assert(iframe.contentDocument.querySelector('.wb-cell').classList.contains('wb-float'),'redo failed');
            document.getElementById('builder-device').click();
            await new Promise(resolve=>setTimeout(resolve,100));
            assert(iframe.contentWindow.getComputedStyle(iframe.contentDocument.querySelector('.wb-row')).gridTemplateColumns.split(' ').length===1,'mobile row failed');
            document.getElementById('builder-rows').querySelector('button').click();
            document.getElementById('builder-resize').click();
            assert(iframe.contentDocument.getElementById('builder-resize-handle'),'resize handle missing');
            iframe.contentDocument.getElementById('builder-resize-handle').remove();
            document.getElementById('builder-template-name').value='Reusable test section';
            document.getElementById('builder-template-save').click();
            document.getElementById('builder-template-add').click();
            assert(iframe.contentDocument.querySelectorAll('.wb-row').length===2,'reusable section insertion failed');
            document.getElementById('builder-layers').querySelector('button').click();
            document.getElementById('builder-lock').click();
            assert(document.getElementById('builder-layers').textContent.includes('Locked'),'layer locking failed');
            document.getElementById('builder-hide').click();
            assert(iframe.contentWindow.websiteEditor.nodes[0].hidden,'layer hiding failed');
            const size=document.getElementById('builder-size');size.value='tablet';change(size);
            assert(iframe.style.width==='820px','tablet preview failed');
            document.getElementById('builder-check').click();
            assert(document.getElementById('builder-checks').textContent.length>0,'prepublish report missing');
            document.getElementById('builder-compare').click();
            assert(!iframe.contentWindow.websiteEditor.nodes[0].hidden,'published comparison failed');
            document.getElementById('builder-compare').click();
            assert(iframe.contentWindow.websiteEditor.nodes[0].hidden,'return to draft failed');
        ''')

    def test_website_editor_mobile_layout_and_reduced_motion(self):
        browsers.NativeFormBrowserTest().browser(self.admin.get('/admin/website-builder').data, '''
            assert(document.querySelectorAll('.admin aside').length===1,'editor tools must not become another navigation bar');
            assert(document.documentElement.scrollWidth<=innerWidth+2,'editor overflows mobile screen');
            assert(getComputedStyle(document.querySelector('.builder-tools')).display!=='none','mobile editor tools missing');
        ''',width=390)
        self.assertIn('@media(prefers-reduced-motion:reduce)',(__import__('pathlib').Path(__file__).parent/'static/website-editor.css').read_text())

    def test_website_builder_save_and_validation(self):
        self.assertEqual(self.guest.get('/admin/website-builder').status_code,302)
        self.assertEqual(self.admin.get('/admin/website-builder').status_code,200)
        self.assertEqual(self.admin.post('/admin/website-builder',data={'layout':'{}'}).status_code,400)
        data=dict(csrf_token='admin-token',page='home',layout=json.dumps({'1':{'text':'A colourful celebration','desktop':{'x':20,'width':80},'mobile':{'x':0}}}))
        self.assertEqual(self.admin.post('/admin/website-builder',data=data).status_code,200)
        self.assertIn('A colourful celebration',self.guest.get('/').text)
        self.assertNotIn('A colourful celebration',self.guest.get('/about').text)
        data['layout']=json.dumps({'1':{'desktop':{'x':3000}}})
        self.assertEqual(self.admin.post('/admin/website-builder',data=data).status_code,400)
        data['layout']=json.dumps({'1':{'photo':'admin-999'}})
        self.assertEqual(self.admin.post('/admin/website-builder',data=data).status_code,400)
        data['layout']='{}'
        self.assertEqual(self.admin.post('/admin/website-builder',data=data).status_code,200)
        self.assertNotIn('A colourful celebration',self.guest.get('/').text)

    def test_website_builder_browser_controls_and_positions(self):
        browser=browsers.NativeFormBrowserTest()
        browser.browser(self.admin.get('/admin/website-builder').data, '''
            const device=document.getElementById('builder-device');
            device.click();
            assert(document.getElementById('builder-preview').style.width==='390px','mobile preview width');
            assert(typeof document.getElementById('builder-save').onclick==='function','save handler missing');
            assert(typeof document.getElementById('builder-upload').onsubmit==='function','upload handler missing');
        ''')
        browser.browser(self.guest.get('/').data, '''
            assert(window.websiteEditor.nodes.length>10,'editable page elements missing');
            const node=window.websiteEditor.nodes[1];
            window.websiteEditor.apply({'1':{text:'New heading',desktop:{x:35,y:10,width:75}}});
            assert(node.textContent==='New heading','live text change failed');
            assert(node.style.left==='35px' && node.style.width==='75%','position failed');
            window.websiteEditor.apply({});
            assert(node.textContent!=='New heading','reset failed');
        ''')

    def test_admin_upload_review_placements_and_story(self):
        Asset = main.db._website_admin_photo
        image = BytesIO()
        exif = Image.Exif()
        exif[270] = 'PRIVATE METADATA'
        Image.new('RGB', (80, 100), 'pink').save(image, 'JPEG', exif=exif)
        image.seek(0)
        self.assertEqual(self.guest.post('/admin/photo-library/upload').status_code, 302)
        self.assertEqual(self.admin.post('/admin/photo-library/upload', data={}).status_code, 400)
        response = self.admin.post('/admin/photo-library/upload', data=dict(csrf_token='admin-token', permissions='Own setup photograph, no people.', authority='yes', images=(image,'setup.jpg')))
        self.assertEqual(response.status_code, 302)
        asset = Asset.query.one()
        self.assertFalse(Image.open(BytesIO(asset.content)).getexif())
        path = f'/website/admin-photos/{asset.id}.jpg'
        self.assertEqual(self.guest.get(path).status_code, 404)
        self.assertEqual(self.admin.get('/admin/photo-library').status_code, 200)
        self.admin.post(f'/admin/photo-library/assets/{asset.id}', data=dict(csrf_token='admin-token', status='approved', alt='Colourful painting setup', reviewed_permissions='yes', gallery='yes', hero='yes'))
        self.assertEqual(self.guest.get(path).status_code, 200)
        self.assertIn(path, self.guest.get('/gallery').text)
        self.admin.post('/admin/website-stories', data=dict(csrf_token='admin-token', title='Our setup', body='Ready for a celebration.', cover_id=f'admin-{asset.id}', published='yes'))
        self.assertEqual(Story.query.one().admin_cover_id, asset.id)
        self.assertEqual(self.admin.get('/admin/website-stories').status_code, 200)
        self.assertIn('Our setup', self.guest.get('/').text)
        self.admin.post(f'/admin/photo-library/assets/{asset.id}', data=dict(csrf_token='admin-token', status='rejected'))
        self.assertEqual(self.guest.get(path).status_code, 404)
        self.assertNotIn('Our setup', self.guest.get('/').text)

    def test_admin_invalid_upload_is_atomic(self):
        Asset = main.db._website_admin_photo
        image = BytesIO()
        Image.new('RGB', (20,20)).save(image,'PNG')
        image.seek(0)
        self.admin.post('/admin/photo-library/upload', data=dict(csrf_token='admin-token', permissions='Own pictures', authority='yes', images=[(image,'valid.png'),(BytesIO(b'bad'),'bad.png')]))
        self.assertEqual(Asset.query.count(),0)
        self.admin.post('/admin/photo-library/upload', data=dict(csrf_token='admin-token', permissions='', authority='yes', images=(BytesIO(b'bad'),'bad.png')))
        self.assertEqual(Asset.query.count(),0)

    def test_existing_library_schema_upgrade_preserves_rows(self):
        from photo_library import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE website_photo (id INTEGER PRIMARY KEY, caption TEXT)'))
                connection.execute(text('CREATE TABLE website_story (id INTEGER PRIMARY KEY, title TEXT)'))
                connection.execute(text("INSERT INTO website_photo (id, caption) VALUES (7, 'Saved photograph')"))
            ensure_schema(SimpleNamespace(engine=engine))
            ensure_schema(SimpleNamespace(engine=engine))
            self.assertTrue({'about','services','contact'}.issubset({c['name'] for c in inspect(engine).get_columns('website_photo')}))
            self.assertIn('admin_cover_id', {c['name'] for c in inspect(engine).get_columns('website_story')})
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
