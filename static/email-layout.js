(() => {
  const root=document.querySelector('.email-workspace');if(!root)return;
  const layouts=JSON.parse(document.querySelector('#email-layout-data').textContent);
  const media=JSON.parse(document.querySelector('#email-layout-media').textContent);
  const stagedAssets={};
  Object.values(layouts).forEach(layout=>{layout.text_blocks??={};});
  const status=root.querySelector('[data-layout-status]');
  let kind='booking',timer,sequence=0,nextTextId=0;
  const node=(tag,text)=>{const element=document.createElement(tag);if(text)element.textContent=text;return element;};
  function update(){clearTimeout(timer);sequence++;status.textContent='Unsaved changes · updating preview…';timer=setTimeout(()=>request('preview'),300);}
  function controls(){
    root.querySelectorAll('[data-layout-key]').forEach(input=>{input.value=layouts[kind][input.dataset.layoutKey];});
    const list=root.querySelector('[data-layout-blocks]');list.replaceChildren();
    layouts[kind].order.forEach((key,index)=>{
      const available=stagedAssets[kind]?stagedAssets[kind].map((item,index)=>({...item,id:-(index+1)})):media;
      const item=available.find(value=>'media-'+value.id===key);
      const row=node('article');row.className='client-record email-layout-block';row.dataset.layoutBlock=key;
      const textBlock=layouts[kind].text_blocks[key];
      row.append(node('strong',textBlock?'Text section':item?item.kind+': '+item.label:({heading:'Heading',body:'Message',portal:'Portal link',footer:'Footer'})[key]));
      const tools=node('div');tools.className='client-action-row';
      [-1,1].forEach(direction=>{const button=node('button',direction===-1?'Move up':'Move down');button.type='button';button.className='btn';button.disabled=index+direction<0||index+direction>=layouts[kind].order.length;
        button.setAttribute('aria-label',(direction===-1?'Move up ':'Move down ')+(item?item.label:key));
        button.addEventListener('click',()=>{const order=layouts[kind].order;[order[index],order[index+direction]]=[order[index+direction],order[index]];controls();update();list.querySelector('[data-layout-block="'+key+'"] button:not(:disabled)')?.focus();});tools.append(button);});row.append(tools);
      if(textBlock){
        const label=node('label','Text');const textarea=node('textarea');textarea.rows=5;textarea.maxLength=5000;textarea.value=textBlock.text;textarea.dataset.emailTextBlock=key;
        textarea.addEventListener('input',()=>{textBlock.text=textarea.value;update();});label.append(textarea);row.append(label);
        const tokens=node('div');tokens.className='client-action-row';
        for(const [token,title] of [['{name}','Client name'],['{reference}','Reference'],['{details}','Update details']]){const insert=node('button',title);insert.type='button';insert.className='btn';insert.onclick=()=>{textarea.setRangeText(token,textarea.selectionStart,textarea.selectionEnd,'end');textarea.focus();textarea.dispatchEvent(new Event('input',{bubbles:true}));};tokens.append(insert);}row.append(tokens);
        const remove=node('button','Remove text block');remove.type='button';remove.className='btn';remove.onclick=()=>{delete layouts[kind].text_blocks[key];layouts[kind].order=layouts[kind].order.filter(value=>value!==key);controls();update();root.querySelector('[data-layout-add-text]').focus();};tools.append(remove);
      }
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
      const response=await fetch('/admin/email-layout/'+current+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':form.querySelector('[name="csrf_token"]').value},body:JSON.stringify({layout:layouts[current],fields,...(stagedAssets[current]?{assets:stagedAssets[current]}:{})})});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Please reload settings and sign in again.');
      if(current!==kind||version!==sequence)return;
      root.querySelector('[data-email-preview]').srcdoc=result.html;
      status.textContent=action==='save'?'Content and layout saved.':'Live preview · unsaved changes';
      if(action==='save'){
        form.querySelector('[data-email-draft-status]').textContent='Saved template';
        if(stagedAssets[current]){delete stagedAssets[current];layouts[current]=result.layout;for(const item of result.media||[]){const index=media.findIndex(old=>old.id===item.id);if(index<0)media.push(item);else media[index]=item;}controls();}
      }
    }catch(error){if(current===kind&&version===sequence)status.textContent='Preview: '+error.message;}
  }
  root.querySelectorAll('[data-layout-key]').forEach(input=>input.addEventListener('input',()=>{layouts[kind][input.dataset.layoutKey]=input.value;update();}));
  root.querySelectorAll('[data-email-composer]').forEach(form=>{form.addEventListener('input',update);form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);request('save');});});
  const design=root.querySelector('#email-design form');design.addEventListener('input',update);design.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);request('save');});
  root.querySelector('[data-layout-save]').addEventListener('click',()=>{clearTimeout(timer);request('save');});
  function addTextBlock(){
    try{
      const layout=layouts[kind];if(Object.keys(layout.text_blocks).length>=8){status.textContent='You can add up to eight extra text blocks.';return;}
      // Block identifiers are layout keys, not security tokens. Avoid browser crypto dependencies.
      let key;do{key='text-'+Date.now().toString(36)+(++nextTextId).toString(36);}while(layout.text_blocks[key]);
      layout.text_blocks[key]={text:''};
      const before=layout.order.indexOf('portal');layout.order.splice(before<0?layout.order.length:before,0,key);controls();update();
      root.querySelector('[data-email-composer="'+kind+'"] [data-email-draft-status]').textContent='Unsaved changes';
      const textarea=root.querySelector('[data-email-text-block="'+key+'"]');textarea.focus();textarea.scrollIntoView?.({block:'center'});
    }catch(error){status.textContent='Could not add a text block: '+error.message;}
  }
  root.querySelector('[data-layout-add-text]').addEventListener('click',addTextBlock);
  root.querySelectorAll('[data-email-add-text]').forEach(button=>button.addEventListener('click',addTextBlock));
  root.emailPresetEditor={
    snapshot(){const fields={};for(const form of [root.querySelector('[data-email-composer="'+kind+'"]'),design])new FormData(form).forEach((value,key)=>{if(key.startsWith('notification_'))fields[key]=value;});return {kind,layout:structuredClone(layouts[kind]),fields,...(stagedAssets[kind]?{assets:structuredClone(stagedAssets[kind])}:{})};},
    load(preset){
      clearTimeout(timer);sequence++;layouts[kind]=structuredClone(preset.layout);stagedAssets[kind]=structuredClone(preset.assets);
      const form=root.querySelector('[data-email-composer="'+kind+'"]');
      form.querySelector('[name="notification_'+kind+'_subject"]').value=preset.fields.subject;
      let body=preset.fields.body;if(kind.includes('enquiry')&&!body.includes('{details}'))body+='\n\n{details}';
      form.querySelector('[name="notification_'+kind+'_body"]').value=body;
      for(const key of ['notification_heading','notification_footer','notification_colour','notification_layout'])design.querySelector('[name="'+key+'"]').value=preset.fields[key];
      form.querySelector('[data-email-draft-status]').textContent='Loaded preset · unsaved';controls();update();
    }
  };
  function switchTemplate(){kind=root.querySelector('[data-email-select][aria-pressed="true"]').dataset.emailSelect;root.querySelector('[data-email-preview]').removeAttribute('srcdoc');controls();update();}
  root.addEventListener('email-template-selected',switchTemplate);switchTemplate();
})();
