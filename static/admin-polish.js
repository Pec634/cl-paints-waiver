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

  // A compact page index leaves the original forms, IDs and event handlers intact.
  const sections = [...main.querySelectorAll('h2')].filter(heading =>
    !heading.closest('dialog, [hidden], template') && heading.textContent.trim()
  );
  if (sections.length < 4) return;
  const navigation = document.createElement('nav');
  navigation.className = 'admin-section-menu';
  navigation.setAttribute('aria-label', 'Page sections');
  const label = document.createElement('label');
  label.textContent = 'Jump to section';
  const select = document.createElement('select');
  select.add(new Option('Choose a section…', ''));
  sections.forEach((heading, index) => {
    if (!heading.id) {
      let id = `admin-section-${index + 1}`;
      while (document.getElementById(id)) id += '-heading';
      heading.id = id;
    }
    select.add(new Option(heading.textContent.trim(), heading.id));
  });
  select.addEventListener('change', () => {
    const heading = document.getElementById(select.value);
    if (!heading) return;
    let parent = heading.parentElement;
    while (parent && parent !== main) {
      if (parent.tagName === 'DETAILS') parent.open = true;
      parent = parent.parentElement;
    }
    const target = heading.closest('.settings-fold')?.querySelector('summary') || heading;
    if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
    target.focus({preventScroll: true});
    target.scrollIntoView({block: 'start', behavior: 'instant'});
  });
  label.append(select);
  navigation.append(label);
  const header = main.querySelector(':scope > header, :scope > .top');
  if (header) header.after(navigation);
  else main.prepend(navigation);
})();
