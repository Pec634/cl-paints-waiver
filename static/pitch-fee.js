document.querySelectorAll('[data-pitch-fee]').forEach(form => {
  const source = form.elements.source;
  const amount = form.elements.amount;
  if (form.dataset.eventReference && !form.elements.reason.value) {
    form.elements.reason.value = form.dataset.eventReference;
  }
  const currency = pence => new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'}).format(pence / 100);
  const sum = selector => {
    let total = 0;
    for (const field of form.querySelectorAll(selector)) {
      if (!/^\d{1,6}$/.test(field.value) || !field.checkValidity()) return null;
      total += Number(field.value) * Number(field.dataset.pitchUsed || field.dataset.pitchRemaining);
    }
    return total;
  };
  const update = () => {
    const cash = source.value === 'till';
    form.querySelectorAll('[data-pitch-count]').forEach(section => {
      section.hidden = !cash;
      section.disabled = !cash;
    });
    amount.readOnly = cash;
    amount.required = !cash;
    if (!cash) return;
    const paid = sum('[data-pitch-used]');
    const remaining = sum('[data-pitch-remaining]');
    const expected = Math.round(Number(form.dataset.expectedTill) * 100) - (paid || 0);
    amount.value = paid === null ? '' : (paid / 100).toFixed(2);
    form.querySelector('[data-pitch-paid]').textContent = paid === null ? 'Check quantities' : currency(paid);
    form.querySelector('[data-pitch-expected]').textContent = paid === null ? 'Check quantities' : currency(expected);
    form.querySelector('[data-pitch-total]').textContent = remaining === null ? 'Check quantities' : currency(remaining);
    const difference = paid === null || remaining === null ? null : remaining - expected;
    form.querySelector('[data-pitch-difference]').textContent = difference === null ? 'Check quantities.'
      : difference === 0 ? 'Till count matches the expected balance.'
      : `${currency(Math.abs(difference))} ${difference > 0 ? 'over' : 'short'}. Explain the difference below.`;
    form.elements.discrepancy_note.required = difference !== null && difference !== 0;
    let topup = 0, returned = 0;
    form.querySelectorAll('[data-pitch-plan]').forEach(row => {
      const pence = Number(row.dataset.pitchPlan);
      const field = form.querySelector(`[data-pitch-remaining="${pence}"]`);
      const short = Number(row.dataset.target) - Number(field.value);
      const cell = row.querySelector('[data-pitch-plan-move]');
      cell.textContent = remaining === null ? 'Check quantities' : short > 0
        ? `Safe → Till: ${short}${row.dataset.safe === '' ? ' — check safe availability' : Number(row.dataset.safe) < short ? ' — insufficient in safe' : ''}`
        : short < 0 ? `Till → Safe: ${-short}` : 'No movement needed';
      if (short > 0) topup += short * pence;
      else returned += -short * pence;
    });
    const planTotal = form.querySelector('[data-pitch-plan-total]');
    if (planTotal) planTotal.textContent = remaining === null ? 'Check quantities.'
      : `Safe → Till: ${currency(topup)}. Till → Safe: ${currency(returned)}. Check each denomination below; you may need to move cash in both directions.`;
  };
  source.addEventListener('change', () => { amount.value = ''; update(); });
  form.addEventListener('input', update);
  update();
});
