(() => {
    'use strict';
    if (window.CLFormReviewItems) return;
    const readable = (value,type) => {
        if (type === 'signature') {try {return JSON.parse(value).name ? 'Signed by '+JSON.parse(value).name : 'No signature';} catch {return 'No signature';}}
        if (type === 'repeat') {try {return JSON.parse(value).map((row,index)=>`Person ${index+1}: `+Object.entries(row).map(([key,value])=>key+': '+value).join(', ')).join('; ');} catch {return value;}}
        return value;
    };
    window.CLFormReviewItems = root => {
        let definitions=[];try {definitions=JSON.parse(root.dataset.nativeSchema);} catch {return [];}
        const rows=[];
        definitions.forEach((field,index)=>{
            if (['heading','content','pagebreak','image'].includes(field.type)) return;
            const block=root.querySelector('[data-native-index="'+index+'"]');
            if (!block || block.dataset.conditionVisible === 'no') return;
            const controls=[...block.querySelectorAll('[name="custom_'+index+'"]')].filter(control=>!control.disabled);
            let values=controls.filter(control=>!['radio','checkbox'].includes(control.type)||control.checked).flatMap(control=>control.type==='file'?[...control.files].map(file=>file.name):[control.type==='checkbox'&&field.type==='checkbox'?'Confirmed':control.value]);
            if (field.type==='calculation') values=[block.querySelector('output')?.textContent || ''];
            if (values.length && values.some(Boolean)) rows.push(field.label+': '+values.map(value=>readable(value,field.type)).join(', '));
        });return rows;
    };
    const init = () => document.querySelectorAll('[data-native-fields]').forEach(root=>{
        const form=root.closest('form');if (!form) return;
        const steps=new Set();let timer;
        const report=()=>{
            if (!root.dataset.activityUrl) return;
            fetch(root.dataset.activityUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.activityCsrf},body:JSON.stringify({started:steps.size>0,steps:[...steps]}),keepalive:true}).catch(()=>{});
        };
        const interacted=event=>{
            const block=event.target.closest('[data-native-index]');
            if (block) steps.add(Number(block.dataset.nativeIndex));
            clearTimeout(timer);timer=setTimeout(report,1200);
        };
        form.addEventListener('input',interacted);form.addEventListener('change',interacted);
        window.addEventListener('pagehide',()=>{clearTimeout(timer);report();});
        if (form.classList.contains('booking-form')) return;
        const dialog=document.createElement('dialog');dialog.className='booking-review-dialog';
        const title=document.createElement('h2');title.textContent='Review your response';title.id='native-review-title';dialog.setAttribute('aria-labelledby',title.id);
        const content=document.createElement('div');
        const edit=document.createElement('button');edit.type='button';edit.className='btn';edit.textContent='Back to editing';
        const send=document.createElement('button');send.type='button';send.className='btn primary';send.textContent='Confirm and submit';
        dialog.append(title,content,edit,send);document.body.append(dialog);
        let confirmed=false,submitter;
        form.addEventListener('input',()=>{confirmed=false;});form.addEventListener('change',()=>{confirmed=false;});
        edit.addEventListener('click',()=>dialog.close());
        send.addEventListener('click',()=>{confirmed=true;dialog.close();form.requestSubmit(submitter);});
        form.addEventListener('submit',event=>{
            if (event.defaultPrevented || confirmed) return;
            event.preventDefault();submitter=event.submitter;content.replaceChildren();
            const rows=window.CLFormReviewItems(root);
            const people=[...form.querySelectorAll('[name="participant_name"]')].map(control=>control.value).filter(Boolean);
            if (people.length) rows.push('Participants: '+people.join(', '));
            rows.push('Rules / permissions: accepted');
            rows.forEach(text=>{const p=document.createElement('p');p.textContent=text;content.append(p);});
            dialog.showModal();
        });
    });
    if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);else init();
})();
