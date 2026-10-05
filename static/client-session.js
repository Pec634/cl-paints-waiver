(() => {
    const timer = document.querySelector('[data-client-session-expires]');
    if (!timer) return;
    const expires = Number(timer.dataset.clientSessionExpires) * 1000;
    const update = () => {
        const remaining = Math.max(0, Math.ceil((expires - Date.now()) / 1000));
        if (!remaining) {
            window.location.replace(timer.dataset.loginUrl);
            return;
        }
        const days = Math.floor(remaining / 86400);
        const hours = Math.floor((remaining % 86400) / 3600);
        const minutes = Math.floor((remaining % 3600) / 60);
        const seconds = remaining % 60;
        timer.textContent = `Automatic sign-out in ${days ? days + ' days ' : ''}${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    };
    update();
    window.setInterval(update, 1000);
    window.addEventListener('pageshow', update);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); });
})();
