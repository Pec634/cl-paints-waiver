"""One validated renderer for draft previews and delivered notification layouts."""
import html
import json
import secrets
from flask import abort, jsonify, request, session, url_for, render_template
from sqlalchemy.exc import SQLAlchemyError

DEFAULT=dict(width=600,padding=24,font_size=16,line_height=1.6,radius=16,
             background='#f1f4f9',paper='#ffffff',text='#243047',align='left',font='Arial',
             portal_label='Open your portal',order=[],media={})

def validate(value,items):
    import re
    if not isinstance(value,dict): raise ValueError('Choose valid layout settings.')
    result=dict(DEFAULT)
    for key,low,high in [('width',320,900),('padding',0,60),('font_size',12,28),('radius',0,40)]:
        raw=value.get(key,result[key])
        if isinstance(raw,bool) or not str(raw).isdigit() or not low<=int(raw)<=high: raise ValueError(f'{key.replace("_"," ").capitalize()} must be between {low} and {high}.')
        result[key]=int(raw)
    try: result['line_height']=float(value.get('line_height',1.6))
    except (ValueError,TypeError): raise ValueError('Choose a valid line spacing.') from None
    if not 1<=result['line_height']<=2.5: raise ValueError('Line spacing must be between 1 and 2.5.')
    for key in ('background','paper','text'):
        result[key]=value.get(key,result[key])
        if not isinstance(result[key],str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',result[key]): raise ValueError('Choose valid colours.')
    for key,choices in [('align',('left','center','right')),('font',('Arial','Georgia','Verdana','Tahoma'))]:
        result[key]=value.get(key,result[key])
        if result[key] not in choices: raise ValueError('Choose a supported font or alignment.')
    result['portal_label']=value.get('portal_label',result['portal_label'])
    if not isinstance(result['portal_label'],str) or not 1<=len(result['portal_label'])<=100: raise ValueError('Portal link text needs 1–100 characters.')
    allowed=['heading','body','portal','footer']+[f'media-{item.id}' for item in items]
    order=value.get('order',[])
    if not isinstance(order,list) or len(order)>16 or any(key not in allowed for key in order) or len(set(order))!=len(order): raise ValueError('Choose valid, unique layout blocks.')
    result['order']=order+[key for key in allowed if key not in order]
    media=value.get('media',{})
    if not isinstance(media,dict): raise ValueError('Choose valid image and link settings.')
    result['media']={}
    for item in items:
        data=media.get(str(item.id),{})
        if not isinstance(data,dict): raise ValueError('Choose valid media settings.')
        width=data.get('width',100)
        if not str(width).isdigit() or not 10<=int(width)<=100: raise ValueError('Image width must be 10–100%.')
        align=data.get('align','left'); style=data.get('style','text'); caption=data.get('caption','')
        if align not in ('left','center','right') or style not in ('text','button') or not isinstance(caption,str) or len(caption)>300: raise ValueError('Choose valid image alignment, link style or caption.')
        result['media'][str(item.id)]=dict(width=int(width),align=align,style=style,caption=caption)
    return result

def register(app,db,Setting,Media,settings,admin_required):
    def items(kind): return Media.query.filter(Media.area.in_(['both',kind])).order_by(Media.id).all()
    def saved(kind):
        row=db.session.get(Setting,'email_layout_'+kind)
        try: data=json.loads(row.value) if row else {}
        except ValueError: data={}
        # Removed files no longer belong in the layout.
        allowed={'heading','body','portal','footer'}|{f'media-{i.id}' for i in items(kind)}
        data['order']=[key for key in data.get('order',[]) if key in allowed]
        if not row:
            data['order']=['heading']+[f'media-{i.id}' for i in items(kind) if i.kind=='image']+['body','portal','footer']+[f'media-{i.id}' for i in items(kind) if i.kind!='image']
        return validate(data,items(kind))
    @app.context_processor
    def context():
        return {'email_layouts':{kind:saved(kind) for kind in ('booking','reward')}} if request.endpoint=='admin_settings' else {}
    def render(config,kind,heading,body,footer,link,preview=False,draft=None):
        layout=validate(draft,items(kind)) if draft is not None else saved(kind)
        esc=html.escape
        blocks=dict(heading=f'<h1 style="font-size:{layout["font_size"]+8}px;color:{config["notification_colour"]}">{esc(heading)}</h1>',
            body=f'<p style="white-space:pre-line">{esc(body)}</p>',
            portal=f'<p><a href="{esc(link,quote=True)}" style="color:{config["notification_colour"]}">{esc(layout["portal_label"])}</a></p>',
            footer=f'<p style="white-space:pre-line">{esc(footer)}</p>')
        for item in items(kind):
            option=layout['media'][str(item.id)]
            if item.kind=='image':
                source=url_for('email_media_file',media_id=item.id) if preview else f'cid:cl-paints-media-{item.id}'
                margins={'left':'0 auto 0 0','center':'0 auto','right':'0 0 0 auto'}[option['align']]
                content=f'<img src="{source}" alt="{esc(item.label,quote=True)}" style="display:block;width:{option["width"]}%;max-width:100%;height:auto;margin:{margins}">'
                if option['caption']: content+=f'<p>{esc(option["caption"])}</p>'
            elif item.kind=='link':
                style=f'color:{config["notification_colour"]}' if option['style']=='text' else f'display:inline-block;padding:12px 18px;border-radius:6px;background:{config["notification_colour"]};color:#ffffff;text-decoration:none'
                content=f'<a href="{esc(item.url,quote=True)}" style="{style}">{esc(item.label)}</a>'
                body+='\n\n'+item.label+': '+item.url
            else:
                content=f'Attachment: {esc(item.label)} ({esc(item.filename)})'
                if preview: content=f'<a href="{url_for("email_media_file",media_id=item.id)}">Download attachment: {esc(item.label)}</a>'
                body+='\n\nAttached: '+item.label+' ('+item.filename+')'
            blocks[f'media-{item.id}']=f'<div style="text-align:{option["align"]};margin:16px 0">{content}</div>'
        border=f'border-top:5px solid {config["notification_colour"]};' if config['notification_layout']=='card' else ''
        message=f'<div style="background:{layout["background"]};padding:16px"><div style="font-family:{layout["font"]},sans-serif;max-width:{layout["width"]}px;margin:auto;background:{layout["paper"]};color:{layout["text"]};padding:{layout["padding"]}px;border-radius:{layout["radius"]}px;font-size:{layout["font_size"]}px;line-height:{layout["line_height"]};text-align:{layout["align"]};{border}">'+''.join(blocks[key] for key in layout['order'])+'</div></div>'
        return message,body
    @app.post('/admin/email-layout/<kind>/<action>')
    @admin_required
    def email_layout_action(kind,action):
        if kind not in ('booking','reward') or action not in ('preview','save'): abort(404)
        if not session.get('settings_csrf') or not secrets.compare_digest(session['settings_csrf'],request.headers.get('X-CSRF-Token','')): abort(400)
        data=request.get_json(silent=True)
        try:
            if not isinstance(data,dict): raise ValueError('Choose valid email settings.')
            layout=validate(data.get('layout',{}),items(kind))
            fields=data.get('fields',{})
            keys=[f'notification_{kind}_subject',f'notification_{kind}_body','notification_heading','notification_footer','notification_colour','notification_layout']
            if not isinstance(fields,dict): raise ValueError('Choose valid email content.')
            config=settings(); values={key:fields.get(key,config[key]) for key in keys}
            if any(not isinstance(value,str) for value in values.values()): raise ValueError('Email content must be text.')
            from client_notifications import validate_email_settings,render_notification
            validate_email_settings(values);config.update(values)
            if action=='save':
                values['email_layout_'+kind]=json.dumps(layout)
                for key,value in values.items():
                    row=db.session.get(Setting,key)
                    if row: row.value=value
                    else: db.session.add(Setting(key=key,value=value))
                db.session.commit()
            subject,_,_,message=render_notification(config,'Sample client',kind,'SAMPLE-001','Sample booking or reward update.',url_for('client.login',_external=True),preview=True,layout=layout)
            return jsonify(html=render_template('email_preview_embed.html',subject=subject,message=message),saved=action=='save')
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(error='The layout could not be saved. Please try again.'),503
    app.extensions['email_layout_render']=render
