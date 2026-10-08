(() => {
    const nav = document.querySelector('nav[aria-label="Admin navigation"]');
    if (nav) {
        const markers = [...nav.querySelectorAll('[data-nav-group]')];
        const groups = new Map();
        for (const marker of markers) {
            const title = marker.dataset.navGroup;
            if (!groups.has(title)) {
                const group = document.createElement('details');
                group.className = 'admin-navigation-group';
                group.setAttribute('name', 'admin-navigation-folders');
                const summary = document.createElement('summary');
                summary.textContent = title;
                group.append(summary);
                group.addEventListener('toggle', () => {
                    if (!group.open) return;
                    nav.querySelectorAll('.admin-navigation-group[open]').forEach(other => {
                        if (other !== group) other.open = false;
                    });
                });
                groups.set(title, group);
            }
            const link = marker.nextElementSibling;
            groups.get(title).append(link);
            if (link.matches('[aria-current="page"]')) groups.get(title).open = true;
        }
        for (const title of ['Bookings & events','Clients & rewards','Communications','Business settings']) {
            const group = groups.get(title);
            if (group) markers[0].before(group);
        }
        markers.forEach(marker => marker.remove());
    }

    // Save only list filter URLs on this device, never client details or form content.
    document.querySelectorAll('.admin form[method="get"]').forEach(form => {
        if (!form.querySelector('select[name="filter"], select[name="status"]')) return;
        const key = 'cl-paints-filter:' + location.pathname;
        const row = document.createElement('div');
        row.className = 'portal-saved-filter';
        const save = document.createElement('button');
        save.type = 'button'; save.className = 'btn'; save.textContent = 'Save current filter';
        const restore = document.createElement('a');
        restore.className = 'btn'; restore.textContent = 'Open saved filter'; restore.hidden = true;
        const forget = document.createElement('button');
        forget.type = 'button'; forget.className = 'btn'; forget.textContent = 'Remove saved filter'; forget.hidden = true;
        const status = document.createElement('span'); status.setAttribute('role','status');
        const refresh = () => {
            try {
                const query = localStorage.getItem(key);
                restore.hidden = forget.hidden = query === null;
                if (query !== null) restore.href = location.pathname + '?' + query;
            } catch (_) { status.textContent = 'Browser storage is unavailable.'; }
        };
        save.onclick = () => {
            const values = new URLSearchParams();
            form.querySelectorAll('select[name="filter"], select[name="status"]').forEach(select => values.set(select.name,select.value));
            try { localStorage.setItem(key,values.toString()); status.textContent = 'Filter saved on this device.'; refresh(); }
            catch (_) { status.textContent = 'Browser storage is unavailable.'; }
        };
        forget.onclick = () => { try { localStorage.removeItem(key); refresh(); status.textContent = 'Saved filter removed.'; } catch (_) {} };
        row.append(save,restore,forget,status); form.after(row); refresh();
    });

    const dirty = new Set();
    document.querySelectorAll('form[data-warn-unsaved]').forEach(form => {
        const baseline = () => JSON.stringify([...new FormData(form)].filter(([key])=>key!=='csrf_token').map(([key,value])=>[key,typeof value==='string'?value:value.name]));
        let initial = baseline();
        const changed = () => { if (baseline()===initial) dirty.delete(form); else dirty.add(form); };
        form.addEventListener('input',changed); form.addEventListener('change',changed);
        form.addEventListener('submit',event => { if (!event.defaultPrevented) dirty.delete(form); });
        form.addEventListener('reset',()=>setTimeout(()=>{ initial=baseline(); dirty.delete(form); },0));
    });
    window.addEventListener('beforeunload',event=>{ if (dirty.size) { event.preventDefault(); event.returnValue=''; } });

    document.querySelectorAll('.admin table.waiver-table').forEach(table => {
        const headings=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim());
        for (const row of table.querySelectorAll('tbody tr')) {
            if (row.cells.length!==headings.length) continue;
            [...row.cells].forEach((cell,index)=>{ cell.dataset.columnLabel=headings[index]; });
        }
    });
})();
