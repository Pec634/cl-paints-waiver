(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const colours = ['#f52f83', '#a379df', '#ffb43f', '#40c9bf'];
    const welcome = document.querySelector('.client-login-celebration');
    if (welcome && !reducedMotion.matches) {
        const celebration = document.createElement('div');
        celebration.className = 'client-confetti';
        celebration.setAttribute('aria-hidden', 'true');
        for (let i = 0; i < 32; i++) {
            const fleck = document.createElement('span');
            fleck.style.cssText = `--paint:${colours[i % 4]};left:${(i * 37) % 100}%;--delay:${(i % 7) * .08}s;--drift:${i % 2 ? 60 : -60}px`;
            celebration.append(fleck);
        }
        document.body.append(celebration);
        window.setTimeout(() => celebration.remove(), 4000);
    }
    const panel = document.querySelector('.client-auth');
    const form = panel?.querySelector('form');
    if (!form) return;
    const artwork = document.createElement('div');
    artwork.className = 'client-paint-scene';
    artwork.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 8; i++) {
        const bubble = document.createElement('span');
        bubble.className = 'client-paint-bubble';
        bubble.style.cssText = `--paint:${colours[i % 4]};--size:${24 + (i % 3) * 18}px;--left:${i % 2 ? 90 : 3}%;--top:${8 + i * 11}%;--delay:-${i * 1.3}s;--duration:${7 + i % 4}s`;
        artwork.append(bubble);
    }
    panel.prepend(artwork);
    const logo = panel.querySelector('.client-auth-logo');
    if (logo) {
        const halo = document.createElement('div');
        halo.className = 'client-logo-halo';
        logo.before(halo);
        halo.append(logo);
        halo.classList.add('client-brush-reveal');
    }
    const button = form.querySelector('button[type="submit"]');
    const codeInput = form.querySelector('[name="code"]');
    if (codeInput) {
        const painting = document.createElement('div');
        painting.className = 'client-code-painting';
        painting.setAttribute('aria-hidden', 'true');
        const slots = Array.from({length: 6}, () => {
            const slot = document.createElement('span');
            slot.className = 'client-painted-digit';
            painting.append(slot);
            return slot;
        });
        const entry = document.createElement('div');
        entry.className = 'client-painted-entry';
        codeInput.before(entry);
        entry.append(codeInput, painting);
        let previous = '';
        const paintDigits = () => {
            const value = codeInput.value;
            slots.forEach((slot, index) => {
                const digit = value[index] || '';
                const changed = digit !== previous[index];
                slot.classList.remove('is-painting');
                slot.textContent = digit;
                slot.classList.toggle('has-digit', Boolean(digit));
                if (digit && changed && !reducedMotion.matches) {
                    // Restart the brush sweep when a digit is replaced quickly.
                    void slot.offsetWidth;
                    slot.classList.add('is-painting');
                }
            });
            previous = value;
        };
        codeInput.addEventListener('input', paintDigits);
        window.addEventListener('pageshow', paintDigits);
        paintDigits();
    }
    const status = document.createElement('p');
    status.className = 'client-action-status';
    status.setAttribute('role', 'status');
    form.append(status);
    if (!form.querySelector('[name="code"]')) {
        const envelope = document.createElement('span');
        envelope.className = 'client-mail-animation';
        envelope.setAttribute('aria-hidden', 'true');
        status.before(envelope);
    }
    let sending = false;
    form.addEventListener('submit', (event) => {
        if (sending) { event.preventDefault(); return; }
        sending = true;
        panel.classList.add('client-auth-sending');
        form.setAttribute('aria-busy', 'true');
        button.disabled = true;
        status.textContent = form.querySelector('[name="code"]')
            ? 'Checking your code…' : 'Sending your verification code…';
        if (!reducedMotion.matches) {
            const panelBounds = panel.getBoundingClientRect();
            const buttonBounds = button.getBoundingClientRect();
            for (let i = 0; i < 24; i++) {
                const drop = document.createElement('span');
                drop.className = 'client-paint-drop';
                const angle = i * Math.PI * 2 / 24;
                const distance = 65 + (i % 4) * 25;
                drop.style.cssText = `--paint:${colours[i % 4]};--dx:${Math.cos(angle) * distance}px;--dy:${Math.sin(angle) * distance}px;left:${buttonBounds.left - panelBounds.left + buttonBounds.width / 2}px;top:${buttonBounds.top - panelBounds.top + buttonBounds.height / 2}px`;
                panel.append(drop);
                drop.addEventListener('animationend', () => drop.remove(), {once: true});
            }
        }
    });
    window.addEventListener('pageshow', () => {
        sending = false;
        panel.classList.remove('client-auth-sending');
        form.removeAttribute('aria-busy');
        button.disabled = false;
        status.textContent = '';
        panel.querySelectorAll('.client-paint-drop').forEach(drop => drop.remove());
    });
})();
