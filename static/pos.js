(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const canManage = document.querySelector('.pos-main')?.dataset.posManager !== 'false';
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
      const priceLabel = document.createElement('label'); priceLabel.textContent = 'Unit price (£)';
      const price = document.createElement('input'); price.type = 'number'; price.min = '0.01'; price.max = '99999'; price.step = '0.01'; price.inputMode = 'decimal'; price.value = (item.pence / 100).toFixed(2);
      price.setAttribute('aria-label', `Unit price for ${item.name}`);
      price.readOnly = !canManage;
      price.addEventListener('change', () => {
        const value = parsePrice(price.value);
        if (value === null) { price.value = (item.pence / 100).toFixed(2); get('pos-error').textContent = 'Enter a positive price with up to two decimal places.'; return; }
        item.pence = value; get('pos-error').textContent = ''; render();
      });
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
      quantityLabel.append(stepper); priceLabel.append(price); fields.append(quantityLabel, priceLabel);
      row.append(fields); get('pos-basket').append(row);
    });
    get('pos-total').textContent = `Total ${money(total)}`;
    if(get('pos-mobile-basket-count')){
      const count=items.reduce((sum,item)=>sum+item.quantity,0);
      get('pos-mobile-basket-count').textContent=count;
      get('pos-mobile-basket-total').textContent=money(total);
      get('pos-mobile-basket-toggle').setAttribute('aria-label',`Basket: ${count} items, total ${money(total)}`);
    }
    get('pos-items').value = JSON.stringify(items.map(i => ({name:i.name, quantity:i.quantity, price:(i.pence / 100).toFixed(2), ...(i.product_id ? {product_id:i.product_id} : {})})));
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
    const card=get('pos-card-pay');
    if(card){
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
  products.forEach(button => button.addEventListener('click', () => {
    const pence = parsePrice(button.dataset.productPrice);
    if (pence !== null) addItem({name: button.dataset.productName, quantity: 1, pence, product_id:Number(button.dataset.productId)});
  }));
  function filterProducts() {
    const query = get('pos-library-search').value.trim().toLowerCase();
    const category=get('pos-product-category')?.value || '';
    const shortcuts=get('pos-shortcuts-only')?.checked;
    products.forEach(button => { button.hidden = !button.dataset.productName.toLowerCase().includes(query) ||
      (category && button.dataset.productCategory!==category) || (shortcuts && button.dataset.productShortcut!=='true'); });
    get('pos-library-status').textContent = `${products.filter(button => !button.hidden).length} items shown`;
  }
  get('pos-library-search')?.addEventListener('input',filterProducts);
  get('pos-product-category')?.addEventListener('change',filterProducts);
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
  document.querySelectorAll('[data-cash-tender]').forEach(button => button.addEventListener('click', () => {
    const total = items.reduce((sum,item) => sum+item.quantity*item.pence,0);
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
              items=saved.items.map(item=>({name:item.name,quantity:item.quantity,pence:Math.round(Number(item.price)*100),...(item.product_id ? {product_id:item.product_id} : {})}));
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
