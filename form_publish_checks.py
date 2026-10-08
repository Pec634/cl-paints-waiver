"""Checks for saved forms before they start accepting responses."""
import json
from datetime import datetime
from native_form_fields import validate_fields
from native_form_features import accessibility_issues
from form_workflows import catalog


def checklist(form, settings, image_exists):
    errors=[];warnings=[]
    if not form.title.strip() or len(form.title)>150:errors.append('Add a form title under 151 characters.')
    if form.kind in ('giveaway','photo') and not form.terms.strip():errors.append('Add the rules or permissions customers will accept.')
    try:
        fields=validate_fields(json.loads(form.fields_json))
        warnings.extend(accessibility_issues(fields))
        sources=[]
        for field in fields:sources.extend([field.get('src','')]+list(field.get('option_images',{}).values()))
        for key in ('packages','extras'):sources.extend(row.get('image','') for row in catalog(settings.get(key,''),key))
        if any(source.startswith('/form-images/') and not image_exists(int(source.rsplit('/',1)[1])) for source in sources):
            errors.append('An uploaded image is missing. Upload it again.')
    except (ValueError,TypeError,KeyError) as error:errors.append(str(error))
    if form.starts_at and form.ends_at and form.ends_at<=form.starts_at:errors.append('Closing time must follow opening time.')
    if form.ends_at and form.ends_at<=datetime.utcnow():errors.append('The closing date has passed. Choose a new date before publishing.')
    if not form.description.strip():warnings.append('Add an introduction so customers know what to expect.')
    return dict(ready=not errors,errors=errors,warnings=warnings)
