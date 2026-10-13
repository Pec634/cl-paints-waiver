"""Portable, independently stored email presets; loading prepares a private draft."""
import base64
import json
import secrets
from types import SimpleNamespace
from urllib.parse import urlsplit
from flask import abort, jsonify, request, session, Response
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename
from client_notifications import EMAIL_KINDS, validate_email_settings
from email_layout import validate
from email_media import file_type

PREFIX='email_preset_'
SHARED=('notification_heading','notification_footer','notification_colour','notification_layout')

def scope(kind):return {'portal_enquiry':'portal','website_enquiry':'website'}.get(kind,kind)

def assets(raw):
    if not isinstance(raw,list) or len(raw)>12:raise ValueError('A preset supports up to 12 media items.')
    result=[];total=0
    for index,item in enumerate(raw):
        if not isinstance(item,dict):raise ValueError('Invalid media item.')
        kind=item.get('kind');label=item.get('label','');filename=secure_filename(item.get('filename',''))
        if kind not in ('image','document','link') or not isinstance(label,str) or not 1<=len(label)<=150:raise ValueError('Invalid media type or description.')
        content=None;content_type='';url=item.get('url','')
        if kind=='link':
            parsed=urlsplit(url)
            if not isinstance(url,str) or len(url)>2000 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443) or any(c.isspace() for c in url):raise ValueError('Use a valid HTTPS media link.')
        else:
            try:content=base64.b64decode(item.get('content',''),validate=True)
            except (ValueError,TypeError):raise ValueError('Invalid encoded media file.') from None
            if not filename or not content or len(content)>2*1024*1024:raise ValueError('Media files must be nonempty and under 2 MB.')
            total+=len(content);content_type=file_type(filename,content,kind)
        result.append(SimpleNamespace(id=-(index+1),kind=kind,label=label,filename=filename,content=content,content_type=content_type,url=url if kind=='link' else '',
                      preview_source='data:'+content_type+';base64,'+base64.b64encode(content).decode() if kind=='image' else ''))
    if total>5*1024*1024:raise ValueError('Keep preset files under 5 MB in total.')
    return result

def register(app,db,Setting,Media,settings,admin_required):
    def eligible(kind):return Media.query.filter(Media.area.in_([kind,scope(kind),'all']+(['both'] if kind in ('booking','reward') else []))).order_by(Media.id).all()
    def check():
        if not session.get('settings_csrf') or not secrets.compare_digest(session['settings_csrf'],request.headers.get('X-CSRF-Token','')):abort(400)
    def private(value):
        response=jsonify(value);response.headers['Cache-Control']='private, no-store';return response
    def validate_preset(data):
        if not isinstance(data,dict) or data.get('format')!='cl-paints-email-preset' or data.get('version')!=1:raise ValueError('Choose a CL Paints email preset file (version 1).')
        name=data.get('name','');fields=data.get('fields',{})
        if not isinstance(name,str) or not 1<=len(name.strip())<=100 or not isinstance(fields,dict):raise ValueError('Enter a preset name of up to 100 characters.')
        values={key:fields.get(key) for key in ('subject','body',*SHARED)}
        if any(not isinstance(value,str) for value in values.values()):raise ValueError('Invalid preset content.')
        validate_email_settings({**{key:values[key] for key in SHARED},'notification_booking_subject':values['subject'],'notification_booking_body':values['body']})
        media=assets(data.get('assets',[]));layout=validate(data.get('layout',{}),media)
        return dict(format='cl-paints-email-preset',version=1,name=name.strip(),fields=values,layout=layout,assets=data.get('assets',[]))
    def prepare(kind,layout,raw,persist):
        imported=assets(raw);layout=validate(layout,imported)
        if not persist:return layout,imported
        mapped={};available=eligible(kind);new=[]
        for item in imported:
            match=next((row for row in available if all(getattr(row,key)==getattr(item,key) for key in ('kind','label','filename','content_type','content','url'))),None)
            if match is None:
                match=Media(area=scope(kind),**{key:getattr(item,key) for key in ('kind','label','filename','content_type','content','url')});db.session.add(match);available.append(match);new.append(match)
            mapped[item.id]=match
        if Media.query.count()>12 or sum(len(row.content or b'') for row in Media.query.all())>5*1024*1024:raise ValueError('The media library would exceed 12 items or 5 MB. Remove unused media before applying this preset.')
        db.session.flush()
        layout['order']=[f'media-{mapped[int(key[6:])].id}' if key.startswith('media-') else key for key in layout['order']]
        layout['media']={str(mapped[int(key)].id):value for key,value in layout['media'].items()}
        return validate(layout,eligible(kind)),eligible(kind)
    app.extensions['email_preset_prepare']=prepare

    @app.get('/admin/email-presets')
    @admin_required
    def email_presets_list():
        rows=Setting.query.filter(Setting.key.startswith(PREFIX,autoescape=True)).order_by(Setting.key).all()
        return private(dict(presets=[dict(id=row.key[len(PREFIX):],name=json.loads(row.value)['name']) for row in rows]))

    @app.post('/admin/email-presets/<action>')
    @admin_required
    def email_presets_write(action):
        check()
        if action not in ('save','import'):abort(404)
        if request.content_length and request.content_length>8*1024*1024:return jsonify(error='Preset files must be under 8 MB.'),413
        try:
            data=request.get_json(silent=True)
            if not isinstance(data,dict):raise ValueError('Choose valid preset content.')
            if action=='import':preset=validate_preset(data)
            else:
                kind=data.get('kind')
                if kind not in EMAIL_KINDS:raise ValueError('Choose an email response type.')
                fields=data.get('fields',{});config=settings()
                layout=data.get('layout',{})
                if 'assets' in data:
                    media=assets(data['assets']);portable=data['assets'];layout=validate(layout,media)
                else:
                    media=eligible(kind);layout=validate(layout,media);portable=[]
                    mapping={item.id:-(index+1) for index,item in enumerate(media)}
                    for item in media:portable.append({key:getattr(item,key) for key in ('kind','label','filename','url')}|{'content':base64.b64encode(item.content).decode() if item.content else ''})
                    layout['order']=[f'media-{mapping[int(key[6:])]}' if key.startswith('media-') else key for key in layout['order']]
                    layout['media']={str(mapping[int(key)]):value for key,value in layout['media'].items()}
                preset=validate_preset(dict(format='cl-paints-email-preset',version=1,name=data.get('name',''),layout=layout,assets=portable,
                    fields={'subject':fields.get(f'notification_{kind}_subject',config[f'notification_{kind}_subject']),
                            'body':fields.get(f'notification_{kind}_body',config[f'notification_{kind}_body']),
                            **{key:fields.get(key,config[key]) for key in SHARED}}))
            if Setting.query.filter(Setting.key.startswith(PREFIX,autoescape=True)).count()>=20:raise ValueError('Keep up to 20 saved presets. Delete an unused preset first.')
            key=secrets.token_hex(12);db.session.add(Setting(key=PREFIX+key,value=json.dumps(preset)));db.session.commit()
            return private(dict(id=key,name=preset['name']))
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            db.session.rollback();return jsonify(error=str(error) or 'Invalid preset.'),400
        except SQLAlchemyError:
            db.session.rollback();return jsonify(error='The preset could not be saved. Please try again.'),503

    @app.get('/admin/email-presets/<preset_id>/<action>')
    @admin_required
    def email_preset_read(preset_id,action):
        if action not in ('load','export'):abort(404)
        row=db.get_or_404(Setting,PREFIX+preset_id);preset=json.loads(row.value)
        if action=='load':return private(preset)
        return Response(json.dumps(preset,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="'+(secure_filename(preset['name']) or 'email-preset')+'.json"','Cache-Control':'private, no-store'})

    @app.post('/admin/email-presets/<preset_id>/delete')
    @admin_required
    def email_preset_delete(preset_id):
        check();db.session.delete(db.get_or_404(Setting,PREFIX+preset_id));db.session.commit();return private(dict(deleted=True))
