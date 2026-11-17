(() => {
  const form=document.querySelector('[data-pos-reconciliation]');
  if(!form)return;
  const pounds=new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'});
  const read=name=>{
    const raw=form.elements.namedItem(name).value;
    if(!/^-?\d+(\.\d{1,2})?$/.test(raw))throw Error();
    return Math.round(Number(raw)*100);
  };
  const update=()=>{
    try{
      const expected=read('opening_cash')+read('other_cash_in')-read('other_cash_out')+Number(form.dataset.cashNet);
      const card=Number(form.dataset.cardNet);
      const values={expected_cash:expected,expected_card:card,cash_variance:read('counted_cash')-expected,card_variance:read('sumup_net')-card};
      form.querySelectorAll('[data-reconcile-value]').forEach(output=>{
        const key=output.dataset.reconcileValue;
        output.textContent=pounds.format(values[key]/100);
        output.classList.toggle('pos-reconcile-difference',key.endsWith('variance')&&values[key]!==0);
      });
    }catch(_){form.querySelectorAll('[data-reconcile-value]').forEach(output=>output.textContent='Enter the cash count and SumUp total');}
  };
  form.addEventListener('input',update);update();
})();
