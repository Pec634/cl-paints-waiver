"""Saved event designs for printable sheets and the moodboard PNG export."""
from flask import jsonify


def event_design_groups(Assignment, event_id, prices, *, include_ids=False):
    rows = Assignment.query.filter_by(event_id=event_id).order_by(
        Assignment.sort_order.asc(), Assignment.id.asc()).all()
    groups = []
    for size, title, prefix in [('large', 'Large Paints', 'L'), ('small', 'Small Paints', 'S')]:
        images = [row.image for row in rows if row.image is not None and row.image.active and row.image.design_type == size]
        designs = []
        for index, image in enumerate(images, 1):
            design = dict(url=image.image_url, label=f'{prefix} - {index}')
            if include_ids:
                design['id'] = image.id
            designs.append(design)
        groups.append(dict(title=title, price=prices[size], images=designs))
    return groups


def register(app, db, Event, Assignment, prices, admin_required):
    def payload(event):
        groups = event_design_groups(Assignment, event.id, prices())
        response = jsonify(event=event.name, event_id=event.id, groups=groups)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/moodboard/event/<int:event_id>/download-data')
    def moodboard_download_data(event_id):
        event = db.get_or_404(Event, event_id)
        if event.status == 'Archived':
            return 'This event has finished. Its moodboard link is closed.', 410
        return payload(event)

    @app.get('/admin/events/<int:event_id>/moodboard/download-data')
    @admin_required
    def admin_moodboard_download_data(event_id):
        return payload(db.get_or_404(Event, event_id))
