"""Saved event designs used by the browser's complete moodboard PNG export."""
from flask import jsonify


def register(app, db, Event, Assignment, prices, admin_required):
    def payload(event):
        rows = Assignment.query.filter_by(event_id=event.id).order_by(
            Assignment.sort_order.asc(), Assignment.id.asc()).all()
        groups = []
        current_prices = prices()
        for size, title, prefix in [('large', 'Large Paints', 'L'), ('small', 'Small Paints', 'S')]:
            images = [row.image for row in rows if row.image is not None and row.image.active and row.image.design_type == size]
            groups.append(dict(title=title, price=current_prices[size], images=[
                dict(url=image.image_url, label=f'{prefix} - {index}') for index, image in enumerate(images, 1)]))
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
