(() => {
  const controls = document.getElementById('sign-controls');
  const sign = document.getElementById('loyalty-sign');
  const status = document.getElementById('editor-status');
  const print = document.getElementById('print-sign');
  const qr = document.getElementById('sign-qr');
  const key = `cl-loyalty-sign-v1-${document.body.dataset.eventId}`;
  const fields = ['heading', 'reward', 'instructions', 'footer', 'paper', 'orientation', 'theme', 'headingSize', 'qrSize', 'logo'];
  const choices = {paper: ['A4', 'A5'], orientation: ['portrait', 'landscape'], theme: ['simple', 'brand'], headingSize: ['small', 'medium', 'large'], qrSize: ['small', 'medium', 'large']};
  let qrReady = false;
  function update() {
    sign.querySelectorAll('[data-sign-text]').forEach(node => {
      node.textContent = controls.elements[node.dataset.signText].value;
    });
    for (const name of Object.keys(choices)) sign.dataset[name] = controls.elements[name].value;
    document.getElementById('sign-logo').hidden = !controls.elements.logo.checked;
    document.getElementById('print-page-size').textContent = `@page{size:${controls.elements.paper.value} ${controls.elements.orientation.value};margin:0}`;
  }
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (saved && typeof saved === 'object') {
      for (const name of fields) {
        const field = controls.elements[name];
        if (name === 'logo') field.checked = saved[name] === true;
        else if (choices[name]) {
          if (choices[name].includes(saved[name])) field.value = saved[name];
        } else if (typeof saved[name] === 'string') field.value = saved[name].slice(0, field.maxLength);
      }
    }
  } catch (_) { status.textContent = 'Browser storage is unavailable. You can still edit and print.'; }
  controls.addEventListener('submit', event => event.preventDefault());
  controls.addEventListener('input', update);
  controls.addEventListener('change', update);
  document.getElementById('save-sign').addEventListener('click', () => {
    const saved = {};
    for (const name of fields) saved[name] = name === 'logo' ? controls.elements[name].checked : controls.elements[name].value;
    try {
      localStorage.setItem(key, JSON.stringify(saved));
      status.textContent = 'Design saved for this event on this device.';
    } catch (_) { status.textContent = 'Could not save on this device. You can still print or save as PDF.'; }
  });
  document.getElementById('reset-sign').addEventListener('click', () => {
    controls.reset();
    update();
    try { localStorage.removeItem(key); } catch (_) { /* Editing and printing remain available. */ }
    status.textContent = 'Default design restored.';
  });
  print.addEventListener('click', () => { if (qrReady) window.print(); });
  function ready() {
    qrReady = true;
    print.disabled = false;
    status.textContent = 'Ready to print. Choose Save as PDF in the print window to download.';
  }
  qr.addEventListener('load', ready);
  qr.addEventListener('error', () => {
    qrReady = false;
    print.disabled = true;
    status.textContent = 'The event QR code could not load. Reload this page before printing.';
  });
  update();
  if (qr.complete && qr.naturalWidth > 0) ready();
})();
