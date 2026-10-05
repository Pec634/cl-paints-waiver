/* Custom colour bands are copied into each stroke, preserving existing artwork. */
(() => {
 const core=window.CLStudioCore;if(!core)return;
 const mode=document.getElementById('paint-colour-mode'),preview=document.getElementById('paint-cake-preview');
 const li=document.createElement('li');li.innerHTML=`<details class="paint-character-group"><summary>Create your own split cake</summary><div class="split-cake-builder"><div id="split-builder-preview" class="paint-cake-preview" aria-label="Custom split cake preview"></div><div id="split-builder-bands"></div><div class="paint-actions"><button type="button" class="btn" id="split-add">Add colour</button><button type="button" class="btn" id="split-reverse">Reverse colours</button><button type="button" class="btn" id="split-copy">Start from selected cake</button></div><button type="button" class="btn primary" id="split-use">Paint with this cake</button><label>Cake name<input id="split-name" maxlength="40" placeholder="My sunset colours"></label><button type="button" class="btn" id="split-save">Keep named cake</button><p id="split-status" role="status">Choose 2-8 colour bands. Named cakes stay available until you leave or refresh.</p></div></details>`;
 preview.closest('ul').append(li);
 const get=id=>document.getElementById('split-'+id);let colours=[...core.cakes.custom],saved=0;
 const gradient=list=>'linear-gradient(90deg,'+list.flatMap((colour,i)=>[colour+' '+i*100/list.length+'%',colour+' '+(i+1)*100/list.length+'%']).join(',')+')';
 function refresh(){get('builder-preview').style.background=gradient(colours);get('add').disabled=colours.length>=8;core.cakes.custom=[...colours];if(mode.value==='custom')preview.style.background=gradient(colours);}
 function rows(){get('builder-bands').replaceChildren();colours.forEach((colour,i)=>{const row=document.createElement('div');row.className='split-colour-row';const label=document.createElement('label'),input=document.createElement('input');input.type='color';input.value=colour;label.append(document.createTextNode('Band '+(i+1)),input);input.oninput=()=>{colours[i]=input.value;refresh();};row.append(label);
  for(const [text,action,disabled] of [['Up',()=>{[colours[i-1],colours[i]]=[colours[i],colours[i-1]];rows();},i===0],['Down',()=>{[colours[i+1],colours[i]]=[colours[i],colours[i+1]];rows();},i===colours.length-1],['Remove',()=>{colours.splice(i,1);rows();},colours.length<=2]]){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=text;button.setAttribute('aria-label',text+' band '+(i+1));button.disabled=disabled;button.onclick=action;row.append(button);}get('builder-bands').append(row);});refresh();}
 function use(){core.cakes.custom=[...colours];mode.value='custom';mode.dispatchEvent(new Event('change'));get('status').textContent='Custom cake loaded. Your selected split-cake brush is ready.';}
 get('add').onclick=()=>{if(colours.length<8){colours.push(document.getElementById('paint-colour').value);rows();}};
 get('reverse').onclick=()=>{colours.reverse();rows();};
 get('copy').onclick=()=>{if(!core.cakes[mode.value]){get('status').textContent='Select a split cake first.';return;}colours=[...core.cakes[mode.value]];rows();get('status').textContent='Colours copied into your builder.';};
 get('use').onclick=use;
 get('save').onclick=()=>{if(saved>=12){get('status').textContent='You can keep 12 named cakes in this page.';return;}const name=get('name').value.trim()||'Custom cake '+(saved+1),key='userCake'+(++saved);core.cakes[key]=[...colours];mode.add(new Option(name,key));mode.value=key;mode.dispatchEvent(new Event('change'));get('status').textContent='Saved '+name+' in the colour-mode list.';};
 rows();
})();
