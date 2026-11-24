document.querySelectorAll('[data-equipment-checklist]').forEach(form => {
  const controls = form.querySelector('[data-check-controls]');
  const neededOnly = form.querySelector('[data-needed-only]');
  const count = form.querySelector('[data-needed-count]');
  const items = Array.from(form.querySelectorAll('[data-equipment-option]'), card => ({
    card, checkbox: card.querySelector('input')
  }));

  function update() {
    let needed = 0;
    items.forEach(({card, checkbox}) => {
      if (checkbox.checked) needed += 1;
      card.hidden = neededOnly.checked && !checkbox.checked;
    });
    count.textContent = `${needed} ${needed === 1 ? 'item' : 'items'} needed`;
  }

  form.addEventListener('change', event => {
    if (event.target.type === 'checkbox') update();
  });
  update();
  controls.hidden = false;
});
