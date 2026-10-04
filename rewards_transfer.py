"""Private, portable referral export/import. Never commit the export file."""
import json
from datetime import datetime
from flask import request, flash, redirect, url_for
from sqlalchemy import text

FIELDS = ['customer_name', 'code', 'original_event_date', 'expires_date', 'friend_event_date',
          'reward_earned_date', 'reward_redeemed_date', 'reward_text', 'status']


def export_referrals(engine):
    with engine.connect() as connection:
        referrals = [dict(row) for row in connection.execute(text('SELECT * FROM referrals')).mappings()]
        uses = [str(row[0]) for row in connection.execute(text('SELECT code FROM referral_code_use'))]
        uses += [str(row[0]) for row in connection.execute(text('SELECT DISTINCT promo_code FROM booking WHERE promo_code IS NOT NULL'))]
    return {'version': 1, 'referrals': [{key: row.get(key) for key in FIELDS} for row in referrals],
            'used_codes': sorted(set(uses))}


def import_referrals(engine, payload):
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('Choose a version 1 Rewards transfer file.')
    rows, used = payload.get('referrals'), payload.get('used_codes')
    if not isinstance(rows, list) or not isinstance(used, list) or len(rows) > 10000 or len(used) > 10000:
        raise ValueError('Invalid transfer file.')
    prepared = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid referral record.')
        values = {key: row.get(key) for key in FIELDS}
        if any(not isinstance(values[key], str) or not values[key] or len(values[key]) > 255 for key in ['customer_name', 'code', 'reward_text']):
            raise ValueError('Every record must contain a name, code and reward description.')
        if len(values['code']) > 100 or values['status'] not in {'active', 'earned', 'redeemed'}:
            raise ValueError('Invalid code or reward status.')
        for key in ['original_event_date', 'expires_date', 'friend_event_date', 'reward_earned_date', 'reward_redeemed_date']:
            if values[key] is not None:
                datetime.strptime(values[key], '%Y-%m-%d')
            elif key in {'original_event_date', 'expires_date'}:
                raise ValueError('Original event and expiry dates are required.')
        prepared.append(values)
    if any(not isinstance(code, str) or not code or len(code) > 100 for code in used):
        raise ValueError('Invalid single-use history.')
    inserted = skipped = 0
    with engine.begin() as connection:
        for row in prepared:
            result = connection.execute(text('INSERT INTO referrals (' + ','.join(FIELDS) + ') VALUES (' + ','.join(':'+key for key in FIELDS) + ') ON CONFLICT (code) DO NOTHING'), row)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        for code in used:
            connection.execute(text('INSERT INTO referral_code_use (code, used_at) VALUES (:code, :used_at) ON CONFLICT (code) DO NOTHING'), {'code': code, 'used_at': datetime.now()})
    return inserted, skipped


def register_transfer(app, engine, admin_required):
    @app.post('/admin/rewards/import-transfer')
    @admin_required
    def import_rewards_transfer():
        upload = request.files.get('transfer_file')
        try:
            if not upload:
                raise ValueError('Choose a Rewards transfer file.')
            raw = upload.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Transfer files must be under 2 MB.')
            inserted, skipped = import_referrals(engine, json.loads(raw.decode('utf-8-sig')))
            flash(f'Transferred {inserted} referrals; preserved {skipped} existing codes. Single-use history restored.', 'success')
        except (ValueError, TypeError, UnicodeError):
            flash('The transfer file is invalid. No records were changed.', 'error')
        return redirect(url_for('rewards.dashboard', section='all'))
