(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('import-config').textContent);
  const el = id => document.getElementById(id);
  const addressLabels = {property: 'House / flat / suite or address line 1', street: 'Street / address line 2',
    city: 'City / town', state: 'County / state', postcode: 'Postcode', country: 'Country', country_code: 'Country code'};
  const label = name => {
    const address = /^(client|event)_address_(.*)$/.exec(name);
    if (address) return addressLabels[address[2]];
    if (name === 'client_address' || name === 'event_address') return 'Full address (used when separate fields are blank)';
    return name.replaceAll('_', ' ').replace(/^./, character => character.toUpperCase());
  };
  const normal = name => name.toLowerCase().replace(/[^a-z0-9]/g, '');
  const aliases = {firstname: 'first_name', surname: 'last_name', lastname: 'last_name',
    emailaddress: 'email', telephone: 'phone', phonenumber: 'phone', mobile: 'phone',
    dob: 'date_of_birth', date: 'event_date', bookingdate: 'event_date',
    venue: 'event_address', venueaddress: 'event_address', endtime: 'finish_time',
    notes: 'additional_info', cost: 'total_event_cost', postcodeaddress: 'client_address'};
  let source, selectors = [];
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
      remove.addEventListener('click', () => { detail.remove(); el('confirm-import').checked = false; }); detail.append(remove);
      const previewFields = el('keep-unmapped').checked ? [...config.fields, 'internal_notes'] : config.fields;
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
        const span = document.createElement('span'); span.textContent = label(field) + (required ? ' (required)' : '');
        const input = document.createElement('textarea'); input.rows = 1; input.dataset.field = field; input.value = values[field] || '';
        const help = document.createElement('small'); help.className = 'import-field-help';
        const updateMissing = () => {
          const addressHasParts = field === 'event_address' && [...detail.querySelectorAll('[data-field^="event_address_"]')].some(control => control.value.trim());
          const missing = required && !input.value.trim() && !addressHasParts;
          input.setAttribute('aria-invalid', String(missing));
          help.textContent = missing ? (field === 'event_address' ? 'Enter the separate venue fields below or a full address here.' : 'Missing from file — enter this before importing.') : '';
        };
        input.addEventListener('input', () => { el('confirm-import').checked = false; updateMissing(); });
        wrapper.append(span, input, help); groups[group].append(wrapper);
        // Address components are added after their full-address fallback.
        if (required) detail.addEventListener('input', updateMissing);
        if (required) queueMicrotask(updateMissing);
      });
      el('preview').append(detail);
    });
    el('review-panel').hidden = false;
    message(`${source.rows.length} bookings ready to review. Columns were matched automatically. Check the details and addresses below; use “Adjust automatic column matching” only if a match needs changing.`);
    el('review-panel').scrollIntoView({behavior: 'smooth'});
  });
  el('save-button').addEventListener('click', async () => {
    if (!el('confirm-import').checked) { message('Review the bookings and tick the confirmation box first. Editing any field clears this confirmation.', [], true); return; }
    const rows = [...el('preview').children].map(detail => Object.fromEntries([...detail.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.value])));
    if (!rows.length) { message('There are no bookings to import.', [], true); return; }
    el('save-button').disabled = true;
    try {
      message('Validating and saving bookings…'); const result = await send({rows}, true);
      if (result) { location.assign('/admin/bookings?imported=' + result.imported); return; }
    } catch (_) { message('The result could not be confirmed. Check bookings before retrying; duplicate bookings will be rejected.', [], true); }
    finally { el('save-button').disabled = false; }
  });
})();
