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
  const stream = document.querySelector('[data-calendar-stream]');
  if (stream) {
    const months = stream.querySelector('[data-calendar-months]');
    const jumpToToday = () => {
      const today = stream.querySelector('#calendar-today');
      if (!today) return false;
      const viewport = stream.getBoundingClientRect();
      const day = today.getBoundingClientRect();
      stream.scrollTop += day.top - viewport.top - Math.max(0, (stream.clientHeight - day.height) / 2);
      if (day.left < viewport.left || day.right > viewport.right) {
        stream.scrollLeft += day.left - viewport.left - Math.max(0, (stream.clientWidth - day.width) / 2);
      }
      today.focus({preventScroll: true});
      return true;
    };
    document.querySelector('[data-calendar-today]').addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (jumpToToday()) event.preventDefault();
    });
    if (location.hash === '#calendar-today') jumpToToday();
    const status = document.querySelector('[data-calendar-status]');
    const edges = [...stream.querySelectorAll('[data-calendar-edge]')];
    const adjacentMonth = edge => edge.dataset.calendarEdge === 'previous'
      ? months.firstElementChild.dataset.previous : months.lastElementChild.dataset.next;
    const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
      entries.forEach(entry => { if (entry.isIntersecting) loadMonth(entry.target); });
    }, {root: stream}) : null;

    async function loadMonth(edge) {
      const month = adjacentMonth(edge);
      const button = edge.querySelector('button');
      if (!month || button.disabled) return;
      button.disabled = true;
      status.textContent = 'Loading calendar month…';
      try {
        const url = new URL(stream.dataset.url, location.href);
        url.searchParams.set('month', month);
        url.searchParams.set('fragment', 'month');
        const response = await fetch(url);
        if (!response.ok || response.redirected) throw new Error('Calendar request failed');
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        const panel = page.querySelector('[data-calendar-month]');
        if (panel?.dataset.calendarMonth !== month) throw new Error('Calendar month missing');
        if (edge.dataset.calendarEdge === 'previous') {
          const first = months.firstElementChild;
          const offset = first.getBoundingClientRect().top;
          months.prepend(panel);
          stream.scrollTop += first.getBoundingClientRect().top - offset;
        } else {
          months.append(panel);
        }
        status.textContent = `${panel.querySelector('h3').textContent} loaded.`;
        edge.hidden = !adjacentMonth(edge);
        if (edge.hidden) observer?.unobserve(edge);
      } catch {
        status.textContent = 'This month could not load. Use the load button to retry.';
      } finally {
        button.disabled = false;
      }
    }

    edges.forEach(edge => {
      edge.hidden = !adjacentMonth(edge);
      if (edge.hidden) return;
      edge.querySelector('button').addEventListener('click', () => loadMonth(edge));
      observer?.observe(edge);
    });
  }
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
  document.addEventListener('click', event => {
      const link = event.target.closest('[data-calendar-detail]');
      if (!link) return;
      const details = document.getElementById(link.dataset.calendarDetail);
      const source = details?.querySelector('.calendar-detail-content');
      if (!source) return;
      if (!dialog || typeof dialog.showModal !== 'function') {
        details.hidden = false;
        const schedule = details.closest('.calendar-schedule-panel');
        if (schedule) schedule.open = true;
        details.open = true;
        return;
      }
      event.preventDefault();
      opener = link;
      content.replaceChildren(source.cloneNode(true));
      dialog.showModal();
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
    if (!/^#calendar-detail-(?:\d{4}-\d{2}-)?\d+$/.test(location.hash)) return;
    const details = document.getElementById(location.hash.slice(1));
    if (!details) return;
    const schedule = details.closest('.calendar-schedule-panel');
    if (schedule) schedule.open = true;
    details.hidden = false;
    details.open = true;
    details.scrollIntoView({block: 'nearest'});
  };
  window.addEventListener('hashchange', revealHash);
  revealHash();
})();
