(() => {
  const sale = document.getElementById('pos-sale-reference');
  if (sale?.dataset.paymentTimeLeft) {
    const deadline = Date.now() + Number(sale.dataset.paymentTimeLeft);
    const expire = () => location.replace(sale.dataset.tillUrl);
    window.setTimeout(expire, Number(sale.dataset.paymentTimeLeft));
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && Date.now() >= deadline) expire();
    });
  }
  const form = document.querySelector('[data-refund-form]');
  if (form) {
    const fields = [...form.querySelectorAll('[data-refund-price]')];
    const update = () => {
      const total = fields.reduce((sum,field) => sum+Number(field.value)*Number(field.dataset.refundPrice),0);
      form.querySelector('[data-refund-total]').textContent = 'Refund total £'+(total/100).toFixed(2);
    };
    const all = form.querySelector('[data-refund-all]');
    all.hidden = false;
    all.onclick = () => { fields.forEach(field => { field.value=field.max; }); update(); };
    fields.forEach(field => field.addEventListener('input',update));
  }
  try {
    const submitted = sessionStorage.getItem('clpaints-pos-submitted');
    if ('POS-' + submitted === sale.dataset.reference) {
      sessionStorage.removeItem('clpaints-pos-draft');
      sessionStorage.removeItem('clpaints-pos-submitted');
    }
  } catch (_) {}
})();
