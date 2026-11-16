(() => {
  const selector = document.querySelector('[data-giveaway-clients]');
  if (!selector) return;
  const rows = Array.from(selector.querySelectorAll('[data-client-option]'));
  const search = selector.querySelector('[data-client-search]');
  const count = selector.querySelector('[data-client-count]');
  const empty = selector.querySelector('[data-client-empty]');
  const update = () => {
    const selected = rows.filter(row => row.querySelector('input').checked).length;
    count.textContent = `${selected} client${selected === 1 ? '' : 's'} selected`;
    empty.hidden = rows.some(row => !row.hidden);
  };
  search.addEventListener('input', () => {
    const term = search.value.trim().toLocaleLowerCase();
    rows.forEach(row => { row.hidden = !row.dataset.search.toLocaleLowerCase().includes(term); });
    update();
  });
  search.addEventListener('keydown', event => {
    if (event.key === 'Enter') event.preventDefault();
  });
  selector.addEventListener('change', update);
  selector.querySelector('[data-select-visible]').addEventListener('click', () => {
    let selected = rows.filter(row => row.querySelector('input').checked).length;
    rows.forEach(row => {
      const box = row.querySelector('input');
      if (!row.hidden && !box.disabled && !box.checked && selected < 500) {
        box.checked = true;
        selected += 1;
      }
    });
    update();
  });
  selector.querySelector('[data-clear-clients]').addEventListener('click', () => {
    rows.forEach(row => { row.querySelector('input').checked = false; });
    update();
  });
  update();
})();
