(() => {
    const carousel=document.querySelector('.client-review-carousel');
    if(!carousel)return;
    const slides=[...carousel.querySelectorAll('[data-review-slide]')];
    if(slides.length<2)return;
    const controls=carousel.querySelector('.client-review-controls');controls.hidden=false;
    const pause=controls.querySelector('[data-review-pause]');
    const motion=matchMedia('(prefers-reduced-motion: reduce)');
    let index=0,paused=false,timer=null,hover=false;
    const show=next=>{
        index=(next+slides.length)%slides.length;
        slides.forEach((slide,i)=>{slide.hidden=i!==index;});
        controls.querySelector('[data-review-count]').textContent=`${index+1} / ${slides.length}`;
    };
    const sync=()=>{
        clearInterval(timer);
        const reduced=motion.matches||document.documentElement.classList.contains('portal-reduced-motion');
        pause.textContent=paused?'Resume rotation':'Pause rotation';
        pause.disabled=reduced;
        if(reduced)pause.textContent='Auto-rotation off';
        if(!paused&&!reduced&&!hover&&!carousel.contains(document.activeElement)&&!document.hidden)timer=setInterval(()=>show(index+1),7000);
    };
    controls.querySelector('[data-review-prev]').onclick=()=>{show(index-1);sync();};
    controls.querySelector('[data-review-next]').onclick=()=>{show(index+1);sync();};
    pause.onclick=()=>{paused=!paused;sync();};
    carousel.addEventListener('mouseenter',()=>{hover=true;sync();});
    carousel.addEventListener('mouseleave',()=>{hover=false;sync();});
    carousel.addEventListener('focusin',sync);carousel.addEventListener('focusout',()=>setTimeout(sync,0));
    motion.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
    new MutationObserver(sync).observe(document.documentElement,{attributes:true,attributeFilter:['class']});
    sync();
})();
