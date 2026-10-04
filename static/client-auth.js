(() => {
    const panel = document.querySelector('.client-auth');
    const form = panel?.querySelector('form');
    if (!form) return;
    const button = form.querySelector('button[type="submit"]');
    const status = document.createElement('p');
    status.className = 'client-action-status';
    status.setAttribute('role', 'status');
    form.append(status);
    let sending = false;
    form.addEventListener('submit', (event) => {
        if (sending) { event.preventDefault(); return; }
        sending = true;
        panel.classList.add('client-auth-sending');
        form.setAttribute('aria-busy', 'true');
        button.disabled = true;
        status.textContent = form.querySelector('[name="code"]')
            ? 'Checking your code…' : 'Sending your verification code…';
    });
    window.addEventListener('pageshow', () => {
        sending = false;
        panel.classList.remove('client-auth-sending');
        form.removeAttribute('aria-busy');
        button.disabled = false;
        status.textContent = '';
    });
})();
