window.createBuilderMultiSelect=({frame,field,editor,getEdits,device,checkpoint,apply,clearSingle})=>{
 let selected=[],mode=false,suppressClick=false;
 const toggle=field('select-multiple'),status=field('multi-status');
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 function item(ref){return typeof ref==='number'?getEdits()[editor().keys[ref]]||{}:getEdits()._blocks[ref.row]?.cells[ref.cell]||{};}
 function node(ref){return typeof ref==='number'?editor().nodes[ref]:frame.contentDocument.querySelector(`[data-builder-row="${ref.row}"] [data-builder-cell="${ref.cell}"]`);}
 function setMode(value){mode=value;toggle.setAttribute('aria-pressed',String(mode));frame.contentDocument?.getElementById('content')?.classList.toggle('builder-select-mode',mode);}
 function clear(){selected.forEach(ref=>{const element=node(ref);if(element)element.style.outline='';});selected=[];status.textContent='';}
 function select(refs){clear();clearSingle();selected=refs;selected.forEach(ref=>node(ref).style.outline='3px solid #ff2785');status.textContent=selected.length?`${selected.length} fields selected. Drag a selected field to move them; press Escape to clear.`:'No movable fields in this selection.';}
 function candidates(){
   const refs=editor().nodes.map((_,index)=>index);
   getEdits()._blocks.forEach((row,r)=>{if(!row.locked&&!row.hidden)row.cells.forEach((_,c)=>refs.push({row:r,cell:c}));});
   const visible=refs.filter(ref=>{const element=node(ref),edit=item(ref),rect=element?.getBoundingClientRect();return element&&!edit.locked&&!edit.hidden&&!edit.deleted&&!element.hidden&&rect.width>0&&rect.height>0;});
   return visible.filter(ref=>!visible.some(parent=>!same(parent,ref)&&node(parent).contains(node(ref))));
 }
 function capture(event,onMove,onEnd){
   const doc=frame.contentDocument,id=event.pointerId;
   if(event.isTrusted)doc.body.setPointerCapture(id);
   const move=e=>{if(e.pointerId===id)onMove(e);};
   const end=e=>{if(e.pointerId!==id)return;doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',end);doc.removeEventListener('pointercancel',end);if(doc.body.hasPointerCapture(id))doc.body.releasePointerCapture(id);doc.body.classList.remove('builder-group-dragging');onEnd(e);};
   doc.body.classList.add('builder-group-dragging');doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',end);doc.addEventListener('pointercancel',end);
 }
 function positions(){return selected.map(ref=>{const edit=item(ref);return {ref,initial:structuredClone(edit[device()]||edit.desktop||{})};});}
 function moveGroup(initial,dx,dy){
   dx=Math.max(...initial.map(({initial:p})=>-2000-(p.x||0)),Math.min(dx,...initial.map(({initial:p})=>2000-(p.x||0))));
   dy=Math.max(...initial.map(({initial:p})=>-2000-(p.y||0)),Math.min(dy,...initial.map(({initial:p})=>2000-(p.y||0))));
   initial.forEach(({ref,initial:p})=>{let edit;if(typeof ref==='number')edit=getEdits()[editor().keys[ref]]??={};else edit=item(ref);edit[device()]={...p,x:(p.x||0)+dx,y:(p.y||0)+dy};});apply(false);
 }
 toggle.onclick=()=>setMode(!mode);
 frame.addEventListener('load',()=>{
   clear();setMode(mode);const doc=frame.contentDocument,main=doc.getElementById('content');if(!main||!editor())return;
   doc.addEventListener('click',event=>{if(suppressClick){suppressClick=false;event.preventDefault();event.stopImmediatePropagation();}},true);
   doc.addEventListener('pointerdown',event=>{
     suppressClick=false;if(event.button!==0||!main.contains(event.target)||event.target.closest('.builder-resize-handle'))return;
     const all=candidates(),hit=all.find(ref=>node(ref)===event.target||node(ref).contains(event.target));
     if(selected.length&&hit!==undefined&&selected.some(ref=>same(ref,hit))&&!event.shiftKey){
       event.preventDefault();event.stopImmediatePropagation();suppressClick=true;
       const initial=positions(),x=event.clientX,y=event.clientY;let moved=false;
       capture(event,e=>{let dx=e.clientX-x,dy=e.clientY-y;if(!moved&&Math.hypot(dx,dy)<3)return;if(!moved){checkpoint();moved=true;}
         if(field('snap').checked&&!e.altKey){const step=Number(field('grid-size').value);dx=Math.round(dx/step)*step;dy=Math.round(dy/step)*step;}
         moveGroup(initial,Math.round(dx),Math.round(dy));},()=>{});return;
     }
     if(!mode&&!event.shiftKey&&hit!==undefined){clear();return;}
     if(!mode&&!event.shiftKey&&event.target.closest('a,button,input,select,textarea,iframe'))return;
     event.preventDefault();event.stopImmediatePropagation();suppressClick=true;
     const startX=event.clientX,startY=event.clientY,previous=event.shiftKey?[...selected]:[];
     select(previous);const box=doc.createElement('div');box.className='builder-selection-box';doc.body.append(box);
     capture(event,e=>{const left=Math.min(startX,e.clientX),top=Math.min(startY,e.clientY),right=Math.max(startX,e.clientX),bottom=Math.max(startY,e.clientY);
       box.style.cssText=`position:fixed;pointer-events:none;z-index:100002;border:2px solid #ff2785;background:#ff278522;left:${left}px;top:${top}px;width:${right-left}px;height:${bottom-top}px;`;
       const refs=all.filter(ref=>{const r=node(ref).getBoundingClientRect();return r.left<right&&r.right>left&&r.top<bottom&&r.bottom>top;});
       select([...previous,...refs.filter(ref=>!previous.some(old=>same(old,ref)))]);
     },()=>{box.remove();setMode(false);});
   },true);
   doc.addEventListener('keydown',keyboard,true);
 });
 function keyboard(event){
   if(event.target.closest?.('input,textarea,select,button,[contenteditable="true"]'))return;
   if(event.key==='Escape'){clear();setMode(false);return;}
   const arrows={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
   if(!selected.length||!arrows[event.key]||event.ctrlKey||event.metaKey||event.altKey)return;
   event.preventDefault();event.stopImmediatePropagation();const [x,y]=arrows[event.key],step=event.shiftKey?10:1;checkpoint();moveGroup(positions(),x*step,y*step);
 }
 document.addEventListener('keydown',keyboard,true);
 return {clear};
};
