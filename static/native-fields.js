(() => {
    'use strict';
    const features = window.CLNativeFeatures;
    document.querySelectorAll('[data-native-fields]').forEach(container => {
        if (container.dataset.initialised || !features) return;
        container.dataset.initialised = 'true';
        const form = container.closest('form');
        const blocks = [...container.querySelectorAll('.native-block')];
        let fields;
        try { fields = JSON.parse(container.dataset.nativeSchema); } catch { fields = []; }
        const definitions = new Map(fields.map(field => [field.label, field]));
        const extras = new Map();
        let page = 0, pageCount = 1, updating = false, touched = false, submitting = false;
        const pageStartRows = new Map([[0, 1]]);
        fields.forEach((field, index) => {
            if (field.type === 'pagebreak') { pageCount++; pageStartRows.set(pageCount-1, field.layout?.row || index+1); }
            blocks[index].dataset.page = pageCount-1;
            if (['repeat', 'signature'].includes(field.type)) {
                const root = blocks[index].querySelector('[data-native-value]');
                extras.set(index, features.advanced(field, root, () => {
                    root.dispatchEvent(new Event('input', {bubbles:true}));
                }));
            }
        });
        blocks.forEach(block => block.querySelectorAll('input, select, textarea').forEach(input => {
            input.dataset.originalRequired = input.required ? 'yes' : 'no';
        }));
        const tail = form?.querySelector('[data-native-tail]');
        tail?.querySelectorAll('input, select, textarea').forEach(input => { input.dataset.originalRequired = input.required ? 'yes' : 'no'; });
        const nav = features.node('div', undefined, 'native-page-navigation');
        const previous = features.node('button', 'Previous', 'btn'), next = features.node('button', 'Next step', 'btn primary');
        previous.type = next.type = 'button';
        const progress = features.node('progress'); progress.max = pageCount;
        const stepStatus = features.node('span'); stepStatus.setAttribute('role', 'status');
        nav.append(previous, stepStatus, progress, next);
        if (pageCount > 1) container.before(nav);
        function controls(block) { return [...block.querySelectorAll('input, select, textarea')]; }
        function valueOf(block, field) {
            const inputs = controls(block), first = block.querySelector('[data-native-value]') || inputs[0];
            if (!first) return '';
            if (field.type === 'multiselect') return inputs.filter(input => input.type === 'checkbox' && input.checked).map(input => input.value);
            if (['radio', 'cards', 'gallery'].includes(field.type)) return inputs.find(input => input.type === 'radio' && input.checked)?.value || '';
            if (field.type === 'checkbox') return first.checked ? 'yes' : '';
            if (field.type === 'file') return [...first.files].map(file => file.name);
            if (field.type === 'repeat') { try { return JSON.parse(first.value || '[]'); } catch { return []; } }
            return first.value;
        }
        function update() {
            if (updating) return;
            updating = true;
            const values = new Map();
            blocks.forEach((block, index) => {
                const field = fields[index];
                if (!field) return;
                const visible = features.matches(field.show_if, values);
                const onPage = Number(block.dataset.page) === page;
                const required = !!field.required || (!!field.required_if && features.matches(field.required_if, values));
                block.dataset.conditionVisible = visible ? 'yes' : 'no';
                block.hidden = !visible || !onPage;
                if (pageCount > 1) block.style.setProperty('--block-row', (field.layout?.row || index+1) - pageStartRows.get(Number(block.dataset.page)) + 1);
                extras.get(index)?.setRequired?.(required && visible);
                controls(block).forEach(control => {
                    control.dataset.originalRequired ||= control.required ? 'yes' : 'no';
                    control.disabled = !visible || !onPage;
                    if (!extras.has(index)) control.required = visible && onPage && required && field.type !== 'multiselect' && control.type !== 'hidden';
                    else if (control.hasAttribute('data-native-value')) control.required = false;
                    else if(field.type==='signature') control.required = visible && onPage && control.required;
                    else control.required = visible && onPage && control.dataset.originalRequired === 'yes';
                    if (!extras.has(index)) control.setCustomValidity('');
                });
                block.querySelectorAll(':scope > label > small, .native-choice-group > legend > small').forEach(label => { label.textContent = required ? '(required)' : '(optional)'; });
                if (!visible) return;
                if (field.type === 'calculation') {
                    const result = features.calculate(field, values, definitions);
                    block.querySelector('output').textContent = result ? (field.calculation.prefix || '') + result : 'Check your answers';
                    values.set(field.label, result);
                } else if (!['content','heading','image','pagebreak'].includes(field.type)) values.set(field.label, valueOf(block, field));
                if (field.type === 'multiselect' && required && !valueOf(block, field).length) controls(block)[0]?.setCustomValidity('Choose at least one option.');
                if (field.type === 'file') {
                    const input = controls(block)[0];
                    if (input.files.length > field.max_files || [...input.files].some(file => file.size > 10000000)) input.setCustomValidity('Check the number and size of your attachments.');
                }
            });
            if (tail && pageCount > 1) {
                tail.hidden = page !== pageCount-1;
                tail.querySelectorAll('input, select, textarea').forEach(input => {
                    input.disabled = page !== pageCount-1;
                    input.required = page === pageCount-1 && input.dataset.originalRequired === 'yes';
                });
            }
            previous.disabled = page === 0; next.hidden = page === pageCount-1;
            progress.value = page+1; stepStatus.textContent = `Step ${page+1} of ${pageCount}`;
            updating = false;
        }
        function checkPage() {
            for (const block of blocks.filter(block => !block.hidden)) for (const input of controls(block)) {
                if (!input.disabled && !input.reportValidity()) return false;
            }
            return true;
        }
        previous.addEventListener('click', () => { page--; update(); nav.scrollIntoView({block:'nearest'}); });
        next.addEventListener('click', () => { if (checkPage()) { page++; update(); nav.scrollIntoView({block:'nearest'}); blocks.find(block => !block.hidden)?.querySelector('input,select,textarea')?.focus(); } });
        container.addEventListener('input', () => { touched = true; update(); });
        container.addEventListener('change', () => { touched = true; update(); });
        container.querySelectorAll('.native-clear-choice').forEach(button => {
            button.hidden = false;
            button.addEventListener('click', () => { button.closest('.native-block').querySelectorAll('input[type=radio]').forEach(input => { input.checked = false; }); touched=true; update(); scheduleSave(); });
        });
        let saveTimer, draftToken, draftFingerprint, saving = false;
        const draftStatus = features.node('p', undefined, 'native-help'); draftStatus.setAttribute('role','status');
        const draftActions = features.node('div', undefined, 'native-draft-actions');
        const save = features.node('button', 'Save progress', 'btn'), clear = features.node('button', 'Discard saved progress', 'btn');
        save.type = clear.type = 'button';
        const ready = document.readyState === 'complete' ? Promise.resolve() : new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once:true}));
        if (container.dataset.draftUrl) {
            draftActions.append(save, clear); container.before(draftActions, draftStatus);
            draftStatus.textContent = 'Progress can be saved. Files, signatures and consent confirmations must be completed again.';
            fetch(container.dataset.draftUrl, {credentials:'same-origin'}).then(response => response.ok ? response.json() : Promise.reject()).then(async data => {
                await ready;
                draftToken=data.csrf_token; draftFingerprint=data.fingerprint;
                if (data.outdated) draftStatus.textContent = 'The form has changed. Your earlier saved draft will not be applied.';
                else if (Object.keys(data.answers).length && !touched) {
                    for (const [name, value] of Object.entries(data.answers)) {
                        const inputs=[...form.elements].filter(input => input.name===name && input.type!=='file');
                        inputs.forEach(input => {
                            if (input.type==='radio' || input.type==='checkbox') input.checked=Array.isArray(value) ? value.includes(input.value) : value===input.value;
                            else input.value=value;
                        });
                    }
                    extras.forEach((host,index) => { if (fields[index].type==='repeat') host.restore(); });
                    form.querySelectorAll('[name=event_schedule]').forEach(input => input.dispatchEvent(new Event('change',{bubbles:true})));
                    form.dispatchEvent(new Event('native-draft-restored'));
                    update(); draftStatus.textContent='Saved progress restored. Reselect files and complete signatures and consent again.';
                } else if (!data.outdated) draftStatus.textContent = data.cross_device ? 'Progress saves to your account so you can return on another device. Reselect files and complete signatures and consent again.' : 'Progress saves for this browser. Sign in to save across devices. Reselect files and complete signatures and consent again.';
            }).catch(() => { draftStatus.textContent='Draft recovery is unavailable. Your form can still be submitted.'; });
        }
        async function saveProgress() {
            if (!draftToken || submitting || saving) return;
            saving=true;
            form.dispatchEvent(new Event('native-draft-collect'));
            const data={};
            [...form.elements].forEach(input => {
                if (!input.name || input.type==='file' || /csrf|token|agree|consent|authority|signature|liability|terms|participant/i.test(input.name)) return;
                const match=input.name.match(/^custom_(\d+)$/);
                if (match && ['signature','file','calculation'].includes(fields[Number(match[1])]?.type)) return;
                if (input.type==='radio') { if (input.checked) data[input.name]=input.value; }
                else if (input.type==='checkbox') {
                    if (input.name==='booking_extras' || (match && fields[Number(match[1])]?.type==='multiselect')) { data[input.name] ||= []; if (input.checked) data[input.name].push(input.value); }
                    else data[input.name]=input.checked ? input.value : '';
                } else data[input.name]=input.value;
            });
            draftStatus.textContent='Saving progress…';
            try {
                const response=await fetch(container.dataset.draftUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':draftToken},body:JSON.stringify({fingerprint:draftFingerprint,answers:data})});
                const result=await response.json(); if (!response.ok) throw new Error(result.error || 'Progress could not be saved.');
                draftStatus.textContent='Progress saved. Files, signatures and consent must be completed again.';
            } catch(error) { draftStatus.textContent=error.message || 'Progress could not be saved. Try again.'; }
            finally { saving=false; }
        }
        function scheduleSave() { if (!container.dataset.draftUrl || submitting) return; clearTimeout(saveTimer); saveTimer=setTimeout(saveProgress,1500); }
        save.addEventListener('click',saveProgress);
        clear.addEventListener('click',async () => {
            clearTimeout(saveTimer);
            if (!draftToken) return;
            try { const response=await fetch(container.dataset.draftUrl,{method:'DELETE',credentials:'same-origin',headers:{'X-CSRF-Token':draftToken}}); if (!response.ok) throw new Error(); draftStatus.textContent='Saved progress discarded. Current answers remain on screen.'; }
            catch { draftStatus.textContent='Saved progress could not be discarded. Try again.'; }
        });
        form?.addEventListener('input',scheduleSave); form?.addEventListener('change',scheduleSave);
        form?.addEventListener('reset',() => setTimeout(update,0));
        form?.addEventListener('submit',event => {
            clearTimeout(saveTimer); submitting=true;
            queueMicrotask(() => { if (event.defaultPrevented) submitting=false; });
            update();
            for (let step=0;step<pageCount;step++) {
                page=step; update();
                if (!checkPage()) { event.preventDefault(); submitting=false; return; }
            }
            blocks.forEach(block => { if (block.dataset.conditionVisible==='yes') controls(block).forEach(input => { input.disabled=false; }); });
            tail?.querySelectorAll('input,select,textarea').forEach(input => { input.disabled=false; });
        });
        update();
    });
})();
