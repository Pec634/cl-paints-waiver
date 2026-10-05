"""Stable display references derived from retained record IDs and creation dates."""
import re
from datetime import datetime

def record_reference(kind, record_id, created):
    if record_id is None or created is None:
        return ''
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    number = record_id
    code = ''
    while number:
        number, remainder = divmod(number, 36)
        code = alphabet[remainder] + code
    return f'{created:%d/%m/%Y} - {kind} - {code.zfill(4)}'

def reference_record_id(reference, kind):
    match = re.fullmatch(r'(\d{2}/\d{2}/\d{4}) - ' + re.escape(kind) + r' - ([0-9A-Z]{4,})', reference)
    if not match:
        return None
    try:
        datetime.strptime(match[1], '%d/%m/%Y')
        return int(match[2], 36)
    except ValueError:
        return None
