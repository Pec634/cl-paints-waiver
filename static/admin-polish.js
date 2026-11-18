(() => {
  const main = document.querySelector('.admin main');
  if (!main) return;

  // Keep data grids within the workspace, including older pages without wrappers.
  main.querySelectorAll('table').forEach(table => {
    if (table.closest('.table-wrap, [class*="-wrap"], [data-admin-scroll]')) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'admin-table-scroll';
    table.before(wrapper);
    wrapper.append(table);
  });
  const scrollAreas = main.querySelectorAll('.table-wrap, .admin-table-scroll, .creates-orders-wrap, .creates-items-wrap, [data-admin-scroll]');
  scrollAreas.forEach(area => {
    if (!area.hasAttribute('tabindex')) area.tabIndex = 0;
    if (!area.hasAttribute('role')) area.setAttribute('role', 'region');
    if (!area.hasAttribute('aria-label') && !area.hasAttribute('aria-labelledby')) {
      const heading = area.closest('section, .panel')?.querySelector('h2, h3');
      area.setAttribute('aria-label', heading ? `${heading.textContent.trim()} — scrollable records` : 'Scrollable records');
    }
  });
})();
