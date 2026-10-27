"""Reconcile attached invoices against verified SumUp transactions."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import secrets
from urllib.error import URLError
from urllib.parse import quote, urlsplit, parse_qs
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import click
from flask import abort, flash, redirect, request, session, url_for

BASE = 'https://api.sumup.com'
PREFIX = 'si-'


def provider_get(path):
    key = os.getenv('SUMUP_API_KEY', '')
    if not key or not os.getenv('SUMUP_MERCHANT_CODE'):
        raise ValueError('Configure the SumUp API key and merchant code first.')
    req = Request(BASE + path, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read(2000001)
        if len(raw) > 2000000:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (URLError, TimeoutError, ValueError):
        raise ValueError('Could not read SumUp transactions. No sync changes were saved.') from None


def history(merchant, days):
    endpoint = '/v2.1/merchants/' + quote(merchant, safe='') + '/transactions/history'
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    path = endpoint + '?limit=100&order=ascending&oldest_time=' + quote(since, safe='')
    rows = {}
    seen = set()
    for _ in range(100):
        if path in seen:
            raise ValueError('SumUp pagination repeated. No sync changes were saved.')
        seen.add(path)
        page = provider_get(path)
        if not isinstance(page.get('items'), list):
            raise ValueError('Invalid SumUp history response.')
        for item in page['items']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                raise ValueError('Invalid SumUp transaction identity.')
            rows[item['id']] = item
        links = page.get('links') or []
        next_links = [link.get('href') for link in links if isinstance(link, dict) and link.get('rel') == 'next']
        if not next_links:
            return list(rows.values())
        if len(next_links) != 1 or not isinstance(next_links[0], str):
            raise ValueError('Invalid SumUp pagination.')
        parsed = urlsplit(next_links[0])
        if parsed.scheme or parsed.netloc or parsed.path not in ('', endpoint):
            raise ValueError('Unexpected SumUp pagination destination.')
        query = parsed.query or next_links[0].lstrip('?')
        if not parse_qs(query):
            raise ValueError('Invalid SumUp pagination query.')
        path = endpoint + '?' + query
    raise ValueError('Too many SumUp history pages. Use a shorter date range.')


def invoice_reference(transaction):
    description = transaction.get('product_summary', '')
    match = re.fullmatch(r'Invoice\s*#\s*([^\r\n]+)', description) if isinstance(description, str) else None
    return match.group(1).strip() if match else None


def register(app, db, Invoice, Booking, Entry, admin_required):
    def sync(days=90, booking_id=None, apply=False):
        merchant = os.getenv('SUMUP_MERCHANT_CODE', '')
        if not merchant or not os.getenv('SUMUP_API_KEY'):
            raise ValueError('Configure the SumUp API key and merchant code first.')
        invoices = Invoice.query
        if booking_id is not None:
            invoices = invoices.filter_by(booking_id=booking_id)
        invoices = {row.reference: row for row in invoices.all()}
        report = dict(recorded=0, matched=0, already_recorded=0, review=[], unmatched=0)
        if not invoices:
            return report
        transactions = history(merchant, days)
        candidates = {}
        for row in transactions:
            reference = invoice_reference(row)
            if reference not in invoices:
                report['unmatched'] += 1
                continue
            candidates.setdefault(reference, []).append(row)
        try:
            for reference, rows in candidates.items():
                invoice = invoices[reference]
                # Lock the booking before inspecting its ledger, including other sync workers.
                booking = Booking.query.filter_by(id=invoice.booking_id).with_for_update().one()
                token_for = lambda row: PREFIX + hashlib.sha256((merchant + ':' + row['id']).encode()).hexdigest()[:60]
                if len(rows) != 1:
                    report['review'].append(f'Invoice {reference}: multiple transactions; review in SumUp.')
                    continue
                row = rows[0]
                token = token_for(row)
                existing = Entry.query.filter_by(token=token).first()
                detail = provider_get('/v2.1/merchants/' + quote(merchant, safe='') + '/transactions?id=' + quote(row['id'], safe=''))
                try:
                    amount = Decimal(str(detail.get('amount')))
                    paid_at = datetime.fromisoformat(detail['timestamp'].replace('Z', '+00:00'))
                    valid = (detail.get('id') == row['id'] and detail.get('merchant_code') == merchant
                             and invoice_reference(detail) == reference and detail.get('currency') == 'GBP'
                             and detail.get('status') == 'SUCCESSFUL' and detail.get('payment_type') == 'ECOM'
                             and amount.is_finite() and amount == invoice.amount and amount > 0
                             and paid_at.tzinfo is not None and paid_at <= datetime.now(timezone.utc)
                             and detail.get('simple_status') not in ('REFUNDED', 'CHARGE_BACK')
                             and Decimal(str(row.get('refunded_amount', 0))) == 0)
                except (InvalidOperation, KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    report['review'].append(f'Invoice {reference}: payment details, refund or status need review.')
                    continue
                if existing:
                    report['already_recorded'] += 1
                    continue
                entries = Entry.query.filter_by(booking_id=booking.id).all()
                # Existing manual/checkout money may already include this invoice payment.
                if any(not entry.token.startswith(PREFIX) for entry in entries):
                    report['review'].append(f'Invoice {reference}: existing ledger entries need duplicate review.')
                    continue
                paid = sum((entry.amount if entry.kind == 'payment' else -entry.amount for entry in entries), Decimal(0))
                if paid + amount > booking.total_event_cost + booking.travel_charge:
                    report['review'].append(f'Invoice {reference}: payment exceeds the booking balance.')
                    continue
                report['matched'] += 1
                if apply:
                    db.session.add(Entry(booking_id=booking.id, token=token, amount=amount, kind='payment',
                        method='SumUp', note=f'Verified invoice {reference}; transaction {detail.get("transaction_code", row["id"])}'[:500],
                        paid_date=paid_at.astimezone(ZoneInfo('Europe/London')).date()))
                    db.session.flush()
                    report['recorded'] += 1
            if apply:
                db.session.commit()
            else:
                db.session.rollback()
        except Exception:
            db.session.rollback()
            raise
        return report

    app.extensions['sumup_invoice_sync'] = sync

    @app.post('/admin/bookings/<int:booking_id>/invoices/sync')
    @admin_required
    def admin_sync_sumup_invoices(booking_id):
        db.get_or_404(Booking, booking_id)
        if not session.get('client_csrf') or not secrets.compare_digest(session['client_csrf'], request.form.get('csrf_token', '')):
            abort(400)
        try:
            result = sync(booking_id=booking_id, apply=True)
            flash(f'SumUp check: {result["recorded"]} payment(s) recorded; {result["already_recorded"]} already recorded. Checked the last 90 days.', 'success')
            for issue in result['review']:
                flash(issue, 'error')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('admin_payments', booking_id=booking_id))

    @app.cli.command('sync-sumup-invoices')
    @click.option('--days', default=90, type=click.IntRange(1, 3660), show_default=True)
    @click.option('--apply', is_flag=True, help='Record verified matches. Otherwise preview only.')
    def sync_command(days, apply):
        """Check invoice payments; unresolved cases are printed for review."""
        try:
            result = sync(days=days, apply=apply)
        except ValueError as error:
            raise click.ClickException(str(error)) from None
        click.echo(json.dumps(result, indent=2))
        if result['review']:
            raise click.ClickException('Some invoice payments need manual review; see the report above.')
