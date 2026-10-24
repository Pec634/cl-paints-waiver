(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('import-config').textContent);
  const el = id => document.getElementById(id);
  const addressLabels = {property: 'House / flat / suite or address line 1', street: 'Street / address line 2',
    city: 'City / town', state: 'County / state', postcode: 'Postcode', country: 'Country', country_code: 'Country code'};
  const label = name => {
    if (name === 'travel_miles') return 'One-way road miles';
    if (name === 'estimated_cost' && config.pricing) return 'Calculated event cost (£)';
    const address = /^(client|event)_address_(.*)$/.exec(name);
    if (address) return addressLabels[address[2]];
    if (name === 'client_address' || name === 'event_address') return 'Full address (used when separate fields are blank)';
    return name.replaceAll('_', ' ').replace(/^./, character => character.toUpperCase());
  };
  const normal = name => name.toLowerCase().replace(/[^a-z0-9]/g, '');
  const dateOnly = value => {
    const text = String(value || '').trim();
    const iso = /^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$/.exec(text);
    if (iso) return iso[1];
    const uk = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
    if (uk) return `${uk[3]}-${uk[2]}-${uk[1]}`;
    return '';
  };
  const aliases = {firstname: 'first_name', surname: 'last_name', lastname: 'last_name',
    emailaddress: 'email', telephone: 'phone', phonenumber: 'phone', mobile: 'phone',
    dob: 'date_of_birth', date: 'event_date', bookingdate: 'event_date',
    venue: 'event_address', venueaddress: 'event_address', endtime: 'finish_time',
    notes: 'additional_info', cost: 'total_event_cost', postcodeaddress: 'client_address'};
  let source, selectors = [];
  let quoteTimer, quoteSequence = 0;
  function editorRows() {
    return [...el('preview').children].map(detail => ({
      ...Object.fromEntries([...detail.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.value])),
      events: [...detail.querySelector('.import-event-days').children].map(dayValues)
    }));
  }
  function refreshPricing() {
    if (!config.pricing || !el('preview').children.length) return;
    clearTimeout(quoteTimer);
    const sequence = ++quoteSequence;
    let summary = el('edit-price-summary');
    if (!summary) {
      summary = document.createElement('section'); summary.id = 'edit-price-summary'; summary.className = 'panel';
      summary.setAttribute('aria-live', 'polite'); el('preview').after(summary);
    }
    summary.textContent = 'Updating costs…'; el('save-button').disabled = true;
    quoteTimer = setTimeout(async () => {
      try {
        const response = await fetch(location.pathname, {method: 'POST', headers: {
          'X-Import-Token': config.token, 'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify({action: 'quote', rows: editorRows(), version: config.version})});
        if (sequence !== quoteSequence) return;
        const result = await response.json();
        if (!response.ok) {
          summary.textContent = [result.error, ...(result.errors || [])].filter(Boolean).join(' '); return;
        }
        const quote = result.quote;
        const currency = value => new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'}).format(Number(value));
        const heading = document.createElement('h3'); heading.textContent = 'Updated booking costs';
        const list = document.createElement('dl'); list.className = 'client-detail';
        const entries = [['Event cost', quote.event_total], ['Travel charge', quote.travel], ['Booking total', quote.total],
          ['Outstanding after recorded payments', quote.outstanding], ['CL Paints pitch costs (excluded from client total)', quote.pitch_cost]];
        if (quote.deposit !== null) entries.push(['Estimated 50% deposit', quote.deposit]);
        entries.forEach(([label, value]) => {
          const term = document.createElement('dt'); term.textContent = label;
          const description = document.createElement('dd'); description.textContent = currency(value); list.append(term, description);
        });
        summary.replaceChildren(heading, list);
        quote.notes.forEach(text => { const note = document.createElement('p'); note.textContent = text; summary.append(note); });
        const explanation = document.createElement('p');
        explanation.textContent = `Hourly rate: ${currency(quote.rate)}. Customers pay, revenue sharing and pitch-fee events have no client event charge. Recorded payments and agreed payment schedules are unchanged.`;
        summary.append(explanation);
        [['total_event_cost', quote.event_total], ['travel_charge', quote.travel]].forEach(([field, value]) => {
          const input = el('preview').querySelector(`[data-field="${field}"]`); if (input) input.value = value;
        });
        el('preview').querySelectorAll('.import-event-day').forEach((day, index) => {
          const input = day.querySelector('[data-day-field="estimated_cost"]'); if (input) input.value = quote.days[index].cost;
          let output = day.querySelector('.day-price-output');
          if (!output) { output = document.createElement('p'); output.className = 'day-price-output'; day.append(output); }
          output.textContent = `${Number(quote.days[index].hours).toFixed(2)} hours · Event cost ${currency(quote.days[index].cost)} · Travel ${currency(quote.days[index].travel)}`;
        });
        el('save-button').disabled = false;
      } catch (_) {
        if (sequence === quoteSequence) summary.textContent = 'Could not calculate costs. Check your connection and reload the editor if your session has expired.';
      }
    }, 300);
  }
  el('preview').addEventListener('input', refreshPricing);
  function message(text, errors = [], reveal = false) {
    el('import-status').textContent = text;
    el('import-errors').replaceChildren(...errors.map(text => {
      const li = document.createElement('li'); li.textContent = text; return li;
    }));
    let saveFeedback = el('save-feedback');
    if (!saveFeedback) {
      saveFeedback = document.createElement('div');
      saveFeedback.id = 'save-feedback';
      saveFeedback.setAttribute('role', 'status');
      saveFeedback.setAttribute('aria-live', 'polite');
      el('save-button').parentElement.after(saveFeedback);
    }
    const saveText = document.createElement('p'); saveText.textContent = text;
    const saveErrors = el('import-errors').cloneNode(true); saveErrors.removeAttribute('id');
    saveFeedback.replaceChildren(saveText, saveErrors);
    if (reveal) {
      el('import-status').tabIndex = -1;
      el('import-status').focus({preventScroll: true});
      el('import-status').scrollIntoView({behavior: 'smooth', block: 'center'});
    }
  }
  const legacyNames = {
    title: 'ClientDetails_Name_Prefix', first_name: 'ClientDetails_Name_First', last_name: 'ClientDetails_Name_Last',
    client_type: 'ClientDetails_AreYouAPrivateIndividualOrBusiness', is_over_18: 'ClientDetails_ICanConfirmIAmAged18OrOver',
    location_type: 'EventSectionForASingularDate_LocationIndoorsOutdoors',
    expected_attendees: 'EventSectionForASingularDate_IfYouKnowTheNumberOfPeopleAttendingEnterHere',
    celebrates_christmas_easter: 'EventSectionForASingularDate_DoTheAttendeesTypicallyCelebrateChristmasEasterToYourUnderstanding',
    additional_info: 'EventSectionForASingularDate_AnyFutherAdditionalInformationThatMayBeHelpfulForUs',
    pitch_fee_required: 'EventSectionForASingularDate_DoCLPaintsNeedToPayAPitchFee',
    payment_preference: 'Payment_PaymentOptions', promo_code: 'Payment_ReferAFriendPromoCode', signature: 'Payment_Signature'
  };
  function columnMatch(field) {
    const exact = source.headers.findIndex(header => normal(header) === normal(field) || aliases[normal(header)] === field);
    if (exact >= 0) return exact;
    const address = /^(client|event)_address_(.*)$/.exec(field);
    if (address) {
      const parts = {property: 'Line1', street: 'Line2', city: 'City', state: 'State', postcode: 'PostalCode', country: 'Country', country_code: 'CountryCode'};
      const prefix = address[1] === 'client' ? 'ClientDetails_Address_' : 'EventSectionForASingularDate_Address_';
      return source.headers.indexOf(prefix + parts[address[2]]);
    }
    return source.headers.findIndex(header => header === legacyNames[field] ||
      ['ClientDetails_', 'EventSectionForASingularDate_', 'Payment_'].some(prefix =>
        header.startsWith(prefix) && normal(header.slice(prefix.length)) === normal(field)));
  }
  function importedDays(row, values) {
    const read = name => {
      const index = source.headers.findIndex(header => normal(header) === normal(name));
      return index < 0 ? '' : row[index];
    };
    const schedule = read('events') || read('event_schedule');
    if (schedule) {
      const parsed = JSON.parse(schedule);
      const events = Array.isArray(parsed) ? parsed : parsed.events;
      if (!Array.isArray(events)) throw new Error('The event schedule must contain an events array.');
      if (events.length > 10) throw new Error('A booking can contain up to 10 dates.');
      if (events.length) return events.map(day => {
        const result = {...day, event_date: day.event_date || day.date || ''};
        ['start_time', 'finish_time'].forEach(field => {
          const match = /(?:^|[T ])(\d{2}:\d{2}):00(?:\.0+)?$/.exec(String(result[field] || ''));
          if (match) result[field] = match[1];
        });
        return result;
      });
    }
    const days = [{...values}];
    for (let number = 2; number <= 10; number++) {
      const day = {...values}; let found = false;
      config.eventFields.forEach(field => {
        const index = source.headers.findIndex(header => [field + number, 'day' + number + field, 'event' + number + field, field === 'event_date' ? 'date' + number : ''].filter(Boolean).some(name => normal(name) === normal(header)));
        if (index >= 0) { day[field] = row[index]; if (row[index]) found = true; }
      });
      if (found) days.push(day);
    }
    if (days.length === 1) {
      const extra = read('additional_event_dates');
      if (extra) extra.split(/[,;\n]+/).filter(date => date.trim()).forEach(date => days.push({...values, event_date: date.trim()}));
    }
    if (days.length > 10) throw new Error('A booking can contain up to 10 dates.');
    return days;
  }
  function dayValues(card) {
    const values = Object.fromEntries([...card.querySelectorAll('[data-day-field]')].map(input => [input.dataset.dayField, input.value]));
    if (card.dataset.originalIndex !== undefined) values._original_index = Number(card.dataset.originalIndex);
    return values;
  }
  function addDay(container, values = {}) {
    if (container.children.length >= 10) { message('A booking can contain up to 10 event dates.', [], true); return; }
    const card = document.createElement('fieldset'); card.className = 'import-group import-event-day';
    if (values._original_index !== undefined) card.dataset.originalIndex = values._original_index;
    const legend = document.createElement('legend'); card.append(legend);
    const renumber = () => [...container.children].forEach((day, index) => { day.querySelector('legend').textContent = `Event day ${index + 1}`; });
    config.eventFields.forEach(field => {
      const wrapper = document.createElement('label'); wrapper.className = 'booking-field';
      const span = document.createElement('span'); span.textContent = label(field);
      const choices = config.pricing && (field === 'charge_type' ? ['Client', 'Customers', 'Revenue sharing'] : field === 'pitch_fee_required' ? ['Yes', 'No'] : null);
      const input = document.createElement(choices ? 'select' : field === 'event_date' ? 'input' : 'textarea');
      if (choices) { input.append(new Option('Choose…', '')); choices.forEach(choice => input.append(new Option(choice, choice))); }
      if (field === 'event_date') input.type = 'date'; else input.rows = 1;
      input.dataset.dayField = field;
      let value = values[field];
      if (typeof value === 'boolean') value = value ? 'Yes' : 'No';
      input.value = field === 'event_date' ? dateOnly(value) : value == null ? '' : String(value);
      if (config.pricing && field === 'pitch_fee_required') input.value = ['yes','true','1'].includes(String(value || '').toLowerCase()) ? 'Yes' : 'No';
      if (config.pricing && field === 'estimated_cost') input.readOnly = true;
      const help = document.createElement('small'); help.className = 'import-field-help';
      const required = ['event_date', 'start_time', 'finish_time', 'event_address'].includes(field);
      if (required) span.textContent += ' (required)';
      const check = () => {
        const addressParts = field === 'event_address' && [...card.querySelectorAll('[data-day-field^="event_address_"]')].some(control => control.value.trim());
        const missing = required && !input.value.trim() && !addressParts;
        input.setAttribute('aria-invalid', String(missing));
        help.textContent = missing ? 'Enter this before importing (venue can use the separate address fields).' : '';
      };
      input.addEventListener('input', () => { el('confirm-import').checked = false; });
      if (required) { card.addEventListener('input', check); queueMicrotask(check); }
      wrapper.append(span, input, help); card.append(wrapper);
    });
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn'; remove.textContent = 'Remove this day';
    remove.addEventListener('click', () => {
      if (container.children.length === 1) { message('Keep at least one event day for each booking.', [], true); return; }
      card.remove(); renumber(); el('confirm-import').checked = false; refreshPricing();
    });
    card.append(remove); container.append(card); renumber();
    el('confirm-import').checked = false;
    refreshPricing();
  }
  async function send(body, json = false) {
    const response = await fetch(location.pathname, {method: 'POST',
      headers: {'X-Import-Token': config.token, 'Accept': 'application/json', ...(json ? {'Content-Type': 'application/json'} : {})},
      body: json ? JSON.stringify(body) : body});
    if (response.redirected || response.status === 401) {
      message('Your admin session has ended. Sign in again, then reopen Import bookings.', [], true); return null;
    }
    if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
      message(response.status === 413 ? 'The file is too large. Choose a file under 2 MB.' :
        `The server could not process the upload (HTTP ${response.status}). Refresh this page and try again.`, [], true);
      return null;
    }
    const result = await response.json();
    if (!response.ok) {
      const errors = result.errors || [];
      for (const error of errors) {
        const match = /^Booking (\d+):/.exec(error);
        if (match && el('preview').children[Number(match[1]) - 1]) el('preview').children[Number(match[1]) - 1].open = true;
      }
      message(result.error || 'Import failed.', errors, true); return null;
    }
    return result;
  }
  el('upload-form').addEventListener('submit', async event => {
    event.preventDefault();
    el('mapping-panel').hidden = true; el('review-panel').hidden = true;
    const button = event.target.querySelector('button'); button.disabled = true;
    try {
      const file = el('import-file').files[0];
      if (file.size > 2 * 1024 * 1024) { message('Choose a file under 2 MB.'); return; }
      const body = new FormData(); body.append('file', file);
      message('Reading file…'); source = await send(body);
      if (!source) return;
      el('mapping').replaceChildren(); selectors = [];
      config.fields.forEach(field => {
        const wrapper = document.createElement('label'); wrapper.style.display = 'block';
        const address = /^(client|event)_address/.exec(field);
        wrapper.append(document.createTextNode(`${address ? `${address[1] === 'client' ? 'Client' : 'Event'} address: ` : ''}${label(field)} ← `));
        const select = document.createElement('select');
        select.append(new Option('Not in file / enter during review', ''));
        source.headers.forEach((header, index) => select.append(new Option(header, String(index))));
        const match = columnMatch(field);
        select.value = match < 0 ? '' : String(match);
        wrapper.append(select); el('mapping').append(wrapper); selectors.push(select);
      });
      el('mapping-panel').hidden = false;
      el('mapping-panel').open = false;
      el('review-button').click();
    } catch (_) { message('Unable to read the file. Check your connection and admin session.'); }
    finally { button.disabled = false; }
  });
  el('review-button').addEventListener('click', () => {
    el('preview').replaceChildren(); el('confirm-import').checked = false;
    const usedColumns = new Set(selectors.map(select => select.value).filter(value => value !== ''));
    source.rows.forEach((row, index) => {
      const values = {}, unmatched = [];
      config.fields.forEach((field, fieldIndex) => {
        const column = selectors[fieldIndex].value;
        if (column !== '') values[field] = row[Number(column)];
      });
      row.forEach((value, column) => {
        if (!usedColumns.has(String(column)) && value) unmatched.push(`${source.headers[column]}: ${value}`);
      });
      if (el('keep-unmapped').checked && unmatched.length) values.internal_notes = [values.internal_notes, ...unmatched].filter(Boolean).join('\n');
      const detail = document.createElement('details'); detail.className = 'import-booking'; detail.open = index === 0;
      const summary = document.createElement('summary'); summary.textContent = `Booking ${index + 1}: ${values.first_name || ''} ${values.last_name || ''} — ${values.event_date || 'date needed'}`;
      detail.append(summary);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn'; remove.textContent = 'Remove this booking';
      remove.hidden = Boolean(config.editing);
      remove.addEventListener('click', () => { detail.remove(); el('confirm-import').checked = false; }); detail.append(remove);
      const commonFields = config.fields.filter(field => !config.eventFields.includes(field));
      const previewFields = el('keep-unmapped').checked ? [...commonFields, 'internal_notes'] : commonFields;
      const groups = {};
      const groupName = field => {
        if (field.startsWith('client_address')) return 'Client address';
        if (field.startsWith('event_address')) return 'Event venue address';
        if (['event_date', 'start_time', 'finish_time', 'event_type', 'theme', 'pitch_fee_required', 'expected_attendees', 'publicity_type', 'location_type', 'charge_type', 'celebrates_christmas_easter', 'additional_info'].includes(field)) return 'Event details';
        if (['payment_preference', 'promo_code', 'signature', 'internal_notes'].includes(field)) return 'Payment and supporting information';
        return 'Client details';
      };
      previewFields.forEach(field => {
        const group = groupName(field);
        if (!groups[group]) {
          const fieldset = document.createElement('fieldset'); fieldset.className = 'import-group';
          const legend = document.createElement('legend'); legend.textContent = group; fieldset.append(legend);
          groups[group] = fieldset; detail.append(fieldset);
        }
        const wrapper = document.createElement('label'); wrapper.className = 'booking-field';
        const required = ['first_name', 'last_name', 'date_of_birth', 'email', 'event_date', 'start_time', 'finish_time', 'event_address'].includes(field);
        const span = document.createElement('span'); span.textContent = label(field) + (field === 'date_of_birth' ? ' (optional for businesses)' : required ? ' (required)' : '');
        const input = document.createElement(field === 'date_of_birth' ? 'input' : 'textarea');
        if (field === 'date_of_birth') input.type = 'date'; else input.rows = 1;
        input.dataset.field = field; input.value = field === 'date_of_birth' ? dateOnly(values[field]) : values[field] || '';
        if (config.pricing && ['total_event_cost', 'travel_charge'].includes(field)) input.readOnly = true;
        const help = document.createElement('small'); help.className = 'import-field-help';
        const updateMissing = () => {
          const addressHasParts = field === 'event_address' && [...detail.querySelectorAll('[data-field^="event_address_"]')].some(control => control.value.trim());
          const business = ['business', 'company', 'organisation', 'organization'].includes((detail.querySelector('[data-field="client_type"]')?.value || '').trim().toLowerCase());
          const placeholderBirth = field === 'date_of_birth' && !business && !input.value && ['00/00/00', '00/00/0000', '0000-00-00'].includes(String(values[field] || '').trim());
          const missing = required && !(field === 'date_of_birth' && business) && ((!input.value.trim() && !addressHasParts) || placeholderBirth);
          input.setAttribute('aria-invalid', String(missing));
          help.textContent = placeholderBirth ? 'The source contains a placeholder birth date. Enter the correct date or remove this booking.' : missing ? (field === 'event_address' ? 'Enter the separate venue fields below or a full address here.' : 'Missing from file — enter this before importing.') : '';
        };
        input.addEventListener('input', () => { el('confirm-import').checked = false; updateMissing(); });
        wrapper.append(span, input, help); groups[group].append(wrapper);
        // Address components are added after their full-address fallback.
        if (required) detail.addEventListener('input', updateMissing);
        if (required) queueMicrotask(updateMissing);
      });
      const heading = document.createElement('h3'); heading.textContent = 'Event dates'; detail.append(heading);
      const eventDays = document.createElement('div'); eventDays.className = 'import-event-days'; detail.append(eventDays);
      try {
        importedDays(row, values).forEach(day => addDay(eventDays, day));
        summary.textContent = `Booking ${index + 1}: ${values.first_name || ''} ${values.last_name || ''} — ${eventDays.children.length} event day(s)`;
      } catch (error) {
        detail.dataset.scheduleError = error.message;
        const warning = document.createElement('p'); warning.textContent = error.message; warning.className = 'import-field-help'; detail.append(warning);
      }
      const add = document.createElement('button'); add.type = 'button'; add.className = 'btn'; add.textContent = 'Add another event date';
      add.addEventListener('click', () => {
        const previous = eventDays.lastElementChild;
        addDay(eventDays, previous ? {...dayValues(previous), event_date: '', _original_index: undefined} : {});
      }); detail.append(add);
      el('preview').append(detail);
    });
    el('review-panel').hidden = false;
    message(config.editing ? 'Edit the details below, review your changes, then save. Client-visible changes will appear in the portal.' : `${source.rows.length} bookings ready to review. Columns were matched automatically. Check the details and addresses below; use “Adjust automatic column matching” only if a match needs changing.`);
    el('review-panel').scrollIntoView({behavior: 'smooth'});
    refreshPricing();
  });
  el('save-button').addEventListener('click', async () => {
    if (!el('confirm-import').checked) { message('Review the bookings and tick the confirmation box first. Editing any field clears this confirmation.', [], true); return; }
    const invalid = [...el('preview').children].find(detail => detail.dataset.scheduleError);
    if (invalid) { message('An imported schedule could not be read. Correct that schedule in the source file and upload it again.', [invalid.dataset.scheduleError], true); return; }
    const rows = editorRows();
    if (!rows.length) { message('There are no bookings to import.', [], true); return; }
    el('save-button').disabled = true;
    try {
      message('Validating and saving bookings…'); const result = await send({rows, version: config.version}, true);
      if (result) { location.assign(result.redirect || '/admin/bookings?imported=' + result.imported); return; }
    } catch (_) { message('The result could not be confirmed. Check bookings before retrying; duplicate bookings will be rejected.', [], true); }
    finally { el('save-button').disabled = false; }
  });
  if (config.initialSource) {
    source = config.initialSource;
    selectors = config.fields.map(field => ({value: String(source.headers.indexOf(field))}));
    selectors.forEach(select => { if (select.value === '-1') select.value = ''; });
    el('review-button').click();
  }
})();
