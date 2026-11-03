"""Add clearly fictional draw entries to the project's local SQLite database only."""
from datetime import datetime
from pathlib import Path
import json
import secrets
import sqlite3


def main():
    database = Path(__file__).resolve().parent / 'instance' / 'cl_paints_waivers.db'
    connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)
    connection.execute('PRAGMA foreign_keys=ON')
    form = connection.execute(
        "SELECT id,title,terms FROM native_form WHERE kind='giveaway' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not form:
        raise SystemExit('No local giveaway exists; nothing changed.')
    backup_path = database.with_name('before_demo_giveaway_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    names = ['Amelia', 'Oliver', 'Isla', 'Noah', 'Ava', 'Arthur', 'Freya', 'Leo',
             'Lily', 'George', 'Mia', 'Oscar', 'Ivy', 'Theo', 'Sofia', 'Archie',
             'Grace', 'Henry', 'Willow', 'Charlie']
    created = 0
    with connection:
        for index, first_name in enumerate(names, 1):
            email = f'giveaway-demo-{index:02d}@example.invalid'
            account = connection.execute('SELECT id FROM client_account WHERE email=?', (email,)).fetchone()
            now = datetime.utcnow().isoformat(' ')
            if account:
                client_id = account[0]
            else:
                client_id = connection.execute(
                    'INSERT INTO client_account (email,first_name,last_name,phone,address,created_at) VALUES (?,?,?,?,?,?)',
                    (email, first_name, 'Demo', '', 'Fictional local test account', now)
                ).lastrowid
            if connection.execute('SELECT 1 FROM native_submission WHERE form_id=? AND client_id=?', (form[0], client_id)).fetchone():
                continue
            answers = {'I confirm I am aged 18 or over': True,
                       'I am not an employee, contractor or immediate family member of CL Paints': True,
                       'I would like marketing updates and news from CL Paints by email': 'No',
                       'Demo entry': 'Fictional local test data for the bingo draw'}
            connection.execute(
                'INSERT INTO native_submission (form_id,client_id,token,giveaway_key,email,name,answers_json,terms_snapshot,title_snapshot,created_at,email_sent) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (form[0], client_id, secrets.token_urlsafe(32), f'{form[0]}:{client_id}', email,
                 f'{first_name} Demo', json.dumps(answers), form[2], form[1], now, False)
            )
            created += 1
    total = connection.execute(
        "SELECT COUNT(*) FROM native_submission WHERE form_id=? AND email LIKE 'giveaway-demo-%@example.invalid'", (form[0],)
    ).fetchone()[0]
    print(f'Local giveaway: {form[1]} (form {form[0]}). Added {created} entries; {total} demo entrants available.')
    print(f'Backup: {backup_path.name}')
    connection.close()


if __name__ == '__main__':
    main()
