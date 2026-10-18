(() => {
 const tools=document.querySelector('.builder-tools'),workspace=document.querySelector('.builder-workspace');
 const get=id=>document.getElementById('builder-'+id);
 const tabs=document.createElement('div');tabs.className='builder-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Editing tools');
 const panels={},buttons={};
 for(const [key,label] of [['content','Content'],['design','Design'],['photo','Photo'],['pages','Pages'],['settings','Settings']]){
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
 workspace.insertBefore(divider,document.querySelector('.builder-preview-scroll'));
 let width=40;try{const saved=Number(localStorage.getItem('cl-builder-panel-width'));if(saved>=25&&saved<=60)width=saved;}catch{}
 function resize(value){width=Math.max(25,Math.min(60,value));workspace.style.setProperty('--builder-tools-width',width+'%');divider.setAttribute('aria-valuenow',String(Math.round(width)));try{localStorage.setItem('cl-builder-panel-width',String(width));}catch{}}
 resize(width);
 divider.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resize(event.key==='Home'?25:event.key==='End'?60:width+(event.key==='ArrowLeft'?-2:2));};
 divider.onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();divider.setPointerCapture(event.pointerId);workspace.classList.add('builder-adjusting');
   const move=event=>{const rect=workspace.getBoundingClientRect();resize((event.clientX-rect.left)/rect.width*100);};
   const end=()=>{workspace.classList.remove('builder-adjusting');divider.removeEventListener('pointermove',move);divider.removeEventListener('pointerup',end);divider.removeEventListener('pointercancel',end);};
   divider.addEventListener('pointermove',move);divider.addEventListener('pointerup',end);divider.addEventListener('pointercancel',end);
 };
})();
