(() => {
  const get = id => document.getElementById(`paint-${id}`);
  const canvas = get('canvas'), base = get('base');
  if (!canvas) return;
  const ctx = canvas.getContext('2d'), bg = base.getContext('2d');
  const strokes = []; let redo = [], active = null;
  function face() {
    const shape = get('face').value;
    return {x:300,y:335,rx:shape === 'round' ? 190 : 165,ry:shape === 'long' ? 260 : shape === 'round' ? 215 : 245};
  }
  function ellipse(context, f) {
    context.beginPath();context.ellipse(f.x,f.y,f.rx,f.ry,0,0,Math.PI*2);
  }
  function tint(hex, amount) {
    const channels=hex.replace('#','').match(/../g).map(v=>Math.max(0,Math.min(255,parseInt(v,16)+amount)));
    return `rgb(${channels.join(',')})`;
  }
  function hairCap(f) {
    bg.beginPath();
    bg.ellipse(f.x,f.y,f.rx+9,f.ry+12,0,Math.PI,Math.PI*2);
    bg.lineTo(300+f.rx-12,325);
    bg.bezierCurveTo(300+f.rx-20,245,365,210,320,225);
    bg.bezierCurveTo(270,190,210,225,300-f.rx+12,325);
    bg.closePath();
  }
  function drawFace() {
    const f=face(),skin=get('skin').value,hair=get('hair').value,colour=get('hair-colour').value;
    const top=f.y-f.ry;
    bg.clearRect(0,0,600,720);
    // Back hair sits behind the ears and face, rather than across the cheeks.
    bg.fillStyle=tint(colour,-20);
    if(hair==='long') {
      bg.beginPath();bg.moveTo(300-f.rx-22,250);bg.bezierCurveTo(300-f.rx-35,70,300+f.rx+35,70,300+f.rx+22,250);
      bg.lineTo(300+f.rx+38,660);bg.quadraticCurveTo(300,710,300-f.rx-38,660);bg.closePath();bg.fill();
    }
    if(hair==='pigtails') {
      for(const side of [-1,1]){bg.beginPath();bg.ellipse(300+side*(f.rx+25),355,42,145,side*-.18,0,Math.PI*2);bg.fill();}
    }
    const neck=bg.createLinearGradient(235,0,365,0);neck.addColorStop(0,tint(skin,-35));neck.addColorStop(.5,skin);neck.addColorStop(1,tint(skin,-25));
    bg.fillStyle=neck;bg.fillRect(240,495,120,160);
    bg.fillStyle='#a78bfa';bg.beginPath();bg.ellipse(300,735,235,120,0,0,Math.PI*2);bg.fill();
    // Ears with a helix and a shaded inner fold.
    for(const side of [-1,1]) {
      const x=300+side*(f.rx-5);
      const ear=bg.createRadialGradient(x,337,4,x,340,42);ear.addColorStop(0,skin);ear.addColorStop(1,tint(skin,-35));
      bg.fillStyle=ear;bg.beginPath();bg.ellipse(x,340,29,52,side*.12,0,Math.PI*2);bg.fill();
      bg.strokeStyle=tint(skin,-65);bg.lineWidth=2;bg.beginPath();bg.ellipse(x+side*6,337,14,32,side*.1,-Math.PI/2,Math.PI/2);bg.stroke();
      bg.beginPath();bg.moveTo(x+side*7,324);bg.quadraticCurveTo(x-side*9,336,x+side*4,355);bg.stroke();
    }
    const complexion=bg.createRadialGradient(270,285,35,310,350,f.ry);
    complexion.addColorStop(0,tint(skin,15));complexion.addColorStop(.65,skin);complexion.addColorStop(1,tint(skin,-40));
    ellipse(bg,f);bg.fillStyle=complexion;bg.fill();
    bg.save();ellipse(bg,f);bg.clip();
    for(const x of [212,388]) {
      const cheek=bg.createRadialGradient(x,383,2,x,383,56);cheek.addColorStop(0,'rgba(182,75,76,.14)');cheek.addColorStop(1,'rgba(182,75,76,0)');
      bg.fillStyle=cheek;bg.fillRect(x-56,327,112,112);
    }
    bg.restore();
    bg.lineCap='round';
    for(const x of [235,365]) {
      bg.strokeStyle=tint(skin,-85);bg.lineWidth=2;
      if(get('expression').value==='wink' && x===365){bg.beginPath();bg.moveTo(x-32,310);bg.quadraticCurveTo(x,321,x+32,310);bg.stroke();}
      else {
        bg.beginPath();bg.moveTo(x-33,306);bg.quadraticCurveTo(x,280,x+33,306);bg.quadraticCurveTo(x,325,x-33,306);bg.fillStyle='#f5f1ed';bg.fill();bg.stroke();
        bg.beginPath();bg.arc(x,305,11,0,Math.PI*2);bg.fillStyle='#6b775d';bg.fill();
        bg.beginPath();bg.arc(x,305,5,0,Math.PI*2);bg.fillStyle='#202020';bg.fill();
        bg.beginPath();bg.arc(x-3,301,2.5,0,Math.PI*2);bg.fillStyle='#fff';bg.fill();
      }
      bg.strokeStyle=colour;bg.lineWidth=5;bg.beginPath();bg.moveTo(x-32,276);bg.quadraticCurveTo(x,265,x+29,275);bg.stroke();
    }
    // Soft nose contours and highlights instead of a triangular outline.
    bg.strokeStyle=tint(skin,-45);bg.lineWidth=2;
    for(const side of [-1,1]){bg.beginPath();bg.moveTo(300+side*12,326);bg.bezierCurveTo(300+side*9,350,300+side*23,375,300+side*16,383);bg.stroke();}
    bg.beginPath();bg.moveTo(281,386);bg.quadraticCurveTo(300,396,319,386);bg.stroke();
    bg.fillStyle=tint(skin,-70);for(const x of [288,312]){bg.beginPath();bg.ellipse(x,386,5,2,0,0,Math.PI*2);bg.fill();}
    bg.fillStyle=tint(skin,-25);
    bg.beginPath();
    if(get('expression').value==='surprise') {bg.ellipse(300,446,19,27,0,0,Math.PI*2);bg.fillStyle=tint(skin,-95);bg.fill();}
    else {bg.moveTo(254,435);bg.quadraticCurveTo(280,417,300,429);bg.quadraticCurveTo(320,417,346,435);bg.quadraticCurveTo(300,460,254,435);bg.fill();bg.strokeStyle=tint(skin,-70);bg.lineWidth=1.5;bg.beginPath();bg.moveTo(254,435);bg.quadraticCurveTo(300,442,346,435);bg.stroke();}
    const hairGradient=bg.createLinearGradient(130,0,475,0);hairGradient.addColorStop(0,tint(colour,-25));hairGradient.addColorStop(.4,tint(colour,24));hairGradient.addColorStop(1,tint(colour,-18));
    bg.fillStyle=hairGradient;
    if(hair!=='none') {
      hairCap(f);bg.fill();
      // Strands follow the crown; every style has a continuous scalp covering.
      bg.save();hairCap(f);bg.clip();bg.strokeStyle=tint(colour,36);bg.globalAlpha=.35;bg.lineWidth=1.5;
      for(let i=-7;i<=7;i++){bg.beginPath();bg.moveTo(305,top-5);bg.bezierCurveTo(300+i*12,top+40,300+i*24,160,300+i*27,325);bg.stroke();}
      bg.restore();
    }
    if(hair==='curly') {
      for(let i=0;i<=16;i++){const a=Math.PI+i*Math.PI/16;const x=300+Math.cos(a)*(f.rx+2),y=335+Math.sin(a)*(f.ry+5);bg.beginPath();bg.arc(x,y,23,0,Math.PI*2);bg.fill();bg.strokeStyle=tint(colour,20);bg.lineWidth=2;bg.beginPath();bg.arc(x,y,13,0,Math.PI*1.5);bg.stroke();}
    }
    if(hair==='mohawk') {
      bg.beginPath();bg.moveTo(272,220);bg.lineTo(266,top-8);bg.lineTo(285,top+9);bg.lineTo(300,Math.max(12,top-48));bg.lineTo(316,top+9);bg.lineTo(335,top-8);bg.lineTo(328,220);bg.closePath();bg.fill();
    }
    if(hair==='pigtails'){bg.fillStyle='#f52f83';for(const side of [-1,1]){bg.beginPath();bg.ellipse(300+side*(f.rx+12),260,20,8,side*.2,0,Math.PI*2);bg.fill();}}
    const facial=get('facial-hair').value;bg.fillStyle=hairGradient;bg.strokeStyle=colour;
    if(facial==='beard') {
      bg.save();ellipse(bg,f);bg.clip();bg.beginPath();bg.moveTo(300-f.rx,395);bg.quadraticCurveTo(300,650,300+f.rx,395);bg.lineTo(300+f.rx,620);bg.lineTo(300-f.rx,620);bg.closePath();bg.fill();bg.restore();
    }
    if(facial!=='none') {
      for(const side of [-1,1]){bg.beginPath();bg.moveTo(300,408);bg.bezierCurveTo(300+side*20,390,300+side*35,425,300+side*65,400);bg.quadraticCurveTo(300+side*55,440,300,415);bg.fill();}
      if(facial==='handlebar'){bg.lineWidth=6;for(const side of [-1,1]){bg.beginPath();bg.arc(300+side*65,398,17,side===1?0:Math.PI,side===1?Math.PI*1.5:Math.PI*2.5);bg.stroke();}}
    }
  }
  function stamp(x,y,stroke) {
    ctx.beginPath();
    if(stroke.tool==='stars') {
      for(let i=0;i<10;i++) {
        const a=-Math.PI/2+i*Math.PI/5,r=stroke.size*(i%2 ? .45 : 1);
        const px=x+Math.cos(a)*r,py=y+Math.sin(a)*r;
        if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
      }
      ctx.closePath();
    } else ctx.arc(x,y,stroke.size/2,0,Math.PI*2);
    ctx.fill();
  }
  function draw(stroke,mirror=false) {
    ctx.save();ellipse(ctx,face());ctx.clip();
    ctx.globalCompositeOperation=stroke.tool==='eraser' ? 'destination-out' : 'source-over';
    ctx.strokeStyle=stroke.colour;ctx.fillStyle=stroke.colour;ctx.lineWidth=stroke.size;ctx.lineCap='round';ctx.lineJoin='round';
    const points=stroke.points.map(p=>({x:mirror ? 600-p.x : p.x,y:p.y}));
    if(stroke.tool==='stars'||stroke.tool==='dots'||points.length===1)points.forEach(p=>stamp(p.x,p.y,stroke));
    else {ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);points.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();}
    ctx.restore();
  }
  function render() {
    ctx.clearRect(0,0,600,720);
    for(const stroke of strokes.concat(active ? [active] : [])){draw(stroke);if(stroke.mirror)draw(stroke,true);}
    get('undo').disabled=!strokes.length;get('redo').disabled=!redo.length;
    updateMission();
  }
  function point(event) {const rect=canvas.getBoundingClientRect();return {x:(event.clientX-rect.left)*600/rect.width,y:(event.clientY-rect.top)*720/rect.height};}
  canvas.addEventListener('pointerdown',event=>{
    if(active || (event.pointerType==='mouse' && event.button!==0))return;
    event.preventDefault();canvas.setPointerCapture(event.pointerId);
    active={round:missionRound,pointer:event.pointerId,colour:get('colour').value,size:Number(get('size').value),tool:get('tool').value,mirror:get('mirror').checked,points:[point(event)]};render();
  });
  canvas.addEventListener('pointermove',event=>{
    if(!active || active.pointer!==event.pointerId)return;
    const p=point(event),last=active.points[active.points.length-1];
    const distance=Math.hypot(p.x-last.x,p.y-last.y);
    if(distance < (active.tool==='stars'||active.tool==='dots' ? active.size*1.5 : 2))return;
    active.points.push(p);render();
  });
  function finish(event) {
    if(!active || active.pointer!==event.pointerId)return;
    const f=face();
    if(active.points.some(p=>((p.x-f.x)/f.rx)**2+((p.y-f.y)/f.ry)**2<=1))strokes.push(active);
    active=null;redo=[];render();get('status').textContent='Looking colourful! Keep creating.';
  }
  canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);canvas.addEventListener('lostpointercapture',finish);
  get('undo').addEventListener('click',()=>{if(active)return;const stroke=strokes.pop();if(stroke)redo.push(stroke);render();});
  get('redo').addEventListener('click',()=>{if(active)return;const stroke=redo.pop();if(stroke)strokes.push(stroke);render();});
  get('clear').addEventListener('click',()=>{if(strokes.length && !window.confirm('Clear your painted design?'))return;active=null;strokes.length=0;redo=[];render();get('status').textContent='A fresh face, ready for your next idea.';});
  for(const id of ['face','skin','hair','hair-colour','facial-hair','expression'])get(id).addEventListener('change',()=>{drawFace();render();});
  get('surprise').addEventListener('click',()=>{
    for(const id of ['face','skin','hair','facial-hair','expression']){const select=get(id);select.selectedIndex=Math.floor(Math.random()*select.options.length);}
    get('hair-colour').value=['#49322c','#c08143','#171717','#dbbcc5','#7c3aed'][Math.floor(Math.random()*5)];
    drawFace();render();get('status').textContent='Meet your surprise character! Your painting has been kept.';
  });
  get('size').addEventListener('input',()=>get('size-value').value=get('size').value);
  document.querySelectorAll('[data-colour]').forEach(button=>button.addEventListener('click',()=>get('colour').value=button.dataset.colour));
  get('download').addEventListener('click',()=>{
    const image=document.createElement('canvas');image.width=600;image.height=720;
    const output=image.getContext('2d');output.fillStyle='#faf5ff';output.fillRect(0,0,600,720);output.drawImage(base,0,0);output.drawImage(canvas,0,0);
    image.toBlob(blob=>{if(!blob){get('status').textContent='Download failed. Please try again.';return;}
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='CL-Paints-my-face-design.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
      get('status').textContent='Your design is ready to save!';
    },'image/png');
  });
  const missions=[
    {name:'Create a butterfly with matching wings on both cheeks.',colours:3,tool:'brush',mirror:true},
    {name:'Turn this character into a tiger with colourful stripes.',colours:2,tool:'brush',mirror:true},
    {name:'Paint a galaxy full of bright stars.',colours:3,tool:'stars',mirror:false},
    {name:'Create a superhero mask with dotted details.',colours:2,tool:'dots',mirror:false},
    {name:'Invent a rainbow dragon with matching cheek decorations.',colours:4,tool:'stars',mirror:true}
  ];let mission=0,missionRound=0,completed=0,won=false;
  function updateMission() {
    const task=missions[mission],painted=strokes.filter(s=>s.round===missionRound && s.tool!=='eraser');
    const checks=[new Set(painted.map(s=>s.colour)).size>=task.colours,painted.some(s=>s.tool===task.tool),task.mirror ? painted.some(s=>s.mirror) : painted.length>=6];
    const labels=[`Use ${task.colours} different paint colours`,`Try ${task.tool==='brush'?'the paintbrush':task.tool==='stars'?'a star stamp':'a dot stamp'}`,task.mirror?'Try painting with mirror mode':'Add at least six paint strokes or stamps'];
    get('tasks').replaceChildren(...labels.map((label,i)=>{const item=document.createElement('li');item.textContent=(checks[i]?'✓ ':'○ ')+label;if(checks[i])item.className='paint-task-done';return item;}));
    const count=checks.filter(Boolean).length;get('progress').value=count;
    get('achievements').textContent=count===3?'★★★ Mission complete! Download your creation or try the next mission.':`${'★'.repeat(count)}${'☆'.repeat(3-count)} ${count} of 3 creative tasks complete`;
    if(count===3 && !won){won=true;completed++;const panel=document.querySelector('.paint-game');panel.classList.remove('paint-celebrate');void panel.offsetWidth;panel.classList.add('paint-celebrate');}
    get('game-score').textContent=`${completed} mission${completed===1?'':'s'} completed this session`;
  }
  get('new-challenge').addEventListener('click',()=>{mission=(mission+1)%missions.length;missionRound++;won=false;get('challenge').textContent=missions[mission].name;updateMission();});
  drawFace();render();
})();
