from decimal import Decimal, InvalidOperation
from flask import request, session, render_template, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import SQLAlchemyError
import secrets

DEFAULTS = dict(business_name='CL Paints', contact_email='info@clpaints.com', phone='',
                website='https://www.clpaints.com', hourly_rate='45.00', minimum_hours='2',
                max_event_dates='10', free_miles='10', mile_rate='1.00', travel_cap='50.00',
                recovery_email='')


def read_settings(db, Setting, recovery_default=''):
    values = dict(DEFAULTS, recovery_email=recovery_default)
    values.update({row.key: row.value for row in Setting.query.all() if row.key in DEFAULTS})
    return values


def register_settings(app, db, Setting, Credential, Reset, admin_required, fallback_password, recovery_default):
    def get_settings():
        return read_settings(db, Setting, recovery_default)
    @app.context_processor
    def settings_context():
        return {'business_settings': get_settings()}

    @app.route('/admin/settings', methods=['GET', 'POST'])
    @admin_required
    def admin_settings():
        token = session.setdefault('settings_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf_token', ''), token):
                return 'Your session expired. Reload Settings and try again.', 400
            try:
                section = request.form.get('section')
                values = {}
                if section == 'business':
                    for key in ['business_name', 'contact_email', 'phone', 'website']:
                        values[key] = request.form.get(key, '').strip()
                        if len(values[key]) > 255:
                            raise ValueError('Keep business details under 256 characters.')
                    if not values['business_name']:
                        raise ValueError('Enter a business name.')
                    from email_validator import validate_email
                    values['contact_email'] = validate_email(values['contact_email'], check_deliverability=False).normalized
                    if values['website'] and not values['website'].startswith(('https://', 'http://')):
                        raise ValueError('The website must begin with https:// or http://.')
                elif section in {'booking', 'travel'}:
                    limits = {'hourly_rate': ('0.01', '10000'), 'minimum_hours': ('0.5', '24'),
                              'max_event_dates': ('1', '10')} if section == 'booking' else {
                                  'free_miles': ('0', '10000'), 'mile_rate': ('0', '1000'), 'travel_cap': ('0', '10000')}
                    for key, (minimum, maximum) in limits.items():
                        number = Decimal(request.form.get(key, ''))
                        if not number.is_finite() or not Decimal(minimum) <= number <= Decimal(maximum):
                            raise ValueError(f'Enter {key.replace("_", " ")} between {minimum} and {maximum}.')
                        if key == 'max_event_dates' and number != number.to_integral_value():
                            raise ValueError('Maximum event dates must be a whole number.')
                        if number != number.quantize(Decimal('0.01')):
                            raise ValueError('Use no more than two decimal places.')
                        values[key] = str(number)
                elif section == 'account':
                    credential = Credential.query.order_by(Credential.id.asc()).first()
                    current = request.form.get('current_password', '')
                    valid = check_password_hash(credential.password_hash, current) if credential else bool(fallback_password) and secrets.compare_digest(current, fallback_password)
                    if not valid:
                        raise ValueError('Your current password is incorrect.')
                    recovery = request.form.get('recovery_email', '').strip()
                    if recovery:
                        from email_validator import validate_email
                        recovery = validate_email(recovery, check_deliverability=False).normalized
                    values['recovery_email'] = recovery
                    password = request.form.get('new_password', '')
                    if password:
                        if len(password) < 12 or len(password) > 128:
                            raise ValueError('Use a new password between 12 and 128 characters.')
                        if password != request.form.get('confirm_password', ''):
                            raise ValueError('The new passwords do not match.')
                        if credential is None:
                            credential = Credential(password_hash=generate_password_hash(password))
                            db.session.add(credential)
                        else:
                            credential.password_hash = generate_password_hash(password)
                    # Existing reset links must not survive account changes.
                    Reset.query.delete()
                else:
                    raise ValueError('Choose a valid settings section.')
                for key, value in values.items():
                    row = db.session.get(Setting, key)
                    if row is None:
                        db.session.add(Setting(key=key, value=value))
                    else:
                        row.value = value
                db.session.commit()
                flash('Settings saved.', 'success')
                return redirect(url_for('admin_settings'))
            except (ValueError, InvalidOperation) as error:
                db.session.rollback()
                flash(str(error) if not isinstance(error, InvalidOperation) else 'Enter valid numbers for all fields.', 'error')
            except SQLAlchemyError:
                db.session.rollback()
                flash('Settings could not be saved. Please try again.', 'error')
        return render_template('admin_settings.html', settings=get_settings(), csrf_token=token)
    return get_settings
