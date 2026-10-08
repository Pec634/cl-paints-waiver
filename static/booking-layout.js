(() => {
    const script=document.querySelector('script[data-booking-layout]');
    if (!script) return;
    const main=document.querySelector('.client-main, .admin main');
    if (!main) return;
    const sections=[...main.querySelectorAll(':scope > section.panel')];
    const rank=title => {
        if (/updated|replacement|proposed/i.test(title)) return 0;
        if (/event details/i.test(title)) return 1;
        if (/journey/i.test(title)) return 2;
        if (/checklist/i.test(title)) return 3;
        if (/payment|balance|invoice/i.test(title)) return 4;
        if (/timeline|activity/i.test(title)) return 9;
        return 6;
    };
    const heading=section=>section.querySelector('h2')?.textContent.trim() || '';
    if (script.dataset.bookingLayout==='client' && sections.length) {
        const marker=document.createElement('span');sections[0].before(marker);
        sections.sort((a,b)=>rank(heading(a))-rank(heading(b)));
        sections.forEach(section=>marker.before(section)); marker.remove();
    }
    const nav=document.createElement('nav');nav.className='portal-booking-navigation';nav.setAttribute('aria-label','Booking sections');
    sections.forEach((section,index)=>{
        const title=heading(section);if(!title)return;
        if(!section.id)section.id='booking-section-'+index;
        const link=document.createElement('a');link.href='#'+section.id;link.textContent=title;nav.append(link);
    });
    main.querySelector('h1')?.after(nav);
})();
