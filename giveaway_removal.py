"""Audited giveaway withdrawals preserve the entry and client account."""
from datetime import datetime
import os
from flask import abort, flash, redirect, render_template, request, url_for


def define_model(db):
    class GiveawayRemoval(db.Model):
        submission_id = db.Column(db.Integer, db.ForeignKey('native_submission.id'), primary_key=True)
        removed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        removed_by = db.Column(db.String(255), nullable=False)
        reason = db.Column(db.Text, nullable=False)
    db._giveaway_removal = GiveawayRemoval


def eligible_accounts(db, Account, Submission, form_id):
    removed = db.session.query(db._giveaway_removal.submission_id)
    return Account.query.join(Submission, Submission.client_id == Account.id).filter(
        Submission.form_id == form_id, ~Submission.id.in_(removed)).distinct()


def register(app, db, Form, Submission, Account, admin_required, check, csrf):
    Removal = db._giveaway_removal

    @app.context_processor
    def context():
        return dict(giveaway_entry_removal=lambda entry: db.session.get(Removal, entry.id))

    @app.route('/admin/native-forms/<int:form_id>/remove-entrants', methods=['GET', 'POST'])
    @admin_required
    def giveaway_remove_entrants(form_id):
        form = Form.query.filter_by(id=form_id, kind='giveaway').with_for_update().first_or_404()
        drawn = bool(db.session.get(db._giveaway_draw, form.id))
        if request.method == 'POST':
            check()
            if drawn:
                abort(409, 'Entrants cannot be removed after the giveaway has been drawn.')
            if request.form.get('confirm_remove') != 'yes':
                abort(400, 'Confirm removal of the selected entrants.')
            reason = request.form.get('reason', '').strip()
            if not reason or len(reason) > 1000:
                abort(400, 'Enter a removal reason, up to 1,000 characters.')
            raw = request.form.getlist('entry_ids')
            if not 1 <= len(raw) <= 500:
                abort(400, 'Select between one and 500 entrants.')
            try:
                selected = {int(value) for value in raw}
            except (ValueError, TypeError):
                abort(400, 'Select valid entrants from the list.')
            entries = Submission.query.filter(Submission.form_id == form.id, Submission.id.in_(selected)).all()
            if len(entries) != len(selected):
                abort(404)
            removed = 0
            for entry in entries:
                if not db.session.get(Removal, entry.id):
                    db.session.add(Removal(submission_id=entry.id, reason=reason,
                                           removed_by=os.getenv('ADMIN_EMAIL') or 'CL Paints admin'))
                    removed += 1
            db.session.commit()
            flash(f'Removed {removed} entrant(s) from the giveaway. Client accounts, bookings and removal history are preserved.', 'success')
            return redirect(url_for('native_form_entries', form_id=form.id))
        removed_ids = db.session.query(Removal.submission_id)
        entries = db.session.query(Submission, Account).join(Account, Account.id == Submission.client_id).filter(
            Submission.form_id == form.id, ~Submission.id.in_(removed_ids)).order_by(
            db.func.lower(Account.first_name), db.func.lower(Account.last_name), Submission.id).all()
        response = app.make_response(render_template('admin_giveaway_remove.html', form=form, entries=entries,
                                                     drawn=drawn, csrf=csrf()))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.post('/admin/native-forms/<int:form_id>/entrants/<int:submission_id>/remove')
    @admin_required
    def giveaway_remove_entrant(form_id, submission_id):
        check()
        form = Form.query.filter_by(id=form_id, kind='giveaway').with_for_update().first_or_404()
        entry = Submission.query.filter_by(id=submission_id, form_id=form.id).first_or_404()
        if db.session.get(db._giveaway_draw, form.id):
            abort(409, 'Entrants cannot be removed after the giveaway has been drawn.')
        if request.form.get('confirm_remove') != 'yes':
            abort(400, 'Confirm that this entrant should be removed from the giveaway.')
        reason = request.form.get('reason', '').strip()
        if not reason or len(reason) > 1000:
            abort(400, 'Enter a removal reason, up to 1,000 characters.')
        if not db.session.get(Removal, entry.id):
            db.session.add(Removal(submission_id=entry.id, reason=reason,
                                   removed_by=os.getenv('ADMIN_EMAIL') or 'CL Paints admin'))
            db.session.commit()
        flash('Entrant removed from this giveaway and excluded from the draw. Their account and booking records are unchanged.', 'success')
        return redirect(url_for('native_form_entries', form_id=form.id))
