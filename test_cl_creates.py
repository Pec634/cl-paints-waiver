import unittest
from io import BytesIO
from unittest.mock import patch
import test_client_portal as fixtures
import test_native_form_browser as browser_helpers

main = fixtures.main


class CreatesSchemaTest(unittest.TestCase):
    def test_legacy_upgrade_preserves_orders_and_can_run_twice(self):
        from types import SimpleNamespace
        from sqlalchemy import create_engine, inspect, text
        from cl_creates import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE creates_order (id INTEGER PRIMARY KEY, total NUMERIC NOT NULL)'))
                connection.execute(text('INSERT INTO creates_order (id, total) VALUES (42, 16.00)'))
            database = SimpleNamespace(engine=engine)
            ensure_schema(database)
            ensure_schema(database)
            with engine.connect() as connection:
                row = connection.execute(text('SELECT id, total, acknowledgement FROM creates_order')).one()
                self.assertEqual(row.id, 42)
                self.assertEqual(float(row.total), 16)
                self.assertEqual(row.acknowledgement, 'Acknowledgement was not recorded for this legacy order.')
                column = next(c for c in inspect(connection).get_columns('creates_order') if c['name'] == 'acknowledgement')
                self.assertFalse(column['nullable'])
        finally:
            engine.dispose()


class CreatesTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True
        self.Order, self.Message, self.Product, self.Image = main.creates_models
        self.product = self.Product(name='Rainbow headband')
        main.db.session.add(self.product)
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def test_customer_search_groups_full_history_without_merging_names(self):
        saved=[]
        for email in ['alex@example.com','alex@example.com','another@example.com']:
            data=self.form();data['email']=email
            self.client.post('/cl-creates',data=data)
            saved.append(self.Order.query.order_by(self.Order.id.desc()).first())
        saved[1].email='Alex@Example.com'
        saved[1].first_name='Alexander'
        main.db.session.commit()
        for search in [saved[0].number,'alex@example.com','Alexander']:
            response=self.admin.get('/admin/cl-creates',query_string={'q':search})
            self.assertEqual(response.status_code,200)
            self.assertIn(saved[0].number.encode(),response.data)
            self.assertIn(saved[1].number.encode(),response.data)
            self.assertNotIn(saved[2].number.encode(),response.data)
            self.assertEqual(response.data.count(b'class="creates-customer-heading"'),1)
            self.assertIn(b'2 orders',response.data)
        response=self.admin.get('/admin/cl-creates',query_string={'q':'Smith'})
        self.assertEqual(response.data.count(b'class="creates-customer-heading"'),2)
        self.assertEqual(self.admin.get('/admin/cl-creates').status_code,200)

    def form(self):
        self.assertEqual(self.client.get('/cl-creates').status_code, 200)
        with self.client.session_transaction() as session:
            return dict(csrf_token=session['creates_csrf'], submission_token=session['creates_submission'],
                        first_name='Alex', last_name='Smith', email='alex@example.com', fulfilment='postage',
                        address_line1='1', address_street='Test Road', town='London', county='Greater London', country='United Kingdom', postcode='SW1A 1AA', mainland='on',
                        consent='on', custom_order_declaration='yes', product=str(self.product.id), wording='HELLO WORLD', word_shape='Heart', quantity='2')

    def test_colour_and_glitter_saved_for_each_headband(self):
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BLUE', 'MY PARTY'], word_shape=['Heart', ''], quantity=['2', '1'],
                    colour=['Blue', 'Pink'], letter_finish=['Plain', 'Glitter'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        order = self.Order.query.one()
        self.assertEqual([item['colour'] for item in order.items], ['Blue', 'Pink'])
        self.assertEqual([item['letter_finish'] for item in order.items], ['Plain', 'Glitter'])
        self.assertEqual(float(order.total), 21)
        self.assertIn(b'Glitter', response.data)
        self.assertIn(b'Pink', self.admin.get(f'/admin/cl-creates/orders/{order.id}').data)

    def test_invalid_colour_or_finish_is_rejected(self):
        for colour, finish in [('Unknown', 'Plain'), ('Black', 'Unknown')]:
            data = self.form()
            data.update(colour=colour, letter_finish=finish)
            self.client.post('/cl-creates', data=data)
            self.assertEqual(self.Order.query.count(), 0)

    def test_admin_manages_colours_and_glitter_letter_choices(self):
        token = self.admin_token()
        path = '/admin/cl-creates/colours'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.post(path, data={'kind':'headband','action':'add','name':'Orange'}).status_code, 400)
        for kind, colour in [('headband','Orange'), ('glitter','Rose gold')]:
            response = self.admin.post(path, data={'csrf_token':token,'kind':kind,'action':'add','name':colour})
            self.assertEqual(response.status_code, 302)
            self.assertIn(colour.encode(), self.client.get('/cl-creates').data)
        data = self.form()
        data.update(colour='Orange', letter_finish='Glitter', glitter_colour='Rose gold')
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['glitter_colour'], 'Rose gold')
        self.admin.post(path, data={'csrf_token':token,'kind':'glitter','action':'remove','name':'Rose gold'})
        data = self.form()
        data.update(colour='Orange', letter_finish='Glitter', glitter_colour='Rose gold')
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        self.assertEqual(order.items[0]['glitter_colour'], 'Rose gold')

    def test_admin_manages_word_shapes_and_orders_preserve_selection(self):
        token = self.admin_token()
        path = '/admin/cl-creates/shapes'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.admin.post(path, data={'csrf_token':token,'action':'add','name':'Butterfly'})
        self.assertIn(b'Butterfly', self.client.get('/cl-creates').data)
        data = self.form()
        data.update(word_shape='Butterfly')
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertIn(b'Separator: Butterfly', response.data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['word_shape'], 'Butterfly')
        self.admin.post(path, data={'csrf_token':token,'action':'remove','name':'Butterfly'})
        data = self.form()
        data.update(word_shape='Butterfly')
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        self.assertEqual(order.items[0]['word_shape'], 'Butterfly')

    def test_custom_order_refund_declaration_is_required_and_saved(self):
        data = self.form()
        data.pop('custom_order_declaration')
        page = self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 0)
        self.assertIn(b'Please read and acknowledge', page.data)
        data['custom_order_declaration'] = 'yes'
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertIn('change of mind', order.acknowledgement)
        self.assertIn('statutory rights', order.acknowledgement)

    def test_custom_shape_drawing_save_edit_validation_and_order_snapshot(self):
        import json
        path = '/admin/cl-creates/shapes'
        token = self.admin_token()
        points = [[-16, 0], [0, -10], [16, 0], [0, 10]]
        def save(name, drawing, original='', stroke='12.5'):
            return self.admin.post(path, data=dict(csrf_token=token, action='save',
                name=name, original=original, points=json.dumps(drawing), stroke_width=stroke))
        self.assertEqual(save('Oval', points).status_code, 302)
        page = self.client.get('/cl-creates').get_data(as_text=True)
        import re
        drawing_json = re.search(r'<script id="creates-shape-drawings" type="application/json">(.*?)</script>', page).group(1)
        self.assertEqual(json.loads(drawing_json)['Oval'], points)
        self.browser(page.encode(), '''
            const line=document.querySelector('.creates-line');
            line.querySelector('[name=word_shape]').value='Oval';
            let shapeText=false,paths=0,customStroke=false;
            const stroke=CanvasRenderingContext2D.prototype.stroke;
            CanvasRenderingContext2D.prototype.stroke=function(...args){if(this.lineWidth===12.5)customStroke=true;return stroke.apply(this,args);};
            const fillText=CanvasRenderingContext2D.prototype.fillText;
            const lineTo=CanvasRenderingContext2D.prototype.lineTo;
            CanvasRenderingContext2D.prototype.fillText=function(text,...args){if(text==='Oval')shapeText=true;return fillText.call(this,text,...args);};
            CanvasRenderingContext2D.prototype.lineTo=function(x,y){if(x===16&&y===0)paths++;return lineTo.call(this,x,y);};
            for(const wording of ['TEAM BRIDE','TEAM BRIDE SQUAD']){
                line.querySelector('[name=wording]').value=wording;
                window.renderHeadbandPreview(line);
            }
            assert(paths>0&&!shapeText,'Custom shape must draw its outline rather than its name');
            assert(customStroke,'Saved pixel stroke width missing from shop preview');
        ''')
        data = self.form()
        data['word_shape'] = 'Oval'
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['word_shape_points'], points)
        self.assertEqual(order.items[0]['word_shape_stroke_width'], 12.5)
        for invalid_stroke in ('-1','21','NaN','Infinity','abc'):
            self.assertIn(b'Enter a stroke width from 0 to 20 pixels', save('Invalid stroke', points, stroke=invalid_stroke).data)
        for invalid in ([], [[0,0]]*3, [[0,0],[99,1],[2,3]], [[0,0],[True,1],[2,3]], 'bad'):
            response = save('Invalid', invalid)
            self.assertIn(b'Draw a shape with at least three points', response.data)
        self.assertIn(b'already available', save('oval', points).data)
        changed = [[-12,0],[0,-12],[12,0],[0,12]]
        self.assertEqual(save('Custom oval', changed, 'Oval', stroke='0').status_code, 302)
        self.assertEqual(order.items[0]['word_shape_points'], points)
        self.assertEqual(order.items[0]['word_shape_stroke_width'], 12.5)
        self.assertEqual(order.items[0]['word_shape'], 'Oval')
        self.admin.post(path, data=dict(csrf_token=token, action='remove', name='Custom oval'))
        self.assertNotIn(b'Custom oval', self.client.get('/cl-creates').data)

    def test_shape_editor_browser(self):
        self.browser(self.admin.get('/admin/cl-creates/shapes').data, '''
            const form=document.getElementById('shape-editor');
            const points=()=>JSON.parse(form.elements.points.value);
            const initial=points();
            assert(initial.length===32,'Oval starting outline missing');
            const stroke=document.getElementById('shape-stroke');
            stroke.dispatchEvent(new InputEvent('beforeinput',{bubbles:true}));stroke.value=5.5;input(stroke);
            assert(document.querySelector('#shape-canvas polygon').style.strokeWidth==='5.5px','Pixel stroke not applied');
            document.getElementById('shape-undo').click();assert(stroke.value==='7','Stroke undo failed');
            stroke.value=0;input(stroke);assert(document.querySelector('#shape-canvas polygon').style.strokeWidth==='0px','Zero stroke failed');
            const measurements=document.getElementById('shape-measurements');
            assert(measurements.textContent==='32.0 mm wide × 22.0 mm high','Initial millimetre measurements missing');
            const width=document.getElementById('shape-width');width.value=38;input(width);
            assert(Math.abs(Math.max(...points().map(p=>p[0]))-Math.min(...points().map(p=>p[0]))-38)<.01,'Width not applied');
            assert(measurements.textContent.startsWith('38.0 mm wide'),'Millimetre width not updated');
            const dot=document.querySelector('#shape-canvas circle');dot.focus();
            dot.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
            assert(points()[0][0]>initial[0][0],'Keyboard editing failed');
            assert(measurements.textContent.startsWith('38.5 mm wide'),'Outline edit did not update measurement');
            document.getElementById('shape-delete-point').click();
            assert(points().length===31,'Dot removal failed');
            document.getElementById('shape-undo').click();assert(points().length===32,'Undo failed');
            document.querySelector('[data-edit-shape="Heart"]').click();
            assert(form.elements.original.value==='Heart'&&points().length===48,'Existing shape editing failed');
            document.getElementById('shape-new').click();
            assert(!form.elements.original.value&&!form.elements.name.value,'New shape did not reset');
        ''')

    def test_shape_editor_sliders_grid_and_compact_mobile_layout(self):
        page=self.admin.get('/admin/cl-creates/shapes').data
        for viewport in (1280,390):
            self.browser(page, '''
                const form=document.getElementById('shape-editor');
                const slider=document.getElementById('shape-width-range');
                slider.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));slider.value=36.5;input(slider);
                assert(document.getElementById('shape-width').value==='36.5','Width slider did not update number');
                assert(document.getElementById('shape-measurements').textContent.startsWith('36.5 mm wide'),'Width slider did not resize outline');
                document.getElementById('shape-undo').click();
                assert(slider.value==='32','Undo did not synchronise slider');
                const stroke=document.getElementById('shape-stroke-range');stroke.value=3.5;input(stroke);
                assert(document.getElementById('shape-stroke').value==='3.5','Stroke slider did not synchronise');
                assert(document.querySelector('#shape-canvas polygon').style.strokeWidth==='3.5px','Stroke slider did not update outline');
                const saved=form.elements.points.value,canvas=document.getElementById('shape-canvas');
                const spacing=document.getElementById('shape-grid-spacing');spacing.value=2;input(spacing);
                assert(canvas.querySelector('pattern').getAttribute('width')==='2','Grid spacing did not change');
                assert(document.getElementById('shape-grid-scale').textContent.includes('2 mm'),'Grid scale label missing');
                const before=canvas.viewBox.baseVal.width;
                const padding=document.getElementById('shape-canvas-padding');padding.value=24;input(padding);
                assert(canvas.viewBox.baseVal.width>before,'Padding did not increase viewing margin');
                assert(form.elements.points.value===saved,'Canvas settings altered saved shape');
                assert(document.getElementById('shape-width').getBoundingClientRect().width<=80,'Number fields are too wide');
                assert(canvas.getBoundingClientRect().right<=innerWidth,'Canvas overflows viewport');
                assert(document.querySelector('.shape-dimensions').getBoundingClientRect().right<=innerWidth,'Controls overflow viewport');
            ''', width=viewport)

    def test_order_preview_images_use_recorded_designs_and_require_admin(self):
        import json
        order = self.review_order()
        order.items_json = json.dumps([
            dict(product='Custom wording headband', wording='TEAM BRIDE', quantity=2, price='5.00',
                 colour='Pink', background_colour='Black', bold_colour='Gold', letter_finish='Plain',
                 word_shape='Custom oval', word_shape_points=[[-16,0],[0,-10],[16,0],[0,10]]),
            dict(product='Custom wording headband', wording='TEAM PARTY', quantity=1, price='5.00',
                 colour='White', letter_finish='Glitter', glitter_colour='Silver', word_shape='Butterfly')])
        main.db.session.commit()
        path = f'/admin/cl-creates/orders/{order.id}/preview'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.get('/admin/cl-creates/orders/999999/preview').status_code, 404)
        detail = self.admin.get(f'/admin/cl-creates/orders/{order.id}?popup=1')
        self.assertIn(path.encode(), detail.data)
        self.assertIn(b'View design preview', detail.data)
        page = self.admin.get(path)
        self.assertEqual(page.status_code, 200)
        self.browser(page.data, '''
            const images=[...document.querySelectorAll('#order-design-previews img')];
            assert(images.length===2,'Every ordered design needs an image');
            assert(images.every(image=>image.src.startsWith('data:image/png;base64,')),'Preview must be a PNG image');
            assert(images[0].alt.includes('TEAM BRIDE')&&images[0].alt.includes('Pink'),'Recorded wording and colours missing');
            assert(images[1].alt.includes('Silver glitter'),'Recorded glitter missing');
            const links=[...document.querySelectorAll('#order-design-previews a[download]')];
            assert(links.length===2&&links[0].href===images[0].src,'Image downloads missing');
            assert(document.getElementById('order-design-previews').textContent.includes('no saved drawing'),'Legacy shape limitation missing');
            const items=JSON.parse(document.getElementById('order-preview-items').textContent);
            assert(items[0].word_shape_points[0][0]===-16,'Saved custom outline missing');
        ''')

    def test_individual_word_and_shape_colours_saved_for_each_line(self):
        data = self.form()
        data.update(product=['custom','custom'], wording=['A B C','TEAM BRIDE'], quantity=['1','1'],
                    word_shape=['Heart','Star'], colour=['White','White'], letter_finish=['Plain','Glitter'],
                    glitter_colour=['','Gold'], word_colour_1=['Red','Silver'], word_colour_2=['Blue','Pink'],
                    word_colour_3=['Green',''], shape_colour_1=['Gold','Blue'], shape_colour_2=['Pink',''])
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        self.assertEqual(order.items[0]['word_colours'], ['Red','Blue','Green'])
        self.assertEqual(order.items[0]['shape_colours'], ['Gold','Pink'])
        self.assertEqual(order.items[1]['word_colours'], ['Silver','Pink'])
        self.assertEqual(order.items[1]['shape_colours'], ['Blue'])
        detail = self.admin.get(f'/admin/cl-creates/orders/{order.id}').data
        self.assertIn(b'Word 2 colour: Blue', detail)
        self.assertIn(b'Shape 2 colour: Pink', detail)
        self.browser(self.admin.get(f'/admin/cl-creates/orders/{order.id}/preview').data, '''
            const images=document.querySelectorAll('#order-design-previews img');
            assert(images[0].alt.includes('Word 1: Red')&&images[0].alt.includes('Shape 2: Pink'),'Saved individual colours missing');
            assert(images[1].alt.includes('Word 1: Silver glitter'),'Saved glitter colours missing');
        ''')
        invalid=self.form();invalid['word_colour_1']='Not a colour'
        self.assertIn(b'Choose an available colour for each word and shape', self.client.post('/cl-creates',data=invalid).data)
        self.assertEqual(self.Order.query.count(),1)
        invalid['word_colour_1']=['Red','Blue']
        self.assertIn(b'Choose colours for each headband separately',self.client.post('/cl-creates',data=invalid).data)

    def test_individual_colour_shop_controls_and_rendering(self):
        self.browser(self.client.get('/cl-creates').data, '''
            const line=document.querySelector('.creates-line');
            const field=name=>line.querySelector(`[name=${name}]`);
            field('wording').value='A B C';field('word_shape').value='Heart';input(field('wording'));
            const chosen={word_colour_1:'Red',word_colour_2:'Blue',word_colour_3:'Green',shape_colour_1:'Gold',shape_colour_2:'Pink'};
            Object.entries(chosen).forEach(([name,value])=>field(name).value=value);
            const faces={},shapeFaces=[];
            const fillText=CanvasRenderingContext2D.prototype.fillText,fill=CanvasRenderingContext2D.prototype.fill;
            CanvasRenderingContext2D.prototype.fillText=function(text,...args){if(['A','B','C'].includes(text)&&this.fillStyle!=='#ffffff')faces[text]=this.fillStyle;return fillText.call(this,text,...args);};
            CanvasRenderingContext2D.prototype.fill=function(...args){if(['#cda34e','#ec71a7'].includes(this.fillStyle))shapeFaces.push(this.fillStyle);return fill.apply(this,args);};
            input(field('word_colour_1'));
            assert(faces.A==='#c92739'&&faces.B==='#2760b0'&&faces.C==='#27845d','Words did not render in separate colours');
            assert(shapeFaces.includes('#cda34e')&&shapeFaces.includes('#ec71a7'),'Shapes did not render in separate colours');
            const details=line.querySelector('.preview-summary-segments');
            assert(details.children.length===3,'Design description must have three separate segments');
            const detailRows=[...details.querySelectorAll('.preview-design-details>div')];
            assert(detailRows.length===9,'Design details should have separate rows for base, finish, words and shapes');
            const rows=detailRows.map(row=>[row.querySelector('dt').textContent,row.querySelector('dd').textContent]);
            assert(rows.some(([label,value])=>label==='Word 1: A'&&value==='Red'),'Word colour summary unclear');
            assert(rows.some(([label,value])=>label.startsWith('Shape 2: Heart')&&value==='Pink'),'Shape colour summary unclear');
            const headings=[...details.querySelectorAll('h4')].map(heading=>heading.textContent);
            assert(headings.join('|')==='Headband & finish|Word colours|Shapes between words','Segment headings missing');
            assert(details.querySelectorAll('.preview-colour-swatch').length===7,'Colour swatches missing');
            assert(!field('shape_colour_2').closest('label').hidden,'Second separator colour missing');
            field('wording').value='TEAM BRIDE';input(field('wording'));
            assert(getComputedStyle(field('word_colour_3').closest('label')).display==='none','Unused word colour visible');
            assert(getComputedStyle(field('shape_colour_2').closest('label')).display==='none','Unused shape colour visible');
            document.getElementById('add-line').click();
            assert(document.querySelectorAll('.creates-line').length===2,'Multiple designs failed');
            field('letter_finish').value='Glitter';change(field('letter_finish'));
            assert([...field('word_colour_1').options].some(option=>option.value==='Silver'),'Glitter colour palette missing');
        ''')

    def test_short_single_word_shows_inline_error_until_corrected(self):
        self.browser(self.client.get('/cl-creates').data, '''
            const first=document.querySelector('.creates-line'),wording=first.querySelector('[name=wording]');
            const warning=()=>first.querySelector('[data-wording-warning]');
            assert(warning().hidden,'Empty wording should not show minimum-length error');
            wording.value='STE';input(wording);
            assert(!warning().hidden&&warning().textContent.includes('Add 4 more characters'),'Short word needs an immediate visible error');
            assert(wording.getAttribute('aria-invalid')==='true'&&!wording.checkValidity(),'Short word must block submission');
            assert(wording.getAttribute('aria-describedby')===warning().id,'Error must be linked to the wording field');
            wording.value='ABCDEF';input(wording);assert(warning().textContent.includes('Add 1 more character.'),'Remaining character count incorrect');
            document.getElementById('add-line').click();
            const second=document.querySelectorAll('.creates-line')[1],secondInput=second.querySelector('[name=wording]');
            assert(second.querySelector('[data-wording-warning]').hidden,'New headband inherited an error');
            secondInput.value='SHORT';input(secondInput);
            assert(second.querySelector('[data-wording-warning]').id!==warning().id,'Errors need unique identifiers');
            wording.value='STEELERS';input(wording);
            assert(warning().hidden&&wording.checkValidity()&&wording.getAttribute('aria-invalid')==='false','Valid single word must clear error');
            wording.value='GO TEAM';input(wording);assert(warning().hidden&&wording.checkValidity(),'Two words must not require 7 characters per word');
            wording.value='';input(wording);assert(warning().hidden,'Clearing wording must clear the short-word error');
        ''')
        data=self.form();data['wording']='STE'
        response=self.client.post('/cl-creates',data=data)
        self.assertIn(b'Single-word headbands require at least 7 characters.',response.data)
        self.assertEqual(self.Order.query.count(),0)

    def admin_token(self):
        self.assertEqual(self.admin.get('/admin/cl-creates').status_code, 200)
        with self.admin.session_transaction() as session:
            return session['creates_csrf']

    def review_order(self):
        order = self.Order(first_name='Delete', last_name='Test', email='delete@example.com',
            address='Test address', fulfilment='collection', items_json='[]', total=10, paid=0,
            status='Under review')
        main.db.session.add(order)
        main.db.session.commit()
        return order

    def test_delete_review_order_removes_communications_and_preserves_other_orders(self):
        order = self.review_order()
        other = self.review_order()
        order_id, other_id = order.id, other.id
        main.db.session.add(self.Message(order_id=order_id, subject='Test', body='Message', result='sent'))
        main.db.session.commit()
        token = self.admin_token()
        path = f'/admin/cl-creates/orders/{order_id}'
        self.assertIn(b'Delete order', self.admin.get(path+'?popup=1').data)
        response = self.admin.post(path, data=dict(csrf_token=token, action='delete', confirm_delete='yes'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('deleted=1', response.location)
        self.assertIsNone(main.db.session.get(self.Order, order_id))
        self.assertEqual(self.Message.query.filter_by(order_id=order_id).count(), 0)
        self.assertIsNotNone(main.db.session.get(self.Order, other_id))
        self.assertEqual(self.admin.get(path).status_code, 404)

    def test_delete_unpaid_order_awaiting_payment_without_checkout(self):
        order=self.review_order();order.status='Awaiting payment'
        main.db.session.commit();identity=order.id
        token=self.admin_token();path=f'/admin/cl-creates/orders/{identity}'
        self.assertIn(b'name="action" value="delete"',self.admin.get(path).data)
        response=self.admin.post(path,data=dict(csrf_token=token,action='delete',confirm_delete='yes'))
        self.assertEqual(response.status_code,302)
        self.assertIsNone(main.db.session.get(self.Order,identity))

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_delete_order_layout_in_popup_and_standalone(self):
        order = self.review_order()
        for width, popup in ((1280, ''), (390, '?popup=1')):
            page = self.admin.get(f'/admin/cl-creates/orders/{order.id}'+popup)
            self.browser(page.data, '''
                const section = document.querySelector('.creates-order-delete');
                assert(!section.open, 'Delete section should start collapsed');
                section.querySelector('summary').click();
                const checkbox = section.querySelector('[name=confirm_delete]');
                assert(checkbox.offsetWidth === 20 && checkbox.offsetHeight === 20, 'Checkbox should have normal dimensions');
                const button = section.querySelector('button');
                assert(button.offsetWidth < section.clientWidth, 'Delete button should be compact');
                const bounds = button.getBoundingClientRect();
                assert(bounds.left >= 0 && bounds.right <= innerWidth, 'Delete button should fit the viewport');
                assert(!section.querySelector('form').checkValidity(), 'Confirmation must still be required');
                checkbox.click();
                assert(section.querySelector('form').checkValidity(), 'Checked confirmation should validate');
                assert(section.querySelector('form').target === '_top', 'Popup deletion should return to full order list');
            ''', width=width)

    def test_delete_requires_admin_csrf_confirmation_and_unpaid_review_status(self):
        order = self.review_order()
        token = self.admin_token()
        path = f'/admin/cl-creates/orders/{order.id}'
        data = dict(csrf_token=token, action='delete', confirm_delete='yes')
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.assertEqual(self.admin.post(path, data=dict(data, csrf_token='bad')).status_code, 400)
        response = self.admin.post(path, data=dict(data, confirm_delete=''))
        self.assertIn(b'Confirm that you want', response.data)
        for field, value in [('paid', 1), ('status', 'Paid'), ('status', 'In production'),
                             ('invoice_url', 'https://pay.sumup.com/test'), ('invoice_reference', '2026-001')]:
            original = getattr(order, field)
            setattr(order, field, value)
            main.db.session.commit()
            response = self.admin.post(path, data=data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(main.db.session.get(self.Order, order.id))
            self.assertNotIn(b'name="action" value="delete"', response.data)
            setattr(order, field, original)
            main.db.session.commit()

    def test_portal_shop_prefills_signup_details_and_keeps_edits(self):
        account = self.fixture.signup()
        Address = main.app.extensions['client_billing_address_model']
        main.db.session.add(Address(client_id=account.id, details={
            'address_property': '42', 'address_street': 'Rainbow Road',
            'address_city': 'Doncaster', 'address_postcode': 'DN1 1AA',
            'address_country': 'United Kingdom'}))
        main.db.session.commit()
        page = self.client.get('/cl-creates')
        for value in [b'Client navigation', b'>CL Creates</a>', b'value="Test"',
                      b'value="client@example.com"', b'value="42"', b'value="Rainbow Road"',
                      b'value="Doncaster"', b'value="DN1 1AA"', b'autocomplete="postal-code"']:
            self.assertIn(value, page.data)
        data = self.form()
        data.update(address_line1='99 Changed Road', wording='')
        invalid = self.client.post('/cl-creates', data=data)
        self.assertIn(b'value="99 Changed Road"', invalid.data)
        self.assertNotIn(b'value="42"', invalid.data)
        anonymous = main.app.test_client().get('/cl-creates')
        self.assertNotIn(b'value="Rainbow Road"', anonymous.data)
        self.assertNotIn(b'aria-label="Client navigation"', anonymous.data)

    def test_shop_back_link_preserves_source_and_rejects_external_urls(self):
        page = self.client.get('/cl-creates', query_string={'return_to': '/services'})
        self.assertIn(b'href="/services">&larr; Back</a>', page.data)
        data = self.form()
        data['return_to'] = '/services'
        data['wording'] = ''
        invalid = self.client.post('/cl-creates', data=data)
        self.assertIn(b'href="/services">&larr; Back</a>', invalid.data)
        data['wording'] = 'HELLO'
        confirmation = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertIn(b'href="/services">&larr; Back</a>', confirmation.data)
        for destination in ['https://example.com', '//example.com', '/\\example.com']:
            fallback = self.client.get('/cl-creates', query_string={'return_to': destination})
            self.assertIn(b'href="/">&larr; Back</a>', fallback.data)
        self.fixture.signup()
        portal = self.client.get('/cl-creates', query_string={'return_to': '/client/bookings'})
        self.assertIn(b'href="/client/bookings">&larr; Back</a>', portal.data)

    def test_order_totals_duplicate_and_private_details(self):
        data = self.form()
        data.update(product=[str(self.product.id)] * 2, wording=['HELLO WORLD', 'A B C'], word_shape=['Heart','Star'], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertNotIn(b'O-000001', response.data)
        order = self.Order.query.one()
        self.assertEqual(float(order.total), 31)
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.count(), 1)
        path = f'/admin/cl-creates/orders/{order.id}'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.get(path).status_code, 200)
        self.assertIn(b'aria-label="Admin navigation"', self.admin.get(path).data)
        popup = self.admin.get(path + '?popup=1')
        self.assertEqual(popup.status_code, 200)
        self.assertNotIn(b'aria-label="Admin navigation"', popup.data)
        self.assertNotIn(b'aria-label="CL Creates navigation"', popup.data)
        saved = self.admin.post(path + '?popup=1', data=dict(csrf_token=self.admin_token(), status='Under review', paid='0'))
        self.assertEqual(saved.status_code, 302)
        self.assertIn('popup=1', saved.location)
        self.assertEqual(self.Message.query.count(), 0)
        for search in ['O-000001', 'Alex Smith', 'alex@example.com', 'Test Road']:
            self.assertIn(b'O-000001', self.admin.get('/admin/cl-creates', query_string={'q': search}).data)

    def test_custom_order_form_works_without_catalogue_products(self):
        main.db.session.delete(self.product)
        main.db.session.commit()
        page = self.client.get('/cl-creates')
        self.assertIn(b'id="creates-form"', page.data)
        self.assertIn(b'Create your headband in 3 steps', page.data)
        self.assertIn(b'More items coming soon', page.data)
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BRIDE', 'BRIDE SQUAD'], word_shape=['Heart',''], quantity=['2', '3'])
        response = self.client.post('/cl-creates', data=data, follow_redirects=True)
        self.assertNotIn(b'O-000001', response.data)
        order = self.Order.query.one()
        self.assertEqual(float(order.total), 31)
        self.assertEqual([item['wording'] for item in order.items], ['TEAM BRIDE', 'BRIDE SQUAD'])
        self.assertEqual(order.status, 'Awaiting payment')

    def test_shipping_label_is_private_and_only_available_for_postage(self):
        self.client.post('/cl-creates', data=self.form())
        order = self.Order.query.one()
        path = f'/admin/cl-creates/orders/{order.id}'
        label_path = path + '/shipping-label'
        self.assertEqual(self.client.get(label_path).status_code, 302)
        label = self.admin.get(label_path)
        self.assertEqual(label.status_code, 200)
        self.assertEqual(label.headers['Cache-Control'], 'no-store')
        self.assertIn(b'Alex Smith', label.data)
        self.assertIn(b'1 Test Road', label.data)
        self.assertIn(b'SW1A 1AA', label.data)
        self.assertNotIn(b'alex@example.com', label.data)
        self.assertNotIn(b'HELLO WORLD', label.data)
        self.assertIn(b'Print shipping address', self.admin.get(path + '?popup=1').data)
        order.fulfilment = 'collection'
        main.db.session.commit()
        self.assertEqual(self.admin.get(label_path).status_code, 404)
        self.assertNotIn(b'Print shipping address', self.admin.get(path + '?popup=1').data)

    def test_seven_character_single_word_is_accepted(self):
        data = self.form()
        data['wording'] = 'PAINTER'
        self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Order.query.one().items[0]['wording'], 'PAINTER')

    def test_postage_is_per_five_headbands_across_all_designs(self):
        for quantity, expected in [(1, 11), (5, 31), (6, 42), (7, 47), (10, 62), (11, 73)]:
            with self.subTest(quantity=quantity):
                data = self.form()
                data['quantity'] = str(quantity)
                response = self.client.post('/cl-creates', data=data)
                self.assertEqual(response.status_code, 302)
                order = self.Order.query.order_by(self.Order.id.desc()).first()
                self.assertEqual(float(order.total), expected)
        data = self.form()
        data.update(product=['custom', 'custom'], wording=['TEAM BLUE', 'TEAM PINK'],
                    word_shape=['', ''], quantity=['3', '4'])
        self.client.post('/cl-creates', data=data)
        self.assertEqual(float(self.Order.query.order_by(self.Order.id.desc()).first().total), 47)

    def test_postage_preview_counts_boxes_across_designs(self):
        self.browser(self.client.get('/cl-creates').data, '''
            const quantity = document.querySelector('[name=quantity]');
            const summary = document.getElementById('creates-total');
            quantity.value = '5'; input(quantity);
            assert(summary.textContent.includes('£31.00') && summary.textContent.includes('for 1 box,'), 'Five headbands use one box');
            quantity.value = '7'; input(quantity);
            assert(summary.textContent.includes('£47.00') && summary.textContent.includes('for 2 boxes,'), 'Seven headbands use two boxes');
            document.getElementById('add-line').click();
            const second = document.querySelectorAll('[name=quantity]')[1];
            second.value = '4'; input(second);
            assert(summary.textContent.includes('£73.00') && summary.textContent.includes('for 3 boxes,'), 'All designs share the box count');
            document.querySelectorAll('.remove-line')[1].click();
            assert(summary.textContent.includes('£47.00'), 'Removing a design recalculates postage');
        ''')

    def test_validation_and_paid_status(self):
        data = self.form()
        for changes in [dict(wording='ABCDEF'), dict(wording='A B C D'), dict(quantity='0'), dict(postcode='BT1 1AA')]:
            self.client.post('/cl-creates', data=dict(data, **changes))
            self.assertEqual(self.Order.query.count(), 0)
        self.assertEqual(self.client.post('/cl-creates', data={}).status_code, 400)
        self.client.post('/cl-creates', data=data)
        order = self.Order.query.one()
        path = f'/admin/cl-creates/orders/{order.id}'
        token = self.admin_token()
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='0'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://evil.example/invoice'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.admin.post(path, data=dict(csrf_token=token, status='Paid', paid='16.00', invoice_url='https://invoices.sumup.com/test'))
        self.assertEqual(order.status, 'Awaiting payment')
        self.assertEqual(float(order.paid), 0)
        order.paid=16;order.status='Paid';main.db.session.commit()
        self.admin.post(path, data=dict(csrf_token=token, status='Ready for collection', paid='16'))
        self.assertEqual(order.status, 'Paid')
        self.admin.post(path, data=dict(csrf_token=token, status='Shipped', paid='16'))
        self.assertEqual(order.status, 'Shipped')

    def test_settings_snapshot_and_email_failure(self):
        data = self.form()
        with patch.object(main, 'send_client_email', return_value=False):
            self.client.post('/cl-creates', data=data)
        self.assertEqual(self.Message.query.count(), 0)
        token = self.admin_token()
        self.admin.post('/admin/cl-creates/settings', data=dict(csrf_token=token, price='8', postage='7',
                        subject='{order_number}: {status}', body='Hello {first_name}'))
        self.assertEqual(float(self.Order.query.one().total), 16)
        data = self.form()
        data['quantity'] = '2'
        self.client.post('/cl-creates', data=data)
        self.assertEqual(float(self.Order.query.order_by(self.Order.id.desc()).first().total), 23)
        self.assertEqual(self.Message.query.count(), 0)
        for path in ['/admin/cl-creates', '/admin/cl-creates/settings', '/admin/cl-creates/communications']:
            self.assertEqual(main.app.test_client().get(path).status_code, 302)

    def image_file(self, name='headband.png'):
        from PIL import Image
        output = BytesIO()
        Image.new('RGB', (30, 30), 'pink').save(output, 'PNG')
        output.seek(0)
        return output, name

    def test_image_library_upload_visibility_and_delete(self):
        token = self.admin_token()
        path = '/admin/cl-creates/images'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.admin.post(path, data={'action': 'delete'}).status_code, 400)
        response = self.admin.post(path, data=dict(csrf_token=token, action='upload',
                                   images=[self.image_file(), self.image_file('example.png')]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.Image.query.count(), 2)
        image = self.Image.query.order_by(self.Image.id).first()
        image_path = f'/cl-creates/library/{image.id}'
        self.assertEqual(self.client.get(image_path).mimetype, 'image/jpeg')
        self.assertIn(b'headband', self.client.get('/cl-creates').data)
        self.admin.post(path, data=dict(csrf_token=token, action='update', image_id=image.id, name='Private example'))
        self.assertEqual(self.client.get(image_path).status_code, 404)
        self.assertEqual(self.admin.get(image_path).status_code, 200)
        self.assertNotIn(b'Private example', self.client.get('/cl-creates').data)
        self.admin.post('/admin/cl-creates/settings', data=dict(csrf_token=token, action='product_image',
                        product_id=self.product.id, library_image=image.id))
        self.assertIsNotNone(self.product.image)
        image_id = image.id
        self.admin.post(path, data=dict(csrf_token=token, action='delete', image_id=image_id))
        self.assertIsNone(main.db.session.get(self.Image, image_id))
        self.assertIsNone(self.product.image)
        self.assertIsNotNone(main.db.session.get(self.Product, self.product.id))
        self.assertEqual(self.client.get(image_path).status_code, 404)

    def test_invalid_image_batch_is_not_partially_saved(self):
        token = self.admin_token()
        response = self.admin.post('/admin/cl-creates/images', data=dict(csrf_token=token, action='upload',
                                   images=[self.image_file(), (BytesIO(b'not an image'), 'fake.png')]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Upload a valid', response.data)
        self.assertEqual(self.Image.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
