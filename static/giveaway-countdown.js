(() => {
  const counters = [...document.querySelectorAll('[data-claim-countdown]')];
  function update() {
    for (const counter of counters) {
      const remaining = Date.parse(counter.dataset.claimCountdown) - Date.now();
      const days = Math.max(0, Math.ceil(remaining / 86400000));
      counter.querySelector('[data-days-number]').textContent = days;
      counter.querySelector('[data-days-label]').textContent = days > 0 ? `${days === 1 ? 'day' : 'days'} left to claim` : 'Claim period ended';
      if (remaining <= 0) {
        const banner = counter.closest('.giveaway-countdown-banner');
        const claim = banner.querySelector('[data-countdown-claim]');
        if (claim) claim.hidden = true;
        const message = banner.querySelector('[data-countdown-message]');
        if (message) message.textContent = 'The claim deadline has passed. The prize is awaiting a replacement draw.';
      }
    }
  }
  update();
  if (counters.length) {
    window.setInterval(update, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); });
  }
})();
