"""Private, admin-only incident and road collision reporting."""
from datetime import datetime
from io import BytesIO
import json
import secrets
from flask import abort, flash, redirect, render_template, request, session, url_for, send_file
from native_forms import design_uploads


def field(label,kind='text',required=False,choices=None):
    return dict(label=label,type=kind,required=required,choices=choices or [])

COMMON=[field('Incident date','date',True),field('Incident time','time',True),field('Location / address','textarea',True),field('What3words location'),field('Related booking or event reference'),field('Reporter name','text',True),field('Reporter job title')]
SCHEMAS={
 'incident':('Incident / accident report',COMMON+[
    field('Person involved','select',True,['Employee','Customer','Contractor','General public','Other']),field('If other, specify'),
    field('Casualty name','text',True),field('Casualty address','textarea'),field('Date of birth','date'),field('Gender'),field('Ethnicity'),field('Age range'),field('Contact number'),field('Email address','email'),
    field('Parent / guardian name'),field('Relationship to casualty'),field('First aid administered by'),field('Incident details','textarea',True),field('Body parts injured','textarea'),field('Action taken / treatment','textarea',True),
    field('Did the casualty resume activities?','select',True,['Yes','No','Unknown']),field('How did the casualty leave?'),field('Was the area checked?','select',True,['Yes','No']),field('Area checked by'),
    field('Witness names and contact details','textarea'),field('Follow-up required','textarea'),field('Reporter signature — type full name','text',True),field('Casualty / parent / guardian signature — type full name'),field('Reason casualty signature is unavailable','textarea')]),
 'collision':('Road traffic collision report',COMMON+[
    field('CL Paints driver name','text',True),field('CL Paints vehicle registration','text',True),field('Vehicle make / model'),field('Other driver names and contact details','textarea'),field('Other vehicle registrations and descriptions','textarea'),field('Other parties insurer / policy details','textarea'),
    field('Road, weather and visibility conditions','textarea'),field('What happened?','textarea',True),field('Vehicle / property damage','textarea'),field('Injuries and affected people','textarea'),field('Witness names and contact details','textarea'),
    field('Emergency services contacted?','select',True,['Yes','No']),field('Police reference / officer details'),field('Insurer notified?','select',True,['Yes','No','Pending']),field('Insurer claim reference'),field('Immediate actions taken','textarea',True),field('Follow-up required','textarea'),field('Reporter signature — type full name','text',True)])}

def define_models(db):
    class StaffReport(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        kind=db.Column(db.String(20),nullable=False)
        answers_json=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
        token=db.Column(db.String(64),nullable=False,unique=True)
    class StaffReportMedia(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        report_id=db.Column(db.Integer,db.ForeignKey('staff_report.id'),nullable=False,index=True)
        content=db.Column(db.LargeBinary,nullable=False)
        mime=db.Column(db.String(50),nullable=False)
        filename=db.Column(db.String(150),nullable=False)
    return StaffReport,StaffReportMedia

def register(app,db,models,admin_required):
    Report,Media=models
    def csrf():return session.setdefault('client_csrf',secrets.token_urlsafe(32))
    @app.get('/admin/staff-reports')
    @admin_required
    def staff_reports():
        kind=request.args.get('kind','')
        query=Report.query
        if kind in SCHEMAS:query=query.filter_by(kind=kind)
        return render_template('admin_staff_reports.html',reports=query.order_by(Report.id.desc()).all(),schemas=SCHEMAS,kind=kind)

    @app.route('/admin/staff-reports/new/<kind>',methods=['GET','POST'])
    @admin_required
    def staff_report_new(kind):
        if kind not in SCHEMAS:abort(404)
        title,fields=SCHEMAS[kind];error=None
        token=session.setdefault('staff_report_token',secrets.token_urlsafe(32))
        if request.method=='POST':
            if not secrets.compare_digest(csrf(),request.form.get('csrf_token','')):abort(400)
            if not secrets.compare_digest(token,request.form.get('submission_token','')):abort(400)
            existing=Report.query.filter_by(token=token).first()
            if existing:return redirect(url_for('staff_report_detail',report_id=existing.id))
            try:
                data={}
                for index,f in enumerate(fields):
                    value=request.form.get('field_'+str(index),'').strip()
                    if f['required'] and not value:raise ValueError('Complete '+f['label']+'.')
                    if len(value)>4000:raise ValueError(f['label']+' is too long.')
                    if value and f['type']=='select' and value not in f['choices']:raise ValueError('Choose a listed option for '+f['label']+'.')
                    if value and f['type'] in ('date','time'):
                        try:datetime.strptime(value,'%Y-%m-%d' if f['type']=='date' else '%H:%M')
                        except ValueError:raise ValueError('Check '+f['label']+'.')
                    data[f['label']]=value
                uploads=design_uploads(request.files.getlist('images'))
                report=Report(kind=kind,answers_json=json.dumps(data),token=token)
                db.session.add(report);db.session.flush()
                for upload in uploads:db.session.add(Media(report_id=report.id,**upload))
                db.session.commit();session.pop('staff_report_token',None)
                flash('Report saved privately.','success')
                return redirect(url_for('staff_report_detail',report_id=report.id))
            except ValueError as problem:
                db.session.rollback();error=str(problem)
        return render_template('admin_staff_report_form.html',title=title,fields=fields,error=error,csrf=csrf(),token=token)

    @app.get('/admin/staff-reports/<int:report_id>')
    @admin_required
    def staff_report_detail(report_id):
        report=db.get_or_404(Report,report_id)
        return render_template('admin_staff_report_detail.html',report=report,title=SCHEMAS[report.kind][0],answers=json.loads(report.answers_json),media=Media.query.filter_by(report_id=report.id).all())

    @app.get('/admin/staff-report-media/<int:media_id>')
    @admin_required
    def staff_report_media(media_id):
        item=db.get_or_404(Media,media_id)
        response=send_file(BytesIO(item.content),mimetype=item.mime,download_name=item.filename,as_attachment=True)
        response.headers['Cache-Control']='no-store'
        return response
