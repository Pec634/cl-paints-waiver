(() => {
    const key = 'cl-paints-display-settings';
    const root = document.documentElement;
    const systemMotion = matchMedia('(prefers-reduced-motion: reduce)');
    let settings = {};
    try { settings = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) { settings = {}; }
    const apply = () => {
        const size = ['100', '112', '125'].includes(String(settings.size)) ? String(settings.size) : '100';
        root.style.fontSize = `${size}%`;
        root.classList.toggle('portal-reduced-motion', settings.motion === undefined ? systemMotion.matches : Boolean(settings.motion));
        root.classList.toggle('portal-high-contrast', Boolean(settings.contrast));
    };
    apply();
    systemMotion.addEventListener('change', apply);
    document.addEventListener('DOMContentLoaded', () => {
        const size = document.getElementById('portal-text-size');
        const motion = document.getElementById('portal-reduce-motion');
        const contrast = document.getElementById('portal-high-contrast');
        const status = document.getElementById('portal-display-status');
        const sync = () => {
            size.value = String(settings.size || '100');
            motion.checked = settings.motion === undefined ? systemMotion.matches : Boolean(settings.motion);
            contrast.checked = Boolean(settings.contrast);
        };
        const save = () => {
            settings = {size: size.value, motion: motion.checked, contrast: contrast.checked};
            apply();
            try { localStorage.setItem(key, JSON.stringify(settings)); status.textContent = 'Display settings saved.'; }
            catch (_) { status.textContent = 'Settings apply now; browser storage is unavailable.'; }
        };
        if (size && motion && contrast) {
            sync();
            [size, motion, contrast].forEach(input => input.addEventListener('change', save));
            document.getElementById('portal-reset-display').addEventListener('click', () => {
                settings = {}; apply(); sync();
                try { localStorage.removeItem(key); } catch (_) {}
                status.textContent = 'Default display settings restored.';
            });
        }
        const main = document.querySelector('main');
        if (main) {
            main.id = main.id || 'portal-main';
            main.setAttribute('tabindex', '-1');
            document.querySelector('.portal-skip-link').href = '#' + main.id;
        }
        const adminMain = document.querySelector('.admin main');
        const toolbar = document.getElementById('portal-admin-toolbar');
        if (adminMain && toolbar) adminMain.prepend(toolbar.content.cloneNode(true));
        document.querySelectorAll('[data-open-display]').forEach(link => link.addEventListener('click', () => {
            const controls = document.querySelector('.portal-display-controls');
            controls.open = true;
            document.getElementById('portal-text-size').focus();
        }));
    });
})();
