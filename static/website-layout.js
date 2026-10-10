(() => {
 const main=document.getElementById('content'),extra=document.getElementById('website-extra-blocks');
 const nodes=[...main.querySelectorAll('img,h1,h2,h3,p,a.button')].filter(n=>!extra.contains(n));
 const originals=nodes.map(n=>({html:n.innerHTML,style:n.getAttribute('style'),src:n.getAttribute('src'),srcset:n.getAttribute('srcset'),alt:n.getAttribute('alt'),href:n.getAttribute('href')}));
 const sections=[...main.children].filter(n=>n!==extra);
 const keys=nodes.map(n=>{
   let section=n;while(section.parentElement!==main)section=section.parentElement;
   let path='';for(let p=n;p!==section;p=p.parentElement)path=p.tagName+':'+[...p.parentElement.children].filter(s=>s.tagName===p.tagName).indexOf(p)+'/'+path;
   const identity=section.className+'|'+(section.querySelector('h1,h2')?.textContent||section.tagName)+'|'+path;
   let hash=2166136261;for(const c of identity)hash=Math.imul(hash^c.charCodeAt(0),16777619);return 'e-'+(hash>>>0).toString(16);
 });
 let edits=JSON.parse(document.getElementById('website-layout').textContent),observer;
 function decorate(n,e={}){
   n.hidden=!!e.hidden;const p=e[innerWidth<=700?'mobile':innerWidth<=1000?'tablet':'desktop']||e.desktop||{};n.style.position='relative';n.style.left=(p.x||0)+'px';n.style.top=(p.y||0)+'px';if(p.width)n.style.width=p.width+'%';
   Object.entries(e.style||{}).forEach(([k,v])=>{n.style[k]=['fontSize','height','padding','gap','borderRadius','borderWidth'].includes(k)?(v?v+'px':''):v;});if(e.style?.borderWidth)n.style.borderStyle='solid';
   const a=e.animation||{};n.classList.remove('wb-animated',...['fade','slide-up','slide-left','zoom','bounce','float','pulse','rotate'].map(k=>'wb-'+k));n.onmouseenter=null;n.onmouseleave=null;
   if(!a.kind||a.kind==='none')return;
   n.style.setProperty('--wb-duration',a.duration+'s');n.style.setProperty('--wb-delay',a.delay+'s');n.style.setProperty('--wb-repeat',a.repeat||1);n.style.setProperty('--wb-easing',a.easing||'ease');
   const start=()=>n.classList.add('wb-animated','wb-'+a.kind);
   if(a.trigger==='hover'){n.onmouseenter=start;n.onmouseleave=()=>n.classList.remove('wb-animated','wb-'+a.kind);}
   else if(a.trigger==='scroll'){observer.observe(n);n.dataset.wbAnimation=a.kind;}else start();
 }
 function renderBlocks(){
   main.querySelectorAll('[data-builder-row]').forEach(n=>n.remove());extra.replaceChildren();
   (edits._blocks||[]).forEach((row,r)=>{
     const section=document.createElement('section');section.className='section wb-row';section.style.setProperty('--wb-columns',row.cells.length);section.dataset.builderRow=r;decorate(section,row);
     row.cells.forEach((cell,c)=>{
       const article=document.createElement('article');article.className='wb-cell';article.dataset.builderCell=c;let n;
       if(cell.kind==='image'){n=document.createElement('img');n.alt=cell.alt||'';if(cell.image)n.src=cell.image;else n.hidden=true;}
       else if(cell.kind==='button'){n=document.createElement('a');n.className='button pink';n.href=cell.link||'#';n.textContent=cell.text||'Button';}
       else if(cell.kind==='video'){n=document.createElement('iframe');n.title=cell.text||'Video';n.loading='lazy';if(cell.video){try{const url=new URL(cell.video);if(url.protocol==='https:'&&['www.youtube-nocookie.com','www.youtube.com','player.vimeo.com'].includes(url.hostname)&&/^\/(embed|video)\//.test(url.pathname))n.src=url.href;}catch{}}n.setAttribute('allowfullscreen','');}
       else{n=document.createElement(cell.kind==='heading'?'h2':cell.kind==='review'?'blockquote':'p');n.textContent=cell.text||'';}
       article.append(n);if(cell.kind==='review'&&cell.caption){const p=document.createElement('p');p.textContent=cell.caption;article.append(p);}if(cell.kind==='image'&&cell.link){const a=document.createElement('a');a.href=cell.link;n.replaceWith(a);a.append(n);}
       decorate(article,cell);if(cell.kind==='image'){for(const key of ['objectFit','objectPosition'])if(cell.style?.[key])n.style[key]=cell.style[key];if(cell.style?.height){n.style.height=cell.style.height+'px';article.style.height='';}}section.append(article);
     });if(row.before>=0&&sections[row.before])main.insertBefore(section,sections[row.before]);else extra.append(section);
   });
 }
 function apply(){
   observer?.disconnect();observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('wb-animated','wb-'+entry.target.dataset.wbAnimation);observer.unobserve(entry.target);}}));
   nodes.forEach((n,i)=>{
     const original=originals[i];n.setAttribute('style',original.style||'');n.innerHTML=original.html;
     if(n.tagName==='IMG'){n.src=original.src;if(original.srcset)n.setAttribute('srcset',original.srcset);else n.removeAttribute('srcset');n.alt=original.alt||'';n.hidden=false;}
     if(original.href)n.setAttribute('href',original.href);const e=edits[keys[i]]||edits[i]||{};
     if(n.tagName!=='IMG'&&'text' in e)n.textContent=e.text;
     if(n.tagName==='IMG'&&e.photo){n.removeAttribute('srcset');if(e.image)n.src=e.image;else n.removeAttribute('src');n.alt=e.alt||'';n.hidden=!e.image;}
     if(n.tagName==='A'&&e.link)n.href=e.link;decorate(n,e);if(n.tagName==='IMG'&&e.photo&&!e.image)n.hidden=true;
   });
   [...(edits._sections||[]),...sections.map((_,i)=>i).filter(i=>!(edits._sections||[]).includes(i))].forEach(i=>{if(sections[i])main.insertBefore(sections[i],extra);});renderBlocks();
 }
 apply();addEventListener('resize',apply);window.websiteEditor={nodes,keys,sections,apply(data){edits=data;apply();}};
})();
