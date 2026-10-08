(() => {
    'use strict';
    const form = document.getElementById('builder-form');
    const schema = document.getElementById('builder-schema');
    const raw = document.getElementById('builder-fields');
    const kind = document.getElementById('builder-kind');
    const questions = document.getElementById('builder-questions');
    const preview = document.getElementById('builder-preview');
    const maxBlocks = 30;
    const types = {text: 'Short answer', textarea: 'Long answer', select: 'Dropdown', radio: 'Radio buttons', cards: 'Selectable cards', gallery: 'Image-choice gallery', multiselect: 'Multiple choice checkboxes', checkbox: 'Confirmation checkbox', number: 'Number', date: 'Date', time: 'Time', email: 'Email address', tel: 'Phone number', url: 'Website address', repeat: 'Repeating section', signature: 'Drawn signature', file: 'Private file upload', calculation: 'Calculated result', content: 'Text / instructions', heading: 'Section heading', image: 'Image', pagebreak: 'New page / step'};
    const displayTypes = ['content', 'heading', 'image', 'pagebreak'];
    const choiceTypes = ['select', 'radio', 'cards', 'gallery', 'multiselect'];
    const features = window.CLNativeFeatures;
    const textTypes = ['text', 'textarea', 'email', 'tel', 'url'];
    const guidance = {
        giveaway: ['Clients sign in with a verified account. Each account can enter once per giveaway.', 'Describe the prize, eligibility, closing date and how you will choose and contact the winner.'],
        photo: ['Clients sign in, name participants, confirm permission and upload one to three photos or videos.', 'Explain where media may be used, permission limits and how clients can contact you to withdraw consent.'],
        booking: ['Adds your information and questions to the standard booking form. Requests appear in Bookings.', 'Explain the seasonal service, pricing, travel details and any restrictions.']
    };
    const node = (tag, text, className) => {
        const element = document.createElement(tag);
        if (text !== undefined) element.textContent = text;
        if (className) element.className = className;
        return element;
    };
    function button(text, action, disabled = false) {
        const control = node('button', text, 'btn');
        control.type = 'button'; control.disabled = disabled;
        control.addEventListener('click', action);
        return control;
    }
    const isImageSource = value => /^\/form-images\/[1-9]\d*$/.test(value) || (() => {
        try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password; } catch { return false; }
    })();
    const uploadedPreviews=new Map();
    const previewFiles=new Map();
    const imageNode = (src, alt = '') => {
        const img = node('img');
        if (isImageSource(src)) img.src = uploadedPreviews.get(src) || src;
        img.alt = alt; img.referrerPolicy = 'no-referrer';
        img.addEventListener('error',()=>{
            img.hidden=true;
            const message=node('p','This image could not load. Check the image link or sign in again, then refresh the preview.','native-help');
            img.after(message);
        },{once:true});
        return img;
    };
    let items = [];
    let visual = true;
    let dirty = false;
    let pendingUploads = 0;
    let conditionRefreshers = [];
    let selectedBlock = null;
    const restoreHooks=[];
    let history=null,historyIndex=0,restoring=false,autosaveTimer,autosaving=false;
    let manualSaveRequested=false;
    let draggedBlock = null;
    const previewValues = new Map();
    let previewPage = 0;
    function dependencies(item) {
        return [...features.rules(item.show_if), ...features.rules(item.required_if)].map(rule => rule.field).concat(item.calculation?.sources || []);
    }
    function defaults(item, index) {
        if (item.type === 'repeat') { item.children ||= [{label:'Full name', type:'text', required:true}]; item.max_items ||= 10; }
        if (item.type === 'file') { item.file_types ||= ['images','pdf']; item.max_files ||= 3; }
        if (item.type === 'calculation' && !item.calculation) {
            const source=items.slice(0,index).filter(other=>['number','select','radio','cards','gallery','multiselect','checkbox','repeat','calculation'].includes(other.type)).at(-1);
            item.calculation={operation:source?.type==='repeat'?'count':'sum',sources:source?[source.label]:[],base:'0',precision:source?.type==='repeat'?0:2,prefix:''};
        }
    }
    try {
        if (!schema.disabled && schema.value) {
            items = JSON.parse(schema.value);
            if (!Array.isArray(items) || items.some(item => !item || typeof item !== 'object' || !types[item.type] || typeof item.label !== 'string')) throw new Error('Invalid blocks');
        } else {
            items = raw.value.split(/\r?\n/).filter(line => line.trim()).map(line => {
                const parts = line.split('|').map(value => value.trim());
                if (parts.length < 3 || parts.length > 4 || !types[parts[1]] || !['required', 'optional'].includes(parts[2])) throw new Error('Invalid question');
                return {label: parts[0], type: parts[1], required: parts[2] === 'required', options: (parts[3] || '').split(',').map(value => value.trim()).filter(Boolean)};
            });
        }
    } catch { visual = false; }
    if (visual) items.forEach((item, index) => { item.layout ||= {row: index + 1, column: 1, width: 12}; defaults(item,index); });
    const grid = document.getElementById('builder-placement-grid');
    const gridStatus = document.getElementById('builder-grid-status');
    function layoutError(blocks) {
        const occupied = new Set();
        for (const item of blocks) {
            const {row, column, width} = item.layout;
            if (![row, column, width].every(Number.isInteger) || row < 1 || row > 60 || column < 1 || width < 1 || column + width > 13) return 'Use rows 1–60 and keep the block inside the 12 columns.';
            for (let cell = column; cell < column + width; cell++) {
                const key = `${row}:${cell}`;
                if (occupied.has(key)) return 'That space is occupied. Choose a free row or column, or reduce the width.';
                occupied.add(key);
            }
            for (const label of dependencies(item)) {
                const parent = blocks.find(other => other.label === label);
                if (!parent || parent.layout.row > row || (parent.layout.row === row && parent.layout.column >= column)) return 'Keep the condition question before the block it controls.';
            }
        }
        return '';
    }
    function commitLayouts(layouts, item, focusGrid = false) {
        const error = layoutError(items.map((block, index) => ({...block, layout: layouts[index]})));
        if (error) { gridStatus.textContent = error; return false; }
        items.forEach((block, index) => { block.layout = layouts[index]; });
        items.sort((a, b) => a.layout.row - b.layout.row || a.layout.column - b.layout.column);
        selectedBlock = item;
        renderQuestions(); changed();
        gridStatus.textContent = `${item?.label || 'Layout'} placed${item ? ` at row ${item.layout.row}, column ${item.layout.column}, width ${item.layout.width}` : ''}. Save the draft to keep this layout.`;
        if (focusGrid && item) grid.querySelector(`[data-block-index="${items.indexOf(item)}"]`)?.focus({preventScroll: true});
        return true;
    }
    function placeBlock(item, layout, focusGrid = false) {
        return commitLayouts(items.map(block => block === item ? layout : {...block.layout}), item, focusGrid);
    }
    document.getElementById('builder-arrange-rows').addEventListener('click', () => {
        const count=Number(document.getElementById('builder-row-columns').value),width=12/count;
        let row=1,column=1;
        const layouts=items.map(item=>{
            if (item.type==='pagebreak') {
                if(column!==1)row++;
                const layout={row,column:1,width:12};row++;column=1;return layout;
            }
            const layout={row,column,width};column+=width;
            if(column>12){row++;column=1;}return layout;
        });
        if(commitLayouts(layouts,selectedBlock)) gridStatus.textContent=`Arranged ${count} blocks per row without overlaps. Review the preview and save your draft.`;
    });
    function selectBlock(item, scroll = true) {
        selectedBlock = item;
        document.querySelectorAll('[data-block-index]').forEach(control => control.classList.toggle('builder-grid-selected', items[Number(control.dataset.blockIndex)] === item));
        questions.querySelectorAll('.builder-question').forEach(control => {
            const selected = items[Number(control.dataset.blockIndex)] === item;
            const settings = control.querySelector('.builder-block-settings');
            settings.hidden = !selected;
            settings.disabled = !selected;
            control.querySelector('.builder-block-toggle').setAttribute('aria-expanded', String(selected));
        });
        const card = questions.querySelector(`[data-block-index="${items.indexOf(item)}"]`);
        if (scroll) { card?.scrollIntoView({behavior: 'smooth', block: 'nearest'}); card?.querySelector('input')?.focus({preventScroll: true}); }
    }
    function renderGrid() {
        grid.replaceChildren();
        const rows = Math.min(60, Math.max(4, ...items.map(item => item.layout.row + 2)));
        for (let row = 1; row <= rows; row++) for (let column = 1; column <= 12; column++) {
            const cell = node('div', undefined, 'builder-grid-cell');
            cell.style.gridRow = row; cell.style.gridColumn = column;
            cell.dataset.gridRow = row; cell.dataset.gridColumn = column;
            cell.setAttribute('aria-hidden', 'true'); grid.append(cell);
        }
        items.forEach((item, index) => {
            const tile = node('button', undefined, 'builder-grid-tile'); tile.type = 'button'; tile.draggable = true;
            tile.dataset.blockIndex = index; tile.dataset.gridRow = item.layout.row; tile.dataset.gridColumn = item.layout.column;
            tile.style.setProperty('--block-row', item.layout.row); tile.style.setProperty('--block-column', item.layout.column); tile.style.setProperty('--block-width', item.layout.width);
            tile.classList.toggle('builder-grid-selected', selectedBlock === item);
            tile.append(node('strong', item.label || types[item.type]), node('small', `Row ${item.layout.row} · Col ${item.layout.column} · Width ${item.layout.width}/12`));
            tile.setAttribute('aria-label', `${item.label || types[item.type]}, row ${item.layout.row}, column ${item.layout.column}, width ${item.layout.width} of 12. Select to edit.`);
            tile.setAttribute('aria-describedby', 'builder-grid-help');
            tile.addEventListener('click', () => selectBlock(item));
            tile.addEventListener('dragstart', event => {
                draggedBlock = item; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index));
            });
            tile.addEventListener('dragend', () => { draggedBlock = null; grid.querySelectorAll('.builder-drop-target').forEach(cell => cell.classList.remove('builder-drop-target')); });
            tile.addEventListener('keydown', event => {
                if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
                event.preventDefault();
                const layout = {...item.layout};
                if (event.shiftKey && ['ArrowLeft', 'ArrowRight'].includes(event.key)) layout.width += event.key === 'ArrowRight' ? 1 : -1;
                else if (event.key === 'ArrowLeft') layout.column--;
                else if (event.key === 'ArrowRight') layout.column++;
                else layout.row += event.key === 'ArrowDown' ? 1 : -1;
                placeBlock(item, layout, true);
            });
            const handle = node('span', undefined, 'builder-grid-resize'); handle.setAttribute('aria-hidden', 'true');
            handle.addEventListener('pointerdown', event => {
                event.preventDefault(); event.stopPropagation();
                const startX = event.clientX, original = item.layout.width;
                const step = (grid.getBoundingClientRect().width - 4) / 12;
                let width = original;
                tile.draggable = false; handle.setPointerCapture(event.pointerId);
                handle.onpointermove = move => {
                    width = Math.max(1, Math.min(13 - item.layout.column, original + Math.round((move.clientX - startX) / step)));
                    tile.style.setProperty('--block-width', width);
                };
                handle.onpointerup = () => {
                    handle.onpointermove = null; handle.onpointerup = null; tile.draggable = true;
                    if (!placeBlock(item, {...item.layout, width}, true)) tile.style.setProperty('--block-width', original);
                };
                handle.onpointercancel = () => { handle.onpointermove = null; handle.onpointerup = null; tile.draggable = true; tile.style.setProperty('--block-width', original); };
            });
            handle.addEventListener('click', event => event.stopPropagation());
            tile.append(handle); grid.append(tile);
        });
    }
    grid.addEventListener('dragover', event => {
        if (!draggedBlock) return;
        event.preventDefault(); event.dataTransfer.dropEffect = 'move';
        grid.querySelectorAll('.builder-drop-target').forEach(cell => cell.classList.remove('builder-drop-target'));
        event.target.closest('[data-grid-row]')?.classList.add('builder-drop-target');
    });
    grid.addEventListener('drop', event => {
        if (!draggedBlock) return;
        event.preventDefault();
        const cell = event.target.closest('[data-grid-row]');
        if (cell) placeBlock(draggedBlock, {row: Number(cell.dataset.gridRow), column: Number(cell.dataset.gridColumn), width: draggedBlock.layout.width}, true);
        draggedBlock = null;
        grid.querySelectorAll('.builder-drop-target').forEach(control => control.classList.remove('builder-drop-target'));
    });
    document.getElementById('builder-stack').addEventListener('click', () => {
        commitLayouts(items.map((item, index) => ({row: index + 1, column: 1, width: 12})), selectedBlock);
    });
    function serialize() { if (visual) schema.value = JSON.stringify(items); }
    function changed() {
        dirty = true;
        document.getElementById('builder-save-status').textContent = 'Unsaved changes';
        serialize(); updatePreview(); if (visual) renderGrid();
        if (history && !restoring) rememberEdit();
        if (history && form.dataset.locked!=='yes') {clearTimeout(autosaveTimer);autosaveTimer=setTimeout(autosaveDraft,1800);}
    }
    function updatePreview() {
        const active = preview.contains(document.activeElement) ? document.activeElement : null;
        const activeName = active?.name, activeValue = active?.value;
        const activeBlock = active?.closest('[data-preview-index]');
        const activeControlIndex = activeBlock ? [...activeBlock.querySelectorAll('input,select,textarea,button')].indexOf(active) : -1;
        const caret = active?.selectionStart;
        const help = guidance[kind.value];
        document.getElementById('builder-kind-help').textContent = help[0];
        document.getElementById('builder-terms-help').textContent = help[1];
        document.getElementById('builder-terms').required = kind.value !== 'booking';
        preview.replaceChildren();
        preview.append(node('h3', document.getElementById('builder-title').value || 'Your form title'));
        preview.append(node('p', document.getElementById('builder-description').value || 'Your introduction will appear here.', 'builder-preserve'));
        preview.append(node('p', help[0], 'builder-standard-fields'));
        const previewGrid = node('div', undefined, 'native-fields');
        preview.append(previewGrid);
        const visibleValues = new Map();
        const definitions = new Map(items.map(item => [item.label,item]));
        let step = 0;
        const starts = new Map([[0,1]]);
        if (visual) items.forEach((item, index) => {
            if (item.type === 'pagebreak') { step++; starts.set(step,item.layout.row); }
            const condition = item.show_if;
            if (!features.matches(condition, visibleValues)) return;
            const block = node('div', undefined, `native-block native-block-${item.type}`);
            block.dataset.previewIndex=index; block.dataset.previewPage=step;
            block.style.setProperty('--block-row', item.layout.row-starts.get(step)+1);
            block.style.setProperty('--block-column', item.layout.column);
            block.style.setProperty('--block-width', item.layout.width);
            if (displayTypes.includes(item.type)) {
                if (item.type === 'image') {
                    const figure = node('figure', undefined, `native-image native-image-${item.size || 'full'} native-align-${item.align || 'center'}`);
                    if (item.src && isImageSource(item.src)) figure.append(imageNode(item.src, item.alt || ''));
                    else figure.append(node('p', 'Choose an image to see it here.'));
                    if (item.content) figure.append(node('figcaption', item.content, 'native-preserve'));
                    block.append(figure);
                } else {
                    block.append(node('h3', item.label || types[item.type]));
                    if (item.content) block.append(node('p', item.content, 'native-preserve'));
                }
            } else {
                let value = previewValues.get(item.label) || '';
                if (item.type === 'repeat') { try { value = JSON.parse(value || '[]'); } catch { value=[]; } }
                visibleValues.set(item.label, value);
                const required = !!item.required || (!!item.required_if && features.matches(item.required_if,visibleValues));
                const title = (item.label || 'Untitled question') + (required ? ' (required)' : ' (optional)');
                const remember = value => { previewValues.set(item.label, value); updatePreview(); };
                if (item.type === 'calculation') {
                    block.append(node('label',item.label || 'Calculated result'));
                    const result=features.calculate(item,visibleValues,definitions);
                    block.append(node('output',(item.calculation.prefix || '')+result)); visibleValues.set(item.label,result);
                } else if (['repeat','signature'].includes(item.type)) {
                    block.append(node('label',title)); const root=node('textarea'); root.value=previewValues.get(item.label) || ''; root.name=`preview_${index}`;
                    block.append(root); const host=features.advanced(item,root,() => remember(root.value));
                    host.setRequired?.(required); previewValues.set(item.label,root.value);
                    if (item.type==='repeat') { try { visibleValues.set(item.label,JSON.parse(root.value)); } catch { visibleValues.set(item.label,[]); } }
                } else if (item.type==='file') {
                    const label=node('label',title), input=node('input'); input.type='file'; input.multiple=true; input.required=required;
                    input.accept=(item.file_types.includes('images') ? 'image/jpeg,image/png,image/webp,' : '')+(item.file_types.includes('pdf') ? 'application/pdf' : '');
                    const thumbnails=node('div',undefined,'builder-file-thumbnails');
                    const showFiles=()=>{
                        thumbnails.replaceChildren();
                        (previewFiles.get(item.label) || []).forEach(file=>{
                            const figure=node('figure');
                            if(file.url){const image=node('img');image.src=file.url;image.alt=file.file.name;figure.append(image);}
                            figure.append(node('figcaption',file.file.name));thumbnails.append(figure);
                        });
                    };
                    const existing=previewFiles.get(item.label);
                    if(existing?.length){const transfer=new DataTransfer();existing.forEach(file=>transfer.items.add(file.file));input.files=transfer.files;}
                    input.addEventListener('change',()=>{
                        (previewFiles.get(item.label) || []).forEach(file=>{if(file.url)URL.revokeObjectURL(file.url);});
                        previewFiles.set(item.label,[...input.files].map(file=>({file,url:['image/jpeg','image/png','image/webp'].includes(file.type)&&file.size<=10000000?URL.createObjectURL(file):null})));
                        previewValues.set(item.label,[...input.files].map(file=>file.name));showFiles();
                    });
                    showFiles();label.append(input); block.append(label,thumbnails,node('p','Selected images appear here for testing only. Preview files are never submitted.','native-help'));
                } else if (['radio', 'cards', 'gallery', 'multiselect'].includes(item.type)) {
                    const group = node('fieldset', undefined, 'native-choice-group');
                    group.append(node('legend', title));
                    const choices = node('div', undefined, (['cards','gallery'].includes(item.type) ? 'native-card-grid' : 'native-choice-list') + ` native-spacing-${item.option_spacing || 'comfortable'}` + (item.type==='gallery' ? ' native-image-gallery' : ''));
                    choices.style.setProperty('--choice-columns', item.option_columns || (['cards','gallery'].includes(item.type) ? 2 : 1));
                    (item.options || []).forEach(option => {
                        const label = node('label', undefined, ['cards','gallery'].includes(item.type) ? 'native-choice-card' : 'native-choice');
                        const input = node('input');
                        input.type = item.type === 'multiselect' ? 'checkbox' : 'radio';
                        input.name = `preview_${index}`; input.value = option;
                        input.required = required && item.type !== 'multiselect';
                        input.checked = item.type === 'multiselect' ? Array.isArray(value) && value.includes(option) : value === option;
                        input.addEventListener('change', () => {
                            if (item.type === 'multiselect') {
                                const selected = new Set(Array.isArray(value) ? value : []);
                                if (input.checked) selected.add(option); else selected.delete(option);
                                remember([...selected]);
                            } else remember(option);
                        });
                        const span = node('span');
                        if (['cards','gallery'].includes(item.type) && item.option_images?.[option]) span.append(imageNode(item.option_images[option]));
                        span.append(document.createTextNode(option)); label.append(input, span); choices.append(label);
                    });
                    group.append(choices);
                    if (item.type === 'multiselect' && required && !(Array.isArray(value) && value.length)) choices.querySelector('input')?.setCustomValidity('Choose at least one option.');
                    if (!required && item.type !== 'multiselect') group.append(button('Clear selection', () => remember('')));
                    block.append(group);
                } else {
                    const label = node('label', title);
                    let control;
                    if (item.type === 'select') {
                        control = node('select'); const empty = node('option', 'Choose an option'); empty.value = ''; control.append(empty);
                        (item.options || []).forEach(value => { const option = node('option', value); option.value = value; control.append(option); });
                        control.value = value; control.addEventListener('change', () => remember(control.value));
                    } else if (item.type === 'checkbox') {
                        control = node('input'); control.type = 'checkbox'; control.checked = value === 'yes';
                        control.addEventListener('change', () => remember(control.checked ? 'yes' : ''));
                    } else {
                        control = node(item.type === 'textarea' ? 'textarea' : 'input');
                        if (item.type !== 'textarea') control.type = item.type;
                        control.placeholder = item.placeholder || '';
                        control.value = value;
                        control.maxLength = item.max_length || 2000;
                        if (item.type === 'number') {
                            control.step = 'any';
                            if (item.min !== undefined) control.min = item.min;
                            if (item.max !== undefined) control.max = item.max;
                        }
                        control.addEventListener('input', () => remember(control.value));
                    }
                    control.required = required;
                    label.append(control); block.append(label);
                    control.name = `preview_${index}`;
                }
                if (item.help) block.append(node('p', item.help, 'native-help'));
            }
            previewGrid.append(block);
        });
        else preview.append(node('p', 'Correct the advanced block settings to use the visual editor.'));
        preview.append(node('h4', kind.value === 'giveaway' ? 'Giveaway rules' : kind.value === 'photo' ? 'Photography / video permissions' : 'Seasonal booking information'));
        preview.append(node('p', document.getElementById('builder-terms').value || 'Your rules or information will appear here.', 'builder-preserve'));
        preview.append(node('p', 'Customers confirm they have read and agree to this wording.'));
        if (kind.value==='booking') {
            for (const [key,title] of [['packages','Packages'],['extras','Optional extras']]) {
                const lines=form.elements.namedItem(key)?.value.split('\n').filter(line=>line.trim()) || [];
                if (!lines.length) continue;
                preview.append(node('h4',title));
                const choices=node('div',undefined,'native-card-grid');
                lines.forEach(line=>{
                    const [name,price,hours,description,source]=line.split('|').map(value=>value.trim());
                    const card=node('div',undefined,'builder-package-preview');
                    if (source && isImageSource(source)) card.append(imageNode(source,name));
                    card.append(node('strong',name),node('p',`£${price || '0'}${key==='packages'?` · ${hours || '0'} hours per event`:''}`),node('small',description || ''));
                    choices.append(card);
                });preview.append(choices);
            }
            const cutoff=form.elements.namedItem('cutoff_days')?.value || '0';
            if (Number(cutoff)>0) preview.append(node('p',`Please allow at least ${cutoff} days before the event.`));
        }
        const start = document.getElementById('builder-start').value;
        const end = document.getElementById('builder-end').value;
        preview.append(node('p', `UK availability: ${start ? 'from ' + start.replace('T', ' ') : 'no opening date'}; ${end ? 'until ' + end.replace('T', ' ') : 'no closing date'}. Publish the saved draft to accept responses.`));
        if (step) {
            previewPage=Math.min(previewPage,step);
            const nav=node('div',undefined,'native-page-navigation');
            const show=() => { previewGrid.querySelectorAll('[data-preview-page]').forEach(block => {
                block.hidden=Number(block.dataset.previewPage)!==previewPage;
                block.querySelectorAll('input,select,textarea').forEach(input=>{input.disabled=block.hidden;});
            }); };
            const back=button('Previous',()=>{previewPage--;updatePreview();},previewPage===0);
            const next=button('Next step',()=>{
                const invalid=[...previewGrid.querySelectorAll('input,select,textarea')].find(input=>!input.disabled&&!input.reportValidity());
                if (!invalid) {previewPage++;updatePreview();}
            },previewPage===step);
            nav.append(back,node('span',`Step ${previewPage+1} of ${step+1}`),next); previewGrid.before(nav); show();
        }
        let focus = activeName ? [...preview.querySelectorAll('input,select,textarea')].find(control => control.name===activeName && control.value===activeValue) : null;
        if (!focus && activeBlock && activeControlIndex>=0) focus=preview.querySelector(`[data-preview-index="${activeBlock.dataset.previewIndex}"]`)?.querySelectorAll('input,select,textarea,button')[activeControlIndex];
        focus?.focus({preventScroll:true});
        if (focus && caret!==null && caret!==undefined && (focus.tagName==='TEXTAREA' || ['text','tel','url'].includes(focus.type))) focus.setSelectionRange(caret,caret);
    }
    function setting(item, title, key, tag = 'input', maxLength = 150) {
        const label = node('label', title);
        const control = node(tag);
        control.value = item[key] ?? '';
        control.maxLength = maxLength;
        if (tag === 'textarea') control.rows = 3;
        control.addEventListener('input', () => {
            const old = item[key];
            item[key] = control.value;
            if (key === 'label') {
                items.forEach(other => {
                    for (const rule of [other.show_if,other.required_if]) {
                        if (rule?.field===old) rule.field=control.value;
                        rule?.rules?.forEach(row=>{if(row.field===old) row.field=control.value;});
                    }
                    if(other.calculation) other.calculation.sources=other.calculation.sources.map(label=>label===old?control.value:label);
                });
                conditionRefreshers.forEach(refresh => refresh());
                const index=items.indexOf(item);
                const heading=questions.querySelector(`[data-block-index="${index}"] .builder-block-toggle`);
                if (heading) heading.textContent=`Block ${index+1}: ${item.label || types[item.type]}`;
                const gridTitle=grid.querySelector(`[data-block-index="${index}"] strong`);
                if (gridTitle) gridTitle.textContent=item.label || types[item.type];
            }
            changed();
        });
        label.append(control);
        return {label, control};
    }
    function selection(title, value, options, onChange) {
        const label = node('label', title);
        const control = node('select');
        Object.entries(options).forEach(([value, text]) => { const option = node('option', text); option.value = value; control.append(option); });
        control.value = value;
        control.addEventListener('change', () => onChange(control.value));
        label.append(control);
        return label;
    }
    function imageSetting(title, value, save) {
        const group = node('div', undefined, 'builder-image-setting');
        const label = node('label', title + ' (HTTPS link or uploaded image)');
        const input = node('input'); input.value = value || ''; input.maxLength = 2000;
        input.placeholder = 'https://example.com/image.jpg';
        input.addEventListener('input', () => { save(input.value); changed(); });
        label.append(input);
        const uploadLabel = node('label', 'Or upload JPG, PNG or WebP (up to 5 MB)');
        const upload = node('input'); upload.type = 'file'; upload.accept = 'image/jpeg,image/png,image/webp';
        uploadLabel.append(upload);
        const status = node('p'); status.setAttribute('role', 'status');
        upload.addEventListener('change', async () => {
            const file = upload.files[0];
            if (!file) return;
            if (file.size > 5000000) { status.textContent = 'Choose an image no larger than 5 MB.'; return; }
            const payload = new FormData();
            payload.append('csrf_token', form.querySelector('[name=csrf_token]').value);
            payload.append('image', file);
            pendingUploads++; upload.disabled = true; status.textContent = 'Uploading image…';
            try {
                const response = await fetch(form.dataset.uploadUrl, {method: 'POST', body: payload, credentials: 'same-origin'});
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || 'Upload failed.');
                if(uploadedPreviews.has(result.url))URL.revokeObjectURL(uploadedPreviews.get(result.url));
                uploadedPreviews.set(result.url,URL.createObjectURL(new Blob([file],{type:result.mime || file.type})));
                input.value = result.url; save(result.url); changed();
                status.textContent = 'Uploaded and shown in the preview. Save the draft to keep its placement.';
            } catch (error) { status.textContent = error.message || 'Upload failed. Try again.'; }
            finally { pendingUploads--; upload.disabled = false; }
        });
        group.append(label, uploadLabel, status);
        return group;
    }
    function ruleEditor(item, key, index, title) {
        const panel=node('details',undefined,'builder-conditions');
        panel.append(node('summary',title)); panel.open=!!item[key];
        const allowed=items.slice(0,index).filter(other=>!['content','heading','image','pagebreak','signature','file'].includes(other.type)&&other.label.trim());
        const options=Object.fromEntries(allowed.map(other=>[other.label,other.label]));
        const rows=node('div');
        function render() {
            rows.replaceChildren();
            const current=features.rules(item[key]);
            current.forEach((rule,position)=>{
                const controls=node('div',undefined,'builder-rule-row');
                const update=(property,value)=>{
                    const rules=features.rules(item[key]).map(row=>({...row})); rules[position][property]=value;
                    item[key]={mode:item[key]?.mode || 'all',rules}; render(); changed();
                };
                controls.append(selection('Earlier question',rule.field,options,value=>update('field',value)));
                controls.append(selection('Comparison',rule.operator || 'equals',{equals:'Equals',not_equals:'Does not equal',contains:'Contains',greater:'Greater than',less:'Less than',answered:'Has an answer'},value=>update('operator',value)));
                const parent=allowed.find(other=>other.label===rule.field);
                if ((rule.operator || 'equals')==='equals' && parent && ['select','radio','cards','gallery','checkbox'].includes(parent.type)) {
                    const answers=parent.type==='checkbox'?{'yes':'Checked','':'Not checked'}:Object.fromEntries((parent.options||[]).map(value=>[value,value]));
                    controls.append(selection('Answer',rule.value??'',answers,value=>update('value',value)));
                } else if (rule.operator!=='answered') {
                    const label=node('label','Answer / number'); const input=node('input'); input.maxLength=150; input.value=rule.value??'';
                    input.addEventListener('input',()=>{
                        const rules=features.rules(item[key]).map(row=>({...row})); rules[position].value=input.value;
                        item[key]={mode:item[key]?.mode||'all',rules}; changed();
                    }); label.append(input);controls.append(label);
                }
                controls.append(button('Remove condition',()=>{
                    const rules=features.rules(item[key]).filter((row,i)=>i!==position);
                    if(rules.length) item[key]={mode:item[key]?.mode||'all',rules}; else delete item[key];
                    render();changed();
                }));rows.append(controls);
            });
        }
        panel.append(selection('Match',item[key]?.mode||'all',{all:'All conditions',any:'Any condition'},value=>{
            if(item[key]) item[key]={mode:value,rules:features.rules(item[key])}; changed();
        }),rows,button('Add condition',()=>{
            const existing=features.rules(item[key]);
            if(existing.length>=8||!allowed.length) return;
            const parent=allowed[0]; const value=parent.type==='checkbox'?'yes':(parent.options?.[0]||'');
            item[key]={mode:item[key]?.mode||'all',rules:[...existing,{field:parent.label,operator:'equals',value}]};
            panel.open=true;render();changed();
        },!allowed.length));
        if(!allowed.length) panel.append(node('p','Add an earlier answer field to use conditions.'));
        render();return panel;
    }
    function repeatEditor(item) {
        const group=node('div',undefined,'builder-repeat-editor');
        const childTypes={text:'Short answer',textarea:'Long answer',number:'Number',date:'Date',email:'Email',tel:'Phone',select:'Dropdown',checkbox:'Confirmation'};
        const maximum=setting(item,'Maximum rows (1–20)','max_items'); maximum.control.type='number';maximum.control.min=1;maximum.control.max=20;
        maximum.control.addEventListener('input',()=>{item.max_items=Number(maximum.control.value);changed();});group.append(maximum.label);
        const children=node('div');
        function render() {
            children.replaceChildren();
            item.children.forEach((child,index)=>{
                const box=node('div',undefined,'builder-repeat-child');box.append(node('h4',`Repeated field ${index+1}`));
                const title=node('label','Field label'),input=node('input');input.maxLength=150;input.value=child.label;
                input.addEventListener('input',()=>{child.label=input.value;changed();});title.append(input);box.append(title);
                box.append(selection('Type',child.type,childTypes,value=>{child.type=value;if(value==='select') child.options||=[];render();changed();}));
                const required=node('label',undefined,'builder-checkbox'),checkbox=node('input');checkbox.type='checkbox';checkbox.checked=!!child.required;
                checkbox.addEventListener('change',()=>{child.required=checkbox.checked;changed();});required.append(checkbox,document.createTextNode('Answer required'));box.append(required);
                if(child.type==='select') {
                    const label=node('label','Choices (one per line)'),textarea=node('textarea');textarea.value=(child.options||[]).join('\n');
                    textarea.addEventListener('input',()=>{child.options=textarea.value.split('\n').map(value=>value.trim()).filter(Boolean);changed();});label.append(textarea);box.append(label);
                }
                box.append(button('Remove repeated field',()=>{item.children.splice(index,1);render();changed();},item.children.length<=1));children.append(box);
            });
        }
        group.append(children,button('Add repeated field',()=>{
            if(item.children.length>=6) return;
            item.children.push({label:`Field ${item.children.length+1}`,type:'text',required:false});render();changed();
        }));render();return group;
    }
    function renderQuestions(focusIndex) {
        if (focusIndex >= 0) selectedBlock = items[focusIndex] || null;
        if (!items.includes(selectedBlock)) selectedBlock = null;
        questions.replaceChildren();
        conditionRefreshers = [];
        items.forEach((item, index) => {
            const card = node('div', undefined, 'builder-question');
            card.dataset.blockIndex = index;
            card.classList.toggle('builder-grid-selected', selectedBlock === item);
            const heading = node('h3');
            const toggle = button(`Block ${index + 1}: ${item.label || types[item.type]}`, () => selectBlock(selectedBlock === item ? null : item, false));
            toggle.classList.add('builder-block-toggle');
            toggle.setAttribute('aria-expanded', String(selectedBlock === item));
            toggle.setAttribute('aria-controls', `builder-block-settings-${index}`);
            heading.append(toggle); card.append(heading);
            const label = setting(item, displayTypes.includes(item.type) ? 'Block title' : 'Question wording', 'label');
            label.control.required = true;
            card.append(label.label);
            const placement = node('div', undefined, 'builder-placement-controls');
            for (const [key, title, max] of [['row', 'Grid row', 60], ['column', 'Start column', 12], ['width', 'Width (columns)', 12]]) {
                const positionLabel = node('label', title);
                const positionInput = node('input'); positionInput.type = 'number'; positionInput.min = 1; positionInput.max = max; positionInput.step = 1;
                positionInput.value = item.layout[key]; positionInput.dataset.layoutSetting = key;
                positionInput.addEventListener('change', () => {
                    if (!placeBlock(item, {...item.layout, [key]: Number(positionInput.value)})) positionInput.value = item.layout[key];
                });
                positionLabel.append(positionInput); placement.append(positionLabel);
            }
            card.append(placement);
            card.append(selection('Block type', item.type, types, value => {
                item.type = value;
                defaults(item,index);
                if (displayTypes.includes(value)) item.required = false;
                if (choiceTypes.includes(value) && !item.options) item.options = [];
                renderQuestions(index); changed();
            }));
            const display = displayTypes.includes(item.type);
            if (!display && item.type!=='calculation') {
                const requiredLabel = node('label', undefined, 'builder-checkbox');
                const required = node('input'); required.type = 'checkbox'; required.checked = !!item.required;
                required.addEventListener('change', () => { item.required = required.checked; changed(); });
                requiredLabel.append(required, document.createTextNode('Answer required')); card.append(requiredLabel);
                card.append(setting(item, 'Help text (optional)', 'help', 'textarea', 1000).label);
            }
            if(item.type==='repeat') card.append(repeatEditor(item));
            if(item.type==='file') {
                card.append(selection('Allowed files',item.file_types.join(','),{'images,pdf':'Images and PDF','images':'Images only','pdf':'PDF only'},value=>{item.file_types=value.split(',');changed();}));
                const max=setting(item,'Maximum files (1–6)','max_files');max.control.type='number';max.control.min=1;max.control.max=6;
                max.control.addEventListener('input',()=>{item.max_files=Number(max.control.value);changed();});card.append(max.label);
            }
            if(item.type==='calculation') {
                const config=item.calculation;
                card.append(selection('Calculation',config.operation,{sum:'Add amounts to the base',product:'Multiply the base by each source',percentage:'Apply the base percentage to sources',count:'Count rows / selections'},value=>{config.operation=value;if(value==='product'&&config.base==='0') config.base='1';changed();}));
                const sources=node('fieldset');sources.append(node('legend','Use earlier fields'));
                items.slice(0,index).filter(other=>['number','select','radio','cards','gallery','multiselect','checkbox','repeat','calculation'].includes(other.type)&&other.label).forEach(other=>{
                    const label=node('label',undefined,'builder-checkbox'),input=node('input');input.type='checkbox';input.checked=config.sources.includes(other.label);
                    input.addEventListener('change',()=>{config.sources=input.checked?[...config.sources,other.label]:config.sources.filter(value=>value!==other.label);changed();});label.append(input,document.createTextNode(other.label));sources.append(label);
                });card.append(sources);
                const base=setting(config,'Base amount / percentage','base');base.control.type='number';base.control.step='any';card.append(base.label);
                card.append(selection('Decimal places',String(config.precision),{'0':'0','1':'1','2':'2','3':'3','4':'4'},value=>{config.precision=Number(value);changed();}));
                card.append(setting(config,'Prefix (optional, e.g. £)','prefix','input',12).label);
                card.append(node('p','Choice amounts are configured on their source questions. Calculations are checked by the server on submission.','native-help'));
            }
            if(item.type==='checkbox') {
                const amount=setting(item,'Amount when checked (optional, for calculations)','checked_value');amount.control.type='number';amount.control.step='any';card.append(amount.label);
            }
            if (display) {
                const content = setting(item, item.type === 'image' ? 'Caption (optional)' : item.type === 'heading' ? 'Section introduction (optional)' : 'Read-only text', 'content', 'textarea', 10000);
                content.control.required = item.type === 'content'; card.append(content.label);
                if (item.type === 'image') {
                    card.append(imageSetting('Image', item.src, value => { item.src = value; }));
                    const alt = setting(item, 'Image description for screen readers', 'alt', 'input', 300); alt.control.required = true; card.append(alt.label);
                    card.append(selection('Image size', item.size || 'full', {small: 'Small (up to 240px)', medium: 'Medium (up to 480px)', full: 'Full width'}, value => { item.size = value; changed(); }));
                    card.append(selection('Image alignment', item.align || 'center', {left: 'Left', center: 'Centre', right: 'Right'}, value => { item.align = value; changed(); }));
                }
            }
            if (choiceTypes.includes(item.type)) {
                if (item.type !== 'select') {
                    const layoutOptions = node('div', undefined, 'builder-option-settings');
                    layoutOptions.append(selection('Option columns', String(item.option_columns || (['cards','gallery'].includes(item.type) ? 2 : 1)), {'1': 'One column', '2': 'Two columns', '3': 'Three columns'}, value => { item.option_columns = Number(value); changed(); }));
                    layoutOptions.append(selection('Option spacing', item.option_spacing || 'comfortable', {compact: 'Compact', comfortable: 'Comfortable', spacious: 'Spacious'}, value => { item.option_spacing = value; changed(); }));
                    card.append(layoutOptions);
                }
                const optionsLabel = node('label', 'Choices (one per line, up to 20)');
                const options = node('textarea'); options.rows = 4; options.value = (item.options || []).join('\n'); options.required = true;
                options.placeholder = 'Butterfly\nUnicorn\nTiger'; optionsLabel.append(options); card.append(optionsLabel);
                const images = node('div');
                function renderCardImages() {
                    images.replaceChildren();
                    if (!['cards','gallery'].includes(item.type)) return;
                    (item.options || []).forEach(option => images.append(imageSetting('Image for '+option+(item.type==='gallery'?' (required)':' (optional)'), item.option_images?.[option], value => {
                        item.option_images ||= {}; item.option_images[option] = value;
                    })));
                }
                options.addEventListener('input', () => {
                    item.options = options.value.split('\n').map(value => value.trim()).filter(Boolean);
                    if (item.option_images) Object.keys(item.option_images).forEach(key => { if (!item.options.includes(key)) delete item.option_images[key]; });
                    renderCardImages(); conditionRefreshers.forEach(refresh => refresh()); changed();
                });
                card.append(images); renderCardImages();
                const amounts=node('details');amounts.append(node('summary','Amounts for calculations (optional)'));
                const amountInputs=node('div');
                function renderAmounts() {
                    amountInputs.replaceChildren();
                    (item.options||[]).forEach(option=>{
                        const label=node('label',option),input=node('input');input.type='number';input.step='any';input.value=item.option_values?.[option]||'';
                        input.addEventListener('input',()=>{item.option_values||={};if(input.value) item.option_values[option]=input.value;else delete item.option_values[option];changed();});label.append(input);amountInputs.append(label);
                    });
                }
                options.addEventListener('input',()=>{if(item.option_values) Object.keys(item.option_values).forEach(key=>{if(!item.options.includes(key)) delete item.option_values[key];});renderAmounts();});
                amounts.append(amountInputs);renderAmounts();card.append(amounts);
            }
            if (textTypes.includes(item.type)) {
                card.append(setting(item, 'Placeholder (optional)', 'placeholder').label);
                const limit = setting(item, 'Maximum answer length (1–2000 characters)', 'max_length');
                limit.control.type = 'number'; limit.control.min = '1'; limit.control.max = '2000'; limit.control.value = item.max_length || 2000;
                limit.control.addEventListener('input', () => { item.max_length = Number(limit.control.value); changed(); }); card.append(limit.label);
            }
            if (item.type === 'number') {
                ['min', 'max'].forEach(key => {
                    const limit = setting(item, key === 'min' ? 'Minimum value (optional)' : 'Maximum value (optional)', key);
                    limit.control.type = 'number'; limit.control.step = 'any'; card.append(limit.label);
                });
            }
            const ruleControls = node('div');
            const refreshCondition = () => {
                ruleControls.replaceChildren(ruleEditor(item, 'show_if', index, 'Show this block when…'));
                if (!display && item.type !== 'calculation') ruleControls.append(ruleEditor(item, 'required_if', index, 'Require an answer when…'));
            };
            conditionRefreshers.push(refreshCondition); refreshCondition(); card.append(ruleControls);
            const actions = node('div', undefined, 'builder-actions');
            const move = offset => {
                const layouts = items.map(block => ({...block.layout}));
                [layouts[index], layouts[index + offset]] = [layouts[index + offset], layouts[index]];
                commitLayouts(layouts, item);
            };
            actions.append(button('Move up', () => move(-1), index === 0), button('Move down', () => move(1), index === items.length - 1));
            actions.append(button('Duplicate block', () => {
                let number = 1, label;
                do { label = `${item.label.slice(0, 130)} (copy ${number++})`; } while (items.some(other => other.label === label));
                const row = Math.max(0, ...items.map(block => block.layout.row)) + 1;
                if (row > 60) { gridStatus.textContent = 'Stack blocks or free a row before duplicating.'; return; }
                const copy = {...JSON.parse(JSON.stringify(item)), label, layout: {...item.layout, row}};
                items.push(copy); selectedBlock = copy; renderQuestions(items.length - 1); changed();
            }, items.length >= maxBlocks));
            actions.append(button('Remove block', () => {
                if (items.some(other => dependencies(other).includes(item.label)) && !window.confirm('Other blocks use this question in their rules or calculations. Remove the question and its references?')) return;
                items.forEach(other => {
                    for(const key of ['show_if','required_if']) {
                        const rules=features.rules(other[key]).filter(rule=>rule.field!==item.label);
                        if(rules.length) other[key]={mode:other[key]?.mode||'all',rules}; else delete other[key];
                    }
                    if(other.calculation) other.calculation.sources=other.calculation.sources.filter(label=>label!==item.label);
                });
                items.splice(index, 1); renderQuestions(Math.min(index, items.length - 1)); changed();
            }));
            card.append(actions);
            const settings = node('fieldset', undefined, 'builder-block-settings');
            settings.id = `builder-block-settings-${index}`;
            settings.setAttribute('aria-label', `Settings for block ${index + 1}`);
            settings.hidden = selectedBlock !== item;
            settings.disabled = selectedBlock !== item;
            while (card.children.length > 1) settings.append(card.children[1]);
            card.append(settings); questions.append(card);
        });
        if (!items.length) questions.append(node('p', 'Choose a question or content type below, then select Add block.'));
        document.getElementById('builder-count').textContent = `${items.length} / ${maxBlocks} blocks`;
        document.getElementById('builder-add').disabled = items.length >= maxBlocks;
        renderGrid();
        if (focusIndex >= 0) questions.querySelectorAll('.builder-question')[focusIndex]?.querySelector('input').focus();
    }
    if (visual) {
        schema.disabled = false;
        document.getElementById('builder-raw').hidden = true;
        document.getElementById('builder-question-actions').hidden = false;
        document.getElementById('builder-grid-panel').hidden = false;
        document.getElementById('builder-preview-modes').hidden = false;
        renderQuestions(); serialize();
    }
    const addTypeSelect=document.getElementById('builder-add-type');
    const addTypeGroups=[...addTypeSelect.children].map(group=>group.cloneNode(true));
    document.getElementById('builder-add-category').addEventListener('change',event=>{
        const previous=addTypeSelect.value;
        addTypeSelect.replaceChildren(...addTypeGroups.filter(group=>!event.target.value || group.label===event.target.value).map(group=>group.cloneNode(true)));
        if ([...addTypeSelect.options].some(option=>option.value===previous)) addTypeSelect.value=previous;
    });
    document.getElementById('builder-add').addEventListener('click', () => {
        if (items.length >= maxBlocks) return;
        const type=document.getElementById('builder-add-type').value;
        const width=type==='pagebreak'?12:Number(document.getElementById('builder-new-width').value);
        let row=Math.max(1,...items.map(item=>item.layout.row));
        const lastRow=items.filter(item=>item.layout.row===row);
        let column=Math.max(1,...lastRow.map(item=>item.layout.column+item.layout.width));
        if(column+width>13 || lastRow.some(item=>item.type==='pagebreak')) {row++;column=1;}
        if (row > 60) { gridStatus.textContent = 'Stack blocks or free a row before adding a block.'; return; }
        items.push({label: '', type, required: false, layout: {row,column,width}});
        defaults(items.at(-1),items.length-1);
        renderQuestions(items.length - 1); changed();
    });
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    for (const mode of ['desktop', 'mobile']) document.getElementById(`builder-preview-${mode}`).addEventListener('click', () => {
        preview.classList.toggle('builder-phone-preview', mode === 'mobile');
        document.getElementById('builder-preview-desktop').setAttribute('aria-pressed', String(mode === 'desktop'));
        document.getElementById('builder-preview-mobile').setAttribute('aria-pressed', String(mode === 'mobile'));
        document.getElementById('builder-dialog-desktop').setAttribute('aria-pressed', String(mode === 'desktop'));
        document.getElementById('builder-dialog-mobile').setAttribute('aria-pressed', String(mode === 'mobile'));
    });
    const dialog = document.getElementById('builder-preview-dialog');
    const previewHome = preview.parentElement;
    let previewOpener;
    document.querySelectorAll('.builder-open-preview').forEach(control => {
        control.hidden = false;
        control.addEventListener('click', () => {
            previewOpener = control;
            document.getElementById('builder-preview-slot').append(preview);
            document.getElementById('builder-preview-result').textContent = '';
            dialog.showModal();
        });
    });
    document.getElementById('builder-close-preview').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { previewHome.append(preview); previewOpener?.focus(); });
    for (const mode of ['desktop', 'mobile']) document.getElementById(`builder-dialog-${mode}`).addEventListener('click', () => document.getElementById(`builder-preview-${mode}`).click());
    document.getElementById('builder-preview-reset').addEventListener('click', () => {
        previewFiles.forEach(files=>files.forEach(file=>{if(file.url)URL.revokeObjectURL(file.url);}));previewFiles.clear();
        previewValues.clear(); updatePreview(); document.getElementById('builder-preview-result').textContent = 'Preview answers cleared.';
    });
    document.getElementById('builder-preview-test').addEventListener('submit', event => {
        event.preventDefault();
        const pages=1+items.filter(item=>item.type==='pagebreak').length;
        let valid=true;
        for(let page=0;page<pages;page++) {previewPage=page;updatePreview();if(!event.currentTarget.reportValidity()) {valid=false;break;}}
        document.getElementById('builder-preview-result').textContent = valid ? 'These preview answers pass the field checks. Nothing has been submitted.' : 'Complete the highlighted fields. Nothing has been submitted.';
    });
    const clear = document.getElementById('builder-clear-dates'); clear.hidden = false;
    clear.addEventListener('click', () => {
        document.getElementById('builder-start').value = ''; document.getElementById('builder-end').value = ''; changed();
    });
    function validationError() {
        if (pendingUploads) return 'Wait for image uploads to finish before saving.';
        if (!visual) return '';
        const placementError = layoutError(items);
        if (placementError) return placementError;
        const labels = items.map(item => item.label.trim());
        if (items.length > maxBlocks) return 'Use up to thirty blocks.';
        if (labels.some(label => !label)) return 'Give every block a title.';
        if (new Set(labels).size !== labels.length) return 'Give every block a different title.';
        for (const [index, item] of items.entries()) {
            if (choiceTypes.includes(item.type)) {
                const choices = item.options || [];
                if (!choices.length || choices.length > 20 || new Set(choices).size !== choices.length || choices.some(value => value.length > 150)) return 'Choice questions need 1 to 20 different choices, each up to 150 characters.';
            }
            if (item.type === 'image' && !isImageSource(item.src || '')) return 'Upload an image or enter an HTTPS image link.';
            if (['cards','gallery'].includes(item.type) && Object.values(item.option_images || {}).some(value => value && !isImageSource(value))) return 'Card images need an HTTPS link or uploaded image.';
            if (item.type==='gallery' && (item.options||[]).some(option=>!item.option_images?.[option])) return 'Add an image to every gallery choice.';
            for (const rule of [...features.rules(item.show_if),...features.rules(item.required_if)]) {
                const parent=items.slice(0,index).find(other=>other.label===rule.field);
                if(!parent) return 'Use an earlier question for each condition.';
                if((rule.operator || 'equals')==='equals' && ['select','radio','cards','gallery','checkbox'].includes(parent.type)) {
                    const values=parent.type==='checkbox'?['yes','']:parent.options||[];
                    if(!values.includes(rule.value)) return 'Update the condition to match a listed answer.';
                }
            }
            if(item.type==='calculation' && !item.calculation.sources.length) return 'Choose at least one source for each calculation.';
            if(item.type==='repeat' && (new Set(item.children.map(child=>child.label.trim())).size!==item.children.length || item.children.some(child=>!child.label.trim()))) return 'Give each repeated field a unique label.';
        }
        return '';
    }
    form.addEventListener('submit', event => {
        if(autosaving){event.preventDefault();manualSaveRequested=true;return;}
        clearTimeout(autosaveTimer);
        serialize(); let error = validationError();
        const start = document.getElementById('builder-start').value, end = document.getElementById('builder-end').value;
        if (start && end && end <= start) error = 'Closing time must follow opening time.';
        const message = document.getElementById('builder-error'); message.textContent = error;
        if (error) { event.preventDefault(); message.tabIndex = -1; message.focus(); }
        else dirty = false;
    });
    window.addEventListener('beforeunload', event => { if (dirty || pendingUploads) { event.preventDefault(); event.returnValue = ''; } });
    updatePreview();
    document.getElementById('builder-filter-tools').hidden = false;
    function filterForms() {
        const query = document.getElementById('builder-search').value.trim().toLowerCase(), status = document.getElementById('builder-filter').value;
        let count = 0;
        document.querySelectorAll('.builder-form-card').forEach(card => {
            card.hidden = !card.dataset.title.includes(query) || (status !== 'all' && status !== card.dataset.state);
            if (!card.hidden) count++;
        });
        document.getElementById('builder-library-status').textContent = count ? `${count} form${count === 1 ? '' : 's'} shown` : 'No forms match your search.';
    }
    document.getElementById('builder-search').addEventListener('input', filterForms);
    document.getElementById('builder-filter').addEventListener('change', filterForms);
    document.querySelectorAll('.builder-copy-link').forEach(control => {
        control.hidden = false;
        control.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(control.dataset.url);
                document.getElementById('builder-library-status').textContent = 'Public form link copied. Scheduled or closed forms only accept responses during their availability window.';
            } catch { window.prompt('Copy this public form link:', control.dataset.url); }
        });
    });
    const accessibilityButton=document.getElementById('builder-check-accessibility');accessibilityButton.hidden=false;
    accessibilityButton.addEventListener('click',()=>{
        const results=document.getElementById('builder-accessibility-results');results.replaceChildren();
        const issues=[],labels=new Set();
        items.forEach(item=>{
            const label=item.label.trim();
            if(!label||labels.has(label)) issues.push('Give every block a unique, descriptive label.'); labels.add(label);
            if(item.type==='image'&&!item.alt?.trim()) issues.push('Add an image description for '+(label||'the image')+'.');
            if(item.layout.width<3&&!['heading','image'].includes(item.type)) issues.push('Widen '+label+' so its label and answer fit comfortably.');
            if(['question','field','untitled','name here'].includes(label.toLowerCase())) issues.push('Use a more specific label for '+label+'.');
            if(item.type==='gallery'&&(item.options||[]).some(option=>!option.trim()||['option','image'].includes(option.toLowerCase()))) issues.push('Use descriptive choice labels in '+label+' so images are understandable without seeing them.');
        });
        if(issues.length) {results.append(node('h3','Accessibility suggestions'));const list=node('ul');[...new Set(issues)].forEach(issue=>list.append(node('li',issue)));results.append(list);}
        else results.append(node('p','No issues found in these label, image-description and width checks. Review the phone preview and try navigating the form with the keyboard.'));
    });
    const tabs = document.getElementById('builder-section-tabs');
    const sections = [...form.children].filter(element => element.tagName === 'FIELDSET');
    const sectionNames = ['Details', 'Blocks', 'Schedule', 'Receipts', 'Booking tools'];
    const tabButtons = [];
    const showSection = index => {
        sections.forEach((section, i) => { section.hidden = i !== index; });
        tabButtons.forEach((tab, i) => { tab.setAttribute('aria-pressed', String(i === index)); });
        document.getElementById('builder-current-section').textContent = sectionNames[index];
    };
    if (visual) {
        tabs.hidden = false; document.getElementById('builder-toolbar').hidden = false;
        sections.forEach((section, index) => {
            section.id = `builder-section-${index}`;
            const tab = button(sectionNames[index], () => showSection(index));
            tab.setAttribute('aria-controls', section.id); tabButtons.push(tab); tabs.append(tab);
        });
        showSection(items.length ? 1 : 0);
        form.addEventListener('invalid', event => {
            const index = sections.findIndex(section => section.contains(event.target));
            if (index >= 0) showSection(index);
        }, true);
        preview.addEventListener('click',event=>{
            const block=event.target.closest('[data-preview-index]');
            if (block) {selectBlock(items[Number(block.dataset.previewIndex)],false);showSection(1);}
        });
    }
    const templateStatus = document.getElementById('builder-template-status');
    for (const key of ['packages','extras']) {
        const source=form.elements.namedItem(key);
        const rows=source.value.split('\n').filter(line=>line.trim()).map(line=>{
            const [name,price,hours,description,image]=line.split('|').map(value=>value.trim());
            return {name,price,hours,description:description || '',image:image || ''};
        });
        const editor=node('div',undefined,'builder-catalog-editor');
        const list=node('div');
        const sync=()=>{source.value=rows.map(row=>[row.name,row.price,row.hours,row.description,row.image].join(' | ')).join('\n');changed();};
        const render=()=>{
            list.replaceChildren();
            rows.forEach((row,index)=>{
                const card=node('div',undefined,'builder-catalog-card');
                card.append(node('h3',`${key==='packages'?'Package':'Extra'} ${index+1}`));
                const inputs=node('div',undefined,'builder-dates');
                for (const [property,title,type] of [['name','Name','text'],['price','Price (£)','number'],...(key==='packages'?[['hours','Hours per event','number']]:[]),['description','Description','text']]) {
                    const label=node('label',title),control=node('input');control.type=type;control.value=row[property] || '';control.required=property!=='description';
                    if (type==='number') {control.min=property==='hours'?'0.01':'0';control.max=property==='hours'?'24':'100000';control.step='0.01';}
                    else control.maxLength=property==='name'?100:500;
                    control.addEventListener('input',()=>{row[property]=control.value;control.setCustomValidity(control.value.includes('|')?'Please use a different character instead of |.':'');sync();});
                    label.append(control);inputs.append(label);
                }
                card.append(inputs);
                card.append(imageSetting('Card image (optional)',row.image,value=>{row.image=value;sync();}));
                card.append(button('Remove '+(key==='packages'?'package':'extra'),()=>{rows.splice(index,1);sync();render();}));list.append(card);
            });
            add.disabled=rows.length>=12;
        };
        const add=button('Add '+(key==='packages'?'package':'extra'),()=>{
            if(rows.length>=12)return;
            rows.push({name:'',price:'0',hours:key==='packages'?'2':'0',description:'',image:''});sync();render();list.lastElementChild?.querySelector('input').focus();
        });
        editor.append(list,add);source.parentElement.after(editor);source.hidden=true;
        const help=source.parentElement.querySelector(':scope > small');
        if(help)help.textContent=key==='packages'?'Fixed price per event. Choose a duration that meets your minimum booking hours. Packages require Client pays and no pitch fee.':'Extras are added once to the request. Each card can have its own image.';
        render();
        restoreHooks.push(()=>{
            rows.splice(0,rows.length,...source.value.split('\n').filter(line=>line.trim()).map(line=>{
                const [name,price,hours,description,image]=line.split('|').map(value=>value.trim());return {name,price,hours,description:description || '',image:image || ''};
            }));render();
        });
    }
    const library = document.getElementById('builder-block-library');
    let savedGroups = [];
    const groupRequest = async (path, body) => {
        const response = await fetch(path, body ? {method:'POST', body} : {});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not update the reusable block library.');
        return data;
    };
    const loadLibrary = async () => {
        try {
            savedGroups = (await groupRequest('/admin/form-blocks')).blocks;
            library.replaceChildren(new Option('Choose a saved group', ''));
            savedGroups.forEach(group => library.append(new Option(group.title, String(group.id))));
            templateStatus.textContent = `${savedGroups.length} saved groups available.`;
        } catch(error) { templateStatus.textContent = error.message; }
    };
    const insertGroup = blocks => {
        if (items.length + blocks.length > maxBlocks) { templateStatus.textContent = 'This group would exceed thirty blocks.'; return; }
        const copies = JSON.parse(JSON.stringify(blocks)), names = new Map();
        const occupied = new Set(items.map(item => item.label));
        copies.forEach(item => {
            const original = item.label; let label = original, count = 2;
            while (occupied.has(label)) label = `${original.slice(0,130)} (${count++})`;
            occupied.add(label); names.set(original, label); item.label = label;
        });
        const firstRow = Math.max(0,...items.map(item => item.layout.row))+1;
        const base = Math.min(...copies.map(item => item.layout?.row || 1));
        copies.forEach(item => {
            item.layout = {...(item.layout || {column:1,width:12}), row:firstRow+(item.layout?.row || 1)-base};
            for (const key of ['show_if','required_if']) {
                const rules = features.rules(item[key]).filter(rule => names.has(rule.field));
                if (rules.length) item[key] = {mode:item[key]?.mode || 'all',rules:rules.map(rule => ({...rule,field:names.get(rule.field)}))};
                else delete item[key];
            }
            if (item.calculation) item.calculation.sources = item.calculation.sources.filter(label => names.has(label)).map(label => names.get(label));
        });
        if (copies.some(item => item.layout.row > 60)) {templateStatus.textContent = 'Free some grid rows before inserting this group.';return;}
        items.push(...copies);renderQuestions(items.length-copies.length);changed();showSection(1);
        templateStatus.textContent = 'Inserted. Review the wording and save your draft.';
    };
    const reusablePresets = {
        venue:[{label:'Venue requirements',type:'heading',content:'Please confirm the following before the event.'},{label:'Sheltered painting area available',type:'checkbox',required:true},{label:'Table and two chairs available',type:'checkbox',required:true},{label:'Suitable lighting and water access',type:'checkbox',required:true},{label:'Venue access and setup notes',type:'textarea',required:false}],
        group:[{label:'Group participants',type:'repeat',required:true,max_items:20,children:[{label:'Full name',type:'text',required:true},{label:'Age',type:'number',required:false,min:'0',max:'120'},{label:'Requirements or preferences',type:'textarea',required:false}]}],
        photos:[{label:'Reference photos',type:'file',required:false,file_types:['images'],max_files:6},{label:'Photo captions',type:'textarea',required:false,help:'Match each caption to its uploaded filename.'}]
    };
    document.getElementById('builder-insert-section').addEventListener('click', () => {
        const blocks = reusablePresets[document.getElementById('builder-section-preset').value].map((block,index) => ({...block,required:!!block.required,layout:{row:index+1,column:1,width:12}}));
        insertGroup(blocks);
    });
    document.getElementById('builder-load-library').addEventListener('click', loadLibrary);
    document.getElementById('builder-insert-library').addEventListener('click', () => {
        const group = savedGroups.find(group => String(group.id) === library.value);
        if (group) insertGroup(group.fields); else templateStatus.textContent = 'Choose a saved group first.';
    });
    const saveGroup = async selected => {
        const blocks = selected ? (selectedBlock ? [selectedBlock] : []) : items;
        if (!blocks.length) {templateStatus.textContent = 'Select a block or add some blocks first.';return;}
        const body = new FormData();body.set('csrf_token',form.elements.csrf_token.value);body.set('title',document.getElementById('builder-template-title').value);body.set('fields_json',JSON.stringify(blocks));
        try {await groupRequest('/admin/form-blocks',body);await loadLibrary();templateStatus.textContent = 'Saved to your reusable library.';} catch(error) {templateStatus.textContent=error.message;}
    };
    document.getElementById('builder-save-block').addEventListener('click', () => saveGroup(true));
    document.getElementById('builder-save-group').addEventListener('click', () => saveGroup(false));
    document.getElementById('builder-delete-library').addEventListener('click', async () => {
        if (!library.value || !window.confirm('Delete this reusable group? Existing forms will keep their blocks.')) return;
        const body=new FormData();body.set('csrf_token',form.elements.csrf_token.value);
        try {await groupRequest('/admin/form-blocks/'+library.value+'/delete',body);await loadLibrary();} catch(error) {templateStatus.textContent=error.message;}
    });
    const undoButton=document.getElementById('builder-undo'),redoButton=document.getElementById('builder-redo');
    const autosaveStatus=document.getElementById('builder-autosave-status');
    function editSnapshot() {
        const values={};
        [...form.elements].filter(control=>control.name && !['csrf_token','id','fields_json'].includes(control.name)).forEach(control=>{
            values[control.name]=control.type==='checkbox'?control.checked:control.value;
        });
        return JSON.stringify({blocks:items,values,selected:items.indexOf(selectedBlock)});
    }
    function updateHistoryButtons() {
        undoButton.disabled=historyIndex===0 || form.dataset.locked==='yes';redoButton.disabled=historyIndex===history.length-1 || form.dataset.locked==='yes';
    }
    function rememberEdit() {
        const state=editSnapshot();
        if(state===history[historyIndex])return;
        history=history.slice(0,historyIndex+1);history.push(state);
        if(history.length>50)history.shift();historyIndex=history.length-1;updateHistoryButtons();
    }
    function restoreEdit(offset) {
        const next=historyIndex+offset;if(next<0 || next>=history.length || form.dataset.locked==='yes')return;
        restoring=true;historyIndex=next;
        const state=JSON.parse(history[next]);items=state.blocks;selectedBlock=items[state.selected] || null;
        [...form.elements].forEach(control=>{
            if(!Object.hasOwn(state.values,control.name))return;
            if(control.type==='checkbox')control.checked=state.values[control.name];else control.value=state.values[control.name];
        });
        restoreHooks.forEach(restore=>restore());renderQuestions();changed();restoring=false;updateHistoryButtons();
    }
    async function autosaveDraft() {
        if(!dirty || autosaving || pendingUploads || form.dataset.locked==='yes')return;
        serialize();
        const invalid=validationError() || !form.elements.title.value.trim() || (['giveaway','photo'].includes(kind.value)&&!form.elements.terms.value.trim()) || [...form.elements].some(control=>control.willValidate&&!control.validity.valid);
        if(invalid){autosaveStatus.textContent='Autosave waiting: complete the draft fields first.';return;}
        autosaving=true;autosaveStatus.textContent='Saving draft…';
        let autoSaved=false;
        const state=editSnapshot(),body=new FormData(form);body.set('action','autosave');body.set('revision',form.dataset.revision || '');
        try {
            const response=await fetch(form.action,{method:'POST',body});
            if(response.headers && !response.headers.get('Content-Type')?.includes('application/json'))throw new Error('Autosave unavailable. Keep this tab open and sign in again before saving.');
            const data=await response.json();if(!response.ok)throw new Error(data.error || 'Autosave unavailable. Use Save draft.');
            form.dataset.revision=data.revision;
            autoSaved=true;
            if(!form.elements.namedItem('id')){
                const identity=node('input');identity.type='hidden';identity.name='id';identity.value=data.id;form.prepend(identity);
                const fixedKind=node('input');fixedKind.type='hidden';fixedKind.name='kind';fixedKind.value=body.get('kind');kind.value=fixedKind.value;form.append(fixedKind);kind.disabled=true;
                const location=new URL(window.location.href);location.searchParams.set('edit',data.id);window.history.replaceState(null,'',location);
            }
            if(state===editSnapshot()){dirty=false;document.getElementById('builder-save-status').textContent='Draft saved';}
            autosaveStatus.textContent='Saved at '+new Date(data.saved_at).toLocaleTimeString('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UK time';
        } catch(error){autosaveStatus.textContent=error.message || 'Autosave unavailable. Use Save draft.';}
        finally {autosaving=false;if(manualSaveRequested){manualSaveRequested=false;if(autoSaved)form.requestSubmit();}else if(dirty && state!==editSnapshot()){clearTimeout(autosaveTimer);autosaveTimer=setTimeout(autosaveDraft,1800);}}
    }
    if(visual){history=[editSnapshot()];document.getElementById('builder-history-tools').hidden=false;updateHistoryButtons();}
    undoButton.addEventListener('click',()=>restoreEdit(-1));redoButton.addEventListener('click',()=>restoreEdit(1));
    form.addEventListener('keydown',event=>{
        if(!(event.ctrlKey||event.metaKey) || event.key.toLowerCase()!=='z' || ['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return;
        event.preventDefault();restoreEdit(event.shiftKey?1:-1);
    });
    document.getElementById('builder-publish-check').addEventListener('click',async()=>{
        const results=document.getElementById('builder-publish-results');results.replaceChildren();
        const errors=[],warnings=[];const invalid=validationError();if(invalid)errors.push(invalid);
        if(!form.elements.title.value.trim())errors.push('Add a form title.');
        if(['giveaway','photo'].includes(kind.value)&&!form.elements.terms.value.trim())errors.push('Add the rules or permissions.');
        [...form.elements].filter(control=>control.willValidate&&!control.validity.valid).forEach(control=>errors.push('Check '+(control.closest('label')?.textContent.trim() || 'the highlighted field')+'.'));
        const start=form.elements.starts_at.value,end=form.elements.ends_at.value;
        if(start&&end&&end<=start)errors.push('Closing time must follow opening time.');
        if(!form.elements.description.value.trim())warnings.push('Consider adding an introduction.');
        if(!dirty && form.elements.namedItem('id')){
            try {const response=await fetch('/admin/native-forms/'+form.elements.id.value+'/checklist');if(!response.ok)throw new Error();const data=await response.json();errors.push(...data.errors);warnings.push(...data.warnings);}
            catch {warnings.push('Saved-form checks are unavailable. Try again before publishing.');}
        }else warnings.push('Save this draft to run the server checks for uploaded images and all block settings.');
        results.append(node('h3',errors.length?'Before publishing':'Draft checklist'));
        const list=node('ul');[...new Set(errors)].forEach(text=>list.append(node('li','Fix: '+text)));[...new Set(warnings)].forEach(text=>list.append(node('li',text)));results.append(list);
        if(!errors.length)results.append(node('p','No blocking issues found in these checks. Review the phone preview before publishing.'));
    });
    if (new URLSearchParams(window.location.search).get('preview') === '1') document.querySelector('.builder-open-preview')?.click();
})();
