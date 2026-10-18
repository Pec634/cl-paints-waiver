(() => {
    const nav = document.querySelector('nav[aria-label="Admin navigation"]');
    if (nav) {
        const markers = [...nav.querySelectorAll('[data-nav-group]')];
        const groups = new Map();
        const toolSearch = document.getElementById('admin-tool-search');
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
                    if (!group.open || toolSearch?.value.trim()) return;
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
        const groupOrder = ['Bookings & events','Clients & rewards','Communications','CL Creates','Website & content','Finance & reports','System & settings'];
        // Keep new sections visible even when they are not in the preferred order yet.
        for (const title of new Set([...groupOrder, ...groups.keys()])) {
            const group = groups.get(title);
            if (group) markers[0].before(group);
        }
        markers.forEach(marker => marker.remove());
        if (toolSearch) {
            toolSearch.closest('.admin-tool-search').hidden = false;
            const status = document.getElementById('admin-tool-search-status');
            let previousOpen = null;
            const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
            const filterTools = () => {
                const words = normalize(toolSearch.value).trim().split(/\s+/).filter(Boolean);
                if (words.length && previousOpen === null) {
                    previousOpen = new Map([...groups.values()].map(group => [group, group.open]));
                    groups.forEach(group => group.removeAttribute('name'));
                }
                let count = 0;
                groups.forEach((group, title) => {
                    let matches = 0;
                    group.querySelectorAll('a').forEach(link => {
                        const text = normalize(title + ' ' + link.textContent);
                        const visible = words.length ? words.every(word => text.includes(word)) : !link.hasAttribute('data-tool-search-only');
                        link.hidden = !visible;
                        if (visible) matches++;
                    });
                    group.hidden = words.length > 0 && matches === 0;
                    if (words.length) group.open = matches > 0;
                    count += matches;
                });
                if (!words.length && previousOpen !== null) {
                    groups.forEach(group => {
                        group.open = previousOpen.get(group);
                        group.setAttribute('name', 'admin-navigation-folders');
                    });
                    previousOpen = null;
                }
                status.textContent = words.length ? (count ? `${count} matching ${count === 1 ? 'tool or setting' : 'tools and settings'}` : 'No matching tools or settings.') : '';
            };
            toolSearch.addEventListener('input', filterTools);
            toolSearch.addEventListener('search', filterTools);
            toolSearch.addEventListener('keydown', event => {
                if (event.key === 'Escape') { toolSearch.value = ''; filterTools(); }
            });
            filterTools();
        }
    }

    // Save only list filter URLs on this device, never client details or form content.
    document.querySelectorAll('.admin form[method="get"]').forEach(form => {
        if (!form.querySelector('select[name="filter"], select[name="status"], select[name="sort"]')) return;
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
            form.querySelectorAll('select[name="filter"], select[name="status"], select[name="sort"]').forEach(select => values.set(select.name,select.value));
            try { localStorage.setItem(key,values.toString()); status.textContent = 'Filter saved on this device.'; refresh(); }
            catch (_) { status.textContent = 'Browser storage is unavailable.'; }
        };
        forget.onclick = () => { try { localStorage.removeItem(key); refresh(); status.textContent = 'Saved filter removed.'; } catch (_) {} };
        row.append(save,restore,forget,status); form.after(row); refresh();
    });

    const dirty = new Set();
    document.querySelectorAll('form[data-warn-unsaved], .settings-column form:not(#qr-form), .admin form[method="post"]').forEach(form => {
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
