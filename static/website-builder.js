(() => {
 const config=JSON.parse(document.getElementById('builder-data').textContent),frame=document.getElementById('builder-preview'),field=id=>document.getElementById('builder-'+id);
 let edits=config.layout,selected=null,mobile=false,deviceName="desktop",dirty=false,undo=[],redo=[];
 let multiSelect=null;frame.style.width='1280px';
 const editor=()=>frame.contentWindow.websiteEditor;
 const styles=[...document.querySelectorAll('[data-builder-style]')],positionFields=[...document.querySelectorAll('[data-builder-position]')];
 const clone=value=>structuredClone(value);
 const geometry=window.BuilderSnap,gridStep=()=>Number(field('grid-size').value),canSnap=event=>field('snap').checked&&!event.altKey;
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
 field('rename-page').onchange=()=>{field('rename-name').value=field('rename-page').selectedOptions[0].dataset.name;};
 function checkpoint(){undo.push(clone(edits));if(undo.length>100)undo.shift();redo=[];dirty=true;field('undo').disabled=false;field('redo').disabled=true;field('status').textContent='Unsaved changes';}
 function current(){if(selected===null)return null;if(typeof selected==='number')return edits[editor().keys[selected]]??={};return selected.cell===undefined?edits._blocks[selected.row]:edits._blocks[selected.row].cells[selected.cell];}
 function enrich(item){if(item.photo){const option=[...field('photo').options].find(o=>o.value===item.photo);item.image=option?.dataset.src||'';item.alt??=option?.dataset.alt||'';}}
 function previewLayout(layout){const data=clone(layout);Object.entries(data).forEach(([k,e])=>{if(!k.startsWith('_'))enrich(e);});data._blocks?.forEach(r=>r.cells.forEach(enrich));editor().apply(data,deviceName);}
 function apply(refreshLists=true){if(!editor())return;previewLayout(edits);if(refreshLists)renderLists();updateResizeHandle();}
 function button(label,fn){const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label;b.onclick=fn;return b;}
 function renderLists(){
   const list=field('rows');list.replaceChildren();edits._blocks.forEach((row,r)=>{const entry=document.createElement('div');entry.className='builder-row-actions';entry.append(button(`Row ${r+1}`,()=>choose({row:r})),button('↑',()=>moveRow(r,-1)),button('↓',()=>moveRow(r,1)),button('Duplicate',()=>{checkpoint();edits._blocks.splice(r+1,0,clone(row));apply();}),button('Remove',()=>{checkpoint();edits._blocks.splice(r,1);selected=null;field('controls').hidden=true;field('delete').disabled=true;apply();}));row.cells.forEach((cell,c)=>entry.append(button(`${c+1}: ${cell.kind}`,()=>choose({row:r,cell:c}))));const location=document.createElement('select');location.add(new Option('After existing sections','-1'));editor()?.sections.forEach((section,i)=>location.add(new Option('Before '+(section.querySelector('h1,h2')?.textContent||`section ${i+1}`).slice(0,50),i)));location.value=row.before??-1;location.setAttribute('aria-label',`Placement for row ${r+1}`);location.onchange=()=>{checkpoint();row.before=Number(location.value);apply();};entry.append(location);list.append(entry);});
   const sections=field('sections');sections.replaceChildren();const order=edits._sections?.length?edits._sections:editor()?.sections.map((_,i)=>i)||[];order.forEach((index,place)=>{const entry=document.createElement('div');entry.className='builder-row-actions';const label=document.createElement('span');entry.dataset.sectionIndex=index;label.textContent=(editor().sections[index]?.querySelector('h1,h2')?.textContent||`Section ${index+1}`).slice(0,60);entry.append(label);[-1,1].forEach(delta=>entry.append(button(delta<0?'↑':'↓',()=>{const target=place+delta;if(target<0||target>=order.length)return;checkpoint();edits._sections=[...order];[edits._sections[place],edits._sections[target]]=[edits._sections[target],edits._sections[place]];apply();})));const spacing=document.createElement('div');spacing.className='builder-row-actions';
[['padding','Top / bottom padding'],['gap','Grid gap'],['sidePadding','Side padding'],['minHeight','Minimum section height'],['maxWidth','Maximum section width'],['columns','Desktop gallery / card columns'],['mobileColumns','Mobile gallery / card columns'],['rowHeight','Gallery / card row height']].forEach(([key,title])=>{
 const label=document.createElement('label'),input=document.createElement('input');label.textContent=title+(['columns','mobileColumns'].includes(key)?'':' (px)');
 input.type='number';input.min='0';input.max=['columns','mobileColumns'].includes(key)?'48':key==='rowHeight'?'240':['minHeight','maxWidth'].includes(key)?'2400':key==='sidePadding'?'240':'120';input.step='1';input.placeholder='Original';input.value=edits._spacing?.[index]?.[key]??'';
 input.onchange=()=>{if(input.value!==''&&!input.checkValidity())return;checkpoint();edits._spacing??={};edits._spacing[index]??={};if(input.value==='')delete edits._spacing[index][key];else edits._spacing[index][key]=Number(input.value);apply(false);};
 label.append(input);spacing.append(label);
});
spacing.append(button('Reset spacing',()=>{checkpoint();if(edits._spacing)delete edits._spacing[index];apply();}));entry.append(spacing);sections.append(entry);});
 }
 function moveRow(index,delta){const target=index+delta;if(target<0||target>=edits._blocks.length)return;checkpoint();[edits._blocks[index],edits._blocks[target]]=[edits._blocks[target],edits._blocks[index]];selected=null;field('controls').hidden=true;field('delete').disabled=true;apply();}
 function choose(selection){multiSelect?.clear();const changed=JSON.stringify(selected)!==JSON.stringify(selection);selected=selection;const edit=current(),node=typeof selected==='number'?editor().nodes[selected]:null,isCell=typeof selected==='object'&&selected.cell!==undefined,isRow=typeof selected==='object'&&!isCell;
   field('controls').hidden=false;field('selection').textContent=node?`Selected ${node.tagName.toLowerCase()}`:isRow?`Row ${selected.row+1}`:`Row ${selected.row+1}, block ${selected.cell+1}`;
   field('delete').disabled=!!edit.locked;
   field('cell-kind').parentElement.hidden=!isCell;field('cell-kind').value=edit.kind||'text';
   field('text').parentElement.hidden=isRow||node?.tagName==='IMG';field('text').value=edit.text??node?.textContent??'';
   field('caption').parentElement.hidden=!isCell||edit.kind!=='review';field('caption').value=edit.caption||'';
   field('photo').parentElement.hidden=!(node?.tagName==='IMG'||isCell&&edit.kind==='image');field('photo').value=edit.photo||'';
   field('link').parentElement.hidden=!(node?.tagName==='A'||isCell&&['button','image'].includes(edit.kind));field('link').value=edit.link??node?.getAttribute('href')??'';
   field('video').parentElement.hidden=!isCell||edit.kind!=='video';field('video').value=edit.video||'';
   const isImage=node?.tagName==='IMG'||isCell&&edit.kind==='image';
   field('photo-alt').parentElement.hidden=!isImage;field('photo-alt').value=edit.alt??(edit.photo?[...field('photo').options].find(option=>option.value===edit.photo)?.dataset.alt:node?.alt)??'';
   const position=edit[deviceName]||edit.desktop||{};['x','y','width'].forEach(k=>field(k).value=position[k]||0);positionFields.forEach(input=>input.value=position[input.dataset.builderPosition]??(['columnSpan','rowSpan'].includes(input.dataset.builderPosition)?1:0));
   styles.forEach(input=>input.value=edit.style?.[input.dataset.builderStyle]??(input.dataset.builderStyle==='objectFit'&&isImage&&(edit.photo||isCell)?'contain':input.type==='number'&&!['columns','rowHeight'].includes(input.dataset.builderStyle)?0:''));
   const animation=edit.animation||{};field('animation').value=animation.kind||'none';['duration','delay','repeat','easing','trigger'].forEach(k=>field(k).value=animation[k]??({duration:1,delay:0,repeat:1,easing:'ease',trigger:'load'}[k]));
   field('controls').querySelectorAll('input,select,textarea').forEach(input=>input.disabled=!!edit.locked);
   editor().nodes.forEach(n=>n.style.outline='');if(node)node.style.outline='3px solid #ff2785';
   window.websiteBuilderWorkspace?.selection(changed,!!edit.locked,isImage,selectedNode());updateResizeHandle();
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
   const target=selectedNode(),rect=target.getBoundingClientRect(),anchors=snapAnchors(target),image=target.tagName==='IMG'?target:target.querySelector('img'),imageRect=image?.getBoundingClientRect(),neighbours=imageNeighbours(target,image);
   if(event.isTrusted)doc.body.setPointerCapture(pointerId);
   let moved=false;
   const move=event=>{
     if(event.pointerId!==pointerId)return;
     const dx=event.clientX-startX,dy=event.clientY-startY;
     if(!moved&&Math.hypot(dx,dy)<3)return;
     if(!moved){checkpoint();moved=true;}
     const snapping=canSnap(event);
     let x=(initial.x||0)+dx,y=(initial.y||0)+dy;
     if(snapping){x+=geometry.grid(rect.left+dx,gridStep(),anchors.origin.x)-(rect.left+dx);y+=geometry.grid(rect.top+dy,gridStep(),anchors.origin.y)-(rect.top+dy);}
     else{x=Math.round(x);y=Math.round(y);}
     clearAlignmentGuides();
     const matchedGaps=[];
     if(snapping){
       const horizontal=nearestSnap([rect.left+dx,rect.left+rect.width/2+dx,rect.right+dx],anchors.x);
       const vertical=nearestSnap([rect.top+dy,rect.top+rect.height/2+dy,rect.bottom+dy],anchors.y);
       if(horizontal){x=(initial.x||0)+dx+horizontal.delta;showAlignmentGuide('x',horizontal.anchor);}
       if(vertical){y=(initial.y||0)+dy+vertical.delta;showAlignmentGuide('y',vertical.anchor);}
       if(imageRect&&field('equal-spacing').checked){
         const moving={left:imageRect.left+dx,right:imageRect.right+dx,top:imageRect.top+dy,bottom:imageRect.bottom+dy};
         for(const axis of ['x','y']){const match=geometry.spacing(moving,neighbours,axis,6,Number(field('image-gap').value));if(!match)continue;
           if(axis==='x')x=(initial.x||0)+dx+match.delta;else y=(initial.y||0)+dy+match.delta;
           frame.contentDocument.querySelectorAll(`.builder-alignment-guide[data-axis="${axis}"]`).forEach(guide=>guide.remove());matchedGaps.push(match);
         }
       }
     }
     item[device]={...initial,x:Math.max(-2000,Math.min(2000,x)),y:Math.max(-2000,Math.min(2000,y))};
     apply(false);showSpacingGuides();matchedGaps.forEach(showEqualSpacing);field('x').value=item[device].x;field('y').value=item[device].y;
   };
   const end=event=>{if(event.pointerId!==pointerId)return;clearAlignmentGuides();if(doc.body.hasPointerCapture(pointerId))doc.body.releasePointerCapture(pointerId);doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',end);doc.removeEventListener('pointercancel',end);};
   doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',end);doc.addEventListener('pointercancel',end);
 }
 function snapAnchors(target){
   const doc=frame.contentDocument,parent=target.parentElement.getBoundingClientRect();
   const anchors={origin:{x:0,y:-frame.contentWindow.scrollY},x:[parent.left,(parent.left+parent.right)/2,parent.right,0,frame.contentWindow.innerWidth/2,frame.contentWindow.innerWidth],y:[parent.top,parent.bottom]};
   doc.querySelectorAll('#content img').forEach(node=>{
     if(node===target||target.contains(node)||node.contains(target)||node.hidden)return;
     const rect=node.getBoundingClientRect();if(!rect.width||!rect.height)return;
     anchors.x.push(rect.left,rect.left+rect.width/2,rect.right);anchors.y.push(rect.top,rect.top+rect.height/2,rect.bottom);
   });return anchors;
 }
 function nearestSnap(points,anchors){
   return geometry.nearest(points,anchors);
 }
 function imageNeighbours(target,image){
   if(!image)return[];const scope=target.closest('.wb-row,section')||target.parentElement;
   return [...scope.querySelectorAll('img')].filter(node=>node!==image&&!target.contains(node)&&!node.contains(target)&&!node.hidden).map(node=>node.getBoundingClientRect()).filter(rect=>rect.width&&rect.height);
 }
 function showEqualSpacing(match){
   const doc=frame.contentDocument,horizontal=match.axis==='x',start=horizontal?'left':'top',end=horizontal?'right':'bottom',crossStart=horizontal?'top':'left',crossEnd=horizontal?'bottom':'right';
   const boxes=[match.rect,...match.references].sort((a,b)=>a[start]-b[start]);
   for(let index=0;index<boxes.length-1;index++){
     const a=boxes[index],b=boxes[index+1];if(Math.abs(b[start]-a[end]-match.gap)>1)continue;
     const cross=(Math.max(a[crossStart],b[crossStart])+Math.min(a[crossEnd],b[crossEnd]))/2;
     const guide=doc.createElement('div');guide.className='builder-equal-guide';
     guide.style.cssText='position:fixed;pointer-events:none;z-index:99999;background:#a32bc4;'+(horizontal?`left:${a[end]}px;top:${cross}px;width:${match.gap}px;height:3px;`:`top:${a[end]}px;left:${cross}px;height:${match.gap}px;width:3px;`);
     const label=doc.createElement('span');label.textContent=Math.round(match.gap*10)/10+' px · '+(match.references.length>1?'equal':'gap');label.style.cssText='position:absolute;background:#a32bc4;color:white;border-radius:4px;padding:3px 6px;white-space:nowrap;font:12px Arial;'+(horizontal?'left:50%;top:-24px;transform:translateX(-50%);':'top:50%;left:5px;transform:translateY(-50%);');guide.append(label);doc.body.append(guide);
   }
 }
 function clearAlignmentGuides(){frame.contentDocument?.querySelectorAll('.builder-alignment-guide,.builder-spacing-guide,.builder-equal-guide').forEach(node=>node.remove());}
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
   guide.dataset.axis=axis;
   guide.style.cssText='position:fixed;pointer-events:none;z-index:99998;background:#00a6b8;box-shadow:0 0 0 1px white;'+(axis==='x'?`left:${value}px;top:0;bottom:0;width:2px;`:`top:${value}px;left:0;right:0;height:2px;`);
   frame.contentDocument.body.append(guide);
 }
 function changeControls(event){if(selected===null||current().locked)return;checkpoint();const edit=current();if([...positionFields,...styles,...['x','y','width'].map(field)].some(input=>input.value!==''&&!input.checkValidity()))return;edit[deviceName]={...(edit[deviceName]||edit.desktop||{}),x:Number(field('x').value),y:Number(field('y').value),width:Number(field('width').value)};positionFields.forEach(input=>edit[deviceName][input.dataset.builderPosition]=Number(input.value));if(event?.target===field('width')){edit[deviceName].widthPx=0;positionFields.find(input=>input.dataset.builderPosition==='widthPx').value=0;}
   if(!field('text').parentElement.hidden)edit.text=field('text').value;if(!field('caption').parentElement.hidden)edit.caption=field('caption').value;
   if(!field('photo').parentElement.hidden){if(field('photo').value)edit.photo=field('photo').value;else delete edit.photo;}
   if(!field('link').parentElement.hidden)edit.link=field('link').value;if(!field('video').parentElement.hidden)edit.video=field('video').value;
   if(!field('photo-alt').parentElement.hidden){if(event?.target===field('photo'))field('photo-alt').value=field('photo').selectedOptions[0]?.dataset.alt||'';edit.alt=field('photo-alt').value;}
   edit.style={};styles.forEach(input=>{if(input.value!=='')edit.style[input.dataset.builderStyle]=input.type==='number'?Number(input.value):input.value;});
   edit.animation={kind:field('animation').value,duration:Number(field('duration').value),delay:Number(field('delay').value),repeat:Number(field('repeat').value),easing:field('easing').value,trigger:field('trigger').value};apply(false);
 }
 ['text','caption','photo','photo-alt','link','video','x','y','width','animation','duration','delay','repeat','easing','trigger'].forEach(k=>field(k).addEventListener('input',changeControls));styles.forEach(input=>input.addEventListener('input',changeControls));positionFields.forEach(input=>input.addEventListener('input',changeControls));
 field('copy-desktop').onclick=()=>{if(selected===null||current().locked)return;checkpoint();current()[deviceName]=clone(current().desktop||{});apply();choose(selected);};
 field('reset-position').onclick=()=>{if(selected===null||current().locked)return;checkpoint();current()[deviceName]={x:0,y:0,width:0};apply();choose(selected);};
 field('cell-kind').onchange=()=>{checkpoint();current().kind=field('cell-kind').value;apply();choose(selected);};
 field('add').onclick=()=>{checkpoint();const kind=field('kind').value;const before=field('add').dataset.before===undefined?-1:Number(field('add').dataset.before);delete field('add').dataset.before;edits._blocks.push({before,cells:Array.from({length:Number(field('columns').value)},(_,i)=>({kind:i===0?kind:'text',text:i===0?'Your new content':'Add your text'}))});apply();choose({row:edits._blocks.length-1,cell:0});};
 field('delete').onclick=()=>{
   if(selected===null||current().locked)return;
   checkpoint();
   if(typeof selected==='number')current().deleted=true;
   else if(selected.cell===undefined)edits._blocks.splice(selected.row,1);
   else {
     const row=edits._blocks[selected.row];
     row.cells.splice(selected.cell,1);
     if(!row.cells.length)edits._blocks.splice(selected.row,1);
   }
   selected=null;field('controls').hidden=true;field('delete').disabled=true;
   editor().nodes.forEach(node=>node.style.outline='');
   clearAlignmentGuides();apply();
   field('status').textContent='Field deleted. Undo to restore it; publish to update the website.';
 };
 field('reset').onclick=()=>{checkpoint();if(typeof selected==='number')delete edits[editor().keys[selected]];else if(selected.cell!==undefined){const cell=current();edits._blocks[selected.row].cells[selected.cell]={kind:cell.kind,text:''};}else{const cells=current().cells;edits._blocks[selected.row]={before:-1,cells};}apply();choose(selected);};
 function history(source,target){multiSelect?.clear();if(!source.length)return;target.push(clone(edits));edits=source.pop();selected=null;field('controls').hidden=true;field('delete').disabled=true;dirty=true;initialise();apply();field('undo').disabled=!undo.length;field('redo').disabled=!redo.length;field('status').textContent='Unsaved changes';}
 field('undo').onclick=()=>history(undo,redo);field('redo').onclick=()=>history(redo,undo);
 field('device').onclick=()=>{mobile=!mobile;deviceName=mobile?'mobile':'desktop';frame.style.width=mobile?'390px':'1280px';field('device').textContent=mobile?'Desktop preview':'Mobile preview';apply();if(selected!==null)choose(selected);};
 field('page').onchange=()=>{if(dirty&&!confirm('Discard unsaved changes?')){field('page').value=config.page;return;}location.href='?page='+field('page').value;};
 ['title','description'].forEach(k=>field('seo-'+k).oninput=()=>{checkpoint();edits._seo[k]=field('seo-'+k).value;});
 async function save(action){field('save').disabled=field('draft').disabled=true;field('status').textContent='Saving…';try{const response=await fetch(location.pathname,{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams({page:config.page,csrf_token:config.csrf,action,revision:field('revision').value,layout:JSON.stringify(edits)})}),result=await readResponse(response);if(!response.ok)throw Error(result.error||'Save failed');if(action==='restore'){checkpoint();edits=result.layout;initialise();apply();selected=null;field('controls').hidden=true;field('delete').disabled=true;}dirty=false;field('publication-status').textContent=result.published?'Published':field('publication-status').textContent.startsWith('Published')?'Published · draft changes':'Draft';field('status').textContent=result.published?'Published to website':action==='restore'?'Restored as private draft':'Draft saved privately';if(action==='publish')location.reload();}catch(error){field('status').textContent=error.message;}finally{field('save').disabled=field('draft').disabled=false;}}
 field('save').onclick=()=>save('publish');field('draft').onclick=()=>save('draft');field('restore').onclick=()=>{if(field('revision').value&&(!dirty||confirm('Replace unsaved work with this version?')))save('restore');};
 function uploadSource(){const drive=field('upload-source').value==='drive',form=field('upload');field('device-photo').hidden=drive;field('drive-photo').hidden=!drive;form.elements.images.disabled=drive;form.elements.images.required=!drive;form.elements.drive_url.disabled=!drive;form.elements.drive_url.required=drive;}
 field('upload-source').onchange=uploadSource;
 field('upload').onsubmit=async event=>{event.preventDefault();const form=event.target,button=form.querySelector('button');button.disabled=true;field('upload-status').textContent='Uploading…';try{const data=new FormData(form),response=await fetch('/admin/photo-library/upload',{method:'POST',headers:{Accept:'application/json'},body:data}),result=await readResponse(response);if(!response.ok)throw Error(result.error||'Upload failed');for(const photo of result.photos){const approved=await fetch('/admin/photo-library/assets/'+photo.id,{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams({csrf_token:config.csrf,status:'approved',reviewed_permissions:'yes',alt:data.get('alt')})});await readResponse(approved);const option=new Option(data.get('alt'),photo.key);option.dataset.src=photo.url;option.dataset.alt=data.get('alt');field('photo').add(option);}field('upload-status').textContent='Uploaded. Select an image block and choose the new photo.';form.reset();uploadSource();}catch(error){field('upload-status').textContent=error.message;}finally{button.disabled=false;}};
 const oldRender=renderLists;renderLists=function(){oldRender();const list=field('layers');list.replaceChildren();editor()?.nodes.forEach((node,i)=>{const edit=edits[editor().keys[i]]||{};if(edit.deleted)return;list.append(button(`${edit.hidden?'Hidden · ':''}${edit.locked?'Locked · ':''}${node.tagName.toLowerCase()} · ${(node.alt||node.textContent).slice(0,40)}`,()=>choose(i)));});};
 function grid(){field('grid-toggle')?.setAttribute('aria-pressed',String(field('show-grid').checked));const doc=frame.contentDocument;if(!doc?.body)return;doc.getElementById('builder-grid-guides')?.remove();if(!field('show-grid').checked)return;const step=gridStep(),overlay=doc.createElement('div');overlay.id='builder-grid-guides';overlay.style.cssText='position:fixed;inset:0;pointer-events:none;z-index:1000;background-image:linear-gradient(to right,#00a6b812 1px,transparent 1px),linear-gradient(to bottom,#00a6b812 1px,transparent 1px),linear-gradient(to right,#00a6b828 1px,transparent 1px),linear-gradient(to bottom,#00a6b828 1px,transparent 1px);'+`background-size:${step}px ${step}px,${step}px ${step}px,${step*5}px ${step*5}px,${step*5}px ${step*5}px;`;overlay.style.backgroundPosition=`${-frame.contentWindow.scrollX}px ${-frame.contentWindow.scrollY}px`;doc.body.append(overlay);}
 frame.addEventListener('load',()=>{grid();frame.contentWindow.addEventListener('scroll',()=>{const overlay=frame.contentDocument.getElementById('builder-grid-guides');if(overlay)overlay.style.backgroundPosition=`${-frame.contentWindow.scrollX}px ${-frame.contentWindow.scrollY}px`;},true);});
 field('show-grid').onchange=grid;field('grid-size').onchange=grid;
 function nudge(event){
   const directions={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
   if(!directions[event.key]||event.ctrlKey||event.metaKey||event.altKey||selected===null||!editor()||current().locked||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
   event.preventDefault();checkpoint();const item=current(),position=item[deviceName]||item.desktop||{},[dx,dy]=directions[event.key],step=event.shiftKey?10:1;
   item[deviceName]={...position,x:Math.max(-2000,Math.min(2000,(position.x||0)+dx*step)),y:Math.max(-2000,Math.min(2000,(position.y||0)+dy*step))};
   clearAlignmentGuides();apply(false);choose(selected);showSpacingGuides();
 }
 document.addEventListener('keydown',nudge);frame.addEventListener('load',()=>frame.contentDocument.addEventListener('keydown',nudge));
 function toggleGrid(event){if(event.key.toLowerCase()!=='g'||event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;event.preventDefault();field('show-grid').checked=!field('show-grid').checked;grid();}document.addEventListener('keydown',toggleGrid);frame.addEventListener('load',()=>frame.contentDocument.addEventListener('keydown',toggleGrid));
 function selectedNode(){return typeof selected==='number'?editor().nodes[selected]:frame.contentDocument.querySelector(`[data-builder-row="${selected?.row}"]${selected?.cell!==undefined?' [data-builder-cell="'+selected.cell+'"]':''}`);}
 field('size').onchange=()=>{deviceName=field('size').value;mobile=deviceName==='mobile';frame.style.width=deviceName==='mobile'?'390px':deviceName==='tablet'?'820px':'1280px';apply();if(selected!==null)choose(selected);};
 field('replay').onclick=()=>{const doc=frame.contentDocument;doc.querySelectorAll('.wb-animated').forEach(node=>{node.style.animationName='none';void node.offsetWidth;node.style.animationName='';});};
 ['hide','lock'].forEach(action=>field(action).onclick=()=>{if(selected===null)return;checkpoint();const item=current(),key=action==='hide'?'hidden':'locked';item[key]=!item[key];apply();choose(selected);});
 let resizeRequested=false,resizing=false;
 function updateResizeHandle(){
   window.websiteBuilderWorkspace?.refreshSelection?.();
   const doc=frame.contentDocument;if(!doc?.body)return;
   const node=selected===null?null:selectedNode(),image=node?.tagName==='IMG'?node:node?.querySelector('img');
   if(!node||current().locked||node.hidden){doc.querySelectorAll('.builder-resize-handle').forEach(handle=>handle.remove());return;}
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
         const initialWidth=parseFloat(frame.contentWindow.getComputedStyle(target).width)||target.offsetWidth;
         const item=current(),device=deviceName,initial=clone(item[device]||item.desktop||{}),startX=event.clientX,startY=event.clientY,anchors=snapAnchors(target);
         const west=direction.includes('w'),north=direction.includes('n'),horizontal=west||direction.includes('e'),vertical=north||direction.includes('s');
         checkpoint();resizing=true;if(event.isTrusted)handle.setPointerCapture(event.pointerId);
         handle.onpointermove=move=>{
           const dx=move.clientX-startX,dy=move.clientY-startY;if(Math.hypot(dx,dy)<3)return;
           const snapping=canSnap(move),edgeX=west?rect.left:rect.right,edgeY=north?photoRect.top:photoRect.bottom;
           const snappedX=snapping?geometry.grid(edgeX+dx,gridStep(),anchors.origin.x)-edgeX:dx,snappedY=snapping?geometry.grid(edgeY+dy,gridStep(),anchors.origin.y)-edgeY:dy;
           let width=initialWidth+(horizontal?(west?-1:1)*snappedX:0),height=photoRect.height+(vertical?(north?-1:1)*snappedY:0);
           clearAlignmentGuides();
           if(snapping){
             const sx=horizontal?nearestSnap([west?rect.left+dx:rect.right+dx],anchors.x):null;
             const sy=vertical?nearestSnap([north?photoRect.top+dy:photoRect.bottom+dy],anchors.y):null;
             if(sx){width=initialWidth+(west?-1:1)*(dx+sx.delta);showAlignmentGuide('x',sx.anchor);}
             if(sy){height=north?photoRect.bottom-sy.anchor:sy.anchor-photoRect.top;showAlignmentGuide('y',sy.anchor);}
           }
           width=Math.max(parentWidth*.05,Math.min(parentWidth,width));height=Math.max(20,Math.min(1200,height));
           if(move.shiftKey&&horizontal&&vertical){height=width*photoRect.height/initialWidth;if(height>1200||height<20){height=Math.max(20,Math.min(1200,height));width=height*initialWidth/photoRect.height;}}
           item[device]={...initial};
           if(horizontal){item[device].width=width/parentWidth*100;item[device].widthPx=0;}
           if(west)item[device].x=(initial.x||0)+initialWidth-width;
           if(north)item[device].y=(initial.y||0)+photoRect.height-height;
           if(vertical){item[device].heightPx=Math.round(height);item.style??={};if(photo)item.style.objectFit||='contain';}positionFields.forEach(input=>input.value=item[device][input.dataset.builderPosition]??(['columnSpan','rowSpan'].includes(input.dataset.builderPosition)?1:0));
           field('width').value=item[device].width||0;field('x').value=item[device].x||0;field('y').value=item[device].y||0;
           if(item.style?.height!==undefined)styles.find(input=>input.dataset.builderStyle==='height').value=item.style.height;
           apply(false);showSpacingGuides();
         };
         const finish=()=>{resizing=false;clearAlignmentGuides();handle.onpointermove=null;handle.onpointerup=null;handle.onpointercancel=null;updateResizeHandle();};
         handle.onpointerup=finish;handle.onpointercancel=finish;
       };
       doc.body.append(handle);
     }
     const rect=(image||node).getBoundingClientRect(),x=direction.includes('w')?rect.left:direction.includes('e')?rect.right:rect.left+rect.width/2,y=direction.includes('n')?rect.top:direction.includes('s')?rect.bottom:rect.top+rect.height/2;handle.style.left=x-16+'px';handle.style.top=y-16+'px';
   }
   if(image){image.draggable=false;image.style.touchAction='none';image.style.cursor='move';}
   if(handleObserver&&observedPreviewImage!==image){if(observedPreviewImage)handleObserver.unobserve(observedPreviewImage);observedPreviewImage=image;if(image)handleObserver.observe(image);}
 }
 field('resize').onclick=()=>{resizeRequested=true;updateResizeHandle();};
 let handleObserver,observedPreviewImage;
 frame.addEventListener('load',()=>{
   frame.contentWindow.addEventListener('scroll',updateResizeHandle,true);frame.contentWindow.addEventListener('resize',updateResizeHandle);
   frame.contentDocument.addEventListener('load',updateResizeHandle,true);
   handleObserver?.disconnect();
   handleObserver=new frame.contentWindow.ResizeObserver(()=>updateResizeHandle());
   handleObserver.observe(frame.contentDocument.getElementById('content'));
 });
 field('photo-reset').onclick=()=>{if(selected===null||current().locked)return;checkpoint();const edit=current();for(const device of ['desktop','tablet','mobile'])if(edit[device]){edit[device].width=0;edit[device].widthPx=0;edit[device].heightPx=0;}edit.style??={};edit.style.height=0;edit.style.objectFit='contain';edit.style.objectPosition='center';edit.compactImage=true;edit.naturalImage=true;apply();choose(selected);};
 field('crop').onclick=()=>{const selectedElement=selectedNode(),image=selectedElement?.tagName==='IMG'?selectedElement:selectedElement?.querySelector('img');if(!image){field('status').textContent='Select an image first.';return;}field('status').textContent='Click the important area of the image to choose its focal point.';image.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();const rect=image.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width,y=(event.clientY-rect.top)/rect.height;checkpoint();current().style??={};current().style.objectPosition=x<.25?'left':x>.75?'right':y<.25?'top':y>.75?'bottom':'center';current().style.objectFit='cover';apply();choose(selected);},{once:true,capture:true});};
 field('check').onclick=()=>{const messages=[];frame.contentDocument.querySelectorAll('#content img:not([hidden])').forEach(n=>{if(!n.alt?.trim())messages.push('An image needs a description.');});frame.contentDocument.querySelectorAll('#content a').forEach(n=>{if(!n.getAttribute('href')||n.getAttribute('href')==='#')messages.push('A button or link needs a destination.');});frame.contentDocument.querySelectorAll('#content img,#content p,#content h1,#content h2,.wb-cell').forEach(n=>{const r=n.getBoundingClientRect();if(!n.hidden&&(r.left<0||r.right>frame.contentWindow.innerWidth+2))messages.push('Content extends beyond the preview width.');});field('checks').textContent=[...new Set(messages)].join(' ')||'No missing descriptions, placeholder links or horizontal overflow found in this preview.';};
 let compare=false;field('compare').onclick=()=>{if(!editor())return;compare=!compare;if(compare){editor().apply(JSON.parse(frame.contentDocument.getElementById('website-layout').textContent));field('compare').textContent='Return to draft';}else{apply();field('compare').textContent='Compare published version';}};
 const storageKey='cl-paints-website-sections';let templates=[];try{templates=JSON.parse(localStorage.getItem(storageKey)||'[]');if(!Array.isArray(templates))templates=[];}catch{}
 function templateOptions(){field('templates').replaceChildren();templates.forEach((t,i)=>field('templates').add(new Option(t.name,i)));}templateOptions();
 field('template-save').onclick=()=>{if(typeof selected!=='object'||selected===null){field('status').textContent='Select an added row or block first.';return;}const name=field('template-name').value.trim();if(!name)return;templates.push({name,row:clone(edits._blocks[selected.row])});templates=templates.slice(-30);try{localStorage.setItem(storageKey,JSON.stringify(templates));templateOptions();field('status').textContent='Section saved on this device.';}catch{field('status').textContent='This browser could not save the section.';}};
 field('template-add').onclick=()=>{const template=templates[field('templates').value];if(!template)return;checkpoint();edits._blocks.push(clone(template.row));apply();};
 addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
 multiSelect=window.createBuilderMultiSelect({frame,field,editor,getEdits:()=>edits,device:()=>deviceName,checkpoint,apply,
   clearSingle(){selected=null;field('controls').hidden=true;field('delete').disabled=true;editor().nodes.forEach(node=>node.style.outline='');frame.contentDocument.querySelectorAll('[data-builder-cell]').forEach(node=>node.style.outline='');updateResizeHandle();}
 });
 let tidyPlan=null;
 const tidyDialog=field('tidy-dialog');
 field('tidy').onclick=()=>{if(!editor())return;tidyPlan=null;field('tidy-changes').replaceChildren();field('tidy-status').textContent='Choose the area and changes, then preview.';field('tidy-apply').disabled=true;tidyDialog.showModal();};
 function resetTidyPreview(){tidyPlan=null;field('tidy-apply').disabled=true;field('tidy-changes').replaceChildren();field('tidy-status').textContent='Preview again to see these options.';apply(false);}
 ['scope','empty','gaps','images'].forEach(key=>field('tidy-'+key).onchange=resetTidyPreview);
 field('tidy-preview').onclick=()=>{
   apply(false);let scope=null;
   if(field('tidy-scope').value==='section'){
     if(selected===null){field('tidy-status').textContent='Close this dialog and select one field or row in the preview first.';return;}
     if(typeof selected==='object')scope={row:selected.row};
     else {const section=editor().sections.findIndex(section=>section.contains(selectedNode()));if(section<0){field('tidy-status').textContent='Select a field inside a section first.';return;}scope={section};}
   }
   tidyPlan=window.planBuilderTidy({layout:edits,editor:editor(),scope,empty:field('tidy-empty').checked,gaps:field('tidy-gaps').checked,images:field('tidy-images').checked,computedStyle:node=>frame.contentWindow.getComputedStyle(node)});
   field('tidy-changes').replaceChildren();tidyPlan.changes.forEach(change=>{const row=document.createElement('li');row.textContent=change;field('tidy-changes').append(row);});
   field('tidy-status').textContent=tidyPlan.changes.length?`${tidyPlan.changes.length} changes previewed. Close this dialog to keep your current layout, or apply to keep these changes.`:'No unused space found with these options.';
   field('tidy-apply').disabled=!tidyPlan.changes.length;previewLayout(tidyPlan.layout);
 };
 field('tidy-apply').onclick=()=>{if(!tidyPlan?.changes.length)return;checkpoint();multiSelect?.clear();edits=tidyPlan.layout;selected=null;field('controls').hidden=true;field('delete').disabled=true;tidyPlan=null;initialise();apply();tidyDialog.close();field('status').textContent='Spacing tidied. Undo to restore; publish when ready.';};
 field('tidy-close').onclick=()=>tidyDialog.close();
 tidyDialog.addEventListener('close',()=>{tidyPlan=null;apply(false);});
})();
