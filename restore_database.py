"""Offline SQLite verification/recovery. Never imports or starts the Flask app."""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
from contextlib import closing

def validate(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Backup integrity check failed.')
        tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'booking','waiver','participant','client_account'} <= tables:
            raise ValueError('This is not a complete CL Paints database backup.')

def restore(backup,database):
    backup=Path(backup).resolve()
    database=Path(database).resolve()
    validate(backup)
    if backup==database or not database.is_file():
        raise ValueError('Choose an existing destination database different from the backup.')
    safety=database.with_name(database.name+'.before-restore-'+datetime.utcnow().strftime('%Y%m%d-%H%M%S-%f'))
    with closing(sqlite3.connect(str(database))) as destination, closing(sqlite3.connect(str(safety))) as copy:
        destination.backup(copy)
    with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(str(database))) as destination:
        source.backup(destination)
    validate(database)
    return safety

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Verify a CL Paints SQLite backup. Stop the app before restoring.')
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--database',type=Path)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    try:
        validate(args.backup)
        if args.restore:
            if not args.database: parser.error('--database is required for --restore')
            print('Restored. Previous database saved at',restore(args.backup,args.database))
        else:
            print('Backup is valid. No database changed.')
    except (ValueError,sqlite3.Error,OSError) as error:
        parser.exit(1,str(error)+'\n')
