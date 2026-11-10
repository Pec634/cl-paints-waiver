(() => {
  document.querySelectorAll('[data-participant-photo]').forEach(control => {
    if (control.dataset.initialized) return;
    control.dataset.initialized = 'true';
    const dialog = control.querySelector('dialog');
    const form = control.querySelector('[data-photo-form]');
    const input = control.querySelector('[data-photo-input]');
    const camera = control.querySelector('[data-photo-camera-input]');
    const preview = control.querySelector('[data-photo-preview]');
    const status = control.querySelector('[data-photo-status]');
    const save = control.querySelector('[data-photo-save]');
    const opener = control.querySelector('[data-photo-open]');
    let previewUrl;
    function clearPreview() {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = null;
      preview.removeAttribute('src');
      preview.hidden = true;
    }
    function selected() {
      clearPreview();
      input.setCustomValidity('');
      const file = input.files[0];
      if (!file) { status.textContent = ''; return; }
      if (file.size > 10000000) {
        input.setCustomValidity('Choose a photograph under 10 MB.');
        status.textContent = input.validationMessage;
        return;
      }
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
      status.textContent = `${file.name} selected. Review it, then save.`;
    }
    opener.addEventListener('click', () => {
      if (typeof dialog.showModal !== 'function') {
        location.href = control.querySelector('a').href + '?upload=1';
        return;
      }
      dialog.showModal();
    });
    control.querySelector('[data-photo-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
      form.reset();
      clearPreview();
      input.setCustomValidity('');
      status.textContent = '';
      save.disabled = false;
      save.textContent = 'Save photo';
      opener.focus();
    });
    control.querySelector('[data-photo-device]').addEventListener('click', () => input.click());
    control.querySelector('[data-photo-camera]').addEventListener('click', () => camera.click());
    camera.addEventListener('change', () => {
      if (!camera.files.length) return;
      try {
        const files = new DataTransfer();
        files.items.add(camera.files[0]);
        input.files = files.files;
        selected();
      } catch (_) {
        status.textContent = 'Please select your saved photo using Choose from device.';
      }
    });
    input.addEventListener('change', selected);
    preview.addEventListener('error', () => {
      preview.hidden = true;
      status.textContent = 'A preview is unavailable. Save to check the file, or choose a JPG, PNG or WebP photograph.';
    });
    form.addEventListener('submit', () => {
      save.disabled = true;
      save.textContent = 'Saving photo…';
      status.textContent = 'Uploading your photograph. Please keep this page open.';
    });
  });
})();
