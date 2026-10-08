"""Local PDF text extraction; every inferred record must be reviewed."""
from io import BytesIO
import re

ALIASES = {
    'email': ('email', 'email address', 'e-mail'),
    'first_name': ('first name', 'given name', 'firstname'),
    'last_name': ('last name', 'surname', 'family name', 'lastname'),
    'full_name': ('full name', 'client name', 'customer name', 'name'),
    'phone': ('phone', 'telephone', 'mobile', 'phone number', 'contact number'),
    'address': ('address', 'client address', 'billing address', 'home address'),
    'address_line_2': ('address line 2',),
    'address_line_3': ('address line 3',),
    'city': ('city', 'town'),
    'county': ('county', 'region'),
    'postcode': ('postcode', 'postal code', 'zip code'),
    'country': ('country',),
    'date_of_birth': ('date of birth', 'dob', 'birth date'),
    'event_date': ('event date', 'booking date', 'date'),
    'start_time': ('start time', 'starts', 'start'),
    'finish_time': ('finish time', 'end time', 'finish', 'ends'),
    'event_address': ('event address', 'venue address', 'event venue', 'venue'),
    'event_type': ('event type', 'event name', 'occasion'),
    'status': ('status', 'booking status'),
    'publicity_type': ('publicity type', 'event setting', 'public/private'),
    'client_type': ('client type',),
    'theme': ('theme',),
    'total_event_cost': ('total event cost', 'event estimate', 'event cost', 'estimated event cost'),
    'travel_charge': ('travel charge', 'travel cost'),
    'submitted_at': ('submitted at', 'submission date', 'original submission date'),
    'signature': ('signature', 'original signature'),
    'source_reference': ('source reference', 'booking reference', 'reference'),
}


def normalise(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


LOOKUP = {normalise(alias): key for key, aliases in ALIASES.items() for alias in (key, *aliases)}


def clean_record(record):
    record = dict(record)
    name = record.pop('full_name', '').strip().split()
    if name:
        record.setdefault('first_name', ' '.join(name[:-1]) if len(name) > 1 else name[0])
        record.setdefault('last_name', name[-1] if len(name) > 1 else '')
    return record


def text_records(text):
    lines = text.splitlines()
    # Only treat a table as records when its headers are recognisable and include email.
    for index, line in enumerate(lines):
        columns = [value.strip() for value in re.split(r'\s{2,}|\t+|\s*\|\s*', line.strip())]
        keys = [LOOKUP.get(normalise(value)) for value in columns]
        if len(columns) >= 3 and 'email' in keys and all(keys) and len(set(keys)) == len(keys):
            records = []
            for candidate in lines[index + 1:]:
                values = [value.strip() for value in re.split(r'\s{2,}|\t+|\s*\|\s*', candidate.strip())]
                if len(values) == len(keys):
                    records.append(clean_record(dict(zip(keys, values))))
            if records:
                return records
    labels = sorted({alias for key, aliases in ALIASES.items() for alias in (key.replace('_', ' '), *aliases)}, key=len, reverse=True)
    pattern = re.compile(r'(?<!\w)(' + '|'.join(re.escape(label) for label in labels) + r')\s*[:=]\s*', re.I)
    matches = list(pattern.finditer(text))
    records, current = [], {}
    for index, match in enumerate(matches):
        key = LOOKUP[normalise(match[1])]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        # Addresses may wrap across lines. Other values end at their first line.
        value = '\n'.join(line.strip() for line in value.splitlines() if line.strip()) if key in ('address', 'event_address') else (value.splitlines()[0] if value else '')
        if key in current:
            records.append(clean_record(current)); current = {}
        current[key] = value[:4000]
    if current:
        records.append(clean_record(current))
    return records


def read_pdf(content, fields):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ValueError('Unlock the PDF before uploading it. Password-protected PDFs are not imported.')
        if not 1 <= len(reader.pages) <= 20:
            raise ValueError('Use a PDF with between 1 and 20 pages.')
        sources, records, decoded_bytes = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            stream = page.get_contents()
            decoded_bytes += len(stream.get_data()) if stream else 0
            if decoded_bytes > 10_000_000:
                raise ValueError('This PDF has too much page content. Split it into smaller documents.')
            text = (page.extract_text(extraction_mode='layout') or '') if stream is not None else ''
            if sum(len(source['text']) for source in sources) + len(text) > 200_000:
                raise ValueError('This PDF contains too much text. Split it into smaller documents.')
            sources.append(dict(page=number, text=text))
            if text.strip():
                found = text_records(text)
                records.extend(found or [{}])
        # Filled form fields can be usable even when their values are absent from page text.
        form_fields = reader.get_fields() or {}
        if len(form_fields) > 200:
            raise ValueError('This PDF has too many form fields. Export it to CSV instead.')
        form_record = {LOOKUP[normalise(key)]: str(value.get('/V', '')) for key, value in form_fields.items() if normalise(key) in LOOKUP}
        if form_record and len(records) <= 1:
            records = [clean_record(dict(form_record, **(records[0] if records else {})))]
        if not records:
            raise ValueError('No selectable text or readable form fields were found. This may be a scanned PDF. Run OCR (text recognition), save a searchable PDF and upload it again.')
        if len(records) > 500:
            raise ValueError('Import no more than 500 records at a time.')
        headers = [key for key, _, _ in fields]
        return dict(headers=headers, rows=[[record.get(key, '') for key in headers] for record in records],
                    format='pdf', sources=sources)
    except (PdfReadError, OSError, KeyError, TypeError, NotImplementedError):
        raise ValueError('This PDF could not be read. Export a fresh, unlocked PDF and try again.') from None
