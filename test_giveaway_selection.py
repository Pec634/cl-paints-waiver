import json
import re
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_native_forms as fixtures
import test_native_form_browser as browsers

main = fixtures.main


class GiveawaySelectionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeFormsTest(); self.fixture.setUp()
        self.form = self.fixture.create('giveaway')
        self.admin = self.fixture.admin
        self.path = f'/admin/native-forms/{self.form.id}/import-entrants'
        self.accounts = [main.ClientAccount(first_name=f'Pick{index:02}', last_name='Client',
            email=f'pick{index:02}@example.com') for index in range(12)]
        main.db.session.add_all(self.accounts); main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def test_multiple_selected_clients_preview_then_confirm(self):
        data = MultiDict([('csrf_token', 'admin-token'), ('action', 'preview'), ('send_email', 'yes'),
                         ('client_ids', str(self.accounts[0].id)), ('client_ids', str(self.accounts[1].id))])
        with patch.object(main, 'send_client_email', return_value=True) as send:
            page = self.admin.post(self.path, data=data)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'2 unique email addresses', page.data)
            self.assertEqual(fixtures.Submission.query.count(), 0)
            send.assert_not_called()
            token = re.search(rb'name="batch_token" value="([^"]+)"', page.data)[1].decode()
            response = self.admin.post(self.path, data=dict(csrf_token='admin-token', action='confirm', batch_token=token))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(fixtures.Submission.query.count(), 2)
            self.assertEqual(send.call_count, 2)

    def test_invalid_selection_and_existing_entrants(self):
        page = self.admin.post(self.path, data=MultiDict([
            ('csrf_token', 'admin-token'), ('action', 'preview'), ('client_ids', str(self.accounts[0].id)), ('client_ids', 'invalid')]))
        self.assertIn(b'Choose valid clients', page.data)
        self.assertIn(f'value="{self.accounts[0].id}" checked'.encode(), page.data)
        self.assertEqual(fixtures.Submission.query.count(), 0)
        page = self.admin.post(self.path, data=dict(csrf_token='admin-token', action='preview', client_ids='999999'))
        self.assertIn(b'selected client no longer exists', page.data)
        self.fixture.client.post('/forms/' + str(self.form.id), data=self.fixture.data(self.form))
        page = self.admin.get(self.path)
        self.assertIn(b'Already entered', page.data)
        self.assertRegex(page.data, rb'name="client_ids" value="\d+" disabled')

    @unittest.skipUnless(browsers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_scroll_search_and_multi_selection_on_mobile(self):
        page = self.admin.get(self.path)
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const selector = document.querySelector('[data-giveaway-clients]');
            const list = selector.querySelector('.giveaway-client-list');
            const search = selector.querySelector('[data-client-search]');
            const count = selector.querySelector('[data-client-count]');
            assert(list.scrollHeight > list.clientHeight, 'Client list should scroll');
            assert(selector.getBoundingClientRect().right <= innerWidth + 1, 'Selector should fit mobile width');
            search.value = 'Pick00'; input(search);
            selector.querySelector('[data-select-visible]').click();
            assert(count.textContent === '1 client selected', 'First selection missing');
            search.value = 'Pick01'; input(search);
            selector.querySelector('[data-select-visible]').click();
            assert(count.textContent === '2 clients selected', 'Filtering should preserve selected clients');
            search.value = 'not-a-client'; input(search);
            assert(!selector.querySelector('[data-client-empty]').hidden, 'No search results should be explained');
            selector.querySelector('[data-clear-clients]').click();
            assert(count.textContent === '0 clients selected', 'Clear selection should include hidden selections');
        ''', width=390)
