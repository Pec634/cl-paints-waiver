(() => {
  const form=document.getElementById('shape-editor'),svg=document.getElementById('shape-canvas');
  const drawings=Object.assign(Object.create(null),JSON.parse(document.getElementById('creates-shape-drawings').textContent));
  const ns='http://www.w3.org/2000/svg',field=form.elements.points;
  const width=document.getElementById('shape-width'),height=document.getElementById('shape-height');
  const strokeInput=document.getElementById('shape-stroke');
  const gridSpacing=document.getElementById('shape-grid-spacing'),canvasPadding=document.getElementById('shape-canvas-padding');
  const strokes=Object.assign(Object.create(null),JSON.parse(document.getElementById('creates-shape-strokes').textContent));
  const strokeWidth=()=>Number.isFinite(strokeInput.valueAsNumber)&&strokeInput.validity.valid?strokeInput.valueAsNumber:7;
  let points=[],selected=-1,dragging=false,history=[];
  const remember=()=>{history.push({points:points.map(p=>[...p]),stroke:strokeWidth()});if(history.length>50)history.shift();};
  function preset(kind){
    if(kind==='rectangle')return [[-16,-12],[16,-12],[16,12],[-16,12]];
    if(kind==='diamond')return [[0,-16],[16,0],[0,16],[-16,0]];
    if(kind==='star')return Array.from({length:10},(_,i)=>{const a=i*Math.PI/5-Math.PI/2,r=i%2?7:16;return [r*Math.cos(a),r*Math.sin(a)];});
    if(kind==='heart')return Array.from({length:48},(_,i)=>{const a=i*Math.PI/24;return [16*Math.sin(a)**3,-(13*Math.cos(a)-5*Math.cos(2*a)-2*Math.cos(3*a)-Math.cos(4*a))];});
    return Array.from({length:32},(_,i)=>{const a=i*Math.PI/16;return [16*Math.cos(a),(kind==='circle'?16:11)*Math.sin(a)];});
  }
  function node(tag,attrs){const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));return el;}
  const extent=axis=>Math.max(...points.map(p=>p[axis]))-Math.min(...points.map(p=>p[axis]));
  function syncSize(){width.value=extent(0).toFixed(1);height.value=extent(1).toFixed(1);}
  function render(focus=false){
    field.value=JSON.stringify(points);svg.replaceChildren();
    [[width,'shape-width-range'],[height,'shape-height-range'],[strokeInput,'shape-stroke-range']].forEach(([input,id])=>{
      document.getElementById(id).value=input.value;
    });
    const spacing=Number(gridSpacing.value),padding=Number(canvasPadding.value),half=24+strokeWidth()/2+padding;
    svg.setAttribute('viewBox',`${-half} ${-half} ${half*2} ${half*2}`);
    const defs=node('defs',{}),pattern=node('pattern',{id:'shape-editor-grid',width:spacing,height:spacing,patternUnits:'userSpaceOnUse'});
    pattern.append(node('path',{d:`M ${spacing} 0 H 0 V ${spacing}`,fill:'none',stroke:'#c7bdcf','stroke-width':.15}));defs.append(pattern);svg.append(defs);
    svg.append(node('rect',{x:-half,y:-half,width:half*2,height:half*2,fill:'url(#shape-editor-grid)','pointer-events':'none'}));
    svg.append(node('path',{d:`M ${-half} 0 H ${half} M 0 ${-half} V ${half}`,fill:'none',stroke:'#a897b6','stroke-width':.2,'pointer-events':'none'}));
    document.getElementById('shape-grid-spacing-value').textContent=`${spacing} mm`;
    document.getElementById('shape-canvas-padding-value').textContent=`${padding} mm`;
    document.getElementById('shape-grid-scale').textContent=`Each square represents ${spacing} mm × ${spacing} mm. Screen preview scales to fit.`;
    document.getElementById('shape-measurements').textContent=`${extent(0).toFixed(1)} mm wide × ${extent(1).toFixed(1)} mm high`;
    const outline=node('polygon',{points:points.map(p=>p.join(',')).join(' ')});
    outline.style.strokeWidth=`${strokeWidth()}px`;outline.style.strokeLinejoin='round';svg.append(outline);
    points.forEach(([x,y],i)=>svg.append(node('circle',{cx:x,cy:y,r:.7,tabindex:0,role:'button','aria-label':`Outline dot ${i+1}`,'aria-pressed':String(i===selected),'data-index':i})));
    document.getElementById('shape-delete-point').disabled=selected<0||points.length<=3;
    document.getElementById('shape-undo').disabled=!history.length;
    if(focus)svg.querySelector(`[data-index="${selected}"]`)?.focus();
  }
  const clamp=v=>Math.max(-24,Math.min(24,v));
  function position(event){const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse());return [clamp(p.x),clamp(p.y)];}
  svg.addEventListener('pointerdown',event=>{
    const dot=event.target.closest('[data-index]');remember();
    if(dot)selected=Number(dot.dataset.index);
    else {
      if(points.length>=120){history.pop();return;}
      const p=position(event);let nearest=0,distance=Infinity;
      points.forEach((a,i)=>{const b=points[(i+1)%points.length],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));const d=Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);if(d<distance){distance=d;nearest=i;}});
      if(distance>3){history.pop();return;}
      selected=nearest+1;points.splice(selected,0,p);
    }
    dragging=true;svg.setPointerCapture(event.pointerId);render();event.preventDefault();
  });
  svg.addEventListener('pointermove',event=>{if(!dragging)return;points[selected]=position(event);syncSize();render();});
  const stop=()=>{if(dragging){dragging=false;render(true);}};
  svg.addEventListener('pointerup',stop);svg.addEventListener('pointercancel',stop);
  function remove(){if(selected<0||points.length<=3)return;remember();points.splice(selected,1);selected=Math.min(selected,points.length-1);syncSize();render(true);}
  svg.addEventListener('keydown',event=>{
    const dot=event.target.closest('[data-index]');if(!dot)return;selected=Number(dot.dataset.index);
    if(event.key==='Delete'||event.key==='Backspace'){event.preventDefault();remove();return;}
    const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
    if(delta){event.preventDefault();remember();points[selected]=points[selected].map((v,i)=>clamp(v+delta[i]*(event.shiftKey?2:.5)));syncSize();render(true);}
    else if(event.key===' '||event.key==='Enter'){event.preventDefault();render(true);}
  });
  svg.addEventListener('focusin',event=>{if(event.target.dataset.index!==undefined){selected=Number(event.target.dataset.index);svg.querySelectorAll('circle').forEach((el,i)=>el.setAttribute('aria-pressed',String(i===selected)));document.getElementById('shape-delete-point').disabled=points.length<=3;}});
  [width,height].forEach((slider,axis)=>{
    slider.addEventListener('pointerdown',remember);
    slider.addEventListener('keydown',event=>{if(event.key.startsWith('Arrow'))remember();});
    slider.addEventListener('beforeinput',remember);
    slider.addEventListener('input',()=>{if(!slider.value||!slider.validity.valid)return;const lo=Math.min(...points.map(p=>p[axis])),hi=Math.max(...points.map(p=>p[axis])),centre=(lo+hi)/2;points.forEach(p=>p[axis]=clamp((p[axis]-centre)*Number(slider.value)/(hi-lo||1)));render();});
  });
  [[width,'shape-width-range'],[height,'shape-height-range'],[strokeInput,'shape-stroke-range']].forEach(([input,id])=>{
    const slider=document.getElementById(id);
    slider.addEventListener('pointerdown',remember);
    slider.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key))remember();});
    slider.addEventListener('input',()=>{input.value=slider.value;input.dispatchEvent(new Event('input',{bubbles:true}));});
  });
  [gridSpacing,canvasPadding].forEach(input=>input.addEventListener('input',()=>render()));
  document.getElementById('shape-delete-point').addEventListener('click',remove);
  document.getElementById('shape-undo').addEventListener('click',()=>{if(history.length){const previous=history.pop();points=previous.points;strokeInput.value=previous.stroke;selected=-1;syncSize();render();}});
  strokeInput.addEventListener('beforeinput',remember);
  strokeInput.addEventListener('pointerdown',remember);
  strokeInput.addEventListener('keydown',event=>{if(event.key.startsWith('Arrow'))remember();});
  strokeInput.addEventListener('input',()=>{if(strokeInput.validity.valid)render();});
  document.getElementById('shape-use-preset').addEventListener('click',()=>{remember();points=preset(document.getElementById('shape-preset').value);selected=-1;syncSize();render();});
  document.getElementById('shape-new').addEventListener('click',()=>{form.elements.original.value='';form.elements.name.value='';strokeInput.value=7;points=preset('oval');history=[];selected=-1;document.getElementById('shape-editor-title').textContent='Create a shape';syncSize();render();form.elements.name.focus();});
  document.querySelectorAll('[data-edit-shape]').forEach(button=>button.addEventListener('click',()=>{
    const name=button.dataset.editShape;form.elements.original.value=name;form.elements.name.value=name;
    points=drawings[name]?.map(p=>[...p])||preset(name.toLowerCase());strokeInput.value=strokes[name]??7;history=[];selected=-1;document.getElementById('shape-editor-title').textContent=`Edit ${name}`;syncSize();render();form.scrollIntoView({behavior:'smooth',block:'start'});form.elements.name.focus();
  }));
  document.querySelectorAll('[data-shape-thumbnail]').forEach(el=>{
    const name=el.dataset.shapeThumbnail;if(!drawings[name]&&!['heart','star'].includes(name.toLowerCase()))return;
    const preview=node('svg',{viewBox:'-40 -40 80 80',role:'img','aria-label':name});
    preview.append(node('polygon',{points:(drawings[name]||preset(name.toLowerCase())).map(p=>p.join(',')).join(' '),fill:'#edb4d2',stroke:'#30263a','stroke-width':strokes[name]??7,'stroke-linejoin':'round'}));el.append(preview);
  });
  try{points=JSON.parse(field.value);}catch{points=preset('oval');}
  if(!Array.isArray(points)||points.length<3||points.some(p=>!Array.isArray(p)||p.length!==2||p.some(v=>!Number.isFinite(v))))points=preset('oval');
  form.addEventListener('submit',event=>{const area=Math.abs(points.reduce((sum,p,i)=>sum+points[(i+points.length-1)%points.length][0]*p[1]-p[0]*points[(i+points.length-1)%points.length][1],0))/2;if(area<4){event.preventDefault();document.getElementById('shape-status').textContent='Give the shape a visible filled area before saving.';}});
  syncSize();render();
})();
