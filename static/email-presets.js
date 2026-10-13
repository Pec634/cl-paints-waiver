(() => {
 const root=document.querySelector('.email-workspace');if(!root?.emailPresetEditor)return;
 const find=name=>root.querySelector('[data-preset-'+name+']'),status=find('status'),select=find('select');
 const csrf=()=>root.querySelector('[name="csrf_token"]').value;
 let busy=false;
 async function call(path,body){const response=await fetch('/admin/email-presets'+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify(body)}:{});if(!(response.headers.get('content-type')||'').includes('application/json'))throw Error('Reload email settings and sign in again.');const data=await response.json();if(!response.ok)throw Error(data.error||'The preset request failed.');return data;}
 function selected(){if(!select.value)throw Error('Choose a saved preset first.');return select.value;}
 function exportLink(){const link=find('export');link.hidden=!select.value;link.href='/admin/email-presets/'+select.value+'/export';}
 async function list(chosen=''){const data=await call('');select.replaceChildren(new Option('Choose a preset',''));data.presets.forEach(item=>select.add(new Option(item.name,item.id)));select.value=chosen;exportLink();}
 async function action(run){if(busy)return;busy=true;root.querySelectorAll('.email-preset-library button').forEach(button=>button.disabled=true);status.textContent='Working…';try{await run();}catch(error){status.textContent=error.message;}finally{busy=false;root.querySelectorAll('.email-preset-library button').forEach(button=>button.disabled=false);}}
 select.addEventListener('change',exportLink);
 find('save').onclick=()=>action(async()=>{const name=find('name').value.trim();if(!name)throw Error('Enter a name for this preset.');const result=await call('/save',{name,...root.emailPresetEditor.snapshot()});await list(result.id);status.textContent='Preset saved as an independent copy.';});
 find('load').onclick=()=>action(async()=>{const preset=await call('/'+selected()+'/load');root.emailPresetEditor.load(preset);status.textContent='Preset loaded into the current draft. Preview it, then Save content & layout to apply. Existing media for that response type are retained when saving.';});
 find('import').onclick=()=>action(async()=>{const file=find('file').files[0];if(!file)throw Error('Choose a JSON preset file.');if(file.size>8*1024*1024)throw Error('Choose a preset file under 8 MB.');let data;try{data=JSON.parse(await file.text());}catch{throw Error('This is not a valid JSON preset file.');}const result=await call('/import',data);await list(result.id);find('file').value='';status.textContent='Preset imported into the library. Load it into a response to preview it.';});
 find('delete').onclick=()=>action(async()=>{const id=selected();await call('/'+id+'/delete',{});await list();status.textContent='Preset deleted. Your active response templates are unchanged.';});
 list().catch(error=>status.textContent=error.message);
})();
