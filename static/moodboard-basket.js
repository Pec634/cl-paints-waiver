(() => {
  const basket = document.getElementById('moodboard-basket');
  if (!basket) return;
  const total = document.getElementById('basket-total');
  const message = document.getElementById('basket-message');
  const review = document.getElementById('review-basket');
  const fields = Array.from(basket.querySelectorAll('[data-price]'));
  const storageKey = `cl-moodboard-basket-v1-${basket.action}`;
  const quantity = input => Math.max(0, Math.min(20, Math.floor(Number(input.value) || 0)));
  const update = () => {
    let count = 0, pennies = 0;
    const saved = {};
    fields.forEach(input => {
      const value = quantity(input);
      count += value;
      pennies += value * Math.round(Number(input.dataset.price) * 100);
      saved[input.name] = value;
      const card = input.closest('[data-design-card]');
      card.classList.toggle('is-selected', value > 0);
      const badge = card.querySelector('.quantity-badge');
      badge.hidden = value === 0;
      badge.textContent = `\u00d7${value}`;
      card.querySelectorAll('[data-adjust-design]').forEach(button => {
        button.disabled = Number(button.dataset.step) < 0 ? value === 0 : value >= 20;
      });
    });
    if (total) total.textContent = `${count} paints \u00b7 \u00a3${(pennies / 100).toFixed(2)}`;
    if (message) message.textContent = count > 50 ? 'Choose up to 50 paints in one order.' : '';
    if (review) review.disabled = count === 0 || count > 50 || pennies === 0;
    try { sessionStorage.setItem(storageKey, JSON.stringify(saved)); } catch (_) { /* Basket still works. */ }
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    fields.forEach(input => {
      if (Number.isInteger(saved[input.name]) && saved[input.name] >= 0 && saved[input.name] <= 20) input.value = saved[input.name];
    });
  } catch (_) { /* Storage is optional. */ }
  basket.addEventListener('input', update);
  basket.addEventListener('change', event => {
    if (event.target.matches('[data-price]')) { event.target.value = quantity(event.target); update(); }
  });
  basket.querySelectorAll('[data-add-design], [data-adjust-design]').forEach(button => {
    button.addEventListener('click', () => {
      const input = basket.elements.namedItem(button.dataset.addDesign || button.dataset.adjustDesign);
      if (!input) return;
      input.value = Math.max(0, Math.min(20, quantity(input) + Number(button.dataset.step || 1)));
      update();
    });
  });
  basket.addEventListener('submit', () => fields.forEach(input => { input.value = quantity(input); }));
  const dialog = document.getElementById('design-preview');
  const previewImage = document.getElementById('design-preview-image');
  const previewTitle = document.getElementById('design-preview-title');
  let opener;
  basket.querySelectorAll('[data-preview-src]').forEach(button => {
    button.addEventListener('click', () => {
      opener = button;
      previewImage.src = button.dataset.previewSrc;
      previewImage.alt = button.dataset.previewLabel;
      previewTitle.textContent = button.dataset.previewLabel;
      dialog.showModal();
    });
  });
  document.getElementById('close-design-preview')?.addEventListener('click', () => dialog.close());
  dialog?.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog?.addEventListener('close', () => opener?.focus());
  update();
})();
