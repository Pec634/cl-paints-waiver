from io import BytesIO
from datetime import datetime, timezone
import os
import unittest

from PIL import Image

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import app as main
import test_reports
from test_admin_polish_browser import BrowserChecks, EDGE


class EquipmentChecklistTest(unittest.TestCase):
    def test_category_selections_and_item_photo(self):
        Category, Item, Entry, BookingCheck = main.equipment_models
        client = main.app.test_client()
        staff_client = main.app.test_client()
        self.assertEqual(client.get('/admin/equipment').status_code, 302)
        with client.session_transaction() as user_session:
            user_session['admin_authenticated'] = True
            user_session['equipment_csrf'] = 'test-token'

        def post(path, **data):
            if path.endswith('/checklist'):
                data.setdefault('checked_by', str(staff.id))
                return staff_client.post('/admin/equipment/' + path, data={'csrf_token': 'test-token', **data})
            return client.post('/admin/equipment/' + path, data={'csrf_token': 'test-token', **data})

        with main.app.app_context():
            main.db.drop_all()
            main.db.create_all()
            staff = main.app.extensions['pos_access'].Staff(
                username='checker', name='Sam Checker', role='cashier', password_hash='unused',
                permissions_json='[]')
            main.db.session.add(staff)
            main.db.session.commit()
            now = datetime.now(timezone.utc).timestamp()
            with staff_client.session_transaction() as state:
                state.update(pos_staff_id=staff.id, pos_last_activity=now, pos_signed_in_at=now,
                             equipment_csrf='test-token')
            self.assertEqual(client.get('/admin/equipment').status_code, 200)
            self.assertEqual(client.post('/admin/equipment/categories', data={'name': 'Party'}).status_code, 400)
            self.assertEqual(post('categories', name='Party').status_code, 302)
            self.assertEqual(post('categories', name='Festival').status_code, 302)
            party = Category.query.filter_by(name='Party').one()
            festival = Category.query.filter_by(name='Festival').one()
            image = BytesIO()
            Image.new('RGB', (16, 16), 'pink').save(image, 'PNG')
            image.seek(0)
            self.assertEqual(post('items', name='Brushes', image=(image, 'brushes.png')).status_code, 302)
            item = Item.query.filter_by(name='Brushes').one()
            photo = client.get(f'/admin/equipment/items/{item.id}/image')
            self.assertEqual(photo.mimetype, 'image/jpeg')
            self.assertEqual(Image.open(BytesIO(photo.data)).size, (16, 16))
            checklist_url = f'/admin/equipment/categories/{party.id}/checklist'
            form = {'csrf_token': 'test-token', 'checked_by': staff.id, 'needed': item.id}
            self.assertEqual(client.post(checklist_url, data=form).status_code, 403)
            self.assertEqual(staff_client.post(checklist_url, data=form).status_code, 403)
            staff.permissions_json = '["equipment"]'
            main.db.session.commit()
            form['checked_by'] = staff.id + 1
            self.assertEqual(staff_client.post(checklist_url, data=form).status_code, 400)
            self.assertEqual(post(f'categories/{party.id}/checklist', needed=[item.id, 999]).status_code, 302)
            self.assertEqual(party.needed_ids, [item.id])
            self.assertEqual(festival.needed_ids, [])
            page = staff_client.get(f'/admin/equipment?category={party.id}')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Party packing list', page.data)
            self.assertIn(b'<li>Brushes</li>', page.data)
            self.assertIn(b'<select name="checked_by" required>', page.data)
            self.assertIn(b'Sam Checker', page.data)
            self.assertEqual(post(f'categories/{party.id}/checklist').status_code, 302)
            self.assertEqual(party.needed_ids, [])
            self.assertEqual(post(f'categories/{party.id}/checklist', needed=[item.id]).status_code, 302)
            self.assertEqual(post(f'categories/{festival.id}/checklist', needed=[item.id]).status_code, 302)
            delete_path = f'categories/{party.id}/delete'
            self.assertEqual(client.post('/admin/equipment/' + delete_path).status_code, 400)
            self.assertEqual(post(delete_path).status_code, 302)
            self.assertIsNone(Category.query.filter_by(name='Party').one_or_none())
            self.assertEqual(festival.needed_ids, [item.id])
            booking = test_reports.ReportsTest().booking()
            self.assertEqual(post(f'categories/{festival.id}', name=booking.event_type).status_code, 302)
            shortcut_page = staff_client.get(f'/admin/equipment?booking={booking.id}')
            self.assertIn(f'{booking.event_type} packing list'.encode(), shortcut_page.data)
            self.assertIn(b'Save booking check', shortcut_page.data)
            self.assertEqual(post(f'categories/{festival.id}', name='Festival').status_code, 302)
            booking_page = staff_client.get(f'/admin/equipment?category={festival.id}&booking={booking.id}')
            self.assertIn(b'Save booking check', booking_page.data)
            self.assertIn(f'name="needed" value="{item.id}" checked'.encode(), booking_page.data)
            self.assertEqual(post(f'categories/{festival.id}/checklist', booking=booking.id).status_code, 302)
            self.assertEqual(BookingCheck.query.filter_by(booking_id=booking.id).one().needed_ids, [])
            self.assertEqual(festival.needed_ids, [item.id])
            booking_page = staff_client.get(f'/admin/equipment?category={festival.id}&booking={booking.id}')
            self.assertNotIn(f'name="needed" value="{item.id}" checked'.encode(), booking_page.data)
            if EDGE.is_file():
                BrowserChecks.browser(self, booking_page.data, '''
                    const form = document.querySelector('[data-equipment-checklist]');
                    const count = form.querySelector('[data-needed-count]');
                    const filter = form.querySelector('[data-needed-only]');
                    const item = form.querySelector('input[name="needed"]');
                    assert(count.textContent === '0 items needed', 'initial count');
                    filter.click();
                    assert(item.closest('label').hidden, 'unused item is visible');
                    filter.click();
                    item.click();
                    assert(count.textContent === '1 item needed', 'live count did not update');
                    const [categories, workspace] = document.querySelector('.equipment-management').children;
                    assert(workspace.getBoundingClientRect().left > categories.getBoundingClientRect().right,
                      'categories and workspace are not side by side');
                ''', 1200)
            self.assertEqual(client.get(f'/admin/equipment/items/{item.id}/image').status_code, 200)
            party_checks = Entry.query.filter_by(category_name='Party').order_by(Entry.id).all()
            self.assertEqual([check.needed for check in party_checks], [['Brushes'], [], ['Brushes']])
            self.assertEqual(party_checks[1].not_needed, ['Brushes'])
            self.assertEqual(party_checks[0].recorded_by, 'Sam Checker')
            self.assertEqual(party_checks[0].local_time.tzinfo.key, 'Europe/London')
            equipment_page = client.get('/admin/equipment')
            self.assertIn(b'View checklist history', equipment_page.data)
            self.assertNotIn(b'<h1>Checklist history</h1>', equipment_page.data)
            self.assertNotIn(b'Sam Checker', equipment_page.data)
            self.assertEqual(main.app.test_client().get('/admin/equipment/history').status_code, 302)
            history_page = staff_client.get('/admin/equipment/history')
            self.assertEqual(history_page.status_code, 200)
            self.assertIn(b'Checklist history', history_page.data)
            self.assertIn(b'Party', history_page.data)
            filtered = staff_client.get('/admin/equipment/history', query_string={
                'event_category': 'Festival', 'staff': 'Sam Checker',
                'from_date': party_checks[0].local_time.date().isoformat(),
                'to_date': party_checks[0].local_time.date().isoformat(),
            })
            self.assertEqual(filtered.status_code, 200)
            self.assertIn(booking.public_reference.encode(), filtered.data)
            self.assertNotIn(b'<summary>Party', filtered.data)
