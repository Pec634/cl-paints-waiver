(() => {
  const controls = document.getElementById('moodboard-sheet-controls');
  const status = document.getElementById('editor-status');
  const print = document.getElementById('print-sign');
  const printPageSize = document.getElementById('print-page-size');
  const orientation = controls.elements.namedItem('orientation');
  const preview = document.querySelector('.moodboard-sheet-preview');
  const sheets = [...preview.querySelectorAll('[data-sheet]')];
  const layoutStatus = document.getElementById('moodboard-layout-status');
  const grids = [...preview.querySelectorAll('.moodboard-sheet-grid')];
  const defaultTiles = grids.map(grid => [...grid.querySelectorAll('[data-design-id]')]);
  const images = [...preview.querySelectorAll('img')];
  const key = `cl-moodboard-sheets-v1-${controls.closest('[data-event-id]').dataset.eventId}`;
  let selected;
  let dragged;
  let dropTarget;

  function select(tile) {
    selected?.setAttribute('aria-pressed', 'false');
    selected = tile;
    selected?.setAttribute('aria-pressed', 'true');
    if (layoutStatus) layoutStatus.textContent = tile
      ? `${tile.getAttribute('aria-label')}. Select another tile on this sheet to swap.`
      : '';
  }

  function swap(source, target) {
    const grid = source.closest('.moodboard-sheet-grid');
    if (source === target || grid !== target.closest('.moodboard-sheet-grid')) return;
    const tiles = [...grid.children];
    const from = tiles.indexOf(source.parentElement);
    const to = tiles.indexOf(target.parentElement);
    [tiles[from], tiles[to]] = [tiles[to], tiles[from]];
    grid.replaceChildren(...tiles);
    source.focus({preventScroll: true});
    layoutStatus.textContent = 'Designs swapped.';
  }

  function highlightDropTarget(tile) {
    dropTarget?.removeAttribute('data-drop-target');
    dropTarget = tile;
    dropTarget?.setAttribute('data-drop-target', '');
  }

  function restoreOrder(orders) {
    for (const [index, grid] of grids.entries()) {
      const original = defaultTiles[index];
      if (!original.length) continue;
      const remaining = new Map(original.map(tile => [tile.dataset.designId, tile]));
      const ordered = [];
      for (const id of Array.isArray(orders?.[index]) ? orders[index] : []) {
        if (remaining.has(id)) {
          ordered.push(remaining.get(id));
          remaining.delete(id);
        }
      }
      grid.replaceChildren(...ordered, ...remaining.values());
    }
  }

  function updateReadiness() {
    const visible = images.filter(image => !image.closest('[hidden]'));
    const loading = visible.some(image => !image.complete);
    const failed = visible.some(image => image.complete && !image.naturalWidth);
    print.disabled = loading || failed;
    status.textContent = failed ? 'A printable image could not load. Reload the editor to try again.'
      : loading ? 'Loading printable images…'
      : 'Ready to print both A4 sheets.';
  }

  function update() {
    const landscape = orientation.value === 'landscape';
    preview.dataset.orientation = orientation.value;
    printPageSize.textContent = `@page{size:A4 ${orientation.value};margin:0}`;
    for (const sheet of sheets) {
      const page = sheet.dataset.sheet;
      const codes = sheet.querySelector('.moodboard-sheet-codes');
      const grid = sheet.querySelector('.moodboard-sheet-grid');
      for (const figure of codes.querySelectorAll('[data-code]')) {
        figure.hidden = !controls.elements.namedItem(`${page}-${figure.dataset.code}`).checked;
      }
      codes.hidden = !codes.querySelector('figure:not([hidden])');
      sheet.dataset.qrPosition = controls.elements.namedItem(`${page}-position`).value;
      const count = Number(grid.dataset.count);
      const gridRatio = landscape ? (codes.hidden ? 1.6 : 2) : (codes.hidden ? 0.72 : 0.86);
      const automaticColumns = Math.max(1, Math.round(Math.sqrt(count * gridRatio)));
      const columns = Number(controls.elements.namedItem(`${page}-columns`)?.value) || automaticColumns;
      grid.style.setProperty('--columns', columns);
      grid.style.setProperty('--rows', Math.max(1, Math.ceil(count / columns)));
    }
    updateReadiness();
  }

  function store(remove) {
    try {
      if (remove) localStorage.removeItem(key);
      else {
        const saved = Object.fromEntries(new FormData(controls));
        saved.orders = grids.map(grid => [...grid.querySelectorAll('[data-design-id]')]
          .map(tile => tile.dataset.designId));
        localStorage.setItem(key, JSON.stringify(saved));
      }
      if (!print.disabled) status.textContent = remove ? 'Default design restored.' : 'Design saved on this device.';
    } catch (_) {
      status.textContent = 'Browser storage is unavailable.';
    }
  }

  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    if (saved.orientation === 'landscape') orientation.value = 'landscape';
    for (const field of controls.querySelectorAll('[data-page]')) {
      if (field.type === 'checkbox') field.checked = saved[field.name] === 'on';
      else if ([...field.options].some(option => option.value === saved[field.name])) field.value = saved[field.name];
    }
    restoreOrder(saved.orders);
  } catch (_) { /* The editor can run without a saved design. */ }

  preview.addEventListener('click', event => {
    const tile = event.target.closest('.moodboard-tile-control');
    if (!tile) return;
    const source = selected;
    if (source && source.closest('.moodboard-sheet-grid') === tile.closest('.moodboard-sheet-grid')) {
      select();
      swap(source, tile);
    } else {
      select(tile);
    }
  });
  preview.addEventListener('keydown', event => {
    if (event.key === 'Escape') select();
  });
  preview.addEventListener('dragstart', event => {
    const tile = event.target.closest('.moodboard-tile-control');
    if (!tile) return;
    dragged = tile;
    select();
    event.dataTransfer.setData('text/plain', tile.parentElement.dataset.designId);
    event.dataTransfer.effectAllowed = 'move';
  });
  preview.addEventListener('dragover', event => {
    const tile = event.target.closest('.moodboard-tile-control');
    if (!dragged || !tile || tile === dragged ||
        tile.closest('.moodboard-sheet-grid') !== dragged.closest('.moodboard-sheet-grid')) {
      highlightDropTarget();
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    highlightDropTarget(tile);
  });
  preview.addEventListener('drop', event => {
    if (!dragged) return;
    event.preventDefault();
    const tile = event.target.closest('.moodboard-tile-control');
    if (tile) swap(dragged, tile);
    dragged = undefined;
    highlightDropTarget();
  });
  preview.addEventListener('dragend', () => {
    dragged = undefined;
    highlightDropTarget();
  });
  controls.addEventListener('submit', event => event.preventDefault());
  controls.addEventListener('change', update);
  for (const image of images) {
    image.addEventListener('load', updateReadiness);
    image.addEventListener('error', updateReadiness);
  }
  document.getElementById('save-sign').addEventListener('click', () => store(false));
  document.getElementById('reset-sign').addEventListener('click', () => {
    controls.reset();
    select();
    restoreOrder();
    update();
    store(true);
  });
  print.addEventListener('click', () => window.print());
  update();
})();
