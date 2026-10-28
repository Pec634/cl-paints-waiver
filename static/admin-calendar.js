(() => {
  const actions = document.querySelector('.booking-actions-menu');
  if (actions) {
    document.addEventListener('click', event => {
      if (!actions.contains(event.target)) actions.open = false;
    });
    actions.addEventListener('keydown', event => {
      if (event.key === 'Escape' && actions.open) {
        actions.open = false;
        actions.querySelector('summary').focus();
        event.stopPropagation();
      }
    });
    actions.querySelector('nav').addEventListener('click', event => {
      if (event.target.closest('a')) actions.open = false;
    });
  }
  const dialog = document.getElementById('calendar-event-dialog');
  const content = document.getElementById('calendar-dialog-content');
  let opener;
  document.querySelectorAll('.booking-row').forEach(row => {
    const details = row.querySelector('.booking-detail:not(.booking-manage-detail)');
    if (!details) return;
    row.tabIndex = 0;
    row.setAttribute('aria-haspopup', 'dialog');
    const open = event => {
      if (event.target.closest('a, button, input, select, textarea, .booking-manage-detail, .booking-action-detail')) return;
      if (!dialog || typeof dialog.showModal !== 'function') { details.open = true; return; }
      event.preventDefault();
      opener = row;
      content.replaceChildren(details.querySelector('.calendar-detail-content').cloneNode(true));
      dialog.showModal();
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', event => {
      if (event.target === row && ['Enter', ' '].includes(event.key)) open(event);
    });
  });
  document.querySelectorAll('[data-calendar-detail]').forEach(link => {
    link.addEventListener('click', event => {
      const details = document.getElementById(link.dataset.calendarDetail);
      const source = details?.querySelector('.calendar-detail-content');
      if (!source) return;
      if (!dialog || typeof dialog.showModal !== 'function') { details.open = true; return; }
      event.preventDefault();
      opener = link;
      content.replaceChildren(source.cloneNode(true));
      dialog.showModal();
    });
  });
  if (!dialog) return;
  dialog.querySelector('[data-calendar-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => { content.replaceChildren(); opener?.focus(); });
  const revealHash = () => {
    if (!/^#calendar-detail-\d+$/.test(location.hash)) return;
    const details = document.getElementById(location.hash.slice(1));
    if (details) details.open = true;
  };
  window.addEventListener('hashchange', revealHash);
  revealHash();
})();
