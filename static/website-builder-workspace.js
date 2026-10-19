(() => {
 const tools=document.querySelector('.builder-tools'),workspace=document.querySelector('.builder-workspace');
 const get=id=>document.getElementById('builder-'+id);
 const frame=get('preview'),host=workspace.closest('main');
 host.classList.add('builder-studio-main');
 const toolbar=document.querySelector('.builder-toolbar');
 const title=host.querySelector('h1'),intro=title.nextElementSibling;
 const help=document.createElement('details');help.className='builder-help';
 const helpTitle=document.createElement('summary');helpTitle.textContent='Help';help.append(helpTitle,intro);
 const back=document.createElement('a');back.href='/admin/dashboard';back.className='btn builder-exit';back.textContent='Exit editor';
 title.classList.add('builder-studio-title');
 const pageGroup=document.createElement('div');pageGroup.className='builder-toolbar-group';pageGroup.append(back,title,get('page').parentElement);
 const deviceGroup=document.createElement('div');deviceGroup.className='builder-toolbar-group builder-device-group';deviceGroup.append(get('size').parentElement,get('device'));
 const gridToggle=document.createElement('button');gridToggle.id='builder-grid-toggle';gridToggle.type='button';gridToggle.className='btn';gridToggle.textContent='Grid';gridToggle.title='Show or hide grid guides (G)';gridToggle.setAttribute('aria-pressed',String(get('show-grid').checked));gridToggle.onclick=()=>get('show-grid').click();deviceGroup.append(gridToggle);
 const saveGroup=document.createElement('div');saveGroup.className='builder-toolbar-group builder-save-group';saveGroup.append(get('undo'),get('redo'),get('draft'),get('save'));
 const more=document.createElement('details');more.className='builder-more';const moreTitle=document.createElement('summary');moreTitle.textContent='More tools';
 const moreItems=document.createElement('div');moreItems.append(get('tidy'),get('select-multiple'),get('delete'));more.append(moreTitle,moreItems);
 toolbar.prepend(pageGroup,deviceGroup,saveGroup);saveGroup.append(more,help);
 const tabs=document.createElement('div');tabs.className='builder-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Editing tools');
 const panels={},buttons={};
 for(const [key,label] of [['content','Blocks'],['design','Design'],['photo','Photo'],['sections','Sections'],['pages','Pages'],['settings','Settings']]){
   const tab=document.createElement('button');tab.type='button';tab.id='builder-tab-'+key;tab.textContent=label;tab.setAttribute('role','tab');
   const panel=document.createElement('div');panel.id='builder-pane-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);
   tab.setAttribute('aria-controls',panel.id);tab.onclick=()=>show(key);buttons[key]=tab;panels[key]=panel;tabs.append(tab);
 }
 function show(key){Object.keys(panels).forEach(name=>{panels[name].hidden=name!==key;buttons[name].setAttribute('aria-selected',String(name===key));buttons[name].tabIndex=name===key?0:-1;});}
 buttons.photo.hidden=true;
 tabs.onkeydown=event=>{const keys=Object.keys(buttons).filter(key=>!buttons[key].hidden),index=keys.indexOf(event.target.id.replace('builder-tab-',''));let next;
   if(event.key==='ArrowRight')next=(index+1)%keys.length;else if(event.key==='ArrowLeft')next=(index+keys.length-1)%keys.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=keys.length-1;else return;
   event.preventDefault();show(keys[next]);buttons[keys[next]].focus();};
 const controls=get('controls'),design=document.createElement('section');design.className='panel';design.id='builder-design-controls';
 const heading=document.createElement('h2');heading.textContent='Selected item design';design.append(heading);
 const hint=document.createElement('p');hint.textContent='Select text, an image or a block in the preview to edit its design.';design.append(hint);
 controls.querySelectorAll(':scope > details').forEach(detail=>{detail.open=false;design.append(detail);});
 const actions=controls.querySelector('.builder-row-actions');design.append(actions);
 const photo=document.createElement('section');photo.className='panel';
 const photoTitle=document.createElement('h2');photoTitle.textContent='Photo editing';photo.append(photoTitle);
 const photoHint=document.createElement('p');photoHint.textContent='Show whole image keeps every edge visible. Fill frame crops the edges; choose a focal point to control the crop.';photo.append(photoHint);
 photo.append(get('photo').parentElement,get('photo-alt').parentElement);
 for(const key of ['objectFit','objectPosition']){
   const select=design.querySelector(`[data-builder-style="${key}"]`);
   if(key==='objectFit'){select.querySelector('option[value=""]').textContent='Original layout';[...select.options].forEach(option=>{option.value=option.value;if(option.value==='contain')option.textContent='Show whole image';if(option.value==='cover')option.textContent='Fill frame (crop edges)';});}
   photo.append(select.parentElement);
 }
 photo.append(get('photo-reset'),actions.querySelector('#builder-crop'));panels.photo.append(photo);
 const precision=get('snap').closest('.panel');
 const advanced=document.createElement('details');advanced.className='panel';
 const summary=document.createElement('summary');summary.textContent='Layout and snapping';advanced.append(summary);
 [...precision.children].filter(child=>child.tagName!=='H2').forEach(child=>advanced.append(child));precision.remove();
 const pages=get('page-management');pages.open=true;panels.pages.append(pages);
 const settings=[get('seo-title').closest('.panel'),get('revision').closest('.panel')];
 settings.forEach(panel=>panels.settings.append(panel));
 const sections=get('sections').closest('.panel');sections.open=true;panels.sections.append(sections);
 panels.design.append(design,advanced);
 panels.content.append(controls);
 [...tools.children].forEach(panel=>panels.content.append(panel));
 tools.append(tabs,...Object.values(panels));show('content');
 const empty=document.createElement('p');empty.id='builder-selection-hint';empty.className='builder-selection-hint';empty.textContent='Select an item in the preview to edit it, or add content below.';panels.content.insertBefore(empty,controls);
 window.websiteBuilderWorkspace={selection(changed,locked,isImage){
   buttons.photo.hidden=!isImage;photo.querySelectorAll('input,select,button').forEach(input=>input.disabled=locked||!isImage);
   empty.hidden=false;empty.textContent='Select an item in the preview to edit it, or add content below.';
   if(!controls.hidden){empty.hidden=true;hint.textContent=get('selection').textContent;design.querySelectorAll('input,select,textarea').forEach(input=>input.disabled=locked);
     if(changed){show(isImage?'photo':'content');tools.scrollTop=0;}
     else if(!isImage&&buttons.photo.getAttribute('aria-selected')==='true')show('content');
   }
 }};
 new MutationObserver(()=>{if(controls.hidden){buttons.photo.hidden=true;if(buttons.photo.getAttribute('aria-selected')==='true')show('content');empty.hidden=false;hint.textContent='Select an item in the preview to edit its design.';design.querySelectorAll('input,select,textarea').forEach(input=>input.disabled=true);}}).observe(controls,{attributes:true,attributeFilter:['hidden']});
 design.querySelectorAll('input,select,textarea').forEach(input=>input.disabled=true);
 const divider=document.createElement('div');divider.className='builder-divider';divider.tabIndex=0;divider.setAttribute('role','separator');divider.setAttribute('aria-label','Editor panel width');divider.setAttribute('aria-orientation','vertical');divider.setAttribute('aria-valuemin','25');divider.setAttribute('aria-valuemax','60');
 workspace.prepend(document.querySelector('.builder-preview-scroll'),divider);
 let width=28;try{const saved=Number(localStorage.getItem('cl-builder-panel-width'));if(saved>=25&&saved<=60)width=saved;}catch{}
 function resize(value){width=Math.max(25,Math.min(60,value));workspace.style.setProperty('--builder-tools-width',width+'%');divider.setAttribute('aria-valuenow',String(Math.round(width)));try{localStorage.setItem('cl-builder-panel-width',String(width));}catch{}}
 resize(width);
 divider.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resize(event.key==='Home'?25:event.key==='End'?60:width+(event.key==='ArrowLeft'?-2:2));};
 divider.onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();divider.setPointerCapture(event.pointerId);workspace.classList.add('builder-adjusting');
   const move=event=>{const rect=workspace.getBoundingClientRect();resize((rect.right-event.clientX)/rect.width*100);};
   const end=()=>{workspace.classList.remove('builder-adjusting');divider.removeEventListener('pointermove',move);divider.removeEventListener('pointerup',end);divider.removeEventListener('pointercancel',end);};
   divider.addEventListener('pointermove',move);divider.addEventListener('pointerup',end);divider.addEventListener('pointercancel',end);
 };
 window.websiteBuilderWorkspace.openSection=index=>{
   show('sections');const entry=get('sections').querySelector(`[data-section-index="${index}"]`);
   if(entry){entry.scrollIntoView({block:'nearest'});entry.querySelector('input')?.focus({preventScroll:true});}
 };
 let selectedBlock=null,selectedLocked=false,blockBar=null;
 const originalSelection=window.websiteBuilderWorkspace.selection;
 window.websiteBuilderWorkspace.selection=(changed,locked,isImage,node)=>{
   originalSelection(changed,locked,isImage);selectedBlock=node;selectedLocked=locked;drawBlockBar();
 };
 function editorButton(doc,label,action){const button=doc.createElement('button');button.type='button';button.textContent=label;button.onpointerdown=event=>event.stopPropagation();button.onclick=event=>{event.preventDefault();event.stopPropagation();action();};return button;}
 function drawBlockBar(){
   blockBar?.remove();blockBar=null;
   const doc=frame.contentDocument;if(!doc||!selectedBlock?.isConnected||controls.hidden)return;
   const rect=selectedBlock.getBoundingClientRect();if(rect.bottom<0||rect.top>frame.clientHeight)return;
   blockBar=doc.createElement('div');blockBar.className='builder-inline-toolbar';
   blockBar.style.cssText=`position:fixed;z-index:100002;display:flex;gap:4px;padding:5px;background:white;border:1px solid #d9d9d9;border-radius:6px;box-shadow:0 3px 14px #0002;left:${Math.max(6,Math.min(rect.left,frame.clientWidth-275))}px;top:${Math.max(6,rect.top-44)}px;`;
   blockBar.append(editorButton(doc,'Edit',()=>show(buttons.photo.hidden?'content':'photo')),editorButton(doc,'Size & position',()=>{show('design');design.querySelector('details').open=true;}),editorButton(doc,selectedLocked?'Unlock':'Lock',()=>get('lock').click()));
   if(!selectedLocked)blockBar.append(editorButton(doc,'Delete',()=>get('delete').click()));
   doc.body.append(blockBar);
 }
 window.websiteBuilderWorkspace.refreshSelection=drawBlockBar;
 frame.addEventListener('load',()=>{
   const doc=frame.contentDocument,style=doc.createElement('style');
   style.textContent='.builder-inline-toolbar button,.builder-section-actions button{font:12px Arial,sans-serif;line-height:1.3;padding:7px 9px;border:0;border-radius:3px;background:white;color:#202020;cursor:pointer}.builder-inline-toolbar button:hover,.builder-section-actions button:hover{background:#eee}';doc.head.append(style);
   const overlay=doc.createElement('div');overlay.className='builder-section-overlay';doc.body.append(overlay);
   let pending=false;
   function drawSections(){pending=false;overlay.replaceChildren();
     frame.contentWindow.websiteEditor?.sections.forEach((section,index)=>{
       const rect=section.getBoundingClientRect();if(rect.bottom<0||rect.top>frame.clientHeight||rect.height<10)return;
       const actions=doc.createElement('div');actions.className='builder-section-actions';actions.style.cssText=`position:fixed;z-index:100001;right:14px;top:${Math.max(8,rect.top+12)}px;border:1px solid #1672e8;border-radius:4px;box-shadow:0 2px 6px #0001;`;
       actions.append(editorButton(doc,'Edit section',()=>window.websiteBuilderWorkspace.openSection(index)),editorButton(doc,'+ Add section',()=>{show('content');get('add').dataset.before=index;get('kind').closest('details').open=true;get('add').focus();}));overlay.append(actions);
     });drawBlockBar();
   }
   const schedule=()=>{if(!pending){pending=true;frame.contentWindow.requestAnimationFrame(drawSections);}};
   frame.contentWindow.addEventListener('scroll',schedule,{passive:true});frame.contentWindow.addEventListener('resize',schedule);
   new frame.contentWindow.ResizeObserver(schedule).observe(doc.getElementById('content'));
   drawSections();
 });
 new MutationObserver(()=>{if(controls.hidden){selectedBlock=null;drawBlockBar();}}).observe(controls,{attributes:true,attributeFilter:['hidden']});
})();
