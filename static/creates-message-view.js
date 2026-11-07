(() => {
  const form = document.querySelector('[data-message-view]');
  if (!form) return;
  const status = document.querySelector('[data-view-status]');
  let sent = false;
  let pending = false;
  async function recordView() {
    if (sent || pending || document.visibilityState !== 'visible') return;
    pending = true;
    try {
      const response = await fetch(window.location.pathname, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        keepalive: true,
        headers: { 'Accept': 'text/html' }
      });
      if (!response.ok) throw new Error('Viewing could not be recorded');
      sent = true;
      status.textContent = 'CL Creates has been notified that you viewed this message.';
    } catch (_) {
      status.textContent = 'Viewing confirmation could not be sent. It will retry when you return to this tab or reconnect.';
    } finally {
      pending = false;
    }
  }
  document.addEventListener('visibilitychange', recordView);
  window.addEventListener('pageshow', recordView);
  window.addEventListener('online', recordView);
  recordView();
})();
