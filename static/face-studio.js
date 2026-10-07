(() => {
  const get = id => document.getElementById(`paint-${id}`);
  const canvas = get('canvas'), base = get('base');
  if (!canvas) return;
  const featureControls=document.querySelector('.paint-controls');
  let keyboardControls=false,mouseControls=false;
  document.addEventListener('keydown',()=>{keyboardControls=true;});
  document.addEventListener('pointerdown',event=>{keyboardControls=false;mouseControls=event.pointerType==='mouse';},true);
  featureControls?.addEventListener('pointerover',event=>{mouseControls=event.pointerType==='mouse';});
  function closeUnusedFeatures(){
    if(!featureControls||!mouseControls)return;
    featureControls.querySelectorAll(':scope > details[open]').forEach(group=>{
      if(group.matches(':hover')||(keyboardControls&&group.contains(document.activeElement)))return;
      // Native colour/select popups can temporarily move the pointer outside.
      const focused=document.activeElement;
      if(group.contains(focused)&&(focused.matches('select,input[type="color"]'))&&document.hasFocus())return;
      group.open=false;
      group.querySelectorAll('details[open]').forEach(nested=>{nested.open=false;});
    });
  }
  featureControls?.addEventListener('pointerout',event=>{
    if(event.pointerType!=='mouse'||event.buttons)return;
    const group=event.target.closest('.paint-option-group');
    if(!group||group.contains(event.relatedTarget))return;
    window.setTimeout(closeUnusedFeatures,120);
  });
  featureControls?.addEventListener('focusout',()=>window.setTimeout(closeUnusedFeatures,0));
  featureControls?.addEventListener('change',()=>{
    // Once a native picker closes, allow its panel to collapse on mouse exit.
    if(mouseControls&&!keyboardControls&&document.activeElement?.matches('select,input[type="color"]'))document.activeElement.blur();
    closeUnusedFeatures();
  });
  let ctx = canvas.getContext('2d');const bg = base.getContext('2d');
  const strokes = []; let redo = [], active = null;
  const cakes={custom:['#f52f83','#9333ea','#0ea5e9','#ffffff'],rainbow:['#ef4444','#f97316','#facc15','#22c55e','#2563eb','#9333ea'],sunset:['#fff7ad','#fbbf24','#f97316','#db2777'],ocean:['#ffffff','#67e8f9','#0ea5e9','#1e3a8a'],forest:['#fef08a','#a3e635','#16a34a','#14532d'],berry:['#ffffff','#f9a8d4','#ec4899','#7e22ce']};
  let deadline=null,timedFinished=false;
  let blinking=false,gazeX=0,gazeY=0,animationFrame=null;
  let paintFrame=null,faceVersion=0,referenceSignature='';
  function face() {
    if(window.CLPortraits?.active())return window.CLPortraits.face();
    const shape = get('face').value;
    return {x:300,y:335,rx:(shape === 'round' ? 190 : 165)*(.8+Number(get('width').value)*.004)*(1+(Number(get('cheeks')?.value||50)-50)*.002),ry:(shape === 'long' ? 260 : shape === 'round' ? 215 : 245)*(.8+Number(get('height').value)*.004)};
  }
  function ellipse(context, f) {
    const x=f.x,y=f.y,r=f.rx,h=f.ry;
    context.beginPath();context.moveTo(x,y-h);
    context.bezierCurveTo(x+r*.82,y-h,x+r*1.04,y-h*.52,x+r*.96,y-h*.04);
    context.bezierCurveTo(x+r*1.01,y+h*.28,x+r*.83,y+h*.62,x+r*.43,y+h*.84);
    context.bezierCurveTo(x+r*.21,y+h*.98,x-r*.21,y+h*.98,x-r*.43,y+h*.84);
    context.bezierCurveTo(x-r*.83,y+h*.62,x-r*1.01,y+h*.28,x-r*.96,y-h*.04);
    context.bezierCurveTo(x-r*1.04,y-h*.52,x-r*.82,y-h,x,y-h);context.closePath();
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
    faceVersion++;
    if(window.CLPortraits?.draw(base))return;
    const f=face(),skin=window.CLCharacterColours?.skin||get('skin').value,hair=get('hair').value,colour=get('hair-colour').value;
    const top=f.y-f.ry;
    bg.clearRect(0,0,600,720);
    // Back hair sits behind the ears and face, rather than across the cheeks.
    bg.fillStyle=tint(colour,-20);
    if(hair==='long'||hair==='wavy') {
      bg.beginPath();bg.moveTo(300-f.rx-22,250);bg.bezierCurveTo(300-f.rx-35,70,300+f.rx+35,70,300+f.rx+22,250);
      bg.lineTo(300+f.rx+38,660);bg.quadraticCurveTo(300,710,300-f.rx-38,660);bg.closePath();bg.fill();
      bg.save();bg.strokeStyle=tint(colour,32);bg.globalAlpha=.32;bg.lineWidth=1.4;
      for(const side of [-1,1])for(let i=0;i<24;i++){const x=300+side*(f.rx-12+i*2);bg.beginPath();bg.moveTo(x,215);if(hair==='wavy')bg.bezierCurveTo(x+side*38,350,x-side*25,470,x+side*22,660);else bg.bezierCurveTo(x+side*18,370,x+side*18,530,x+side*22,665);bg.stroke();}
      bg.restore();
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
    bg.fillStyle='rgba(92,57,40,.045)';
    for(let i=0;i<2600;i++){const x=130+(i*37.71)%340,y=160+(i*23.17)%430;bg.fillRect(x,y,.65,.65);}

    // Facial planes add depth around the temples, nose and jaw.
    for(const side of [-1,1]) {
      const shadow=bg.createRadialGradient(300+side*f.rx*.8,375,6,300+side*f.rx*.8,375,110);
      shadow.addColorStop(0,'rgba(84,47,33,.13)');shadow.addColorStop(1,'rgba(84,47,33,0)');
      bg.fillStyle=shadow;bg.fillRect(300+side*f.rx*.8-110,265,220,220);
    }
    const noseLight=bg.createLinearGradient(270,0,328,0);
    noseLight.addColorStop(0,'rgba(80,45,30,0)');noseLight.addColorStop(.25,'rgba(80,45,30,.1)');noseLight.addColorStop(.5,'rgba(255,255,255,.2)');noseLight.addColorStop(.8,'rgba(80,45,30,.09)');noseLight.addColorStop(1,'rgba(80,45,30,0)');
    bg.fillStyle=noseLight;bg.beginPath();bg.moveTo(286,318);bg.lineTo(275,386);bg.quadraticCurveTo(300,408,325,386);bg.lineTo(312,318);bg.closePath();bg.fill();
    for(const x of [212,388]) {
      const cheek=bg.createRadialGradient(x,383,2,x,383,56);cheek.addColorStop(0,'rgba(182,75,76,.14)');cheek.addColorStop(1,'rgba(182,75,76,0)');
      bg.fillStyle=cheek;bg.fillRect(x-56,327,112,112);
    }
    bg.restore();
    bg.lineCap='round';
    for(const x of [235,365]) {
      const socket=bg.createRadialGradient(x,301,10,x,301,48);socket.addColorStop(0,'rgba(80,45,30,.14)');socket.addColorStop(1,'rgba(80,45,30,0)');bg.fillStyle=socket;bg.fillRect(x-48,260,96,83);
      bg.strokeStyle=tint(skin,-85);bg.lineWidth=2;
      if(blinking || ['closed','sleepy'].includes(get('expression').value) || (get('expression').value==='wink' && x===365)){bg.beginPath();bg.moveTo(x-32,310);bg.quadraticCurveTo(x,321,x+32,310);bg.stroke();}
      else {
        bg.beginPath();bg.moveTo(x-33,306);bg.quadraticCurveTo(x,284,x+33,306);bg.quadraticCurveTo(x,321,x-33,306);bg.fillStyle='#f5f1ed';bg.fill();bg.stroke();
        bg.save();bg.clip();bg.beginPath();bg.arc(x+gazeX,305+gazeY,11,0,Math.PI*2);bg.fillStyle=window.CLCharacterColours?.['eye-colour']||get('eye-colour').value;bg.fill();
        bg.strokeStyle='#344538';bg.lineWidth=.7;
        for(let i=0;i<24;i++){const a=i*Math.PI/12;bg.beginPath();bg.moveTo(x+gazeX+Math.cos(a)*5,305+gazeY+Math.sin(a)*5);bg.lineTo(x+gazeX+Math.cos(a)*10,305+gazeY+Math.sin(a)*10);bg.stroke();}

        bg.beginPath();bg.arc(x+gazeX,305+gazeY,5,0,Math.PI*2);bg.fillStyle='#202020';bg.fill();
        bg.beginPath();bg.arc(x+gazeX-3,301+gazeY,2.5,0,Math.PI*2);bg.fillStyle='#fff';bg.fill();
        bg.restore();
        bg.strokeStyle=tint(skin,-42);bg.lineWidth=1;bg.beginPath();bg.moveTo(x-30,293);bg.quadraticCurveTo(x,276,x+30,294);bg.stroke();
      }
      bg.save();bg.translate(x,276);bg.rotate((Number(get('brow-angle')?.value||50)-50)*Math.PI/600);bg.translate(-x,-276);bg.strokeStyle=colour;const brows=get('brows').value;bg.lineWidth=brows==='soft'?2:brows==='full'?7:4;bg.beginPath();bg.moveTo(x-32,276);bg.quadraticCurveTo(x,brows==='arched'?255:brows==='straight'?276:265,x+29,275);bg.stroke();bg.restore();
    }
    if(get('freckles').value!=='none'){bg.save();ellipse(bg,f);bg.clip();bg.fillStyle=tint(skin,-55);bg.globalAlpha=.5;const count=get('freckles').value==='many'?55:22;for(let i=0;i<count;i++){const side=i%2?1:-1,x=300+side*(30+(i*31)%104),y=357+(i*17)%40;bg.beginPath();bg.arc(x,y,1+(i%3)*.4,0,Math.PI*2);bg.fill();}bg.restore();}
    bg.save();bg.translate(300,0);bg.scale(.7+Number(get('nose-width')?.value||50)*.006,1);bg.translate(-300,0);
    // Soft nose contours and highlights instead of a triangular outline.
    bg.strokeStyle=tint(skin,-45);bg.lineWidth=2;
    for(const side of [-1,1]){bg.beginPath();bg.moveTo(300+side*12,326);bg.bezierCurveTo(300+side*9,350,300+side*23,375,300+side*16,383);bg.stroke();}
    bg.beginPath();bg.moveTo(281,386);bg.quadraticCurveTo(300,396,319,386);bg.stroke();
    bg.fillStyle=tint(skin,-70);for(const x of [288,312]){bg.beginPath();bg.ellipse(x,386,5,2,0,0,Math.PI*2);bg.fill();}
    bg.restore();bg.save();bg.translate(300,435);bg.scale(.7+Number(get('lip-width')?.value||50)*.006,.7+Number(get('lip-fullness')?.value||50)*.006);bg.translate(-300,-435);
    const lips=bg.createLinearGradient(0,423,0,451);lips.addColorStop(0,tint(skin,-45));lips.addColorStop(.6,tint(skin,-25));lips.addColorStop(1,tint(skin,-15));bg.fillStyle=get('lips').value==='natural'&&!window.CLCharacterColours?.lips?lips:(window.CLCharacterColours?.lips||get('lips').value);
    bg.beginPath();
    if(get('expression').value==='surprise') {bg.ellipse(300,446,19,27,0,0,Math.PI*2);bg.fillStyle=tint(skin,-95);bg.fill();}
    else if(get('expression').value==='grin'){bg.moveTo(255,433);bg.quadraticCurveTo(300,450,345,433);bg.quadraticCurveTo(300,478,255,433);bg.fillStyle=tint(skin,-95);bg.fill();bg.fillStyle='#fffaf0';bg.beginPath();bg.moveTo(263,436);bg.quadraticCurveTo(300,449,337,436);bg.lineTo(333,447);bg.quadraticCurveTo(300,458,267,447);bg.closePath();bg.fill();}
    else {bg.moveTo(254,435);bg.quadraticCurveTo(280,417,300,429);bg.quadraticCurveTo(320,417,346,435);bg.quadraticCurveTo(300,460,254,435);bg.fill();bg.strokeStyle=tint(skin,-70);bg.lineWidth=1.5;bg.beginPath();bg.moveTo(254,435);bg.quadraticCurveTo(300,get('expression').value==='sad'?420:get('expression').value==='neutral'?435:442,346,435);bg.stroke();}
    bg.restore();
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
    if(stroke.tool==='hearts') {
      const r=stroke.size;ctx.moveTo(x,y+r*.6);ctx.bezierCurveTo(x-r*1.3,y-r*.2,x-r*.5,y-r,x,y-r*.3);ctx.bezierCurveTo(x+r*.5,y-r,x+r*1.3,y-r*.2,x,y+r*.6);
    } else if(stroke.tool==='flowers') {
      for(let i=0;i<5;i++){const a=i*Math.PI*2/5;ctx.moveTo(x+Math.cos(a)*stroke.size,y+Math.sin(a)*stroke.size);ctx.ellipse(x+Math.cos(a)*stroke.size*.55,y+Math.sin(a)*stroke.size*.55,stroke.size*.35,stroke.size*.55,a-Math.PI/2,0,Math.PI*2);}
    } else if(stroke.tool==='stars') {
      for(let i=0;i<10;i++) {
        const a=-Math.PI/2+i*Math.PI/5,r=stroke.size*(i%2 ? .45 : 1);
        const px=x+Math.cos(a)*r,py=y+Math.sin(a)*r;
        if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
      }
      ctx.closePath();
    } else ctx.arc(x,y,stroke.size/2,0,Math.PI*2);
    ctx.fill();
  }
  function mirrorPoint(p,stroke){const x=stroke.mirrorAxis??300,y=stroke.mirrorAxisY??360,a=(stroke.mirrorAngle||0)*Math.PI/180,dx=p.x-x,dy=p.y-y,ux=Math.sin(a),uy=Math.cos(a),dot=dx*ux+dy*uy;return {x:x+2*dot*ux-dx,y:y+2*dot*uy-dy};}
  function draw(stroke,mirror=false) {
    if(stroke.hidden)return;
    ctx.save();if(window.CLPortraits?.active())window.CLPortraits.path(ctx);else ellipse(ctx,face());ctx.clip();
    ctx.globalCompositeOperation=stroke.tool==='eraser' ? 'destination-out' : 'source-over';
    ctx.strokeStyle=stroke.colour;ctx.fillStyle=stroke.colour;ctx.lineWidth=stroke.size;ctx.lineCap='round';ctx.lineJoin='round';
    ctx.globalAlpha=(stroke.opacity || 100)/100;
    let points=stroke.points;
    if(mirror){
      const x=stroke.mirrorAxis??300,y=stroke.mirrorAxisY??360,a=(stroke.mirrorAngle||0)*Math.PI/180;
      const ux=Math.sin(a),uy=Math.cos(a);
      points=stroke.points.map(p=>{const dx=p.x-x,dy=p.y-y,dot=dx*ux+dy*uy;return {x:x+2*dot*ux-dx,y:y+2*dot*uy-dy};});
    }
    if(mirror&&stroke.mirrorScope&&stroke.mirrorScope!=='whole'){ctx.beginPath();ctx.rect(0,stroke.mirrorScope==='lower'?350:0,600,stroke.mirrorScope==='lower'?370:350);ctx.clip();}
    if(stroke.tool==='blend'){for(const p of points){ctx.save();ctx.beginPath();ctx.arc(p.x,p.y,stroke.size,0,Math.PI*2);ctx.clip();ctx.filter='blur(3px)';ctx.globalAlpha=.35;ctx.drawImage(ctx.canvas,0,0);ctx.restore();}ctx.restore();return;}
    if(stroke.finish==='metallic'||stroke.finish==='pearl'){const g=ctx.createLinearGradient(0,Math.min(...points.map(p=>p.y))-stroke.size,0,Math.max(...points.map(p=>p.y))+stroke.size);g.addColorStop(0,stroke.colour);g.addColorStop(.45,stroke.finish==='pearl'?'#fdf4ff':'#fff8dc');g.addColorStop(.6,stroke.colour);g.addColorStop(1,stroke.colour);ctx.strokeStyle=g;ctx.fillStyle=g;}
    if(['stars','dots','hearts','flowers'].includes(stroke.tool))points.forEach(p=>stamp(p.x,p.y,stroke));
    else if(stroke.tool==='glitter'||stroke.tool==='sponge'||stroke.tool==='soft') {
      const samples=[];
      points.forEach((p,i)=>{const last=points[Math.max(0,i-1)],steps=Math.max(1,Math.ceil(Math.hypot(p.x-last.x,p.y-last.y)/Math.max(2,stroke.size/5)));for(let j=1;j<=steps;j++)samples.push({x:last.x+(p.x-last.x)*j/steps,y:last.y+(p.y-last.y)*j/steps});});
      for(const p of samples) {
        if(stroke.tool==='soft'){const gradient=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,stroke.size/2);gradient.addColorStop(0,stroke.colour+'50');gradient.addColorStop(1,stroke.colour+'00');ctx.fillStyle=gradient;ctx.fillRect(p.x-stroke.size/2,p.y-stroke.size/2,stroke.size,stroke.size);}
        else for(let i=0;i<12;i++){const angle=i*2.399+ p.x*.02,r=(i%5+1)*stroke.size/12;ctx.fillStyle=stroke.tool==='glitter'&&i%3===0?'#ffffff':stroke.colour;ctx.beginPath();ctx.arc(p.x+Math.cos(angle)*r,p.y+Math.sin(angle)*r,stroke.tool==='glitter'?1.2:stroke.size/12,0,Math.PI*2);ctx.fill();}
      }
    }
    else if(stroke.cake && stroke.tool!=='eraser') {
      const colours=stroke.cakeColours||cakes[stroke.cake],style=stroke.cakeBrush||'round';
      // Sample one smooth centreline, then stroke each continuous offset band.
      // This avoids restarting the ribbon at every pointer event.
      const ribbon=[points[0]];
      function curve(start,control,end){const length=Math.hypot(control.x-start.x,control.y-start.y)+Math.hypot(end.x-control.x,end.y-control.y),steps=Math.max(1,Math.ceil(length/2));for(let j=1;j<=steps;j++){const t=j/steps,u=1-t;ribbon.push({x:u*u*start.x+2*u*t*control.x+t*t*end.x,y:u*u*start.y+2*u*t*control.y+t*t*end.y});}}
      let start=points[0];
      for(let i=1;i<points.length-1;i++){const end={x:(points[i].x+points[i+1].x)/2,y:(points[i].y+points[i+1].y)/2};curve(start,points[i],end);start=end;}
      if(points.length>1)curve(start,points[points.length-1],points[points.length-1]);
      const normals=ribbon.map((p,i)=>{const before=ribbon[Math.max(0,i-2)],after=ribbon[Math.min(ribbon.length-1,i+2)],dx=after.x-before.x,dy=after.y-before.y,length=Math.hypot(dx,dy);return length>.001?{x:-dy/length,y:dx/length}:{x:1,y:0};});
      if(style==='angled')for(const n of normals){const x=n.x,y=n.y;n.x=(x-y)*Math.SQRT1_2;n.y=(x+y)*Math.SQRT1_2;}
      if(ribbon.length===1){const p=ribbon[0];ctx.save();ctx.translate(p.x,p.y);if(style==='angled')ctx.rotate(Math.PI/4);if(style==='round'||style==='petal'){ctx.beginPath();ctx.ellipse(0,0,stroke.size/2,stroke.size*.3,0,0,Math.PI*2);ctx.clip();}colours.forEach((colour,band)=>{ctx.fillStyle=colour;ctx.fillRect(-stroke.size/2+band*stroke.size/colours.length,-stroke.size*(style==='round'||style==='petal'?.3:.1),stroke.size/colours.length+.35,stroke.size*(style==='round'||style==='petal'?.6:.2));});ctx.restore();}
      else colours.forEach((colour,band)=>{
        const width=stroke.size/colours.length,offset=(band-(colours.length-1)/2)*width;
        ctx.strokeStyle=colour;ctx.fillStyle=colour;ctx.lineWidth=width+.35;ctx.lineCap=style==='flat'||style==='angled'?'butt':'round';ctx.lineJoin='round';ctx.beginPath();
        if(style==='petal'){
          const edge=(i,side)=>{const p=ribbon[i],n=normals[i],t=i/(ribbon.length-1),taper=.05+.95*Math.pow(Math.sin(Math.PI*t),.7),distance=(offset+side*width/2)*taper;return {x:p.x+n.x*distance,y:p.y+n.y*distance};};
          for(let i=0;i<ribbon.length;i++){const p=edge(i,-1);if(i===0)ctx.moveTo(p.x,p.y);else ctx.lineTo(p.x,p.y);}
          for(let i=ribbon.length-1;i>=0;i--){const p=edge(i,1);ctx.lineTo(p.x,p.y);}ctx.closePath();ctx.fill();return;
        }
        ribbon.forEach((p,i)=>{const x=p.x+normals[i].x*offset,y=p.y+normals[i].y*offset;if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
        if(ribbon.length===1){const p=ribbon[0],n=normals[0];ctx.fillRect(p.x+n.x*offset-width/2,p.y-2,width,4);}else ctx.stroke();
      });
    }
    else if(stroke.tool==='flat') {
      for(const p of points)ctx.fillRect(p.x-stroke.size/2,p.y-stroke.size/6,stroke.size,stroke.size/3);
    }
    else if(points.length===1)stamp(points[0].x,points[0].y,stroke);
    else {ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);if(stroke.smoothing){for(let i=1;i<points.length-1;i++)ctx.quadraticCurveTo(points[i].x,points[i].y,(points[i].x+points[i+1].x)/2,(points[i].y+points[i+1].y)/2);ctx.lineTo(points[points.length-1].x,points[points.length-1].y);}else points.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();}
    if(stroke.finish==='glitter'&&stroke.tool!=='eraser'){ctx.fillStyle='#fff';for(const p of points){ctx.fillRect(p.x-2,p.y-2,2,2);ctx.fillRect(p.x+3,p.y+2,1,1);}}
    ctx.restore();
  }
  function render(reuseLayers=false) {
    if(paintFrame!==null){cancelAnimationFrame(paintFrame);paintFrame=null;}
    ctx.clearRect(0,0,600,720);
    if(window.CLStudioEdits)window.CLStudioEdits.render(draw,strokes,value=>ctx=value,canvas,active,reuseLayers);else for(const stroke of strokes.concat(active ? [active] : [])){draw(stroke);if(stroke.mirror)draw(stroke,true);}
    if(!active){
      if(window.CLStudioEdits)window.CLStudioEdits.refresh();else{get('undo').disabled=!strokes.length;get('redo').disabled=!redo.length;}
      updateMission();
    }
    updateReference();
  }
  function schedulePaint(){
    if(paintFrame!==null)return;
    paintFrame=requestAnimationFrame(()=>{paintFrame=null;render(true);});
  }
  // Screen-space preview only: never included in painting or downloads.
  const brushCursor=document.createElement('div');brushCursor.className='paint-brush-cursor';brushCursor.hidden=true;brushCursor.setAttribute('aria-hidden','true');
  brushCursor.innerHTML='<span class="paint-cursor-ring"></span><svg class="paint-cursor-brush" viewBox="0 0 40 48" width="32" height="38"><path d="M8 38 L27 5 Q30 1 33 4 Q36 6 33 10 L14 42 Z" fill="#825137" stroke="#fff" stroke-width="2"/><path d="M8 33 L18 39 L14 45 L4 40 Z" fill="#cbd5e1" stroke="#334155"/><path d="M4 39 Q0 43 0 48 Q9 48 14 44 L8 40 Z" fill="currentColor" stroke="#fff"/></svg>';
  document.body.append(brushCursor);let cursorPosition=null;
  function updateBrushCursor(){
    if(!cursorPosition)return;const rect=canvas.getBoundingClientRect(),scale=rect.width/600,tool=get('tool').value,size=Number(get('size').value);
    const diameter=size*scale*(['stars','hearts','flowers','dots'].includes(tool)?2:1);
    brushCursor.style.left=cursorPosition.x+'px';brushCursor.style.top=cursorPosition.y+'px';brushCursor.style.setProperty('--brush-diameter',diameter+'px');brushCursor.style.color=get('colour').value;
    brushCursor.dataset.tool=tool;brushCursor.dataset.cakeBrush=get('colour-mode').value==='solid'?'':get('cake-brush').value;brushCursor.title=tool==='eraser'?'Eraser':'Brush';
  }
  canvas.addEventListener('pointermove',event=>{if(event.pointerType==='touch'){brushCursor.hidden=true;canvas.classList.remove('paint-custom-cursor');return;}cursorPosition={x:event.clientX,y:event.clientY};brushCursor.hidden=false;canvas.classList.add('paint-custom-cursor');updateBrushCursor();});
  canvas.addEventListener('pointerleave',()=>{brushCursor.hidden=true;canvas.classList.remove('paint-custom-cursor');});
  canvas.addEventListener('pointercancel',()=>brushCursor.hidden=true);
  for(const id of ['size','colour','tool','colour-mode','zoom'])get(id).addEventListener('input',updateBrushCursor);
  for(const id of ['tool','colour-mode','cake-brush'])get(id).addEventListener('change',()=>requestAnimationFrame(updateBrushCursor));
  get('viewport').addEventListener('scroll',()=>{brushCursor.hidden=true;});
  window.addEventListener('resize',updateBrushCursor);
  const animationToggle=get('animate'),reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  animationToggle.checked=!reducedMotion.matches;
  function animationEnabled(){return animationToggle.checked&&!document.hidden&&!window.CLPortraits?.active();}
  function refreshAnimation(){if(animationFrame!==null)return;animationFrame=requestAnimationFrame(()=>{animationFrame=null;drawFace();updateReference();});}
  function resetAnimation(){blinking=false;gazeX=0;gazeY=0;refreshAnimation();}
  animationToggle.addEventListener('change',resetAnimation);
  get('model').addEventListener('change',resetAnimation);
  reducedMotion.addEventListener('change',event=>{if(event.matches){animationToggle.checked=false;resetAnimation();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)resetAnimation();});
  canvas.addEventListener('pointermove',event=>{if(!animationEnabled()||event.pointerType==='touch')return;const rect=canvas.getBoundingClientRect(),x=(event.clientX-rect.left)*600/rect.width,y=(event.clientY-rect.top)*720/rect.height;gazeX=Math.max(-3,Math.min(3,(x-300)/60));gazeY=Math.max(-2,Math.min(2,(y-305)/100));refreshAnimation();});
  canvas.addEventListener('pointerleave',()=>{gazeX=0;gazeY=0;if(animationEnabled())refreshAnimation();});
  function scheduleBlink(){setTimeout(()=>{if(animationEnabled()&&!['closed','sleepy'].includes(get('expression').value)){blinking=true;refreshAnimation();setTimeout(()=>{blinking=false;refreshAnimation();},140);}scheduleBlink();},3000+Math.random()*2500);}
  scheduleBlink();
  function point(event) {const rect=canvas.getBoundingClientRect();return {x:(event.clientX-rect.left)*600/rect.width,y:(event.clientY-rect.top)*720/rect.height};}
  canvas.addEventListener('pointerdown',event=>{
    if(active || timedFinished || (event.pointerType==='mouse' && event.button!==0))return;
    if(window.CLStudioEdits?.pointerDown(event,point(event)))return;
    window.CLStudioEdits?.checkpoint();
    event.preventDefault();canvas.setPointerCapture(event.pointerId);
    active={...window.CLStudioEdits?.strokeSettings(),cakeBrush:get('cake-brush').value,cakeColours:get('colour-mode').value==='solid'?null:[...cakes[get('colour-mode').value]],round:missionRound,pointer:event.pointerId,colour:get('colour').value,cake:get('colour-mode').value==='solid'?null:get('colour-mode').value,opacity:Number(get('opacity').value),size:Number(get('size').value),tool:get('tool').value,mirror:get('mirror').checked,points:[point(event)]};render();
  });
  canvas.addEventListener('pointermove',event=>{
    if(window.CLStudioEdits?.pointerMove(event,point(event)))return;
    if(!active || active.pointer!==event.pointerId)return;
    const p=point(event),last=active.points[active.points.length-1];
    const distance=Math.hypot(p.x-last.x,p.y-last.y);
    if(distance < (['stars','dots','hearts','flowers'].includes(active.tool) ? active.size*1.5 : 2))return;
    active.points.push(p);schedulePaint();
  });
  function finish(event) {
    if(window.CLStudioEdits?.pointerUp(event))return;
    if(!active || active.pointer!==event.pointerId)return;
    const f=face();
    const mask=document.createElement('canvas').getContext('2d');if(window.CLPortraits?.active())window.CLPortraits.path(mask);else ellipse(mask,f);if(active.points.some(p=>mask.isPointInPath(p.x,p.y)))strokes.push(active);
    active=null;redo=[];render();get('status').textContent='Looking colourful! Keep creating.';
  }
  canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);canvas.addEventListener('lostpointercapture',finish);
  get('undo').addEventListener('click',()=>{if(active)return;if(window.CLStudioEdits){window.CLStudioEdits.undo();return;}const stroke=strokes.pop();if(stroke)redo.push(stroke);render();});
  get('redo').addEventListener('click',()=>{if(active)return;if(window.CLStudioEdits){window.CLStudioEdits.redo();return;}const stroke=redo.pop();if(stroke)strokes.push(stroke);render();});
  get('clear').addEventListener('click',()=>{if(strokes.length && !window.confirm('Clear your painted design?'))return;window.CLStudioEdits?.checkpoint();active=null;strokes.length=0;redo=[];render();get('status').textContent='A fresh face, ready for your next idea.';});
  for(const id of ['model','face','skin','hair','hair-colour','facial-hair','expression','eye-colour','brows','freckles','lips','height','width'])get(id).addEventListener('change',()=>{drawFace();render();});
  for(const id of ['height','width'])get(id).addEventListener('input',()=>{get(id+'-value').value=get(id).value+'%';drawFace();render();});
  get('surprise').addEventListener('click',()=>{
    get('model').value='illustrated';get('model').dispatchEvent(new Event('change'));
    for(const id of ['face','skin','hair','facial-hair','expression','eye-colour','brows','freckles','lips']){const select=get(id);select.selectedIndex=Math.floor(Math.random()*select.options.length);}
    get('hair-colour').selectedIndex=Math.floor(Math.random()*get('hair-colour').options.length);
    drawFace();render();get('status').textContent='Meet your surprise character! Your painting has been kept.';
  });
  get('size').addEventListener('input',()=>get('size-value').value=get('size').value);
  const palette=['#ffffff','#d1d5db','#6b7280','#111827','#fee2e2','#fca5a5','#ef4444','#991b1b','#ffedd5','#fdba74','#f97316','#9a3412','#fef9c3','#fde047','#eab308','#854d0e','#dcfce7','#86efac','#22c55e','#166534','#ccfbf1','#5eead4','#14b8a6','#115e59','#dbeafe','#93c5fd','#3b82f6','#1e3a8a','#ede9fe','#c4b5fd','#8b5cf6','#5b21b6','#fae8ff','#e879f9','#d946ef','#86198f','#fce7f3','#f9a8d4','#f52f83','#9d174d','#f7d7bd','#deb08b','#b77d55','#513224'];
  for(const colour of palette){const button=document.createElement('button');button.type='button';button.style.setProperty('--swatch',colour);button.setAttribute('aria-label',`Paint colour ${colour}`);button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>{get('colour').value=colour;get('colour-mode').value='solid';document.querySelectorAll('.paint-palette button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));cakePreview();});get('palette').appendChild(button);}
  function cakePreview(){const colours=cakes[get('colour-mode').value]||[get('colour').value];get('cake-preview').style.background=`linear-gradient(90deg,${colours.flatMap((c,i)=>[`${c} ${i*100/colours.length}%`,`${c} ${(i+1)*100/colours.length}%`]).join(',')})`;}
  get('colour-mode').addEventListener('change',()=>{if(get('colour-mode').value!=='solid'){get('tool').value='flat';get('size').value=40;get('size-value').value=40;}cakePreview();});get('colour').addEventListener('input',()=>{get('colour-mode').value='solid';cakePreview();});cakePreview();
  const viewport=get('viewport');let boardWidth=viewport.clientWidth;
  function zoom(center=true){
    const value=Number(get('zoom').value);
    get('board').style.width=`${boardWidth*value/100}px`;
    get('zoom-value').value=`${value}%`;
    if(center){
      // Read the resized scroll area so the centre of the face stays in view.
      viewport.scrollLeft=Math.max(0,(viewport.scrollWidth-viewport.clientWidth)/2);
      viewport.scrollTop=Math.max(0,(viewport.scrollHeight-viewport.clientHeight)/2);
    }
  }
  get('zoom').addEventListener('input',()=>zoom());get('zoom-reset').addEventListener('click',()=>{get('zoom').value=100;zoom(false);viewport.scrollTo(0,0);});
  window.addEventListener('resize',()=>{boardWidth=viewport.clientWidth;zoom();});zoom(false);
  const photoEffect=document.createElement('div');
  photoEffect.className='paint-photo-effect';photoEffect.hidden=true;
  photoEffect.setAttribute('aria-hidden','true');
  photoEffect.innerHTML='<div class="paint-photo-frame"><span class="paint-photo-camera">&#128247;</span><span class="paint-photo-caption">Picture taken!</span></div>';
  document.body.appendChild(photoEffect);
  let photoTimer;
  function showPhotoEffect(){
    clearTimeout(photoTimer);photoEffect.hidden=false;
    photoEffect.classList.remove('paint-photo-active');void photoEffect.offsetWidth;
    photoEffect.classList.add('paint-photo-active');
    photoTimer=setTimeout(()=>{photoEffect.hidden=true;photoEffect.classList.remove('paint-photo-active');},1600);
  }
  get('download').addEventListener('click',()=>{
    const image=document.createElement('canvas');image.width=600;image.height=720;
    const output=image.getContext('2d');output.fillStyle='#faf5ff';output.fillRect(0,0,600,720);output.drawImage(base,0,0);output.drawImage(canvas,0,0);
    const photo=window.CLStudioBooth?window.CLStudioBooth.compose(image):image;
    photo.toBlob(blob=>{if(!blob){get('status').textContent='Download failed. Please try again.';return;}
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='CL-Paints-my-face-design.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
      showPhotoEffect();
      get('status').textContent='Picture taken! Your design is ready to save.';
    },'image/png');
  });
  const missions=[
    {name:'Create a butterfly with matching wings on both cheeks.',colours:3,tool:'brush',mirror:true},
    {name:'Turn this character into a tiger with colourful stripes.',colours:2,tool:'brush',mirror:true},
    {name:'Paint a galaxy full of bright stars.',colours:3,tool:'stars',mirror:false},
    {name:'Create a superhero mask with dotted details.',colours:2,tool:'dots',mirror:false},
    {name:'Invent a rainbow dragon with matching cheek decorations.',colours:4,tool:'stars',mirror:true}
  ];let mission=0,missionRound=0,completed=0,won=false;
  const customers=[
    {name:'Poppy',request:'Please paint a purple butterfly with pink wings and glitter!',colours:['#8b5cf6','#f52f83'],tool:'glitter',mirror:true,design:'butterfly'},
    {name:'Leo',request:'I would love an orange tiger with black stripes on both cheeks.',colours:['#f97316','#111827'],tool:'brush',mirror:true,design:'tiger'},
    {name:'Sky',request:'Can I have a blue and purple galaxy with star stamps?',colours:['#3b82f6','#8b5cf6'],tool:'stars',mirror:false,design:'galaxy'}
  ];
  function designPattern(context,customer) {
    context.save();if(window.CLPortraits?.active())window.CLPortraits.path(context);else ellipse(context,face());context.clip();context.lineWidth=6;context.lineJoin='round';
    if(customer.design==='butterfly') {
      for(const side of [-1,1]){context.fillStyle=customer.colours[0];context.beginPath();context.moveTo(300,335);context.bezierCurveTo(300+side*55,215,300+side*160,240,300+side*145,335);context.quadraticCurveTo(300+side*170,430,300+side*50,430);context.closePath();context.fill();context.strokeStyle=customer.colours[1];context.stroke();context.fillStyle=customer.colours[1];for(let i=0;i<4;i++){context.beginPath();context.arc(300+side*(70+i*17),310+i*18,7,0,Math.PI*2);context.fill();}}
      context.strokeStyle='#111827';context.beginPath();context.moveTo(300,285);context.lineTo(300,420);context.stroke();
    } else if(customer.design==='tiger') {
      context.fillStyle=customer.colours[0];for(const side of [-1,1]){context.beginPath();context.ellipse(300+side*90,365,65,80,side*.15,0,Math.PI*2);context.fill();context.strokeStyle=customer.colours[1];for(let i=0;i<4;i++){context.beginPath();context.moveTo(300+side*145,325+i*30);context.lineTo(300+side*75,340+i*23);context.stroke();}}
      context.fillStyle=customer.colours[1];context.beginPath();context.moveTo(280,383);context.lineTo(320,383);context.lineTo(300,402);context.closePath();context.fill();
    } else {
      const gradient=context.createLinearGradient(150,250,450,450);gradient.addColorStop(0,customer.colours[0]);gradient.addColorStop(1,customer.colours[1]);context.fillStyle=gradient;context.fillRect(145,265,310,155);context.fillStyle='#ffffff';
      for(let i=0;i<10;i++){const x=180+(i*73)%250,y=290+(i*47)%100;context.beginPath();for(let j=0;j<10;j++){const a=-Math.PI/2+j*Math.PI/5,r=j%2?4:10;if(j===0)context.moveTo(x+Math.cos(a)*r,y+Math.sin(a)*r);else context.lineTo(x+Math.cos(a)*r,y+Math.sin(a)*r);}context.closePath();context.fill();}
    }
    context.restore();
  }
  function updateReference() {
    const mode=get('game-mode').value,customer=customers[mission%customers.length];
    const signature=`${mode}:${mission}:${mode==='follow'?faceVersion:0}:${get('show-guide').checked}`;
    if(signature===referenceSignature)return;
    referenceSignature=signature;
    get('customer-card').hidden=mode!=='customer';get('reference-panel').hidden=mode!=='follow';
    get('customer-name').textContent=`Meet ${customer.name}`;get('customer-request').textContent=customer.request;
    const guide=get('guide').getContext('2d');guide.clearRect(0,0,600,720);
    if(mode==='follow') {const reference=get('reference').getContext('2d');reference.clearRect(0,0,600,720);reference.drawImage(base,0,0);designPattern(reference,customer);if(get('show-guide').checked){guide.globalAlpha=.25;designPattern(guide,customer);guide.globalAlpha=1;}}
  }
  function loadGamePrompt() {
    const mode=get('game-mode').value,customer=customers[mission%customers.length];
    get('challenge').textContent=mode==='customer'?customer.request:mode==='follow'?`Recreate ${customer.design} colours and details using the reference.`:missions[mission].name;
    get('new-challenge').textContent=mode==='customer'?'Next customer':mode==='follow'?'Next design':'Next mission';
    updateMission();updateReference();
  }
  const missionPicker=document.createElement('select');missionPicker.id='paint-mission-picker';
  const pickerLabel=document.createElement('label');pickerLabel.htmlFor=missionPicker.id;pickerLabel.textContent='Choose an unlocked mission';pickerLabel.append(missionPicker);
  get('new-challenge').before(pickerLabel);
  const unlockHint=document.createElement('p');unlockHint.id='paint-unlock-hint';get('new-challenge').after(unlockHint);
  const sessionCleared=new Set();
  const challengeLimit=mode=>['customer','follow'].includes(mode)?customers.length:missions.length;
  const isCompleted=(mode,index)=>sessionCleared.has(`${mode}:${index}`)||Boolean(window.CLStudioProgress?.isCompleted(mode,index));
  const isUnlocked=(mode,index)=>isCompleted(mode,index)||Array.from({length:index},(_,previous)=>previous).every(previous=>isCompleted(mode,previous));
  let navigationState='';
  function updateMissionNavigation(){
    const mode=get('game-mode').value,limit=challengeLimit(mode);
    const state=`${mode}:${mission}:`+Array.from({length:limit},(_,index)=>isCompleted(mode,index)?'1':'0').join('');
    if(state===navigationState){missionPicker.value=String(mission);return;}
    navigationState=state;
    missionPicker.replaceChildren(...Array.from({length:limit},(_,index)=>{
      const title=['customer','follow'].includes(mode)?customers[index].name:['Butterfly','Tiger','Galaxy','Superhero','Rainbow dragon'][index];
      const option=new Option(`${index+1}. ${title} — ${isCompleted(mode,index)?'Completed':isUnlocked(mode,index)?'Unlocked':'Locked'}`,String(index));
      option.disabled=!isUnlocked(mode,index);return option;
    }));
    missionPicker.value=String(mission);missionPicker.disabled=mode==='free';
    get('new-challenge').disabled=mode==='free'||mission+1>=limit||!isUnlocked(mode,mission+1);
    unlockHint.textContent=mode==='free'?'Choose a challenge mode to progress through missions.':
      mission+1>=limit&&isCompleted(mode,mission)?'All missions in this mode are complete. Replay any unlocked mission!':
      isCompleted(mode,mission)?'Pick any unlocked mission, or continue to the next one.':'Complete all three tasks to unlock the next mission. You can revisit unlocked missions at any time.';
  }
  function chooseMission(index){
    const mode=get('game-mode').value;
    if(active||mode==='free'||!Number.isInteger(index)||index<0||index>=challengeLimit(mode)||!isUnlocked(mode,index)){
      updateMissionNavigation();return;
    }
    mission=index;missionRound++;won=false;
    if(mode==='timed'){deadline=null;timedFinished=false;get('timer').textContent='Start a timed round for this mission when you are ready.';}
    loadGamePrompt();
  }
  function updateMission() {
    const task=missions[mission],painted=strokes.filter(s=>s.round===missionRound && s.tool!=='eraser');
    const used=new Set(painted.flatMap(s=>s.cake?(s.cakeColours||cakes[s.cake]):[s.colour]));
    const requestMode=['customer','follow'].includes(get('game-mode').value),customer=customers[mission%customers.length];
    const tool=requestMode?customer.tool:task.tool,mirror=requestMode?customer.mirror:task.mirror;
    const checks=[requestMode?customer.colours.every(c=>used.has(c)):used.size>=task.colours,painted.some(s=>s.tool===tool),mirror ? painted.some(s=>s.mirror) : painted.length>=6];
    const labels=[requestMode?'Use both requested colours (Load requested colours helps)':`Use ${task.colours} different paint colours`,`Try the ${tool==='brush'?'paintbrush':tool==='glitter'?'glitter brush':tool==='stars'?'star stamp':'dot stamp'}`,mirror?'Try painting with mirror mode':'Add at least six paint strokes or stamps'];
    get('tasks').replaceChildren(...labels.map((label,i)=>{const item=document.createElement('li');item.textContent=(checks[i]?'\u2713 ':'\u25cb ')+label;if(checks[i])item.className='paint-task-done';return item;}));
    const count=checks.filter(Boolean).length;get('progress').value=count;
    get('achievements').textContent=count===3?'\u2605\u2605\u2605 Mission complete! Download your creation or try the next mission.':`${'\u2605'.repeat(count)}${'\u2606'.repeat(3-count)} ${count} of 3 creative tasks complete`;
    const mode=get('game-mode').value;
    const canEarn=mode!=='free' && (mode!=='timed' || (deadline && Date.now()<deadline && !timedFinished));
    if(count===3 && !won && canEarn && isUnlocked(mode,mission)){won=true;completed++;sessionCleared.add(`${mode}:${mission}`);window.CLStudioProgress?.complete(mode,mission);const panel=document.querySelector('.paint-game');panel.classList.remove('paint-celebrate');void panel.offsetWidth;panel.classList.add('paint-celebrate');}
    get('game-score').textContent=`${completed} mission${completed===1?'':'s'} completed this session`;
    updateMissionNavigation();
  }
  get('new-challenge').addEventListener('click',()=>chooseMission(mission+1));
  missionPicker.addEventListener('change',()=>chooseMission(Number(missionPicker.value)));
  get('game-mode').addEventListener('change',()=>{deadline=null;timedFinished=false;mission=0;missionRound++;won=false;get('tasks').hidden=get('game-mode').value==='free';get('progress').hidden=get('game-mode').value==='free';get('timer').textContent=get('game-mode').value==='free'?'Free play: take your time and enjoy creating.':'Start a timed round when you are ready.';loadGamePrompt();});
  get('show-guide').addEventListener('change',updateReference);
  get('request-colours').addEventListener('click',()=>{const c=customers[mission%customers.length];get('colour-mode').value='solid';get('colour').value=c.colours[0];cakePreview();get('status').textContent='First requested colour loaded. Use the two highlighted palette colours.';document.querySelectorAll('.paint-palette button').forEach(button=>button.setAttribute('aria-pressed',String(c.colours.includes(button.getAttribute('aria-label').replace('Paint colour ','')))));});
  get('start-timer').addEventListener('click',()=>{if(active)return;if(get('game-mode').value!=='timed')mission=0;get('game-mode').value='timed';get('tasks').hidden=false;get('progress').hidden=false;deadline=Date.now()+120000;timedFinished=false;missionRound++;won=false;loadGamePrompt();});
  setInterval(()=>{if(!deadline)return;const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));get('timer').textContent=`Time left: ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;if(!seconds){deadline=null;timedFinished=true;if(active)finish({pointerId:active.pointer});get('timer').textContent='Round complete! Download your design, start again or switch to free play.';}},250);
  window.CLStudioCore={strokes,render,scheduleRender:schedulePaint,drawFace,cakes,canvas,base,point,mirrorPoint,
    renderPreview(target,previewStrokes){const previous=ctx;try{ctx=target.getContext('2d');ctx.clearRect(0,0,600,720);for(const stroke of previewStrokes){draw(stroke);if(stroke.mirror)draw(stroke,true);}}finally{ctx=previous;}}
  };
  drawFace();render();
})();
