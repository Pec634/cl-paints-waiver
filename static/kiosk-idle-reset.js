(() => {
  const dialog = document.getElementById('kioskIdleDialog');
  const form = document.querySelector('form.client-form');
  if (!dialog || !form) return;
  const idleDuration = 120000;
  const warningDuration = 20000;
  const countdown = document.getElementById('kioskIdleCountdown');
  let lastActivity = Date.now(), warningDeadline = null, leaving = false;
  const keepGoing = () => {
    lastActivity = Date.now();
    warningDeadline = null;
    if (dialog.open) dialog.close();
  };
  const activity = () => { if (!dialog.open && !leaving) lastActivity = Date.now(); };
  ['pointerdown', 'keydown', 'input', 'scroll'].forEach(event => document.addEventListener(event, activity, {passive:true, capture:true}));
  document.getElementById('kioskIdleContinue').addEventListener('click', keepGoing);
  dialog.addEventListener('cancel', event => { event.preventDefault(); keepGoing(); });
  const reset = async () => {
    if (leaving) return;
    leaving = true;
    dialog.close();
    // Clear visible personal information immediately, even if connectivity drops.
    form.hidden = true;
    form.reset();
    for (const input of form.querySelectorAll('input:not([type="hidden"]), textarea, select')) {
      if (input.type === 'checkbox' || input.type === 'radio') input.checked = false;
      else input.value = '';
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      await fetch(dialog.dataset.resetUrl, {method:'POST', credentials:'same-origin',
        headers:{'X-CSRF-Token':dialog.dataset.csrf}, signal:controller.signal});
    } catch (_) { /* The fresh page still clears this device if reset is offline. */ }
    finally { clearTimeout(timeout); location.replace(dialog.dataset.formUrl); }
  };
  document.getElementById('kioskIdleReset').addEventListener('click', reset);
  const check = () => {
    if (leaving) return;
    const now = Date.now();
    if (!warningDeadline && now - lastActivity >= idleDuration) {
      warningDeadline = lastActivity + idleDuration + warningDuration;
      if (now < warningDeadline) dialog.showModal();
    }
    if (warningDeadline) {
      const remaining = Math.max(0, Math.ceil((warningDeadline - now) / 1000));
      countdown.textContent = remaining;
      if (!remaining) reset();
    }
  };
  const timer = setInterval(check, 500);
  document.addEventListener('visibilitychange', check);
  form.addEventListener('submit', event => queueMicrotask(() => {
    if (!event.defaultPrevented) { leaving = true; clearInterval(timer); if (dialog.open) dialog.close(); }
  }));
  window.addEventListener('pagehide', () => clearInterval(timer), {once:true});
})();
