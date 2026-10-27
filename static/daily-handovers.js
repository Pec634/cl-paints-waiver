(() => {
  const form = document.querySelector('[data-handover-form]');
  const rows = form?.querySelector('[data-staff-rows]');
  const template = document.getElementById('handover-staff-template');
  if (!form || !rows || !template) return;
  const message = form.querySelector('[data-staff-message]');
  form.querySelector('[data-add-staff]').addEventListener('click', () => {
    if (rows.children.length >= 30) { message.textContent = 'A handover supports up to 30 staff members.'; return; }
    rows.append(template.content.cloneNode(true));
    rows.lastElementChild.querySelector('input').focus();
    message.textContent = 'Staffing row added.';
    form.dispatchEvent(new Event('input', {bubbles:true}));
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-staff]');
    if (!button) return;
    const row = button.closest('[data-staff-row]');
    const next = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    (next?.querySelector('input') || form.querySelector('[data-add-staff]')).focus();
    message.textContent = 'Staffing row removed. Save the handover to keep this change.';
    form.dispatchEvent(new Event('input', {bubbles:true}));
  });
})();
