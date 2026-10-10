(() => {
 const config=JSON.parse(document.getElementById('builder-data').textContent),frame=document.getElementById('builder-preview'),field=id=>document.getElementById('builder-'+id);
 let edits=config.layout,selected=null,mobile=false,deviceName="desktop",dirty=false,undo=[],redo=[];
 const editor=()=>frame.contentWindow.websiteEditor;
 const styles=[...document.querySelectorAll('[data-builder-style]')];
 const clone=value=>structuredClone(value);
 async function readResponse(response){
   if(response.redirected&&new URL(response.url).pathname.includes('/admin/login'))throw Error('Your admin session has ended. Sign in again, then retry.');
   const contentType=response.headers.get('content-type')||'';
   if(!contentType.includes('application/json')){
     const messages={400:'The form has expired. Refresh this page and retry.',401:'Sign in again, then retry.',403:'Sign in again, then retry.',413:'The upload is too large. Choose a file under 10 MB.',500:'The server could not process this upload. Check the Render error logs.',502:'The server is temporarily unavailable. Retry shortly.',503:'The server is temporarily unavailable. Retry shortly.'};
     throw Error(messages[response.status]||`The server returned an unexpected response (HTTP ${response.status}). Refresh this page and retry.`);
   }
   const result=await response.json();if(!response.ok)throw Error(result.error||`Request failed (HTTP ${response.status}).`);return result;
 }
 function initialise(){edits._blocks??=[];edits._seo??={};field('seo-title').value=edits._seo.title||'';field('seo-description').value=edits._seo.description||'';}
 initialise();
 function checkpoint(){undo.push(clone(edits));if(undo.length>100)undo.shift();redo=[];dirty=true;field('undo').disabled=false;field('redo').disabled=true;field('status').textContent='Unsaved changes';}
 function current(){if(selected===null)return null;if(typeof selected==='number')return edits[editor().keys[selected]]??={};return selected.cell===undefined?edits._blocks[selected.row]:edits._blocks[selected.row].cells[selected.cell];}
 function enrich(item){if(item.photo){const option=[...field('photo').options].find(o=>o.value===item.photo);item.image=option?.dataset.src||'';item.alt=option?.dataset.alt||'';}}
 function apply(){if(!editor())return;const data=clone(edits);Object.entries(data).forEach(([k,e])=>{if(!k.startsWith('_'))enrich(e);});data._blocks?.forEach(r=>r.cells.forEach(enrich));editor().apply(data,deviceName);renderLists();updateResizeHandle();}
 function button(label,fn){const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label;b.onclick=fn;return b;}
 function renderLists(){
   const list=field('rows');list.replaceChildren();edits._blocks.forEach((row,r)=>{const entry=document.createElement('div');entry.className='builder-row-actions';entry.append(button(`Row ${r+1}`,()=>choose({row:r})),button('↑',()=>moveRow(r,-1)),button('↓',()=>moveRow(r,1)),button('Duplicate',()=>{checkpoint();edits._blocks.splice(r+1,0,clone(row));apply();}),button('Remove',()=>{checkpoint();edits._blocks.splice(r,1);selected=null;field('controls').hidden=true;apply();}));row.cells.forEach((cell,c)=>entry.append(button(`${c+1}: ${cell.kind}`,()=>choose({row:r,cell:c}))));const location=document.createElement('select');location.add(new Option('After existing sections','-1'));editor()?.sections.forEach((section,i)=>location.add(new Option('Before '+(section.querySelector('h1,h2')?.textContent||`section ${i+1}`).slice(0,50),i)));location.value=row.before??-1;location.setAttribute('aria-label',`Placement for row ${r+1}`);location.onchange=()=>{checkpoint();row.before=Number(location.value);apply();};entry.append(location);list.append(entry);});
   const sections=field('sections');sections.replaceChildren();const order=edits._sections?.length?edits._sections:editor()?.sections.map((_,i)=>i)||[];order.forEach((index,place)=>{const entry=document.createElement('div');entry.className='builder-row-actions';const label=document.createElement('span');label.textContent=(editor().sections[index]?.querySelector('h1,h2')?.textContent||`Section ${index+1}`).slice(0,60);entry.append(label);[-1,1].forEach(delta=>entry.append(button(delta<0?'↑':'↓',()=>{const target=place+delta;if(target<0||target>=order.length)return;checkpoint();edits._sections=[...order];[edits._sections[place],edits._sections[target]]=[edits._sections[target],edits._sections[place]];apply();})));sections.append(entry);});
 }
 function moveRow(index,delta){const target=index+delta;if(target<0||target>=edits._blocks.length)return;checkpoint();[edits._blocks[index],edits._blocks[target]]=[edits._blocks[target],edits._blocks[index]];selected=null;field('controls').hidden=true;apply();}
 function choose(selection){selected=selection;const edit=current(),node=typeof selected==='number'?editor().nodes[selected]:null,isCell=typeof selected==='object'&&selected.cell!==undefined,isRow=typeof selected==='object'&&!isCell;
   field('controls').hidden=false;field('selection').textContent=node?`Selected ${node.tagName.toLowerCase()}`:isRow?`Row ${selected.row+1}`:`Row ${selected.row+1}, block ${selected.cell+1}`;
   field('cell-kind').parentElement.hidden=!isCell;field('cell-kind').value=edit.kind||'text';
   field('text').parentElement.hidden=isRow||node?.tagName==='IMG';field('text').value=edit.text??node?.textContent??'';
   field('caption').parentElement.hidden=!isCell||edit.kind!=='review';field('caption').value=edit.caption||'';
   field('photo').parentElement.hidden=!(node?.tagName==='IMG'||isCell&&edit.kind==='image');field('photo').value=edit.photo||'';
   field('link').parentElement.hidden=!(node?.tagName==='A'||isCell&&['button','image'].includes(edit.kind));field('link').value=edit.link??node?.getAttribute('href')??'';
   field('video').parentElement.hidden=!isCell||edit.kind!=='video';field('video').value=edit.video||'';
   const position=edit[deviceName]||{};['x','y','width'].forEach(k=>field(k).value=position[k]||0);
   styles.forEach(input=>input.value=edit.style?.[input.dataset.builderStyle]??(input.type==='number'?0:''));
   const animation=edit.animation||{};field('animation').value=animation.kind||'none';['duration','delay','repeat','easing','trigger'].forEach(k=>field(k).value=animation[k]??({duration:1,delay:0,repeat:1,easing:'ease',trigger:'load'}[k]));
   field('controls').querySelectorAll('input,select,textarea').forEach(input=>input.disabled=!!edit.locked);
   editor().nodes.forEach(n=>n.style.outline='');if(node)node.style.outline='3px solid #ff2785';
   updateResizeHandle();
 }
 frame.addEventListener('load',()=>{if(!editor())return;Object.keys(edits).filter(k=>/^\d+$/.test(k)).forEach(k=>{if(editor().keys[k]){edits[editor().keys[k]]??=edits[k];delete edits[k];}});apply();editor().nodes.forEach((node,i)=>{
   node.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(i);});
   node.addEventListener('pointerdown',event=>beginDrag(event,i));
   if(node.tagName==='IMG'){node.draggable=false;node.style.touchAction='none';node.style.cursor='move';}
 });frame.contentDocument.addEventListener('pointerdown',event=>{const cell=event.target.closest('[data-builder-cell]');if(cell)beginDrag(event,{row:Number(cell.closest('[data-builder-row]').dataset.builderRow),cell:Number(cell.dataset.builderCell)});});
 frame.contentDocument.addEventListener('dragstart',event=>event.preventDefault());
 frame.contentDocument.addEventListener('click',event=>{const cell=event.target.closest('[data-builder-cell]');if(cell){event.preventDefault();choose({row:Number(cell.closest('[data-builder-row]').dataset.builderRow),cell:Number(cell.dataset.builderCell)});}else if(event.target.closest('a'))event.preventDefault();});});
 function beginDrag(event,selection){
   if(event.button!==0)return;event.preventDefault();event.stopPropagation();choose(selection);
   const item=current();if(item.locked)return;
   const doc=frame.contentDocument,device=deviceName,initial=clone(item[device]||item.desktop||{}),startX=event.clientX,startY=event.clientY,pointerId=event.pointerId;
   const target=selectedNode(),rect=target.getBoundingClientRect(),anchors=snapAnchors(target);
   if(event.isTrusted)doc.body.setPointerCapture(pointerId);
   let moved=false;
   const move=event=>{
     if(event.pointerId!==pointerId)return;
     const dx=event.clientX-startX,dy=event.clientY-startY;
     if(!moved&&Math.hypot(dx,dy)<3)return;
     if(!moved){checkpoint();moved=true;}
     const snap=value=>field('snap').checked?Math.round(value/10)*10:Math.round(value);
     let x=snap((initial.x||0)+dx),y=snap((initial.y||0)+dy);
     clearAlignmentGuides();
     if(field('snap').checked){
       const horizontal=nearestSnap([rect.left+dx,rect.left+rect.width/2+dx,rect.right+dx],anchors.x);
       const vertical=nearestSnap([rect.top+dy,rect.top+rect.height/2+dy,rect.bottom+dy],anchors.y);
       if(horizontal){x=(initial.x||0)+dx+horizontal.delta;showAlignmentGuide('x',horizontal.anchor);}
       if(vertical){y=(initial.y||0)+dy+vertical.delta;showAlignmentGuide('y',vertical.anchor);}
     }
     item[device]={...initial,x:Math.max(-2000,Math.min(2000,x)),y:Math.max(-2000,Math.min(2000,y))};
     apply();showSpacingGuides();field('x').value=item[device].x;field('y').value=item[device].y;
   };
   const end=event=>{if(event.pointerId!==pointerId)return;clearAlignmentGuides();if(doc.body.hasPointerCapture(pointerId))doc.body.releasePointerCapture(pointerId);doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',end);doc.removeEventListener('pointercancel',end);};
   doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',end);doc.addEventListener('pointercancel',end);
 }
 function snapAnchors(target){
   const doc=frame.contentDocument,parent=target.parentElement.getBoundingClientRect();
   const anchors={x:[parent.left,(parent.left+parent.right)/2,parent.right,0,frame.contentWindow.innerWidth/2,frame.contentWindow.innerWidth],y:[parent.top,parent.bottom]};
   doc.querySelectorAll('#content img').forEach(node=>{
     if(node===target||target.contains(node)||node.contains(target)||node.hidden)return;
     const rect=node.getBoundingClientRect();if(!rect.width||!rect.height)return;
     anchors.x.push(rect.left,rect.left+rect.width/2,rect.right);anchors.y.push(rect.top,rect.top+rect.height/2,rect.bottom);
   });return anchors;
 }
 function nearestSnap(points,anchors){
   let best=null;for(const point of points)for(const anchor of anchors){const delta=anchor-point;if(Math.abs(delta)<=8&&(!best||Math.abs(delta)<Math.abs(best.delta)))best={delta,anchor};}return best;
 }
 function clearAlignmentGuides(){frame.contentDocument?.querySelectorAll('.builder-alignment-guide,.builder-spacing-guide').forEach(node=>node.remove());}
 function showSpacingGuides(){
   const doc=frame.contentDocument,target=selectedNode(),image=target?.tagName==='IMG'?target:target?.querySelector('img');if(!image)return;
   doc.querySelectorAll('.builder-spacing-guide').forEach(node=>node.remove());
   const rect=image.getBoundingClientRect(),nearest={};
   doc.querySelectorAll('#content img').forEach(other=>{
     if(other===image||target.contains(other)||other.hidden)return;
     const r=other.getBoundingClientRect();if(!r.width||!r.height)return;
     const verticalOverlap=Math.min(rect.bottom,r.bottom)>Math.max(rect.top,r.top),horizontalOverlap=Math.min(rect.right,r.right)>Math.max(rect.left,r.left);
     const add=(side,gap,start,end,cross,axis)=>{if(!nearest[side]||gap<nearest[side].gap)nearest[side]={gap,start,end,cross,axis};};
     if(verticalOverlap){const y=(Math.max(rect.top,r.top)+Math.min(rect.bottom,r.bottom))/2;if(r.right<=rect.left)add('left',rect.left-r.right,r.right,rect.left,y,'x');if(r.left>=rect.right)add('right',r.left-rect.right,rect.right,r.left,y,'x');}
     if(horizontalOverlap){const x=(Math.max(rect.left,r.left)+Math.min(rect.right,r.right))/2;if(r.bottom<=rect.top)add('top',rect.top-r.bottom,r.bottom,rect.top,x,'y');if(r.top>=rect.bottom)add('bottom',r.top-rect.bottom,rect.bottom,r.top,x,'y');}
   });
   Object.values(nearest).forEach(({gap,start,end,cross,axis})=>{
     const line=doc.createElement('div');line.className='builder-spacing-guide';line.style.cssText='position:fixed;pointer-events:none;z-index:99998;color:#fff;background:#a32bc4;font:12px Arial;'+(axis==='x'?`left:${start}px;top:${cross}px;width:${end-start}px;height:2px;`:`top:${start}px;left:${cross}px;height:${end-start}px;width:2px;`);
     const label=doc.createElement('span');label.textContent=Math.round(gap)+' px';label.style.cssText='position:absolute;background:#a32bc4;border-radius:4px;padding:3px 6px;white-space:nowrap;'+(axis==='x'?'left:50%;top:-24px;transform:translateX(-50%);':'top:50%;left:5px;transform:translateY(-50%);');line.append(label);doc.body.append(line);
   });
 }
 function showAlignmentGuide(axis,value){
   const guide=frame.contentDocument.createElement('div');guide.className='builder-alignment-guide';
   guide.style.cssText='position:fixed;pointer-events:none;z-index:99998;background:#00a6b8;box-shadow:0 0 0 1px white;'+(axis==='x'?`left:${value}px;top:0;bottom:0;width:2px;`:`top:${value}px;left:0;right:0;height:2px;`);
   frame.contentDocument.body.append(guide);
 }
 function changeControls(){if(selected===null||current().locked)return;checkpoint();const edit=current();edit[deviceName]={x:Number(field('x').value),y:Number(field('y').value),width:Number(field('width').value)};
   if(!field('text').parentElement.hidden)edit.text=field('text').value;if(!field('caption').parentElement.hidden)edit.caption=field('caption').value;
   if(!field('photo').parentElement.hidden){if(field('photo').value)edit.photo=field('photo').value;else delete edit.photo;}
   if(!field('link').parentElement.hidden)edit.link=field('link').value;if(!field('video').parentElement.hidden)edit.video=field('video').value;
   edit.style={};styles.forEach(input=>{if(input.value!=='')edit.style[input.dataset.builderStyle]=input.type==='number'?Number(input.value):input.value;});
   edit.animation={kind:field('animation').value,duration:Number(field('duration').value),delay:Number(field('delay').value),repeat:Number(field('repeat').value),easing:field('easing').value,trigger:field('trigger').value};apply();
 }
 ['text','caption','photo','link','video','x','y','width','animation','duration','delay','repeat','easing','trigger'].forEach(k=>field(k).addEventListener('input',changeControls));styles.forEach(input=>input.addEventListener('input',changeControls));
 field('cell-kind').onchange=()=>{checkpoint();current().kind=field('cell-kind').value;apply();choose(selected);};
 field('add').onclick=()=>{checkpoint();const kind=field('kind').value;edits._blocks.push({before:-1,cells:Array.from({length:Number(field('columns').value)},(_,i)=>({kind:i===0?kind:'text',text:i===0?'Your new content':'Add your text'}))});apply();choose({row:edits._blocks.length-1,cell:0});};
 field('reset').onclick=()=>{checkpoint();if(typeof selected==='number')delete edits[editor().keys[selected]];else if(selected.cell!==undefined){const cell=current();edits._blocks[selected.row].cells[selected.cell]={kind:cell.kind,text:''};}else{const cells=current().cells;edits._blocks[selected.row]={before:-1,cells};}apply();choose(selected);};
 function history(source,target){if(!source.length)return;target.push(clone(edits));edits=source.pop();selected=null;field('controls').hidden=true;dirty=true;initialise();apply();field('undo').disabled=!undo.length;field('redo').disabled=!redo.length;field('status').textContent='Unsaved changes';}
 field('undo').onclick=()=>history(undo,redo);field('redo').onclick=()=>history(redo,undo);
 field('device').onclick=()=>{mobile=!mobile;deviceName=mobile?'mobile':'desktop';frame.style.width=mobile?'390px':'100%';field('device').textContent=mobile?'Desktop preview':'Mobile preview';apply();if(selected!==null)choose(selected);};
 field('page').onchange=()=>{if(dirty&&!confirm('Discard unsaved changes?')){field('page').value=config.page;return;}location.href='?page='+field('page').value;};
 ['title','description'].forEach(k=>field('seo-'+k).oninput=()=>{checkpoint();edits._seo[k]=field('seo-'+k).value;});
 async function save(action){field('save').disabled=field('draft').disabled=true;field('status').textContent='Saving…';try{const response=await fetch(location.pathname,{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams({page:config.page,csrf_token:config.csrf,action,revision:field('revision').value,layout:JSON.stringify(edits)})}),result=await readResponse(response);if(!response.ok)throw Error(result.error||'Save failed');if(action==='restore'){checkpoint();edits=result.layout;initialise();apply();selected=null;field('controls').hidden=true;}dirty=false;field('status').textContent=result.published?'Published to website':action==='restore'?'Restored as private draft':'Draft saved privately';if(action==='publish')location.reload();}catch(error){field('status').textContent=error.message;}finally{field('save').disabled=field('draft').disabled=false;}}
 field('save').onclick=()=>save('publish');field('draft').onclick=()=>save('draft');field('restore').onclick=()=>{if(field('revision').value&&(!dirty||confirm('Replace unsaved work with this version?')))save('restore');};
 function uploadSource(){const drive=field('upload-source').value==='drive',form=field('upload');field('device-photo').hidden=drive;field('drive-photo').hidden=!drive;form.elements.images.disabled=drive;form.elements.images.required=!drive;form.elements.drive_url.disabled=!drive;form.elements.drive_url.required=drive;}
 field('upload-source').onchange=uploadSource;
 field('upload').onsubmit=async event=>{event.preventDefault();const form=event.target,button=form.querySelector('button');button.disabled=true;field('upload-status').textContent='Uploading…';try{const data=new FormData(form),response=await fetch('/admin/photo-library/upload',{method:'POST',headers:{Accept:'application/json'},body:data}),result=await readResponse(response);if(!response.ok)throw Error(result.error||'Upload failed');for(const photo of result.photos){const approved=await fetch('/admin/photo-library/assets/'+photo.id,{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams({csrf_token:config.csrf,status:'approved',reviewed_permissions:'yes',alt:data.get('alt')})});await readResponse(approved);const option=new Option(data.get('alt'),photo.key);option.dataset.src=photo.url;option.dataset.alt=data.get('alt');field('photo').add(option);}field('upload-status').textContent='Uploaded. Select an image block and choose the new photo.';form.reset();uploadSource();}catch(error){field('upload-status').textContent=error.message;}finally{button.disabled=false;}};
 const oldRender=renderLists;renderLists=function(){oldRender();const list=field('layers');list.replaceChildren();editor()?.nodes.forEach((node,i)=>{const edit=edits[editor().keys[i]]||{};list.append(button(`${edit.hidden?'Hidden · ':''}${edit.locked?'Locked · ':''}${node.tagName.toLowerCase()} · ${(node.alt||node.textContent).slice(0,40)}`,()=>choose(i)));});};
 function grid(){const doc=frame.contentDocument;if(!doc?.body)return;doc.getElementById('builder-grid-guides')?.remove();if(!field('snap').checked)return;const overlay=doc.createElement('div');overlay.id='builder-grid-guides';overlay.style.cssText='position:fixed;inset:0;pointer-events:none;z-index:1000;background-image:linear-gradient(to right,#f52f8315 1px,transparent 1px),linear-gradient(to bottom,#f52f8315 1px,transparent 1px);background-size:10px 10px;';doc.body.append(overlay);}
 frame.addEventListener('load',grid);field('snap').onchange=grid;
 function selectedNode(){return typeof selected==='number'?editor().nodes[selected]:frame.contentDocument.querySelector(`[data-builder-row="${selected?.row}"]${selected?.cell!==undefined?' [data-builder-cell="'+selected.cell+'"]':''}`);}
 field('size').onchange=()=>{deviceName=field('size').value;mobile=deviceName==='mobile';frame.style.width=deviceName==='mobile'?'390px':deviceName==='tablet'?'820px':'100%';apply();if(selected!==null)choose(selected);};
 field('replay').onclick=()=>{const doc=frame.contentDocument;doc.querySelectorAll('.wb-animated').forEach(node=>{node.style.animationName='none';void node.offsetWidth;node.style.animationName='';});};
 ['hide','lock'].forEach(action=>field(action).onclick=()=>{if(selected===null)return;checkpoint();const item=current(),key=action==='hide'?'hidden':'locked';item[key]=!item[key];apply();choose(selected);});
 let resizeRequested=false,resizing=false;
 function updateResizeHandle(){
   const doc=frame.contentDocument;if(!doc?.body)return;
   const node=selected===null?null:selectedNode(),image=node?.tagName==='IMG'?node:node?.querySelector('img');
   if(!node||current().locked||node.hidden||(!image&&!resizeRequested)){doc.querySelectorAll('.builder-resize-handle').forEach(handle=>handle.remove());return;}
   const directions=['nw','n','ne','e','se','s','sw','w'];
   for(const direction of directions){
     const id=direction==='se'?'builder-resize-handle':'builder-resize-'+direction;
     let handle=doc.getElementById(id);
     if(!handle){
       handle=doc.createElement('button');handle.id=id;handle.className='builder-resize-handle';handle.type='button';handle.dataset.direction=direction;
       handle.textContent=direction.length===1?(direction==='n'||direction==='s'?'↕':'↔'):(direction==='nw'||direction==='se'?'⤡':'⤢');
       handle.setAttribute('aria-label','Resize '+({n:'top',s:'bottom',e:'right',w:'left',nw:'top left',ne:'top right',sw:'bottom left',se:'bottom right'}[direction]));
       handle.title='Drag to resize. Hold Shift on a corner to keep proportions.';
       const cursor=direction.length===1?(direction==='n'||direction==='s'?'ns':'ew'):(direction==='nw'||direction==='se'?'nwse':'nesw');
       handle.style.cssText='position:fixed;z-index:99999;background:#f52f83;color:white;width:32px;height:32px;font-size:22px;padding:0;cursor:'+cursor+'-resize;border:2px solid white;border-radius:8px;box-shadow:0 2px 8px #0006;touch-action:none;';
       handle.onclick=event=>{event.preventDefault();event.stopPropagation();};
       handle.onpointerdown=event=>{
         if(event.button!==0)return;event.preventDefault();event.stopPropagation();
         const target=selectedNode(),photo=target.tagName==='IMG'?target:target.querySelector('img'),rect=target.getBoundingClientRect(),photoRect=(photo||target).getBoundingClientRect();
         const parentStyle=frame.contentWindow.getComputedStyle(target.parentElement),parentWidth=target.parentElement.clientWidth-parseFloat(parentStyle.paddingLeft)-parseFloat(parentStyle.paddingRight);if(!parentWidth)return;
         const item=current(),device=deviceName,initial=clone(item[device]||item.desktop||{}),startX=event.clientX,startY=event.clientY,handleRect=handle.getBoundingClientRect(),anchors=snapAnchors(target);
         const west=direction.includes('w'),north=direction.includes('n'),horizontal=west||direction.includes('e'),vertical=north||direction.includes('s');
         checkpoint();resizing=true;handle.setPointerCapture(event.pointerId);
         handle.onpointermove=move=>{
           const dx=move.clientX-startX,dy=move.clientY-startY;if(Math.hypot(dx,dy)<3)return;
           handle.style.left=handleRect.left+(horizontal?dx:0)+'px';handle.style.top=handleRect.top+(vertical?dy:0)+'px';
           const delta=value=>field('snap').checked?Math.round(value/10)*10:value;
           let width=rect.width+(horizontal?(west?-1:1)*delta(dx):0),height=photoRect.height+(vertical?(north?-1:1)*delta(dy):0);
           clearAlignmentGuides();
           if(field('snap').checked){
             const sx=horizontal?nearestSnap([west?rect.left+dx:rect.right+dx],anchors.x):null;
             const sy=vertical?nearestSnap([north?photoRect.top+dy:photoRect.bottom+dy],anchors.y):null;
             if(sx){width=west?rect.right-sx.anchor:sx.anchor-rect.left;showAlignmentGuide('x',sx.anchor);}
             if(sy){height=north?photoRect.bottom-sy.anchor:sy.anchor-photoRect.top;showAlignmentGuide('y',sy.anchor);}
           }
           width=Math.max(parentWidth*.05,Math.min(parentWidth,width));height=Math.max(20,Math.min(1200,height));
           if(move.shiftKey&&horizontal&&vertical){height=width*photoRect.height/rect.width;if(height>1200||height<20){height=Math.max(20,Math.min(1200,height));width=height*rect.width/photoRect.height;}}
           item[device]={...initial};
           if(horizontal)item[device].width=width/parentWidth*100;
           if(west)item[device].x=(initial.x||0)+rect.width-width;
           if(north)item[device].y=(initial.y||0)+photoRect.height-height;
           if(vertical){item.style??={};item.style.height=Math.round(height);if(photo)item.style.objectFit||='cover';}
           field('width').value=item[device].width||0;field('x').value=item[device].x||0;field('y').value=item[device].y||0;
           if(item.style?.height!==undefined)styles.find(input=>input.dataset.builderStyle==='height').value=item.style.height;
           apply();showSpacingGuides();
         };
         const finish=()=>{resizing=false;clearAlignmentGuides();handle.onpointermove=null;handle.onpointerup=null;handle.onpointercancel=null;updateResizeHandle();};
         handle.onpointerup=finish;handle.onpointercancel=finish;
       };
       doc.body.append(handle);
     }
     if(!resizing){const rect=(image||node).getBoundingClientRect(),x=direction.includes('w')?rect.left:direction.includes('e')?rect.right:rect.left+rect.width/2,y=direction.includes('n')?rect.top:direction.includes('s')?rect.bottom:rect.top+rect.height/2;handle.style.left=Math.max(0,Math.min(frame.contentWindow.innerWidth-32,x-16))+'px';handle.style.top=y-16+'px';}
   }
   if(image){image.draggable=false;image.style.touchAction='none';image.style.cursor='move';}
 }
 field('resize').onclick=()=>{resizeRequested=true;updateResizeHandle();};
 frame.addEventListener('load',()=>{frame.contentWindow.addEventListener('scroll',updateResizeHandle,true);frame.contentWindow.addEventListener('resize',updateResizeHandle);});
 field('crop').onclick=()=>{const selectedElement=selectedNode(),image=selectedElement?.tagName==='IMG'?selectedElement:selectedElement?.querySelector('img');if(!image){field('status').textContent='Select an image first.';return;}field('status').textContent='Click the important area of the image to choose its focal point.';image.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();const rect=image.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width,y=(event.clientY-rect.top)/rect.height;checkpoint();current().style??={};current().style.objectPosition=x<.25?'left':x>.75?'right':y<.25?'top':y>.75?'bottom':'center';current().style.objectFit='cover';apply();choose(selected);},{once:true,capture:true});};
 field('check').onclick=()=>{const messages=[];frame.contentDocument.querySelectorAll('#content img:not([hidden])').forEach(n=>{if(!n.alt?.trim())messages.push('An image needs a description.');});frame.contentDocument.querySelectorAll('#content a').forEach(n=>{if(!n.getAttribute('href')||n.getAttribute('href')==='#')messages.push('A button or link needs a destination.');});frame.contentDocument.querySelectorAll('#content img,#content p,#content h1,#content h2,.wb-cell').forEach(n=>{const r=n.getBoundingClientRect();if(!n.hidden&&(r.left<0||r.right>frame.contentWindow.innerWidth+2))messages.push('Content extends beyond the preview width.');});field('checks').textContent=[...new Set(messages)].join(' ')||'No missing descriptions, placeholder links or horizontal overflow found in this preview.';};
 let compare=false;field('compare').onclick=()=>{if(!editor())return;compare=!compare;if(compare){editor().apply(JSON.parse(frame.contentDocument.getElementById('website-layout').textContent));field('compare').textContent='Return to draft';}else{apply();field('compare').textContent='Compare published version';}};
 const storageKey='cl-paints-website-sections';let templates=[];try{templates=JSON.parse(localStorage.getItem(storageKey)||'[]');if(!Array.isArray(templates))templates=[];}catch{}
 function templateOptions(){field('templates').replaceChildren();templates.forEach((t,i)=>field('templates').add(new Option(t.name,i)));}templateOptions();
 field('template-save').onclick=()=>{if(typeof selected!=='object'||selected===null){field('status').textContent='Select an added row or block first.';return;}const name=field('template-name').value.trim();if(!name)return;templates.push({name,row:clone(edits._blocks[selected.row])});templates=templates.slice(-30);try{localStorage.setItem(storageKey,JSON.stringify(templates));templateOptions();field('status').textContent='Section saved on this device.';}catch{field('status').textContent='This browser could not save the section.';}};
 field('template-add').onclick=()=>{const template=templates[field('templates').value];if(!template)return;checkpoint();edits._blocks.push(clone(template.row));apply();};
 addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
})();
