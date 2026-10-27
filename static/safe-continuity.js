(() => {
  const panel=document.querySelector('[data-safe-continuity]');
  const form=document.querySelector('[data-cashup-form]');
  if(!panel || !form || panel.dataset.enforce!=='yes') return;
  const opening=form.elements.opening_safe;
  const button=form.querySelector('button[value="open"]');
  const expected=Math.round(Number(panel.dataset.expected)*100);
  const money=new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'});
  const update=()=>{
    const amount=Number(opening.value);
    const valid=opening.value!=='' && Number.isFinite(amount);
    const difference=Math.round(amount*100)-expected;
    const matches=valid && difference===0;
    panel.querySelector('[data-safe-difference]').textContent=matches ? 'Opening safe matches the previous close. Difference: £0.00.' : 'Safe difference: '+(valid?money.format(difference/100):'enter a count')+'. Opening checks cannot be saved until the difference is £0.00.';
    if(button) button.disabled=!matches;
  };
  form.addEventListener('input',update);
  form.addEventListener('change',update);
  update();
})();
