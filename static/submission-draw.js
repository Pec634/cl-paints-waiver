(() => {
  const root = document.querySelector('[data-submission-draw]');
  if (!root) return;
  const clients = JSON.parse(root.querySelector('[data-draw-clients]').textContent);
  const handle = root.querySelector('[data-draw-handle]');
  const duration = root.querySelector('[data-draw-duration]');
  const countdown = root.querySelector('[data-draw-countdown]');
  const result = root.querySelector('[data-draw-winner]');
  const ball = root.querySelector('[data-draw-ball]');
  let running = false;
  let startY = null;
  const balls = [...root.querySelectorAll('.draw-mini-ball')];
  const wire = root.querySelector('.draw-wire');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const celebration = document.querySelector('[data-draw-celebration]');
  if (celebration) {
    celebration.querySelector('[data-close-celebration]').addEventListener('click', () => celebration.close());
    celebration.addEventListener('close', () => handle.focus());
  }
  function celebrate(winner) {
    if (!celebration || typeof celebration.showModal !== 'function') return;
    celebration.querySelector('[data-celebration-number]').textContent = winner.number;
    celebration.showModal();
    root.dispatchEvent(new CustomEvent('draw:winner'));
  }
  let motionFrame = 0;
  let wireAngle = 0;
  function animateMix(milliseconds) {
    if (reducedMotion.matches) return;
    const started = performance.now();
    let previous = started;
    function frame(now) {
      const elapsed = Math.min(milliseconds, now - started);
      const ramp = Math.min(1, elapsed / 700, (milliseconds - elapsed) / 900);
      const strength = ramp * ramp * (3 - 2 * ramp);
      wireAngle += Math.min(40, now - previous) * .09 * strength;
      previous = now;
      wire.style.transform = `rotate(${wireAngle}deg)`;
      balls.forEach((item, index) => {
        const phase = elapsed / (650 + index * 19) + index * 1.7;
        const x = Math.sin(phase) * 25 * strength;
        const y = -(1 + Math.sin(phase * .85)) * 52 * strength;
        item.style.transform = `translate3d(${x}px,${y}px,0) rotate(${Math.sin(phase) * 70 * strength}deg)`;
      });
      if (elapsed < milliseconds) motionFrame = requestAnimationFrame(frame);
    }
    motionFrame = requestAnimationFrame(frame);
  }
  function choose() {
    const count = clients.length;
    const limit = 4294967296 - (4294967296 % count);
    const random = new Uint32Array(1);
    do { window.crypto.getRandomValues(random); } while (random[0] >= limit);
    return clients[random[0] % count];
  }
  function spin() {
    if (running || !clients.length) return;
    let winner;
    try { winner = root.dataset.drawUrl ? null : choose(); } catch (_) {
      result.textContent = 'Secure random selection is unavailable. Please reload in a supported browser.';
      return;
    }
    running = true;
    root.dispatchEvent(new CustomEvent('draw:started'));
    startY = null;
    handle.classList.remove('is-dragging');
    handle.disabled = true;
    duration.disabled = true;
    root.classList.remove('draw-revealed');
    root.classList.add('draw-running');
    ball.textContent = '?';
    result.textContent = 'The draw is running. Mixing the balls…';
    const seconds = Number(duration.value);
    animateMix(seconds * 1000);
    const ends = Date.now() + seconds * 1000;
    countdown.textContent = `${seconds} seconds remaining`;
    const timer = window.setInterval(() => {
      countdown.textContent = `${Math.max(0, Math.ceil((ends - Date.now()) / 1000))} seconds remaining`;
    }, 200);
    window.setTimeout(async () => {
      window.clearInterval(timer);
      cancelAnimationFrame(motionFrame);
      balls.forEach(item => item.style.removeProperty('transform'));
      root.classList.remove('draw-running');
      if (root.dataset.drawUrl) {
        countdown.textContent = 'Saving the winner and notifying entrants…';
        try {
          const response = await fetch(root.dataset.drawUrl, {
            method: 'POST', body: new URLSearchParams({csrf_token: root.dataset.csrf, draw_version: root.dataset.drawVersion || ''}),
            headers: {'Accept': 'application/json'}
          });
          if (!response.ok) throw new Error('Draw could not be saved');
          winner = await response.json();
          if (!winner.number || !winner.saved) throw new Error('Invalid draw result');
        } catch (_) {
          result.textContent = 'Could not confirm the saved result. Refresh this page to check before trying again.';
          countdown.textContent = 'Check saved result';
          running = false;
          duration.disabled = false;
          return;
        }
      }
      root.classList.add('draw-revealed');
      ball.textContent = winner.number;
      countdown.textContent = 'Here comes the winning ball!';
      window.setTimeout(() => {
        result.replaceChildren();
        const label = document.createElement('span');
        label.textContent = 'WINNING CLIENT ACCOUNT';
        const number = document.createElement('strong');
        number.textContent = winner.number;
        result.append(label, number);
        countdown.textContent = 'Winner selected';
        running = false;
        handle.disabled = Boolean(root.dataset.drawUrl);
        duration.disabled = false;
        handle.querySelector('.draw-handle-label').textContent = root.dataset.drawUrl ? 'Draw completed' : 'Draw again';
        celebrate(winner);
      }, 1200);
    }, seconds * 1000);
  }
  handle.addEventListener('click', spin);
  handle.addEventListener('pointerdown', event => {
    if (running) return;
    startY = event.clientY;
    handle.classList.add('is-dragging');
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (startY === null || running) return;
    const distance = Math.max(0, Math.min(60, event.clientY - startY));
    handle.style.setProperty('--pull', `${distance}px`);
    if (distance >= 45) {
      startY = null;
      spin();
      handle.style.removeProperty('--pull');
    }
  });
  function release() {
    startY = null;
    handle.classList.remove('is-dragging');
    handle.style.removeProperty('--pull');
  }
  handle.addEventListener('pointerup', release);
  handle.addEventListener('pointercancel', release);
})();
