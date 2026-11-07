import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import test_client_portal as fixtures
import test_native_form_browser as browser_helpers
from creates_automation import parse_settings

main = fixtures.main


class CreatesAutomationTest(unittest.TestCase):
    browser = browser_helpers.NativeFormBrowserTest.browser
    def setUp(self):
        self.fixture = fixtures.ClientPortalTest()
        self.fixture.setUp()
        self.Order, self.Message, _, _ = main.creates_models
        self.client = self.fixture.client
        self.admin = main.app.test_client()
        with self.admin.session_transaction() as session:
            session['admin_authenticated'] = True
        self.config = dict(reminder_days='2,7', archive_days=30, delete_days=60, emails=True,
                           reminder_subject='Reminder {order_number}', reminder_body='{first_name}: {balance} {payment_url}')
        main.db.session.merge(main.BusinessSetting(key='cl_creates', value=json.dumps(self.config)))
        main.db.session.merge(main.BusinessSetting(key='public_app_url', value='https://example.com'))
        main.db.session.commit()

    def tearDown(self):
        self.fixture.tearDown()

    def order(self, days=8, **kwargs):
        values = dict(first_name='Alex', last_name='Smith', email='alex@example.com', address='London',
                      fulfilment='postage', items_json='[]', total=10, paid=0,
                      created_at=datetime.utcnow() - timedelta(days=days), checkout_token='token' + str(self.Order.query.count()))
        values.update(kwargs)
        order = self.Order(**values)
        main.db.session.add(order)
        main.db.session.commit()
        return order

    def process(self, apply=True):
        return main.app.extensions['creates_automation'](apply=apply)

    def test_visible_message_page_posts_csrf_protected_first_view(self):
        order = self.order()
        message = self.Message(order_id=order.id, subject='<test>', body='<script>bad</script>', result='Sent', view_token='private-token')
        main.db.session.add(message)
        main.db.session.commit()
        url = '/cl-creates/message/private-token'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'&lt;script&gt;', response.data)
        self.assertIn(b'creates-message-view.js', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIsNone(message.viewed_at)
        self.assertEqual(self.client.post(url).status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session['creates_message_csrf']
        self.assertEqual(self.client.post(url, data={'csrf_token': csrf}).status_code, 200)
        stamp = message.viewed_at
        self.assertIsNotNone(stamp)
        self.client.post(url, data={'csrf_token': csrf})
        self.assertEqual(message.viewed_at, stamp)
        self.assertEqual(self.client.get('/cl-creates/message/unknown').status_code, 404)

    @unittest.skipUnless(browser_helpers.EDGE.is_file(), 'Microsoft Edge is not installed')
    def test_browser_waits_for_visible_tab_and_retries_failed_view(self):
        markup = b'''<!doctype html><html><head></head><body>
        <p data-view-status></p><form data-message-view method="post">
        <input name="csrf_token" value="test-csrf"></form>
        <script src="/static/creates-message-view.js" defer></script></body></html>'''
        self.browser(markup, '''
            const tick = () => new Promise(resolve => setTimeout(resolve, 0));
            await tick();
            assert(window.viewCalls.length === 0, 'Hidden tab was recorded');
            window.testVisibility = 'visible';
            document.dispatchEvent(new Event('visibilitychange'));
            await tick();
            assert(window.viewCalls.length === 1, 'Visible tab did not send');
            assert(window.viewCalls[0].body.get('csrf_token') === 'test-csrf', 'CSRF was missing');
            assert(document.querySelector('[data-view-status]').textContent.includes('retry'), 'Failure not displayed');
            window.testVisibility = 'hidden';
            window.dispatchEvent(new Event('online'));
            await tick();
            assert(window.viewCalls.length === 1, 'Hidden retry was sent');
            window.viewSuccess = true;
            window.testVisibility = 'visible';
            document.dispatchEvent(new Event('visibilitychange'));
            await tick();
            assert(window.viewCalls.length === 2, 'Visible retry did not send');
            assert(document.querySelector('[data-view-status]').textContent.includes('has been notified'), 'Success not displayed');
            window.dispatchEvent(new Event('pageshow'));
            document.dispatchEvent(new Event('visibilitychange'));
            await tick();
            assert(window.viewCalls.length === 2, 'Successful view was sent twice');
        ''', setup='''
            window.testVisibility = 'hidden'; window.viewCalls = []; window.viewSuccess = false;
            Object.defineProperty(document, 'visibilityState', {get: () => window.testVisibility});
            window.fetch = async (url, options) => {window.viewCalls.push(options); return {ok: window.viewSuccess};};
        ''')

    def test_retention_preview_archive_delete_and_protected_records(self):
        archive = self.order(days=35)
        delete = self.order(days=65)
        paid = self.order(days=65, paid=10, status='Paid')
        invoice = self.order(days=65, invoice_url='https://sumup.me/invoice')
        checkout = self.order(days=65, checkout_started=True)
        delete_id = delete.id
        main.db.session.add(self.Message(order_id=delete_id, subject='old', body='body', result='Sent'))
        main.db.session.commit()
        result = self.process(False)
        self.assertEqual(result['deleted'], 1)
        self.assertIsNone(archive.archived_at)
        self.assertIsNotNone(main.db.session.get(self.Order, delete_id))
        with patch.dict(main.app.extensions, {'creates_verify_payment': lambda order: False}):
            result = self.process()
        self.assertEqual(result['deleted'], 1)
        self.assertIsNotNone(archive.archived_at)
        self.assertIsNone(main.db.session.get(self.Order, delete_id))
        self.assertEqual(self.Message.query.filter_by(order_id=delete_id).count(), 0)
        for order in (paid, invoice, checkout):
            self.assertIsNotNone(main.db.session.get(self.Order, order.id))
            self.assertIsNone(order.archived_at)

    def test_settings_reject_unsafe_periods_and_template_fields(self):
        for values in ({'reminder_days':'0'}, {'delete_days':'20'}, {'reminder_body':'{first_name.__class__}'}, {'archive_days':'-1'}):
            with self.assertRaises(ValueError):
                parse_settings(values, self.config)
        self.assertEqual(parse_settings({'reminder_days':'7,2,7'}, self.config)['reminder_days'], '2,7')

    def test_payment_reconciliation_failure_prevents_reminder_and_deletion(self):
        order = self.order(days=65, checkout_started=True)
        with patch.dict(main.app.extensions, {'creates_verify_payment': unittest.mock.Mock(side_effect=ValueError('offline'))}):
            result = self.process()
        self.assertEqual(result['errors'], 1)
        self.assertEqual(self.Message.query.count(), 0)
        self.assertIsNotNone(main.db.session.get(self.Order, order.id))
        self.assertIsNone(order.automation_claimed_at)

    def test_admin_run_requires_authentication_and_csrf(self):
        self.assertNotEqual(self.client.post('/admin/cl-creates/automation/run').status_code, 200)
        self.assertEqual(self.admin.post('/admin/cl-creates/automation/run').status_code, 400)

    def test_reminders_send_latest_due_stage_once_with_private_links(self):
        order = self.order()
        with patch.object(main, 'send_client_email', return_value=True) as send:
            result = self.process()
            self.assertEqual(result['reminders'], 1)
            self.assertEqual(send.call_args.args[0], order.email)
            self.assertIn('/cl-creates/payment/' + order.checkout_token, send.call_args.args[2])
            self.assertIn('/cl-creates/message/', send.call_args.args[2])
            self.assertEqual(self.process()['reminders'], 0)
            self.assertEqual(send.call_count, 1)
        message = self.Message.query.one()
        self.assertEqual(message.automation_key, f'reminder:{order.id}:7')

    def test_failed_reminder_retries_same_message(self):
        self.order()
        with patch.object(main, 'send_client_email', return_value=False):
            self.assertEqual(self.process()['errors'], 1)
        token = self.Message.query.one().view_token
        with patch.object(main, 'send_client_email', return_value=True):
            self.assertEqual(self.process()['reminders'], 1)
        self.assertEqual(self.Message.query.count(), 1)
        self.assertEqual(self.Message.query.one().view_token, token)

    def test_disabled_emails_and_claimed_orders_do_not_send(self):
        order = self.order(automation_claimed_at=datetime.utcnow())
        with patch.object(main, 'send_client_email') as send:
            self.assertEqual(self.process()['reminders'], 0)
            order.automation_claimed_at = None
            self.config['emails'] = False
            main.db.session.merge(main.BusinessSetting(key='cl_creates', value=json.dumps(self.config)))
            main.db.session.commit()
            self.assertEqual(self.process()['reminders'], 0)
            send.assert_not_called()

    def test_verified_payment_stops_reminders(self):
        order = self.order(checkout_started=True)
        def verify(record):
            record.paid = record.total
            record.status = 'Paid'
            main.db.session.commit()
            return True
        with patch.dict(main.app.extensions, {'creates_verify_payment': verify}), patch.object(main, 'send_client_email') as send:
            self.assertEqual(self.process()['reminders'], 0)
            send.assert_not_called()
        self.assertEqual(order.status, 'Paid')

    def test_archived_order_payment_link_expires_and_search_retains_history(self):
        order = self.order(days=35)
        self.process()
        self.assertEqual(self.client.get('/cl-creates/payment/' + order.checkout_token).status_code, 410)
        self.assertNotIn(order.number.encode(), self.admin.get('/admin/cl-creates').data)
        self.assertIn(order.number.encode(), self.admin.get('/admin/cl-creates?q=' + order.number).data)

    def test_settings_and_run_preview_display_result_without_sending(self):
        self.order()
        response = self.admin.get('/admin/cl-creates/settings')
        self.assertIn(b'name="reminder_days"', response.data)
        with self.admin.session_transaction() as session:
            token = session['creates_csrf']
        with patch.object(main, 'send_client_email') as send:
            response = self.admin.post('/admin/cl-creates/automation/run', data={'csrf_token': token, 'mode': 'preview'}, follow_redirects=True)
            self.assertIn(b'Preview (payment checks happen when applied)', response.data)
            send.assert_not_called()
        self.assertEqual(main.app.test_cli_runner().invoke(args=['process-creates-orders']).exit_code, 0)


class CreatesAutomationMigrationTest(unittest.TestCase):
    def test_legacy_message_upgrade_preserves_data_and_is_repeatable(self):
        from types import SimpleNamespace
        from sqlalchemy import create_engine, text, inspect
        from cl_creates import ensure_schema
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE creates_order (id INTEGER PRIMARY KEY)'))
                connection.execute(text('CREATE TABLE creates_message (id INTEGER PRIMARY KEY, body TEXT)'))
                connection.execute(text("INSERT INTO creates_message VALUES (1, 'Keep me')"))
            ensure_schema(SimpleNamespace(engine=engine))
            ensure_schema(SimpleNamespace(engine=engine))
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text('SELECT body FROM creates_message')).scalar(), 'Keep me')
                self.assertTrue({'view_token', 'viewed_at', 'automation_key'}.issubset({c['name'] for c in inspect(connection).get_columns('creates_message')}))
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
