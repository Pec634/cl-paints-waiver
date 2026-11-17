(() => {
  const popup = document.getElementById('pos-popup');
  const launch = document.getElementById('pos-popup-open');
  const close = document.getElementById('pos-popup-close');
  if (!popup || typeof popup.showModal !== 'function') return;
  const open = () => {
    if (popup.open) return;
    popup.showModal();
    document.documentElement.classList.add('pos-modal-open');
  };
  const revealSection = () => {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
    if (!target || !popup.contains(target)) return;
    open();
    for (let section = target; section && section !== popup; section = section.parentElement) {
      if (section.tagName === 'DETAILS') section.open = true;
    }
    requestAnimationFrame(() => target.scrollIntoView({block: 'start'}));
  };
  launch.hidden = false;
  close.hidden = false;
  launch.addEventListener('click', open);
  close.addEventListener('click', () => popup.close());
  popup.addEventListener('close', () => {
    if (popup.open) return;
    document.documentElement.classList.remove('pos-modal-open');
    launch.focus();
  });
  // An open non-modal dialog keeps the till available when JavaScript is disabled.
  popup.removeAttribute('open');
  open();
  revealSection();
  window.addEventListener('hashchange', revealSection);
})();
