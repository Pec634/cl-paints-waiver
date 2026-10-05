(() => {
  'use strict';
  const core=window.CLStudioCore;
  if(!core)return;
  const panel=document.createElement('details');
  panel.className='paint-option-group';panel.open=false;
  panel.innerHTML=`<summary>Photo booth</summary><div class="paint-booth-options">
    <label>Lighting<select id="booth-light"><option value="neutral">Neutral studio</option><option value="daylight">Daylight</option><option value="warm">Warm party</option><option value="sunset">Sunset</option><option value="moon">Moonlight</option><option value="disco">Disco</option></select></label>
    <label>Brightness <output id="booth-brightness-value">100%</output><input id="booth-brightness" type="range" min="50" max="150" value="100"></label>
    <label>Warmth <output id="booth-warmth-value">0%</output><input id="booth-warmth" type="range" min="0" max="100" value="0"></label>
    <label>Backdrop frame<select id="booth-background"><option value="studio">Pastel studio</option><option value="forest">Enchanted forest</option><option value="carnival">Carnival</option><option value="ocean">Underwater</option><option value="stars">Starry sky</option></select></label>
    <label>Design name<input id="booth-title" maxlength="50" placeholder="Name your creation"></label>
    <label><input id="booth-compare" type="checkbox"> Before-and-after comparison</label>
    <label>Reveal painted design <output id="booth-reveal-value">50%</output><input id="booth-reveal" type="range" min="0" max="100" value="50" disabled></label>
    <p>Backdrops frame your portrait. Comparison is preview only; downloads include the complete design.</p>
    <button type="button" class="btn" id="booth-reset">Reset photo booth</button></div>`;
  document.querySelector('.paint-controls').appendChild(panel);
  const el=id=>document.getElementById('booth-'+id);
  const viewport=document.getElementById('paint-viewport');
  const presets={neutral:[100,0,0],daylight:[108,0,0],warm:[105,25,0],sunset:[98,40,-8],moon:[90,0,15],disco:[110,15,30]};
  const backgrounds={studio:['#fae8ff','#c7d2fe'],forest:['#052e16','#4ade80'],carnival:['#db2777','#facc15'],ocean:['#082f49','#22d3ee'],stars:['#0f172a','#6d28d9']};
  function filter(){const p=presets[el('light').value];return `brightness(${el('brightness').value}%) sepia(${el('warmth').value}%) saturate(${el('light').value==='disco'?150:100}%) hue-rotate(${p[2]}deg)`;}
  function update(){
    core.base.style.filter=core.canvas.style.filter=filter();
    const colours=backgrounds[el('background').value];
    viewport.style.boxShadow=`0 0 0 12px ${colours[0]},0 0 0 18px ${colours[1]}`;
    for(const key of ['brightness','warmth','reveal'])el(key+'-value').value=el(key).value+'%';
    el('reveal').disabled=!el('compare').checked;
    core.canvas.style.clipPath=el('compare').checked?`inset(0 ${100-Number(el('reveal').value)}% 0 0)`:'';
  }
  el('light').addEventListener('change',()=>{const p=presets[el('light').value];el('brightness').value=p[0];el('warmth').value=p[1];update();});
  panel.addEventListener('input',update);
  el('reset').addEventListener('click',()=>{el('light').value='neutral';el('brightness').value=100;el('warmth').value=0;el('background').value='studio';el('title').value='';el('compare').checked=false;el('reveal').value=50;update();});
  function compose(image){
    const result=document.createElement('canvas');result.width=720;result.height=860;
    const ctx=result.getContext('2d'),colours=backgrounds[el('background').value];
    const gradient=ctx.createLinearGradient(0,0,720,860);gradient.addColorStop(0,colours[0]);gradient.addColorStop(1,colours[1]);ctx.fillStyle=gradient;ctx.fillRect(0,0,720,860);
    ctx.fillStyle='#ffffff88';
    for(let i=0;i<45;i++){const x=(i*137+23)%720,y=(i*193+19)%860;ctx.beginPath();ctx.arc(x,y,el('background').value==='stars'?2:5,0,Math.PI*2);ctx.fill();}
    ctx.save();ctx.filter=filter();ctx.drawImage(image,60,40);ctx.restore();
    ctx.fillStyle='white';ctx.textAlign='center';ctx.font='bold 22px sans-serif';ctx.fillText(el('title').value.trim()||'My CL Paints creation',360,806,660);
    ctx.font='14px sans-serif';ctx.fillText('CL Paints Face Paint Studio',360,835);
    return result;
  }
  window.CLStudioBooth={compose};update();
})();
