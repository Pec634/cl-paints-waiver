/* DOM contract checks for live updates. Run with node test_builder_live_preview.js. */
function runLivePreviewTests(source) {
  let checks=0;
  const check=(condition,message)=>{if(!condition)throw Error(message);checks++;};
  class Element {
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.dataset={};this.attributes={};this.writes={};this._text='';this._html='';this.style={setProperty(key,value){this[key]=value;}};this.hidden=false;this.classes=new Set();this.classList={add:(...values)=>values.forEach(value=>this.classes.add(value)),remove:(...values)=>values.forEach(value=>this.classes.delete(value))};}
    get className(){return [...this.classes].join(' ');}set className(value){this.classes=new Set(value.split(' ').filter(Boolean));}
    get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}set textContent(value){this._text=String(value);this._html=String(value);this.replaceChildren();}
    get innerHTML(){return this._html;}set innerHTML(value){this._html=value;this._text=value;this.replaceChildren();}
    get firstElementChild(){return this.children[0]||null;}get lastElementChild(){return this.children.at(-1)||null;}
    get nextElementSibling(){if(!this.parentElement)return null;return this.parentElement.children[this.parentElement.children.indexOf(this)+1]||null;}
    get src(){return this.getAttribute('src')||'';}get srcset(){return this.getAttribute('srcset')||'';}get alt(){return this.getAttribute('alt')||'';}
    append(...nodes){nodes.forEach(node=>this.insertBefore(node,null));}
    insertBefore(node,before){if(node===before)return;node.remove();let index=before?this.children.indexOf(before):this.children.length;if(index<0)throw Error('Invalid insertion reference');this.children.splice(index,0,node);node.parentElement=this;}
    remove(){if(this.parentElement){const list=this.parentElement.children;list.splice(list.indexOf(this),1);this.parentElement=null;}}
    replaceChildren(...nodes){[...this.children].forEach(node=>node.remove());this.append(...nodes);}
    contains(node){return node===this||this.children.some(child=>child.contains(node));}
    getAttribute(key){return key in this.attributes?this.attributes[key]:null;}hasAttribute(key){return key in this.attributes;}
    setAttribute(key,value){this.attributes[key]=String(value);this.writes[key]=(this.writes[key]||0)+1;}
    removeAttribute(key){delete this.attributes[key];this.writes[key]=(this.writes[key]||0)+1;}
    matches(selector){if(selector==='.wb-cell')return this.classes.has('wb-cell');return this.tagName.toLowerCase()===selector;}
    querySelectorAll(selector){const selectors=selector.split(',');const found=[];const walk=node=>node.children.forEach(child=>{if(selectors.some(part=>child.matches(part)))found.push(child);walk(child);});walk(this);return found;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  }
  const main=new Element('main'),nativeSection=new Element('section'),nativeImage=new Element('img'),paragraph=new Element('p'),extra=new Element('div');
  nativeSection.className='gallery';nativeImage.setAttribute('src','original.jpg');nativeImage.setAttribute('alt','Original photo');paragraph.textContent='Original text';
  nativeSection.append(nativeImage,paragraph);main.append(nativeSection,extra);
  const initial={_blocks:[{before:-1,cells:[{kind:'image',image:'added.jpg',alt:'Added image',animation:{kind:'fade',trigger:'load'}},{kind:'video',video:'https://www.youtube-nocookie.com/embed/example'}]}]};
  const serverRow=new Element('section'),serverCell=new Element('article'),serverImage=new Element('img'),serverVideoCell=new Element('article'),serverVideo=new Element('iframe');
  serverImage.setAttribute('src','added.jpg');serverVideo.setAttribute('src','https://www.youtube-nocookie.com/embed/example');serverCell.append(serverImage);serverVideoCell.append(serverVideo);serverRow.append(serverCell,serverVideoCell);extra.append(serverRow);
  const layout=new Element('script');layout.textContent=JSON.stringify(initial);
  const document={getElementById:id=>({'content':main,'website-extra-blocks':extra,'website-layout':layout})[id],createElement:tag=>new Element(tag)};
  const window={scrollX:0,scrollY:180};
  window.getComputedStyle=node=>({position:node.initialPosition||'static'});
  nativeImage.offsetWidth=100;nativeImage.offsetHeight=100;nativeSection.clientWidth=200;
  let observed=0;
  class Observer{observe(){observed++;}unobserve(){}}
  new Function('document','window','IntersectionObserver','innerWidth','addEventListener',source)(document,window,Observer,1200,()=>{});
  const editor=window.websiteEditor,clone=value=>JSON.parse(JSON.stringify(value));
  const row=extra.firstElementChild,cell=row.firstElementChild,image=cell.querySelector('img'),video=row.children[1].querySelector('iframe');
  check(extra.children.length===1&&row===serverRow,'Initial render adopts existing server rows without duplicating them');
  check(image===serverImage&&video===serverVideo,'Initial render retains server-rendered media');
  const imageWrites=image.writes.src,videoWrites=video.writes.src,nativeWrites=nativeImage.writes.src;
  const modified=clone(initial);modified._blocks[0].cells[0].desktop={x:48,y:16};
  editor.apply(modified,'desktop');
  check(extra.firstElementChild===row,'Moving an image keeps its row mounted');
  check(row.firstElementChild===cell&&cell.querySelector('img')===image,'Moving an image keeps its cell and image mounted');
  check(image.writes.src===imageWrites,'Dragging does not reload the image source');
  check(row.children[1].querySelector('iframe')===video&&video.writes.src===videoWrites,'Unrelated video is not replaced or reloaded');
  check(nativeImage.writes.src===nativeWrites,'Unrelated native image source stays untouched');
  check(cell.style.left==='48px'&&cell.style.top==='16px','Live offsets apply immediately');
  check(cell.classes.has('wb-animated')&&cell.classes.has('wb-fade'),'Position changes preserve animation classes');
  check(window.scrollY===180,'Preview update does not reset its scroll position');
  modified._blocks[0].cells[0].desktop.x=80;editor.apply(modified,'desktop');
  check(cell.querySelector('img')===image&&cell.style.left==='80px','Repeated live updates keep the same image');
  modified[editor.keys[1]]={text:'Updated text',desktop:{x:4}};editor.apply(modified,'desktop');
  check(paragraph.textContent==='Updated text','Native text is updated in place');
  delete modified[editor.keys[1]];editor.apply(modified,'desktop');
  check(paragraph.textContent==='Original text','Reset restores native text');
  modified._blocks[0].cells[0].link='/gallery';editor.apply(modified,'desktop');
  check(cell.querySelector('img')===image&&image.parentElement.tagName==='A','Adding a link preserves its image');
  delete modified._blocks[0].cells[0].link;editor.apply(modified,'desktop');
  check(image.parentElement===cell,'Removing a link preserves its image');
  modified._blocks[0].before=0;editor.apply(modified,'desktop');
  check(main.firstElementChild===row&&row.firstElementChild===cell,'Moving a row reuses the existing row and cell');
  modified._blocks[0].cells[0].kind='heading';modified._blocks[0].cells[0].text='New heading';editor.apply(modified,'desktop');
  check(cell.querySelector('h2').textContent==='New heading','Changing a block type replaces only its content');
  check(row.children[1].querySelector('iframe')===video,'Changing a sibling block type preserves the video');
  modified._blocks=[];editor.apply(modified,'desktop');
  check(row.parentElement===null&&main.firstElementChild===nativeSection,'Removing a row preserves native sections');
  modified[editor.keys[0]]={desktop:{width:50},style:{height:160}};editor.apply(modified,'desktop');
  const slot=nativeImage.parentElement;
  check(slot!==nativeSection&&slot.className==='wb-image-slot','Resizing a native image retains its own layout slot');
  check(slot.style.aspectRatio==='200 / 100','Original image footprint is retained instead of adopting its resized height');
  modified[editor.keys[0]].style.height=240;editor.apply(modified,'desktop');
  check(nativeImage.parentElement===slot&&slot.style.aspectRatio==='200 / 100','Repeated resizing does not grow the image layout slot');
  check(paragraph.parentElement===nativeSection,'Neighbouring content stays in its existing container');
  delete modified[editor.keys[0]];editor.apply(modified,'desktop');
  check(nativeImage.parentElement===nativeSection,'Reset restores the natural image layout');
  return `${checks} live-preview DOM checks passed`;
}
if(typeof module!=='undefined'&&module.exports)console.log(runLivePreviewTests(require('node:fs').readFileSync('static/website-layout.js','utf8')));
