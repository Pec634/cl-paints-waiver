(() => {
  const controls = document.getElementById('moodboard-sheet-controls');
  const status = document.getElementById('editor-status');
  const print = document.getElementById('print-sign');
  const printPageSize = document.getElementById('print-page-size');
  const orientation = controls.elements.namedItem('orientation');
  const preview = document.querySelector('.moodboard-sheet-preview');
  const sheets = [...preview.querySelectorAll('[data-sheet]')];
  const layoutStatus = document.getElementById('moodboard-layout-status');
  const grids = sheets.map(sheet => sheet.querySelector('.moodboard-sheet-grid'));
  const defaultTiles = grids.map(grid => [...grid.querySelectorAll('[data-design-id]')]);
  const designs = new Map(defaultTiles.flat().map(tile => [tile.dataset.designId, tile.querySelector('img')]));
  const images = [...preview.querySelectorAll('img')];
  const sizeProbe = preview.querySelector('.moodboard-size-probe span');
  const sizeLabel = document.getElementById('moodboard-image-size');
  const undo = document.getElementById('moodboard-undo');
  const redo = document.getElementById('moodboard-redo');
  const togglePreview = document.getElementById('toggle-print-preview');
  const previewPrint = document.getElementById('print-from-preview');
  const history = [];
  let historyIndex = -1;
  let crops = {};
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
    recordChange();
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
    previewPrint.disabled = print.disabled;
    status.textContent = failed ? 'A printable image could not load. Reload the editor to try again.'
      : loading ? 'Loading printable images…'
      : 'Ready to print both A4 sheets.';
  }

  function update() {
    const landscape = orientation.value === 'landscape';
    preview.dataset.orientation = orientation.value;
    printPageSize.textContent = `@page{size:A4 ${orientation.value};margin:0}`;
    let widestGrid = 1;
    let tallestGrid = 1;
    let hasQr = false;
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
      const rows = Math.max(1, Math.ceil(count / columns));
      grid.style.setProperty('--columns', columns);
      grid.style.setProperty('--rows', rows);
      if (count) {
        widestGrid = Math.max(widestGrid, columns);
        tallestGrid = Math.max(tallestGrid, rows);
        hasQr ||= !codes.hidden;
      }
    }
    preview.style.setProperty('--widest-grid', widestGrid);
    preview.style.setProperty('--tallest-grid', tallestGrid);
    preview.toggleAttribute('data-has-grid-qr', hasQr);
    const mm = (sizeProbe.getBoundingClientRect().width * 25.4 / 96).toFixed(1);
    sizeLabel.textContent = designs.size ? `Each image prints at ${mm} × ${mm} mm.` : '';
    updateReadiness();
  }

  function store(remove) {
    try {
      if (remove) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(snapshot()));
      if (!print.disabled) status.textContent = remove ? 'Default design restored.' : 'Design saved on this device.';
    } catch (_) {
      status.textContent = 'Browser storage is unavailable.';
    }
  }

  function snapshot() {
    return {
      ...Object.fromEntries(new FormData(controls)),
      orders: grids.map(grid => [...grid.children].filter(tile => tile.dataset.designId).map(tile => tile.dataset.designId)),
      crops: {...crops},
    };
  }

  function applyCrop(image, crop = {}) {
    image.style.objectFit = crop.fit ? 'contain' : 'cover';
    image.style.objectPosition = crop.fit ? '50% 50%' : `${crop.x ?? 50}% ${crop.y ?? 50}%`;
  }

  function applyState(saved) {
    orientation.value = saved.orientation === 'landscape' ? 'landscape' : 'portrait';
    for (const field of controls.querySelectorAll('[data-page]')) {
      if (field.type === 'checkbox') field.checked = saved[field.name] === 'on';
      else field.selectedIndex = Math.max(0, [...field.options].findIndex(option => option.value === saved[field.name]));
    }
    restoreOrder(saved.orders);
    crops = {};
    for (const [id, image] of designs) {
      const crop = saved.crops?.[id];
      if (crop && [crop.x, crop.y].every(value => Number.isFinite(value) && value >= 0 && value <= 100)) {
        crops[id] = {x: crop.x, y: crop.y, fit: crop.fit === true};
      }
      applyCrop(image, crops[id]);
    }
  }

  function updateHistoryButtons() {
    undo.disabled = historyIndex <= 0;
    redo.disabled = historyIndex >= history.length - 1;
  }

  function recordChange() {
    const state = snapshot();
    if (JSON.stringify(state) === JSON.stringify(history[historyIndex])) return;
    history.splice(historyIndex + 1, history.length, state);
    if (history.length > 51) history.shift();
    historyIndex = history.length - 1;
    updateHistoryButtons();
  }

  function restoreHistory(offset) {
    select();
    historyIndex += offset;
    applyState(history[historyIndex]);
    update();
    updateHistoryButtons();
    if (!print.disabled) status.textContent = offset < 0 ? 'Change undone.' : 'Change redone.';
  }

  try {
    applyState(JSON.parse(localStorage.getItem(key) || '{}') || {});
  } catch (_) { /* The editor can run without a saved design. */ }
  recordChange();

  undo.addEventListener('click', () => restoreHistory(-1));
  redo.addEventListener('click', () => restoreHistory(1));
  togglePreview.addEventListener('click', () => {
    select();
    const clean = preview.parentElement.toggleAttribute('data-clean-preview');
    togglePreview.setAttribute('aria-pressed', String(clean));
    togglePreview.textContent = clean ? 'Back to editing' : 'Clean print preview';
    previewPrint.hidden = !clean;
  });
  previewPrint.addEventListener('click', () => window.print());

  const cropDialog = document.getElementById('moodboard-crop-dialog');
  if (cropDialog) {
    const cropForm = cropDialog.querySelector('form');
    const cropImage = cropDialog.querySelector('img');
    const designSelect = document.getElementById('moodboard-crop-design');
    const {x, y, fit} = cropForm.elements;
    let editingId;
    let pan;

    function readCrop() {
      return {x: Number(x.value), y: Number(y.value), fit: fit.checked};
    }

    function updateCropPreview() {
      x.disabled = y.disabled = fit.checked;
      applyCrop(cropImage, readCrop());
    }

    document.getElementById('moodboard-open-crop').addEventListener('click', () => {
      editingId = designSelect.value;
      const image = designs.get(editingId);
      const crop = crops[editingId] || {x: 50, y: 50, fit: false};
      x.value = crop.x;
      y.value = crop.y;
      fit.checked = crop.fit;
      cropImage.src = image.currentSrc || image.src;
      cropImage.alt = image.alt;
      updateCropPreview();
      cropDialog.showModal();
    });
    document.getElementById('moodboard-cancel-crop').addEventListener('click', () => cropDialog.close());
    cropForm.addEventListener('input', updateCropPreview);
    cropForm.addEventListener('submit', () => {
      const crop = readCrop();
      if (crop.x === 50 && crop.y === 50 && !crop.fit) delete crops[editingId];
      else crops[editingId] = crop;
      applyCrop(designs.get(editingId), crop);
      recordChange();
    });
    cropImage.addEventListener('pointerdown', event => {
      if (fit.checked || event.button !== 0 || !cropImage.naturalWidth) return;
      const rect = cropImage.getBoundingClientRect();
      const scale = Math.max(rect.width / cropImage.naturalWidth, rect.height / cropImage.naturalHeight);
      pan = {pointer: event.pointerId, startX: event.clientX, startY: event.clientY, crop: readCrop(),
        overflowX: cropImage.naturalWidth * scale - rect.width,
        overflowY: cropImage.naturalHeight * scale - rect.height};
      cropImage.setPointerCapture(event.pointerId);
    });
    cropImage.addEventListener('pointermove', event => {
      if (pan?.pointer !== event.pointerId) return;
      const position = (start, delta, overflow) => Math.max(0, Math.min(100, start - delta * 100 / overflow));
      if (pan.overflowX > 1) x.value = position(pan.crop.x, event.clientX - pan.startX, pan.overflowX);
      if (pan.overflowY > 1) y.value = position(pan.crop.y, event.clientY - pan.startY, pan.overflowY);
      updateCropPreview();
    });
    cropImage.addEventListener('lostpointercapture', () => { pan = undefined; });
  }

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
  controls.addEventListener('change', event => {
    if (!event.target.name) return;
    update();
    recordChange();
  });
  for (const image of images) {
    image.addEventListener('load', updateReadiness);
    image.addEventListener('error', updateReadiness);
  }
  document.getElementById('save-sign').addEventListener('click', () => store(false));
  document.getElementById('reset-sign').addEventListener('click', () => {
    select();
    applyState({});
    update();
    recordChange();
    store(true);
  });
  print.addEventListener('click', () => window.print());
  update();
})();
