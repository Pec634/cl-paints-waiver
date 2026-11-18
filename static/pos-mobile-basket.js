(() => {
  const popup=document.getElementById('pos-popup');
  const panel=popup?.querySelector('.pos-sale-panel');
  const browse=popup?.querySelector('.pos-browse');
  const content=popup?.querySelector('.pos-popup-content');
  if(!panel || !browse || !content)return;
  const mobile=window.matchMedia('(max-width:899px)');
  const library=document.getElementById('pos-library');
  const waivers=popup.querySelector('.pos-waiver-panel');
  const history=document.getElementById('pos-history');
  const options=document.getElementById('pos-sale-options');
  waivers.id='pos-waiver-panel';panel.id='pos-basket-panel';
  const nav=document.createElement('nav');
  nav.className='pos-mobile-nav';nav.setAttribute('aria-label','Till views');
  const panes={items:library,waivers,history,basket:panel};
  const buttons={};
  for(const [name,label] of Object.entries({items:'Items',waivers:'Waivers',history:'History',basket:'Basket'})){
    const button=document.createElement('button');button.type='button';
    button.dataset.posView=name;button.setAttribute('aria-controls',panes[name].id);
    if(name==='basket'){
      button.id='pos-mobile-basket-toggle';button.className='pos-mobile-basket-toggle';
      button.innerHTML='<span>Basket <strong id="pos-mobile-basket-count">0</strong></span><small id="pos-mobile-basket-total">&pound;0.00</small>';
    }else button.textContent=label;
    buttons[name]=button;nav.append(button);
  }
  const customer=document.createElement('button');customer.type='button';
  customer.className='pos-mobile-customer';customer.textContent='Add a waiver / customer';
  customer.addEventListener('click',()=>document.getElementById('pos-change-waiver').click());
  library.insertBefore(customer,library.firstChild);
  popup.append(nav);
  let view=document.getElementById('pos-cash-receipt')?'basket':history.open?'history':document.getElementById('pos-query').value?'waivers':'items';
  let wasMobile=false;
  const scrolls={items:0,waivers:0,history:0};
  const sync=() => {
    popup.classList.toggle('pos-mobile-basket-ready',mobile.matches);
    popup.dataset.mobileView=view;
    nav.hidden=!mobile.matches;buttons.basket.hidden=!mobile.matches;
    for(const [name,pane] of Object.entries(panes))pane.classList.toggle('pos-mobile-pane-hidden',mobile.matches && view!==name);
    panel.hidden=mobile.matches && view!=='basket';
    browse.inert=mobile.matches && view==='basket';
    browse.hidden=mobile.matches && view==='basket';
    for(const [name,button] of Object.entries(buttons))button.setAttribute('aria-pressed',String(view===name));
    buttons.basket.setAttribute('aria-expanded',String(mobile.matches && view==='basket'));
    if(mobile.matches && !wasMobile && options)options.open=false;
    if(!mobile.matches && wasMobile && options)options.open=true;
    wasMobile=mobile.matches;
  };
  const select=(next,focus=false) => {
    if(!panes[next])return;
    popup.querySelectorAll('.pos-header-menu[open]').forEach(menu=>{menu.open=false;});
    if(view!=='basket')scrolls[view]=browse.scrollTop;
    view=next;
    if(next==='history')history.open=true;
    if(next==='waivers')document.getElementById('pos-waiver-fold').open=true;
    sync();
    if(next!=='basket')browse.scrollTop=scrolls[next] || 0;
    if(mobile.matches && focus)buttons[next].focus();
  };
  nav.addEventListener('click',event=>{
    const button=event.target.closest('[data-pos-view]');
    if(button)select(button.dataset.posView,true);
  });
  document.addEventListener('pos-basket-open',()=>select('basket'));
  document.addEventListener('pos-basket-close',()=>select('items',true));
  document.addEventListener('pos-waiver-open',()=>select('waivers'));
  document.addEventListener('pos-waiver-linked',()=>{select('items',true);});
  document.addEventListener('pos-basket-updated',event=>{
    customer.textContent=event.detail.waiver?'Waiver: '+event.detail.waiver+' · Change':'Add a waiver / customer';
    customer.classList.toggle('pos-customer-linked',!!event.detail.waiver);
    buttons.waivers.classList.toggle('pos-customer-linked',!!event.detail.waiver);
  });
  popup.addEventListener('cancel',event=>{
    if(mobile.matches && view!=='items'){event.preventDefault();select('items',true);}
  });
  const revealHash=()=>{
    let target;
    try{target=document.getElementById(decodeURIComponent(location.hash.slice(1)));}catch(_){return;}
    if(!target)return;
    const entry=Object.entries(panes).find(([,pane])=>pane===target || pane.contains(target));
    if(entry)select(entry[0]);
  };
  window.addEventListener('hashchange',revealHash);
  mobile.addEventListener('change',sync);
  sync();revealHash();
})();
