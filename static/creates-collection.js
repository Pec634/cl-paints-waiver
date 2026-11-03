(() => {
  const root = document.getElementById('collection');
  if (!root) return;
  const select = root.querySelector('[name=collection_slot_id]');
  const dates = [...select.options].filter(option => option.dataset.date);
  const first = dates[0]?.dataset.date || new Date().toISOString().slice(0, 10);
  let month = new Date(first.slice(0,7)+'-01T12:00:00');
  const render = () => {
    const grid = root.querySelector('[data-collection-calendar]'); grid.replaceChildren();
    root.querySelector('[data-collection-month]').textContent = month.toLocaleDateString('en-GB',{month:'long',year:'numeric'});
    ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach(day => { const label=document.createElement('small');label.textContent=day;grid.append(label); });
    const offset=(month.getDay()+6)%7;
    for(let index=0;index<offset;index++) grid.append(document.createElement('span'));
    const days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
    for(let day=1;day<=days;day++) {
      const key=`${month.getFullYear()}-${String(month.getMonth()+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
      const games=dates.filter(option=>option.dataset.date===key);
      const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=day;
      button.disabled=games.length===0;button.style.padding='8px 2px';
      button.setAttribute('aria-label',games.length?games.map(option=>option.textContent).join('; '):`${key}: no collection`);
      button.setAttribute('aria-pressed',String(games.some(option=>option.value===select.value)));
      if(games.some(option=>option.value===select.value))button.classList.add('primary');
      button.addEventListener('click',()=>{select.value=games[0].value;select.dispatchEvent(new Event('change',{bubbles:true}));render();});grid.append(button);
    }
  };
  root.querySelector('[data-collection-prev]').addEventListener('click',()=>{month.setMonth(month.getMonth()-1);render();});
  root.querySelector('[data-collection-next]').addEventListener('click',()=>{month.setMonth(month.getMonth()+1);render();});
  select.addEventListener('change',()=>{const selected=select.selectedOptions[0];if(selected?.dataset.date)month=new Date(selected.dataset.date.slice(0,7)+'-01T12:00:00');render();});
  render();
})();
