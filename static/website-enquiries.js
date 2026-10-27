(() => {
  const form = document.querySelector('[data-enquiry-selection]');
  if (!form) return;
  const choices = [...form.querySelectorAll('[name="enquiry_ids"]')];
  const all = form.querySelector('[data-select-all]');
  const confirmation = form.elements.confirm_delete;
  const button = form.querySelector('[data-delete-selected]');
  const count = form.querySelector('[data-selection-count]');
  form.querySelector('[data-select-all-label]').hidden = false;
  function update(resetConfirmation = false) {
    if (resetConfirmation) confirmation.checked = false;
    const selected = choices.filter(choice => choice.checked).length;
    all.checked = selected === choices.length;
    all.indeterminate = selected > 0 && selected < choices.length;
    count.textContent = `${selected} of ${choices.length} enquiries selected on this page`;
    button.textContent = selected ? `Delete ${selected} selected ${selected === 1 ? 'enquiry' : 'enquiries'}` : 'Delete selected enquiries';
    button.disabled = selected === 0 || !confirmation.checked;
  }
  choices.forEach(choice => choice.addEventListener('change', () => update(true)));
  all.addEventListener('change', () => {
    choices.forEach(choice => { choice.checked = all.checked; });
    update(true);
  });
  confirmation.addEventListener('change', () => update());
  form.addEventListener('submit', event => {
    if (!choices.some(choice => choice.checked) || !confirmation.checked) event.preventDefault();
  });
  update();
})();
