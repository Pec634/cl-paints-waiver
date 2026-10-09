(() => {
    const menu=document.querySelector('.website-menu-toggle'),navigation=document.getElementById('website-navigation');
    if(menu&&navigation){
        menu.hidden=false;navigation.classList.add('website-navigation-ready');
        const close=()=>{menu.setAttribute('aria-expanded','false');navigation.classList.remove('is-open');};
        menu.onclick=()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));navigation.classList.toggle('is-open',open);};
        document.addEventListener('keydown',event=>{if(event.key==='Escape'){close();menu.focus();}});
        navigation.addEventListener('click',event=>{if(event.target.closest('a'))setTimeout(close,0);});
        matchMedia('(max-width:700px)').addEventListener('change',close);
    }
    const photos=[...document.querySelectorAll('.photo-grid img,.hero-photo img')];
    if(photos.length&&typeof HTMLDialogElement!=='undefined'){
        const dialog=document.createElement('dialog');dialog.className='website-lightbox';dialog.setAttribute('aria-label','Face painting photograph');
        const close=document.createElement('button');close.className='button light';close.textContent='Close photo';
        const image=document.createElement('img');dialog.append(close,image);document.body.append(dialog);
        close.onclick=()=>dialog.close();dialog.onclick=event=>{if(event.target===dialog)dialog.close();};
        photos.forEach(photo=>{const button=document.createElement('button');button.className='photo-expand';button.type='button';button.setAttribute('aria-label','View full photograph: '+photo.alt);photo.before(button);button.append(photo);button.onclick=()=>{image.src=photo.src;image.alt=photo.alt;dialog.showModal();};});
    }
    if (!('IntersectionObserver' in window)) return;
    const motion=matchMedia('(prefers-reduced-motion: reduce)');
    if(motion.matches)return;
    const sections=[...document.querySelectorAll('main > .section, main > .cta')];
    const observer=new IntersectionObserver(entries=>{
        entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target);}});
    },{threshold:.08});
    sections.forEach(section=>{section.classList.add('website-reveal');observer.observe(section);});
    motion.addEventListener('change',()=>{if(motion.matches){sections.forEach(section=>section.classList.add('is-visible'));observer.disconnect();}});
})();
