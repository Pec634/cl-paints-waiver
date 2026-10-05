(() => {
  'use strict';
  const core=window.CLStudioCore,edits=window.CLStudioEdits;
  if(!core||!edits)return;
  const panel=document.createElement('details');panel.open=false;panel.className='paint-option-group';
  panel.innerHTML=`<summary>Gallery and stencils</summary><div class="paint-library-options">
    <label>Design name<input id="library-name" maxlength="50" placeholder="My butterfly"></label>
    <button type="button" class="btn" id="library-save">Save a new design</button>
    <label>Saved designs<select id="library-designs"><option value="">Choose a design</option></select></label>
    <div class="paint-actions"><button type="button" class="btn" id="library-load">Load</button><button type="button" class="btn" id="library-delete">Delete saved design</button></div>
    <p>Saved on this browser and device, including the character and photo booth. Clearing browser data removes them. Download a photo to keep a separate copy.</p>
    <label>Stencil<select id="library-stencil"><option value="butterfly">Butterfly</option><option value="flower">Flower</option><option value="star">Star</option><option value="web">Spider web</option><option value="scales">Dragon scales</option></select></label>
    <label>Stencil size <output id="library-size-value">100%</output><input id="library-size" type="range" min="25" max="200" value="100"></label>
    <label>Stencil rotation <output id="library-angle-value">0°</output><input id="library-angle" type="range" min="-180" max="180" value="0"></label>
    <canvas id="library-stencil-preview" width="180" height="160" aria-label="Selected stencil preview"></canvas><button type="button" class="btn" id="library-apply" disabled>Apply stencil</button><button type="button" class="btn" id="library-place" aria-pressed="false">Place stencil on face</button><p>Preview the stencil on the face, drag it into position and adjust size or rotation. Apply when ready, or cancel without changing your painting.</p>
    <button type="button" class="btn" id="library-fullscreen">Full-screen painting</button></div>`;
  document.querySelector('.paint-controls').appendChild(panel);
  const get=id=>document.getElementById('library-'+id),paint=id=>document.getElementById('paint-'+id),notice=text=>paint('status').textContent=text;
  const key='cl-paints-studio-gallery-v1';let gallery=[],placing=false;
  try{const saved=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(saved))gallery=saved.filter(d=>d&&typeof d.name==='string'&&d.state&&Array.isArray(d.state.strokes)).slice(0,20);}catch{notice('Saved designs are unavailable in this browser. You can still paint and download.');}
  function list(){get('designs').replaceChildren(new Option('Choose a design',''));gallery.forEach((d,i)=>get('designs').add(new Option(d.name,String(i))));get('load').disabled=get('delete').disabled=get('designs').value==='';}
  function persist(){try{localStorage.setItem(key,JSON.stringify(gallery));return true;}catch{notice('Could not save: browser storage is unavailable or full. Download your design instead.');return false;}}
  get('designs').onchange=()=>{get('load').disabled=get('delete').disabled=get('designs').value==='';};
  get('save').onclick=()=>{
    if(gallery.length>=20){notice('Gallery holds 20 designs. Delete an old saved design to make room.');return;}
    const booth={};document.querySelectorAll('[id^="booth-"]').forEach(input=>{if(input.matches('input,select'))booth[input.id]={value:input.value,checked:input.checked};});
    gallery.push({name:get('name').value.trim()||'Design '+(gallery.length+1),state:edits.snapshot(),appearance:edits.appearance(),cakes:structuredClone(core.cakes),booth});
    if(!persist()){gallery.pop();return;}list();get('designs').value=String(gallery.length-1);get('designs').dispatchEvent(new Event('change'));notice('Design saved on this browser. Save again to keep a new variation.');
  };
  get('load').onclick=()=>{
    const saved=gallery[Number(get('designs').value)];if(!saved||get('designs').value==='')return;
    if(core.strokes.length&&!confirm('Load this design? Save your current design first if you want to keep it.'))return;
    edits.checkpoint();Object.assign(core.cakes,saved.cakes||{});
    for(const cake of Object.keys(saved.cakes||{}))if(![...paint('colour-mode').options].some(option=>option.value===cake))paint('colour-mode').add(new Option('Saved split cake '+cake,cake));
    for(const [id,state] of Object.entries(saved.appearance?.values||{})){const input=document.getElementById(id);if(input){input.value=state.value;if(input.type==='checkbox')input.checked=state.checked;}}
    window.CLCharacterColours=structuredClone(saved.appearance?.colours||{});
    paint('model').dispatchEvent(new Event('change'));edits.restore(structuredClone(saved.state));
    for(const [id,state] of Object.entries(saved.booth||{})){const input=document.getElementById(id);if(input){input.value=state.value;input.checked=state.checked;}}
    document.getElementById('booth-brightness').dispatchEvent(new Event('input',{bubbles:true}));
    core.drawFace();core.render();get('name').value=saved.name;notice('Loaded '+saved.name+'.');
  };
  get('delete').onclick=()=>{if(get('designs').value===''||!confirm('Delete this saved design from this browser?'))return;const index=Number(get('designs').value),removed=gallery.splice(index,1);if(!persist()){gallery.splice(index,0,...removed);return;}list();notice('Saved design deleted. The painting on screen is unchanged.');};
  const circle=(x,y,rx,ry=rx)=>Array.from({length:37},(_,i)=>({x:x+rx*Math.cos(i*Math.PI/18),y:y+ry*Math.sin(i*Math.PI/18)}));
  function pattern(name){
    const custom=window.CLCustomStencils?.pattern(name);if(custom)return custom;
    if(name==='flower')return [...Array.from({length:5},(_,i)=>{const a=i*Math.PI*2/5;return circle(Math.cos(a)*32,Math.sin(a)*32,22);}),circle(0,0,12)];
    if(name==='butterfly')return [circle(-30,-20,28,35),circle(30,-20,28,35),circle(-24,28,22,25),circle(24,28,22,25),[{x:0,y:-45},{x:0,y:50}],[{x:0,y:-35},{x:-14,y:-60}],[{x:0,y:-35},{x:14,y:-60}]];
    if(name==='star')return [Array.from({length:11},(_,i)=>{const a=i*Math.PI/5-Math.PI/2,r=i%2?22:50;return {x:Math.cos(a)*r,y:Math.sin(a)*r};})];
    if(name==='web')return [...Array.from({length:8},(_,i)=>{const a=i*Math.PI/4;return [{x:0,y:0},{x:Math.cos(a)*55,y:Math.sin(a)*55}];}),...Array.from({length:3},(_,j)=>Array.from({length:9},(_,i)=>({x:Math.cos(i*Math.PI/4)*(j+1)*18,y:Math.sin(i*Math.PI/4)*(j+1)*18})))];
    return Array.from({length:9},(_,i)=>Array.from({length:19},(_,j)=>({x:(i%3-1)*32+(Math.floor(i/3)%2)*16+16*Math.cos(j*Math.PI/18),y:(Math.floor(i/3)-1)*24+16*Math.sin(j*Math.PI/18)})));
  }
  const overlay=document.createElement('canvas');overlay.width=600;overlay.height=720;overlay.className='paint-stencil-overlay';overlay.hidden=true;overlay.setAttribute('aria-hidden','true');document.getElementById('paint-board').appendChild(overlay);
  let position={x:300,y:350},dragPointer=null;
  function paths(){const scale=Number(get('size').value)/100,a=Number(get('angle').value)*Math.PI/180;return pattern(get('stencil').value).map(path=>path.map(v=>({x:position.x+scale*(v.x*Math.cos(a)-v.y*Math.sin(a)),y:position.y+scale*(v.x*Math.sin(a)+v.y*Math.cos(a))})));}
  const thumbnailSurface=document.createElement('canvas');thumbnailSurface.width=600;thumbnailSurface.height=720;
  function previewStrokes(){return paths().map(path=>({...edits.strokeSettings(),tool:'brush',colour:paint('colour').value,size:Number(paint('size').value),opacity:Number(paint('opacity').value),mirror:paint('mirror').checked,points:path}));}
  function preview(){
    const strokes=previewStrokes();core.renderPreview(thumbnailSurface,strokes);
    const thumb=get('stencil-preview').getContext('2d');thumb.clearRect(0,0,180,160);thumb.drawImage(thumbnailSurface,0,0,600,720,23,0,133,160);
    core.renderPreview(overlay,placing?strokes:[]);
    overlay.style.filter=core.canvas.style.filter;
  }
  function placement(on){placing=on;overlay.hidden=!on;get('apply').disabled=!on;get('place').setAttribute('aria-pressed',String(on));get('place').textContent=on?'Cancel preview':'Preview stencil on face';preview();}
  get('place').onclick=()=>{const axis=document.getElementById('edit-place-axis');if(!placing&&axis?.getAttribute('aria-pressed')==='true')axis.click();placement(!placing);notice(placing?'Drag the stencil into position, adjust size and rotation, then Apply stencil.':'Preview cancelled. Painting unchanged.');};
  get('apply').onclick=()=>{if(!placing)return;edits.checkpoint();core.strokes.push(...previewStrokes());placement(false);core.render();notice('Stencil applied. Undo removes the whole stencil.');};
  for(const [id,suffix] of [['size','%'],['angle',' degrees']])get(id).oninput=()=>{get(id+'-value').value=get(id).value+suffix;preview();};
  get('stencil').onchange=preview;
  for(const type of ['input','change','click'])document.addEventListener(type,event=>{if(event.target.closest('.paint-controls,.paint-fullscreen-bar'))requestAnimationFrame(preview);});
  core.canvas.addEventListener('pointerdown',event=>{if(!placing||(event.pointerType==='mouse'&&event.button!==0))return;event.preventDefault();event.stopImmediatePropagation();position=core.point(event);dragPointer=event.pointerId;core.canvas.setPointerCapture(event.pointerId);preview();},true);
  core.canvas.addEventListener('pointermove',event=>{if(!placing)return;event.stopImmediatePropagation();if(dragPointer===event.pointerId){position=core.point(event);preview();}},true);
  for(const type of ['pointerup','pointercancel','lostpointercapture'])core.canvas.addEventListener(type,event=>{if(!placing)return;event.stopImmediatePropagation();dragPointer=null;},true);
  preview();
  const studio=document.querySelector('.paint-studio'),bar=document.createElement('div');bar.className='paint-fullscreen-bar';bar.hidden=true;
  bar.innerHTML='<button type="button" class="btn" data-action="exit">Exit full screen</button><label>Colour<input type="color" value="#f52f83"></label><label>Brush size<input type="range" min="2" max="50" value="12"></label><button type="button" class="btn" data-action="undo">Undo</button><button type="button" class="btn" data-action="download">Take photo</button>';
  studio.prepend(bar);let previousOverflow='';
  function full(open){studio.classList.toggle('paint-fullscreen',open);bar.hidden=!open;if(open){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';bar.querySelector('[type=color]').value=paint('colour').value;bar.querySelector('[type=range]').value=paint('size').value;}else document.body.style.overflow=previousOverflow;window.dispatchEvent(new Event('resize'));if(!open)get('fullscreen').focus();}
  get('fullscreen').onclick=()=>full(true);
  bar.onclick=event=>{const action=event.target.dataset.action;if(action==='exit')full(false);else if(action)paint(action).click();};
  bar.querySelector('[type=color]').oninput=event=>{paint('colour').value=event.target.value;paint('colour').dispatchEvent(new Event('input'));};
  bar.querySelector('[type=range]').oninput=event=>{paint('size').value=event.target.value;paint('size-value').value=event.target.value;paint('size').dispatchEvent(new Event('input'));};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&studio.classList.contains('paint-fullscreen'))full(false);});list();
  document.querySelectorAll('.paint-controls details').forEach(group=>group.open=false);
})();
