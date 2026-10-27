(() => {
  const form = document.querySelector('[data-cashup-form]');
  if (!form) return;
  const currency = new Intl.NumberFormat('en-GB', {style:'currency', currency:'GBP'});
  const counters = [...form.querySelectorAll('[data-denomination-counter]')];
  const update = () => {
    const counted = {};
    counters.forEach(counter => {
      const field = counter.dataset.denominationCounter;
      const enabled = counter.querySelector('[data-count-toggle]').checked;
      const grid = counter.querySelector('.denomination-grid');
      grid.hidden = !enabled;
      let total=0, valid=true;
      const counts = {};
      counter.querySelectorAll('[data-pence]').forEach(input => {
        input.disabled = !enabled;
        const quantity = Number(input.value);
        if (!/^\d{1,6}$/.test(input.value) || !input.checkValidity()) valid=false;
        counts[input.dataset.pence] = quantity;
        const subtotal = quantity * Number(input.dataset.pence);
        total += subtotal;
        input.nextElementSibling.textContent = currency.format(subtotal/100);
      });
      counter.querySelector('[data-denomination-total]').textContent = enabled && valid ? currency.format(total/100) : (enabled ? 'Check counts' : 'Manual total');
      const amount = form.elements.namedItem(field);
      const locked = counter.querySelector('[data-count-toggle]').disabled;
      amount.readOnly = locked || enabled;
      if (enabled && valid && !locked) amount.value = (total/100).toFixed(2);
      if (enabled && valid) counted[field]=counts;
    });
    const plan = form.querySelector('[data-float-plan]');
    if (!plan) return;
    const opening = counted.opening_till, closing = counted.closing_till;
    const ready = opening && closing;
    plan.querySelector('[data-float-table]').hidden = !ready;
    let keepTotal=0, shortTotal=0, surplusTotal=0;
    if (ready) plan.querySelectorAll('[data-float-pence]').forEach(row => {
      const pence = row.dataset.floatPence;
      const target=opening[pence], available=closing[pence];
      const keep=Math.min(target,available), short=Math.max(0,target-available), surplus=available-keep;
      for (const [name,value] of Object.entries({target,available,keep,short,surplus})) row.querySelector('[data-float-'+name+']').textContent=value;
      keepTotal+=keep*Number(pence); shortTotal+=short*Number(pence); surplusTotal+=surplus*Number(pence);
    });
    plan.querySelector('[data-float-message]').textContent = ready ? 'Return '+currency.format(keepTotal/100)+' to the float. Denomination top-ups needed: '+currency.format(shortTotal/100)+'. Remaining counted till cash: '+currency.format(surplusTotal/100)+'.' : 'Count both the opening float and closing till by denomination to see the return plan.';
  };
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  update();
})();
