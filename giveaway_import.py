"""Preview and import historical giveaway entries without inventing consent."""
import csv
import io
import json
import secrets
from datetime import datetime, timedelta
from email_validator import validate_email, EmailNotValidError
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class GiveawayImportBatch(db.Model):
        token = db.Column(db.String(64), primary_key=True)
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), nullable=False)
        rows_json = db.Column(db.Text, nullable=False)
        send_email = db.Column(db.Boolean, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        completed_at = db.Column(db.DateTime)
    db._giveaway_import_batch = GiveawayImportBatch


def register(app, db, Form, Submission, Account, admin_required, check, csrf, send):
    Batch = db._giveaway_import_batch

    def message(form, name, number):
        return (f'Hello {name},\n\nYour existing entry into {form.title} has been added to the CL Paints client portal. '
                f'You do not need to enter again.\n\nYour client account number: {number}\n\n'
                f'Sign in using this email address to view your entry and future draw results: '
                f'{url_for("client.login", _external=True)}\n\n'
                'This confirms your existing entry, not a prize win. This import does not subscribe you to marketing emails.\n\nCL Paints')

    @app.route('/admin/native-forms/<int:form_id>/import-entrants', methods=['GET', 'POST'])
    @admin_required
    def giveaway_import(form_id):
        form = db.get_or_404(Form, form_id)
        if form.kind != 'giveaway':
            abort(404)
        error = None
        batch = None
        preview = []
        if request.method == 'POST':
            check()
            if db.session.get(db._giveaway_draw, form_id):
                abort(409, 'This giveaway has already been drawn. Import entries into a new giveaway.')
            try:
                if request.form.get('action') == 'confirm':
                    batch = Batch.query.filter_by(token=request.form.get('batch_token', ''), form_id=form_id).with_for_update().first_or_404()
                    if batch.completed_at:
                        flash('This import has already been completed. No entries or emails were repeated.', 'success')
                        return redirect(url_for('native_form_entries', form_id=form_id))
                    if batch.created_at < datetime.utcnow() - timedelta(minutes=30):
                        raise ValueError('This preview has expired. Please upload or enter the details again.')
                    created, skipped, deliveries = 0, 0, []
                    for row in json.loads(batch.rows_json):
                        account = Account.query.filter(db.func.lower(db.func.trim(Account.email)) == row['email']).first()
                        if not account:
                            account = Account(email=row['email'], first_name=row['first_name'], last_name=row['last_name'])
                            db.session.add(account)
                            db.session.flush()
                        if Submission.query.filter_by(form_id=form_id, client_id=account.id).first():
                            skipped += 1
                            continue
                        details = {'Entry source':'Imported historical giveaway entry',
                                   'Original entry details':'Imported by administrator; original entry rules and consent were recorded outside this system.'}
                        item = Submission(form_id=form_id, client_id=account.id, token=secrets.token_urlsafe(32),
                            giveaway_key=f'{form_id}:{account.id}', email=account.email,
                            name=f'{account.first_name} {account.last_name}'.strip(), answers_json=json.dumps(details),
                            terms_snapshot='Historical entry imported by administrator. Agreement to current form wording was not collected by this import.',
                            title_snapshot=form.title)
                        db.session.add(item)
                        created += 1
                        if batch.send_email:
                            body = message(form, account.first_name, account.account_number)
                            Notice = app.extensions['client_notification_model']
                            notice = Notice(email=account.email, kind='reward', reference=f'Giveaway-import-{form_id}', details=body)
                            db.session.add(notice)
                            deliveries.append((item, notice, body))
                    batch.completed_at = datetime.utcnow()
                    db.session.commit()
                    sent, failed = 0, 0
                    for item, notice, body in deliveries:
                        try:
                            success = False if notice.email.endswith('@example.invalid') else bool(send(notice.email, f'CL Paints: your existing giveaway entry — {form.title}', body))
                        except Exception:
                            app.logger.exception('Historical entry confirmation email failed')
                            success = False
                        item.email_sent = notice.email_sent = success
                        sent += int(success)
                        failed += int(not success)
                    db.session.commit()
                    flash(f'Imported {created} entrants; skipped {skipped} duplicates. Confirmation emails: {sent} sent, {failed} not sent.', 'success')
                    return redirect(url_for('native_form_entries', form_id=form_id))

                rows = []
                selected = request.form.get('client_id', type=int)
                upload = request.files.get('csv_file')
                if upload and upload.filename:
                    content = upload.read(1024 * 1024 + 1)
                    if len(content) > 1024 * 1024:
                        raise ValueError('CSV uploads must be no larger than 1 MB.')
                    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
                    if not {'first_name','last_name','email'} <= set(reader.fieldnames or []):
                        raise ValueError('CSV headers must include first_name, last_name and email.')
                    for row in reader:
                        rows.append(row)
                        if len(rows) > 1000:
                            raise ValueError('Import no more than 1,000 entrants at a time.')
                elif selected:
                    account = db.get_or_404(Account, selected)
                    rows = [dict(first_name=account.first_name, last_name=account.last_name, email=account.email)]
                else:
                    rows = [{key: request.form.get(key, '') for key in ('first_name','last_name','email')}]
                unique = {}
                for index, row in enumerate(rows, 1):
                    first = (row.get('first_name') or '').strip()
                    last = (row.get('last_name') or '').strip()
                    email = validate_email((row.get('email') or '').strip(), check_deliverability=False).normalized.casefold()
                    if not first or not last or len(first) > 100 or len(last) > 100 or len(email) > 254:
                        raise ValueError(f'Row {index}: provide first and last names up to 100 characters and a valid email.')
                    unique.setdefault(email, dict(first_name=first, last_name=last, email=email))
                if not unique:
                    raise ValueError('Add at least one entrant.')
                batch = Batch(token=secrets.token_urlsafe(32), form_id=form_id, rows_json=json.dumps(list(unique.values())), send_email=request.form.get('send_email') == 'yes')
                db.session.add(batch)
                db.session.commit()
                for row in unique.values():
                    account = Account.query.filter(db.func.lower(db.func.trim(Account.email)) == row['email']).first()
                    duplicate = bool(account and Submission.query.filter_by(form_id=form_id, client_id=account.id).first())
                    preview.append(dict(row, number=account.account_number if account else 'Assigned on import', status='Skip duplicate' if duplicate else 'Link existing account' if account else 'Create account'))
            except (ValueError, UnicodeError, csv.Error, EmailNotValidError) as exc:
                db.session.rollback()
                error = str(exc)
                batch = None
            except IntegrityError:
                db.session.rollback()
                error = 'The records changed during import. Preview again; no partial import was saved.'
                batch = None
        return render_template('admin_giveaway_import.html', form=form, batch=batch, preview=preview,
            email_preview=message(form, '{first_name}', '{client_account_number}'), csrf=csrf(), error=error,
            accounts=Account.query.order_by(Account.first_name, Account.last_name).limit(500).all())
