document.addEventListener('DOMContentLoaded',()=>{
 const main=document.querySelector('.admin main'),nav=document.querySelector('nav[aria-label="Admin navigation"]');if(!main||!nav)return;
 const read=key=>{try{return JSON.parse(localStorage.getItem(key));}catch{return null;}};
 const write=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{}};
 const links=[...nav.querySelectorAll('a[href]')].filter(a=>!a.hasAttribute('data-tool-search-only')&&!a.href.includes('logout'));
 const favourites=document.createElement('section');favourites.className='admin-favourites';favourites.setAttribute('aria-label','Favourite tools');
 const heading=document.createElement('strong');heading.textContent='Favourites';const list=document.createElement('div');favourites.append(heading,list);nav.before(favourites);
 const storageKey='cl-admin-favourites';let saved=read(storageKey);saved=Array.isArray(saved)?saved.filter(value=>typeof value==='string'):[];
 const pins=[];
 function render(){list.replaceChildren();links.filter(link=>saved.includes(link.getAttribute('href'))).forEach(link=>{const item=document.createElement('a');item.href=link.getAttribute('href');item.textContent=link.textContent;list.append(item);});
   if(!list.children.length){const note=document.createElement('small');note.textContent='Use the stars beside tools to pin them here.';list.append(note);}
   pins.forEach(({button,link})=>{const active=saved.includes(link.getAttribute('href'));button.textContent=active?'★':'☆';button.setAttribute('aria-pressed',String(active));button.setAttribute('aria-label',(active?'Unpin ':'Pin ')+link.textContent);});}
 links.forEach(link=>{const button=document.createElement('button');button.type='button';button.className='admin-pin';button.onclick=()=>{const href=link.getAttribute('href');saved=saved.includes(href)?saved.filter(value=>value!==href):[...saved,href];write(storageKey,saved);render();};
   const row=document.createElement('div');row.className='admin-pin-row';link.before(row);row.append(link,button);pins.push({button,link});});render();
 const search=document.getElementById('admin-tool-search');search?.addEventListener('input',()=>pins.forEach(({button,link})=>button.hidden=link.hidden));
 const quick=main.querySelector('[data-quick-actions]'),dialog=main.querySelector('#admin-quick-actions');
 quick?.addEventListener('click',()=>dialog.showModal());dialog?.querySelector('[data-close-actions]').addEventListener('click',()=>dialog.close());
 dialog?.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
 // Retain only non-sensitive list preferences. Searches and form contents are never saved.
 document.querySelectorAll('.admin form[method="get"]').forEach(form=>{
   if(form.matches('.reports-filters,[data-report-preferences]'))return;
   const fields=[...form.querySelectorAll('select[name],input[type="date"][name]')].filter(field=>['sort','status','filter','state','view','category','start','end','from','to'].includes(field.name));
   if(!fields.length)return;
   const key='cl-admin-list:'+location.pathname,stored=read(key);
   if(!location.search&&stored&&typeof stored==='object'){
     const params=new URLSearchParams();fields.forEach(field=>{const value=stored[field.name];if(typeof value!=='string')return;if(field.tagName==='SELECT'&&![...field.options].some(option=>option.value===value))return;params.set(field.name,value);});
     if(params.size){location.replace(location.pathname+'?'+params);return;}
   }
   form.addEventListener('submit',()=>{const preferences={};fields.forEach(field=>{if(!field.disabled)preferences[field.name]=field.value;});write(key,preferences);});
   const reset=document.createElement('button');reset.type='button';reset.className='btn';reset.textContent='Reset remembered filters';reset.onclick=()=>{try{localStorage.removeItem(key);}catch{}location.href=location.pathname+'?';};form.after(reset);
 });
});
