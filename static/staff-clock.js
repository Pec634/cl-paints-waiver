document.querySelectorAll('[data-staff-clock]').forEach(form => {
  let locating = false;
  form.addEventListener('submit', event => {
    const button = event.submitter;
    if (!button || !['in', 'out'].includes(button.value)) return;
    event.preventDefault();
    if (locating) return;
    const status = form.querySelector('[data-location-status]');
    const clear = () => ['latitude', 'longitude', 'accuracy', 'location_at'].forEach(name => { form.elements[name].value = ''; });
    clear();
    const submit = () => {
      const action = document.createElement('input');
      action.type = 'hidden'; action.name = 'action'; action.value = button.value; form.append(action);
      HTMLFormElement.prototype.submit.call(form);
    };
    const unavailable = message => {
      locating = false;
      button.disabled = false;
      status.textContent = message + ' Explain why location is unavailable, then press the clocking button again.';
      if (form.elements.location_reason.value.trim()) submit();
      else form.elements.location_reason.focus();
    };
    if (!window.isSecureContext || !navigator.geolocation) {
      unavailable('Location requires a supported browser and HTTPS or localhost.'); return;
    }
    locating = true; button.disabled = true;
    status.textContent = 'Getting your current location…';
    navigator.geolocation.getCurrentPosition(position => {
      form.elements.latitude.value = position.coords.latitude;
      form.elements.longitude.value = position.coords.longitude;
      form.elements.accuracy.value = position.coords.accuracy;
      form.elements.location_at.value = position.timestamp;
      status.textContent = `Location captured (accuracy about ${Math.round(position.coords.accuracy)} metres). Saving…`;
      submit();
    }, () => unavailable('Your device did not provide a location.'), {enableHighAccuracy: true, timeout: 12000, maximumAge: 0});
  });
});
