(() => {
  const form = document.querySelector('[data-cashup-form]');
  const preview = document.querySelector('[data-cashup-preview]');
  if (!form || !preview) return;
  const currency = new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'});
  const amount = name => {
    const input = form.elements.namedItem(name);
    const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(input?.value || '');
    if (!match || !input.checkValidity()) throw new Error('Check the amounts');
    return Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0'));
  };
  const update = () => {
    try {
      const netCash = amount('cash_sales') - amount('cash_refunds');
      const net = netCash + amount('card_sales') - amount('card_refunds');
      const shared = amount('share_till') + amount('share_safe') + amount('share_bank');
      const shareDue = Math.round(Math.max(0, net) * amount('share_percent') / 10000);
      const till = amount('opening_till') + netCash + amount('safe_to_till') - amount('till_to_safe') - amount('share_till') + amount('till_other_in') - amount('till_other_out') + Number(form.dataset.invoiceTill || 0);
      const safe = amount('opening_safe') + amount('till_to_safe') - amount('safe_to_till') - amount('share_safe') + amount('safe_other_in') - amount('safe_other_out') + Number(form.dataset.invoiceSafe || 0);
      const values = {net, shared, share_due: shareDue, share_remaining: shareDue - shared,
        retained: net - shared, expected_till: till, expected_safe: safe,
        till_variance: amount('closing_till') - till, safe_variance: amount('closing_safe') - safe};
      preview.querySelectorAll('[data-cashup-value]').forEach(output => {
        output.textContent = currency.format(values[output.dataset.cashupValue] / 100);
      });
      preview.querySelector('[data-cashup-message]').textContent = 'Unsaved preview. Save a draft or close the cash-up to record these figures.';
    } catch {
      preview.querySelectorAll('[data-cashup-value]').forEach(output => { output.textContent = '\u2014'; });
      preview.querySelector('[data-cashup-message]').textContent = 'Enter valid amounts to preview the reconciliation.';
    }
  };
  form.addEventListener('input', update);
  update();
})();
