"""Revocable, read-only calendar subscriptions with no client personal details."""
from datetime import datetime, timedelta, timezone
import secrets
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from flask import abort, flash, make_response, redirect, render_template, request, session, url_for

KEY = 'combined_calendar_share_token'
UK = ZoneInfo('Europe/London')


def escape(value):
    return str(value).replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold(line):
    lines=[]; current=''; length=0
    for char in line:
        size=len(char.encode('utf-8'))
        if length+size > 75:
            lines.append(current);current=' ';length=1
        current+=char;length+=size
    lines.append(current)
    return '\r\n'.join(lines)


def register(app, db, Setting, Booking, Block, Slot, Order, schedule, settings, admin_required):
    def saved_token():
        row=db.session.get(Setting,KEY)
        return row.value if row else ''

    @app.route('/admin/calendar/share',methods=['GET','POST'])
    @admin_required
    def admin_shared_calendar():
        csrf=session.setdefault('shared_calendar_csrf',secrets.token_urlsafe(32))
        if request.method=='POST':
            if not secrets.compare_digest(csrf,request.form.get('csrf_token','')):abort(400)
            action=request.form.get('action')
            if action not in ('create','rotate','disable'):abort(400)
            if action=='create' and saved_token():
                return redirect(url_for('admin_shared_calendar'))
            db.session.merge(Setting(key=KEY,value='' if action=='disable' else secrets.token_urlsafe(32)))
            db.session.commit()
            flash('Shared calendar link disabled.' if action=='disable' else 'Shared calendar link ready. Anyone with the link can read this schedule.','success')
            return redirect(url_for('admin_shared_calendar'))
        token=saved_token(); feed_url=''; subscribe_url=''; error=None
        if token:
            base=settings().get('public_app_url','').rstrip('/')
            parsed=urlsplit(base)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                error='Set a valid HTTPS public portal URL in Settings before sharing this calendar.'
            else:
                feed_url=base+url_for('shared_calendar_feed',token=token)
                subscribe_url='webcal://'+feed_url.removeprefix('https://')
        response=make_response(render_template('admin_shared_calendar.html',csrf=csrf,enabled=bool(token),feed_url=feed_url,subscribe_url=subscribe_url,error=error))
        response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.get('/calendar/shared/<token>.ics')
    def shared_calendar_feed(token):
        expected=saved_token()
        if not expected or not token.isascii() or len(token)>64 or not secrets.compare_digest(expected,token):abort(404)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//CL Paints//Combined Calendar//EN',
            'CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:CL Paints & CL Creates','X-WR-TIMEZONE:Europe/London']
        def event(uid,start,end,summary,description='',status='CONFIRMED',location='',transparent=False):
            if end<=start:return
            def utc(value):
                return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            lines.extend(['BEGIN:VEVENT','UID:'+uid+'@clpaints', 'DTSTAMP:'+stamp,'DTSTART:'+utc(start),'DTEND:'+utc(end),
                'SUMMARY:'+escape(summary),'DESCRIPTION:'+escape(description),'STATUS:'+status,
                'TRANSP:'+('TRANSPARENT' if transparent else 'OPAQUE')])
            if location:lines.append('LOCATION:'+escape(location))
            lines.append('END:VEVENT')
        for booking in Booking.query.filter(Booking.status.in_(('Accepted','Under Review','Awaiting Payment'))).all():
            for index,day in enumerate(schedule(booking)):
                try:
                    start=datetime.fromisoformat(day['date']+'T'+day['start_time']).replace(tzinfo=UK)
                    end=datetime.fromisoformat(day['date']+'T'+day['finish_time']).replace(tzinfo=UK)
                    if end<=start:end+=timedelta(days=1)
                except (KeyError,TypeError,ValueError):continue
                state='Confirmed' if booking.status=='Accepted' else 'Awaiting Payment' if booking.status=='Awaiting Payment' else 'Under Review'
                event(f'booking-{booking.id}-{index}',start,end,f'CL Paints Face Painting · {booking.public_reference} · {state}',
                    f'Booking day {index+1}. Open the admin portal for event and client details.',
                    'CONFIRMED' if booking.status=='Accepted' else 'TENTATIVE')
        for block in Block.query.all():
            event(f'block-{block.id}',block.starts_at.replace(tzinfo=UK),block.ends_at.replace(tzinfo=UK),'CL Paints · Unavailable')
        for slot in Slot.query.filter_by(active=True,enabled=True).all():
            paid_count=Order.query.filter(Order.collection_slot_id==slot.id,Order.paid>=Order.total,Order.total>0).count()
            event(f'collection-{slot.id}',slot.starts_at.replace(tzinfo=timezone.utc),slot.ends_at.replace(tzinfo=timezone.utc),
                'CL Creates collection · '+slot.title,
                f'{paid_count} paid collection order(s). Face-off time; Chloe confirms meeting details separately. This does not block CL Paints availability.',
                location=slot.venue,transparent=True)
        lines.append('END:VCALENDAR')
        response=make_response('\r\n'.join(fold(line) for line in lines)+'\r\n')
        response.headers['Content-Type']='text/calendar; charset=utf-8'
        response.headers['Content-Disposition']='inline; filename="cl-paints-and-creates.ics"'
        response.headers['Cache-Control']='private, no-cache, max-age=0'
        response.headers['Referrer-Policy']='no-referrer';response.headers['X-Robots-Tag']='noindex, nofollow'
        return response
