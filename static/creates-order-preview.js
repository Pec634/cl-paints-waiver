(() => {
  const container=document.getElementById('order-design-previews');
  const items=JSON.parse(document.getElementById('order-preview-items').textContent);
  items.forEach((item,index)=>{
    const section=document.createElement('section');section.className='panel';
    const title=document.createElement('h3');title.textContent=`${index+1}. ${item.wording} (quantity ${item.quantity})`;
    const line=document.createElement('div');
    const values={wording:item.wording,colour:item.colour||'White',background_colour:item.background_colour||'Black',bold_colour:item.bold_colour||'Black',letter_finish:item.letter_finish||'Plain',glitter_colour:item.glitter_colour||'',word_shape:item.word_shape||''};
    for(const kind of ['word','shape'])(item[kind+'_colours']||[]).forEach((value,index)=>values[`${kind}_colour_${index+1}`]=value);
    Object.entries(values).forEach(([name,value])=>{const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;line.append(field);});
    const anchor=document.createElement('span');anchor.className='remove-line';anchor.hidden=true;line.append(anchor);
    section.append(title,line);container.append(section);
    const drawings=Object.create(null);
    if(item.word_shape_points)drawings[item.word_shape]=item.word_shape_points;
    const strokes=Object.create(null);strokes[item.word_shape]=item.word_shape_stroke_width??7;
    window.renderHeadbandPreview(line,drawings,strokes);
    const canvas=line.querySelector('canvas'),image=document.createElement('img');
    image.src=canvas.toDataURL('image/png');image.alt=canvas.getAttribute('aria-label');image.width=canvas.width;image.height=canvas.height;
    canvas.replaceWith(image);
    const download=document.createElement('a');download.className='btn';download.textContent='Download preview image';download.href=image.src;download.download=`${container.dataset.orderNumber}-design-${index+1}.png`;section.append(download);
    if(item.word_shape&&!item.word_shape_points&&!['heart','star'].includes(item.word_shape.toLowerCase())){
      const warning=document.createElement('p');warning.textContent='This older order has no saved drawing for its separator shape. The preview shows the recorded shape name.';section.append(warning);
    }
  });
})();
