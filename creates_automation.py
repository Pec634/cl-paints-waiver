"""Account-free message acknowledgements and scheduled CL Creates maintenance."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import secrets
import click
from flask import abort, has_request_context, make_response, redirect, render_template, request, session, url_for
from sqlalchemy import or_


def parse_settings(form, current):
    result = {}
    try:
        days = sorted(set(int(value.strip()) for value in form.get('reminder_days', current['reminder_days']).split(',') if value.strip()))
        if len(days) > 10 or any(day < 1 or day > 365 for day in days):
            raise ValueError()
        result['reminder_days'] = ','.join(map(str, days))
        for key in ('archive_days', 'delete_days'):
            result[key] = int(form.get(key, current[key]))
            if not 0 <= result[key] <= 3650:
                raise ValueError()
        if result['delete_days'] and (not result['archive_days'] or result['delete_days'] <= result['archive_days']):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Use up to 10 reminder days (1–365). Retention must be 0–3650 days; deletion must be later than archiving. Zero disables retention.')
    for key, limit in (('reminder_subject', 200), ('reminder_body', 10000)):
        value = form.get(key, current[key]).strip()
        if not value or len(value) > limit:
            raise ValueError('Enter a reminder subject and body within 200 / 10,000 characters.')
        import string
        allowed = {'first_name', 'order_number', 'balance', 'payment_url'}
        try:
            for _, field, spec, conversion in string.Formatter().parse(value):
                if field is not None and (field not in allowed or spec or conversion):
                    raise ValueError()
            value.format(**dict.fromkeys(allowed, 'Example'))
        except (KeyError, ValueError, IndexError, AttributeError):
            raise ValueError('Reminder placeholders: {first_name}, {order_number}, {balance}, {payment_url}.')
        result[key] = value
    return result


def register(app, db, Order, Message, settings, communicate, business_settings, admin_required, csrf):
    @app.route('/cl-creates/message/<token>', methods=['GET', 'POST'])
    def creates_message_view(token):
        message = Message.query.filter_by(view_token=token).first_or_404()
        form_token = session.setdefault('creates_message_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(form_token, request.form.get('csrf_token', '')):
                abort(400)
            if message.viewed_at is None:
                Message.query.filter_by(id=message.id, viewed_at=None).update(
                    {Message.viewed_at: datetime.utcnow()}, synchronize_session=False)
                db.session.commit()
                db.session.refresh(message)
        response = make_response(render_template('creates_message_view.html', message=message, csrf=form_token))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    def process(apply=False, now=None):
        if has_request_context():
            return process_orders(apply, now)
        with app.test_request_context('/'):
            return process_orders(apply, now)

    def process_orders(apply=False, now=None):
        now = now or datetime.utcnow()
        config = settings()
        report = dict(reminders=0, archived=0, deleted=0, protected=0, errors=0)
        base = business_settings().get('public_app_url', '').rstrip('/')
        parsed = urlsplit(base)
        valid_base = parsed.scheme == 'https' and bool(parsed.hostname) and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
        days = [int(day) for day in config['reminder_days'].split(',') if day]
        orders = Order.query.filter(Order.paid < Order.total, Order.status.in_(('Under review', 'Awaiting payment'))).order_by(Order.id).all()
        for order in orders:
            order_id = order.id
            claimed = False
            try:
                if apply:
                    claimed = bool(Order.query.filter(Order.id == order_id, or_(Order.automation_claimed_at.is_(None), Order.automation_claimed_at < now - timedelta(minutes=15))).update({Order.automation_claimed_at: now}, synchronize_session=False))
                    db.session.commit()
                    if not claimed:
                        continue
                    db.session.refresh(order)
                    if order.checkout_started:
                        # Failure to reconcile must prevent both reminders and retention.
                        if app.extensions['creates_verify_payment'](order):
                            continue
                    # Re-read after provider calls and lock against admin edits while
                    # deciding retention. Checkout creation also respects our claim.
                    order = Order.query.filter_by(id=order_id).populate_existing().with_for_update().first()
                    if order is None:
                        continue
                if order.paid >= order.total:
                    continue
                age = (now - order.created_at).total_seconds() / 86400
                # Never remove a record while an external payment can still arrive.
                protected = bool(order.checkout_started or order.provider_id or order.payment_url or order.invoice_url or order.invoice_reference or order.paid)
                if config['archive_days'] and age >= config['archive_days']:
                    if protected:
                        report['protected'] += 1
                    else:
                        if order.archived_at is None:
                            report['archived'] += 1
                            if apply:
                                order.archived_at = now
                                app.logger.info('CL Creates archived unpaid order %s', order_id)
                        if config['delete_days'] and age >= config['delete_days']:
                            report['deleted'] += 1
                            if apply:
                                Message.query.filter_by(order_id=order_id).delete(synchronize_session=False)
                                db.session.delete(order)
                                db.session.commit()
                                app.logger.info('CL Creates deleted expired unpaid order %s', order_id)
                        if apply:
                            db.session.commit()
                        continue
                if order.archived_at or not days or not config['emails'] or not valid_base:
                    continue
                due = [day for day in days if age >= day]
                if not due:
                    continue
                # Send only the latest due stage after downtime; never a burst of old reminders.
                day = max(due)
                key = f'reminder:{order.id}:{day}'
                previous = Message.query.filter_by(automation_key=key).first()
                if previous and previous.result != 'Failed':
                    continue
                # Legacy invoices cannot be verified automatically: do not chase potentially paid customers.
                if not order.checkout_token or (not order.checkout_started and (order.invoice_url or order.invoice_reference)):
                    continue
                values = dict(first_name=order.first_name, order_number=order.number,
                              balance=f'{order.total - order.paid:.2f}',
                              payment_url=base + '/cl-creates/payment/' + order.checkout_token)
                if apply:
                    message = communicate(order, config['reminder_subject'].format(**values), config['reminder_body'].format(**values), True, key)
                    if message.result != 'Sent':
                        report['errors'] += 1
                        continue
                report['reminders'] += 1
            except Exception:
                db.session.rollback()
                report['errors'] += 1
                app.logger.exception('CL Creates automation failed for order %s', order_id)
            finally:
                if claimed:
                    Order.query.filter_by(id=order_id, automation_claimed_at=now).update({Order.automation_claimed_at: None}, synchronize_session=False)
                    db.session.commit()
        return report

    app.extensions['creates_automation'] = process

    @app.cli.command('process-creates-orders')
    @click.option('--apply', is_flag=True, help='Send due reminders and apply configured retention; otherwise preview only.')
    def process_command(apply):
        report = process(apply=apply)
        click.echo(('Applied: ' if apply else 'Preview: ') + ', '.join(f'{key}={value}' for key, value in report.items()))
        if report['errors']:
            raise click.ClickException('Some orders could not be processed; check the application log before retrying.')

    @app.post('/admin/cl-creates/automation/run')
    @admin_required
    def creates_automation_run():
        csrf()
        apply = request.form.get('mode') != 'preview'
        report = process(apply=apply)
        from flask import flash
        flash(('Applied: ' if apply else 'Preview (payment checks happen when applied): ') + ', '.join(f'{key}={value}' for key, value in report.items()))
        return redirect(url_for('creates_settings'))
