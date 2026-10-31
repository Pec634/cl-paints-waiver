const form = document.getElementById('creates-form');
const lines = document.getElementById('creates-lines');
const total = document.getElementById('creates-total');
function updateCreates() {
  const posting = form.fulfilment.value === 'postage';
  document.getElementById('shipping').disabled = !posting;
  document.getElementById('shipping').hidden = !posting;
  let quantity = 0;
  lines.querySelectorAll('.creates-line').forEach(line => {
    const glitter = line.querySelector('[name=letter_finish]').value === 'Glitter';
    line.querySelector('[data-glitter-colour]').hidden = !glitter;
    line.querySelector('[name=glitter_colour]').required = glitter;
    if (window.renderHeadbandPreview) window.renderHeadbandPreview(line);
  });
  lines.querySelectorAll('[name=quantity]').forEach(input => quantity += Number(input.value) || 0);
  lines.querySelectorAll('[name=wording]').forEach(input => {
    const value = input.value;
    input.setCustomValidity([...value].filter(c => c !== ' ').length > 11 || (value.match(/ /g) || []).length > 2 ? 'Use up to 11 characters plus two spaces.' : '');
  });
  total.textContent = `Order total: £${((quantity * Math.round(Number(total.dataset.price) * 100) + (posting ? Math.round(Number(total.dataset.postage) * 100) : 0)) / 100).toFixed(2)}`;
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
