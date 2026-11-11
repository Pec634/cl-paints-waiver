(() => {
  const root = document.querySelector('[data-client-address-lookup]');
  if (!root) return;
  const form = root.closest('form');
  const host = root.querySelector('[data-address-search-host]');
  const status = root.querySelector('[data-address-status]');
  let revision = 0, started = false;
  const names = ['address_property', 'address_street', 'address_city', 'address_postcode', 'address_country'];
  names.forEach(name => form.elements[name].addEventListener('input', () => { revision++; }));
  const unavailable = () => {
    revision++;
    host.hidden = true;
    status.textContent = 'Google address lookup is unavailable. Please enter the address below.';
  };
  window.clientAddressLookupUnavailable = unavailable;
  const timer = setTimeout(unavailable, 15000);
  window.initializeClientAddressAutocomplete = async () => {
    if (started) return;
    started = true;
    try {
      const {PlaceAutocompleteElement} = await google.maps.importLibrary('places');
      const widget = new PlaceAutocompleteElement();
      widget.includedRegionCodes = ['gb'];
      widget.placeholder = 'Search for a house, street or postcode';
      widget.setAttribute('aria-label', 'Find the client address with Google Maps');
      widget.style.width = '100%';
      widget.addEventListener('gmp-error', unavailable);
      widget.addEventListener('gmp-select', async ({placePrediction}) => {
        const current = ++revision;
        try {
          const place = placePrediction.toPlace();
          await place.fetchFields({fields: ['addressComponents']});
          if (current !== revision) return;
          const component = type => place.addressComponents?.find(part => part.types.includes(type))?.longText || '';
          const values = {
            address_property: ['subpremise', 'premise', 'street_number'].map(component).filter(Boolean).join(', '),
            address_street: component('route'),
            address_city: component('postal_town') || component('locality'),
            address_postcode: component('postal_code'),
            address_country: component('country')
          };
          for (const [name, value] of Object.entries(values)) {
            form.elements[name].value = value;
            form.elements[name].dispatchEvent(new Event('input', {bubbles: true}));
            form.elements[name].dispatchEvent(new Event('change', {bubbles: true}));
          }
          status.textContent = 'Address filled. Check the house or flat number and complete any missing fields before saving.';
        } catch {
          if (current === revision) unavailable();
        }
      });
      host.append(widget);
      host.hidden = false;
      status.textContent = 'Search and select an address, then check the fields below.';
    } catch { unavailable(); }
    finally { clearTimeout(timer); }
  };
})();
