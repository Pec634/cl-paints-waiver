"""Exercise the actual builder and public controls in Edge when it is available."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_forms as fixtures
from native_form_fields import validate_fields

EDGE = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')


@unittest.skipUnless(EDGE.is_file(), 'Microsoft Edge is not installed')
class NativeFormBrowserTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeFormsTest()
        self.fixture.setUp()
        self.form = self.fixture.create('giveaway', validate_fields([
            dict(label='Instructions', type='content', content='Read-only instructions'),
            dict(label='Add details?', type='radio', required=True, options=['Yes', 'No']),
            dict(label='Details', type='text', required=True, show_if={'field':'Add details?', 'equals':'Yes'}),
            dict(label='Design', type='cards', options=['Tiger', 'Butterfly']),
            dict(label='Extras', type='multiselect', required=True, options=['Glitter', 'Gems']),
        ]))

    def tearDown(self):
        self.fixture.tearDown()

    def browser(self, markup, assertions, width=1280, setup=''):
        static = (Path(__file__).resolve().parent / 'static').as_uri()+'/'
        markup = markup.decode().replace('src="/static/', 'src="'+static).replace('href="/static/', 'href="'+static)
        if setup: markup=markup.replace('<head>','<head><script>'+setup+'</script>',1)
        probe = '''<p id="browser-result">PENDING</p><script>
        window.addEventListener('DOMContentLoaded', async () => {
            const assert = (condition, message) => { if (!condition) throw new Error(message); };
            const change = element => element.dispatchEvent(new Event('change', {bubbles:true}));
            const input = element => element.dispatchEvent(new Event('input', {bubbles:true}));
            try { %s document.getElementById('browser-result').textContent = 'PASS'; }
            catch(error) { document.getElementById('browser-result').textContent = 'FAIL: '+error.stack; }
        });</script>''' % assertions
        markup = markup.replace('</body>', probe+'</body>')
        temp_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix='cl-paints-form-browser-') as directory:
            directory = Path(directory).resolve()
            self.assertTrue(directory.is_relative_to(temp_root))
            page = directory/'form.html'
            page.write_text(markup, encoding='utf-8')
            result = subprocess.run([str(EDGE), '--headless', '--disable-gpu', '--no-first-run',
                '--window-size='+str(width)+',900',
                '--no-default-browser-check', '--allow-file-access-from-files',
                '--user-data-dir='+str(directory/'profile'), '--dump-dom', '--virtual-time-budget=1500',
                page.as_uri()], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40)
            marker = '<p id="browser-result">'
            output = result.stdout.split(marker)[-1].split('</p>')[0]
            self.assertIn(marker, result.stdout, result.stderr[-1500:])
            self.assertEqual(output, 'PASS')

    def test_portal_mobile_navigation_and_next_steps(self):
        for client, path, button, navigation, expanded in (
            (self.fixture.admin, '/admin/dashboard', '.admin-menu-toggle', '.admin aside > nav:not(.portal-mobile-shortcuts)', '.admin-menu-open'),
            (self.fixture.client, '/client/', '.client-menu-toggle', '#client-navigation', '.is-expanded'),
        ):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.browser(page.data, '''
                const toggle = document.querySelector('%s');
                const nav = document.querySelector('%s');
                const shortcuts = document.querySelector('.portal-mobile-shortcuts');
                assert(toggle && getComputedStyle(toggle).display !== 'none', 'mobile menu button missing');
                assert(getComputedStyle(shortcuts).display === 'grid', 'quick links missing');
                assert(shortcuts.querySelectorAll('a').length === (document.querySelector('.admin') ? 3 : 4), 'quick link count');
                assert(getComputedStyle(nav).display === 'none', 'menu should start collapsed');
                toggle.click();
                assert(toggle.getAttribute('aria-expanded') === 'true', 'menu state not announced');
                assert(getComputedStyle(nav).display !== 'none', 'menu did not open');
                assert(getComputedStyle(shortcuts).display === 'none', 'quick links should hide while full menu is open');
                nav.querySelector('a').dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
                assert(toggle.getAttribute('aria-expanded') === 'false', 'Escape did not close menu');
                assert(document.activeElement === toggle, 'Escape did not restore focus');
                assert(getComputedStyle(shortcuts).display === 'grid', 'quick links should return after menu closes');
                toggle.click(); document.querySelector('main').click();
                assert(toggle.getAttribute('aria-expanded') === 'false', 'outside click did not close');
                assert(!document.querySelector('%s'), 'expanded menu class remains');
                assert(getComputedStyle(shortcuts).display === 'grid', 'outside click should restore quick links');
                assert(document.documentElement.scrollWidth <= innerWidth, 'page overflows phone width');
            ''' % (button, navigation, expanded), width=390)

    def test_portal_desktop_shortcuts_are_hidden(self):
        for client, path in ((self.fixture.admin, '/admin/dashboard'), (self.fixture.client, '/client/')):
            self.browser(client.get(path).data, '''
                assert(getComputedStyle(document.querySelector('.portal-mobile-shortcuts')).display === 'none', 'mobile shortcuts visible on desktop');
            ''')

    def test_portal_accessibility_controls_and_keyboard_shortcuts(self):
        page = self.fixture.client.get('/client/')
        self.browser(page.data, '''
            const controls = document.querySelector('.portal-display-controls');
            controls.open = true;
            const size = document.getElementById('portal-text-size');
            size.value = '125'; change(size);
            assert(getComputedStyle(document.documentElement).fontSize === '20px', 'larger text was not applied');
            const motion = document.getElementById('portal-reduce-motion');
            motion.checked = true; change(motion);
            assert(document.documentElement.classList.contains('portal-reduced-motion'), 'motion preference missing');
            assert(getComputedStyle(document.querySelector('.client-welcome-art img')).animationName === 'none', 'animation remains active');
            const contrast = document.getElementById('portal-high-contrast');
            contrast.checked = true; change(contrast);
            assert(document.documentElement.classList.contains('portal-high-contrast'), 'contrast preference missing');
            const saved = JSON.parse(localStorage.getItem('cl-paints-display-settings'));
            assert(saved.size === '125' && saved.motion && saved.contrast, 'preferences were not saved');
            const skip = document.querySelector('.portal-skip-link');
            assert(skip.hash === '#' + document.querySelector('main').id, 'skip link points to wrong content');
            assert(document.querySelector('main').getAttribute('tabindex') === '-1', 'main cannot receive keyboard focus');
            assert(document.documentElement.scrollWidth <= innerWidth, 'larger text overflows on phone');
            document.getElementById('portal-reset-display').click();
            assert(getComputedStyle(document.documentElement).fontSize === '16px', 'text size did not reset');
            assert(!document.documentElement.classList.contains('portal-high-contrast'), 'contrast did not reset');
        ''', width=390)

    def test_portal_new_screens_fit_phone_and_expose_admin_tools(self):
        booking = self.fixture.fixture.booking
        for client, path in (
            (self.fixture.admin, '/admin/notifications'),
            (self.fixture.admin, '/admin/search?q=Test'),
            (self.fixture.admin, f'/admin/bookings/{booking.id}/activity'),
            (self.fixture.client, '/client/notifications'),
            (self.fixture.client, f'/client/bookings/{booking.id}'),
        ):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.browser(page.data, '''
                assert(document.documentElement.scrollWidth <= innerWidth, 'new screen overflows phone width');
                if (document.querySelector('.admin')) {
                    const toolbar = document.querySelector('.portal-admin-toolbar');
                    assert(toolbar.querySelectorAll('a').length === 3, 'admin tools missing');
                    assert([...toolbar.querySelectorAll('a')].some(link => link.textContent.includes('Search all records')), 'global search missing');
                }
            ''', width=390)

    def test_builder_preserves_rich_blocks_and_previews_conditions(self):
        self.form.enabled=False
        fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.assertEqual(page.status_code,200)
        self.browser(page.data, '''
            const schema = document.getElementById('builder-schema');
            assert(!document.getElementById('builder-question-actions').hidden, 'visual editor did not load');
            assert(document.querySelectorAll('.builder-question').length === 5, 'blocks missing');
            assert([...document.querySelectorAll('.builder-block-settings')].every(panel => panel.hidden && panel.disabled), 'unselected edits should be collapsed');
            document.querySelectorAll('.builder-block-toggle')[0].click();
            assert(document.querySelectorAll('.builder-block-settings')[0].hidden === false, 'selected edits missing');
            document.querySelectorAll('.builder-grid-tile')[1].click();
            assert(document.querySelectorAll('.builder-block-settings')[0].hidden, 'previous edits remain visible');
            assert(!document.querySelectorAll('.builder-block-settings')[1].hidden, 'grid selection did not open edits');
            document.querySelectorAll('.builder-block-toggle')[1].click();
            assert([...document.querySelectorAll('.builder-block-settings')].every(panel => panel.hidden), 'edits did not collapse');
            let data = JSON.parse(schema.value);
            assert(data[0].content === 'Read-only instructions', 'read-only content lost');
            assert(data[2].show_if.equals === 'Yes', 'condition lost');
            assert(![...document.querySelectorAll('#builder-preview label')].some(label => label.textContent.includes('Details (required)')), 'conditional question should start hidden');
            const previewYes = document.querySelector('#builder-preview input[type=radio][value=Yes]');
            previewYes.checked = true; change(previewYes);
            assert([...document.querySelectorAll('#builder-preview label')].some(label => label.textContent.includes('Details (required)')), 'preview condition failed');
            const addType = document.getElementById('builder-add-type');
            addType.value = 'image'; document.getElementById('builder-add').click();
            data = JSON.parse(schema.value);
            assert(data.length === 6 && data[5].type === 'image', 'image block not added');
            const cards = document.querySelectorAll('.builder-question')[3];
            cards.querySelector('.builder-block-toggle').click();
            [...cards.querySelectorAll('button')].find(button => button.textContent === 'Duplicate block').click();
            data = JSON.parse(schema.value);
            assert(data.length === 7 && data[6].type === 'cards', 'card duplication failed');
            const clone = document.querySelectorAll('.builder-question')[6];
            const choices = [...clone.querySelectorAll('textarea')].find(area => area.value === 'Tiger\\nButterfly');
            choices.value = 'Tiger, deluxe\\nButterfly'; input(choices);
            data = JSON.parse(schema.value);
            assert(data[6].options[0] === 'Tiger, deluxe', 'commas in choices lost');
            assert(data[3].options[0] === 'Tiger', 'duplicate mutated original choices');
            assert(document.getElementById('builder-save-status').textContent === 'Unsaved changes', 'save status not updated');
        ''')

    def test_builder_section_navigation_reusable_library_and_presets(self):
        self.form.enabled=False;fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const tabs=[...document.querySelectorAll('#builder-section-tabs button')];
            assert(tabs.length===5,'builder sections missing');
            assert(!document.getElementById('builder-section-1').hidden,'existing draft should open blocks');
            tabs[0].click();assert(!document.getElementById('builder-section-0').hidden && document.getElementById('builder-section-1').hidden,'section navigation failed');
            tabs[4].click();assert(!document.querySelector('[name=packages]').closest('fieldset').hidden,'booking tools missing');
            const catalog=document.querySelector('.builder-catalog-editor');
            [...catalog.querySelectorAll('button')].find(button=>button.textContent==='Add package').click();
            const packageFields=catalog.querySelectorAll('.builder-dates input');
            packageFields[0].value='Party painting';input(packageFields[0]);packageFields[1].value='120';input(packageFields[1]);
            assert(document.querySelector('[name=packages]').value.includes('Party painting | 120 | 2'),'visual package editor did not save its values');
            tabs[1].click();document.getElementById('builder-insert-section').click();
            let blocks=JSON.parse(document.getElementById('builder-schema').value);
            assert(blocks.length===10 && blocks[6].type==='checkbox','venue checklist not inserted');
            assert(document.querySelectorAll('.builder-block-settings:not([hidden])').length===1,'multiple settings panels expanded');
            document.getElementById('builder-load-library').click();await new Promise(resolve=>setTimeout(resolve,10));
            const library=document.getElementById('builder-block-library');library.value='1';document.getElementById('builder-insert-library').click();
            blocks=JSON.parse(document.getElementById('builder-schema').value);
            assert(blocks.length===11 && blocks[10].label==='Instructions (2)','reusable group naming failed');
            document.getElementById('builder-template-title').value='Saved venue';document.getElementById('builder-save-group').click();await new Promise(resolve=>setTimeout(resolve,10));
            assert(window.savedGroup.title==='Saved venue' && JSON.parse(window.savedGroup.fields_json).length===11,'library save missing blocks');
            assert(!document.getElementById('builder-toolbar').hidden,'persistent actions missing');
            document.getElementById('builder-row-columns').value='3';document.getElementById('builder-arrange-rows').click();
            blocks=JSON.parse(document.getElementById('builder-schema').value);
            assert(blocks[0].layout.row===blocks[2].layout.row && blocks[0].layout.width===4 && blocks[2].layout.column===9,'three-across arrangement failed');
            const occupied=new Set();blocks.forEach(block=>{for(let col=block.layout.column;col<block.layout.column+block.layout.width;col++){const key=block.layout.row+':'+col;assert(!occupied.has(key),'arranged blocks overlap');occupied.add(key);}});
            document.getElementById('builder-new-width').value='4';document.getElementById('builder-add').click();
            blocks=JSON.parse(document.getElementById('builder-schema').value);
            assert(blocks[11].layout.row===blocks[10].layout.row && blocks[11].layout.column===9,'new block did not fill the free space');
        ''', setup='''
            window.fetch=async (url,options={})=>{
                if(options.method==='POST'){window.savedGroup=Object.fromEntries(options.body.entries());return {ok:true,json:async()=>({id:2})};}
                return {ok:true,json:async()=>({blocks:[{id:1,title:'Reusable instructions',fields:[{label:'Instructions',type:'content',content:'Reusable text',required:false,layout:{row:1,column:1,width:12}}]}]})};
            };
        ''')

    def test_builder_undo_redo_autosave_and_publish_checklist(self):
        self.form.enabled=False;fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const title=document.getElementById('builder-title'),original=title.value;
            title.value='Changed title';input(title);
            document.getElementById('builder-undo').click();assert(title.value===original,'undo did not restore title');
            document.getElementById('builder-redo').click();assert(title.value==='Changed title','redo did not restore title');
            await new Promise(resolve=>setTimeout(resolve,100));
            assert(window.autosaved.title==='Changed title' && window.autosaved.action==='autosave','draft not autosaved');
            assert(document.getElementById('builder-autosave-status').textContent.includes('Saved at'),'saved timestamp missing');
            document.getElementById('builder-publish-check').click();await new Promise(resolve=>setTimeout(resolve,10));
            assert(document.getElementById('builder-publish-results').textContent.includes('Missing test image'),'server checklist not shown');
            const heading=document.querySelector('.builder-block-toggle');heading.click();
            [...document.querySelectorAll('.builder-question')[0].querySelectorAll('button')].find(button=>button.textContent==='Remove block').click();
            assert(document.querySelectorAll('.builder-question').length===4,'block removal failed');
            document.getElementById('builder-undo').click();assert(document.querySelectorAll('.builder-question').length===5,'undo did not restore removed block');
        ''',setup='''
            const realTimeout=window.setTimeout;window.setTimeout=(fn,delay,...args)=>realTimeout(fn,delay===1800?30:delay,...args);
            window.fetch=async (url,options={})=>{
                if(options.method==='POST'){window.autosaved=Object.fromEntries(options.body.entries());return {ok:true,json:async()=>({id:1,revision:'new-version',saved_at:'2026-10-07T12:00:00Z'})};}
                return {ok:true,json:async()=>({ready:false,errors:['Missing test image'],warnings:[]})};
            };
        ''')

    def test_uploaded_images_and_selected_files_render_in_preview(self):
        self.form.enabled=False;fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const png=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='),c=>c.charCodeAt(0));
            const file=new File([png],'butterfly.png',{type:'image/png'});
            const choose=control=>{const transfer=new DataTransfer();transfer.items.add(file);control.files=transfer.files;change(control);};
            const add=type=>{document.getElementById('builder-add-type').value=type;document.getElementById('builder-add').click();};
            add('image');choose(document.querySelectorAll('.builder-question')[5].querySelector('input[type=file]'));
            await new Promise(resolve=>setTimeout(resolve,30));
            let image=document.querySelector('#builder-preview .native-image img');
            await image.decode();
            assert(image.naturalWidth===1 && image.src.startsWith('blob:'),'uploaded image did not display immediately');
            assert(JSON.parse(document.getElementById('builder-schema').value)[5].src==='/form-images/123','temporary preview URL leaked into saved schema');
            add('file');choose(document.querySelector('#builder-preview .native-block-file input[type=file]'));
            image=document.querySelector('#builder-preview .builder-file-thumbnails img');await image.decode();
            assert(image.naturalWidth===1,'chosen image thumbnail missing');
            const title=document.getElementById('builder-title');title.value='Updated title';input(title);
            assert(document.querySelector('#builder-preview .native-block-file input[type=file]').files.length===1,'preview rerender lost the selected file');
            document.querySelector('.builder-open-preview').click();
            assert(document.querySelector('#builder-preview-dialog .builder-file-thumbnails img'),'full preview lost thumbnail');
            document.getElementById('builder-preview-reset').click();
            assert(!document.querySelector('#builder-preview .builder-file-thumbnails img'),'reset retained selected image');
        ''',setup='''window.fetch=async()=>({ok:true,json:async()=>({url:'/form-images/123',mime:'image/png'})});''')

    def test_studio_uses_photo_templates_without_illustrated_controls(self):
        page=self.fixture.client.get('/client/face-paint-studio')
        self.assertEqual(page.status_code,200)
        self.browser(page.data, '''
            const model=document.getElementById('paint-model');
            assert(model.options.length===8 && ![...model.options].some(option=>option.value==='illustrated'),'illustrated template still selectable');
            assert(document.querySelector('.paint-character-custom').getBoundingClientRect().height===0,'custom character controls remain visible');
            assert(window.CLStudioCore && window.CLStudioEdits,'studio painting tools failed to initialise');
            model.value='illustrated';window.CLPortraits.selected();
            assert(model.value==='adult-male','legacy illustrated designs did not switch to a photo template');
            change(model);window.CLStudioCore.drawFace();window.CLStudioCore.render();
            assert(!document.getElementById('paint-animate').checked,'character animation remains active');
        ''')

    def test_client_bookings_link_stays_visible_during_activation(self):
        page=self.fixture.client.get('/client/')
        self.browser(page.data, '''
            const navigation=document.querySelector('.client-navigation');
            const group=[...navigation.querySelectorAll('details')].find(item=>item.querySelector('summary').textContent==='My events');
            group.open=true;
            const link=group.querySelector('a');
            assert(link.getAttribute('href')==='/client/bookings','Bookings destination correct');
            const event=new MouseEvent('click',{bubbles:true,cancelable:true});
            link.addEventListener('click',click=>click.preventDefault(),{once:true});
            link.dispatchEvent(event);
            assert(group.open,'Dropdown stays open while link activates');
            await new Promise(resolve=>setTimeout(resolve,50));
            assert(!group.open,'Menu closes after link activation');
        ''')

    def test_admin_groups_and_saved_filters(self):
        page=self.fixture.admin.get('/admin/bookings')
        self.browser(page.data, '''
            const groups=[...document.querySelectorAll('.admin-navigation-group')];
            assert(groups.length===4,'Four admin navigation groups');
            const active=document.querySelector('nav[aria-label="Admin navigation"] a[aria-current="page"]');
            assert(active.closest('details').open,'Current navigation group expanded');
            const bounds=document.querySelector('.admin aside').getBoundingClientRect();
            for(const group of groups) {
                group.open=true;
                for(const link of group.querySelectorAll('a')) {
                    assert(getComputedStyle(link).display==='flex','Navigation links are button blocks');
                    assert(link.getBoundingClientRect().right<=bounds.right,'Button stays within sidebar');
                }
            }
            assert(getComputedStyle(active).backgroundColor===getComputedStyle(document.querySelector('.btn.primary')).backgroundColor,'Active navigation uses brand colour');
            groups[0].open=true;
            groups[1].open=true;
            assert(groups[1].open && !groups[0].open,'Only one navigation folder opens');
            groups[1].querySelector('summary').click();
            assert(!groups[1].open,'Folder can collapse');
            const row=document.querySelector('.portal-saved-filter');
            assert(row,'Saved filter controls available');
            row.querySelector('button').click();
            assert(!row.querySelector('a').hidden,'Saved filter can be restored');
            assert(row.querySelector('a').getAttribute('href').includes('filter='),'Only filter saved');
            row.querySelectorAll('button')[1].click();
            assert(row.querySelector('a').hidden,'Saved filter removed');
        ''',width=390)

    def test_booking_section_navigation_and_mobile_cards(self):
        booking=self.fixture.fixture.booking
        admin_page=self.fixture.admin.get(f'/admin/bookings/{booking.id}/activity')
        self.browser(admin_page.data, '''
            const nav=document.querySelector('.portal-booking-navigation');
            const links=[...nav.querySelectorAll('a')];
            assert(getComputedStyle(nav).display==='grid','Booking buttons use an organised grid');
            assert(getComputedStyle(links[0]).color==='rgb(16, 33, 63)','Booking buttons have dark readable text');
            assert(Math.abs(links[0].getBoundingClientRect().top-links[1].getBoundingClientRect().top)<1,'Desktop buttons share a row');
        ''')
        page=self.fixture.client.get(f'/client/bookings/{booking.id}')
        self.browser(page.data, '''
            const links=[...document.querySelectorAll('.portal-booking-navigation a')];
            assert(links.length>=4,'Booking sections have shortcuts');
            assert(links.every(link=>document.querySelector(link.hash)),'Shortcuts point to existing sections');
            const headings=[...document.querySelectorAll('.client-main > section.panel h2')].map(h=>h.textContent.trim());
            assert(headings.indexOf('Your event details')<headings.indexOf('Payments & balance'),'Event summary before payments');
            assert(headings.indexOf('Booking activity timeline')>headings.indexOf('Payments & balance'),'Activity after payments');
            assert(document.documentElement.scrollWidth<=innerWidth,'Booking fits phone');
        ''',width=390)
        page=self.fixture.admin.get('/admin/bookings')
        self.browser(page.data, '''
            const cell=document.querySelector('td[data-column-label]');
            assert(cell && getComputedStyle(cell).display==='block','Mobile table uses labelled cards');
            assert(cell.dataset.columnLabel,'Card fields have labels');
            assert(document.documentElement.scrollWidth<=innerWidth,'Booking cards fit phone');
        ''',width=390)

    def test_account_unsaved_changes_warning(self):
        page=self.fixture.client.get('/client/account')
        self.browser(page.data, '''
            const form=document.querySelector('form[data-warn-unsaved]');
            const field=form.querySelector('[name="first_name"]');
            const original=field.value;
            field.value='Changed name';input(field);
            const changed=new Event('beforeunload',{cancelable:true});window.dispatchEvent(changed);
            assert(changed.defaultPrevented,'Unsaved edits warn before leaving');
            field.value=original;input(field);
            const reverted=new Event('beforeunload',{cancelable:true});window.dispatchEvent(reverted);
            assert(!reverted.defaultPrevented,'Reverted edits do not warn');
        ''')

    def test_mobile_studio_layout_and_tools(self):
        page=self.fixture.client.get('/client/face-paint-studio')
        self.browser(page.data, '''
            const studio=document.querySelector('.paint-studio');
            assert(window.CLStudioCore && window.CLStudioEdits,'Painting tools initialize');
            assert(getComputedStyle(document.querySelector('.studio-mobile-shortcuts')).display==='flex','Mobile shortcuts visible');
            const panels=[...studio.querySelectorAll(':scope > .studio-mobile-panel')];
            assert(panels.length>=2 && panels.every(panel=>!panel.open),'Mission and progress initially collapsed');
            assert(document.querySelector('#studio-face').getBoundingClientRect().top < panels[0].getBoundingClientRect().top,'Canvas before mission information');
            const groups=[...document.querySelectorAll('.paint-controls > details')];
            groups[0].open=true;
            await new Promise(resolve=>setTimeout(resolve,50));
            groups[1].open=true;
            await new Promise(resolve=>setTimeout(resolve,50));
            assert(groups[1].open && !groups[0].open,'One tool group at a time');
            assert(studio.getBoundingClientRect().right<=innerWidth+1,'Studio fits phone');
        ''',width=390)

    def test_public_form_review_does_not_submit_until_confirmed(self):
        page=self.fixture.client.get('/forms/'+str(self.form.id))
        self.browser(page.data, '''
            const form=document.querySelector('form.client-form');
            const no=form.querySelector('[name=custom_1][value=No]');no.checked=true;change(no);
            const extras=form.querySelector('[name=custom_4][value=Glitter]');extras.checked=true;change(extras);
            form.querySelector('[name=agree]').checked=true;
            let submitted=false;form.addEventListener('submit',event=>{if(!event.defaultPrevented){submitted=true;event.preventDefault();}});
            form.requestSubmit();
            const dialog=document.querySelector('dialog.booking-review-dialog');
            assert(dialog.open && !submitted,'review did not stop initial submission');
            assert(dialog.textContent.includes('Extras: Glitter') && !dialog.textContent.includes('Details:'),'review answers or hidden rules incorrect');
            [...dialog.querySelectorAll('button')].find(button=>button.textContent==='Confirm and submit').click();
            assert(submitted && !dialog.open,'confirmed submission not released');
        ''',setup='window.fetch=async()=>({ok:true,json:async()=>({answers:{},csrf_token:"test",fingerprint:"test"})});')

    def test_booking_packages_estimates_travel_and_availability(self):
        form=self.fixture.create('booking')
        fixtures.main.app.extensions['native_form_records']['set_settings'](form,dict(packages='Party | 120 | 2 | Face painting',extras='Glitter | 15 | 0 | Sparkle'))
        fixtures.main.db.session.commit()
        page=self.fixture.client.get('/booking?seasonal='+str(form.id))
        self.browser(page.data, '''
            const form=document.querySelector('form.booking-form');
            form.querySelector('[name=booking_package][value=Party]').click();form.querySelector('[name=booking_extras][value=Glitter]').click();
            assert(document.getElementById('estimatedEventCost').textContent.includes('135.00'),'package estimate incorrect');
            const payment=form.querySelector('[name=payment_preference]');payment.value='50% deposit';change(payment);
            assert(document.getElementById('depositEstimateAmount').textContent.includes('67.50'),'deposit estimate incorrect');
            const miles=form.querySelector('[name=travel_miles]');miles.value='20';input(miles);
            assert(document.getElementById('booking-travel-estimate').textContent.includes('Provisional travel charge:'),'travel estimate missing');
            document.getElementById('booking-check-dates').click();await new Promise(resolve=>setTimeout(resolve,10));
            assert(document.getElementById('booking-dates-result').textContent.includes('unavailable'),'availability result missing');
        ''',setup='''window.fetch=async url=>({ok:true,json:async()=>String(url).includes('availability-check')?{success:true,available:false,message:'This time is unavailable.'}:{answers:{},csrf_token:'test',fingerprint:'test'}});''')

    def test_grid_controls_dragging_keyboard_resize_and_overlap_rejection(self):
        self.form.enabled=False
        fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const read = () => JSON.parse(document.getElementById('builder-schema').value);
            const edit = (index, key, value) => {
                const control = document.querySelectorAll('.builder-question')[index].querySelector('[data-layout-setting='+key+']');
                control.value = value; change(control);
            };
            assert(!document.getElementById('builder-grid-panel').hidden, 'grid editor missing');
            edit(0, 'width', 6);
            edit(1, 'width', 6);
            edit(1, 'column', 7);
            edit(1, 'row', 1);
            assert(read()[0].layout.width === 6 && read()[1].layout.column === 7 && read()[1].layout.row === 1, 'side-by-side placement failed');
            const previewBlocks = document.querySelectorAll('#builder-preview .native-block');
            const firstBox = previewBlocks[0].getBoundingClientRect(), secondBox = previewBlocks[1].getBoundingClientRect();
            assert(Math.abs(firstBox.top - secondBox.top) < 2 && secondBox.left > firstBox.right, 'preview does not show columns side by side');
            edit(0, 'width', 12);
            assert(read()[0].layout.width === 6, 'overlapping resize accepted');
            assert(document.getElementById('builder-grid-status').textContent.includes('occupied'), 'overlap explanation missing');
            let tile = document.querySelector('#builder-placement-grid [data-block-index="0"]');
            tile.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft', shiftKey:true, bubbles:true}));
            assert(read()[0].layout.width === 5, 'keyboard resize failed');
            tile = document.querySelector('#builder-placement-grid [data-block-index="0"]');
            tile.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));
            assert(read()[0].layout.column === 2, 'keyboard move failed');
            const designIndex = read().findIndex(item => item.label === 'Design');
            const transfer = new DataTransfer();
            tile = document.querySelector('#builder-placement-grid [data-block-index="'+designIndex+'"]');
            tile.dispatchEvent(new DragEvent('dragstart', {dataTransfer:transfer, bubbles:true}));
            document.querySelector('.builder-grid-cell[data-grid-row="2"][data-grid-column="1"]').dispatchEvent(new DragEvent('drop', {dataTransfer:transfer, bubbles:true, cancelable:true}));
            assert(read().find(item => item.label === 'Design').layout.row === 2, 'drag placement failed');
            document.getElementById('builder-preview-mobile').click();
            const mobileBoxes = document.querySelectorAll('#builder-preview .native-block');
            assert(mobileBoxes[1].getBoundingClientRect().top > mobileBoxes[0].getBoundingClientRect().bottom, 'phone preview not stacked');
            document.getElementById('builder-stack').click();
            assert(read().every((item,index) => item.layout.row === index+1 && item.layout.column === 1 && item.layout.width === 12), 'stack reset failed');
        ''')

    def test_public_grid_uses_columns_and_stacks_on_small_screens(self):
        self.form.fields_json=fixtures.json.dumps(validate_fields([
            dict(label='First',type='text',layout=dict(row=1,column=1,width=6)),
            dict(label='Second',type='text',layout=dict(row=1,column=7,width=6)),
        ]))
        fixtures.main.db.session.commit()
        page=self.fixture.client.get('/forms/'+str(self.form.id))
        self.browser(page.data, '''
            const blocks = document.querySelectorAll('.native-block');
            const first = blocks[0].getBoundingClientRect(), second = blocks[1].getBoundingClientRect();
            assert(Math.abs(first.top-second.top) < 2 && second.left > first.right, 'public grid not side by side');
        ''')
        self.browser(page.data, '''
            assert(window.matchMedia('(max-width: 640px)').matches, 'phone viewport unavailable');
            const blocks = document.querySelectorAll('.native-block');
            assert(blocks[1].getBoundingClientRect().top > blocks[0].getBoundingClientRect().bottom, 'stacked grid not in reading order');
        ''', width=390)

    def test_public_advanced_steps_repeats_calculations_signatures_and_submit_data(self):
        self.form.fields_json=fixtures.json.dumps(validate_fields([
            dict(label='Guests',type='number',required=True,min='1'),
            dict(label='Design',type='select',required=True,options=['Standard','Deluxe'],option_values={'Standard':'10','Deluxe':'15'}),
            dict(label='Estimate',type='calculation',calculation=dict(operation='product',sources=['Guests','Design'],base='1',precision=2,prefix='£')),
            dict(label='Participants',type='repeat',required=True,max_items=3,children=[dict(label='Name',type='text',required=True)]),
            dict(label='People count',type='calculation',calculation=dict(operation='count',sources=['Participants'],base='0',precision=0)),
            dict(label='Second step',type='pagebreak'),
            dict(label='Signature',type='signature',required=True),
            dict(label='Large party details',type='text',show_if=dict(mode='all',rules=[dict(field='Guests',operator='greater',value='2'),dict(field='Design',operator='equals',value='Deluxe')]),required_if=dict(mode='any',rules=[dict(field='Guests',operator='greater',value='2')])),
        ]))
        fixtures.main.db.session.commit()
        page=self.fixture.client.get('/forms/'+str(self.form.id))
        self.browser(page.data, '''
            const block = label => document.querySelector('[data-field-label="'+label+'"]');
            const guests = block('Guests').querySelector('input'); guests.value='3'; input(guests);
            const design = block('Design').querySelector('select'); design.value='Deluxe'; change(design);
            assert(block('Estimate').querySelector('output').textContent === '£45.00', 'live calculation incorrect');
            const repeat = block('Participants');
            let name = repeat.querySelector('.native-repeat-row input'); name.value='Alex'; input(name);
            [...repeat.querySelectorAll('button')].find(button=>button.textContent==='Add another row').click();
            name = repeat.querySelectorAll('.native-repeat-row input')[1]; name.value='Sam'; input(name);
            assert(block('People count').querySelector('output').textContent==='2', 'row count calculation incorrect');
            assert(document.querySelector('[data-native-tail]').hidden, 'final consent shown before last step');
            [...document.querySelectorAll('.native-page-navigation button')].find(button=>button.textContent==='Next step').click();
            assert(!block('Signature').hidden && block('Guests').hidden, 'page navigation failed');
            const details=block('Large party details').querySelector('input');
            assert(details.required && !details.disabled, 'conditional requirement missing'); details.value='Venue notes'; input(details);
            const signer=block('Signature').querySelector('input'); signer.value='Test Client'; input(signer);
            const canvas=block('Signature').querySelector('canvas'); canvas.setPointerCapture=()=>{};
            const rect=canvas.getBoundingClientRect();
            canvas.dispatchEvent(new PointerEvent('pointerdown',{pointerId:1,clientX:rect.left+10,clientY:rect.top+10,bubbles:true}));
            canvas.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:rect.left+100,clientY:rect.top+70,bubbles:true}));
            canvas.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,clientX:rect.left+100,clientY:rect.top+70,bubbles:true}));
            assert(!signer.validity.customError, 'signature remains invalid after drawing');
            const signed=JSON.parse(block('Signature').querySelector('[data-native-value]').value);
            assert(signed.name==='Test Client' && signed.strokes[0].length===2, 'signature data missing');
            const form=document.querySelector('.client-form'); let captured;
            form.addEventListener('submit',event=>{event.preventDefault();captured=new FormData(form);});
            form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
            assert(captured.get('custom_0')==='3', 'earlier-page answer omitted from submit');
            assert(JSON.parse(captured.get('custom_3')).length===2, 'repeating rows omitted from submit');
            assert(captured.get('custom_7')==='Venue notes', 'conditional answer missing');
        ''')

    def test_builder_advanced_fields_rules_and_accessibility_audit(self):
        self.form.enabled=False
        fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const add = type => {document.getElementById('builder-add-type').value=type;document.getElementById('builder-add').click();};
            const read = () => JSON.parse(document.getElementById('builder-schema').value);
            add('repeat');
            let card=document.querySelectorAll('.builder-question')[5];
            const label=card.querySelector('input'); label.value='People'; input(label);
            assert(read()[5].children[0].label==='Full name', 'repeating defaults missing');
            [...card.querySelectorAll('button')].find(button=>button.textContent==='Add repeated field').click();
            assert(read()[5].children.length===2, 'repeated child field not added');
            add('calculation');
            assert(read()[6].calculation.operation==='count' && read()[6].calculation.sources[0]==='People', 'count calculation defaults incorrect');
            add('pagebreak'); assert(read()[7].type==='pagebreak', 'pagebreak not added');
            add('signature'); assert(read()[8].type==='signature', 'signature not added');
            card=document.querySelectorAll('.builder-question')[8];
            const condition=[...card.querySelectorAll('.builder-conditions')].find(panel=>panel.querySelector('summary').textContent.startsWith('Require'));
            [...condition.querySelectorAll('button')].find(button=>button.textContent==='Add condition').click();
            assert(read()[8].required_if.rules.length===1, 'conditional required rule not added');
            add('image');
            document.getElementById('builder-check-accessibility').click();
            assert(document.getElementById('builder-accessibility-results').textContent.includes('image description'), 'accessibility audit missing image warning');
            assert(document.querySelector('[name=confirmation_text]') && document.querySelector('[name=email_body]'), 'confirmation controls missing');
        ''')

    def test_browser_draft_recovery_and_manual_save(self):
        self.form.fields_json=fixtures.json.dumps(validate_fields([
            dict(label='Notes',type='text'),
            dict(label='People',type='repeat',children=[dict(label='Name',type='text')]),
            dict(label='Signature',type='signature'),
        ]))
        fixtures.main.db.session.commit()
        page=self.fixture.client.get('/forms/'+str(self.form.id))
        setup='''window.draftRequests=[];window.fetch=async (url,options={})=>{
            if(options.method==='POST') {window.draftRequests.push(JSON.parse(options.body));return {ok:true,json:async()=>({saved:true})};}
            if(options.method==='DELETE') return {ok:true,json:async()=>({saved:false})};
            return {ok:true,json:async()=>({csrf_token:'draft-token',fingerprint:'version',cross_device:true,answers:{custom_0:'Saved notes',custom_1:'[{"Name":"Alex"}]'}})};
        };'''
        self.browser(page.data, '''
            await new Promise(resolve=>setTimeout(resolve,20));
            const note=document.querySelector('[name=custom_0]');
            assert(note.value==='Saved notes','saved text not recovered');
            assert(document.querySelector('.native-repeat-row input').value==='Alex','repeating row not recovered');
            assert(!document.querySelector('[name=custom_2]').value,'signature was recovered unexpectedly');
            note.value='Updated notes';input(note);
            [...document.querySelectorAll('.native-draft-actions button')].find(button=>button.textContent==='Save progress').click();
            await new Promise(resolve=>setTimeout(resolve,20));
            assert(window.draftRequests.length===1,'manual draft save not sent');
            assert(window.draftRequests[0].answers.custom_0==='Updated notes','updated answer missing from draft');
            assert(!window.draftRequests[0].answers.custom_2,'signature included in draft');
            [...document.querySelectorAll('.native-draft-actions button')].find(button=>button.textContent==='Discard saved progress').click();
            await new Promise(resolve=>setTimeout(resolve,20));
            assert(note.value==='Updated notes','discarding saved draft cleared current answers');
        ''',setup=setup)

    def test_booking_draft_restores_event_day_editor(self):
        self.form.kind='booking';fixtures.main.db.session.commit()
        page=self.fixture.client.get('/booking?seasonal='+str(self.form.id))
        schedule=dict(same_details=False,events=[dict(date='2099-01-01',start_time='10:00',finish_time='12:00',event_address='Saved venue',event_type='Party',theme='Tiger',pitch_fee_required='no',publicity_type='Private',location_type='Indoors',charge_type='Client')])
        answers={'first_name':'Restored client','event_schedule':fixtures.json.dumps(schedule),'custom_2':'Saved custom details'}
        setup='window.fetch=async()=>({ok:true,json:async()=>({csrf_token:"draft-token",fingerprint:"version",cross_device:true,answers:'+fixtures.json.dumps(answers)+'})});'
        self.browser(page.data, '''
            await new Promise(resolve=>setTimeout(resolve,30));
            assert(document.querySelector('[name=first_name]').value==='Restored client','booking client name not restored');
            const card=document.querySelector('[data-event-day]');
            assert(card.querySelector('[data-event-field=date]').value==='2099-01-01','booking date not restored');
            assert(card.querySelector('[data-event-field=event_address]').value==='Saved venue','booking venue not restored');
            document.querySelector('.booking-form').dispatchEvent(new Event('native-draft-collect'));
            assert(JSON.parse(document.getElementById('eventScheduleInput').value).events[0].event_address==='Saved venue','event data not collected for saving');
        ''',setup=setup)

    def test_public_conditional_required_fields_and_card_choices(self):
        page=self.fixture.client.get('/forms/'+str(self.form.id))
        self.assertEqual(page.status_code,200)
        self.browser(page.data, '''
            const detailBlock = document.querySelector('[data-field-label="Details"]');
            const detailInput = detailBlock.querySelector('input');
            assert(detailBlock.hidden && detailInput.disabled && !detailInput.required, 'hidden question still required');
            const yes = document.querySelector('input[name=custom_1][value=Yes]');
            yes.checked = true; change(yes);
            assert(!detailBlock.hidden && !detailInput.disabled && detailInput.required, 'shown question not required');
            const no = document.querySelector('input[name=custom_1][value=No]');
            no.checked = true; change(no);
            assert(detailBlock.hidden && detailInput.disabled, 'question not hidden again');
            const extra = document.querySelector('input[name=custom_4]');
            assert(extra.validity.customError, 'required multiple choice not enforced');
            extra.checked = true; change(extra);
            assert(!extra.validity.customError, 'multiple choice remains invalid after selection');
            const card = document.querySelector('input[name=custom_3]');
            card.checked = true; change(card);
            assert(card.closest('.native-choice-card').matches(':has(input:checked)'), 'card selection style unavailable');
            card.closest('.native-block').querySelector('.native-clear-choice').click();
            assert(!card.checked, 'optional card selection not cleared');
            assert(!document.querySelector('input[name=custom_0]'), 'content became an editable question');
        ''')

    def test_full_preview_keeps_unsaved_edits_and_never_submits_answers(self):
        self.form.enabled=False
        fixtures.main.db.session.commit()
        page=self.fixture.admin.get('/admin/native-forms?edit='+str(self.form.id))
        self.browser(page.data, '''
            const title = document.getElementById('builder-title');
            title.value = 'Unsaved preview title'; input(title);
            const radioCard = document.querySelectorAll('.builder-question')[1];
            const columns = [...radioCard.querySelectorAll('label')].find(label => label.textContent.includes('Option columns')).querySelector('select');
            columns.value = '2'; change(columns);
            const spacing = [...radioCard.querySelectorAll('label')].find(label => label.textContent.includes('Option spacing')).querySelector('select');
            spacing.value = 'spacious'; change(spacing);
            const schema = document.getElementById('builder-schema').value;
            document.querySelector('.builder-open-preview').click();
            const dialog = document.getElementById('builder-preview-dialog');
            assert(dialog.open && dialog.contains(document.getElementById('builder-preview')), 'full preview not opened');
            assert(dialog.textContent.includes('Unsaved preview title'), 'unsaved title missing');
            const choices = dialog.querySelector('.native-choice-list');
            assert(getComputedStyle(choices).gap === '20px', 'spacious choice gap not applied');
            assert(getComputedStyle(choices).gridTemplateColumns.split(' ').length === 2, 'two option columns not applied');
            const yes = dialog.querySelector('input[type=radio][value=Yes]'); yes.checked = true; change(yes);
            const detail = dialog.querySelector('input[type=text]');
            assert(detail && !detail.disabled, 'preview text input disabled');
            detail.value = 'Example preview answer'; input(detail);
            document.getElementById('builder-dialog-mobile').click();
            assert(document.getElementById('builder-preview').classList.contains('builder-phone-preview'), 'phone preview mode failed');
            assert(document.getElementById('builder-schema').value === schema, 'preview answers modified form schema');
            document.getElementById('builder-preview-test').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}));
            assert(document.getElementById('builder-preview-result').textContent.includes('Nothing has been submitted'), 'preview tried to submit');
            document.getElementById('builder-preview-reset').click();
            assert(!dialog.querySelector('input[type=radio][value=Yes]').checked, 'preview answers not cleared');
            document.getElementById('builder-close-preview').click();
            await new Promise(resolve => setTimeout(resolve, 0));
            assert(!dialog.open && document.querySelector('.builder-preview').contains(document.getElementById('builder-preview')), 'preview not restored to editor');
            assert(title.value === 'Unsaved preview title', 'closing preview discarded edits');
        ''')


if __name__ == '__main__': unittest.main()
