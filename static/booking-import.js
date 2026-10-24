(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('import-config').textContent);
  const el = id => document.getElementById(id);
  const label = name => name.replaceAll('_', ' ');
  const normal = name => name.toLowerCase().replace(/[^a-z0-9]/g, '');
  const aliases = {firstname: 'first_name', surname: 'last_name', lastname: 'last_name',
    emailaddress: 'email', telephone: 'phone', phonenumber: 'phone', mobile: 'phone',
    dob: 'date_of_birth', date: 'event_date', bookingdate: 'event_date',
    venue: 'event_address', venueaddress: 'event_address', endtime: 'finish_time',
    notes: 'additional_info', cost: 'total_event_cost', postcodeaddress: 'client_address'};
  let source, selectors = [];
  function message(text, errors = []) {
    el('import-status').textContent = text;
    el('import-errors').replaceChildren(...errors.map(text => {
      const li = document.createElement('li'); li.textContent = text; return li;
    }));
  }
  async function send(body, json = false) {
    const response = await fetch(location.pathname, {method: 'POST',
      headers: {'X-Import-Token': config.token, 'Accept': 'application/json', ...(json ? {'Content-Type': 'application/json'} : {})},
      body: json ? JSON.stringify(body) : body});
    if (response.redirected || response.status === 401) {
      message('Your admin session has ended. Sign in again, then reopen Import bookings.'); return null;
    }
    if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
      message(response.status === 413 ? 'The file is too large. Choose a file under 2 MB.' :
        `The server could not process the upload (HTTP ${response.status}). Refresh this page and try again.`);
      return null;
    }
    const result = await response.json();
    if (!response.ok) { message(result.error || 'Import failed.', result.errors); return null; }
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
      source.headers.forEach(header => {
        const wrapper = document.createElement('label'); wrapper.style.display = 'block';
        wrapper.append(document.createTextNode(`${header} → `));
        const select = document.createElement('select');
        select.append(new Option('Do not map', ''));
        config.fields.forEach(field => select.append(new Option(label(field), field)));
        select.value = config.fields.find(field => normal(field) === normal(header)) || aliases[normal(header)] || '';
        wrapper.append(select); el('mapping').append(wrapper); selectors.push(select);
      });
      el('mapping-panel').hidden = false; message(`Read ${source.rows.length} bookings. Check the column matches.`);
    } catch (_) { message('Unable to read the file. Check your connection and admin session.'); }
    finally { button.disabled = false; }
  });
  el('review-button').addEventListener('click', () => {
    const selected = selectors.map(select => select.value).filter(Boolean);
    if (new Set(selected).size !== selected.length) { message('Each destination field can only be matched once.'); return; }
    el('preview').replaceChildren(); el('confirm-import').checked = false;
    source.rows.forEach((row, index) => {
      const values = {}, unmatched = [];
      row.forEach((value, column) => {
        if (selectors[column].value) values[selectors[column].value] = value;
        else if (value) unmatched.push(`${source.headers[column]}: ${value}`);
      });
      if (el('keep-unmapped').checked && unmatched.length) values.internal_notes = [values.internal_notes, ...unmatched].filter(Boolean).join('\n');
      const detail = document.createElement('details'); detail.className = 'import-booking'; detail.open = index === 0;
      const summary = document.createElement('summary'); summary.textContent = `Booking ${index + 1}: ${values.first_name || ''} ${values.last_name || ''} — ${values.event_date || 'date needed'}`;
      detail.append(summary);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn'; remove.textContent = 'Remove this booking';
      remove.addEventListener('click', () => { detail.remove(); el('confirm-import').checked = false; }); detail.append(remove);
      config.fields.forEach(field => {
        const wrapper = document.createElement('label'); wrapper.className = 'booking-field';
        const span = document.createElement('span'); span.textContent = label(field);
        const input = document.createElement('textarea'); input.rows = 1; input.dataset.field = field; input.value = values[field] || '';
        input.addEventListener('input', () => { el('confirm-import').checked = false; });
        wrapper.append(span, input); detail.append(wrapper);
      });
      el('preview').append(detail);
    });
    el('review-panel').hidden = false; message('Preview ready. Review and edit before completing the import.');
    el('review-panel').scrollIntoView({behavior: 'smooth'});
  });
  el('save-button').addEventListener('click', async () => {
    if (!el('confirm-import').checked) { message('Review the bookings and tick the confirmation box first.'); return; }
    const rows = [...el('preview').children].map(detail => Object.fromEntries([...detail.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.value])));
    if (!rows.length) { message('There are no bookings to import.'); return; }
    el('save-button').disabled = true;
    try {
      message('Validating and saving bookings…'); const result = await send({rows}, true);
      if (result) { location.assign('/admin/bookings?imported=' + result.imported); return; }
    } catch (_) { message('The result could not be confirmed. Check bookings before retrying; duplicate bookings will be rejected.'); }
    finally { el('save-button').disabled = false; }
  });
})();
