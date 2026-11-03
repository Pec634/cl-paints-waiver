(() => {
  const root = document.querySelector('[data-creates-address-lookup]');
  const form = document.getElementById('creates-form');
  if (!root || !form) return;
  const host = root.querySelector('[data-address-search-host]');


  const status = root.querySelector('[data-address-status]');
  let active = false, revision = 0, widget = null, loading = null, starting = false;
  const unavailable = () => {
    active = false; revision++;
    status.textContent = 'Google address lookup is unavailable. Please enter your address manually below.';
    host.hidden = true;
  };
  const load = () => {
    if (window.google?.maps?.importLibrary) return Promise.resolve();
    if (!loading) loading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const timer = setTimeout(() => { script.remove(); reject(new Error('Lookup timed out')); }, 12000);
      window.initializeCreatesAddressAutocomplete = () => { clearTimeout(timer); resolve(); };
      const params = new URLSearchParams({key: root.dataset.googleKey, callback: 'initializeCreatesAddressAutocomplete', loading: 'async', v: 'weekly'});
      script.src = 'https://maps.googleapis.com/maps/api/js?' + params;
      script.async = true; script.onerror = () => { clearTimeout(timer); script.remove(); reject(new Error('Lookup unavailable')); };
      document.head.append(script);
    }).catch(error => { loading = null; throw error; });
    return loading;
  };
  ['address_line1','address_line2','address_street','village','town','county','postcode','country'].forEach(name => form.elements[name].addEventListener('input', () => { revision++; }));
  async function initialize() {
    if (form.fulfilment.value !== 'postage' || !root.dataset.googleKey) return;
    active = true;
    if (widget) { host.hidden = false; return; }
    if (starting) return;
    starting = true;
    active = true;
    status.textContent = 'Loading UK address lookup…';
    try {
      await load();
      if (!widget) {
        const {PlaceAutocompleteElement} = await google.maps.importLibrary('places');
        widget = new PlaceAutocompleteElement();
        widget.includedRegionCodes = ['gb']; widget.placeholder = 'Search your street, house or postcode';
        widget.setAttribute('aria-label','Find your UK delivery address with Google Maps');
        widget.style.width = '100%';
        widget.addEventListener('gmp-error', unavailable);
        widget.addEventListener('gmp-select', async ({placePrediction}) => {
          if (!active) return;
          const current = ++revision;
          try {
            const place = placePrediction.toPlace();
            await place.fetchFields({fields:['addressComponents']});
            if (!active || current !== revision || form.fulfilment.value !== 'postage') return;
            const components = place.addressComponents || [];
            const component = (type, short = false) => {
              const item = components.find(part => part.types.includes(type));
              return item ? (short ? item.shortText : item.longText) || '' : '';
            };
            if (component('country',true).toUpperCase() !== 'GB') {
              status.textContent = 'Please choose a UK address or enter your UK delivery address manually.'; return;
            }
            const values = {
              address_line1: [component('premise'),component('street_number')].filter(Boolean).join(', '),
              address_line2: component('subpremise'),
              address_street: component('route'),
              village: component('locality') !== component('postal_town') && component('postal_town') ? component('locality') : component('sublocality_level_1') || component('sublocality'),
              town: component('postal_town') || component('locality'),
              county: component('administrative_area_level_2') || component('administrative_area_level_1'),
              postcode: component('postal_code'),
              country: component('country')
            };
            for (const [name,value] of Object.entries(values)) {
              form.elements[name].value = value;
              form.elements[name].dispatchEvent(new Event('input',{bubbles:true}));
              form.elements[name].dispatchEvent(new Event('change',{bubbles:true}));
            }
            status.textContent = 'Address filled. Check the house name or number, suite or flat, street, village, town, county, postcode and country. Complete any missing required fields below.';
          } catch {
            if (active && current === revision) unavailable();
          }
        });
        host.append(widget);
      }
      if (active && form.fulfilment.value === 'postage') {
        host.hidden = false;
        status.textContent = 'Search and choose a suggestion. You can still enter or edit every address field below.';
      }
    } catch { if (active) unavailable(); }
    finally { starting = false; }
  }
  form.fulfilment.addEventListener('change', () => {
    revision++; active = form.fulfilment.value === 'postage';
    if (active) initialize();
  });
  initialize();
})();
