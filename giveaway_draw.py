"""Persist one automatic giveaway result and portal notices in one transaction."""
from datetime import datetime, timedelta
import secrets
import math
from flask import abort, jsonify, request, url_for, redirect, flash
from sqlalchemy.exc import IntegrityError


def define_model(db):
    class GiveawayDraw(db.Model):
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), nullable=False)
        account_number = db.Column(db.String(100), nullable=False)
        title = db.Column(db.String(150), nullable=False)
        drawn_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        entrant_count = db.Column(db.Integer, nullable=False)
        @property
        def claim_deadline(self):
            return self.drawn_at + timedelta(days=14)
        @property
        def claimed_at(self):
            record = db.session.get(db._giveaway_round, (self.form_id, self.client_id))
            return record.claimed_at if record else None
        @property
        def can_redraw(self):
            return not self.claimed_at and datetime.utcnow() >= self.claim_deadline
        @property
        def days_remaining(self):
            return max(0, math.ceil((self.claim_deadline - datetime.utcnow()).total_seconds() / 86400))
    class GiveawayRound(db.Model):
        form_id = db.Column(db.Integer, db.ForeignKey('native_form.id'), primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id'), primary_key=True)
        drawn_at = db.Column(db.DateTime, nullable=False)
        claimed_at = db.Column(db.DateTime)
    db._giveaway_round = GiveawayRound
    return GiveawayDraw


def register(app, db, Form, Submission, Account, admin_required, check, current_client):
    Draw = db._giveaway_draw

    @app.context_processor
    def giveaway_results():
        account = current_client() if request.endpoint == 'client.dashboard' else None
        return {'giveaway_results': Draw.query.order_by(Draw.drawn_at.desc()).limit(12).all(),
                'dashboard_giveaway_wins': Draw.query.filter_by(client_id=account.id).order_by(Draw.drawn_at.desc()).all() if account else []}

    @app.post('/admin/native-forms/<int:form_id>/draw')
    @admin_required
    def giveaway_draw(form_id):
        check()
        form = db.get_or_404(Form, form_id)
        if form.kind != 'giveaway':
            abort(400)
        existing = Draw.query.filter_by(form_id=form_id).with_for_update().first()
        if existing and (not existing.can_redraw or request.form.get('draw_version') != existing.drawn_at.isoformat()):
            return jsonify(number=existing.account_number, saved=True)
        accounts = Account.query.join(Submission, Submission.client_id == Account.id).filter(Submission.form_id == form_id).distinct().order_by(Account.id).all()
        previous_ids = {item.client_id for item in db._giveaway_round.query.filter_by(form_id=form_id).all()}
        if existing:
            previous_ids.add(existing.client_id)
            if not db.session.get(db._giveaway_round, (form_id, existing.client_id)):
                db.session.add(db._giveaway_round(form_id=form_id, client_id=existing.client_id, drawn_at=existing.drawn_at))
        eligible = [account for account in accounts if account.id not in previous_ids]
        if not eligible:
            abort(400, 'No eligible clients have entered this giveaway.')
        winner = secrets.choice(eligible)
        draw = existing or Draw(form_id=form.id)
        draw.client_id = winner.id
        draw.account_number = winner.account_number
        draw.title = form.title
        draw.drawn_at = datetime.utcnow()
        draw.entrant_count = len(eligible)
        db.session.add(draw)
        db.session.add(db._giveaway_round(form_id=form.id, client_id=winner.id, drawn_at=draw.drawn_at))
        # Closing entries and saving notices happen atomically with the winner.
        form.enabled = False
        Notice = app.extensions['client_notification_model']
        notices = []
        for account in accounts:
            details = f'{form.title} has been drawn. Winning client account: {winner.account_number}. '
            details += (f'Congratulations! You have won. Contact CL Paints to claim within 14 days, by {draw.claim_deadline.strftime("%d/%m/%Y %H:%M")} UTC. If you do not respond by then, another winner may be drawn.' if account.id == winner.id
                        else 'Thank you for entering. Visit your Rewards page for the result and future giveaways.')
            notice = Notice(email=account.email, kind='reward', reference=f'Giveaway-{form.id}', details=details)
            db.session.add(notice)
            notices.append((account.first_name, notice))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = db.session.get(Draw, form_id)
            if existing:
                return jsonify(number=existing.account_number, saved=True)
            raise
        for name, notice in notices:
            # Demo accounts are local fixtures and must never receive email.
            if notice.email.endswith('@example.invalid'):
                continue
            try:
                app.extensions['client_notice_deliver'](notice, name, url_for('client.rewards', _external=True))
            except Exception:
                db.session.rollback()
                app.logger.exception('Giveaway email failed; saved portal notice remains available')
        return jsonify(number=draw.account_number, saved=True)

    @app.post('/admin/native-forms/<int:form_id>/draw/claim')
    @admin_required
    def giveaway_claim(form_id):
        check()
        draw = Draw.query.filter_by(form_id=form_id).with_for_update().first_or_404()
        if request.form.get('draw_version') != draw.drawn_at.isoformat():
            abort(409, 'The winner has changed. Refresh before recording a claim.')
        if draw.can_redraw:
            abort(409, 'The 14-day claim deadline has passed.')
        record = db.session.get(db._giveaway_round, (form_id, draw.client_id))
        if not record:
            record = db._giveaway_round(form_id=form_id, client_id=draw.client_id, drawn_at=draw.drawn_at)
            db.session.add(record)
        if not record.claimed_at:
            record.claimed_at = datetime.utcnow()
        db.session.commit()
        flash('Prize claim recorded. Another winner cannot be drawn.', 'success')
        return redirect(url_for('native_form_entries', form_id=form_id))

    @app.post('/client/giveaways/<int:form_id>/claim')
    def client_giveaway_claim(form_id):
        account = current_client()
        if not account:
            abort(401)
        check()
        draw = Draw.query.filter_by(form_id=form_id).with_for_update().first_or_404()
        if draw.client_id != account.id:
            abort(403)
        if draw.can_redraw:
            abort(409, 'The 14-day claim deadline has passed.')
        record = db.session.get(db._giveaway_round, (form_id, account.id))
        if not record:
            record = db._giveaway_round(form_id=form_id, client_id=account.id, drawn_at=draw.drawn_at)
            db.session.add(record)
        if not record.claimed_at:
            record.claimed_at = datetime.utcnow()
        db.session.commit()
        flash('Your prize is claimed! Contact CL Paints to arrange your booking.', 'success')
        return redirect(url_for('client.rewards'))
