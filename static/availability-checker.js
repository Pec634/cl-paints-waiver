(() => {
    const form=document.getElementById('availability-form');if(!form)return;
    const result=document.getElementById('availability-result'),link=document.getElementById('availability-continue');
    const action=document.getElementById('availability-booking-action');
    const button=form.querySelector('button');let version=0;
    form.addEventListener('input',()=>{version++;action.hidden=true;result.textContent='';});
    form.addEventListener('submit',async event=>{
        event.preventDefault();const current=++version;action.hidden=true;button.disabled=true;result.textContent='Checking your preferred date…';
        const data=Object.fromEntries(new FormData(form));
        try {
            const response=await fetch(form.dataset.checkUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
            const answer=await response.json();if(current!==version)return;
            if(!response.ok||!answer.success)throw new Error(answer.error||'Please try again.');
            result.textContent=answer.message;
            if(answer.available){link.href=form.dataset.bookingUrl+'?'+new URLSearchParams({preferred_date:data.date,preferred_start:data.start_time,preferred_finish:data.finish_time});action.hidden=false;}
        }catch(error){if(current===version)result.textContent=error.message||'Availability could not be checked. Please contact CL Paints.';}
        finally{button.disabled=false;}
    });
})();
