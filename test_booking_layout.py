"""Check booking actions fit the viewport and keep working after filtering."""
import unittest

import test_business_tools as fixtures
import test_native_form_browser as browser_helpers

main = fixtures.main


@unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
class BookingLayoutTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser

    def setUp(self):
        self.fixture = fixtures.BusinessToolsTest()
        self.fixture.setUp()
        self.booking = self.fixture.booking
        self.booking.email = 'a-very-long-customer-address-for-testing-layout@example.com'
        self.booking.event_address = 'A long event address ' * 12
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def check_layout(self, width):
        page = self.fixture.admin.get('/admin/bookings?filter=all')
        self.assertEqual(page.status_code, 200)
        self.browser(page.data, '''
            const menu = document.querySelector('.booking-actions-menu');
            assert(menu && !menu.open, 'Booking actions should start collapsed');
            menu.querySelector('summary').click();
            assert(menu.open, 'Actions menu should open');
            assert(menu.querySelectorAll('nav a').length === 4, 'All booking actions should remain available');
            const menuBounds = menu.querySelector('nav').getBoundingClientRect();
            assert(menuBounds.left >= 0 && menuBounds.right <= innerWidth + 1, 'Actions menu must fit the screen');
            menu.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
            assert(!menu.open && document.activeElement === menu.querySelector('summary'), 'Escape should close the menu and return focus');
            menu.querySelector('summary').click();
            document.querySelector('h1').click();
            assert(!menu.open, 'Clicking outside should close the menu');
            const card = document.querySelector('.booking-request-card');
            const more = card.querySelector('.booking-more-actions');
            const deletion = card.querySelector('.booking-delete-detail');
            const manage = card.querySelector('.booking-manage-detail');
            const withinScreen = element => {
                const bounds = element.getBoundingClientRect();
                return bounds.left >= 0 && bounds.right <= innerWidth + 1;
            };
            assert(card && deletion, 'Booking and delete control must be present');
            assert(!more.open && more.contains(deletion), 'Secondary actions should start collapsed');
            const buttons = [...card.querySelectorAll('.booking-card-actions > .btn, .booking-card-actions > details > summary')];
            const bounds = buttons.map(button => button.getBoundingClientRect());
            assert(bounds.every(rect => Math.abs(rect.height - bounds[0].height) < 1), 'Booking buttons should have matching heights');
            if (innerWidth >= 1000) assert(bounds.every(rect => Math.abs(rect.top - bounds[0].top) < 1), 'Booking buttons should align in one row');
            assert(card.querySelector('.booking-card-event time').textContent.trim(), 'Event date should be visible');
            assert(card.getBoundingClientRect().height < 235, 'Collapsed booking should stay compact');
            more.querySelector('summary').click();
            assert(more.open && !document.getElementById('calendar-event-dialog').open, 'More actions must expand on its own');
            assert(withinScreen(deletion.querySelector('summary')), 'Delete control must fit without horizontal scrolling');
            deletion.querySelector('summary').click();
            assert(deletion.open, 'Delete control must expand');
            assert(!document.getElementById('calendar-event-dialog').open, 'Delete must not open booking preview');
            const button = deletion.querySelector('button[type=submit]');
            assert(withinScreen(button), 'Delete button must fit the screen');
            assert(!deletion.querySelector('form').checkValidity(), 'Deletion must still require confirmation');
            more.querySelector('summary').click();
            manage.querySelector('summary').click();
            assert(manage.open, 'Manage request must expand');
            assert(withinScreen(manage.querySelector('textarea')), 'Management fields must fit the screen');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Page must not overflow horizontally');
            assert(card.scrollWidth <= card.clientWidth + 1, 'Card must not overflow horizontally');
            const region = document.querySelector('.booking-requests-scroll');
            assert(getComputedStyle(region).overflowY === 'auto', 'Requests must scroll vertically');
            assert(region.clientHeight <= innerHeight * .69, 'Request area must have a bounded height');
            region.scrollTop = region.scrollHeight;
            assert(region.scrollTop > 0, 'Expanded booking must be scrollable');
            assert(!region.contains(document.querySelector('.workspace-pagination')), 'Pagination must stay outside the scroll area');
            assert(!manage.querySelector('select[name="status"]'), 'Status should be read-only');
            assert(manage.querySelector('.workspace-badge[data-tone]'), 'Status should be colour coded');
            if (innerWidth > 800) assert(manage.querySelector('input[type="number"]').offsetHeight < 44, 'Desktop fields should be compact');
            const search = document.getElementById('bookingSearch');
            search.value = 'no-such-client-123'; input(search);
            assert(card.hidden && getComputedStyle(card).display === 'none', 'Search must hide non-matching cards');
            search.value = ''; input(search);
            assert(!card.hidden, 'Clearing search must restore the card');
            const searchType = document.getElementById('bookingSearchType');
            searchType.value = 'email';
            searchType.dispatchEvent(new Event('change', {bubbles: true}));
            search.value = 'example.com'; input(search);
            assert(!card.hidden, 'Email search must match compact rows');
            card.querySelector('.booking-detail:not(.booking-action-detail) summary').click();
            assert(document.getElementById('calendar-event-dialog').open, 'Booking preview must still open');
        ''', width=width)

    def test_desktop_actions_fit_without_horizontal_scroll(self):
        self.check_layout(1280)

    def test_phone_actions_fit_without_horizontal_scroll(self):
        self.check_layout(390)

    def test_narrow_desktop_actions_fit_without_horizontal_scroll(self):
        self.check_layout(1000)
