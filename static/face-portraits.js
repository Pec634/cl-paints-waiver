/* User-supplied template grid, cropped at draw time without changing the source. */
window.CLPortraits={image:new Image(),templates:{
'curly-man':{asset:'variations',column:0,row:0,cx:384,scale:1.25,split:512,eyes:330,mouth:467,rx:158,ry:187,y:375},
'curly-woman':{asset:'variations',column:1,row:0,cx:384,scale:1.25,split:512,eyes:347,mouth:472,rx:148,ry:178,y:380},
'red-haired-boy':{asset:'variations',column:0,row:1,cx:384,scale:1.25,split:512,eyes:330,mouth:444,rx:167,ry:168,y:375},
'plaited-girl':{asset:'variations',column:1,row:1,cx:384,scale:1.25,split:512,eyes:326,mouth:444,rx:155,ry:175,y:375},
'adult-male':{column:0,row:0,cx:420,scale:1.05,eyes:322,mouth:463,rx:155,ry:190,y:375},
'adult-female':{column:1,row:0,cx:360,scale:1.05,eyes:342,mouth:479,rx:148,ry:192,y:382},
'child-male':{column:0,row:1,cx:420,scale:1.15,eyes:332,mouth:452,rx:165,ry:165,y:365},
'child-female':{column:1,row:1,cx:360,scale:1.15,eyes:335,mouth:452,rx:160,ry:165,y:365}},
// Face outlines measured in each source cell, before crop/scale.
outlines:{
'adult-male':[[300,135],[325,110],[420,100],[520,120],[545,190],[545,310],[515,400],[460,450],[420,465],[370,450],[315,400],[290,310],[290,195]],
'adult-female':[[250,150],[275,115],[355,100],[445,115],[475,170],[480,290],[455,375],[410,440],[360,465],[310,440],[270,380],[240,290],[245,195]],
'child-male':[[300,120],[330,90],[420,85],[510,105],[540,175],[540,260],[510,330],[465,370],[420,390],[370,370],[325,330],[295,260],[290,175]],
'child-female':[[255,115],[285,90],[360,85],[435,100],[470,160],[480,245],[455,320],[410,370],[360,390],[310,370],[265,320],[240,245],[245,160]],
'curly-man':[[285,130],[305,95],[385,80],[470,100],[495,150],[500,250],[475,330],[425,375],[385,390],[340,375],[290,330],[265,250],[270,150]],
'curly-woman':[[285,150],[300,110],[380,85],[460,115],[475,170],[480,250],[460,320],[420,365],[385,380],[340,365],[305,320],[285,250],[275,170]],
'red-haired-boy':[[275,160],[285,110],[375,80],[465,100],[495,155],[505,235],[480,300],[430,350],[385,365],[335,350],[285,300],[265,235],[265,170]],
'plaited-girl':[[290,155],[300,110],[385,85],[465,110],[480,160],[485,235],[460,300],[420,350],[385,365],[340,350],[305,300],[280,235],[280,165]]},
path(context){
 const t=this.selected(),source=this.outlines[document.getElementById('paint-model').value];
 const offset=t.asset?80:(t.row?90:80);
 // Allow the entire visible face, including the hairline, outer temples and jaw.
 // Interpolate THROUGH contour anchors rather than rounding inwards between them.
 const points=source.map(([x,y])=>({x:300+(x-t.cx)*t.scale*1.22,y:offset+y*t.scale+(y<180?-48:y>300?18:0)}));
 context.beginPath();context.moveTo(points[0].x,points[0].y);
 for(let i=0;i<points.length;i++){
  const previous=points[(i+points.length-1)%points.length],current=points[i],next=points[(i+1)%points.length],after=points[(i+2)%points.length];
  context.bezierCurveTo(current.x+(next.x-previous.x)/6,current.y+(next.y-previous.y)/6,next.x-(after.x-current.x)/6,next.y-(after.y-current.y)/6,next.x,next.y);
 }
 context.closePath();
},
selected(){const control=document.getElementById('paint-model');if(control && !this.templates[control.value])control.value='adult-male';return this.templates[control?.value];},active(){return !!this.selected();},
face(){const t=this.selected();return {x:300,y:t.y,rx:t.rx,ry:t.ry};},
draw(canvas){const t=this.selected(),image=t?.asset?this.images[t.asset]:this.image;if(!t||!image.complete||!image.naturalWidth)return false;const ctx=canvas.getContext('2d'),unit=image.naturalWidth/1536,width=768*unit,split=t.split||548,cellHeight=t.row?1024-split:split,top=t.row?split*unit:0,height=cellHeight*unit;ctx.clearRect(0,0,600,720);ctx.fillStyle='#fff';ctx.fillRect(0,0,600,720);ctx.drawImage(image,t.column*width,top,width,height,300-t.cx*t.scale,t.asset?80:(t.row?90:80),768*t.scale,cellHeight*t.scale);return true;}};
window.CLPortraits.image.src='/static/face-assets/studio-face-grid.png';
window.CLPortraits.image.onload=()=>document.getElementById('paint-model')?.dispatchEvent(new Event('change'));
function syncPortraitControls(){const photo=window.CLPortraits.active();for(const id of ['face','skin','hair','hair-colour','facial-hair','expression','eye-colour','brows','freckles','lips','height','width','animate']){const control=document.getElementById('paint-'+id);if(control)control.disabled=photo;}}
document.getElementById('paint-model')?.addEventListener('change',syncPortraitControls);syncPortraitControls();

window.CLPortraits.images={variations:new Image()};
window.CLPortraits.images.variations.onload=()=>document.getElementById('paint-model')?.dispatchEvent(new Event('change'));
window.CLPortraits.images.variations.src='/static/face-assets/studio-face-variations-swept-back.png';
