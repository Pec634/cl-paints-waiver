const form = document.getElementById('creates-form');
const lines = document.getElementById('creates-lines');
const total = document.getElementById('creates-total');
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
    if (window.renderHeadbandPreview) window.renderHeadbandPreview(line);
  });
  lines.querySelectorAll('[name=quantity]').forEach(input => quantity += Number(input.value) || 0);
  lines.querySelectorAll('[name=wording]').forEach(input => {
    const value = input.value;
    input.setCustomValidity(value.trim().split(/\s+/).filter(Boolean).length === 1 && [...value.trim()].length < 7 ? 'Single-word headbands require at least 7 characters.' : [...value].filter(c => c !== ' ').length > 16 || (value.match(/ /g) || []).length > 2 ? 'Use up to 16 characters plus two spaces.' : '');
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
