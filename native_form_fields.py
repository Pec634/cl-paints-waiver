"""Validate builder definitions and responses shared by native and seasonal forms."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlsplit
from native_form_features import EXTRA_QUESTIONS, EXTRA_DISPLAY, validate_extra, validate_rule, rule_matches, extra_answer

QUESTION_TYPES = {'text', 'textarea', 'number', 'date', 'time', 'email', 'tel', 'url',
                  'checkbox', 'select', 'radio', 'cards', 'multiselect'} | EXTRA_QUESTIONS
DISPLAY_TYPES = {'content', 'heading', 'image'} | EXTRA_DISPLAY
CHOICE_TYPES = {'select', 'radio', 'cards', 'gallery', 'multiselect'}
MAX_BLOCKS = 30
GRID_COLUMNS = 12
MAX_GRID_ROWS = 60


def image_source(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('Use a short HTTPS image link or upload an image.')
    value = value.strip()
    if re.fullmatch(r'/form-images/[1-9][0-9]*', value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Image links must start with https://. You can also upload an image.')
    return value


def validate_fields(data):
    if not isinstance(data, list) or len(data) > MAX_BLOCKS:
        raise ValueError('Use up to thirty questions and content blocks.')
    fields = []
    previous = {}
    occupied = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError('Check the question settings.')
        kind = item.get('type')
        label = item.get('label', '')
        if not isinstance(kind, str) or kind not in QUESTION_TYPES | DISPLAY_TYPES or not isinstance(label, str) or not label.strip() or len(label.strip()) > 150:
            raise ValueError('Give every block a title of up to 150 characters and a listed type.')
        label = label.strip()
        if label in previous:
            raise ValueError('Question and block titles must be unique.')
        required = item.get('required', False)
        if not isinstance(required, bool):
            raise ValueError('Check which answers are required.')
        field = dict(label=label, type=kind, required=required if kind in QUESTION_TYPES else False)
        layout = item.get('layout', {})
        if not isinstance(layout, dict):
            raise ValueError('Check the grid placement for '+label+'.')
        layout = {key: layout.get(key, default) for key, default in [('row', len(fields)+1), ('column', 1), ('width', GRID_COLUMNS)]}
        if any(isinstance(value, bool) or not isinstance(value, int) for value in layout.values()):
            raise ValueError('Grid rows, columns and widths must be whole numbers.')
        if not 1 <= layout['row'] <= MAX_GRID_ROWS or not 1 <= layout['column'] <= GRID_COLUMNS or not 1 <= layout['width'] <= GRID_COLUMNS or layout['column'] + layout['width'] > GRID_COLUMNS + 1:
            raise ValueError('Use rows 1–60 and columns 1–12, keeping each block inside the grid.')
        cells = {(layout['row'], column) for column in range(layout['column'], layout['column']+layout['width'])}
        if occupied.intersection(cells):
            raise ValueError('Blocks overlap in the grid. Move '+label+' to a free space.')
        occupied.update(cells)
        field['layout'] = layout
        for key, limit in [('help', 1000), ('placeholder', 150), ('content', 10000)]:
            value = item.get(key, '')
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'Check the {key} length for {label}.')
            if value: field[key] = value.strip()
        if kind == 'content' and not field.get('content'):
            raise ValueError('Add the read-only text for '+label+'.')
        if kind in CHOICE_TYPES:
            options = item.get('options', [])
            if not isinstance(options, list) or not 1 <= len(options) <= 20 or any(not isinstance(v, str) or not v.strip() or len(v.strip()) > 150 for v in options):
                raise ValueError('Provide one to twenty short choices for '+label+'.')
            options = [v.strip() for v in options]
            if len(set(options)) != len(options):
                raise ValueError('Choices must be different for '+label+'.')
            field['options'] = options
        if kind in ('cards', 'gallery'):
            images = item.get('option_images', {})
            if not isinstance(images, dict) or any(key not in field['options'] for key in images):
                raise ValueError('Card images must belong to listed choices.')
            field['option_images'] = {key: image_source(value) for key, value in images.items() if value}
            if kind == 'gallery' and any(not field['option_images'].get(option) for option in field['options']):
                raise ValueError('Add an image to every gallery choice.')
        if kind in ('radio', 'cards', 'gallery', 'multiselect'):
            columns = item.get('option_columns', 2 if kind == 'cards' else 1)
            spacing = item.get('option_spacing', 'comfortable')
            if isinstance(columns, bool) or not isinstance(columns, int) or columns not in (1, 2, 3) or spacing not in ('compact', 'comfortable', 'spacious'):
                raise ValueError('Choose one to three option columns and a listed spacing style.')
            field['option_columns'] = columns
            field['option_spacing'] = spacing
        if kind == 'image':
            field['src'] = image_source(item.get('src', ''))
            alt = item.get('alt', '')
            if not isinstance(alt, str) or not alt.strip() or len(alt) > 300:
                raise ValueError('Describe the image for people using screen readers (up to 300 characters).')
            field['alt'] = alt.strip()
            if item.get('align', 'center') not in ('left', 'center', 'right') or item.get('size', 'full') not in ('small', 'medium', 'full'):
                raise ValueError('Choose a listed image alignment and size.')
            field['align'] = item.get('align', 'center')
            field['size'] = item.get('size', 'full')
        if kind in ('text', 'textarea', 'email', 'tel', 'url'):
            maximum = item.get('max_length', 2000)
            if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 2000:
                raise ValueError('Answer length must be between 1 and 2000 characters.')
            field['max_length'] = maximum
        if kind == 'number':
            for key in ('min', 'max'):
                if item.get(key) not in (None, ''):
                    try:
                        value = Decimal(str(item[key]))
                        if not value.is_finite(): raise InvalidOperation
                    except (InvalidOperation, ValueError):
                        raise ValueError('Use valid number limits for '+label+'.')
                    field[key] = str(value)
            if 'min' in field and 'max' in field and Decimal(field['min']) > Decimal(field['max']):
                raise ValueError('Minimum must not exceed maximum for '+label+'.')
        validate_extra(field, item, previous)
        for key in ('show_if', 'required_if'):
            rule = validate_rule(item.get(key), previous, layout)
            if rule: field[key] = rule
        previous[label] = field
        fields.append(field)
    return sorted(fields, key=lambda field: (field['layout']['row'], field['layout']['column']))


def parse_fields(submitted):
    structured = submitted.get('fields_json')
    if structured is not None:
        if len(structured) > 400_000: raise ValueError('The form content is too large.')
        try: data = json.loads(structured)
        except (ValueError, TypeError): raise ValueError('Check the question settings and try saving again.')
        return validate_fields(data)
    data = []
    for line in submitted.get('fields', '').splitlines():
        if not line.strip(): continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) not in (3, 4) or parts[2] not in ('required', 'optional'):
            raise ValueError('Use Question | type | required/optional; choice questions also need | comma-separated choices.')
        item = dict(label=parts[0], type=parts[1], required=parts[2] == 'required')
        if parts[1] in CHOICE_TYPES:
            item['options'] = [v.strip() for v in parts[3].split(',') if v.strip()] if len(parts) == 4 else []
        data.append(item)
    return validate_fields(data)


def field_answers(form, submitted, uploads=None):
    result = {}
    fields = json.loads(form.fields_json)
    definitions = {field['label']: field for field in fields}
    for index, field in enumerate(fields):
        condition = field.get('show_if')
        if not rule_matches(condition, result):
            continue
        if field['type'] in DISPLAY_TYPES:
            continue
        required = field['required'] or bool(field.get('required_if') and rule_matches(field['required_if'], result))
        key = 'custom_'+str(index)
        handled, extra = extra_answer(field, submitted.get(key, ''), required, result, definitions, uploads or {})
        if handled:
            result[field['label']] = extra
            continue
        if field['type'] == 'multiselect':
            values = submitted.getlist(key) if hasattr(submitted, 'getlist') else submitted.get(key, [])
            if not isinstance(values, list): values = [values]
            if any(not isinstance(value, str) or value not in field['options'] for value in values):
                raise ValueError('Choose listed options for '+field['label']+'.')
            values = list(dict.fromkeys(values))
            if required and not values: raise ValueError('Complete '+field['label']+'.')
            result[field['label']] = values
            continue
        value = submitted.get(key, '').strip()
        if required and not value: raise ValueError('Complete '+field['label']+'.')
        if len(value) > field.get('max_length', 2000): raise ValueError(field['label']+' is too long.')
        kind = field['type']
        if value and kind == 'number':
            try:
                number = Decimal(value)
                if not number.is_finite(): raise InvalidOperation
            except InvalidOperation: raise ValueError('Enter a valid number for '+field['label']+'.')
            if ('min' in field and number < Decimal(field['min'])) or ('max' in field and number > Decimal(field['max'])):
                raise ValueError('Enter a number within the limits for '+field['label']+'.')
        if value and kind in ('date', 'time'):
            try: datetime.strptime(value, '%Y-%m-%d' if kind == 'date' else '%H:%M')
            except ValueError: raise ValueError('Enter a valid '+kind+' for '+field['label']+'.')
        if value and kind == 'email':
            from email_validator import validate_email, EmailNotValidError
            try: validate_email(value, check_deliverability=False)
            except EmailNotValidError: raise ValueError('Enter a valid email for '+field['label']+'.')
        if value and kind == 'url':
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                raise ValueError('Enter a full website address for '+field['label']+'.')
        if value and kind in ('select', 'radio', 'cards', 'gallery') and value not in field.get('options', []):
            raise ValueError('Choose a listed option for '+field['label']+'.')
        if value and kind == 'checkbox' and value != 'yes': raise ValueError('Confirm '+field['label']+'.')
        result[field['label']] = value
    return result
