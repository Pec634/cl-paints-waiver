"""Cookie-free daily website totals; no visitor identifiers or IP addresses stored."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import os
from flask import request, session, render_template
from sqlalchemy import func

def define_models(db):
    class WebsiteHit(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        day=db.Column(db.Date,nullable=False,index=True)
        page=db.Column(db.String(30),nullable=False)
        source=db.Column(db.String(200),nullable=False)
        device=db.Column(db.String(20),nullable=False)
        country=db.Column(db.String(30),nullable=False)
        count=db.Column(db.Integer,nullable=False,default=1)
        __table_args__=(db.UniqueConstraint('day','page','source','device','country'),)
    return WebsiteHit

def register(app,db,Hit,admin_required):
    @app.after_request
    def count_website_view(response):
        if request.method!='GET' or response.status_code!=200 or request.endpoint not in {'website_'+p for p in ('home','about','services','gallery','contact','studio')}:
            return response
        # Exclude authenticated staff and builder iframe previews.
        if request.headers.get('Sec-Fetch-Dest')=='iframe' or session.get('admin_authenticated'):
            return response
        agent=request.headers.get('User-Agent','').lower()
        if any(word in agent for word in ('bot','crawler','spider','headless','preview','uptime','monitor')):return response
        device='Tablet' if any(word in agent for word in ('ipad','tablet')) or ('android' in agent and 'mobile' not in agent) else 'Mobile' if any(word in agent for word in ('mobile','iphone')) else 'Desktop' if agent else 'Unknown'
        try:
            source=urlsplit(request.referrer or '').hostname or 'Direct / unavailable'
            if source==request.host.split(':')[0]:source='Internal website navigation'
            source=source[:200]
        except ValueError:source='Direct / unavailable'
        # Only configure this when a trusted proxy overwrites the header.
        geo_header=os.getenv('WEBSITE_TRUSTED_COUNTRY_HEADER','')
        country=request.headers.get(geo_header,'').upper() if geo_header else ''
        country=country if len(country)==2 and country.isascii() and country.isalpha() else 'Unavailable'
        values=dict(day=datetime.now(ZoneInfo('Europe/London')).date(),page=request.endpoint.removeprefix('website_'),source=source,device=device,country=country)
        try:
            dialect=db.engine.dialect.name
            if dialect in ('sqlite','postgresql'):
                if dialect=='sqlite':
                    from sqlalchemy.dialects.sqlite import insert
                else:
                    from sqlalchemy.dialects.postgresql import insert
                statement=insert(Hit).values(**values,count=1)
                statement=statement.on_conflict_do_update(index_elements=['day','page','source','device','country'],set_={'count':Hit.count+1})
                db.session.execute(statement)
            else:
                row=Hit.query.filter_by(**values).first()
                if row:row.count+=1
                else:db.session.add(Hit(**values,count=1))
            db.session.commit()
        except Exception:
            db.session.rollback();app.logger.warning('Website report count could not be saved.')
        return response

    @app.get('/admin/website-report')
    @admin_required
    def admin_website_report():
        today=datetime.now(ZoneInfo('Europe/London')).date()
        error=None
        try:
            start=datetime.strptime(request.args.get('start',(today-timedelta(days=29)).isoformat()),'%Y-%m-%d').date()
            end=datetime.strptime(request.args.get('end',today.isoformat()),'%Y-%m-%d').date()
            if start>end:raise ValueError()
        except ValueError:
            start,end=today-timedelta(days=29),today;error='Choose a valid start date before the end date.'
        def totals(column):
            return db.session.query(column,func.sum(Hit.count)).filter(Hit.day>=start,Hit.day<=end).group_by(column).order_by(func.sum(Hit.count).desc()).all()
        pages=totals(Hit.page)
        return render_template('admin_website_report.html',start=start,end=end,error=error,total=sum(value for _,value in pages),pages=pages,sources=totals(Hit.source),devices=totals(Hit.device),countries=totals(Hit.country),days=sorted(totals(Hit.day)))
