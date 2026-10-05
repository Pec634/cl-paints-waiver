"""External business forms and time-limited hourly booking offers."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for

FORMS = dict(giveaway='https://www.cognitoforms.com/CLPaints/Give-away',
             photo='https://www.cognitoforms.com/CLPaints/Photo',
             incident='https://www.cognitoforms.com/CLPaints/IncidentForm',
             collision='https://www.cognitoforms.com/CLPaints/RoadTrafficCollision',
             halloween='https://www.cognitoforms.com/CLPaints/Halloween')


def define_models(db):
    class SeasonalBookingForm(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(150), nullable=False)
        description = db.Column(db.String(500), nullable=False, default='')
        url = db.Column(db.Text, nullable=False)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
    class HourlyPromotion(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(150), nullable=False)
        reduction = db.Column(db.Numeric(10, 2), nullable=False)
        starts_at = db.Column(db.DateTime, nullable=False)
        ends_at = db.Column(db.DateTime, nullable=False)
        enabled = db.Column(db.Boolean, nullable=False, default=True)
    return SeasonalBookingForm, HourlyPromotion


def active_discount(Promotion, base_rate, now=None):
    now = now or datetime.utcnow()
    offer = Promotion.query.filter(Promotion.enabled.is_(True), Promotion.starts_at <= now, Promotion.ends_at > now).order_by(Promotion.reduction.desc(), Promotion.id).first()
    if not offer: return None
    saving = min(Decimal(base_rate), Decimal(offer.reduction))
    return dict(id=offer.id, title=offer.title, saving=str(saving), original_rate=str(base_rate),
                hourly_rate=str((Decimal(base_rate)-saving).quantize(Decimal('0.01'))))


def register(app, db, models, admin_required, settings):
    Form, Promotion = models
    app.extensions['active_hourly_discount'] = lambda rate: active_discount(Promotion, rate)

    @app.context_processor
    def forms_context():
        return dict(business_forms=FORMS, seasonal_forms=Form.query.filter_by(enabled=True).order_by(Form.id).all(),
                    booking_offer=active_discount(Promotion, settings()['hourly_rate']))

    def uk_datetime(value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo: raise ValueError('Use local UK dates and times.')
        return parsed.replace(tzinfo=ZoneInfo('Europe/London')).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)

    @app.route('/admin/forms-offers', methods=['GET', 'POST'])
    @admin_required
    def forms_offers():
        token = session.setdefault('client_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not secrets.compare_digest(token, request.form.get('csrf_token', '')): abort(400)
            action = request.form.get('action')
            try:
                if action == 'form':
                    title = request.form.get('title','').strip(); description = request.form.get('description','').strip()
                    link = request.form.get('url','').strip(); parsed=urlparse(link)
                    if not title or len(title)>150 or len(description)>500 or len(link)>2000 or parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password:
                        raise ValueError('Provide a title, description up to 500 characters and a valid HTTPS form link.')
                    db.session.add(Form(title=title,description=description,url=link))
                elif action == 'offer':
                    title = request.form.get('title','').strip()
                    reduction=Decimal(request.form.get('reduction',''))
                    start=uk_datetime(request.form.get('starts_at','')); end=uk_datetime(request.form.get('ends_at',''))
                    if not title or len(title)>150 or not reduction.is_finite() or reduction<=0 or reduction>Decimal(settings()['hourly_rate']) or reduction!=reduction.quantize(Decimal('.01')) or end<=start:
                        raise ValueError('Enter a title, a positive hourly saving no greater than the normal rate, and an end after the start.')
                    db.session.add(Promotion(title=title,reduction=reduction,starts_at=start,ends_at=end))
                elif action in ('toggle_form','toggle_offer'):
                    model=Form if action=='toggle_form' else Promotion
                    item=db.get_or_404(model,request.form.get('id',type=int)); item.enabled=not item.enabled
                else: abort(400)
                db.session.commit(); flash('Saved.', 'success')
            except (ValueError, InvalidOperation, TypeError) as exc:
                db.session.rollback(); flash(str(exc) if isinstance(exc, ValueError) else 'Check the dates and hourly saving.', 'error')
            return redirect(url_for('forms_offers'))
        def local(value): return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/London')).strftime('%d/%m/%Y %H:%M')
        return render_template('admin_forms_offers.html', forms=Form.query.order_by(Form.id.desc()).all(),
                               offers=Promotion.query.order_by(Promotion.starts_at.desc()).all(), csrf=token, local=local)
