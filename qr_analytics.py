"""Named QR links and anonymous scan totals."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import Counter
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError


def define_models(db):
    class QRCode(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        token = db.Column(db.String(40), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(18))
        name = db.Column(db.String(120), nullable=False)
        destination = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    class QRScan(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        code_id = db.Column(db.Integer, db.ForeignKey('qr_code.id'), nullable=False, index=True)
        scanned_at = db.Column(db.DateTime, nullable=False, index=True, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    return QRCode, QRScan


def define_metadata(db):
    class QRMetadata(db.Model):
        code_id = db.Column(db.Integer, db.ForeignKey('qr_code.id'), primary_key=True)
        campaign = db.Column(db.String(120), nullable=False, default='')
        archived = db.Column(db.Boolean, nullable=False, default=False)
    return QRMetadata


def register(app, db, models, admin_required):
    Code, Scan = models
    Meta = app.extensions['qr_metadata_model']

    @app.post('/admin/reports/qr-codes/<int:code_id>/organise')
    @admin_required
    def organise_qr_code(code_id):
        if not session.get('qr_manage_csrf') or not secrets.compare_digest(
                request.form.get('csrf_token', ''), session['qr_manage_csrf']):
            abort(400, 'Reload QR analytics and try again.')
        code = db.session.get(Code, code_id)
        if code is None:
            abort(404)
        campaign = request.form.get('campaign', '').strip()
        if len(campaign) > 120 or request.form.get('archived') not in ('0', '1'):
            abort(400, 'Use a campaign label up to 120 characters and a valid archive state.')
        try:
            meta = db.session.get(Meta, code_id)
            if meta is None:
                meta = Meta(code_id=code_id)
                db.session.add(meta)
            meta.campaign = campaign
            meta.archived = request.form['archived'] == '1'
            db.session.commit()
            flash('QR code organisation saved. Printed links remain active.', 'success')
        except SQLAlchemyError:
            db.session.rollback()
            flash('QR code could not be updated. Please try again.', 'error')
        return redirect(url_for('admin_qr_analytics', state='archived' if request.form['archived'] == '1' else 'active'))

    @app.get('/admin/reports/qr-codes/<int:code_id>/sign')
    @admin_required
    def qr_print_sign(code_id):
        code = db.session.get(Code, code_id)
        if code is None:
            abort(404)
        return render_template('admin_qr_sign.html', code=code)

    @app.route('/q/<token>')
    def qr_redirect(token):
        code = Code.query.filter_by(token=token).first_or_404()
        agent = request.headers.get('User-Agent', '').lower()
        if request.method == 'GET' and not session.get('admin_authenticated') and not any(
                word in agent for word in ('bot', 'crawler', 'spider', 'headless', 'preview', 'uptime', 'monitor')):
            try:
                db.session.add(Scan(code_id=code.id))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.warning('QR scan could not be recorded')
        response = redirect(code.destination)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.route('/admin/reports/qr-codes')
    @admin_required
    def admin_qr_analytics():
        today = datetime.now(ZoneInfo('Europe/London')).date()
        try:
            start = datetime.strptime(request.args.get('start', (today - timedelta(days=29)).isoformat()), '%Y-%m-%d').date()
            end = datetime.strptime(request.args.get('end', today.isoformat()), '%Y-%m-%d').date()
            if start > end or (end - start).days > 3660 or end.year == 9999:
                raise ValueError()
        except ValueError:
            abort(400, 'Choose a valid date range of up to ten years.')
        london = ZoneInfo('Europe/London')
        lower = datetime.combine(start, datetime.min.time(), london).astimezone(timezone.utc).replace(tzinfo=None)
        upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), london).astimezone(timezone.utc).replace(tzinfo=None)
        scans = Scan.query.filter(Scan.scanned_at >= lower, Scan.scanned_at < upper).all()
        counts = Counter(scan.code_id for scan in scans)
        days = Counter(scan.scanned_at.replace(tzinfo=timezone.utc).astimezone(london).date() for scan in scans)
        from sqlalchemy import or_
        query = request.args.get('q', '').strip()[:120]
        state = request.args.get('state', 'active')
        if state not in ('active', 'archived', 'all'):
            abort(400, 'Choose a valid QR code list.')
        code_query = Code.query.outerjoin(Meta, Meta.code_id == Code.id)
        if state == 'active':
            code_query = code_query.filter(or_(Meta.archived.is_(False), Meta.code_id.is_(None)))
        elif state == 'archived':
            code_query = code_query.filter(Meta.archived.is_(True))
        if query:
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            code_query = code_query.filter(or_(Code.name.ilike(pattern, escape='\\'), Code.destination.ilike(pattern, escape='\\'), Meta.campaign.ilike(pattern, escape='\\')))
        pagination = code_query.order_by(Code.created_at.desc(), Code.id.desc()).paginate(per_page=12, error_out=False)
        metadata = {meta.code_id: meta for meta in Meta.query.filter(Meta.code_id.in_([code.id for code in pagination.items])).all()}
        peak = max(days.values(), default=1)
        return render_template('admin_qr_analytics.html', codes=pagination.items, counts=counts, total=len(scans),
                               code_count=Code.query.count(), pagination=pagination, metadata=metadata, query=query, state=state,
                               qr_csrf=session.setdefault('qr_manage_csrf', secrets.token_urlsafe(32)),
                               days=sorted(days.items()), peak=peak, start=start, end=end)
