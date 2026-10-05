/* Discrete sliders retain the renderer's existing named choices. */
(() => {
 const get=id=>document.getElementById('paint-'+id),sliders=[];
 function blend(a,b,t){const channels=hex=>hex.slice(1).match(/../g).map(v=>parseInt(v,16));const x=channels(a),y=channels(b);return '#'+x.map((v,i)=>Math.round(v+(y[i]-v)*t).toString(16).padStart(2,'0')).join('');}
 function decorate(range){range.classList.add('paint-character-slider');const percent=Math.round((Number(range.value)-Number(range.min))/(Number(range.max)-Number(range.min))*100);range.style.setProperty('--slider-fill',percent+'%');return percent;}
 function endpoints(range,left,right){const row=document.createElement('span');row.className='paint-slider-endpoints';const a=document.createElement('span'),b=document.createElement('span');a.textContent=left;b.textContent=right;row.append(a,b);range.after(row);}

 for(const id of ['face','skin','facial-hair','eye-colour','brows','freckles','lips']){
  const select=get(id),range=document.createElement('input'),output=document.createElement('output');range.type='range';range.min=0;range.max=100;range.step=1;range.id='paint-'+id+'-slider';range.setAttribute('aria-label',select.parentElement.firstChild.textContent.trim());select.hidden=true;output.className='paint-slider-readout';output.htmlFor=range.id;select.parentElement.append(output,range);endpoints(range,select.options[0].textContent,select.options[select.options.length-1].textContent);
  let sliding=false;const sync=()=>{if(!sliding)range.value=Math.round(select.selectedIndex/(select.options.length-1)*100);const percent=decorate(range);output.value=select.selectedOptions[0].textContent+' ('+percent+'%)';range.disabled=select.disabled;range.setAttribute('aria-valuetext',output.value);const colour=select.value.startsWith('#')?select.value:null;output.classList.toggle('paint-slider-colour',!!colour);if(colour)output.style.setProperty('--character-colour',colour);};
  range.addEventListener('input',()=>{sliding=true;const position=Number(range.value)/100*(select.options.length-1);select.selectedIndex=Math.round(position);window.CLCharacterColours=window.CLCharacterColours||{};if(['skin','eye-colour'].includes(id)){window.CLCharacterColours[id]=blend(select.options[Math.floor(position)].value,select.options[Math.ceil(position)].value,position%1);}select.dispatchEvent(new Event('change'));sync();sliding=false;});select.addEventListener('change',sync);sliders.push(sync);sync();
 }
 for(const id of ['height','width']){const range=get(id);get(id+'-value').classList.add('paint-slider-readout');endpoints(range,'0%','100%');decorate(range);range.addEventListener('input',()=>{decorate(range);range.setAttribute('aria-valuetext',range.value+'%');});}
 get('model').addEventListener('change',()=>sliders.forEach(sync=>sync()));get('surprise').addEventListener('click',()=>sliders.forEach(sync=>sync()));
})();
