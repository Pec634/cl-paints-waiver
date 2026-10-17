from datetime import datetime, timedelta
import re
import unittest
from unittest.mock import patch
import test_loyalty as fixtures

main = fixtures.main


class KioskTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoyaltyTest()
        self.fixture.setUp()
        self.event, _ = self.fixture.event()
        self.admin = self.fixture.admin
        self.admin.get('/admin/kiosk')
        self.admin.post('/admin/kiosk', data=dict(csrf_token='admin-token', event_id=self.event.id, pin='583729'))
        with self.admin.session_transaction() as session: self.kiosk_id = session['kiosk_id']

    def tearDown(self):
        self.fixture.tearDown()

    def test_admin_can_replace_saved_pin_and_unlock_with_new_pin(self):
        from werkzeug.security import check_password_hash
        item = main.db.session.get(main.KioskSession, self.kiosk_id)
        self.admin.post('/kiosk/staff', data=dict(csrf_token=item.csrf, pin='583729', action='exit'))
        self.admin.get('/admin/kiosk')
        with self.admin.session_transaction() as state: csrf = state['client_csrf']
        payload = dict(csrf_token=csrf, event_id=self.event.id, pin='917264')
        response = self.admin.post('/admin/kiosk', data=payload)
        self.assertIn(b'Set a new staff PIN', response.data)
        with self.admin.session_transaction() as state: self.assertNotIn('kiosk_id', state)
        payload['replace_pin'] = 'yes'
        self.assertEqual(self.admin.post('/admin/kiosk', data={**payload, 'csrf_token':'wrong'}).status_code, 400)
        self.assertTrue(check_password_hash(main.db.session.get(main.BusinessSetting, 'kiosk_pin_hash').value, '583729'))
        self.assertEqual(self.admin.post('/admin/kiosk', data=payload).status_code, 302)
        with self.admin.session_transaction() as state: identity = state['kiosk_id']
        item = main.db.session.get(main.KioskSession, identity)
        self.admin.post('/kiosk/staff', data=dict(csrf_token=item.csrf, pin='583729', action='exit'))
        self.assertNotEqual(item.phase, 'closed')
        self.admin.post('/kiosk/staff', data=dict(csrf_token=item.csrf, pin='917264', action='exit'))
        self.assertEqual(item.phase, 'closed')

    def test_wedding_fair_form_is_quick_and_does_not_email_during_fair(self):
        import json
        item = main.db.session.get(main.KioskSession, self.kiosk_id)
        self.admin.post('/kiosk/staff', data=dict(csrf_token=item.csrf, pin='583729', action='exit'))
        self.admin.get('/admin/kiosk')
        with self.admin.session_transaction() as state: csrf = state['client_csrf']
        for _ in range(2):
            self.admin.post('/admin/kiosk', data=dict(csrf_token=csrf, action='wedding_fair'))
        Form, Submission, _ = main.native_form_models
        form = Form.query.filter_by(kind='enquiry').one()
        self.assertTrue(form.enabled)
        page = self.admin.get(f'/admin/kiosk?wedding_form={form.id}&event_id={self.event.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'name="form_ids" value="{form.id}" checked'.encode(), page.data)
        self.assertIn(f'name="event_ids" value="{self.event.id}" checked'.encode(), page.data)
        self.assertEqual(self.admin.get('/admin/kiosk?wedding_form=invalid&event_id=invalid').status_code, 200)
        self.assertTrue(all(not field['required'] for field in json.loads(form.fields_json)))
        self.event.status = 'Closed'; main.db.session.commit()
        self.admin.post('/admin/kiosk', data=dict(csrf_token=csrf, selection_present='1',
            form_ids=str(form.id), pin='583729'))
        with self.admin.session_transaction() as state: kiosk_id = state['kiosk_id']
        kiosk = main.db.session.get(main.KioskSession, kiosk_id)
        self.assertIsNone(kiosk.event_id)
        self.assertEqual(self.admin.get('/kiosk').status_code, 200)
        self.assertIn(form.title.encode(), self.admin.get('/kiosk/customer').data)
        self.assertEqual(self.admin.post('/kiosk/new-waiver', data=dict(csrf_token=kiosk.csrf)).status_code, 403)
        page = self.admin.get(f'/forms/{form.id}')
        self.assertIn(b'Send me wedding information', page.data)
        self.assertIn(b'data-draft-url=""', page.data)
        self.assertNotIn(b'Submit media and consent', page.data)
        with self.admin.session_transaction() as state:
            payload = dict(csrf_token=state['client_csrf'], submission_token=state['native_form_'+str(form.id)],
                guest_first_name='Wedding', guest_last_name='Visitor', guest_email='visitor@example.com',
                custom_0='Summer 2028', custom_1='', custom_2='Not sure yet', agree='yes')
        # Background requests and redirects must not invalidate the visible form.
        self.admin.get('/phone-push-worker.js')
        self.admin.get(f'/forms/{form.id}/draft', follow_redirects=True)
        self.admin.get('/kiosk/customer')
        with self.admin.session_transaction() as state:
            self.assertEqual(state['client_csrf'], payload['csrf_token'])
        activity = self.admin.post(f'/forms/{form.id}/activity', json=dict(started=True, steps=[0]),
            headers={'X-CSRF-Token': payload['csrf_token']})
        self.assertEqual(activity.status_code, 200)
        self.assertEqual(self.admin.post(f'/forms/{form.id}/activity', json={},
            headers={'X-CSRF-Token': 'wrong'}).status_code, 400)
        with patch.object(main, 'send_client_email', return_value=True) as send:
            response = self.admin.post(f'/forms/{form.id}', data=payload)
        send.assert_not_called()
        self.assertTrue(response.location.endswith('/kiosk/form-done'))
        confirmation = self.admin.get(response.location)
        self.assertIn(b'Your form has been received.', confirmation.data)
        self.assertIn(b'10 seconds', confirmation.data)
        self.assertIn(b'Click for next person', confirmation.data)
        self.assertIn(b'const duration = 10000;', confirmation.data)
        self.assertIn(f'href="/forms/{form.id}"'.encode(), confirmation.data)
        fresh_form = self.admin.get(f'/forms/{form.id}')
        self.assertEqual(fresh_form.status_code, 200)
        self.assertNotIn(b'visitor@example.com', fresh_form.data)
        self.assertNotIn(b'Summer 2028', fresh_form.data)
        with self.admin.session_transaction() as state:
            self.assertNotEqual(state['native_form_'+str(form.id)], payload['submission_token'])
        entry = Submission.query.filter_by(form_id=form.id).one()
        self.assertEqual(entry.email, 'visitor@example.com')
        self.assertEqual(json.loads(entry.answers_json)['Wedding date or expected year'], 'Summer 2028')
        queue = main.app.extensions['wedding_followups']
        job = queue['model'].query.filter_by(submission_id=entry.id).one()
        self.assertEqual(job.due_at, entry.created_at + timedelta(hours=4))
        original_due = job.due_at
        with self.admin.session_transaction() as state:
            payload.update(csrf_token=state['client_csrf'], submission_token=state['native_form_'+str(form.id)])
        payload.update(guest_email='VISITOR@example.com', custom_0='Summer 2030')
        repeated = self.admin.post(f'/forms/{form.id}', data=payload)
        self.assertTrue(repeated.location.endswith('/kiosk/form-done'))
        self.assertEqual(Submission.query.filter_by(form_id=form.id).count(), 1)
        self.assertEqual(queue['model'].query.count(), 1)
        self.assertEqual(job.due_at, original_due)
        self.assertEqual(json.loads(entry.answers_json)['Wedding date or expected year'], 'Summer 2030')
        self.admin.get(repeated.location)
        self.admin.get(f'/forms/{form.id}')
        with patch.object(main, 'send_client_email', return_value=True) as send:
            queue['process'](job.due_at - timedelta(seconds=1))
            send.assert_not_called()
            queue['process'](job.due_at)
            queue['process'](job.due_at + timedelta(minutes=1))
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], 'visitor@example.com')
        self.assertIn('/booking', send.call_args.args[2])
        self.assertIn('per hour', send.call_args.args[2])
        self.assertEqual(main.app.test_client().get('/booking').status_code, 200)
        self.assertEqual(job.status, 'sent')
        self.assertTrue(entry.email_sent)
        # Updating a contact after the email was sent must not queue another.
        with self.admin.session_transaction() as state:
            payload.update(csrf_token=state['client_csrf'], submission_token=state['native_form_'+str(form.id)])
        payload.update(guest_email='VISITOR@example.com', custom_0='Summer 2029')
        self.assertEqual(self.admin.post(f'/forms/{form.id}', data=payload).status_code, 302)
        self.assertEqual(Submission.query.filter_by(form_id=form.id).count(), 1)
        self.assertEqual(queue['model'].query.count(), 1)
        self.assertEqual(json.loads(entry.answers_json)['Wedding date or expected year'], 'Summer 2029')
        with patch.object(main, 'send_client_email', return_value=True) as send:
            queue['process'](job.due_at + timedelta(days=1))
        send.assert_not_called()

    def test_idle_reset_clears_session_and_invalidates_old_submission_token(self):
        import json
        Form = main.native_form_models[0]
        form = Form(kind='enquiry', title='Idle reset enquiry', terms='Contact permission', enabled=True, fields_json='[]')
        main.db.session.add(form); main.db.session.commit()
        item = main.db.session.get(main.KioskSession, self.kiosk_id)
        item.choices_json = json.dumps(dict(events=[self.event.id], forms=[form.id]))
        main.db.session.commit()
        page = self.admin.get(f'/forms/{form.id}')
        self.assertIn(b'kioskIdleDialog', page.data)
        with self.admin.session_transaction() as state:
            old_token = state['native_form_'+str(form.id)]
            state['native_draft_owner'] = 'old-person'
        path = f'/kiosk/forms/{form.id}/reset'
        self.assertEqual(self.admin.post(path).status_code, 400)
        self.assertEqual(self.admin.post(path, headers={'X-CSRF-Token':item.csrf}).status_code, 200)
        self.admin.get(f'/forms/{form.id}')
        with self.admin.session_transaction() as state:
            self.assertNotEqual(old_token, state['native_form_'+str(form.id)])
            csrf = state['client_csrf']
        self.assertEqual(self.admin.post(f'/forms/{form.id}', data=dict(csrf_token=csrf, submission_token=old_token)).status_code, 400)

    def test_selected_events_and_forms_are_enforced(self):
        import json
        Form = main.native_form_models[0]
        selected = Form(kind='giveaway', title='Kiosk giveaway', terms='Entry rules', enabled=True, fields_json='[]')
        hidden = Form(kind='giveaway', title='Other giveaway', terms='Entry rules', enabled=True, fields_json='[]')
        second, _ = self.fixture.event()
        second.name = 'Second selected event'
        main.db.session.add_all([selected, hidden]); main.db.session.commit()
        item = main.db.session.get(main.KioskSession, self.kiosk_id)
        self.admin.post('/kiosk/staff', data=dict(csrf_token=item.csrf, pin='583729', action='exit'))
        self.admin.get('/admin/kiosk')
        with self.admin.session_transaction() as state: csrf = state['client_csrf']
        self.admin.post('/admin/kiosk', data=dict(csrf_token=csrf, selection_present='1',
            event_ids=[str(self.event.id), str(second.id)], form_ids=str(selected.id), pin='583729'))
        with self.admin.session_transaction() as state: identity = state['kiosk_id']
        item = main.db.session.get(main.KioskSession, identity)
        self.assertEqual(json.loads(item.choices_json)['forms'], [selected.id])
        menu = self.admin.get('/kiosk/customer')
        self.assertIn(b'Kiosk giveaway', menu.data)
        self.assertIn(b'Second selected event', menu.data)
        self.assertNotIn(b'Other giveaway', menu.data)
        self.assertEqual(self.admin.get(f'/forms/{hidden.id}').status_code, 302)
        self.assertIn(b'guest_email', self.admin.get(f'/forms/{selected.id}').data)
        with self.admin.session_transaction() as state:
            form_csrf = state['client_csrf']
            submission_token = state['native_form_'+str(selected.id)]
        with patch.object(main, 'send_client_email', return_value=True):
            response = self.admin.post(f'/forms/{selected.id}', data=dict(csrf_token=form_csrf,
                submission_token=submission_token, agree='yes', guest_first_name='Guest',
                guest_last_name='Customer', guest_email=self.fixture.account.email))
        self.assertTrue(response.location.endswith('/kiosk/form-done'))
        submission = main.native_form_models[1].query.filter_by(form_id=selected.id).one()
        self.assertEqual(submission.name, 'Guest Customer')
        self.assertEqual(self.admin.get(f'/client/form-submissions/{submission.id}').status_code, 302)
        with self.admin.session_transaction() as state: self.assertNotIn('client_id', state)
        self.assertEqual(self.admin.post('/kiosk/choose', data=dict(event_id=second.id)).status_code, 400)
        self.admin.post('/kiosk/choose', data=dict(csrf_token=item.csrf, event_id=second.id))
        self.assertEqual(item.event_id, second.id)
        self.assertIn(b'I already have a waiver', self.admin.get('/kiosk/customer').data)
        self.admin.get('/kiosk/menu')
        selected.enabled=False; main.db.session.commit()
        self.assertNotIn(b'Kiosk giveaway', self.admin.get('/kiosk/menu').data)
        self.assertEqual(self.admin.get(f'/forms/{selected.id}').status_code, 404)

    def test_legacy_event_requirement_is_removed_without_losing_sessions(self):
        from kiosk import ensure_schema
        from sqlalchemy import text, inspect
        main.db.session.remove()
        with main.db.engine.begin() as connection:
            connection.execute(text('''CREATE TABLE kiosk_session_legacy (
                id VARCHAR(64) PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES event(id),
                phase VARCHAR(20) NOT NULL, csrf VARCHAR(64) NOT NULL,
                waiver_id INTEGER REFERENCES waiver(id), completed_at DATETIME,
                choices_json TEXT, pin_attempts INTEGER NOT NULL, locked_until DATETIME)'''))
            columns = 'id, event_id, phase, csrf, waiver_id, completed_at, choices_json, pin_attempts, locked_until'
            connection.execute(text(f'INSERT INTO kiosk_session_legacy ({columns}) SELECT {columns} FROM kiosk_session'))
            connection.execute(text('DROP TABLE kiosk_session'))
            connection.execute(text('ALTER TABLE kiosk_session_legacy RENAME TO kiosk_session'))
        ensure_schema(main.db)
        ensure_schema(main.db)
        column = next(c for c in inspect(main.db.engine).get_columns('kiosk_session') if c['name'] == 'event_id')
        self.assertTrue(column['nullable'])
        item = main.db.session.get(main.KioskSession, self.kiosk_id)
        self.assertEqual(item.event_id, self.event.id)
        self.assertEqual(item.phase, 'signup')
        self.assertEqual(self.admin.get('/kiosk/customer').status_code, 200)
        item.event_id = None; item.choices_json = '{"events": [], "forms": []}'
        main.db.session.commit()
        self.assertEqual(self.admin.get('/kiosk').status_code, 200)

    def test_existing_kiosk_table_is_upgraded_without_losing_session(self):
        from kiosk import ensure_schema
        from sqlalchemy import text, inspect
        main.db.session.remove()
        with main.db.engine.begin() as connection:
            connection.execute(text('ALTER TABLE kiosk_session DROP COLUMN completed_at'))
            connection.execute(text('ALTER TABLE kiosk_session DROP COLUMN choices_json'))
        ensure_schema(main.db)
        ensure_schema(main.db)
        self.assertIn('completed_at', {column['name'] for column in inspect(main.db.engine).get_columns('kiosk_session')})
        self.assertIsNotNone(main.db.session.get(main.KioskSession, self.kiosk_id))
        self.assertEqual(self.admin.get('/kiosk/customer').status_code, 200)

    def test_guest_waiver_auto_reset_and_later_account_link(self):
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'I already have a waiver', page.data)
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        self.admin.post('/kiosk/new-waiver', data={'csrf_token':item.csrf})
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'id="responsibleEmail"', page.data)
        self.assertNotIn(b'Email my verification code', page.data)
        self.assertEqual(self.admin.post('/client/signup', data={}).status_code, 403)
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        data = dict(responsible_first_name='Kiosk', responsible_last_name='Customer', responsible_email=self.fixture.account.email,
            signature_text='Kiosk Customer', liability_acknowledged=True, responsible_authority=True, responsible_accuracy=True,
            participants=[dict(first_name='Alex',last_name='Customer',age=8,gender='Gender Neutral')])
        self.assertEqual(self.admin.post('/kiosk/submit',json=data).status_code,400)
        with patch.object(main.resend.Emails,'send',return_value={}) as send:
            response = self.admin.post('/kiosk/submit',json=data,headers={'X-CSRF-Token':item.csrf})
            self.assertEqual(send.call_args.args[0]['to'],[self.fixture.account.email])
        self.assertEqual(response.status_code,200)
        self.assertEqual(item.phase,'complete')
        self.assertEqual(main.db.session.get(main.Waiver,item.waiver_id).responsible_email,self.fixture.account.email)
        with self.admin.session_transaction() as session: self.assertNotIn('client_id',session)
        self.assertIn(b'Next customer in',self.admin.get('/kiosk/customer').data)
        self.assertEqual(self.admin.post('/kiosk/submit',json=data,headers={'X-CSRF-Token':item.csrf}).status_code,403)
        portal = self.fixture.client.get('/client/waivers')
        self.assertIn(main.db.session.get(main.Waiver,item.waiver_id).public_reference.encode(), portal.data)
        item.completed_at=datetime.utcnow()-timedelta(seconds=31)
        main.db.session.commit()
        self.assertIn(b'I already have a waiver',self.admin.get('/kiosk/customer').data)
        self.assertEqual(item.phase,'signup')
        self.assertIsNone(item.waiver_id)

    def test_id_lookup_is_member_only_and_rejects_wrong_or_expired_ids(self):
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        path = '/kiosk/lookup-id'
        self.assertEqual(self.admin.post(path, data={'reference':self.fixture.waiver.public_reference}).status_code,400)
        self.admin.post(path, data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        page = self.admin.get('/kiosk/customer')
        self.assertIn(b'Alex Client',page.data)
        self.assertIn(b'Sam Client',page.data)
        self.assertNotIn(self.fixture.account.email.encode(),page.data)
        self.assertNotIn(b'Original signature',page.data)
        with self.admin.session_transaction() as state:
            self.assertNotIn('client_id',state)
        self.assertEqual(self.admin.get('/client/account').status_code,302)
        self.assertEqual(self.admin.post('/kiosk/confirm-members',data={'csrf_token':item.csrf,'member_id':'999999'}).status_code,400)
        self.admin.post('/kiosk/confirm-members',data={'csrf_token':item.csrf,'member_id':self.fixture.person.id})
        complete=self.admin.get('/kiosk/customer')
        self.assertIn(b'Waiver members confirmed',complete.data)
        self.assertIn(b'Alex Client',complete.data)
        self.assertNotIn(b'Sam Client',complete.data)
        item.completed_at=datetime.utcnow()-timedelta(seconds=31);main.db.session.commit()
        self.admin.get('/kiosk/customer')
        with self.admin.session_transaction() as state:
            self.assertNotIn('kiosk_waivers',state)
            self.assertNotIn('kiosk_selected_members',state)
        self.fixture.waiver.expiry_date=datetime.utcnow()-timedelta(days=1);main.db.session.commit()
        self.admin.post(path,data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        self.assertEqual(item.phase,'signup')
        self.assertNotIn(b'Alex Client',self.admin.get('/kiosk/customer').data)

    def test_forged_reference_dates_and_archived_waivers_are_rejected(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        reference=self.fixture.waiver.public_reference
        wrong_date=('01/01/2000' if not reference.startswith('01/01/2000') else '02/01/2000')+reference[10:]
        for value in (wrong_date, str(self.fixture.waiver.id)):
            self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':value})
            self.assertEqual(item.phase,'signup')
        self.fixture.waiver.is_archived=True;main.db.session.commit()
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':reference})
        self.assertEqual(item.phase,'signup')

    def test_email_lookup_verifies_without_portal_signin_and_members_timeout(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        main.ClientLoginCode.query.filter_by(email=self.fixture.account.email).delete();main.db.session.commit()
        with patch.object(main,'send_client_email',return_value=True) as send:
            self.admin.post('/kiosk/email-code',data={'csrf_token':item.csrf,'email':self.fixture.account.email})
            raw=re.search(r'code is (\d{6})',send.call_args.args[2]).group(1)
        self.assertIn(b'Check your email',self.admin.get('/kiosk/customer').data)
        self.admin.post('/kiosk/verify-email',data={'csrf_token':item.csrf,'code':'WRONG'})
        self.assertEqual(item.phase,'signup')
        self.admin.post('/kiosk/verify-email',data={'csrf_token':item.csrf,'code':raw})
        self.assertIn(b'Alex Client',self.admin.get('/kiosk/customer').data)
        with self.admin.session_transaction() as state:
            self.assertNotIn('client_id',state)
            state['kiosk_lookup_expires']=0
        self.assertEqual(self.admin.get('/kiosk/customer').status_code,302)
        self.assertEqual(item.phase,'signup')

    def test_transferred_members_and_lookup_throttle(self):
        item=main.db.session.get(main.KioskSession,self.kiosk_id)
        Custodian=main.loyalty_models[3]
        target=self.fixture.make_waiver('someone@example.com','TARGET-KIOSK')
        main.db.session.add(Custodian(participant_id=self.fixture.person.id,client_id=self.fixture.account.id,waiver_id=target.id));main.db.session.commit()
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        page=self.admin.get('/kiosk/customer')
        self.assertNotIn(b'Alex Client',page.data)
        self.assertIn(b'Sam Client',page.data)
        self.admin.post('/kiosk/start-over',data={'csrf_token':item.csrf})
        for _ in range(10):
            self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':'NOT-FOUND'})
        self.admin.post('/kiosk/lookup-id',data={'csrf_token':item.csrf,'reference':self.fixture.waiver.public_reference})
        self.assertEqual(item.phase,'signup')
        self.assertIn(b'Please wait a minute',self.admin.get('/kiosk/customer').data)

    def test_pin_exit_route_guard_lockout_and_reset_removed(self):
        item = main.db.session.get(main.KioskSession,self.kiosk_id)
        self.assertEqual(self.admin.get('/admin/bookings').status_code,302)
        self.assertEqual(self.admin.post('/client/logout',data={}).status_code,403)
        self.assertEqual(self.admin.post('/kiosk/staff',data=dict(pin='583729',action='exit')).status_code,400)
        for _ in range(5): self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='0000',action='exit'))
        self.assertIsNotNone(item.locked_until)
        self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='583729',action='exit'))
        self.assertEqual(item.phase,'signup')
        item.locked_until=datetime.utcnow()-timedelta(seconds=1)
        main.db.session.commit()
        self.admin.post('/kiosk/staff',data=dict(csrf_token=item.csrf,pin='583729',action='exit'))
        self.assertEqual(item.phase,'closed')
        self.assertEqual(self.admin.get('/admin/bookings').status_code,200)
        self.assertNotIn(b'staffResetButton',self.fixture.client.get(f'/waiver/event/{self.event.id}').data)

    def test_normal_admin_pages_do_not_require_kiosk_table(self):
        from sqlalchemy import text
        with main.db.engine.begin() as connection:
            connection.execute(text('DROP TABLE kiosk_session'))
        admin = main.app.test_client()
        with admin.session_transaction() as session: session['admin_authenticated'] = True
        self.assertEqual(admin.get('/admin/bookings').status_code,200)
        self.assertEqual(admin.get('/admin/dashboard').status_code,200)


if __name__ == '__main__': unittest.main()
