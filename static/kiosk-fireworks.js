(() => {
  const placeholder = document.getElementById('kioskFireworks');
  if (!placeholder) return;
  // Portal settings honour system preferences and the user's display override.
  if (document.documentElement.classList.contains('portal-reduced-motion')) {
    placeholder.remove();
    return;
  }
  const canvas = document.createElement('canvas');
  canvas.id = 'kioskFireworks';
  canvas.setAttribute('aria-hidden', 'true');
  // Inline positioning avoids dependence on a cached global stylesheet.
  canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:100;pointer-events:none;';
  placeholder.replaceWith(canvas);
  const context = canvas.getContext('2d');
  if (!context) { canvas.remove(); return; }
  const width = window.innerWidth, height = window.innerHeight;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.scale(ratio, ratio);
  const colours = ['#ed1977', '#d99100', '#7044d9', '#008f9e', '#e85c22'];
  const positions = [[.18,.24], [.82,.27], [.3,.55], [.73,.6], [.5,.18], [.14,.66], [.86,.48]];
  const radius = Math.min(190, width * .28);
  const started = performance.now();
  let frame;
  const stop = () => {
    cancelAnimationFrame(frame);
    canvas.remove();
    observer.disconnect();
    window.removeEventListener('pagehide', stop);
  };
  const observer = new MutationObserver(() => {
    if (document.documentElement.classList.contains('portal-reduced-motion')) stop();
  });
  observer.observe(document.documentElement, {attributes:true, attributeFilter:['class']});
  window.addEventListener('pagehide', stop, {once:true});
  const draw = now => {
    const elapsed = now - started;
    context.clearRect(0, 0, width, height);
    if (elapsed >= 6500) { stop(); return; }
    positions.forEach(([x,y], burst) => {
      const age = (elapsed - burst * 650) / 1900;
      if (age < 0 || age > 1) return;
      const spread = 1 - Math.pow(1 - age, 3);
      context.globalAlpha = Math.min(1, (1 - age) * 2);
      for (let spark = 0; spark < 40; spark += 1) {
        const angle = spark * Math.PI * 2 / 40;
        const distance = radius * (spark % 2 ? .65 : 1);
        const dx = Math.cos(angle) * distance, dy = Math.sin(angle) * distance;
        const tail = Math.max(0, spread - .09 * (1 - age));
        context.strokeStyle = colours[(burst + spark) % colours.length];
        context.lineWidth = 3.5 * (1 - age * .6);
        context.lineCap = 'round';
        context.beginPath();
        context.moveTo(x * width + dx * tail, y * height + dy * tail + age * age * 65);
        context.lineTo(x * width + dx * spread, y * height + dy * spread + age * age * 65);
        context.stroke();
      }
    });
    context.globalAlpha = 1;
    frame = requestAnimationFrame(draw);
  };
  frame = requestAnimationFrame(draw);
})();
