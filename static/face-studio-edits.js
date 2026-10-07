/* Studio edits stay in this page; no accounts, uploads or database changes. */
(() => {
 const core=window.CLStudioCore;if(!core)return;
 const get=id=>document.getElementById('edit-'+id),paint=id=>document.getElementById('paint-'+id);
 const panel=document.createElement('details');panel.className='paint-option-group';panel.innerHTML=`<summary>Edit your design</summary><div class="studio-edit-groups">
 <details class="paint-character-group"><summary>Layers and selection</summary><div class="studio-edit-fields">
 <label>Paint on layer<select id="edit-layer"><option value="0">Base colours</option><option value="1">Linework</option><option value="2">Decorations</option></select></label>
 <div id="edit-layer-list"></div><label>Editing mode<select id="edit-mode"><option value="paint">Paint normally</option><option value="select">Select and move a detail</option><option value="delete">Delete a detail by tapping</option></select></label>
 <label>Selected detail<select id="edit-selection"><option value="">None</option></select></label>
 <label>Resize <input id="edit-scale" type="range" min="25" max="200" value="100"><output id="edit-scale-value">100%</output></label>
 <label>Rotate <input id="edit-rotation" type="range" min="-180" max="180" value="0"><output id="edit-rotation-value">0 degrees</output></label>
 <button class="btn" type="button" id="edit-delete">Delete selected detail</button>
 </div></details>
 <details class="paint-character-group"><summary>Colour and finish</summary><div class="studio-edit-fields">
 <label>Replace colour<input type="color" id="edit-from" value="#f52f83"></label><label>With colour<input type="color" id="edit-to" value="#0ea5e9"></label><button class="btn" type="button" id="edit-replace">Replace throughout design</button>
 <label>Paint finish<select id="edit-finish"><option value="matte">Matte</option><option value="metallic">Metallic</option><option value="pearl">Pearl</option><option value="glitter">Glitter</option></select></label>
 <button class="btn" type="button" id="edit-apply-finish">Apply finish to selected detail</button><label><input type="checkbox" id="edit-smooth" checked> Smooth new brush lines</label><button class="btn" type="button" id="edit-smooth-selected">Smooth selected detail</button>
 <p>Choose Blend / soften in the painting tools to soften paint on the active layer.</p>
 </div></details>
 <details class="paint-character-group"><summary>Symmetry</summary><div class="studio-edit-fields"><label>Mirror centre<input id="edit-axis" type="range" min="0" max="600" value="300"><output id="edit-axis-value">50%</output></label><input id="edit-axis-y" type="hidden" value="360"><label>Line angle<input id="edit-axis-angle" type="range" min="-90" max="90" value="0"><output id="edit-axis-angle-value">0 degrees</output></label><button class="btn" type="button" id="edit-place-axis" aria-pressed="false">Place symmetry line on face</button><button class="btn" type="button" id="edit-axis-reset">Centre symmetry line</button><label><input id="edit-show-axis" type="checkbox"> Show symmetry line</label><p>Click for a vertical line, or drag to draw a tilted line. Placement enables mirror painting. The guide is excluded from photos.</p><label>Mirrored area<select id="edit-scope"><option value="whole">Whole face</option><option value="upper">Upper face</option><option value="lower">Lower face</option></select></label><p>Enable Mirror both sides in Brushes and effects. These settings apply to new strokes.</p></div></details>
 <details class="paint-character-group"><summary>Design variations</summary><div class="studio-edit-fields"><label>Variation name<input id="edit-name" maxlength="60" placeholder="My blue butterfly"></label><button class="btn" type="button" id="edit-save">Keep this version and start a variation</button><label>Your versions<select id="edit-versions"><option value="">Choose a version</option></select></label><button class="btn" type="button" id="edit-load">Load version</button><p>Versions are kept in this page only. Download designs before leaving.</p></div></details>
 <p id="edit-status" role="status">Choose a detail to edit, or paint on a layer.</p></div>`;
 document.querySelector('.paint-controls').append(panel);
 const layers=[{name:'Base colours',visible:true},{name:'Linework',visible:true},{name:'Decorations',visible:true}],order=[0,1,2],surfaces=layers.map(()=>Object.assign(document.createElement('canvas'),{width:600,height:720}));
 const activeSurface=Object.assign(document.createElement('canvas'),{width:600,height:720});
 let layersCached=false;
 let selected=-1,drag=null,transform=null,applied={scale:1,rotation:0},selectionSignature='';const undo=[],redo=[],versions=[];
 const clone=x=>JSON.parse(JSON.stringify(x));
 function snapshot(){return {strokes:clone(core.strokes),layers:clone(layers),order:[...order]};}
 function restore(state){core.strokes.splice(0,core.strokes.length,...clone(state.strokes));state.layers.forEach((l,i)=>Object.assign(layers[i],l));order.splice(0,3,...state.order);selected=-1;layerList();core.render();}
 function checkpoint(){undo.push(snapshot());if(undo.length>50)undo.shift();redo.length=0;}
 function notice(text){get('status').textContent=text;}
 function layerList(){get('layer-list').replaceChildren();for(const id of order){const row=document.createElement('div');row.className='studio-layer-row';const label=document.createElement('label'),box=document.createElement('input');box.type='checkbox';box.checked=layers[id].visible;box.onchange=()=>{checkpoint();layers[id].visible=box.checked;core.render();};label.append(box,document.createTextNode(layers[id].name));const button=document.createElement('button');button.className='btn';button.textContent='Bring forward';button.type='button';button.onclick=()=>{checkpoint();order.splice(order.indexOf(id),1);order.push(id);layerList();core.render();};row.append(label,button);get('layer-list').append(row);}}
 function selectedStroke(){return core.strokes[selected];}
 function refresh(){paint('undo').disabled=!undo.length;paint('redo').disabled=!redo.length;const signature=core.strokes.map(stroke=>(stroke.tool||'brush')+':'+(stroke.layer||0)).join('|');if(selectionSignature===signature){get('selection').value=selected>=0?String(selected):'';get('delete').disabled=!selectedStroke();return;}selectionSignature=signature;const select=get('selection');select.replaceChildren(new Option('None',''));core.strokes.forEach((stroke,i)=>{select.add(new Option((i+1)+'. '+(stroke.tool||'brush')+' - '+layers[stroke.layer||0].name,String(i)));});select.value=selected>=0?String(selected):'';get('delete').disabled=!selectedStroke();}
 function center(points){const xs=points.map(p=>p.x),ys=points.map(p=>p.y);return {x:(Math.min(...xs)+Math.max(...xs))/2,y:(Math.min(...ys)+Math.max(...ys))/2};}
 function resetTransform(){transform=null;applied={scale:1,rotation:0};get('scale').value=100;get('rotation').value=0;get('scale-value').value='100%';get('rotation-value').value='0 degrees';}
 get('selection').onchange=()=>{selected=get('selection').value===''?-1:Number(get('selection').value);resetTransform();refresh();};
 function transformInput(){const stroke=selectedStroke();if(!stroke)return;if(!transform){checkpoint();transform={points:clone(stroke.points),size:stroke.size,center:center(stroke.points),scaleStart:applied.scale,rotationStart:applied.rotation};}const scale=Number(get('scale').value)/100/transform.scaleStart,angle=(Number(get('rotation').value)-transform.rotationStart)*Math.PI/180,c=transform.center;
 stroke.points=transform.points.map(p=>{const x=(p.x-c.x)*scale,y=(p.y-c.y)*scale;return {x:c.x+x*Math.cos(angle)-y*Math.sin(angle),y:c.y+x*Math.sin(angle)+y*Math.cos(angle)};});stroke.size=transform.size*scale;get('scale-value').value=get('scale').value+'%';get('rotation-value').value=get('rotation').value+' degrees';core.render();}
 for(const id of ['scale','rotation']){get(id).oninput=transformInput;get(id).onchange=()=>{applied={scale:Number(get('scale').value)/100,rotation:Number(get('rotation').value)};transform=null;};}
 function removeSelected(){if(!selectedStroke())return;checkpoint();core.strokes.splice(selected,1);selected=-1;resetTransform();core.render();notice('Detail removed. Undo restores it.');}
 get('delete').onclick=removeSelected;
 get('replace').onclick=()=>{const from=get('from').value,to=get('to').value;checkpoint();let count=0;for(const stroke of core.strokes){if(stroke.colour.toLowerCase()===from){stroke.colour=to;count++;}if(stroke.cake){stroke.cakeColours=(stroke.cakeColours||core.cakes[stroke.cake]).map(c=>{if(c.toLowerCase()===from){count++;return to;}return c;});}}core.render();notice('Replaced '+count+' colour uses.');};
 get('apply-finish').onclick=()=>{if(!selectedStroke())return;checkpoint();selectedStroke().finish=get('finish').value;core.render();};
 get('smooth-selected').onclick=()=>{if(!selectedStroke())return;checkpoint();selectedStroke().smoothing=true;core.render();};
 const axisOverlay=document.createElement('canvas');axisOverlay.width=600;axisOverlay.height=720;axisOverlay.className='paint-stencil-overlay';axisOverlay.hidden=true;axisOverlay.setAttribute('aria-hidden','true');document.getElementById('paint-board').append(axisOverlay);
 let placingAxis=false,axisStart=null,axisPointer=null;
 function axisGuide(){const ctx=axisOverlay.getContext('2d');ctx.clearRect(0,0,600,720);axisOverlay.hidden=!placingAxis&&!get('show-axis').checked;get('axis-value').value=Math.round(Number(get('axis').value)/6)+'%';get('axis-angle-value').value=get('axis-angle').value+' degrees';if(axisOverlay.hidden)return;const x=Number(get('axis').value),y=Number(get('axis-y').value),a=Number(get('axis-angle').value)*Math.PI/180;ctx.beginPath();ctx.moveTo(x-1000*Math.sin(a),y-1000*Math.cos(a));ctx.lineTo(x+1000*Math.sin(a),y+1000*Math.cos(a));ctx.lineWidth=4;ctx.strokeStyle='#fff';ctx.stroke();ctx.setLineDash([10,8]);ctx.lineWidth=2;ctx.strokeStyle='#7c3aed';ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fillStyle='#7c3aed';ctx.fill();}
 function axisMode(on){placingAxis=on;get('place-axis').setAttribute('aria-pressed',String(on));get('place-axis').textContent=on?'Finish placing line':'Place symmetry line on face';axisGuide();}
 get('place-axis').onclick=()=>{const stencil=document.getElementById('library-place');if(!placingAxis&&stencil?.getAttribute('aria-pressed')==='true')stencil.click();axisMode(!placingAxis);if(placingAxis){paint('mirror').checked=true;paint('mirror').dispatchEvent(new Event('change',{bubbles:true}));notice('Click or drag on the face to place your symmetry line.');}};
 get('axis-reset').onclick=()=>{get('axis').value=300;get('axis-y').value=360;get('axis-angle').value=0;axisGuide();};
 for(const id of ['axis','axis-angle','show-axis'])get(id).addEventListener('input',axisGuide);
 core.canvas.addEventListener('pointerdown',event=>{if(!placingAxis||(event.pointerType==='mouse'&&event.button!==0))return;event.preventDefault();event.stopImmediatePropagation();axisStart=core.point(event);axisPointer=event.pointerId;core.canvas.setPointerCapture(event.pointerId);get('axis').value=Math.max(0,Math.min(600,axisStart.x));get('axis-y').value=Math.max(0,Math.min(720,axisStart.y));get('axis-angle').value=0;axisGuide();},true);
 core.canvas.addEventListener('pointermove',event=>{if(!placingAxis||axisPointer!==event.pointerId)return;event.stopImmediatePropagation();const p=core.point(event),dx=p.x-axisStart.x,dy=p.y-axisStart.y;if(Math.hypot(dx,dy)>5){let angle=Math.atan2(dx,dy)*180/Math.PI;if(angle>90)angle-=180;if(angle<-90)angle+=180;get('axis-angle').value=Math.round(angle);axisGuide();}},true);
 for(const type of ['pointerup','pointercancel','lostpointercapture'])core.canvas.addEventListener(type,event=>{if(!placingAxis||axisPointer!==event.pointerId)return;event.stopImmediatePropagation();axisPointer=null;axisStart=null;get('show-axis').checked=true;axisMode(false);paint('mirror').dispatchEvent(new Event('change',{bubbles:true}));notice('Symmetry line placed. New mirrored strokes follow this line.');},true);
 document.addEventListener('input',event=>{if(event.target.closest('.paint-controls'))axisGuide();});axisGuide();
 function appearance(){const values={};document.querySelectorAll('.paint-controls [id^="paint-"]').forEach(input=>{if(input.matches('input,select'))values[input.id]={value:input.value,checked:input.checked};});return {values,colours:clone(window.CLCharacterColours||{})};}
 get('save').onclick=()=>{if(versions.length>=12){notice('You can keep up to 12 versions in this page. Download the designs you want to keep.');return;}const name=get('name').value.trim()||'Version '+(versions.length+1);versions.push({name,state:snapshot(),appearance:appearance()});get('versions').add(new Option(name,String(versions.length-1)));get('versions').value=String(versions.length-1);notice('Version kept. Continue painting to make a variation.');};
 get('load').onclick=()=>{if(get('versions').value==='')return;const version=versions[Number(get('versions').value)];checkpoint();Object.entries(version.appearance.values).forEach(([id,state])=>{const input=document.getElementById(id);if(input){input.value=state.value;if(input.type==='checkbox')input.checked=state.checked;}});window.CLCharacterColours=clone(version.appearance.colours);paint('model').dispatchEvent(new Event('change'));restore(version.state);core.drawFace();core.render();notice('Loaded '+version.name+'. Undo restores the previous paint.');};
 function distance(p,a,b){const dx=b.x-a.x,dy=b.y-a.y,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);}
 function hit(p){for(const layer of [...order].reverse()){if(!layers[layer].visible)continue;for(let i=core.strokes.length-1;i>=0;i--){const stroke=core.strokes[i];if((stroke.layer||0)!==layer||stroke.tool==='eraser')continue;for(const mirrored of [false,...(stroke.mirror?[true]:[])]){const points=stroke.points.map(point=>mirrored?core.mirrorPoint(point,stroke):point);for(let j=0;j<points.length;j++)if(distance(p,points[Math.max(0,j-1)],points[j])<=Math.max(8,stroke.size))return {index:i,mirrored};}}}return null;}
 window.CLStudioEdits={checkpoint,refresh,snapshot,restore,appearance,
  undo(){if(!undo.length)return;redo.push(snapshot());restore(undo.pop());},redo(){if(!redo.length)return;undo.push(snapshot());restore(redo.pop());},
  strokeSettings(){return {layer:Number(get('layer').value),finish:get('finish').value,smoothing:get('smooth').checked,mirrorAxis:Number(get('axis').value),mirrorAxisY:Number(get('axis-y').value),mirrorAngle:Number(get('axis-angle').value),mirrorScope:get('scope').value};},
  render(draw,strokes,setContext,canvas,active=null,reuseLayers=false){
   const main=canvas.getContext('2d');
   // Completed layers are stable during brush movement. Keep erasing and
   // blending on a copy of the active layer so their compositing stays correct.
   if(!layersCached||!reuseLayers||!active){
    for(const id of order){
     const context=surfaces[id].getContext('2d');context.clearRect(0,0,600,720);setContext(context);
     for(const stroke of strokes){if((stroke.layer||0)!==id)continue;draw(stroke);if(stroke.mirror)draw(stroke,true);}
    }
    layersCached=true;
   }
   for(const id of order){
    if(!layers[id].visible)continue;
    let surface=surfaces[id];
    if(active&&(active.layer||0)===id){
     const context=activeSurface.getContext('2d');context.clearRect(0,0,600,720);context.drawImage(surface,0,0);setContext(context);
     draw(active);if(active.mirror)draw(active,true);surface=activeSurface;
    }
    main.drawImage(surface,0,0);
   }
   setContext(main);
  },
  pointerDown(event,p){if(get('mode').value==='paint')return false;event.preventDefault();const result=hit(p);selected=result?result.index:-1;resetTransform();refresh();if(get('mode').value==='delete'){removeSelected();return true;}if(result){checkpoint();core.canvas.setPointerCapture(event.pointerId);drag={id:event.pointerId,start:p,points:clone(selectedStroke().points),mirrored:result.mirrored};notice('Drag the detail to move it; use Resize and Rotate below.');}return true;},
  pointerMove(event,p){if(!drag||drag.id!==event.pointerId)return false;let dx=p.x-drag.start.x,dy=p.y-drag.start.y;if(drag.mirrored){const s=selectedStroke(),origin={x:s.mirrorAxis??300,y:s.mirrorAxisY??360},reflected=core.mirrorPoint({x:origin.x+dx,y:origin.y+dy},s);dx=reflected.x-origin.x;dy=reflected.y-origin.y;}selectedStroke().points=drag.points.map(point=>({x:point.x+dx,y:point.y+dy}));core.scheduleRender();return true;},
  pointerUp(event){if(!drag||drag.id!==event.pointerId)return false;drag=null;refresh();return true;}
 };
 // Additional illustrated anatomy controls, kept beside the existing finishing details.
 const finishing=[...document.querySelectorAll('.paint-character-group')].find(group=>group.querySelector('summary')?.textContent==='Finishing details');
 for(const [id,title] of [['nose-width','Nose width'],['lip-width','Lip width'],['lip-fullness','Lip fullness'],['cheeks','Cheek fullness'],['brow-angle','Eyebrow angle']]){const li=document.createElement('li'),label=document.createElement('label'),range=document.createElement('input'),output=document.createElement('output');range.id='paint-'+id;range.type='range';range.min=0;range.max=100;range.value=50;output.value='50%';output.className='paint-slider-readout';label.append(document.createTextNode(title),output,range);li.append(label);finishing.querySelector('ul').append(li);range.oninput=()=>{output.value=range.value+'%';core.drawFace();core.render();};}
 function syncFace(){for(const id of ['nose-width','lip-width','lip-fullness','cheeks','brow-angle'])paint(id).disabled=window.CLPortraits.active();}
 paint('model').addEventListener('change',syncFace);syncFace();layerList();core.render();
})();
