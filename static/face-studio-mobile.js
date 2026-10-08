(() => {
    const studio = document.querySelector('.paint-studio');
    if (!studio) return;
    const mobile = window.matchMedia('(max-width:700px)');
    studio.querySelector('.paint-workspace').id = 'studio-face';
    studio.querySelector('.paint-controls').id = 'studio-tools';
    for (const selector of ['.paint-mission-sidebar', '.paint-progress-sidebar', '.paint-player-progress']) {
        const panel = studio.querySelector(selector);
        if (!panel) continue;
        const details = document.createElement('details');
        details.className = 'studio-mobile-panel';
        details.style.gridArea = getComputedStyle(panel).gridArea;
        const summary = document.createElement('summary');
        summary.textContent = panel.querySelector('h2, h3')?.textContent || 'Your studio rewards';
        panel.before(details);
        details.append(summary, panel);
        const update = () => { details.open = !mobile.matches; };
        update();
        mobile.addEventListener('change', update);
    }
    const controls = studio.querySelector('.paint-controls');
    controls.addEventListener('toggle', event => {
        const group = event.target;
        if (!mobile.matches || !group.open || group.parentElement !== controls) return;
        [...controls.children].forEach(other => {
            if (other !== group && other.tagName === 'DETAILS') other.open = false;
        });
    }, true);
})();
