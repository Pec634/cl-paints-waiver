(() => {
  const form = document.getElementById('loyalty-member-selection');
  if (!form || typeof HTMLDialogElement === 'undefined' ||
      typeof HTMLDialogElement.prototype.showModal !== 'function' ||
      !form.querySelector('input[name="member_id"]')) return;

  const dialog = document.createElement('dialog');
  dialog.className = 'loyalty-selection-dialog';
  dialog.setAttribute('aria-labelledby', 'loyalty-selection-title');
  const heading = document.createElement('div');
  heading.className = 'loyalty-selection-heading';
  const title = document.createElement('h2');
  title.id = 'loyalty-selection-title';
  title.textContent = 'Who is being painted today?';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'btn';
  close.textContent = 'Close';
  close.addEventListener('click', () => dialog.close());
  heading.append(title, close);
  const help = document.createElement('p');
  help.textContent = 'Select the participants below, then confirm to add their points or claim their free paint.';
  const reopen = document.createElement('button');
  reopen.type = 'button';
  reopen.className = 'btn primary';
  reopen.textContent = 'Select participants for check-in';
  reopen.addEventListener('click', () => dialog.showModal());
  form.before(reopen);
  dialog.append(heading, help, form);
  document.body.append(dialog);
  dialog.addEventListener('close', () => reopen.focus());
  form.addEventListener('submit', (event) => {
    if (!form.querySelector('input[name="member_id"]:checked')) {
      event.preventDefault();
      help.textContent = 'Select at least one participant being painted today before confirming.';
      help.setAttribute('role', 'alert');
      form.querySelector('input[name="member_id"]').focus();
    }
  });
  dialog.showModal();
})();
