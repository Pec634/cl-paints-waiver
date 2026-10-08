(() => {
    'use strict';
    const node = (tag, text, className) => {
        const element = document.createElement(tag);
        if (text !== undefined) element.textContent = text;
        if (className) element.className = className;
        return element;
    };
    function rules(rule) {
        if (!rule) return [];
        return rule.rules || [{field: rule.field, operator: 'equals', value: rule.equals}];
    }
    function matches(rule, values) {
        if (!rule) return true;
        const results = rules(rule).map(row => {
            if (!values.has(row.field)) return false;
            const value = values.get(row.field), expected = row.value || '';
            switch (row.operator || 'equals') {
                case 'equals': return value === expected;
                case 'not_equals': return value !== expected;
                case 'contains': return (typeof value === 'string' || Array.isArray(value)) && value.includes(expected);
                case 'answered': return Array.isArray(value) ? !!value.length : !!value;
                case 'greater': return Number.isFinite(Number(value)) && Number(value) > Number(expected);
                case 'less': return Number.isFinite(Number(value)) && Number(value) < Number(expected);
                default: return false;
            }
        });
        return rule.mode === 'any' ? results.some(Boolean) : results.every(Boolean);
    }
    function calculate(field, values, definitions) {
        const config = field.calculation;
        const amounts = config.sources.map(label => {
            const source = definitions.get(label), value = values.get(label) || '';
            if (config.operation === 'count') return Array.isArray(value) ? value.length : (value ? 1 : 0);
            if (['select', 'radio', 'cards', 'gallery', 'multiselect'].includes(source?.type)) return (Array.isArray(value) ? value : [value]).reduce((sum, choice) => sum + Number(source.option_values?.[choice] || 0), 0);
            if (source?.type === 'checkbox') return value === 'yes' ? Number(source.checked_value || 0) : 0;
            return Number(value || 0);
        });
        let result = Number(config.base || 0);
        if (config.operation === 'product') amounts.forEach(value => { result *= value; });
        else if (config.operation === 'percentage') result = amounts.reduce((sum, value) => sum + value, 0) * result / 100;
        else result += amounts.reduce((sum, value) => sum + value, 0);
        return Number.isFinite(result) && Math.abs(result) <= 1e12 ? result.toFixed(config.precision ?? 2) : '';
    }
    function advanced(field, root, changed) {
        const host = node('div', undefined, 'native-advanced-control');
        if (field.type === 'repeat') {
            let rows;
            try { rows = JSON.parse(root.value || '[]'); } catch { rows = []; }
            if (!Array.isArray(rows)) rows = [];
            rows = rows.filter(row => row && typeof row==='object' && !Array.isArray(row)).slice(0,field.max_items || 10);
            const list = node('div', undefined, 'native-repeat-rows');
            const add = node('button', 'Add another row', 'btn'); add.type = 'button';
            const sync = () => { root.value = JSON.stringify(rows); changed(); };
            function render() {
                list.replaceChildren();
                rows.forEach((row, index) => {
                    const group = node('fieldset', undefined, 'native-repeat-row');
                    group.append(node('legend', `Row ${index + 1}`));
                    (field.children || []).forEach(child => {
                        const label = node('label', child.label + (child.required ? ' (required)' : ''));
                        let control;
                        if (child.type === 'select') {
                            control = node('select'); const blank = node('option', 'Choose an option'); blank.value = ''; control.append(blank);
                            (child.options || []).forEach(value => { const option = node('option', value); option.value = value; control.append(option); });
                        } else {
                            control = node(child.type === 'textarea' ? 'textarea' : 'input');
                            if (child.type !== 'textarea') control.type = child.type;
                            if (child.type === 'number') { control.step = 'any'; if (child.min !== undefined) control.min = child.min; if (child.max !== undefined) control.max = child.max; }
                            control.maxLength = child.max_length || 2000;
                        }
                        control.required = !!child.required;
                        if (child.type === 'checkbox') control.checked = row[child.label] === 'yes';
                        else control.value = row[child.label] || '';
                        control.addEventListener('input', () => { row[child.label] = child.type === 'checkbox' ? (control.checked ? 'yes' : '') : control.value; sync(); });
                        control.addEventListener('change', () => { row[child.label] = child.type === 'checkbox' ? (control.checked ? 'yes' : '') : control.value; sync(); });
                        label.append(control); group.append(label);
                    });
                    const remove = node('button', 'Remove row', 'btn'); remove.type = 'button';
                    remove.addEventListener('click', () => { rows.splice(index, 1); render(); sync(); }); group.append(remove); list.append(group);
                });
                add.disabled = rows.length >= (field.max_items || 10);
            }
            add.addEventListener('click', () => {
                if (rows.length >= (field.max_items || 10)) return;
                rows.push({}); render(); sync(); list.lastElementChild?.querySelector('input, select, textarea')?.focus();
            });
            host.append(list, add);
            host.restore = () => { try { rows = JSON.parse(root.value || '[]'); } catch { rows = []; } if(!Array.isArray(rows)) rows=[];rows=rows.filter(row=>row&&typeof row==='object'&&!Array.isArray(row)).slice(0,field.max_items||10);render(); };
            host.setRequired = required => { if (required && !rows.length) { rows.push({}); render(); root.value = JSON.stringify(rows); } };
            if (field.required && !rows.length) rows.push({});
            render(); root.value = JSON.stringify(rows);
        } else if (field.type === 'signature') {
            let data;
            try { data = JSON.parse(root.value || '{}'); } catch { data = {}; }
            if(!data || typeof data!=='object' || Array.isArray(data)) data={};
            if(!Array.isArray(data.strokes) || data.strokes.some(stroke=>!Array.isArray(stroke)||stroke.some(point=>!Array.isArray(point)||point.length!==2||point.some(value=>typeof value!=='number'||value<0||value>1)))) data.strokes=[];
            if(typeof data.name!=='string') data.name='';
            let strokes = data.strokes || [], drawing = null;
            const nameLabel = node('label', 'Type your full name');
            const name = node('input'); name.type = 'text'; name.maxLength = 150; name.value = data.name || ''; nameLabel.append(name);
            const canvas = node('canvas', undefined, 'native-signature-canvas'); canvas.width = 600; canvas.height = 180;
            canvas.setAttribute('aria-label', 'Draw your signature using a mouse, finger or stylus');
            const context = canvas.getContext('2d');
            function paint() {
                context.clearRect(0, 0, 600, 180); context.lineWidth = 2; context.lineCap = 'round'; context.strokeStyle = '#252025';
                strokes.forEach(stroke => { context.beginPath(); stroke.forEach((point, index) => { if (index) context.lineTo(point[0]*600, point[1]*180); else context.moveTo(point[0]*600, point[1]*180); }); context.stroke(); });
            }
            function sync() {
                root.value = name.value.trim() || strokes.length ? JSON.stringify({name: name.value, strokes}) : '';
                name.required = host.required || !!strokes.length || !!name.value.trim();
                name.setCustomValidity(strokes.length || !name.required ? '' : 'Draw your signature.'); changed();
            }
            const point = event => { const rect = canvas.getBoundingClientRect(); return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)), Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))]; };
            canvas.addEventListener('pointerdown', event => {
                if (strokes.length >= 50) return;
                event.preventDefault(); canvas.setPointerCapture(event.pointerId); drawing = [point(event)]; strokes.push(drawing); paint();
            });
            canvas.addEventListener('pointermove', event => { if (drawing && strokes.reduce((sum, stroke) => sum+stroke.length, 0) < 4000) { drawing.push(point(event)); paint(); } });
            const finish = () => { if (drawing && drawing.length < 2) strokes.pop(); drawing = null; sync(); };
            canvas.addEventListener('pointerup', finish); canvas.addEventListener('pointercancel', finish);
            name.addEventListener('input', sync);
            const clear = node('button', 'Clear signature', 'btn'); clear.type = 'button'; clear.addEventListener('click', () => { strokes = []; paint(); sync(); });
            host.append(nameLabel, canvas, clear, node('p', 'Your typed name is recorded with the drawing. If you cannot draw, contact CL Paints for assistance.', 'native-help'));
            host.setRequired = required => { host.required = required; name.required = required || !!strokes.length || !!name.value.trim(); name.setCustomValidity(name.required && !strokes.length ? 'Draw your signature.' : ''); };
            host.restore = () => { name.value = ''; strokes = []; root.value = ''; paint(); };
            host.setRequired(!!field.required); paint();
        }
        root.hidden = true; root.required = false;
        root.after(host);
        return host;
    }
    window.CLNativeFeatures = {node, rules, matches, calculate, advanced};
})();
