import base64
from io import BytesIO
import json
import unittest
from PIL import Image
import test_moodboard_payments as fixtures
import test_native_form_browser as browser_helpers

main = fixtures.main


class MoodboardExportTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MoodboardPaymentTest()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.event = self.fixture.event

    def tearDown(self):
        self.fixture.tearDown()

    def test_export_uses_saved_active_selection_and_group_labels(self):
        other = main.MoodboardImage(title='Not selected', image_url='https://example.com/other.png')
        hidden = main.MoodboardImage(title='Inactive', image_url='https://example.com/hidden.png', active=False)
        main.db.session.add_all([other, hidden])
        main.db.session.flush()
        main.db.session.add(main.EventMoodboardImage(event_id=self.event.id, image_id=hidden.id))
        main.db.session.add(main.BusinessSetting(key='moodboard_price_small', value='4.25'))
        main.db.session.commit()
        response = self.client.get(f'/moodboard/event/{self.event.id}/download-data')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        data = response.json
        self.assertEqual(data['event'], 'Test fair')
        large, small = data['groups']
        self.assertEqual((large['title'], large['price']), ('Large Paints', '5.00'))
        self.assertEqual((small['title'], small['price']), ('Small Paints', '4.25'))
        self.assertEqual([item['label'] for item in large['images']], ['L - 1'])
        self.assertEqual([item['label'] for item in small['images']], ['S - 1'])
        self.assertNotIn('other.png', response.get_data(as_text=True))
        self.assertNotIn('hidden.png', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/moodboard/event/99999/download-data').status_code, 404)

    def test_archived_public_link_closed_and_admin_export_requires_login(self):
        path = f'/admin/events/{self.event.id}/moodboard/download-data'
        self.assertEqual(self.client.get(path).status_code, 302)
        self.event.status = 'Archived'
        main.db.session.commit()
        self.assertEqual(self.client.get(f'/moodboard/event/{self.event.id}/download-data').status_code, 410)
        self.fixture.admin()
        self.assertEqual(self.client.get(path).status_code, 200)

    def test_empty_groups_are_included(self):
        main.EventMoodboardImage.query.filter_by(event_id=self.event.id).delete()
        main.db.session.commit()
        response = self.client.get(f'/moodboard/event/{self.event.id}/download-data')
        self.assertEqual([group['images'] for group in response.json['groups']], [[], []])

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_downloads_complete_png(self):
        page = self.client.get(f'/moodboard/event/{self.event.id}')
        data = self.client.get(f'/moodboard/event/{self.event.id}/download-data').json
        buffer = BytesIO()
        Image.new('RGB', (100, 80), 'pink').save(buffer, format='PNG')
        image_url = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        for group, prefix, count in zip(data['groups'], ('L', 'S'), (7, 5)):
            group['images'] = [dict(url=image_url, label=f'{prefix} - {index}') for index in range(1, count + 1)]
        setup = '''
            window.exportData = %s;
            window.fetch = async () => new Response(JSON.stringify(window.exportData), {status:200,headers:{'content-type':'application/json'}});
            window.exportText = [];
            const originalFillText = CanvasRenderingContext2D.prototype.fillText;
            CanvasRenderingContext2D.prototype.fillText = function(value,...args) { window.exportText.push(value); return originalFillText.call(this,value,...args); };
            const originalCreateURL = URL.createObjectURL;
            URL.createObjectURL = function(blob) {window.exportBlob = blob; return originalCreateURL(blob);};
            HTMLAnchorElement.prototype.click = function() {window.exportFilename = this.download;};
        ''' % json.dumps(data)
        browser_helpers.NativeFormBrowserTest.browser(self, page.data, '''
            const button = document.querySelector('[data-moodboard-download]');
            button.click();
            assert(button.disabled, 'export should disable while processing');
            for (let attempt=0; attempt<100 && button.disabled; attempt++) await new Promise(resolve=>setTimeout(resolve,10));
            assert(!button.disabled, 'export did not finish');
            assert(window.exportBlob?.type === 'image/png', 'must create PNG');
            assert(window.exportFilename === 'moodboard-event-' + window.exportData.event_id + '.png', 'wrong download filename');
            const bytes = new Uint8Array(await window.exportBlob.slice(0,8).arrayBuffer());
            assert(bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71, 'invalid PNG signature');
            for (const text of ['Test fair Moodboard','Large Paints','Small Paints','L - 1','S - 1','\\u00a35.00','\\u00a33.50']) {
                assert(window.exportText.includes(text), 'missing export text: ' + text);
            }
            assert(window.exportText.includes('L - 7') && window.exportText.includes('S - 5'), 'must include designs beyond first row');
            const bitmap = await createImageBitmap(window.exportBlob);
            assert(bitmap.height > innerHeight, 'export must include off-screen content');
            bitmap.close();
        ''', setup=setup, width=390)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_reports_failed_images_without_partial_download(self):
        page = self.client.get(f'/moodboard/event/{self.event.id}')
        data = self.client.get(f'/moodboard/event/{self.event.id}/download-data').json
        for group in data['groups']:
            for item in group['images']:
                item['url'] = 'data:image/png;base64,broken'
        setup = '''
            window.fetch = async () => new Response(JSON.stringify(%s), {status:200,headers:{'content-type':'application/json'}});
            URL.createObjectURL = function() {window.partialDownload = true; return 'blob:test';};
        ''' % json.dumps(data)
        browser_helpers.NativeFormBrowserTest.browser(self, page.data, '''
            const button = document.querySelector('[data-moodboard-download]');
            button.click();
            for (let attempt=0; attempt<100 && button.disabled; attempt++) await new Promise(resolve=>setTimeout(resolve,10));
            assert(!button.disabled, 'download must be retryable after failure');
            assert(!window.partialDownload, 'must not download an incomplete moodboard');
            assert(document.querySelector('[data-moodboard-download-status]').textContent.includes('could not be loaded'), 'must explain failed image');
        ''', setup=setup)


if __name__ == '__main__':
    unittest.main()
