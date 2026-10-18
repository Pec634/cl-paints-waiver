(() => {
 const main=document.getElementById('content'),extra=document.getElementById('website-extra-blocks');
 const nodes=[...main.querySelectorAll('img,h1,h2,h3,p,a.button')].filter(n=>!extra.contains(n));
 // Append labels so older layouts that address fields by number keep their original order.
 const labels=[...main.querySelectorAll('span,small')].filter(n=>!extra.contains(n)&&n.textContent.trim()&&
   !n.closest('form,button,a,[aria-hidden="true"]')&&!nodes.some(parent=>parent.contains(n)||n.contains(parent)));
 nodes.push(...labels.filter(n=>!labels.some(parent=>parent!==n&&parent.contains(n))));
 const originals=nodes.map(n=>({html:n.innerHTML,style:n.getAttribute('style'),src:n.getAttribute('src'),srcset:n.getAttribute('srcset'),alt:n.getAttribute('alt'),href:n.getAttribute('href')}));
 const sections=[...main.children].filter(n=>n!==extra);
 const keys=nodes.map(n=>{
   let section=n;while(section.parentElement!==main)section=section.parentElement;
   let path='';for(let p=n;p!==section;p=p.parentElement)path=p.tagName+':'+[...p.parentElement.children].filter(s=>s.tagName===p.tagName).indexOf(p)+'/'+path;
   const identity=section.className+'|'+(section.querySelector('h1,h2')?.textContent||section.tagName)+'|'+path;
   let hash=2166136261;for(const c of identity)hash=Math.imul(hash^c.charCodeAt(0),16777619);return 'e-'+(hash>>>0).toString(16);
 });
 let edits=JSON.parse(document.getElementById('website-layout').textContent),previewDevice;
 const applied=new WeakMap(),decorated=new WeakMap(),baselines=new WeakMap(),blockRows=[...extra.children];
 const imageSlots=new WeakMap(),originalPositions=new WeakMap(),blockImageHeights=new WeakMap(),originalFootprints=new WeakMap(),sectionSpacing=new WeakMap();
 nodes.filter(node=>node.tagName==='IMG').forEach(node=>originalPositions.set(node,window.getComputedStyle?.(node).position||'static'));
 nodes.forEach((node,index)=>{const style=document.createElement('span').style;style.cssText=originals[index].style||'';baselines.set(node,style);});
 const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('wb-animated','wb-'+entry.target.dataset.wbAnimation);observer.unobserve(entry.target);}}));
 function decorate(n,e={}){
   const previous=decorated.get(n)||{},baseline=baselines.get(n)||{};
   n.hidden=!!(e.hidden||e.deleted);const p=e[previewDevice||(innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop')]||e.desktop||{};
   const originalPosition=originalPositions.get(n)||'static';n.style.position=originalPosition==='static'?'relative':originalPosition;
   n.style.left=p.x?p.x+'px':baseline.left||'';n.style.top=p.y?p.y+'px':baseline.top||'';n.style.width=p.width?p.width+'%':baseline.width||'';
   if(['SPAN','SMALL'].includes(n.tagName))n.style.display=p.width||e.style?.height?'inline-block':baseline.display||'';
   if(n.matches('a.button')){n.style.flex=p.width?'0 0 auto':baseline.flex||'';n.style.boxSizing=p.width?'border-box':baseline.boxSizing||'';}
   Object.keys(previous.style||{}).forEach(key=>{if(!(key in (e.style||{})))n.style[key]=baseline[key]||'';});
   Object.entries(e.style||{}).forEach(([k,v])=>{n.style[k]=['fontSize','height','padding','gap','borderRadius','borderWidth'].includes(k)?(v||['borderRadius','borderWidth'].includes(k)?v+'px':''):v;});if(e.style?.borderWidth)n.style.borderStyle='solid';
   else if(previous.style?.borderWidth)n.style.borderStyle=baseline.borderStyle||'';
   if(n.tagName==='IMG'){n.style.objectFit=e.style?.objectFit||(e.photo?'contain':baseline.objectFit||'');if(e.naturalImage&&!e.style?.height)n.style.height='auto';}
   const a=e.animation||{},animationKey=JSON.stringify(a);decorated.set(n,{style:{...e.style},animationKey});
   if(previous.animationKey===animationKey)return;
   observer.unobserve(n);n.classList.remove('wb-animated',...['fade','slide-up','slide-left','zoom','bounce','float','pulse','rotate'].map(k=>'wb-'+k));n.onmouseenter=null;n.onmouseleave=null;delete n.dataset.wbAnimation;
   if(!a.kind||a.kind==='none')return;
   n.style.setProperty('--wb-duration',a.duration+'s');n.style.setProperty('--wb-delay',a.delay+'s');n.style.setProperty('--wb-repeat',a.repeat||1);n.style.setProperty('--wb-easing',a.easing||'ease');
   const start=()=>n.classList.add('wb-animated','wb-'+a.kind);
   if(a.trigger==='hover'){n.onmouseenter=start;n.onmouseleave=()=>n.classList.remove('wb-animated','wb-'+a.kind);}
   else if(a.trigger==='scroll'){observer.observe(n);n.dataset.wbAnimation=a.kind;}else start();
 }
 function setAttribute(n,key,value){if(value===undefined||value===null||(value===''&&key!=='alt')){if(n.hasAttribute(key))n.removeAttribute(key);}else if(n.getAttribute(key)!==String(value))n.setAttribute(key,value);}
 function setText(n,value){if(n.textContent!==value)n.textContent=value;}
 function reconcile(parent,desired){let cursor=parent.firstElementChild;desired.forEach(node=>{if(node!==cursor)parent.insertBefore(node,cursor);cursor=node.nextElementSibling;});}
 function preserveImageSlot(n,e){
   const position=e[previewDevice||(innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop')]||e.desktop||{};
   const resized=!e.deleted&&(!!position.width||!!e.style?.height||!!e.compactImage);
   if(!resized){const slot=imageSlots.get(n);if(slot){slot.parentElement.insertBefore(n,slot);slot.remove();imageSlots.delete(n);}return;}
   if(imageSlots.has(n)||['absolute','fixed'].includes(originalPositions.get(n)))return;
   const footprint=originalFootprints.get(n)||{width:n.offsetWidth,height:n.offsetHeight,parentWidth:n.parentElement.clientWidth};
   const {width,height}=footprint;if(!width||!height)return;originalFootprints.set(n,footprint);
   const slot=document.createElement('div');slot.className='wb-image-slot';
   const parentWidth=footprint.parentWidth||width;
   slot.style.width='100%';slot.style.aspectRatio=parentWidth+' / '+height;slot.style.position='relative';slot.style.overflow='visible';
   n.parentElement.insertBefore(slot,n);slot.append(n);imageSlots.set(n,slot);
 }
 function renderBlocks(){
   while(blockRows.length>(edits._blocks||[]).length){const removed=blockRows.pop();observer.unobserve(removed);removed.querySelectorAll('.wb-cell').forEach(node=>observer.unobserve(node));removed.remove();}
   (edits._blocks||[]).forEach((row,r)=>{
     const section=blockRows[r]||document.createElement('section');blockRows[r]=section;section.classList.add('section','wb-row');section.style.setProperty('--wb-columns',row.cells.length);section.dataset.builderRow=r;decorate(section,row);
     while(section.children.length>row.cells.length){observer.unobserve(section.lastElementChild);section.lastElementChild.remove();}
     row.cells.forEach((cell,c)=>{
       const article=section.children[c]||document.createElement('article');article.classList.add('wb-cell');article.dataset.builderCell=c;
       const contentTag=({image:'img',button:'a',video:'iframe',heading:'h2',review:'blockquote'})[cell.kind]||'p';
       if(!article.dataset.builderKind&&article.querySelector(contentTag))article.dataset.builderKind=cell.kind;
       if(article.dataset.builderKind!==cell.kind){article.replaceChildren();article.dataset.builderKind=cell.kind;article.append(document.createElement(contentTag));}
       let n=article.querySelector(cell.kind==='image'?'img':cell.kind==='video'?'iframe':cell.kind==='button'?'a':cell.kind==='heading'?'h2':cell.kind==='review'?'blockquote':'p');
       if(cell.kind==='image'){
         setAttribute(n,'src',cell.image);setAttribute(n,'alt',cell.alt||'');n.hidden=!cell.image;
         const link=n.parentElement!==article?n.parentElement:null;
         if(cell.link){const anchor=link||document.createElement('a');if(!link){article.insertBefore(anchor,n);anchor.append(n);}setAttribute(anchor,'href',cell.link);}
         else if(link){article.insertBefore(n,link);link.remove();}
       }else if(cell.kind==='button'){n.className='button pink';setAttribute(n,'href',cell.link||'#');setText(n,cell.text||'Button');}
       else if(cell.kind==='video'){n.title=cell.text||'Video';n.loading='lazy';let source='';if(cell.video){try{const url=new URL(cell.video);if(url.protocol==='https:'&&['www.youtube-nocookie.com','www.youtube.com','player.vimeo.com'].includes(url.hostname)&&/^\/(embed|video)\//.test(url.pathname))source=url.href;}catch{}}setAttribute(n,'src',source);if(!n.hasAttribute('allowfullscreen'))n.setAttribute('allowfullscreen','');}
       else{setText(n,cell.text||'');}
       if(cell.kind==='review'){let caption=article.querySelector('p');if(cell.caption){if(!caption){caption=document.createElement('p');article.append(caption);}setText(caption,cell.caption);}else caption?.remove();}
       const cellPosition=cell[previewDevice||(innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop')]||cell.desktop||{};
       const freeImageSize=cell.kind==='image'&&!cell.compactImage&&(!!cellPosition.width||!!cell.style?.height);
       if(freeImageSize&&!blockImageHeights.has(article)&&n.offsetHeight)blockImageHeights.set(article,n.offsetHeight);
       if(!freeImageSize)blockImageHeights.delete(article);
       decorate(article,cell);if(cell.kind==='image'){for(const key of ['objectFit','objectPosition'])n.style[key]=cell.style?.[key]||(key==='objectFit'?'contain':'');n.style.borderRadius=cell.style?.borderRadius!==undefined?cell.style.borderRadius+'px':'';n.style.height=cell.style?.height?cell.style.height+'px':'';article.style.height=cell.compactImage?Math.max(0,n.offsetHeight+(cellPosition.y||0))+'px':blockImageHeights.has(article)?blockImageHeights.get(article)+'px':'';}
       if(article.parentElement!==section)section.append(article);
     });
   });
   const order=[...(edits._sections||[]),...sections.map((_,i)=>i).filter(i=>!(edits._sections||[]).includes(i))],desired=[];
   order.forEach(index=>{if(!sections[index])return;(edits._blocks||[]).forEach((row,r)=>{if(row.before===index)desired.push(blockRows[r]);});desired.push(sections[index]);});
   desired.push(extra);reconcile(main,desired);
   reconcile(extra,blockRows.filter((_,r)=>!(edits._blocks[r].before>=0&&sections[edits._blocks[r].before])));
 }
 function apply(){
   sections.forEach((section,index)=>{
     if(!sectionSpacing.has(section))sectionSpacing.set(section,{paddingTop:section.style.paddingTop,paddingBottom:section.style.paddingBottom,gap:section.style.gap});
     const original=sectionSpacing.get(section),spacing=edits._spacing?.[index]||{};
     section.style.paddingTop=spacing.padding!==undefined?spacing.padding+'px':original.paddingTop;
     section.style.paddingBottom=spacing.padding!==undefined?spacing.padding+'px':original.paddingBottom;
     section.style.gap=spacing.gap!==undefined?spacing.gap+'px':original.gap;
   });
   nodes.forEach((n,i)=>{
     const original=originals[i],e=edits[keys[i]]||edits[i]||{},signature=JSON.stringify([e,previewDevice||(innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop')]),previous=applied.get(n);
     if(previous?.signature===signature)return;
     if(n.tagName==='IMG')preserveImageSlot(n,e);
     if(n.tagName!=='IMG'){if('text' in e)setText(n,e.text);else if(previous?.text)n.innerHTML=original.html;}
     if(n.tagName==='IMG'){setAttribute(n,'src',e.photo?e.image:original.src);setAttribute(n,'srcset',e.photo?null:original.srcset);setAttribute(n,'alt',e.alt??original.alt);}
     if(n.tagName==='A')setAttribute(n,'href',e.link||original.href);decorate(n,e);if(n.tagName==='IMG'&&e.photo&&!e.image)n.hidden=true;
     applied.set(n,{signature,text:'text' in e});
   });
   nodes.forEach((n,i)=>{
     const slot=imageSlots.get(n);if(!slot)return;
     const edit=edits[keys[i]]||edits[i]||{},position=edit[previewDevice||(innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop')]||edit.desktop||{};
     if(edit.compactImage){slot.style.aspectRatio='auto';slot.style.height=Math.max(0,n.offsetHeight+(position.y||0))+'px';}
     else{const original=originalFootprints.get(n);slot.style.height='';slot.style.aspectRatio=(original.parentWidth||original.width)+' / '+original.height;}
   });
   renderBlocks();
 }
 apply();addEventListener('resize',apply);window.websiteEditor={nodes,keys,sections,apply(data,device){edits=data;previewDevice=device;apply();}};
})();
