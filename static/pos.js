(() => {
  'use strict';
  const get = id => document.getElementById(id);
  let items = [], waiver = null;
  const storageKey = 'clpaints-pos-draft';
  const receipt = get('pos-cash-receipt');
  try {
    if (receipt && receipt.dataset.completedReference === 'POS-' + sessionStorage.getItem('clpaints-pos-submitted')) {
      sessionStorage.removeItem(storageKey);
      sessionStorage.removeItem('clpaints-pos-submitted');
    }
  } catch (_) {}
  // Keep only the current tab's unfinished basket; never store consent records.
  try {
    const draft = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (draft && Array.isArray(draft.items)) items = draft.items.filter(item =>
      typeof item.name === 'string' && Number.isInteger(item.quantity) && item.quantity > 0 &&
      Number.isInteger(item.pence) && item.pence > 0).slice(0, 50);
  } catch (_) { /* A blocked storage area must not prevent checkout. */ }
  const save = () => { try { sessionStorage.setItem(storageKey, JSON.stringify({items})); } catch (_) {} };
  const money = pence => `£${(pence / 100).toFixed(2)}`;
  const parsePrice = value => /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0 && Number(value) <= 99999 ? Math.round(Number(value) * 100) : null;
  function updateReceipt() {
    const requested = get('pos-receipt-requested').checked;
    get('pos-receipt-fields').hidden = !requested;
    get('pos-receipt-email').disabled = !requested;
    get('pos-receipt-email').required = requested;
  }
  get('pos-receipt-requested').addEventListener('change', () => {
    updateReceipt();
    if (get('pos-receipt-requested').checked) get('pos-receipt-email').focus();
  });
  function updateLoyalty(people = [], selectedId = '') {
    const fields = get('pos-loyalty-fields'), list = get('pos-loyalty-people');
    if (!fields) return;
    fields.hidden = !waiver;
    if (!list) return;
    list.replaceChildren();
    people.forEach(person => {
      const label = document.createElement('label'); label.className = 'pos-loyalty-person';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
      checkbox.name = 'loyalty_participant_id'; checkbox.value = person.value;
      checkbox.checked = Number(person.dataset.points) < 3 && (person.value === selectedId || people.length === 1);
      label.append(checkbox, document.createTextNode(`${person.textContent} · ${person.dataset.points || 0}/3 points${Number(person.dataset.points) >= 3 ? ' · Free paint ready' : ''}`));
      list.append(label);
    });
  }
  function updateCash() {
    const total = items.reduce((sum, item) => sum + item.quantity * item.pence, 0);
    const field = get('pos-cash-tender');
    const raw = field.value;
    const tender = /^\d+(\.\d{1,2})?$/.test(raw) && Number(raw) <= 999999.99 ? Math.round(Number(raw) * 100) : null;
    const valid = items.length > 0 && total <= 9999999 && tender !== null && tender >= total;
    get('pos-cash-confirm').disabled = !valid;
    get('pos-cash-cancel').disabled = false;
    get('pos-cash-change').textContent = tender === null ? 'Enter the amount received.' : tender < total ? `Still to receive: ${money(total - tender)}` : `Change to give: ${money(tender - total)}`;
    field.min = (total / 100).toFixed(2);
  }
  function closeCash() {
    get('pos-cash-panel').hidden = true;
    get('pos-cash-open').setAttribute('aria-expanded', 'false');
    get('pos-cash-tender').value = '';
    get('pos-cash-tender').disabled = true;
  }
  function addItem(item) {
    const existing = items.find(line => line.name === item.name && line.pence === item.pence);
    if (existing && existing.quantity + item.quantity <= 999) existing.quantity += item.quantity;
    else if (items.length < 50) items.push(item);
    else { get('pos-error').textContent = 'A sale can contain up to 50 lines.'; return; }
    get('pos-error').textContent = '';
    render();
    if (get('pos-library-status')) get('pos-library-status').textContent = `${item.name} added to basket.`;
  }
  function render() {
    get('pos-basket').replaceChildren();
    get('pos-clear-basket').disabled = items.length === 0;
    let total = 0;
    items.forEach((item, index) => {
      total += item.quantity * item.pence;
      const row = document.createElement('li');
      row.append(document.createTextNode(`${item.quantity} × ${item.name} · ${money(item.quantity * item.pence)} `));
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${item.name}`);
      remove.onclick = () => { items.splice(index, 1); render(); };
      row.append(remove);
      const fields = document.createElement('div'); fields.className = 'pos-fields';
      const quantityLabel = document.createElement('label'); quantityLabel.textContent = 'Quantity';
      const quantity = document.createElement('input'); quantity.type = 'number'; quantity.min = '1'; quantity.max = '999'; quantity.step = '1'; quantity.value = item.quantity;
      quantity.setAttribute('aria-label', `Quantity for ${item.name}`);
      quantity.addEventListener('change', () => {
        const value = Number(quantity.value);
        if (!Number.isInteger(value) || value < 1 || value > 999) { quantity.value = item.quantity; get('pos-error').textContent = 'Quantity must be a whole number from 1 to 999.'; return; }
        item.quantity = value; get('pos-error').textContent = ''; render();
      });
      const priceLabel = document.createElement('label'); priceLabel.textContent = 'Unit price (£)';
      const price = document.createElement('input'); price.type = 'number'; price.min = '0.01'; price.max = '99999'; price.step = '0.01'; price.inputMode = 'decimal'; price.value = (item.pence / 100).toFixed(2);
      price.setAttribute('aria-label', `Unit price for ${item.name}`);
      price.addEventListener('change', () => {
        const value = parsePrice(price.value);
        if (value === null) { price.value = (item.pence / 100).toFixed(2); get('pos-error').textContent = 'Enter a positive price with up to two decimal places.'; return; }
        item.pence = value; get('pos-error').textContent = ''; render();
      });
      quantityLabel.append(quantity); priceLabel.append(price); fields.append(quantityLabel, priceLabel);
      row.append(fields); get('pos-basket').append(row);
    });
    get('pos-total').textContent = `Total ${money(total)}`;
    get('pos-items').value = JSON.stringify(items.map(i => ({name:i.name, quantity:i.quantity, price:(i.pence / 100).toFixed(2)})));
    get('pos-waiver-id').value = waiver ? waiver.id : '';
    get('pos-participant-id').value = waiver?.participantId || '';
    get('pos-linked').textContent = waiver ? `Linked: ${waiver.label}${waiver.participantName ? ' · ' + waiver.participantName : ''}` : 'No waiver linked';
    get('pos-waiver-selection').textContent = waiver ? `${get('pos-linked').textContent} — open to change` : '';
    get('pos-waiver-selection').hidden = !waiver;
    get('pos-checkout').querySelectorAll('button').forEach(button => { button.disabled = !items.length || total > 9999999 || button.dataset.unconfigured === 'true'; });
    if (!items.length) closeCash();
    updateCash();
    save();
  }
  get('pos-add-item').addEventListener('submit', event => {
    event.preventDefault();
    const name = get('pos-item-name').value.trim(), quantity = Number(get('pos-item-quantity').value);
    const price = get('pos-item-price').value;
    if (!name || !Number.isInteger(quantity) || quantity < 1 || quantity > 999 ||
        !/^\d+(\.\d{1,2})?$/.test(price) || Number(price) <= 0 || Number(price) > 99999 || items.length >= 50) {
      get('pos-error').textContent = 'Check the item name, quantity and price. A sale can contain up to 50 lines.'; return;
    }
    addItem({name, quantity, pence:Math.round(Number(price) * 100)});
    get('pos-error').textContent = ''; get('pos-add-item').reset(); render(); get('pos-item-name').focus();
  });
  const products = [...document.querySelectorAll('[data-product-id]')];
  products.forEach(button => button.addEventListener('click', () => {
    const pence = parsePrice(button.dataset.productPrice);
    if (pence !== null) addItem({name: button.dataset.productName, quantity: 1, pence});
  }));
  get('pos-library-search')?.addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    products.forEach(button => { button.hidden = !button.dataset.productName.toLowerCase().includes(query); });
    get('pos-library-status').textContent = `${products.filter(button => !button.hidden).length} items shown`;
  });
  const waiverResults = get('pos-waiver-results');
  waiverResults.addEventListener('click', event => {
    const button = event.target.closest('button[data-waiver-id]');
    if (!button || !waiverResults.contains(button)) return;
    const participant = button.closest('.pos-waiver')?.querySelector('.pos-participant');
    waiver = {id:button.dataset.waiverId, label:button.dataset.waiverLabel,
      participantId:participant?.value || '', participantName:participant?.value ? participant.selectedOptions[0].textContent : ''}; render();
    updateLoyalty(participant ? [...participant.options].filter(option => option.value) : [], participant?.value || '');
    const receiptEmail = get('pos-receipt-email');
    if (!receiptEmail.value || receiptEmail.value === receiptEmail.dataset.prefilled) {
      receiptEmail.value = button.dataset.waiverEmail || '';
      receiptEmail.dataset.prefilled = receiptEmail.value;
    }
    get('pos-waiver-fold').open = false;
    get('pos-waiver-summary').focus();
  });
  waiverResults.addEventListener('change', event => {
    const select = event.target.closest('.pos-participant');
    if (!select) return;
    const button = select.closest('.pos-waiver').querySelector('[data-waiver-id]');
    if (waiver?.id === button.dataset.waiverId) button.click();
  });
  const searchForm = get('pos-search'), searchInput = get('pos-query');
  const searchStatus = get('pos-waiver-search-status');
  let searchTimer, searchController, searchVersion = 0;
  async function searchWaivers(version) {
    const query = searchInput.value.trim();
    if (!query) {
      waiverResults.replaceChildren();
      searchStatus.textContent = 'Start typing a name, email or waiver reference.';
      waiverResults.removeAttribute('aria-busy');
      return;
    }
    searchController = new AbortController();
    searchStatus.textContent = 'Searching waivers…';
    waiverResults.setAttribute('aria-busy', 'true');
    try {
      const url = new URL(searchForm.dataset.searchUrl, location.href);
      url.searchParams.set('q', query);
      const response = await fetch(url, {signal:searchController.signal, credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok || response.redirected) throw new Error('Search unavailable');
      const data = await response.json();
      if (version !== searchVersion) return;
      if (typeof data.html !== 'string' || !Number.isInteger(data.count)) throw new Error('Invalid search response');
      waiverResults.innerHTML = data.html;
      waiverResults.scrollTop = 0;
      searchStatus.textContent = `${data.count === 30 ? 'Showing the latest ' : ''}${data.count} matching waiver${data.count === 1 ? '' : 's'}.`;
    } catch (error) {
      if (version !== searchVersion || error.name === 'AbortError') return;
      waiverResults.replaceChildren();
      searchStatus.textContent = 'Could not update waiver results. Check your connection or sign-in, then try Search again.';
    } finally {
      if (version === searchVersion) waiverResults.removeAttribute('aria-busy');
    }
  }
  function queueWaiverSearch(immediate = false) {
    clearTimeout(searchTimer);
    searchController?.abort();
    const version = ++searchVersion;
    if (immediate || !searchInput.value.trim()) searchWaivers(version);
    else searchTimer = setTimeout(() => searchWaivers(version), 200);
  }
  searchInput.addEventListener('input', event => { if (!event.isComposing) queueWaiverSearch(); });
  searchInput.addEventListener('compositionend', () => queueWaiverSearch());
  searchForm.addEventListener('submit', event => { event.preventDefault(); queueWaiverSearch(true); });
  get('pos-clear-waiver').onclick = () => {
    waiver = null;
    const receiptEmail = get('pos-receipt-email');
    if (receiptEmail.value === receiptEmail.dataset.prefilled) receiptEmail.value = '';
    delete receiptEmail.dataset.prefilled;
    render();
    updateLoyalty();
    get('pos-waiver-fold').open = true;
    get('pos-query').focus();
  };
  get('pos-clear-basket').onclick = () => {
    items = [];
    get('pos-error').textContent = '';
    render();
    if (get('pos-library-status')) get('pos-library-status').textContent = 'Basket cleared.';
  };
  get('pos-cash-open').onclick = () => {
    get('pos-cash-panel').hidden = false;
    get('pos-cash-open').setAttribute('aria-expanded', 'true');
    get('pos-cash-tender').disabled = false;
    updateCash();
    get('pos-cash-tender').focus();
  };
  get('pos-cash-tender').addEventListener('input', updateCash);
  get('pos-cash-cancel').onclick = () => { closeCash(); get('pos-cash-open').focus(); };
  get('pos-checkout').addEventListener('submit', event => {
    const eventField = get('pos-loyalty-event');
    if (eventField) {
      eventField.required = !!document.querySelector('input[name=loyalty_participant_id]:checked');
      if (!eventField.reportValidity()) { event.preventDefault(); return; }
    }
    if (get('pos-receipt-requested').checked && !get('pos-receipt-email').reportValidity()) {
      event.preventDefault(); return;
    }
    if (event.submitter?.value === 'Cash') {
      updateCash();
      if (get('pos-cash-panel').hidden || get('pos-cash-confirm').disabled) { event.preventDefault(); return; }
    }
    // Remove the draft only when a sale page is reached, so failed submissions can recover.
    try { sessionStorage.setItem('clpaints-pos-submitted', get('pos-checkout').elements.sale_token.value); } catch (_) {}
  });
  updateReceipt();
  render();
})();
