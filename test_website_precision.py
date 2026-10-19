import unittest
import html
import re
from pathlib import Path

import website_editor
import test_photo_library
import test_native_form_browser as browsers


class PrecisionValidationTest(unittest.TestCase):
    def test_device_dimensions_and_grid_survive_validation(self):
        position = dict(widthPx=321, heightPx=177, gridColumn=3, gridRow=2,
                        columnSpan=4, rowSpan=2, layer=5, gridColumns=24, gridRowHeight=16)
        saved = website_editor.validate({'e-abc': {'desktop': position}}, lambda photo: None)
        for key, value in position.items():
            self.assertEqual(saved['e-abc']['desktop'][key], value)
        self.assertNotIn('mobile', saved['e-abc'])
        for key, value in [('widthPx', -1), ('heightPx', float('nan')), ('gridColumns', 49)]:
            with self.assertRaises(ValueError):
                website_editor.validate({'e-abc': {'desktop': {key: value}}}, lambda photo: None)


class PrecisionBrowserTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_photo_library.PhotoLibraryTest()
        self.fixture.setUp()
        self.guest = self.fixture.guest

    def tearDown(self):
        self.fixture.tearDown()

    def test_precision_controls_edit_devices_and_undo(self):
        public=self.guest.get('/').text
        static=(Path(__file__).resolve().parent/'static').as_uri()+'/'
        public=public.replace('src="/static/','src="'+static).replace('href="/static/','href="'+static)
        public=re.sub(r'srcset="([^"]+)"',lambda match:'srcset="'+match.group(1).replace('/static/',static)+'"',public)
        for name in ('website-layout.js','website.js'):
            public=re.sub(r'<script src="[^"]*/'+re.escape(name)+r'" defer></script>',lambda match:'<script>'+(Path(__file__).resolve().parent/'static'/name).read_text(encoding='utf-8')+'</script>',public)
        public=public.replace('</head>','<style>'+(Path(__file__).resolve().parent/'static'/'website-editor.css').read_text(encoding='utf-8')+'</style></head>')
        public=re.sub(r'<link\b[^>]*>','',public)
        markup=self.fixture.admin.get('/admin/website-builder').text.replace('src="/"','srcdoc="'+html.escape(public,quote=True)+'"')
        browsers.NativeFormBrowserTest().browser(markup.encode(), '''
            await new Promise(resolve=>setTimeout(resolve,400));
            const frame=document.getElementById('builder-preview'),get=id=>document.getElementById('builder-'+id);
            assert(frame.style.width==='1280px','desktop canvas width');
            const sectionActions=frame.contentDocument.querySelector('.builder-section-actions');
            assert(sectionActions,'section controls appear over the canvas');
            sectionActions.querySelector('button').click();
            assert(get('tab-sections').getAttribute('aria-selected')==='true','edit section opens section settings');
            get('add').click();
            frame.contentDocument.querySelector('.wb-cell').scrollIntoView();
            window.websiteBuilderWorkspace.refreshSelection();
            assert(frame.contentDocument.querySelector('.builder-inline-toolbar'),'selected block has an inline toolbar');
            const width=document.querySelector('[data-builder-position="widthPx"]'),height=document.querySelector('[data-builder-position="heightPx"]');
            width.value=321;input(width);height.value=180;input(height);
            const cell=()=>frame.contentDocument.querySelector('.wb-cell');
            assert(cell().style.width==='321px'&&cell().style.height==='180px','numeric controls apply exact size');
            get('size').value='mobile';change(get('size'));
            width.value=155;input(width);
            assert(cell().style.width==='155px','mobile size edits');
            get('size').value='desktop';change(get('size'));
            assert(cell().style.width==='321px','desktop size preserved');
            get('reset-position').click();assert(cell().style.width!=='321px','device reset');
            get('undo').click();assert(cell().style.width==='321px','undo restores exact dimensions');
        ''')

    def test_precision_dimensions_grid_and_reset(self):
        browsers.NativeFormBrowserTest().browser(self.guest.get('/').data, '''
            const editor=window.websiteEditor;
            const index=editor.nodes.findIndex(node=>node.tagName==='IMG'),key=editor.keys[index];
            const layout={ [key]:{desktop:{widthPx:321,heightPx:177,layer:5},mobile:{widthPx:123,heightPx:99}},
                _blocks:[{desktop:{gridColumns:12,gridRowHeight:20},mobile:{gridColumns:4,gridRowHeight:10},
                    cells:[{kind:'text',text:'Grid block',desktop:{gridColumn:3,gridRow:2,columnSpan:4,rowSpan:2}}]}] };
            editor.apply(layout,'desktop');
            const image=editor.nodes[index],cell=document.querySelector('.wb-cell'),row=document.querySelector('.wb-row');
            assert(image.style.width==='321px'&&image.style.height==='177px','exact image dimensions');
            assert(image.style.zIndex==='5','layer setting');
            assert(getComputedStyle(row).gridTemplateColumns.split(' ').length===12,'desktop grid columns');
            assert(cell.style.gridColumn==='3 / span 4','block column and span');
            const before=image.getBoundingClientRect();editor.apply(layout,'desktop');
            assert(image.getBoundingClientRect().left===before.left,'reapplying must not move image');
            const gallery=document.querySelector('.photo-grid'),galleryImage=gallery.querySelector('img');
            const galleryIndex=editor.nodes.indexOf(galleryImage),sectionIndex=editor.sections.findIndex(section=>section.contains(gallery));
            layout[editor.keys[galleryIndex]]={desktop:{gridColumn:2,gridRow:1,columnSpan:2,widthPx:120,heightPx:90}};
            layout._spacing={[sectionIndex]:{columns:6,mobileColumns:2,gap:8,sidePadding:12,minHeight:200}};
            editor.apply(layout,'desktop');
            assert(getComputedStyle(gallery).gridTemplateColumns.split(' ').length===6,'native gallery columns');
            assert(gallery.children[0].style.gridColumn==='2 / span 2','gallery image wrapper placement');
            editor.apply(layout,'mobile');
            assert(image.style.width==='123px'&&image.style.height==='99px','independent mobile size');
            assert(getComputedStyle(row).gridTemplateColumns.split(' ').length===4,'mobile grid columns');
            assert(getComputedStyle(gallery).gridTemplateColumns.split(' ').length===2,'native gallery mobile columns');
            editor.apply({},'desktop');
            assert(image.style.zIndex==='','reset layer');
            assert(image.style.width!=='321px'&&image.style.height!=='177px','reset dimensions');
        ''')


if __name__ == '__main__':
    unittest.main()
