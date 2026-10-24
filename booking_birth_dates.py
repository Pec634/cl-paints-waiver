"""Optional business contact birth dates, including existing database schemas."""
import re
from datetime import datetime
from sqlalchemy import inspect


def client_kind(value):
    text = str(value).strip().lower()
    if text in ('business', 'company', 'organisation', 'organization'):
        return 'business'
    if text in ('individual', 'private individual', 'private'):
        return 'individual'
    return text


def birth_date(value, kind):
    text = str(value or '').strip()
    if text in ('', '00/00/00', '00/00/0000', '0000-00-00'):
        if client_kind(kind) == 'business':
            return None
        raise ValueError('Date of birth is required for private individuals. Enter the correct date or choose Business for a business booking.')
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.strptime(text, '%d/%m/%Y').date()
        except ValueError:
            raise ValueError('Enter a valid date of birth (DD/MM/YYYY or YYYY-MM-DD).')


def ensure_nullable_dob(db):
    column = next(item for item in inspect(db.engine).get_columns('booking') if item['name'] == 'date_of_birth')
    if column['nullable']:
        return
    if db.engine.dialect.name == 'postgresql':
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE booking ALTER COLUMN date_of_birth DROP NOT NULL')
        return
    if db.engine.dialect.name != 'sqlite':
        raise RuntimeError('Unsupported booking birth date schema migration.')
    # SQLite requires a table rebuild to remove NOT NULL. Preserve the original
    # table definition, data, indexes and triggers, and keep incoming FKs intact.
    connection = db.engine.raw_connection()
    cursor = connection.cursor()
    foreign_keys = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
    try:
        cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute('BEGIN IMMEDIATE')
        definition = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='booking'").fetchone()[0]
        definition, count = re.subn(r'(?i)(\bdate_of_birth\b\s+DATE)\s+NOT\s+NULL', r'\1', definition)
        if count != 1:
            raise RuntimeError('Could not safely migrate booking date of birth.')
        definition = re.sub(r'(?i)^CREATE TABLE\s+["`\[]?booking["`\]]?', 'CREATE TABLE booking_dob_migration', definition, count=1)
        objects = cursor.execute("SELECT sql FROM sqlite_master WHERE tbl_name='booking' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        columns = ', '.join('"' + item[1].replace('"', '""') + '"' for item in cursor.execute('PRAGMA table_info(booking)').fetchall())
        cursor.execute(definition)
        cursor.execute(f'INSERT INTO booking_dob_migration ({columns}) SELECT {columns} FROM booking')
        cursor.execute('DROP TABLE booking')
        cursor.execute('ALTER TABLE booking_dob_migration RENAME TO booking')
        for (statement,) in objects:
            cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.execute(f'PRAGMA foreign_keys={int(foreign_keys)}')
        cursor.close()
        connection.close()
