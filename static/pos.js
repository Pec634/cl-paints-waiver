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
  if (receipt) {
    const next = get('pos-next-sale');
    const confirmation = document.createElement('dialog');
    confirmation.className = 'pos-sale-confirmation';
    confirmation.setAttribute('aria-label', 'Sale confirmation');
    if (typeof confirmation.showModal === 'function') {
      receipt.before(confirmation);
      confirmation.append(receipt);
      confirmation.showModal();
    }
    const dismiss = () => {
      if (confirmation.open) confirmation.close();
      receipt.hidden = true;
      history.replaceState(history.state, '', next.href);
      document.dispatchEvent(new Event('pos-basket-close'));
    };
    const timer = setTimeout(dismiss, 30000);
    confirmation.addEventListener('cancel', event => {
      event.preventDefault();
      clearTimeout(timer);
      dismiss();
    });
    next.addEventListener('click', event => {
      event.preventDefault();
      clearTimeout(timer);
      dismiss();
    });
  }
  // Keep only the current tab's unfinished basket; never store consent records.
  try {
    const draft = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (draft && Array.isArray(draft.items)) items = draft.items.filter(item =>
      typeof item.name === 'string' && Number.isInteger(item.quantity) && item.quantity > 0 &&
      Number.isInteger(item.pence) && item.pence > 0).slice(0, 50);
    if (typeof draft?.saleToken==='string' && /^[A-Za-z0-9_-]{20,50}$/.test(draft.saleToken)) {
      get('pos-checkout').elements.sale_token.value=draft.saleToken;
    }
  } catch (_) { /* A blocked storage area must not prevent checkout. */ }
  const save = () => { try { sessionStorage.setItem(storageKey, JSON.stringify({items,saleToken:get('pos-checkout').elements.sale_token.value})); } catch (_) {} };
  const money = pence => `£${(pence / 100).toFixed(2)}`;
  const parsePrice = value => /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0 && Number(value) <= 99999 ? Math.round(Number(value) * 100) : null;
  function updateSaleOptions() {
    const selectedEvent = get('pos-trading-event');
    const recipients = document.querySelectorAll('input[name=loyalty_participant_id]:checked').length;
    const summary = [selectedEvent?.value ? selectedEvent.selectedOptions[0].textContent : 'Daily till'];
    if (waiver) summary.push(`${recipients} loyalty recipient${recipients === 1 ? '' : 's'}`);
    summary.push(get('pos-receipt-requested').checked ? 'Email receipt requested' : 'No email receipt');
    get('pos-options-summary').textContent = summary.join(' · ');
  }
  function updateReceipt() {
    const requested = get('pos-receipt-requested').checked;
    get('pos-receipt-fields').hidden = !requested;
    get('pos-receipt-email').disabled = !requested;
    get('pos-receipt-email').required = requested;
    if (requested) get('pos-sale-options').open = true;
    updateSaleOptions();
  }
  get('pos-receipt-requested').addEventListener('change', () => {
    updateReceipt();
    if (get('pos-receipt-requested').checked) get('pos-receipt-email').focus();
  });
  function updateLoyalty(people = [], selectedId = '') {
    const fields = get('pos-loyalty-fields'), list = get('pos-loyalty-people');
    if (!fields) return;
    fields.hidden = !waiver;
    if (waiver) get('pos-sale-options').open = true;
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
    updateSaleOptions();
  }
  function rewardDiscount() {
    const person = waiver?.people?.find(person => String(person.id) === waiver.participantId);
    if (Number(person?.points) !== 3) return 0;
    const line = items.find(item => {
      const product = products.find(button => Number(button.dataset.productId) === item.product_id);
      return product?.dataset.loyaltyReward === 'true' && parsePrice(product.dataset.productPrice) === item.pence;
    });
    return line?.pence || 0;
  }
  const amountDue = () => items.reduce((sum, item) => sum + item.quantity * item.pence, 0) - rewardDiscount();
  function updateCash() {
    const total = amountDue();
    const field = get('pos-cash-tender');
    const raw = field.value;
    const tender = /^\d+(\.\d{1,2})?$/.test(raw) && Number(raw) <= 999999.99 ? Math.round(Number(raw) * 100) : null;
    const valid = items.length > 0 && total <= 9999999 && tender !== null && tender >= total;
    get('pos-cash-confirm').disabled = !valid;
    get('pos-cash-cancel').disabled = false;
    get('pos-cash-change').textContent = tender === null ? 'Enter the amount received.' : tender < total ? `Still to receive: ${money(total - tender)}` : `Change to give: ${money(tender - total)}`;
  }
  function closeCash() {
    get('pos-cash-panel').hidden = true;
    get('pos-cash-open').setAttribute('aria-expanded', 'false');
    get('pos-cash-tender').value = '';
    get('pos-cash-tender').disabled = true;
  }
  function addItem(item) {
    const existing = items.find(line => line.name === item.name && line.pence === item.pence && line.product_id === item.product_id);
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
    if (get('pos-hold-basket')) get('pos-hold-basket').disabled = !items.length;
    let total = 0;
    items.forEach((item, index) => {
      total += item.quantity * item.pence;
      const row = document.createElement('li');
      const heading = document.createElement('div'); heading.className = 'pos-line-heading';
      const name = document.createElement('strong'); name.textContent = item.name;
      const lineTotal = document.createElement('span'); lineTotal.textContent = money(item.quantity * item.pence);
      heading.append(name, lineTotal);
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${item.name}`);
      remove.onclick = () => { items.splice(index, 1); render(); };
      heading.append(remove); row.append(heading);
      const fields = document.createElement('div'); fields.className = 'pos-fields';
      const quantityLabel = document.createElement('label'); quantityLabel.textContent = 'Quantity';
      const quantity = document.createElement('input'); quantity.type = 'number'; quantity.min = '1'; quantity.max = '999'; quantity.step = '1'; quantity.value = item.quantity;
      quantity.setAttribute('aria-label', `Quantity for ${item.name}`);
      quantity.addEventListener('change', () => {
        const value = Number(quantity.value);
        if (!Number.isInteger(value) || value < 1 || value > 999) { quantity.value = item.quantity; get('pos-error').textContent = 'Quantity must be a whole number from 1 to 999.'; return; }
        item.quantity = value; get('pos-error').textContent = ''; render();
      });
      const unitPrice = document.createElement('p');
      unitPrice.className = 'pos-unit-price';
      unitPrice.textContent = `Unit price: ${money(item.pence)}`;
      const stepper = document.createElement('div'); stepper.className = 'pos-quantity-stepper';
      const stepButton = (delta, text) => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = text;
        button.dataset.quantityStep = String(delta);
        button.setAttribute('aria-label', `${delta < 0 ? 'Decrease' : 'Increase'} quantity for ${item.name}`);
        button.disabled = delta < 0 ? item.quantity <= 1 : item.quantity >= 999;
        button.onclick = () => {
          item.quantity += delta; render();
          const next = get('pos-basket').children[index]?.querySelector(`[data-quantity-step="${delta}"]`);
          if (next && !next.disabled) next.focus();
          else get('pos-basket').children[index]?.querySelector('input').focus();
        };
        return button;
      };
      stepper.append(stepButton(-1, '−'), quantity, stepButton(1, '+'));
      quantityLabel.append(stepper); fields.append(quantityLabel, unitPrice);
      row.append(fields); get('pos-basket').append(row);
    });
    const discount = rewardDiscount();
    total -= discount;
    get('pos-reward-discount').value = String(discount);
    const rewardSummary = get('pos-reward-summary');
    rewardSummary.hidden = !discount;
    rewardSummary.textContent = discount ? `Free face paint for ${waiver.participantName} · ${money(discount)} off` : '';
    const freeSale = !!discount && !total;
    get('pos-total').textContent = `Total ${money(total)}`;
    if(get('pos-mobile-basket-count')){
      const count=items.reduce((sum,item)=>sum+item.quantity,0);
      get('pos-mobile-basket-count').textContent=count;
      get('pos-mobile-basket-total').textContent=money(total);
      get('pos-mobile-basket-toggle').setAttribute('aria-label',`Basket: ${count} items, total ${money(total)}`);
    }
    get('pos-items').value = JSON.stringify(items.map(i => ({name:i.name, quantity:i.quantity, price:(i.pence / 100).toFixed(2), ...(i.product_id ? {product_id:i.product_id} : {}), ...(i.variation ? {variation:i.variation} : {})})));
    get('pos-waiver-id').value = waiver ? waiver.id : '';
    get('pos-participant-id').value = waiver?.participantId || '';
    get('pos-linked').textContent = waiver ? `Linked: ${waiver.label}${waiver.participantName ? ' · ' + waiver.participantName : ''}` : 'No waiver linked';
    get('pos-waiver-selection').textContent = waiver ? `${get('pos-linked').textContent} — open to change` : '';
    get('pos-waiver-selection').hidden = !waiver;
    get('pos-clear-waiver').disabled = !waiver;
    document.querySelectorAll('[data-product-id]').forEach(button => {
      const count = items.filter(item => item.product_id === Number(button.dataset.productId)).reduce((sum,item) => sum + item.quantity, 0);
      button.dataset.basketQuantity = String(count);
      button.setAttribute('aria-label', `${button.dataset.productName}, £${button.dataset.productPrice}${count ? `, ${count} in basket` : ''}`);
    });
    document.dispatchEvent(new CustomEvent('pos-basket-updated', {detail:{waiver:waiver?.label || ''}}));
    for (const control of get('pos-checkout').elements) {
      if (control.tagName === 'BUTTON') control.disabled = !items.length || total > 9999999 || control.dataset.unconfigured === 'true';
    }
    get('pos-reward-complete').hidden = !freeSale;
    get('pos-cash-open').hidden = freeSale;
    if (freeSale) closeCash();
    const card=get('pos-card-pay');
    if(card){
      card.hidden = freeSale;
      get('pos-card-status').hidden = freeSale;
      card.classList.toggle('pos-card-ready',!card.disabled);
      card.textContent=card.dataset.unconfigured==='true' ? 'Card setup required' : 'Pay with Solo Lite';
      get('pos-card-status').textContent=card.dataset.unconfigured==='true' ? 'Card payment unavailable: SumUp setup is incomplete on the website server.' :
        !items.length ? 'Add an item to enable card payment.' : total>9999999 ? 'The basket exceeds the maximum sale amount.' : 'Card payment is ready. SumUp will open on this Android device.';
    }
    if (!items.length) closeCash();
    updateCash();
    updateSaleOptions();
    save();
  }
  get('pos-add-item')?.addEventListener('submit', event => {
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
  const library = get('pos-library');
  library.querySelector('[data-pos-open-on-load]')?.showModal();
  const orderForm = get('pos-tile-order-form');
  const batchForm = get('pos-batch-editor');
  const pendingEdits = new Map();
  const variationColourEditors = new Map();
  const colourPalettes = new WeakMap();
  const colourDialog = get('pos-colour-dialog');
  const validColour = value => /^#[0-9a-f]{6}$/i.test(value);
  function setColourValue(select, value) {
    if (validColour(value) && ![...select.options].some(option => option.value === value)) {
      select.add(new Option(value, value));
    }
    select.value = value;
  }
  function tileColourText(value) {
    if (!validColour(value)) return '#241733';
    const channels = value.slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255)
      .map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    return luminance > 0.179 ? '#111' : '#fff';
  }
  let openColourDialog;
  if (colourDialog) {
    const wheel = get('pos-colour-wheel');
    const presets = get('pos-colour-presets');
    const hex = get('pos-colour-hex');
    const sample = get('pos-colour-sample');
    const apply = get('pos-colour-apply');
    const lightness = [0.94, 0.86, 0.77, 0.68, 0.57, 0.46];
    const shades = lightness.map(light => Array.from({length: 12}, (_, hue) => {
      const amplitude = 0.85 * Math.min(light, 1 - light);
      const rgb = [0, 8, 4].map(offset => {
        const angle = (offset + hue) % 12;
        const channel = light - amplitude * Math.max(-1, Math.min(angle - 3, 9 - angle, 1));
        return Math.round(channel * 255).toString(16).padStart(2, '0');
      });
      return '#' + rgb.join('');
    }));
    for (let index = shades.length - 1; index >= 0; index--) {
      const ring = document.createElement('div');
      ring.className = 'pos-colour-wheel-ring';
      ring.style.width = `${(index + 1) * 100 / shades.length}%`;
      ring.style.background = 'conic-gradient(' + shades[index].map((colour, hue) =>
        `${colour} ${hue * 30}deg ${(hue + 1) * 30}deg`).join(', ') + ')';
      wheel.append(ring);
    }
    let activeSelect;
    function preview(value) {
      hex.value = value;
      apply.disabled = !!value && !validColour(value);
      sample.style.backgroundColor = validColour(value) ? value : '#fff1f7';
      for (const swatch of presets.children) {
        swatch.setAttribute('aria-pressed', String(swatch.dataset.colour.toLowerCase() === value.toLowerCase()));
      }
    }
    hex.addEventListener('input', () => preview(hex.value));
    wheel.addEventListener('click', event => {
      const bounds = wheel.getBoundingClientRect();
      const x = event.clientX - bounds.left - bounds.width / 2;
      const y = event.clientY - bounds.top - bounds.height / 2;
      const radius = Math.hypot(x, y) / (bounds.width / 2);
      if (radius > 1) return;
      const hue = Math.floor(((Math.atan2(x, -y) * 180 / Math.PI + 360) % 360) / 30);
      const shade = Math.min(shades.length - 1, Math.floor(radius * shades.length));
      preview(radius < 0.08 ? '#ffffff' : shades[shade][hue]);
    });
    apply.addEventListener('click', () => {
      const select = activeSelect;
      const value = hex.value.toLowerCase();
      if (value && !validColour(value)) return;
      colourDialog.close();
      if (select.value === value) return;
      setColourValue(select, value);
      select.dispatchEvent(new Event('input', {bubbles: true}));
      select.dispatchEvent(new Event('change', {bubbles: true}));
    });
    openColourDialog = (select, label) => {
      activeSelect = select;
      get('pos-colour-title').textContent = label;
      presets.replaceChildren(...[...select.options].filter(option => option.textContent !== option.value).map(option => {
        const swatch = document.createElement('button');
        swatch.type = 'button';
        swatch.className = 'pos-colour-swatch';
        swatch.dataset.colour = option.value;
        swatch.title = option.textContent.trim();
        swatch.setAttribute('aria-label', swatch.title);
        swatch.style.setProperty('--pos-swatch-colour', option.value || '#fff');
        swatch.addEventListener('click', () => preview(option.value));
        return swatch;
      }));
      preview(select.value);
      colourDialog.showModal();
    };
  }
  function addColourPalette(select, label) {
    if (select.dataset.savedColour) {
      setColourValue(select, select.dataset.savedColour);
      for (const option of select.options) option.defaultSelected = option.value === select.dataset.savedColour;
    }
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'pos-secondary pos-colour-trigger';
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-label', label);
    trigger.textContent = 'Choose colour';
    trigger.addEventListener('click', () => openColourDialog(select, label));
    function sync() {
      trigger.style.setProperty('--pos-swatch-colour', select.value || '#fff1f7');
      trigger.disabled = select.disabled;
    }
    colourPalettes.set(select, sync);
    select.addEventListener('change', sync);
    select.hidden = true;
    (select.closest('label') || select).after(trigger);
    sync();
  }
  for (const select of library.querySelectorAll('select[name=tile_colour]')) {
    addColourPalette(select, select.getAttribute('aria-label') || 'Tile colour');
  }
  for (const button of products) {
    const entry = button.closest('.pos-product-entry');
    if (entry.style.getPropertyValue('--pos-tile-colour')) {
      entry.style.setProperty('--pos-tile-text', tileColourText(entry.style.getPropertyValue('--pos-tile-colour')));
    }
  }
  const itemFields = form => {
    const fields = new FormData(form);
    fields.delete('csrf_token');
    return Object.fromEntries(fields);
  };
  function renderVariationColours(form) {
    const container = form.querySelector('[data-pos-variation-colours]');
    const variations = [...new Set(form.elements.variations.value.split(/\r?\n/).map(name => name.trim()).filter(Boolean))];
    const stored = form.elements.variation_colours;
    const colours = new Map(Object.entries(JSON.parse(stored.value)));
    const rows = variations.slice(0, 50).map(name => {
      const row = document.createElement('div');
      const label = document.createElement('label');
      label.textContent = `Tile colour for ${name}`;
      const select = form.elements.tile_colour.cloneNode(true);
      select.removeAttribute('name');
      select.options[0].textContent = 'Use item colour';
      select.dataset.savedColour = colours.get(name) || '';
      setColourValue(select, select.dataset.savedColour);
      select.addEventListener('change', () => {
        if (select.value) colours.set(name, select.value);
        else colours.delete(name);
        stored.value = JSON.stringify(Object.fromEntries(colours));
      });
      label.append(select);
      row.append(label);
      addColourPalette(select, label.firstChild.textContent);
      return row;
    });
    container.replaceChildren(...rows);
    container.hidden = !rows.length;
  }
  for (const form of library.querySelectorAll('.pos-item-editor')) {
    renderVariationColours(form);
    form.elements.variations.addEventListener('input', () => renderVariationColours(form));
  }
  library.addEventListener('click', event => {
    const opener = event.target.closest('[data-pos-library-open]');
    const closer = event.target.closest('[data-pos-library-close]');
    if (opener) {
      const dialog = get(opener.dataset.posLibraryOpen);
      const form = dialog.querySelector('[data-pos-queue-edit]');
      if (form) {
        form.reset();
        const queued = pendingEdits.get(form.elements.product_id.value);
        if (queued) {
          for (const field of form.elements) {
            if (field.type === 'checkbox') field.checked = queued[field.name] === field.value;
            else if (field.name === 'tile_colour') setColourValue(field, queued[field.name]);
            else if (Object.hasOwn(queued, field.name)) field.value = queued[field.name];
          }
        }
        form.querySelector('[data-pos-discard-edit]').hidden = !queued;
        colourPalettes.get(form.elements.tile_colour)?.();
        renderVariationColours(form);
      }
      dialog.showModal();
      dialog.querySelector('input[name=name]')?.focus();
    }
    if (closer) closer.closest('dialog').close();
  });
  if (batchForm) {
    const status = get('pos-batch-status');
    const save = batchForm.querySelector('button');
    const editors = [...library.querySelectorAll('[data-pos-queue-edit]')];
    const inlineFields = [...library.querySelectorAll('[data-pos-inline-edit]')];
    let saving = false;
    function report(message) {
      save.disabled = saving || !pendingEdits.size;
      status.textContent = message || (pendingEdits.size
        ? `${pendingEdits.size} item${pendingEdits.size === 1 ? '' : 's'} queued.`
        : 'No item changes queued.');
    }
    for (const form of editors) {
      const original = itemFields(form);
      const row = form.closest('tr');
      const fieldsInRow = row.querySelectorAll('[data-pos-inline-edit]');
      function queue(fields) {
        const changed = JSON.stringify(fields) !== JSON.stringify(original);
        if (changed) pendingEdits.set(fields.product_id, fields);
        else pendingEdits.delete(fields.product_id);
        row.querySelector('[data-pos-edit-pending]').hidden = !changed;
        report();
      }
      variationColourEditors.set(original.product_id, {
        options: row.querySelector('[data-pos-inline-edit][name=tile_colour]'),
        set(variation, colour) {
          if (saving) return;
          const fields = pendingEdits.get(original.product_id) || original;
          const colours = new Map(Object.entries(JSON.parse(fields.variation_colours)));
          if (colour) colours.set(variation, colour);
          else colours.delete(variation);
          queue({...fields, variation_colours: JSON.stringify(Object.fromEntries(colours))});
        },
        saved(colours, names) {
          const pending = pendingEdits.get(original.product_id);
          original.variation_colours = JSON.stringify(colours);
          form.elements.variation_colours.defaultValue = original.variation_colours;
          if (!pending) return;
          const unsaved = Object.entries(JSON.parse(pending.variation_colours))
            .filter(([name]) => !names.includes(name));
          queue({...pending, variation_colours: JSON.stringify({...colours, ...Object.fromEntries(unsaved)})});
        }
      });
      for (const field of fieldsInRow) {
        field.addEventListener('input', () => {
          if (saving) return;
          const previous = pendingEdits.get(original.product_id) || original;
          queue({...previous, [field.name]: field.value});
        });
      }
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (saving) return;
        const fields = itemFields(form);
        fieldsInRow.forEach(field => {
          if (field.name === 'tile_colour') setColourValue(field, fields[field.name]);
          else field.value = fields[field.name];
          colourPalettes.get(field)?.();
        });
        queue(fields);
        form.closest('dialog').close();
      });
      form.querySelector('[data-pos-discard-edit]').addEventListener('click', () => {
        if (saving) return;
        fieldsInRow.forEach(field => {
          field.value = original[field.name];
          colourPalettes.get(field)?.();
        });
        queue(original);
        form.closest('dialog').close();
      });
    }
    window.addEventListener('beforeunload', event => {
      if (pendingEdits.size) {
        event.preventDefault();
        event.returnValue = true;
      }
    });
    batchForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (saving || !pendingEdits.size) return;
      const invalid = inlineFields.find(field => !field.validity.valid);
      if (invalid) {
        invalid.reportValidity();
        return;
      }
      saving = true;
      inlineFields.forEach(field => {
        field.disabled = true;
        colourPalettes.get(field)?.();
      });
      report('Saving item changes…');
      const body = new FormData(batchForm);
      body.set('edits', JSON.stringify([...pendingEdits.values()]));
      try {
        const response = await fetch(batchForm.action, {method: 'POST', body, headers: {Accept: 'application/json'}});
        if (response.redirected) throw new Error('Sign in again before saving item changes.');
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save item changes.');
        pendingEdits.clear();
        const destination = new URL(result.location, location.href);
        if (destination.pathname === location.pathname && destination.search === location.search) {
          history.replaceState(history.state, '', destination);
          location.reload();
        } else {
          location.assign(destination);
        }
      } catch (error) {
        saving = false;
        inlineFields.forEach(field => {
          field.disabled = false;
          colourPalettes.get(field)?.();
        });
        report(error instanceof SyntaxError ? 'Could not save item changes. Try again.' : error.message);
      }
    });
  }
  if (orderForm) {
    const dialog = get('pos-tile-order');
    const list = orderForm.querySelector('ol');
    const columns = orderForm.elements.columns;
    const feedback = get('pos-order-feedback');
    const saveButton = orderForm.querySelector('[type=submit]');
    let savedRows = [...list.children];
    let savedColumns = columns.value;
    let drag = null;
    let saving = false;
    library.querySelector('[data-pos-library-open=pos-tile-order]').addEventListener('click', () => {
      const colours = new Map([...library.querySelectorAll('[data-pos-inline-edit][name=tile_colour]')]
        .map(field => [field.closest('tr').dataset.posManagedItem, field.value]));
      for (const row of list.children) {
        const colour = colours.get(row.querySelector('[name=product_id]').value);
        row.style.setProperty('--pos-tile-text', tileColourText(colour));
        if (colour) row.style.setProperty('--pos-tile-colour', colour);
        else row.style.removeProperty('--pos-tile-colour');
      }
    });
    const updateControls = () => {
      [...list.children].forEach((row, index) => {
        row.querySelector('[data-pos-move=up]').disabled = saving || index === 0;
        row.querySelector('[data-pos-move=down]').disabled = saving || index === list.children.length - 1;
      });
      saveButton.disabled = saving;
      columns.disabled = saving;
      orderForm.querySelector('[data-pos-library-close]').disabled = saving;
    };
    columns.addEventListener('change', () => { list.dataset.columns = columns.value; });
    list.addEventListener('pointerdown', event => {
      const grip = event.target.closest('[data-pos-drag]');
      if (!grip || saving || drag || event.button !== 0) return;
      const row = grip.closest('li');
      drag = {id: event.pointerId, row, original: [...list.children]};
      row.dataset.dragging = '';
      list.setPointerCapture(event.pointerId);
    });
    list.addEventListener('pointermove', event => {
      if (drag?.id !== event.pointerId) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientY < bounds.top + 28) dialog.scrollTop -= 12;
      if (event.clientY > bounds.bottom - 28) dialog.scrollTop += 12;
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('li');
      if (target?.parentElement !== list || target === drag.row) return;
      const rows = [...list.children];
      if (rows.indexOf(target) < rows.indexOf(drag.row)) target.before(drag.row);
      else target.after(drag.row);
      updateControls();
    });
    function finishDrag(event, cancelled) {
      if (drag?.id !== event.pointerId) return;
      delete drag.row.dataset.dragging;
      if (cancelled) list.replaceChildren(...drag.original);
      drag = null;
      updateControls();
    }
    list.addEventListener('pointerup', event => finishDrag(event, false));
    list.addEventListener('pointercancel', event => finishDrag(event, true));
    list.addEventListener('lostpointercapture', event => finishDrag(event, true));
    list.addEventListener('click', event => {
      const button = event.target.closest('[data-pos-move]');
      if (!button) return;
      const row = button.closest('li');
      if (button.dataset.posMove === 'up') row.previousElementSibling.before(row);
      else row.nextElementSibling.after(row);
      updateControls();
      (button.disabled ? row.querySelector('[data-pos-move]:enabled') : button).focus();
    });
    dialog.addEventListener('cancel', event => {
      if (saving) event.preventDefault();
    });
    dialog.addEventListener('close', () => {
      list.replaceChildren(...savedRows);
      columns.value = savedColumns;
      list.dataset.columns = savedColumns;
      feedback.textContent = '';
      updateControls();
    });
    orderForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (saving) return;
      const body = new FormData(orderForm);
      saving = true;
      updateControls();
      feedback.textContent = 'Saving tile order…';
      try {
        const response = await fetch(orderForm.action, {method: 'POST', body, headers: {Accept: 'application/json'}});
        if (response.redirected) throw new Error('Sign in again before saving the tile order.');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not save the tile order.');
        const tiles = new Map(products.map(button => [Number(button.dataset.productId), button.closest('.pos-product-entry')]));
        const rows = new Map([...library.querySelectorAll('[data-pos-managed-item]')].map(row => [Number(row.dataset.posManagedItem), row]));
        const grid = library.querySelector('.pos-product-grid');
        const table = library.querySelector('.pos-management-table tbody');
        grid.append(...data.product_ids.map(id => tiles.get(id)));
        grid.dataset.columns = String(data.columns);
        table.append(...data.product_ids.map(id => rows.get(id)));
        savedRows = [...list.children];
        savedColumns = String(data.columns);
        dialog.close();
        get('pos-order-saved').textContent = 'Tile order saved.';
      } catch (error) {
        feedback.textContent = error instanceof SyntaxError ? 'Could not save the tile order. Try again.' : error.message;
      } finally {
        saving = false;
        updateControls();
      }
    });
  }
  const picker = get('pos-variation-picker');
  const variationGrid = get('pos-variation-grid');
  const editVariationColours = get('pos-variation-edit-colours');
  const saveVariationColours = get('pos-variation-save-colours');
  const variationColourStatus = get('pos-variation-colour-status');
  let showVariations;
  let savePickerColours;
  let variationSaving = false;
  saveVariationColours?.addEventListener('click', () => savePickerColours());
  picker.addEventListener('cancel', event => {
    if (variationSaving) event.preventDefault();
  });
  editVariationColours?.addEventListener('click', () => {
    const editing = editVariationColours.getAttribute('aria-pressed') !== 'true';
    editVariationColours.setAttribute('aria-pressed', String(editing));
    editVariationColours.textContent = editing ? 'Done editing' : 'Edit colours';
    variationColourStatus.hidden = !editing;
    variationColourStatus.textContent = 'Choose a variation to change its colour.';
    showVariations(editing);
  });
  products.forEach(button => button.addEventListener('click', () => {
    const pence = parsePrice(button.dataset.productPrice);
    if (pence === null) return;
    const item = {name: button.dataset.productName, quantity: 1, pence, product_id: Number(button.dataset.productId)};
    if (!button.dataset.variations) {
      addItem(item);
      return;
    }
    get('pos-variation-title').textContent = item.name;
    const variations = JSON.parse(button.dataset.variations);
    const editor = variationColourEditors.get(button.dataset.productId);
    function colourChanges() {
      const queued = pendingEdits.get(button.dataset.productId);
      if (!queued) return [];
      const saved = new Map(Object.entries(JSON.parse(button.dataset.variationColours)));
      const pending = new Map(Object.entries(JSON.parse(queued.variation_colours)));
      return variations.filter(name => saved.get(name) !== pending.get(name))
        .map(name => [name, pending.get(name) ?? null]);
    }
    function renderChoices(editing) {
      if (saveVariationColours) {
        saveVariationColours.hidden = !editing;
        saveVariationColours.disabled = variationSaving || !colourChanges().length;
      }
      const queued = editing ? pendingEdits.get(button.dataset.productId) : null;
      const colours = JSON.parse(queued?.variation_colours || button.dataset.variationColours);
      const itemColour = queued?.tile_colour ?? button.closest('.pos-product-entry').style.getPropertyValue('--pos-tile-colour');
      variationGrid.replaceChildren(...variations.map(variation => {
        const choice = document.createElement('button');
        choice.type = 'button';
        choice.disabled = variationSaving;
        choice.className = 'pos-variation-tile';
        choice.textContent = variation;
        const colour = (Object.hasOwn(colours, variation) && colours[variation]) || itemColour;
        choice.style.setProperty('--pos-tile-colour', colour);
        choice.style.setProperty('--pos-tile-text', tileColourText(colour));
        choice.addEventListener('click', () => {
          if (editing) {
            const select = editor.options.cloneNode(true);
            select.options[0].textContent = 'Use item colour';
            setColourValue(select, Object.hasOwn(colours, variation) ? colours[variation] : '');
            select.addEventListener('change', () => {
              editor.set(variation, select.value);
              renderChoices(true);
              variationColourStatus.textContent = 'Select Save colours to apply your changes.';
              [...variationGrid.children].find(tile => tile.textContent === variation)?.focus();
            });
            openColourDialog(select, `Tile colour for ${variation}`);
            return;
          }
          if (!button.disabled) addItem({...item, name: `${item.name} · ${variation}`, variation});
          picker.close();
        });
        return choice;
      }));
    }
    showVariations = renderChoices;
    savePickerColours = async () => {
      const changes = colourChanges();
      if (variationSaving || !changes.length) return;
      variationSaving = true;
      const cancel = picker.querySelector('[data-pos-library-close]');
      cancel.disabled = editVariationColours.disabled = true;
      variationColourStatus.textContent = 'Saving colours…';
      renderChoices(true);
      const body = new FormData();
      body.set('csrf_token', batchForm.elements.csrf_token.value);
      body.set('changes', JSON.stringify(Object.fromEntries(changes)));
      try {
        const response = await fetch(button.dataset.variationSaveUrl, {
          method: 'POST', body, headers: {Accept: 'application/json'}
        });
        if (response.redirected) throw new Error('Sign in again before saving colours.');
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save colours.');
        button.dataset.variationColours = JSON.stringify(result.colours);
        editor.saved(result.colours, variations);
        variationColourStatus.textContent = 'Colours saved.';
      } catch (error) {
        variationColourStatus.textContent = error instanceof SyntaxError ? 'Could not save colours. Try again.' : error.message;
      } finally {
        variationSaving = false;
        cancel.disabled = editVariationColours.disabled = false;
        renderChoices(true);
        editVariationColours.focus();
      }
    };
    if (editVariationColours) {
      editVariationColours.setAttribute('aria-pressed', 'false');
      editVariationColours.textContent = 'Edit colours';
      variationColourStatus.hidden = true;
    }
    renderChoices(false);
    picker.showModal();
    variationGrid.querySelector('button')?.focus();
  }));
  function filterProducts() {
    const query = get('pos-library-search').value.trim().toLowerCase();
    const category=get('pos-product-category')?.value || '';
    const shortcuts=get('pos-shortcuts-only')?.checked;
    products.forEach(button => {
      button.hidden = !button.dataset.productName.toLowerCase().includes(query) ||
        (category && button.dataset.productCategory!==category) || (shortcuts && button.dataset.productShortcut!=='true');
      button.closest('.pos-product-entry').hidden = button.hidden;
    });
    get('pos-library-status').textContent = `${products.filter(button => !button.closest('.pos-product-entry').hidden).length} items shown`;
  }
  get('pos-library-search')?.addEventListener('input',filterProducts);
  get('pos-product-category')?.addEventListener('change',filterProducts);
  let refreshingStock = false;
  setInterval(async () => {
    if (document.hidden || refreshingStock || !products.length) return;
    refreshingStock = true;
    try {
      const response = await fetch(get('pos-library').dataset.stockUrl, {
        cache: 'no-store', headers: {Accept: 'application/json', 'X-Portal-Refresh': '1'}
      });
      if (!response.ok || response.redirected) return;
      const stock = await response.json();
      products.forEach(button => {
        const entry = stock[button.dataset.productId];
        button.disabled = entry?.available === 0;
        let warning = button.querySelector('.pos-stock-warning');
        if (!warning && entry?.low) {
          warning = document.createElement('span');
          warning.className = 'pos-stock-warning';
          button.append(warning);
        }
        if (warning) {
          warning.hidden = !entry?.low;
          warning.textContent = entry?.low ? (entry.available ? `Low stock · ${entry.available} left` : 'Out of stock') : '';
        }
      });
    } catch (_) {
      // Leave the last available stock information in place until the next refresh.
    } finally {
      refreshingStock = false;
    }
  }, 5000);
  get('pos-shortcuts-only')?.addEventListener('change',filterProducts);
  const waiverResults = get('pos-waiver-results');
  waiverResults.addEventListener('click', event => {
    const button = event.target.closest('button[data-waiver-id]');
    if (!button || !waiverResults.contains(button)) return;
    const participant = button.closest('.pos-waiver')?.querySelector('.pos-participant');
    waiver = {id:button.dataset.waiverId, label:button.dataset.waiverLabel,
      participantId:participant?.value || '', participantName:participant?.value ? participant.selectedOptions[0].textContent : '',
      people:participant ? [...participant.options].filter(option=>option.value).map(option=>({id:option.value,name:option.textContent,points:option.dataset.points || '0'})) : []}; render();
    updateLoyalty(participant ? [...participant.options].filter(option => option.value) : [], participant?.value || '');
    const receiptEmail = get('pos-receipt-email');
    if (!receiptEmail.value || receiptEmail.value === receiptEmail.dataset.prefilled) {
      receiptEmail.value = button.dataset.waiverEmail || '';
      receiptEmail.dataset.prefilled = receiptEmail.value;
    }
    get('pos-waiver-fold').open = false;
    get('pos-waiver-summary').focus();
    document.dispatchEvent(new Event('pos-waiver-linked'));
  });
  waiverResults.addEventListener('change', event => {
    const select = event.target.closest('.pos-participant');
    if (!select) return;
    const button = select.closest('.pos-waiver').querySelector('[data-waiver-id]');
    if (waiver?.id === button.dataset.waiverId) button.click();
  });
  const searchForm = get('pos-search'), searchInput = get('pos-query');
  const searchStatus = get('pos-waiver-search-status'), recentWaivers = get('pos-recent-waivers');
  let searchTimer, searchController, lastWaiverHtml, searchVersion = 0;
  async function searchWaivers(version, background = false) {
    const query = searchInput.value.trim();
    if (!query && !recentWaivers.checked) {
      lastWaiverHtml = null;
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
      url.searchParams.set('recent', recentWaivers.checked ? '1' : '0');
      const headers = {Accept: 'application/json'};
      if (background) headers['X-Portal-Refresh'] = '1';
      const response = await fetch(url, {signal:searchController.signal, credentials:'same-origin', cache:'no-store', headers});
      if (!response.ok || response.redirected) throw new Error('Search unavailable');
      const data = await response.json();
      if (version !== searchVersion) return;
      if (typeof data.html !== 'string' || !Number.isInteger(data.count)) throw new Error('Invalid search response');
      if (data.html !== lastWaiverHtml && (!background || !waiverResults.contains(document.activeElement))) {
        lastWaiverHtml = data.html;
        waiverResults.innerHTML = data.html;
        if (!background) waiverResults.scrollTop = 0;
      }
      searchStatus.textContent = `${data.count === 30 ? 'Showing the latest ' : ''}${data.count} matching waiver${data.count === 1 ? '' : 's'}.`;
    } catch (error) {
      if (version !== searchVersion || error.name === 'AbortError' || background) return;
      lastWaiverHtml = null;
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
  recentWaivers.addEventListener('change', () => queueWaiverSearch(true));
  setInterval(() => {
    if (!document.hidden && get('pos-waiver-fold').open && (recentWaivers.checked || searchInput.value.trim()) &&
        !waiverResults.hasAttribute('aria-busy')) searchWaivers(++searchVersion, true);
  }, 3000);
  searchInput.addEventListener('input', event => { if (!event.isComposing) queueWaiverSearch(); });
  searchInput.addEventListener('compositionend', () => queueWaiverSearch());
  searchForm.addEventListener('submit', event => { event.preventDefault(); queueWaiverSearch(true); });
  const showWaivers = () => {
    get('pos-waiver-fold').open = true;
    document.dispatchEvent(new Event('pos-waiver-open'));
    get('pos-query').focus();
  };
  get('pos-change-waiver')?.addEventListener('click',showWaivers);
  get('pos-clear-waiver').onclick = () => {
    waiver = null;
    const receiptEmail = get('pos-receipt-email');
    if (receiptEmail.value === receiptEmail.dataset.prefilled) receiptEmail.value = '';
    delete receiptEmail.dataset.prefilled;
    render();
    updateLoyalty();
    showWaivers();
  };
  get('pos-clear-basket').onclick = () => {
    items = [];
    get('pos-error').textContent = '';
    render();
    if (get('pos-library-status')) get('pos-library-status').textContent = 'Basket cleared.';
  };
  get('pos-cash-open').onclick = () => {
    document.dispatchEvent(new Event('pos-basket-open'));
    get('pos-cash-panel').hidden = false;
    get('pos-cash-open').setAttribute('aria-expanded', 'true');
    get('pos-cash-tender').disabled = false;
    updateCash();
    get('pos-cash-tender').focus();
  };
  get('pos-cash-tender').addEventListener('input', updateCash);
  get('pos-cash-keypad').addEventListener('click', event => {
    const button = event.target.closest('[data-cash-key]');
    if (!button) return;
    const tender = get('pos-cash-tender');
    const key = button.dataset.cashKey;
    let start = tender.selectionStart;
    let end = tender.selectionEnd;
    let replacement = key;
    if (key === 'clear') {
      start = 0;
      end = tender.value.length;
      replacement = '';
    } else if (key === 'backspace') {
      if (start === end) start = Math.max(0, start - 1);
      replacement = '';
    } else if (key === '.' && start === 0) {
      replacement = '0.';
    }
    const next = tender.value.slice(0, start) + replacement + tender.value.slice(end);
    if (replacement && !/^\d{0,6}(\.\d{0,2})?$/.test(next)) return;
    tender.setRangeText(replacement, start, end, 'end');
    tender.focus({preventScroll: true});
    updateCash();
  });
  document.querySelectorAll('[data-cash-tender]').forEach(button => button.addEventListener('click', () => {
    const total = amountDue();
    get('pos-cash-tender').value = button.dataset.cashTender === 'exact' ? (total/100).toFixed(2) : Number(button.dataset.cashTender).toFixed(2);
    updateCash();
  }));
  get('pos-cash-cancel').onclick = () => { closeCash(); get('pos-cash-open').focus(); };
  if (get('pos-hold-basket')) {
    const base = get('pos-hold-basket').dataset.heldUrl;
    const feedback = get('pos-held-status');
    const api = async (path, payload) => {
      const response = await fetch(path,{method:payload ? 'POST':'GET',credentials:'same-origin',cache:'no-store',
        headers:{Accept:'application/json',...(payload ? {'Content-Type':'application/json'} : {})},
        ...(payload ? {body:JSON.stringify({...payload,csrf_token:get('pos-checkout').elements.csrf_token.value})} : {})});
      if (!response.ok || response.redirected) throw new Error('Could not save or load this basket. Check your sign-in and try again.');
      return response.json();
    };
    const refresh = async () => {
      try {
        const data = await api(base);
        get('pos-held-list').replaceChildren();
        data.baskets.forEach(basket => {
          const row = document.createElement('div'); row.className='pos-held-row';
          const label = document.createElement('span');label.textContent=basket.label+(basket.status==='Resumed' ? ' · Previously resumed, not yet paid' : '');
          const resume = document.createElement('button');resume.type='button';resume.textContent='Resume';
          resume.onclick = async () => {
            if (items.length) {feedback.textContent='Hold or clear the current basket before resuming another.';return;}
            resume.disabled=true;
            try {
              const data=await api(base+'/'+basket.id+'/resume',{}), saved=data.payload;
              items=saved.items.map(item=>({name:item.name,quantity:item.quantity,pence:Math.round(Number(item.price)*100),...(item.product_id ? {product_id:item.product_id} : {}), variation:item.variation}));
              waiver=saved.waiver || null;
              get('pos-checkout').elements.sale_token.value=data.sale_token;
              get('pos-receipt-requested').checked=!!saved.receipt_requested;
              get('pos-receipt-email').value=saved.receipt_email || '';
              if (get('pos-trading-event')) get('pos-trading-event').value=saved.trading_event_id || '';
              if (get('pos-loyalty-event')) get('pos-loyalty-event').value=saved.loyalty_event_id || '';
              const people=(saved.loyalty_people || []);
              updateLoyalty(people.map(person=>({value:String(person.id),textContent:person.name,dataset:{points:String(person.points || 0)}})),waiver?.participantId || '');
              document.querySelectorAll('input[name=loyalty_participant_id]').forEach(field=>{field.checked=people.some(person=>String(person.id)===field.value && person.checked);});
              updateReceipt();render();
              document.dispatchEvent(new Event('pos-basket-open'));
              get('pos-waiver-fold').open=!waiver;
              feedback.textContent='Basket resumed. Check prices, waiver validity and event before payment.';
            } catch(error) {feedback.textContent=error.message;}
            resume.disabled=false;
          };
          row.append(label,resume);get('pos-held-list').append(row);
        });
        if (!data.baskets.length) get('pos-held-list').textContent='No held baskets.';
      } catch(error) {feedback.textContent=error.message;}
    };
    get('pos-refresh-held').onclick=refresh;
    get('pos-held-controls').addEventListener('toggle',()=>{if(get('pos-held-controls').open)refresh();});
    get('pos-hold-basket').onclick=async () => {
      const label=get('pos-hold-label').value.trim();
      if (!label) {feedback.textContent='Enter a name for this held basket.';return;}
      get('pos-hold-basket').disabled=true;
      try {
        const data=await api(base,{label,items:JSON.parse(get('pos-items').value),waiver,
          receipt_email:get('pos-receipt-email').value,receipt_requested:get('pos-receipt-requested').checked,
          trading_event_id:get('pos-trading-event')?.value || '',loyalty_event_id:get('pos-loyalty-event')?.value || '',
          loyalty_people:(waiver?.people || []).map(person=>({...person,checked:[...document.querySelectorAll('input[name=loyalty_participant_id]')].some(field=>field.value===String(person.id)&&field.checked)}))});
        items=[];waiver=null;closeCash();updateLoyalty();get('pos-receipt-requested').checked=false;get('pos-receipt-email').value='';updateReceipt();
        get('pos-checkout').elements.sale_token.value=data.next_sale_token;
        get('pos-hold-label').value='';render();get('pos-waiver-fold').open=true;
        feedback.textContent='Basket held. Ready for the next customer.';await refresh();
      } catch(error) {feedback.textContent=error.message;render();}
    };
  }
  get('pos-checkout').addEventListener('change', updateSaleOptions);
  get('pos-checkout').addEventListener('invalid', event => {
    if (get('pos-sale-options').contains(event.target)) get('pos-sale-options').open = true;
  }, true);
  get('pos-checkout').addEventListener('submit', event => {
    const eventField = get('pos-loyalty-event');
    if (eventField) {
      eventField.required = !!document.querySelector('input[name=loyalty_participant_id]:checked');
      if (!eventField.checkValidity()) {
        event.preventDefault();
        document.dispatchEvent(new Event('pos-basket-open'));
        get('pos-sale-options').open = true;
        eventField.reportValidity();
        return;
      }
    }
    if (get('pos-receipt-requested').checked && !get('pos-receipt-email').checkValidity()) {
      event.preventDefault();
      document.dispatchEvent(new Event('pos-basket-open'));
      get('pos-sale-options').open = true;
      get('pos-receipt-email').reportValidity();
      return;
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
