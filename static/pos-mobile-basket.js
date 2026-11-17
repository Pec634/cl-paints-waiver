(() => {
  const popup=document.getElementById('pos-popup');
  const panel=popup?.querySelector('.pos-sale-panel');
  const browse=popup?.querySelector('.pos-browse');
  const content=popup?.querySelector('.pos-popup-content');
  if(!panel || !browse || !content)return;
  const mobile=window.matchMedia('(max-width:899px)');
  const toggle=document.createElement('button');
  toggle.type='button';toggle.id='pos-mobile-basket-toggle';toggle.className='pos-mobile-basket-toggle';
  toggle.innerHTML='<span>Basket</span><strong id="pos-mobile-basket-count">0</strong><small id="pos-mobile-basket-total">£0.00</small>';
  panel.id='pos-basket-panel';
  toggle.setAttribute('aria-controls',panel.id);
  const backdrop=document.createElement('button');
  backdrop.type='button';backdrop.className='pos-mobile-basket-backdrop';
  backdrop.setAttribute('aria-label','Close basket and return to items');
  content.append(backdrop,toggle);
  let expanded=!!document.getElementById('pos-cash-receipt');
  const sync=() => {
    popup.classList.toggle('pos-mobile-basket-ready',mobile.matches);
    toggle.hidden=!mobile.matches;
    panel.hidden=mobile.matches && !expanded;
    browse.inert=mobile.matches && expanded;
    backdrop.hidden=!mobile.matches || !expanded;
    toggle.setAttribute('aria-expanded',String(mobile.matches && expanded));
    popup.classList.toggle('pos-mobile-basket-expanded',mobile.matches && expanded);
  };
  const close=() => {
    const hadFocus=panel.contains(document.activeElement) || document.activeElement===backdrop;
    expanded=false;sync();
    if(hadFocus && mobile.matches)toggle.focus();
  };
  toggle.addEventListener('click',() => {expanded=!expanded;sync();});
  backdrop.addEventListener('click',close);
  document.addEventListener('pos-basket-open',() => {expanded=true;sync();});
  document.addEventListener('pos-basket-close',close);
  popup.addEventListener('cancel',event => {
    if(mobile.matches && expanded){event.preventDefault();close();}
  });
  window.addEventListener('hashchange',() => {
    let target;
    try{target=document.getElementById(decodeURIComponent(location.hash.slice(1)));}catch(_){return;}
    if(target && panel.contains(target)){expanded=true;sync();}
  });
  mobile.addEventListener('change',sync);
  sync();
})();
