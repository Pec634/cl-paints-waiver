const form = document.getElementById('creates-form');
const lines = document.getElementById('creates-lines');
const total = document.getElementById('creates-total');
const partPalettes=JSON.parse(document.getElementById('creates-part-palettes').textContent);
function updateCreates() {
  const posting = form.fulfilment.value === 'postage';
  document.getElementById('shipping').disabled = !posting;
  document.getElementById('shipping').hidden = !posting;
  const collection = document.getElementById('collection');
  if (collection) { collection.hidden = posting; collection.disabled = posting; }
  let quantity = 0;
  lines.querySelectorAll('.creates-line').forEach(line => {
    const separator = line.querySelector('[name=word_shape]');
    separator.required = line.querySelector('[name=wording]').value.trim().split(/\s+/).filter(Boolean).length === 3;
    separator.setCustomValidity(separator.required && !separator.value ? 'Choose a shape to replace each space.' : '');
    const missingShape = separator.required && !separator.value;
    const shapeLabel = line.querySelector('[data-word-shape]');
    shapeLabel.classList.toggle('creates-shape-warning', missingShape);
    separator.setAttribute('aria-invalid', String(missingShape));
    let shapeWarning = shapeLabel.querySelector('[data-shape-warning]');
    if (!shapeWarning) {
      shapeWarning = document.createElement('small');
      shapeWarning.dataset.shapeWarning = '';
      shapeWarning.setAttribute('role', 'status');
      shapeWarning.textContent = 'Three-word wording requires a shape between the words. Please choose a shape.';
      shapeLabel.append(shapeWarning);
    }
    shapeWarning.hidden = !missingShape;
    const glitter = line.querySelector('[name=letter_finish]').value === 'Glitter';
    line.querySelector('[data-glitter-colour]').hidden = !glitter;
    line.querySelector('[name=glitter_colour]').required = glitter;
    const words=line.querySelector('[name=wording]').value.trim().split(/\s+/).filter(Boolean);
    const palette=glitter?partPalettes.glitter:partPalettes.headband;
    line.querySelectorAll('[data-part-colour]').forEach(label=>{
      const index=Number(label.dataset.partIndex),isWord=label.dataset.partColour==='word';
      label.hidden=isWord?index>words.length:!separator.value||index>=words.length;
      const select=label.querySelector('select'),current=select.value;
      if(JSON.stringify([...select.options].slice(1).map(option=>option.value))!==JSON.stringify(palette)){
        select.replaceChildren(new Option('Use overall colour',''),...palette.map(value=>new Option(value,value)));
        select.value=palette.includes(current)?current:'';
      }
      label.querySelector('[data-part-label]').textContent=isWord?`Word ${index}${words[index-1]?' ('+words[index-1]+')':''} colour`:`Shape ${index} (between words ${index} and ${index+1}) colour`;
    });
    if (window.renderHeadbandPreview) window.renderHeadbandPreview(line);
  });
  lines.querySelectorAll('[name=quantity]').forEach(input => quantity += Number(input.value) || 0);
  lines.querySelectorAll('[name=wording]').forEach((input,index) => {
    const value = input.value;
    const missing=7-[...value.trim()].length;
    const tooShort=value.trim().split(/\s+/).filter(Boolean).length===1&&missing>0;
    const message=tooShort?`A single word must have at least 7 characters. Add ${missing} more character${missing===1?'':'s'}.`:[...value].filter(c=>c!==' ').length>16||(value.match(/ /g)||[]).length>2?'Use up to 16 characters plus two spaces.':'';
    input.setCustomValidity(message);
    input.setAttribute('aria-invalid',String(Boolean(message)));
    input.classList.toggle('creates-wording-invalid',Boolean(message));
    let warning=input.parentElement.querySelector('[data-wording-warning]');
    if(!warning){warning=document.createElement('small');warning.dataset.wordingWarning='';warning.setAttribute('role','status');warning.setAttribute('aria-live','polite');input.after(warning);}
    warning.id=`creates-wording-error-${index+1}`;
    const descriptions=(input.getAttribute('aria-describedby')||'').split(/\s+/).filter(id=>id&&!id.startsWith('creates-wording-error-'));
    input.setAttribute('aria-describedby',[...descriptions,warning.id].join(' '));
    warning.textContent=message;warning.hidden=!message;
  });
  const boxes = posting ? Math.ceil(Math.max(0, quantity) / 5) : 0;
  const postage = boxes * Math.round(Number(total.dataset.postage) * 100);
  total.textContent = `Order total: £${((quantity * Math.round(Number(total.dataset.price) * 100) + postage) / 100).toFixed(2)}${posting ? ` (postage: £${(postage / 100).toFixed(2)} for ${boxes} ${boxes === 1 ? 'box' : 'boxes'}, up to 5 headbands per box)` : ''}`;
}
document.getElementById('add-line').addEventListener('click', () => {
  if (lines.children.length >= 30) return;
  const line = lines.firstElementChild.cloneNode(true);
  line.querySelector('[name=wording]').value = '';
  line.querySelector('[name=quantity]').value = 1;
  lines.append(line); updateCreates();
});
lines.addEventListener('click', event => {
  if (event.target.classList.contains('remove-line') && lines.children.length > 1) { event.target.closest('fieldset').remove(); updateCreates(); }
});
form.addEventListener('input', updateCreates);
form.addEventListener('change', updateCreates);
updateCreates();
