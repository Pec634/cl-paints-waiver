(() => {
    const notice=document.querySelector('[data-login-countdown]');
    if(!notice)return;
    const deadline=Date.now()+Number(notice.dataset.loginCountdown)*1000;
    const form=document.querySelector('.login-form');
    const button=form.querySelector('[type="submit"]');
    let timer;
    const update=()=>{
        const remaining=Math.max(0,Math.ceil((deadline-Date.now())/1000));
        notice.querySelector('[data-login-time]').textContent=`${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`;
        button.disabled=remaining>0;
        if(!remaining){clearInterval(timer);notice.hidden=true;document.querySelector('[data-login-ready]').textContent='You can try signing in again.';}
    };
    form.addEventListener('submit',event=>{if(Date.now()<deadline){event.preventDefault();event.stopImmediatePropagation();}},true);
    timer=setInterval(update,1000);update();
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)update();});
})();
