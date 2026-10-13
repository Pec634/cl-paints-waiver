(() => {
  const main = document.querySelector('.admin main');
  if (!main) return;
  const read = key => { try { return JSON.parse(localStorage.getItem(key)); } catch (_) { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  // Remember only report filter preferences, never client search terms or record data.
  document.querySelectorAll('.reports-filters, form[data-report-preferences]').forEach(form => {
    const key = 'cl-paints-report-preferences:' + location.pathname;
    const allowed = ['period', 'start', 'end', 'setting', 'location', 'view', 'state'];
    const saved = read(key);
    if (!location.search && saved) {
      const params = new URLSearchParams();
      allowed.forEach(name => { if (typeof saved[name] === 'string') params.set(name, saved[name]); });
      if (params.size) { location.replace(location.pathname + '?' + params); return; }
    }
    const remember = () => {
      const preferences = {};
      allowed.forEach(name => {
        const field = form.elements.namedItem(name);
        if (field && !field.disabled) preferences[name] = field.value;
      });
      if (preferences.period && preferences.period !== 'custom') { delete preferences.start; delete preferences.end; }
      write(key, preferences);
    };
    form.addEventListener('submit', remember);
    window.addEventListener('report-view-change', remember);
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'btn'; reset.textContent = 'Reset saved view';
    reset.addEventListener('click', () => { try { localStorage.removeItem(key); } catch (_) {} location.href = location.pathname + '?view=overview'; });
    form.append(reset);
  });
  // Compact settings while retaining every original form and its validation.
  document.querySelectorAll('.settings-column > .panel').forEach(panel => {
    if (panel.classList.contains('settings-business-tools')) return;
    const heading = panel.querySelector(':scope > h2');
    if (!heading) return;
    const title = heading.textContent.trim();
    const key = 'cl-paints-settings-fold:' + title;
    const fold = document.createElement('details'); fold.className = 'panel settings-fold';
    const summary = document.createElement('summary'); summary.textContent = title;
    const hint = document.createElement('span'); hint.className = 'settings-fold-hint';
    hint.textContent = panel.id === 'qr-generator' ? 'Create, brand and track QR codes' : 'Expand to view and edit';
    summary.append(hint);
    const body = document.createElement('div'); body.className = 'settings-fold-body';
    panel.before(fold); body.append(panel); fold.append(summary, body);
    const saved = read(key); fold.open = saved === null ? title === 'Business details' : saved === true;
    fold.addEventListener('toggle', () => write(key, fold.open));
    panel.addEventListener('invalid', () => { fold.open = true; }, true);
    panel.querySelectorAll('form').forEach(form => form.setAttribute('data-warn-unsaved', ''));
  });
  const settingsGrid = main.querySelector('.settings-columns');
  if (settingsGrid) {
    const controls = document.createElement('div'); controls.className = 'workspace-list-tools';
    [['Expand all sections', true], ['Collapse all sections', false]].forEach(([label, open]) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = label;
      button.onclick = () => settingsGrid.querySelectorAll('.settings-fold').forEach(fold => { fold.open = open; });
      controls.append(button);
    });
    settingsGrid.before(controls);
    const failedSection = main.dataset.settingsSection;
    if (failedSection) settingsGrid.querySelectorAll('input[name="section"]').forEach(field => {
      if (field.value === failedSection) field.closest('.settings-fold').open = true;
    });
  }
  function revealAnchor() {
    if (!location.hash) return;
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
    if (!target) return;
    let parent = target.parentElement;
    while (parent) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
    const row = target.closest('tr');
    if (row) row.dispatchEvent(new CustomEvent('workspace-reveal', {bubbles: true}));
    requestAnimationFrame(() => (target.closest('.settings-fold') || target).scrollIntoView({block: 'center'}));
  }
  window.addEventListener('hashchange', revealAnchor);
  main.querySelectorAll('.dashboard-tag, .status-badge').forEach(badge => {
    const text = badge.textContent.trim();
    badge.classList.add('workspace-badge');
    badge.dataset.tone = /Accepted|Open|Paid|Valid|Completed/.test(text) ? 'success' : /Declined|Cancelled|Overdue/.test(text) ? 'danger' : /review|pending|expiring|due/i.test(text) ? 'warning' : 'neutral';
  });
  main.querySelectorAll('.waiver-table').forEach(table => {
    table.classList.add('workspace-card-table');
    const headings = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
    table.querySelectorAll('tbody tr').forEach(row => {
      if (row.cells.length === headings.length) [...row.cells].forEach((cell, index) => { cell.dataset.columnLabel = headings[index]; });
    });
  });
  main.querySelectorAll('[data-workspace-list]').forEach(table => {
    const isTable = table.tagName === 'TABLE';
    const rows = [...table.querySelectorAll(isTable ? 'tbody tr' : ':scope > article')].filter(row => !row.querySelector('[colspan]'));
    if (!rows.length) return;
    const tools = document.createElement('div'); tools.className = 'workspace-list-tools';
    const search = table.classList.contains('booking-table') ? document.getElementById('bookingSearch') : document.createElement('input');
    const searchType = document.getElementById('bookingSearchType');
    if (!search.id) { search.type = 'search'; search.placeholder = 'Search names, dates or details'; const label = document.createElement('label'); label.textContent = 'Search records'; label.append(search); tools.append(label); }
    const status = document.createElement('select');
    status.add(new Option('All statuses', ''));
    const states = [...new Set(rows.map(row => row.dataset.recordStatus).filter(Boolean))].sort();
    states.forEach(state => status.add(new Option(state, state)));
    const statusLabel = document.createElement('label'); statusLabel.textContent = 'Status'; statusLabel.append(status); tools.append(statusLabel);
    statusLabel.hidden = states.length === 0;
    const size = document.createElement('select'); [10, 25, 50].forEach(value => size.add(new Option(`${value} per page`, String(value))));
    const sizeLabel = document.createElement('label'); sizeLabel.textContent = 'Show'; sizeLabel.append(size); tools.append(sizeLabel);
    const wrapper = table.closest('.table-wrap') || table;
    wrapper.before(tools);
    const pager = document.createElement('div'); pager.className = 'workspace-pagination'; pager.setAttribute('aria-label', 'List pagination');
    const summary = document.createElement('span'); summary.setAttribute('role', 'status');
    const previous = document.createElement('button'); previous.type = 'button'; previous.className = 'btn'; previous.textContent = 'Previous';
    const next = document.createElement('button'); next.type = 'button'; next.className = 'btn'; next.textContent = 'Next';
    const pageLabel = document.createElement('span');
    pager.append(summary, previous, pageLabel, next); wrapper.after(pager);
    const empty = document.createElement('p'); empty.className = 'workspace-empty'; empty.textContent = 'No records match your search. Clear the search or choose another status.'; pager.before(empty);
    let page = 1;
    const searchText = row => {
      if (table.classList.contains('booking-table') && searchType) {
        const selectors = {client: '[data-search-client]', email: '[data-search-email]', phone: '[data-search-phone]', event: '[data-search-event]'};
        return row.querySelector(selectors[searchType.value])?.textContent || '';
      }
      if (!isTable) return row.textContent;
      return [...row.cells].map(cell => cell.querySelector('select') ? cell.querySelector('select').value : cell.textContent).join(' ');
    };
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const matched = rows.filter(row => searchText(row).toLowerCase().includes(query) && (!status.value || row.dataset.recordStatus === status.value));
      const length = Number(size.value), pages = Math.max(1, Math.ceil(matched.length / length)); page = Math.min(page, pages);
      const visible = new Set(matched.slice((page - 1) * length, page * length)); rows.forEach(row => { row.hidden = !visible.has(row); });
      summary.textContent = `${matched.length ? (page - 1) * length + 1 : 0}–${Math.min(page * length, matched.length)} of ${matched.length} records`;
      pageLabel.textContent = `Page ${page} of ${pages}`; previous.disabled = page === 1; next.disabled = page === pages; empty.hidden = matched.length > 0;
    };
    [search, status, size, searchType].filter(Boolean).forEach(field => field.addEventListener(field === search ? 'input' : 'change', () => { page = 1; render(); }));
    previous.onclick = () => { page--; render(); }; next.onclick = () => { page++; render(); };
    table.addEventListener('workspace-reveal', event => {
      const row = event.target.closest(isTable ? 'tr' : 'article'); search.value = ''; status.value = ''; page = Math.floor(rows.indexOf(row) / Number(size.value)) + 1; render();
    });
    render();
  });
  revealAnchor();
})();
