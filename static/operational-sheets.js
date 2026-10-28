(() => {
  const sheet = document.querySelector('[data-operational-sheet]');
  const opener = document.querySelector('[data-open-sheet]');
  if (!sheet || !opener || typeof HTMLDialogElement === 'undefined') return;
  const dialog = document.createElement('dialog');
  dialog.className = 'operational-sheet-dialog';
  dialog.setAttribute('aria-labelledby', 'operational-sheet-title');
  const heading = document.createElement('header');
  heading.className = 'operational-sheet-heading';
  const title = document.createElement('h2');
  title.id = 'operational-sheet-title';
  title.textContent = sheet.dataset.sheetTitle;
  const close = document.createElement('button');
  close.type = 'button'; close.className = 'btn'; close.textContent = 'Close sheet';
  close.dataset.closeSheet = '';
  heading.append(title, close);
  const body = document.createElement('div'); body.className = 'operational-sheet-body';
  sheet.before(dialog); body.append(sheet); dialog.append(heading, body);
  const navigation = document.createElement('nav');
  navigation.className = 'operational-sheet-navigation';
  navigation.setAttribute('aria-label', 'Sheet sections');
  sheet.querySelectorAll('[data-handover-form] > section > h2, [data-cashup-form] > section > h2, .sheet-closing-stage > section > h2, [data-invoice-reconciliation] > h2').forEach((label, index) => {
    const section = label.parentElement;
    section.id ||= 'sheet-section-'+index;
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label.textContent;
    button.addEventListener('click', () => {
      section.scrollIntoView({block:'start', behavior:'instant'});
      const target = section.querySelector('input:not([type="hidden"]), textarea, select');
      target?.focus({preventScroll:true});
    });
    navigation.append(button);
  });
  heading.after(navigation);
  const open = () => {
    if (dialog.open) return;
    dialog.showModal();
    document.documentElement.classList.add('operational-sheet-open');
    const error = sheet.querySelector('[role="alert"]');
    if (error) { error.tabIndex = -1; error.focus(); }
  };
  opener.hidden = false;
  opener.addEventListener('click', open);
  const closeSheet = () => {
    dialog.close();
    document.documentElement.classList.remove('operational-sheet-open');
    opener.focus();
  };
  close.addEventListener('click', closeSheet);
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeSheet();
  });
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    document.documentElement.classList.remove('operational-sheet-open');
    opener.focus();
  });
  // Close and Escape keep the same live form, including unsaved values.
  open();
})();
