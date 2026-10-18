// Plan changes on a copy so previewing never modifies the saved draft or Undo history.
window.planBuilderTidy=({layout,editor,scope,empty,gaps,images,computedStyle})=>{
 const result=structuredClone(layout),changes=[];
 const clean=(edit,label)=>{if(edit.locked||edit.hidden||edit.deleted)return;
   if(gaps&&edit.style){for(const key of ['padding','gap'])if(edit.style[key]>32){edit.style[key]=24;changes.push(`Reduce ${label} ${key} to 24 px`);}}
 };
 const emptyText=cell=>['text','heading','announcement','review'].includes(cell.kind)&&!String(cell.text||'').trim()&&!String(cell.caption||'').trim()&&!cell.locked&&!cell.hidden;
 for(let r=(result._blocks||[]).length-1;r>=0;r--){
   if(scope&&scope.row!==r)continue;
   const row=result._blocks[r];if(row.locked||row.hidden||row.cells.some(cell=>cell.locked))continue;
   clean(row,`row ${r+1}`);
   row.cells.forEach((cell,c)=>clean(cell,`row ${r+1}, block ${c+1}`));
   if(empty){for(let c=row.cells.length-1;c>=0;c--)if(emptyText(row.cells[c])){row.cells.splice(c,1);changes.push(`Remove empty block ${c+1} from row ${r+1}`);}
     if(!row.cells.length){result._blocks.splice(r,1);changes.push(`Remove empty row ${r+1}`);}}
 }
 editor.nodes.forEach((node,index)=>{
   if(scope&&(scope.row!==undefined||!editor.sections[scope.section]?.contains(node)))return;
   const key=editor.keys[index],edit=result[key]||{};
   const section=editor.sections.find(section=>section.contains(node));
   if(section&&editor.nodes.some((other,i)=>section.contains(other)&&layout[editor.keys[i]]?.locked))return;
   if(edit.locked||edit.hidden||edit.deleted)return;
   if(empty&&['P','H1','H2','H3'].includes(node.tagName)&&!String(edit.text??node.textContent).trim()){
     result[key]={...edit,deleted:true};changes.push('Remove an empty text field');return;
   }
   const updated={...edit};clean(updated,node.tagName.toLowerCase());
   if(images&&node.tagName==='IMG'&&node.parentElement.classList.contains('wb-image-slot')&&!edit.compactImage){updated.compactImage=true;changes.push('Release unused layout space around a resized image');}
   if(JSON.stringify(updated)!==JSON.stringify(edit))result[key]=updated;
 });
 if(gaps){editor.sections.forEach((section,index)=>{
   if(scope&&(scope.row!==undefined||scope.section!==index))return;
   const locked=editor.nodes.some((node,i)=>section.contains(node)&&layout[editor.keys[i]]?.locked);if(locked)return;
   const style=computedStyle(section),spacing={...(result._spacing?.[index]||{})};
   if(parseFloat(style.paddingTop)>48||parseFloat(style.paddingBottom)>48){spacing.padding=24;changes.push(`Reduce section ${index+1} vertical padding to 24 px`);}
   if(parseFloat(style.rowGap)>32||parseFloat(style.columnGap)>32){spacing.gap=24;changes.push(`Reduce section ${index+1} gaps to 24 px`);}
   if(Object.keys(spacing).length){result._spacing??={};result._spacing[index]=spacing;}
 });}
 return {layout:result,changes};
};
