/* Browser event contract checks, including environments without crypto APIs. */
async function runEmailTextBlockTests(source){
  let checks=0;const check=(value,message)=>{if(!value)throw Error(message);checks++;};
  class Element{
    constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.listeners={};this.value='';this.textContent='';}
    append(...children){this.children.push(...children);}replaceChildren(){this.children=[];}
    addEventListener(name,callback){(this.listeners[name]??=[]).push(callback);}
    click(){for(const callback of this.listeners.click||[])callback({});if(this.onclick)this.onclick({});}
    focus(){focused=this;}scrollIntoView(){}setAttribute(){}removeAttribute(){}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    querySelectorAll(selector){const match=selector.match(/\[data-([a-z-]+)(?:="([^"]+)")?\]/),found=[];
      if(!match)return found;const key=match[1].replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
      const walk=element=>element.children.forEach(child=>{if(key in child.dataset&&(match[2]===undefined||child.dataset[key]===match[2]))found.push(child);walk(child);});walk(this);return found;}
  }
  let focused=null,selected='booking';const timers=[],calls=[];
  const layouts={booking:{order:['heading','body','portal','footer'],media:{}},reward:{order:['heading','body','portal','footer'],media:{}}};
  const root=new Element(),list=new Element(),status=new Element(),add=new Element('button'),save=new Element('button'),quick=new Element('button'),preview=new Element('iframe');root.append(list);
  const forms={};for(const kind of ['booking','reward']){const form=new Element('form'),draft=new Element(),csrf=new Element('input');csrf.value='test-token';form.fields={[`notification_${kind}_body`]:'Main text'};
    form.querySelector=selector=>selector==='[data-email-draft-status]'?draft:csrf;forms[kind]={form,draft};}
  const design=new Element('form');design.fields={};
  root.querySelector=selector=>{
    if(selector==='[data-layout-status]')return status;if(selector==='[data-layout-blocks]')return list;
    if(selector==='[data-layout-add-text]')return add;if(selector==='[data-layout-save]')return save;if(selector==='[data-email-preview]')return preview;
    if(selector==='#email-design form')return design;if(selector==='[data-email-select][aria-pressed="true"]')return {dataset:{emailSelect:selected}};
    const form=selector.match(/\[data-email-composer="(booking|reward)"\]/);if(form)return selector.includes('data-email-draft-status')?forms[form[1]].draft:forms[form[1]].form;
    return Element.prototype.querySelector.call(list,selector);
  };
  root.querySelectorAll=selector=>selector==='[data-email-composer]'?Object.values(forms).map(value=>value.form):selector==='[data-email-add-text]'?[quick]:[];
  const document={querySelector:selector=>selector==='.email-workspace'?root:{textContent:JSON.stringify(selector==='#email-layout-data'?layouts:[])},createElement:tag=>new Element(tag)};
  class FormData{constructor(form){this.fields=form.fields;}forEach(callback){Object.entries(this.fields).forEach(([key,value])=>callback(value,key));}}
  const fetch=async(url,options)=>{calls.push({url,data:JSON.parse(options.body)});return {ok:true,json:async()=>({html:'Preview',saved:url.endsWith('/save')})};};
  new Function('document','setTimeout','clearTimeout','fetch','FormData',source)(document,callback=>{timers.push(callback);return timers.length;},()=>{},fetch,FormData);
  quick.click();let textarea=root.querySelector('[data-email-text-block]');
  check(!!textarea,'Composer button creates a text field without crypto APIs');check(focused===textarea,'New field receives keyboard focus');
  textarea.value='Hello {name}, introductory text';textarea.listeners.input[0]();await timers.at(-1)();
  let latest=calls.at(-1);const key=Object.keys(latest.data.layout.text_blocks)[0];
  check(latest.data.layout.text_blocks[key].text===textarea.value,'Typed text reaches the preview request');
  check(latest.data.layout.order.indexOf(key)<latest.data.layout.order.indexOf('portal'),'New text is placed before the portal button');
  save.click();await Promise.resolve();await Promise.resolve();check(calls.at(-1).url.endsWith('/save'),'Save includes extra text blocks');
  for(let index=0;index<7;index++)add.click();check(list.children.filter(row=>row.dataset.layoutBlock?.startsWith('text-')).length===8,'Eight extra fields can be created');
  add.click();check(status.textContent.includes('eight'),'Limit is shown instead of silently failing');
  const first=list.children.find(row=>row.dataset.layoutBlock===key);first.children[1].children.find(button=>button.textContent==='Delete').click();
  check(!list.children.some(row=>row.dataset.layoutBlock===key),'Remove deletes the extra field');
  const bodyBlock=list.children.find(row=>row.dataset.layoutBlock==='body');bodyBlock.children[1].children.find(button=>button.textContent==='Delete').click();await timers.at(-1)();
  check(!calls.at(-1).data.layout.order.includes('body')&&calls.at(-1).data.layout.deleted.includes('body'),'Deleting a built-in block persists its exclusion');
  selected='reward';root.listeners['email-template-selected'][0]();check(!root.querySelector('[data-email-text-block]'),'Booking fields stay separate from rewards');
  quick.click();check(!!root.querySelector('[data-email-text-block]'),'Rewards can add their own text field');
  return `${checks} email text-block interaction checks passed`;
}
if(typeof module!=='undefined'&&module.exports)runEmailTextBlockTests(require('node:fs').readFileSync('static/email-layout.js','utf8')).then(console.log).catch(error=>{console.error(error);process.exitCode=1;});
