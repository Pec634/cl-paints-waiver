"""Exercise the till's actual basket, consent linking and small-screen layout."""
import unittest
import test_pos as fixtures
import test_native_form_browser as browser_helpers


@unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
class PosBrowserTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PosTest()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_basket_link_remove_and_mobile_width(self):
        page = self.fixture.admin.get('/admin/pos?q=Alex')
        browser_helpers.NativeFormBrowserTest.browser(self, page.data, '''
            const checkout = document.getElementById('pos-checkout');
            assert(checkout.querySelector('button').disabled, 'empty sale can be submitted');
            document.querySelector('[data-waiver-id]').click();
            assert(document.getElementById('pos-waiver-id').value, 'waiver was not linked');
            document.getElementById('pos-item-name').value = '<img src=x onerror=alert(1)>';
            document.getElementById('pos-item-quantity').value = '3';
            document.getElementById('pos-item-price').value = '0.10';
            document.getElementById('pos-add-item').requestSubmit();
            assert(document.getElementById('pos-total').textContent.includes('0.30'), 'decimal total is wrong');
            assert(!document.querySelector('#pos-basket img'), 'item name interpreted as HTML');
            const data = JSON.parse(document.getElementById('pos-items').value);
            assert(data[0].price === '0.10' && data[0].quantity === 3, 'checkout data is wrong');
            assert(!checkout.querySelector('button').disabled, 'cash checkout remains disabled');
            document.getElementById('pos-clear-waiver').click();
            assert(!document.getElementById('pos-waiver-id').value, 'waiver was not cleared');
            document.querySelector('#pos-basket button').click();
            assert(checkout.querySelector('button').disabled, 'removed basket can be submitted');
            assert(document.documentElement.scrollWidth <= innerWidth, 'till overflows phone width');
        ''', width=390)


if __name__ == '__main__':
    unittest.main()
