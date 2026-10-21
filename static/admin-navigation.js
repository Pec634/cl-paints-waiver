(() => {
  const main = document.querySelector('.admin main');
  if (!main) return;
  const key = 'cl-admin-pending-navigation';
  const stateKey = 'clAdminReturnTrail';
  const localUrl = value => {
    try {
      const url = new URL(value, location.href);
      if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol) || /\/(?:logout|login)(?:\/|$)/.test(url.pathname)) return null;
      return url.pathname + url.search + url.hash;
    } catch { return null; }
  };
  const current = localUrl(location.href);
  let trail = [];
  try {
    const pending = JSON.parse(sessionStorage.getItem(key) || 'null');
    sessionStorage.removeItem(key);
    const saved = history.state?.[stateKey];
    const incoming = pending?.target === current ? pending.trail : saved;
    if (Array.isArray(incoming)) trail = incoming.filter(value => typeof value === 'string' && localUrl(value) === value).slice(-30);
    history.replaceState({ ...history.state, [stateKey]: trail }, '');
  } catch { /* Navigation still works if browser storage is unavailable. */ }

  const back = document.createElement('a');
  back.className = 'btn admin-back-link';
  back.href = trail.at(-1) || '/admin/bookings';
  back.textContent = trail.length ? '← Back to previous page' : '← Back to bookings';
  const navigation = document.createElement('nav');
  navigation.className = 'admin-page-navigation';
  navigation.setAttribute('aria-label', 'Return navigation');
  navigation.append(back);
  // Bookings is the fallback starting point rather than linking to itself.
  if (trail.length || location.pathname !== '/admin/bookings') main.prepend(navigation);

  const revealBooking = () => {
    if (!/^#booking-\d+$/.test(location.hash)) return;
    const row = document.getElementById(location.hash.slice(1));
    const details = row?.querySelector('details.booking-detail');
    if (details) details.open = true;
  };
  revealBooking();
  window.addEventListener('hashchange', revealBooking);

  // Keep the return path when a detail page saves a form and redirects to itself.
  document.addEventListener('submit', event => {
    const form = event.target;
    if (event.defaultPrevented || form.method.toLowerCase() !== 'post' || (form.target && form.target !== '_self')) return;
    const target = localUrl(form.action);
    if (!target || new URL(form.action).pathname !== location.pathname) return;
    try { sessionStorage.setItem(key, JSON.stringify({ target, trail })); } catch { /* Forms still submit normally. */ }
  });

  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const target = localUrl(link.href);
    if (!target) return;
    const destination = new URL(link.href);
    if (destination.pathname === location.pathname && destination.search === location.search) return;
    const row = link.closest('[id^="booking-"]');
    const source = row && /^booking-\d+$/.test(row.id)
      ? location.pathname + location.search + '#' + row.id : localUrl(location.href);
    const nextTrail = link === back ? trail.slice(0, -1) : [...trail, source].slice(-30);
    try { sessionStorage.setItem(key, JSON.stringify({ target, trail: nextTrail })); } catch { /* Keep the ordinary link working. */ }
  });
})();
