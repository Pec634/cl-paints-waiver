(() => {
  const section=document.querySelector('[data-handover-cashups]');
  if (!section) return;
  const frames=[...section.querySelectorAll('[data-cashup-frame]')];
  const dirtyFrames=new Set();
  window.addEventListener('beforeunload',event => {
    if(!dirtyFrames.size) return;
    event.preventDefault(); event.returnValue='';
  });
  const complete=document.querySelector('[data-handover-form] button[name="action"][value="complete"]');
  const setPending = count => {
    if (complete) { complete.disabled=count>0; complete.title=count>0 ? 'Close all event-day cash-ups first' : ''; }
    const status=section.querySelector('[data-cashup-status]');
    if (status) status.textContent=count+' cash-up(s) still need closing.';
  };
  setPending(Number(section.dataset.pending));
  let refreshing=false;
  const refresh=async () => {
    if (refreshing) return;
    refreshing=true;
    const message=section.querySelector('[data-cashup-refresh-message]');
    try {
      const url=new URL(location.href); url.searchParams.set('cashup_status','1');
      url.searchParams.set('date',document.querySelector('[data-handover-form] [name="handover_date"]').value);
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});
      if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) throw new Error();
      const status=await response.json();
      setPending(status.pending);
      status.events.forEach(event => {
        const label=section.querySelector(`[data-booking="${event.booking_id}"][data-day="${event.day}"]`);
        if (label) label.textContent=event.phase;
      });
      if(message) message.textContent=status.pending ? 'Cash-up status updated. You can still save a handover draft.' : 'All event cash-ups are closed. The handover can now be completed.';
    } catch { if(message) message.textContent='Could not refresh cash-up status. Check your connection and sign-in, then try again. Your handover notes remain here.'; }
    finally { refreshing=false; }
  };
  section.querySelector('[data-refresh-cashup-status]')?.addEventListener('click',refresh);
  section.querySelectorAll('[data-event-cashup]').forEach(details => details.addEventListener('toggle',() => {
    const frame=details.querySelector('[data-cashup-frame]');
    if(details.open && !frame.hasAttribute('src')) frame.src=frame.dataset.src;
  }));
  window.addEventListener('message',event => {
    if(event.origin!==location.origin || event.data?.type!=='handover-cashup') return;
    const frame=frames.find(frame=>frame.contentWindow===event.source);
    if(!frame) return;
    if(event.data.dirty) dirtyFrames.add(frame); else dirtyFrames.delete(frame);
    const height=Number(event.data.height);
    if(Number.isFinite(height)) frame.style.height=Math.max(400,Math.min(height,20000))+'px';
    if(!event.data.dirty) refresh();
  });
})();
