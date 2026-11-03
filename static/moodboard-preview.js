(() => {
  const dialog = document.getElementById('design-preview');
  if (!dialog) return;
  document.querySelectorAll('[data-preview-src]').forEach(button => button.addEventListener('click', () => {
    document.getElementById('design-preview-title').textContent = button.dataset.previewLabel;
    const image = document.getElementById('design-preview-image');
    image.src = button.dataset.previewSrc; image.alt = button.dataset.previewLabel;
    dialog.showModal();
  }));
  document.getElementById('close-design-preview').addEventListener('click', () => dialog.close());
})();
