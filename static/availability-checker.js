(() => {
    const form=document.getElementById('availability-form');if(!form)return;
    const result=document.getElementById('availability-result'),link=document.getElementById('availability-continue');
    const button=form.querySelector('button');let version=0;
    form.addEventListener('input',()=>{version++;link.hidden=true;result.textContent='';});
    form.addEventListener('submit',async event=>{
        event.preventDefault();const current=++version;link.hidden=true;button.disabled=true;result.textContent='Checking your preferred date…';
        const data=Object.fromEntries(new FormData(form));
        try {
            const response=await fetch(form.dataset.checkUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
            const answer=await response.json();if(current!==version)return;
            if(!response.ok||!answer.success)throw new Error(answer.error||'Please try again.');
            result.textContent=answer.available?'Available to enquire. Your booking still needs confirmation.':'Please contact us about this date. We can discuss suitable arrangements.';
            if(answer.available){link.href=form.dataset.bookingUrl+'?'+new URLSearchParams({preferred_date:data.date,preferred_start:data.start_time,preferred_finish:data.finish_time,preferred_type:data.event_type,preferred_address:data.address});link.hidden=false;}
        }catch(error){if(current===version)result.textContent=error.message||'Availability could not be checked. Please contact CL Paints.';}
        finally{button.disabled=false;}
    });
})();
