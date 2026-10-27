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
            const card = document.querySelector('.booking-request-card');
            const deletion = card.querySelector('.booking-delete-detail');
            const manage = card.querySelector('.booking-manage-detail');
            const withinScreen = element => {
                const bounds = element.getBoundingClientRect();
                return bounds.left >= 0 && bounds.right <= innerWidth + 1;
            };
            assert(card && deletion, 'Booking and delete control must be present');
            assert(withinScreen(deletion.querySelector('summary')), 'Delete control must fit without horizontal scrolling');
            deletion.querySelector('summary').click();
            assert(deletion.open, 'Delete control must expand');
            assert(!document.getElementById('calendar-event-dialog').open, 'Delete must not open booking preview');
            const button = deletion.querySelector('button[type=submit]');
            assert(withinScreen(button), 'Delete button must fit the screen');
            assert(!deletion.querySelector('form').checkValidity(), 'Deletion must still require confirmation');
            manage.querySelector('summary').click();
            assert(manage.open, 'Manage request must expand');
            assert(withinScreen(manage.querySelector('textarea')), 'Management fields must fit the screen');
            assert(document.documentElement.scrollWidth <= innerWidth + 1, 'Page must not overflow horizontally');
            assert(card.scrollWidth <= card.clientWidth + 1, 'Card must not overflow horizontally');
            const search = document.getElementById('bookingSearch');
            search.value = 'no-such-client-123'; input(search);
            assert(card.hidden && getComputedStyle(card).display === 'none', 'Search must hide non-matching cards');
            search.value = ''; input(search);
            assert(!card.hidden, 'Clearing search must restore the card');
            card.querySelector('.booking-detail:not(.booking-action-detail) summary').click();
            assert(document.getElementById('calendar-event-dialog').open, 'Booking preview must still open');
        ''', width=width)

    def test_desktop_actions_fit_without_horizontal_scroll(self):
        self.check_layout(1280)

    def test_phone_actions_fit_without_horizontal_scroll(self):
        self.check_layout(390)

    def test_narrow_desktop_actions_fit_without_horizontal_scroll(self):
        self.check_layout(1000)
