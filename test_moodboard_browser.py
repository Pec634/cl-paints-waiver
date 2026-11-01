"""Exercise the real basket controls and mobile layout in headless Edge."""
import unittest
import test_moodboard_payments as fixtures
import test_native_form_browser as browser_helpers


@unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
class MoodboardBrowserTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MoodboardPaymentTest()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_image_click_quantity_preview_and_sticky_basket(self):
        page = self.fixture.client.get(f'/moodboard/event/{self.fixture.event.id}')
        browser_helpers.NativeFormBrowserTest.browser(self, page.data, '''
            const basket = document.getElementById('moodboard-basket');
            const field = basket.querySelector('[data-price]');
            const card = field.closest('[data-design-card]');
            const addImage = card.querySelector('[data-add-design]');
            const minus = card.querySelector('[data-step="-1"]');
            const plus = card.querySelector('[data-step="1"]');
            const review = document.getElementById('review-basket');
            field.value = 0; input(field);
            assert(minus.disabled, 'minus must start disabled');
            addImage.click();
            assert(field.value === '1', 'image click must add one');
            assert(card.classList.contains('is-selected'), 'selected card needs highlight');
            assert(!card.querySelector('.quantity-badge').hidden, 'badge must be visible');
            assert(card.querySelector('.quantity-badge').textContent === '\\u00d71', 'badge quantity wrong');
            plus.click();
            assert(field.value === '2', 'plus must add one');
            const amount = document.getElementById('basket-total').textContent;
            assert(amount.includes((2 * Number(field.dataset.price)).toFixed(2)), 'total incorrect');
            minus.click();
            assert(field.value === '1', 'minus must remove one');
            const preview = card.querySelector('[data-preview-src]');
            preview.click();
            const dialog = document.getElementById('design-preview');
            assert(dialog.open, 'preview did not open');
            assert(field.value === '1', 'preview must not add a design');
            document.getElementById('close-design-preview').click();
            assert(!dialog.open, 'preview did not close');
            await new Promise(resolve => setTimeout(resolve, 50));
            assert(document.activeElement === preview, 'preview must restore focus');
            field.value = 20; input(field);
            addImage.click();
            assert(field.value === '20' && plus.disabled, 'quantity cap must be respected');
            field.value = 0; input(field);
            assert(!card.classList.contains('is-selected'), 'empty card must clear highlight');
            assert(card.querySelector('.quantity-badge').hidden, 'empty badge must hide');
            assert(review.disabled, 'empty basket must not submit');
            const sticky = document.querySelector('.moodboard-sticky-basket');
            assert(getComputedStyle(sticky).position === 'fixed', 'basket must remain visible');
            const rect = sticky.getBoundingClientRect();
            assert(rect.left >= 0 && rect.right <= innerWidth + 1, 'mobile basket overflows');
        ''', width=390)


if __name__ == '__main__':
    unittest.main()
