(() => {
  const editor = document.querySelector('.moodboard-photo-editor');
  const cards = [...editor.querySelectorAll('.moodboard-photo-card')];
  const printButton = editor.querySelector('[data-print-photos]');
  const previewButton = editor.querySelector('[data-preview-photos]');
  const status = editor.querySelector('[data-photo-print-status]');
  const orientation = editor.querySelector('[data-print-orientation]');
  const layout = editor.querySelector('[data-print-layout]');
  const sheets = editor.querySelector('.moodboard-photo-a4');
  const choice = card => card.querySelector('[data-print-choice]');
  let printing = false;

  function arrangeSheets(selected) {
    sheets.replaceChildren();
    if (layout.value !== 'a4') return;
    for (let index = 0; index < selected.length; index += 2) {
      const sheet = document.createElement('section');
      sheet.className = 'moodboard-photo-sheet';
      sheet.setAttribute('aria-label', `Sheet ${index / 2 + 1}`);
      for (const card of selected.slice(index, index + 2)) {
        sheet.append(card.querySelector('.moodboard-photo-frame').cloneNode(true));
      }
      sheets.append(sheet);
    }
  }

  function setPreview(enabled) {
    editor.classList.toggle('is-print-preview', enabled);
    previewButton.setAttribute('aria-pressed', String(enabled));
    previewButton.textContent = enabled ? 'Back to editing' : 'Print preview';
    if (enabled) arrangeSheets(cards.filter(card => choice(card).checked));
  }

  previewButton.addEventListener('click', () => setPreview(previewButton.getAttribute('aria-pressed') === 'false'));

  function updateSelection() {
    const selected = cards.filter(card => {
      const included = choice(card).checked;
      card.classList.toggle('is-selected', included);
      return included;
    });
    printButton.disabled = printing || !selected.length;
    previewButton.disabled = !selected.length;
    if (!selected.length) setPreview(false);
    const portrait = orientation.value === 'portrait';
    const a4 = layout.value === 'a4';
    editor.classList.toggle('is-portrait', portrait);
    editor.classList.toggle('is-a4', a4);
    const paper = a4 ? `A4 ${portrait ? 'landscape' : 'portrait'}` : `7 × 5 in ${orientation.value}`;
    const count = Math.ceil(selected.length / (a4 ? 2 : 1));
    status.textContent = `${selected.length} selected · ${count} ${count === 1 ? 'sheet' : 'sheets'} · ${paper}`;
    if (editor.classList.contains('is-print-preview')) arrangeSheets(selected);
    return selected;
  }

  orientation.addEventListener('change', updateSelection);
  layout.addEventListener('change', updateSelection);
  window.addEventListener('beforeprint', () => {
    if (!printing) arrangeSheets(cards.filter(card => choice(card).checked));
  });

  for (const card of cards) {
    const form = card.querySelector('form');
    const image = card.querySelector('img');
    const frame = () => {
      const { fit, zoom, x, y } = form.elements;
      image.style.objectFit = fit.value;
      image.style.transform = `translate(${x.value}%, ${y.value}%) scale(${zoom.value / 100})`;
    };
    form.addEventListener('input', frame);
    form.addEventListener('reset', () => requestAnimationFrame(frame));
    choice(card).addEventListener('change', updateSelection);
    frame();
  }

  editor.querySelectorAll('[data-photo-select]').forEach(button => {
    button.disabled = !cards.length;
    button.addEventListener('click', () => {
      for (const card of cards) choice(card).checked = button.dataset.photoSelect === 'all';
      updateSelection();
    });
  });

  printButton.addEventListener('click', async () => {
    if (printButton.disabled) return;
    const selected = updateSelection();
    const layoutAtClick = layout.value;
    const orientationAtClick = orientation.value;
    printing = true;
    printButton.disabled = true;
    try {
      await Promise.all(selected.map(card => card.querySelector('img').decode()));
      arrangeSheets(selected);
      await Promise.all([...sheets.querySelectorAll('img')].map(image => image.decode()));
      const current = cards.filter(card => choice(card).checked);
      if (layout.value !== layoutAtClick || orientation.value !== orientationAtClick ||
          current.length !== selected.length || current.some((card, index) => card !== selected[index])) {
        updateSelection();
        return;
      }
      window.print();
    } catch {
      status.textContent = 'One or more selected photos could not load. Check the previews before printing.';
    } finally {
      printing = false;
      printButton.disabled = !cards.some(card => choice(card).checked);
    }
  });
  updateSelection();
})();
