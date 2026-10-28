document.querySelectorAll('[data-till-denominations]').forEach(form => {
  const update = () => {
    let pence = 0;
    let valid = true;
    form.querySelectorAll('[data-till-pence]').forEach(input => {
      valid = valid && /^\d{1,6}$/.test(input.value) && input.checkValidity();
      pence += Number(input.value) * Number(input.dataset.tillPence);
    });
    form.querySelector('[data-till-count-total]').textContent = valid
      ? new Intl.NumberFormat('en-GB', {style:'currency', currency:'GBP'}).format(pence / 100) : 'Check quantities';
  };
  form.addEventListener('input', update);
  update();
});
