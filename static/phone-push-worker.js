self.addEventListener('push', event => {
  let data;
  try { data = event.data.json(); } catch (_) { data = {}; }
  event.waitUntil(self.registration.showNotification(data.title || 'CL Paints update', {
    body: data.body || 'Open your portal to view the details.',
    icon: '/static/cl-paints-logo.jpg', data: {url: data.url || '/client/notifications'}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data.url, self.location.origin);
  if (target.origin !== self.location.origin || !/^\/(admin|client)\//.test(target.pathname)) return;
  event.waitUntil(clients.openWindow(target.href));
});
