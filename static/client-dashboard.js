(() => {
    const container = document.querySelector('[data-dashboard-accordion]');
    if (!container) return;
    const panels = [...container.children].filter(element =>
        element.matches('section.panel'));
    panels.sort((left, right) =>
        left.querySelector('h2').textContent.trim().localeCompare(
            right.querySelector('h2').textContent.trim(), 'en-GB', {sensitivity: 'base'}));
    panels.forEach(panel => {
        const heading = panel.querySelector('h2');
        const details = document.createElement('details');
        details.className = 'panel client-dashboard-dropdown';
        details.setAttribute('name', 'client-dashboard-sections');
        const summary = document.createElement('summary');
        summary.textContent = heading ? heading.textContent.trim() : 'Booking and reward overview';
        container.append(details);
        details.append(summary, panel);
        details.addEventListener('toggle', () => {
            if (!details.open) return;
            container.querySelectorAll(':scope > details[open]').forEach(other => {
                if (other !== details) other.open = false;
            });
        });
    });
})();
