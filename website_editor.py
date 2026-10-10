"""Validate the website editor's structured content, never arbitrary HTML/CSS."""
import math
import re
from urllib.parse import urlsplit

ANIMATIONS = ('none', 'fade', 'slide-up', 'slide-left', 'zoom', 'bounce', 'float', 'pulse', 'rotate')

def number(value, low, high):
    value=float(value)
    if not math.isfinite(value) or not low<=value<=high: raise ValueError('Invalid numeric setting')
    return value

def link(value):
    value=str(value).strip()
    parts=urlsplit(value)
    if len(value)>2000 or any(ord(c)<32 for c in value) or '\\' in value: raise ValueError('Invalid link')
    if value and not (parts.scheme in ('https','http','mailto','tel') or (not parts.scheme and not parts.netloc and value.startswith(('/', '#')))): raise ValueError('Use a website, email, telephone or page link')
    return value

def text(value, limit=5000):
    if not isinstance(value,str) or len(value)>limit: raise ValueError('Text is too long')
    return value

def item(raw, validate_photo):
    if not isinstance(raw,dict): raise ValueError('Invalid block')
    result={}
    for key in ('text','caption'):
        if key in raw: result[key]=text(raw[key])
    if raw.get('photo'):
        validate_photo(raw['photo']);result['photo']=raw['photo']
    if 'link' in raw: result['link']=link(raw['link'])
    if raw.get('video'):
        video=link(raw['video']);parts=urlsplit(video)
        if parts.scheme!='https' or parts.hostname not in ('www.youtube-nocookie.com','www.youtube.com','player.vimeo.com') or not parts.path.startswith(('/embed/','/video/')): raise ValueError('Use a YouTube or Vimeo embed URL')
        result['video']=video
    for device in ('desktop','tablet','mobile'):
        position=raw.get(device,{})
        result[device]={key:number(position.get(key,0),0 if key=='width' else -2000,100 if key=='width' else 2000) for key in ('x','y','width')}
    style=raw.get('style',{});safe={}
    for key in ('color','background','borderColor'):
        if style.get(key):
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',style[key]): raise ValueError('Invalid colour')
            safe[key]=style[key]
    for key,limits in {'fontSize':(0,120),'height':(0,1200),'padding':(0,120),'gap':(0,120),'borderRadius':(0,100),'borderWidth':(0,20)}.items():
        if key in style: safe[key]=number(style[key],*limits)
    for key,choices in {'textAlign':('left','center','right'),'fontFamily':('inherit','Georgia','Arial','Verdana'),'objectFit':('cover','contain'),'objectPosition':('center','top','bottom','left','right')}.items():
        if key in style:
            if style[key] not in choices: raise ValueError('Invalid style')
            safe[key]=style[key]
    result['style']=safe
    for flag in ('hidden','locked'):
        result[flag]=bool(raw.get(flag,False))
    animation=raw.get('animation',{})
    kind=animation.get('kind','none')
    if kind not in ANIMATIONS: raise ValueError('Invalid animation')
    easing=animation.get('easing','ease')
    trigger=animation.get('trigger','load')
    if easing not in ('ease','linear','ease-in','ease-out','ease-in-out') or trigger not in ('load','scroll','hover'): raise ValueError('Invalid animation timing')
    result['animation']={'kind':kind,'duration':number(animation.get('duration',1),0.2,20),'delay':number(animation.get('delay',0),0,20),'repeat':number(animation.get('repeat',1),1,10),'easing':easing,'trigger':trigger}
    return result

def validate(raw, validate_photo):
    if not isinstance(raw,dict) or len(raw)>203: raise ValueError('Invalid layout')
    result={}
    for key,value in raw.items():
        if key.startswith('_'): continue
        if not (re.fullmatch(r'e-[a-f0-9]+',key) or key.isdigit() and int(key)<=1000): raise ValueError('Invalid element')
        result[key]=item(value,validate_photo)
    blocks=raw.get('_blocks',[])
    if not isinstance(blocks,list) or len(blocks)>50: raise ValueError('Maximum 50 rows')
    result['_blocks']=[]
    for row in blocks:
        clean=item(row,validate_photo)
        clean['before']=int(number(row.get('before',-1),-1,100))
        cells=row.get('cells',[])
        if not isinstance(cells,list) or not 1<=len(cells)<=4: raise ValueError('Use one to four columns')
        clean['cells']=[]
        for cell in cells:
            kind=cell.get('kind')
            if kind not in ('heading','text','image','button','review','video','announcement'): raise ValueError('Invalid block type')
            clean['cells'].append(dict(item(cell,validate_photo),kind=kind))
        result['_blocks'].append(clean)
    sections=raw.get('_sections',[])
    if not isinstance(sections,list) or len(sections)>100 or any(not isinstance(i,int) or i<0 or i>100 for i in sections) or len(set(sections))!=len(sections): raise ValueError('Invalid section order')
    result['_sections']=sections
    seo=raw.get('_seo',{})
    result['_seo']={key:text(seo.get(key,''),limit) for key,limit in [('title',150),('description',300)]}
    return result
