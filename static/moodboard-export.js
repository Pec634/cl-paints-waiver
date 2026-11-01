(() => {
  const loadImage = url => new Promise((resolve, reject) => {
    const img = new Image();
    const timeout = setTimeout(() => { img.src = ''; reject(new Error('A design image took too long to load. Please try again.')); }, 20000);
    img.crossOrigin = 'anonymous';
    img.onload = () => { clearTimeout(timeout); resolve(img); };
    img.onerror = () => { clearTimeout(timeout); reject(new Error('A design image could not be loaded for download. Please try again or check the image in the library.')); };
    img.src = url;
  });
  const wrap = (ctx, value, width) => {
    const lines = [];
    let line = '';
    for (const character of value) {
      if (ctx.measureText(line + character).width > width && line) { lines.push(line); line = ''; }
      line += character;
    }
    if (line) lines.push(line);
    return lines;
  };
  async function render(data) {
    // Load every design before rendering: failed images never produce a partial board.
    const groups = [];
    for (const group of data.groups) {
      const images = [];
      for (let start = 0; start < group.images.length; start += 6) {
        images.push(...await Promise.all(group.images.slice(start, start + 6).map(async item => ({ ...item, image: await loadImage(item.url) }))));
      }
      groups.push({ ...group, images });
    }
    const width = 1600, margin = 64, gap = 24, columns = 4;
    const cardWidth = (width - 2 * margin - gap * (columns - 1)) / columns;
    const cardHeight = cardWidth + 70;
    const canvas = document.createElement('canvas');
    let ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Your browser could not create the image. Try another browser.');
    ctx.font = 'bold 42px Arial';
    const titleLines = wrap(ctx, data.event + ' Moodboard', width - 2 * margin);
    const headerHeight = 140 + titleLines.length * 54;
    const height = headerHeight + groups.reduce((sum, group) => sum + 100 + Math.max(1, Math.ceil(group.images.length / columns)) * (cardHeight + gap) + 40, 0) + 70;
    const scale = Math.min(1, 30000 / height, Math.sqrt(32000000 / (width * height)));
    canvas.width = Math.floor(width * scale);
    canvas.height = Math.floor(height * scale);
    ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#10213f'; ctx.font = 'bold 52px Arial';
    ctx.fillText('CL', margin, 78);
    ctx.fillStyle = '#cf1c69'; ctx.fillText('Paints', margin + 90, 78);
    ctx.fillStyle = '#10213f'; ctx.font = 'bold 42px Arial';
    titleLines.forEach((line, index) => ctx.fillText(line, margin, 140 + index * 54));
    let y = headerHeight;
    for (const group of groups) {
      ctx.fillStyle = '#fff0f6'; ctx.fillRect(margin, y, width - 2 * margin, 70);
      ctx.fillStyle = '#10213f'; ctx.font = 'bold 36px Arial';
      ctx.fillText(group.title, margin + 22, y + 48);
      ctx.textAlign = 'right'; ctx.fillText(`\u00a3${group.price}`, width - margin - 22, y + 48); ctx.textAlign = 'left';
      y += 100;
      group.images.forEach((item, index) => {
        const x = margin + (index % columns) * (cardWidth + gap);
        const top = y + Math.floor(index / columns) * (cardHeight + gap);
        ctx.strokeStyle = '#dce1eb'; ctx.lineWidth = 2;
        ctx.strokeRect(x, top, cardWidth, cardHeight);
        const box = cardWidth - 24;
        const fit = Math.min(box / item.image.naturalWidth, box / item.image.naturalHeight);
        const w = item.image.naturalWidth * fit, h = item.image.naturalHeight * fit;
        ctx.drawImage(item.image, x + (cardWidth - w) / 2, top + 12 + (box - h) / 2, w, h);
        ctx.fillStyle = '#10213f'; ctx.font = 'bold 30px Arial'; ctx.textAlign = 'center';
        ctx.fillText(item.label, x + cardWidth / 2, top + cardHeight - 22); ctx.textAlign = 'left';
      });
      if (!group.images.length) {
        ctx.font = '28px Arial'; ctx.fillStyle = '#59677d'; ctx.fillText('No designs selected', margin, y + 50);
      }
      y += Math.max(1, Math.ceil(group.images.length / columns)) * (cardHeight + gap) + 40;
    }
    ctx.fillStyle = '#59677d'; ctx.font = '24px Arial';
    ctx.fillText('Bringing colour to life, one face at a time!', margin, height - 35);
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The image could not be created. Please try again.')), 'image/png'));
  }
  document.querySelectorAll('[data-moodboard-download]').forEach(button => {
    button.addEventListener('click', async () => {
      const status = button.parentElement.querySelector('[data-moodboard-download-status]');
      button.disabled = true;
      status.textContent = 'Preparing the full moodboard image…';
      try {
        const response = await fetch(button.dataset.moodboardDownload, { headers: { Accept: 'application/json' } });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('The moodboard could not be loaded. Refresh the page and try again.');
        const data = await response.json();
        const blob = await render(data);
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `moodboard-event-${data.event_id}.png`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        status.textContent = 'Your complete moodboard image is ready.';
      } catch (error) {
        status.textContent = error.message || 'The download failed. Please try again.';
      } finally {
        button.disabled = false;
      }
    });
  });
})();
