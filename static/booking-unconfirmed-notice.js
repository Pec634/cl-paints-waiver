(() => {
  const notice = document.getElementById('booking-unconfirmed-notice');
  if (!notice) return;
  const showNotice = () => {
    if (!notice.open) notice.showModal();
  };
  showNotice();
  window.addEventListener('pageshow', event => {
    if (event.persisted) showNotice();
  });
})();
