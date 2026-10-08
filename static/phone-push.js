(() => {
  const panel = document.querySelector('[data-push-api]');
  if (!panel) return;
  const status = panel.querySelector('[data-push-status]');
  const enable = panel.querySelector('[data-push-enable]');
  const disable = panel.querySelector('[data-push-disable]');
  const api = panel.dataset.pushApi;
  let config, registration;
  const show = message => { status.textContent = message; };
  async function save(method, subscription) {
    const response = await fetch(api, {method, headers: {'Content-Type':'application/json','X-CSRF-Token':config.csrf},
      body:JSON.stringify({subscription:subscription.toJSON(),preferences:Array.from(panel.querySelectorAll('input:checked'), el => el.value)})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Please sign in again and retry.');
  }
  async function init() {
    if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      enable.disabled = disable.disabled = true;
      show('This browser cannot enable push here. Use HTTPS and a supported browser; on iPhone open the portal from its Home Screen icon.'); return;
    }
    const response = await fetch(api);
    if (!response.ok) throw Error('Please sign in again to manage phone notifications.');
    config = await response.json();
    registration = await navigator.serviceWorker.register('/phone-push-worker.js');
    await navigator.serviceWorker.ready;
    enable.disabled = !config.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      const saved = await fetch(api + '?endpoint=' + encodeURIComponent(subscription.endpoint));
      if (saved.ok) {
        const data = await saved.json();
        if (data.preferences) panel.querySelectorAll('input').forEach(el => { el.checked = data.preferences.includes(el.value); });
      }
    }
    show(!config.ready ? 'Phone notifications need server configuration before they can be enabled.' :
      subscription ? 'This browser has a subscription. Save preferences to link it to this signed-in account.' : 'Choose your alerts, then enable notifications on this device.');
  }
  enable.addEventListener('click', async () => {
    if (!config || !registration) return;
    enable.disabled = true;
    try {
      if (await Notification.requestPermission() !== 'granted') throw Error('Permission was not granted. You can change it in your browser or phone settings.');
      const key = Uint8Array.from(atob(config.public_key.replace(/-/g,'+').replace(/_/g,'/')), char => char.charCodeAt(0));
      const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
      await save('POST',subscription); show('Phone notifications enabled. Your preferences have been saved for this device.');
    } catch (error) { show(error.message); }
    finally { enable.disabled = false; }
  });
  disable.addEventListener('click', async () => {
    try {
      if (!registration || !config) return;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) { await save('DELETE',subscription); await subscription.unsubscribe(); }
      show('Phone notifications are off on this device.');
    } catch (error) { show(error.message); }
  });
  init().catch(error => show(error.message));
})();
