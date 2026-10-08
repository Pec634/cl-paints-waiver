"""Advanced form definitions, rules and safely computed answers."""
from decimal import Decimal, InvalidOperation, localcontext
from types import SimpleNamespace
import json

EXTRA_QUESTIONS = {'repeat', 'signature', 'file', 'calculation', 'gallery'}
EXTRA_DISPLAY = {'pagebreak'}


def amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or (number and (number.adjusted() > 9 or number.adjusted() < -9)) or abs(number) > Decimal('1000000000'):
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Use a finite amount between -1 billion and 1 billion.')


def validate_rule(rule, previous, layout):
    if not rule: return None
    if not isinstance(rule, dict): raise ValueError('Check the conditional rule settings.')
    if 'rules' not in rule:
        rules = [dict(field=rule.get('field'), operator='equals', value=rule.get('equals'))]
        legacy = True
    else:
        rules = rule['rules']; legacy = False
    mode = rule.get('mode', 'all')
    if mode not in ('all', 'any') or not isinstance(rules, list) or not 1 <= len(rules) <= 8:
        raise ValueError('Use one to eight conditions, matching all or any.')
    result = []
    for row in rules:
        if not isinstance(row, dict) or not isinstance(row.get('field'), str):
            raise ValueError('Select an earlier question for each condition.')
        parent = previous.get(row['field'].strip())
        if not parent or parent['type'] in ('content', 'heading', 'image', 'pagebreak', 'file', 'signature'):
            raise ValueError('Conditions must use an earlier answer field.')
        if (parent['layout']['row'], parent['layout']['column']) >= (layout['row'], layout['column']):
            raise ValueError('Place the condition question before the block it controls in the grid.')
        operator = row.get('operator', 'equals')
        value = row.get('value', '')
        if operator not in ('equals', 'not_equals', 'contains', 'greater', 'less', 'answered') or not isinstance(value, str) or len(value) > 150:
            raise ValueError('Choose a listed condition operator and a short answer.')
        if operator in ('greater', 'less'): amount(value)
        if operator == 'equals' and parent['type'] in ('select', 'radio', 'cards', 'gallery', 'checkbox'):
            choices = ['yes', ''] if parent['type'] == 'checkbox' else parent['options']
            if value not in choices: raise ValueError('Choose a listed answer for the condition.')
        result.append(dict(field=parent['label'], operator=operator, value=value))
    if legacy: return dict(field=result[0]['field'], equals=result[0]['value'])
    return dict(mode=mode, rules=result)


def rule_matches(rule, answers):
    if not rule: return True
    rules = rule.get('rules', [dict(field=rule.get('field'), operator='equals', value=rule.get('equals'))])
    outcomes = []
    for row in rules:
        if row['field'] not in answers:
            outcomes.append(False); continue
        actual = answers[row['field']]; expected = row.get('value', '')
        operator = row.get('operator', 'equals')
        if operator == 'answered': matches = bool(actual)
        elif operator == 'equals': matches = actual == expected
        elif operator == 'not_equals': matches = actual != expected
        elif operator == 'contains': matches = expected in actual if isinstance(actual, (str, list)) else False
        else:
            try: matches = amount(actual) > amount(expected) if operator == 'greater' else amount(actual) < amount(expected)
            except ValueError: matches = False
        outcomes.append(matches)
    return any(outcomes) if rule.get('mode') == 'any' else all(outcomes)


def validate_extra(field, item, previous):
    kind = field['type']
    if kind in ('select', 'radio', 'cards', 'gallery', 'multiselect'):
        values = item.get('option_values', {})
        if not isinstance(values, dict) or any(key not in field['options'] for key in values):
            raise ValueError('Calculation values must belong to listed choices.')
        if values: field['option_values'] = {key: str(amount(value)) for key, value in values.items()}
    if kind == 'checkbox' and item.get('checked_value') not in (None, ''):
        field['checked_value'] = str(amount(item['checked_value']))
    if kind == 'repeat':
        from native_form_fields import validate_fields
        children = item.get('children', [])
        if not isinstance(children, list) or not 1 <= len(children) <= 6 or any(not isinstance(child, dict) or child.get('type') not in ('text', 'textarea', 'number', 'date', 'email', 'tel', 'select', 'checkbox') or child.get('show_if') or child.get('required_if') for child in children):
            raise ValueError('Repeating sections need one to six simple fields.')
        maximum = item.get('max_items', 10)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 20:
            raise ValueError('Repeating sections allow one to twenty rows.')
        field['children'] = validate_fields(children)
        field['max_items'] = maximum
    if kind == 'file':
        allowed = item.get('file_types', ['images', 'pdf'])
        maximum = item.get('max_files', 3)
        if not isinstance(allowed, list) or not allowed or any(value not in ('images', 'pdf') for value in allowed) or isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 6:
            raise ValueError('Uploads allow images and/or PDF, with one to six files.')
        field['file_types'] = list(dict.fromkeys(allowed)); field['max_files'] = maximum
    if kind == 'calculation':
        settings = item.get('calculation', {})
        if not isinstance(settings, dict): raise ValueError('Check the calculation settings.')
        sources = settings.get('sources', [])
        if isinstance(sources,list): sources=[source.strip() if isinstance(source,str) else source for source in sources]
        operation = settings.get('operation', 'sum')
        precision = settings.get('precision', 2)
        prefix = settings.get('prefix', '')
        if operation not in ('sum', 'product', 'count', 'percentage') or not isinstance(sources, list) or not 1 <= len(sources) <= 8 or any(not isinstance(source, str) or source not in previous or previous[source]['type'] not in ('number', 'select', 'radio', 'cards', 'gallery', 'multiselect', 'checkbox', 'repeat', 'calculation') for source in sources):
            raise ValueError('Calculations need one to eight earlier number, choice, repeating or calculated fields.')
        if any((previous[source]['layout']['row'], previous[source]['layout']['column']) >= (field['layout']['row'], field['layout']['column']) for source in sources):
            raise ValueError('Place calculation source fields before their result in the grid.')
        if operation != 'count' and any(previous[source]['type']=='repeat' for source in sources):
            raise ValueError('Use the count operation for repeating sections.')
        if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 4 or not isinstance(prefix, str) or len(prefix) > 12:
            raise ValueError('Calculation precision is 0–4 decimal places; the prefix is up to 12 characters.')
        field['required'] = False
        field['calculation'] = dict(operation=operation, sources=list(dict.fromkeys(sources)), base=str(amount(settings.get('base', 0))), precision=precision, prefix=prefix)


def calculate(field, answers, definitions):
    settings = field['calculation']
    values = []
    for label in settings['sources']:
        source = definitions[label]; value = answers.get(label, '')
        if settings['operation'] == 'count':
            values.append(Decimal(len(value) if isinstance(value, list) else (1 if value else 0)))
        elif source['type'] in ('select', 'radio', 'cards', 'gallery', 'multiselect'):
            chosen = value if isinstance(value, list) else [value]
            values.append(sum((amount(source.get('option_values', {}).get(option, 0)) for option in chosen), Decimal(0)))
        elif source['type'] == 'checkbox': values.append(amount(source.get('checked_value', 0)) if value == 'yes' else Decimal(0))
        elif source['type'] == 'repeat': raise ValueError('Use the count operation for repeating sections.')
        else: values.append(amount(value or 0))
    base = amount(settings['base'])
    with localcontext() as context:
        context.prec = 40
        if settings['operation'] in ('sum', 'count'): result = base + sum(values, Decimal(0))
        elif settings['operation'] == 'product':
            result = base
            for value in values: result *= value
        else: result = sum(values, Decimal(0)) * base / Decimal(100)
        if abs(result) > Decimal('1000000000000'): raise ValueError('The calculated amount is too large.')
        return str(result.quantize(Decimal(1).scaleb(-settings['precision'])))


def signature(value, required):
    if not value and not required: return ''
    if not isinstance(value, str) or len(value) > 100_000: raise ValueError('The signature is too large.')
    try: data = json.loads(value)
    except ValueError: raise ValueError('Draw your signature and type your full name.')
    if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not 1 <= len(data['name'].strip()) <= 150 or not isinstance(data.get('strokes'), list) or not 1 <= len(data['strokes']) <= 50:
        raise ValueError('Draw your signature and type your full name.')
    count = 0; strokes = []
    for stroke in data['strokes']:
        if not isinstance(stroke, list) or len(stroke) < 2: raise ValueError('Draw a complete signature.')
        clean = []
        for point in stroke:
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in point):
                raise ValueError('Check the signature drawing.')
            clean.append([round(v, 5) for v in point]); count += 1
            if count > 4000: raise ValueError('The signature contains too many points. Clear it and sign again.')
        strokes.append(clean)
    return dict(name=data['name'].strip(), strokes=strokes)


def extra_answer(field, raw, required, answers, definitions, uploads):
    kind = field['type']
    if kind == 'calculation': return True, calculate(field, answers, definitions)
    if kind == 'signature': return True, signature(raw, required)
    if kind == 'file':
        names = uploads.get(field['label'], [])
        if required and not names: raise ValueError('Upload a file for '+field['label']+'.')
        if len(names) > field['max_files']: raise ValueError('Too many files for '+field['label']+'.')
        return True, names
    if kind == 'repeat':
        if len(raw) > 100_000: raise ValueError('The repeating section is too large.')
        try: rows = json.loads(raw or '[]')
        except ValueError: raise ValueError('Check the rows in '+field['label']+'.')
        if not isinstance(rows, list) or len(rows) > field['max_items'] or (required and not rows):
            raise ValueError('Add '+('one to ' if required else 'up to ')+str(field['max_items'])+' rows for '+field['label']+'.')
        from native_form_fields import field_answers
        result = []
        child_form = SimpleNamespace(fields_json=json.dumps(field['children']))
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(value, str) for value in row.values()): raise ValueError('Check the repeating row answers.')
            payload = {'custom_'+str(index): row.get(child['label'], '') for index, child in enumerate(field['children'])}
            result.append(field_answers(child_form, payload))
        return True, result
    return False, None


def signature_path(value):
    if not isinstance(value, dict) or 'strokes' not in value: return ''
    return ' '.join(('M' if index == 0 else 'L')+f'{point[0]*600:.2f},{point[1]*180:.2f}' for stroke in value['strokes'] for index, point in enumerate(stroke))


def accessibility_issues(fields):
    issues = []
    seen = set()
    for field in fields:
        label = field.get('label', '').strip()
        if not label or label in seen: issues.append('Give every block a unique, descriptive label.')
        seen.add(label)
        if field.get('type') == 'image' and not field.get('alt', '').strip(): issues.append('Add an image description for '+(label or 'the image')+'.')
        if field.get('layout', {}).get('width', 12) < 3 and field.get('type') not in ('heading', 'image'): issues.append('Widen '+label+' so its label and answer fit comfortably.')
        if label.lower() in ('question', 'field', 'untitled', 'name here'): issues.append('Make the label more specific: '+label+'.')
    return list(dict.fromkeys(issues))
