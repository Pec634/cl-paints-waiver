(() => {
  const root=document.querySelector('.email-workspace');if(!root)return;
  const layouts=JSON.parse(document.querySelector('#email-layout-data').textContent);
  const media=JSON.parse(document.querySelector('#email-layout-media').textContent);
  const status=root.querySelector('[data-layout-status]');
  let kind='booking',timer,sequence=0;
  const node=(tag,text)=>{const element=document.createElement(tag);if(text)element.textContent=text;return element;};
  function update(){clearTimeout(timer);sequence++;status.textContent='Unsaved changes · updating preview…';timer=setTimeout(()=>request('preview'),300);}
  function controls(){
    root.querySelectorAll('[data-layout-key]').forEach(input=>{input.value=layouts[kind][input.dataset.layoutKey];});
    const list=root.querySelector('[data-layout-blocks]');list.replaceChildren();
    layouts[kind].order.forEach((key,index)=>{
      const item=media.find(value=>'media-'+value.id===key);
      const row=node('article');row.className='client-record email-layout-block';row.dataset.layoutBlock=key;
      row.append(node('strong',item?item.kind+': '+item.label:({heading:'Heading',body:'Message',portal:'Portal link',footer:'Footer'})[key]));
      const tools=node('div');tools.className='client-action-row';
      [-1,1].forEach(direction=>{const button=node('button',direction===-1?'Move up':'Move down');button.type='button';button.className='btn';button.disabled=index+direction<0||index+direction>=layouts[kind].order.length;
        button.setAttribute('aria-label',(direction===-1?'Move up ':'Move down ')+(item?item.label:key));
        button.addEventListener('click',()=>{const order=layouts[kind].order;[order[index],order[index+direction]]=[order[index+direction],order[index]];controls();update();list.querySelector('[data-layout-block="'+key+'"] button:not(:disabled)')?.focus();});tools.append(button);});row.append(tools);
      if(item){
        const options=layouts[kind].media[String(item.id)];
        const label=node('label','Alignment');const select=node('select');['left','center','right'].forEach(value=>{const option=node('option',value==='center'?'Centre':value);option.value=value;select.append(option);});select.value=options.align;
        select.addEventListener('change',()=>{options.align=select.value;update();});label.append(select);row.append(label);
        if(item.kind==='image'){
          const widthLabel=node('label','Image width (%)');const width=node('input');width.type='number';width.min=10;width.max=100;width.value=options.width;width.addEventListener('input',()=>{options.width=width.value;update();});widthLabel.append(width);row.append(widthLabel);
          const captionLabel=node('label','Caption');const caption=node('input');caption.maxLength=300;caption.value=options.caption;caption.addEventListener('input',()=>{options.caption=caption.value;update();});captionLabel.append(caption);row.append(captionLabel);
        }
        if(item.kind==='link'){
          const styleLabel=node('label','Link appearance');const style=node('select');['text','button'].forEach(value=>{const option=node('option',value==='text'?'Text link':'Button');option.value=value;style.append(option);});style.value=options.style;style.addEventListener('change',()=>{options.style=style.value;update();});styleLabel.append(style);row.append(styleLabel);
        }
      }list.append(row);
    });
  }
  async function request(action){
    const current=kind,version=++sequence;
    const form=root.querySelector('[data-email-composer="'+current+'"]');
    const fields={};[form,root.querySelector('#email-design form')].forEach(element=>{new FormData(element).forEach((value,key)=>{if(key.startsWith('notification_'))fields[key]=value;});});
    try {
      const response=await fetch('/admin/email-layout/'+current+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':form.querySelector('[name="csrf_token"]').value},body:JSON.stringify({layout:layouts[current],fields})});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Please reload settings and sign in again.');
      if(current!==kind||version!==sequence)return;
      root.querySelector('[data-email-preview]').srcdoc=result.html;
      status.textContent=action==='save'?'Content and layout saved.':'Live preview · unsaved changes';
      if(action==='save')form.querySelector('[data-email-draft-status]').textContent='Saved template';
    }catch(error){if(current===kind&&version===sequence)status.textContent='Preview: '+error.message;}
  }
  root.querySelectorAll('[data-layout-key]').forEach(input=>input.addEventListener('input',()=>{layouts[kind][input.dataset.layoutKey]=input.value;update();}));
  root.querySelectorAll('[data-email-composer]').forEach(form=>{form.addEventListener('input',update);form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);request('save');});});
  const design=root.querySelector('#email-design form');design.addEventListener('input',update);design.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);request('save');});
  root.querySelector('[data-layout-save]').addEventListener('click',()=>{clearTimeout(timer);request('save');});
  function switchTemplate(){kind=root.querySelector('[data-email-select][aria-pressed="true"]').dataset.emailSelect;root.querySelector('[data-email-preview]').removeAttribute('srcdoc');controls();update();}
  root.addEventListener('email-template-selected',switchTemplate);switchTemplate();
})();
