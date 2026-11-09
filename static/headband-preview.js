(() => {
  const shapeDrawings = Object.assign(Object.create(null), JSON.parse(document.getElementById('creates-shape-drawings')?.textContent || '{}'));
  const shapeStrokes = Object.assign(Object.create(null), JSON.parse(document.getElementById('creates-shape-strokes')?.textContent || '{}'));
  const colours = {black:'#20212a',white:'#f5f1e9',red:'#c92739',blue:'#2760b0',green:'#27845d',pink:'#ec71a7',purple:'#8652ae',gold:'#cda34e',silver:'#abb4c4','rose gold':'#c68d80',orange:'#ed8b32',yellow:'#efd04a'};
  function colour(value) {
    if (colours[value.toLowerCase()]) return colours[value.toLowerCase()];
    return CSS.supports('color', value) ? value : '#8e96a8';
  }
  const zoomReady = new WeakSet();
  function bindZoom(figure) {
    if (zoomReady.has(figure)) return;
    zoomReady.add(figure);
    const viewport = figure.querySelector('.headband-preview-viewport');
    viewport.classList.remove('is-hoverzoom');
    viewport.style.setProperty('--zoom-origin', '50% 50%');
    viewport.addEventListener('pointerenter', event => {
      if (event.pointerType === 'mouse') viewport.classList.add('is-hoverzoom');
    });
    const reset = () => viewport.classList.remove('is-hoverzoom');
    viewport.addEventListener('pointerleave', reset);
    viewport.addEventListener('pointercancel', reset);
    viewport.addEventListener('pointermove', event => {
      if (event.pointerType !== 'mouse') return;
      const box = viewport.getBoundingClientRect();
      const x = Math.max(0, Math.min(100, (event.clientX-box.left)/box.width*100));
      const y = Math.max(0, Math.min(100, (event.clientY-box.top)/box.height*100));
      viewport.style.setProperty('--zoom-origin', `${x}% ${y}%`);
    });
  }
  function render(line, drawings=shapeDrawings, strokes=shapeStrokes) {
    let figure = line.querySelector('[data-headband-preview]');
    if (!figure) {
      figure = document.createElement('figure');
      figure.className = 'headband-preview';
      figure.dataset.headbandPreview = '';
      const canvas = document.createElement('canvas');
      canvas.width = 1600;
      canvas.height = 1000;
      canvas.setAttribute('role', 'img');
      const viewport = document.createElement('div');
      viewport.className = 'headband-preview-viewport';
      viewport.setAttribute('aria-label', 'Design preview. Hover to zoom.');
      viewport.append(canvas);
      const caption = document.createElement('figcaption');
      const title = document.createElement('strong');
      title.textContent = 'Your design at a glance';
      const description = document.createElement('div');
      description.dataset.previewDescription = '';
      const disclaimer = document.createElement('p');
      disclaimer.className = 'headband-preview-disclaimer';
      disclaimer.textContent = 'Preview only. Colours and glitter may look slightly different in person.';
      const hint=document.createElement('p');hint.className='headband-preview-disclaimer';hint.textContent='Hover over your design to zoom in.';
      caption.append(title, hint, description, disclaimer);
      figure.append(viewport, caption);
      line.querySelector('.remove-line').before(figure);
    }
    bindZoom(figure);
    const canvas = figure.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(2, 0, 0, 2, 0, 0);
    const wording = line.querySelector('[name=wording]').value.trim();
    const letterColour = line.querySelector('[name=colour]').value;
    const backgroundColour = line.querySelector('[name=background_colour]')?.value || 'Black';
    const boldColour = line.querySelector('[name=bold_colour]')?.value || 'Black';
    const baseInk = colour(backgroundColour), boldInk = colour(boldColour);
    const finish = line.querySelector('[name=letter_finish]').value;
    const glitterColour = line.querySelector('[name=glitter_colour]').value;
    const selectedShape = line.querySelector('[name=word_shape]').value;
    const shape = selectedShape || (wording.split(/\s+/).filter(Boolean).length === 3 ? '?' : '');
    const glitter = finish === 'Glitter';
    const ink = glitter ? colour(glitterColour || 'Gold') : colour(letterColour);
    let description = `${wording || 'Your wording'}: ${backgroundColour} background, ${boldColour} outline, ${glitter ? (glitterColour || 'Choose a colour') + ' glitter' : letterColour + ' plain'} letters${shape && wording.split(/\s+/).length > 1 ? '. ' + shape + ' shapes between words' : ''}.`;
    canvas.setAttribute('aria-label', 'Illustrative headband preview: ' + description);
    figure.querySelector('[data-preview-description]').textContent = description;
    ctx.clearRect(0, 0, 800, 500);
    const background = ctx.createLinearGradient(0, 0, 800, 500);
    background.addColorStop(0, '#fff8fc');
    background.addColorStop(1, '#eef0fa');
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, 800, 500);
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.arc(400, 390, 177, Math.PI, Math.PI * 2);
    ctx.strokeStyle = '#b9b9c4';
    ctx.lineWidth = 15;
    ctx.stroke();
    ctx.strokeStyle = '#15151a';
    ctx.lineWidth = 11;
    ctx.stroke();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const words=(wording || 'YOUR WORDS').toUpperCase().split(/\s+/).filter(Boolean).slice(0,3);
    for(const [kind,count] of [['word',words.length],['shape',selectedShape?words.length-1:0]]){
      for(let index=1;index<=count;index++){
        const value=line.querySelector(`[name=${kind}_colour_${index}]`)?.value;
        if(value)description+=` ${kind==='word'?'Word':'Shape'} ${index}: ${value}${glitter?' glitter':''}.`;
      }
    }
    const coils=[290,510], coilTop=205;
    // Coil positions, wire colour and dimensions are hardware, not design options.
    for(const x of coils){
      const bottom=390-Math.sqrt(177**2-(x-400)**2);
      const drawSpring=(stroke,width)=>{
        ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.beginPath();
        ctx.moveTo(x,bottom);ctx.lineTo(x,bottom-6);
        for(let y=bottom-10;y>coilTop+5;y-=6){
          ctx.moveTo(x+6,y);ctx.ellipse(x,y,6,2.5,0,0,Math.PI*2);
        }
        ctx.moveTo(x,coilTop+7);ctx.lineTo(x,coilTop);ctx.moveTo(x-8,coilTop);ctx.lineTo(x+8,coilTop);ctx.stroke();
      };
      drawSpring('#a1a1aa',4);drawSpring('#15151a',2);
    }
    const paints=new Map();
    const makePaint=value=>{
      if(!glitter)return value;
      if(paints.has(value))return paints.get(value);
      const texture=document.createElement('canvas');texture.width=texture.height=32;
      const paint=texture.getContext('2d');paint.fillStyle=value;paint.fillRect(0,0,32,32);paint.fillStyle='#ffffffaa';
      for(let fleck=0;fleck<28;fleck++)paint.fillRect((fleck*7)%32,(fleck*13)%32,1.2,1.2);
      const pattern=ctx.createPattern(texture,'repeat');paints.set(value,pattern);return pattern;
    };
    const letterPaint=makePaint(ink);
    const makeGlyph=(token,isShape=false,index=0)=>{
      const name=isShape?shape:token;
      const font=isShape?'bold 11px Arial':'900 31px Georgia, serif';
      ctx.font=font;
      const metrics=ctx.measureText(name.slice(0,10));
      const offset=isShape&&(drawings[shape]||['heart','star'].includes(shape.toLowerCase()))?0:(metrics.actualBoundingBoxRight-metrics.actualBoundingBoxLeft)/2;
      const chosen=line.querySelector(`[name=${isShape?'shape':'word'}_colour_${index+1}]`)?.value;
      return {token,name,isShape,font,offset,face:chosen?makePaint(colour(chosen)):letterPaint};
    };
    const paintGlyph=(paint,glyph,x,y,scale,base=baseInk,bold=boldInk,face=letterPaint,angle=0)=>{
      paint.save();paint.translate(x,y);paint.rotate(angle);paint.scale(scale,scale);paint.translate(-glyph.offset,0);
      paint.textAlign='center';paint.textBaseline='middle';paint.lineJoin='round';paint.font=glyph.font;
      const customPoints=glyph.isShape ? drawings[shape] : null;
      const pathShape=glyph.isShape&&(customPoints||['heart','star'].includes(shape.toLowerCase()));
      if(pathShape){
        paint.beginPath();
        if(customPoints){
          customPoints.forEach(([x,y],index)=>index ? paint.lineTo(x,y) : paint.moveTo(x,y));paint.closePath();
        }else if(shape.toLowerCase()==='heart'){
          paint.moveTo(0,12);paint.bezierCurveTo(-30,-6,-8,-23,0,-9);paint.bezierCurveTo(8,-23,30,-6,0,12);paint.closePath();
        }else{
          for(let point=0;point<10;point++){const theta=point*Math.PI/5-Math.PI/2,radius=point%2?7:16;paint.lineTo(Math.cos(theta)*radius,Math.sin(theta)*radius);}paint.closePath();
        }
        const stroke=strokes[shape]??7;
        paint.strokeStyle=base;paint.lineWidth=stroke+4;paint.stroke();
        if(stroke>0){paint.strokeStyle=bold;paint.lineWidth=stroke;paint.stroke();}
        paint.fillStyle=face;paint.fill();
      }else{
        paint.strokeStyle=base;paint.lineWidth=11;paint.strokeText(glyph.name.slice(0,10),0,0);
        paint.strokeStyle=bold;paint.lineWidth=7;paint.strokeText(glyph.name.slice(0,10),0,0);
        paint.fillStyle=face;paint.fillText(glyph.name.slice(0,10),0,0);
      }
      paint.restore();
    };
    const geometry=new Map();
    const measure=glyph=>{
      const key=(glyph.isShape?'shape:':'letter:')+glyph.name;
      if(geometry.has(key))return geometry.get(key);
      const mask=document.createElement('canvas');mask.width=220;mask.height=130;
      const paint=mask.getContext('2d');paintGlyph(paint,glyph,110,65,1,'white','white','white');
      const pixels=paint.getImageData(0,0,220,130).data,rows=new Map();
      let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity;
      for(let y=0;y<130;y++)for(let x=0;x<220;x++)if(pixels[(y*220+x)*4+3]>127){
        const row=rows.get(y-65)||[Infinity,-Infinity];row[0]=Math.min(row[0],x-110);row[1]=Math.max(row[1],x-110);rows.set(y-65,row);
        left=Math.min(left,x-110);right=Math.max(right,x-110);top=Math.min(top,y-65);bottom=Math.max(bottom,y-65);
      }
      const result={rows,left,right,top,bottom};geometry.set(key,result);return result;
    };
    const pack=sequence=>{
      const positions=[0];
      for(let index=1;index<sequence.length;index++){
        const previous=measure(sequence[index-1]),current=measure(sequence[index]);let advance=0;
        for(const [y,bounds] of previous.rows)for(let offset=-1;offset<=1;offset++){
          const next=current.rows.get(y+offset);if(next)advance=Math.max(advance,bounds[1]-next[0]);
        }
        positions.push(positions[index-1]+advance-.4);
      }
      const bounds=(first,last)=>({left:positions[first]+measure(sequence[first]).left,right:positions[last]+measure(sequence[last]).right,
        bottom:Math.max(...sequence.slice(first,last+1).map(measure).map(value=>value.bottom))});
      return {positions,bounds};
    };
    const letters=(word,index=0)=>Array.from(word).map(token=>makeGlyph(token,false,index));
    // Distances follow the arc, so curvature does not squeeze the lettering.
    const curveRadius=330;
    const curveBaseline=coilTop-(curveRadius-Math.sqrt(curveRadius**2-(coils[1]-400)**2));
    const paintCurved=(glyph,x,bottom,scale)=>{
      const radius=curveRadius+bottom*scale-2;
      const angle=(x-400)/radius;
      paintGlyph(ctx,glyph,400+radius*Math.sin(angle),curveBaseline+curveRadius-radius*Math.cos(angle),scale,baseInk,boldInk,glyph.face,angle);
    };
    const packCurved=(sequence,scale,bottom,anchor)=>{
      const radius=curveRadius+bottom*scale-2,positions=[0];
      const mask=document.createElement('canvas');mask.width=512;mask.height=320;
      const paint=mask.getContext('2d',{willReadFrequently:true});
      paint.setTransform(2,0,0,2,0,0);
      for(let index=1;index<sequence.length;index++){
        paint.clearRect(0,0,256,160);
        paintGlyph(paint,sequence[index-1],80,80,scale,'white','white','white');
        const previous=paint.getImageData(0,0,512,320).data;
        const occupied=[];
        for(let pixel=0;pixel<previous.length;pixel+=4)if(previous[pixel+3]>127)occupied.push(pixel+3);
        const touches=distance=>{
          paint.clearRect(0,0,256,160);
          const angle=distance/radius;
          paintGlyph(paint,sequence[index],80+radius*Math.sin(angle),80+radius*(1-Math.cos(angle)),scale,'white','white','white',angle);
          const next=paint.getImageData(0,0,512,320).data;
          return occupied.some(pixel=>next[pixel]>127);
        };
        let low=0,high=(measure(sequence[index-1]).right-measure(sequence[index]).left+12)*scale;
        while(touches(high))high+=10;
        // Find actual backing contact after rotation, rather than reusing
        // straight lettering widths. Only the outer padding has a small join.
        for(let pass=0;pass<10;pass++){
          const middle=(low+high)/2;
          if(touches(middle))low=middle;else high=middle;
        }
        positions.push(positions[index-1]+Math.max(0,low-.7));
      }
      const center=(measure(sequence[0]).left*scale+positions[positions.length-1]+measure(sequence[sequence.length-1]).right*scale)/2;
      return positions.map(position=>anchor+position-center);
    };
    const mountDescription=words.length===1 ? `Single word: ${words[0]}, centred across both coils.` : words.length===3
      ? `Left coil: ${words[0]}. Suspended middle word: ${words[1]}, joined by ${selectedShape || 'a shape you must select'}. Right coil: ${words[2]}.`
      : `Left coil: ${words[0] || 'first word'}. Right coil: ${words[1] || 'second word'}.`;
    canvas.setAttribute('aria-label','Illustrative headband preview: '+description+` ${boldColour} bold outline. ${shape ? shape+' between words. ' : ''}`+'Two fixed spring coils. '+mountDescription);
    const summary=figure.querySelector('[data-preview-description]');summary.replaceChildren();
    const wordingSummary=document.createElement('p');wordingSummary.className='preview-wording';wordingSummary.textContent=wording||'Enter your wording to see your design';summary.append(wordingSummary);
    const segments=document.createElement('div');segments.className='preview-summary-segments';summary.append(segments);
    const makeSegment=heading=>{
      const section=document.createElement('section'),title=document.createElement('h4'),details=document.createElement('dl');
      section.className='preview-summary-segment';title.textContent=heading;details.className='preview-design-details';
      section.append(title,details);segments.append(section);return details;
    };
    const addDetail=(details,label,value,swatch='')=>{
      const row=document.createElement('div'),term=document.createElement('dt'),definition=document.createElement('dd');
      term.textContent=label;
      if(swatch){const chip=document.createElement('span');chip.className='preview-colour-swatch';chip.style.backgroundColor=colour(swatch);chip.setAttribute('aria-hidden','true');definition.append(chip);}
      definition.append(document.createTextNode(value));row.append(term,definition);details.append(row);
    };
    const baseDetails=makeSegment('Headband & finish');
    addDetail(baseDetails,'Headband','Black');
    addDetail(baseDetails,'Background backing',backgroundColour,backgroundColour);
    addDetail(baseDetails,'Bold border',boldColour,boldColour);
    addDetail(baseDetails,'Finish',glitter?'Glitter':'Plain');
    if(wording){
      const originalWords=wording.split(/\s+/);
      const wordDetails=makeSegment('Word colours');
      const shapeDetails=originalWords.length>1?makeSegment('Shapes between words'):null;
      originalWords.forEach((word,index)=>{
        const wordColour=line.querySelector(`[name=word_colour_${index+1}]`)?.value||(glitter?glitterColour:letterColour);
        addDetail(wordDetails,`Word ${index+1}: ${word}`,wordColour||'Choose a colour',wordColour);
        if(index<originalWords.length-1){
          if(selectedShape){
            const shapeColour=line.querySelector(`[name=shape_colour_${index+1}]`)?.value||(glitter?glitterColour:letterColour);
            addDetail(shapeDetails,`Shape ${index+1}: ${selectedShape}`,shapeColour||'Choose a colour',shapeColour);
            const placement=document.createElement('small');placement.className='preview-shape-placement';placement.textContent=`Between words ${index+1} and ${index+2}`;shapeDetails.lastElementChild.querySelector('dt').append(placement);
          }else addDetail(shapeDetails,`Between words ${index+1} and ${index+2}`,originalWords.length===3?'Choose a shape':'Plain space');
        }
      });
    }
    if(words.length===3){
      const first=letters(words[0],0),middle=letters(words[1],1),last=letters(words[2],2);
      const sequence=[...first,makeGlyph(' ',true,0),...middle,makeGlyph(' ',true,1),...last];
      const layout=pack(sequence);
      const left=layout.bounds(0,first.length-1),right=layout.bounds(sequence.length-last.length,sequence.length-1);
      const leftCenter=(left.left+left.right)/2,rightCenter=(right.left+right.right)/2;
      const scale=(coils[1]-coils[0])/(rightCenter-leftCenter);
      // Keep one undistorted letter size across all words, and centre
      // the complete backing rather than squeezing the longer outer word.
      const bottom=Math.max(left.bottom,right.bottom);
      const positions=packCurved(sequence,scale,bottom,400);
      sequence.forEach((glyph,index)=>paintCurved(glyph,positions[index],bottom,scale));
    }else{
      const groups=words.map(letters),layouts=groups.map(pack);
      const widths=layouts.map((layout,index)=>{const box=layout.bounds(0,groups[index].length-1);return box.right-box.left;});
      // A single backing must bridge both springs, with a little overhang.
      // The per-coil width limit is only appropriate for separate words.
      const scale=words.length===1
        ? (coils[1]-coils[0]+50)/Math.max(widths[0],1)
        : Math.min(1.2,185/Math.max(...widths,1));
      groups.forEach((group,index)=>{
        const layout=layouts[index],box=layout.bounds(0,group.length-1);
        const positions=packCurved(group,scale,box.bottom,words.length===1 ? 400 : coils[index]);
        group.forEach((glyph,position)=>paintCurved(glyph,positions[position],box.bottom,scale));
      });
      if(selectedShape&&words.length===2){
        const separator=makeGlyph(' ',true);
        paintCurved(separator,400,measure(separator).bottom,Math.min(scale,1));
      }
    }
    ctx.fillStyle = '#69718a';
    ctx.font = '15px Arial';
    ctx.fillText('CL CREATES  ·  DESIGN PREVIEW', 400, 465);
  }
  window.renderHeadbandPreview = render;
})();
