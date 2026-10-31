(() => {
  const colours = {black:'#20212a',white:'#f5f1e9',red:'#c92739',blue:'#2760b0',green:'#27845d',pink:'#ec71a7',purple:'#8652ae',gold:'#cda34e',silver:'#abb4c4','rose gold':'#c68d80',orange:'#ed8b32',yellow:'#efd04a'};
  function colour(value) {
    if (colours[value.toLowerCase()]) return colours[value.toLowerCase()];
    return CSS.supports('color', value) ? value : '#8e96a8';
  }
  function render(line) {
    let figure = line.querySelector('[data-headband-preview]');
    if (!figure) {
      figure = document.createElement('figure');
      figure.className = 'headband-preview';
      figure.dataset.headbandPreview = '';
      const canvas = document.createElement('canvas');
      canvas.width = 800;
      canvas.height = 500;
      canvas.setAttribute('role', 'img');
      const caption = document.createElement('figcaption');
      const title = document.createElement('strong');
      title.textContent = 'Live design preview';
      const description = document.createElement('p');
      description.dataset.previewDescription = '';
      const disclaimer = document.createElement('p');
      disclaimer.className = 'headband-preview-disclaimer';
      disclaimer.textContent = 'Illustrative preview only. Actual colours, shape details, letter spacing, sizing and glitter finish may vary. Custom colours and shapes are shown approximately.';
      caption.append(title, description, disclaimer);
      figure.append(canvas, caption);
      line.querySelector('.remove-line').before(figure);
    }
    const canvas = figure.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const wording = line.querySelector('[name=wording]').value.trim();
    const bandColour = line.querySelector('[name=colour]').value;
    const finish = line.querySelector('[name=letter_finish]').value;
    const glitterColour = line.querySelector('[name=glitter_colour]').value;
    const shape = line.querySelector('[name=word_shape]').value;
    const tokens = Array.from((wording || 'YOUR WORDS').toUpperCase()).slice(0, 30);
    const glitter = finish === 'Glitter';
    const ink = glitter ? colour(glitterColour || 'Gold') : '#252534';
    const description = `${wording || 'Your wording'} — ${bandColour} headband, ${glitter ? (glitterColour || 'choose a colour') + ' glitter' : 'plain'} letters${shape && wording.split(/\s+/).length > 1 ? ', ' + shape + ' between words' : ''}.`;
    canvas.setAttribute('aria-label', 'Illustrative headband preview: ' + description);
    figure.querySelector('[data-preview-description]').textContent = description;
    ctx.clearRect(0, 0, 800, 500);
    const background = ctx.createLinearGradient(0, 0, 800, 500);
    background.addColorStop(0, '#fff8fc');
    background.addColorStop(1, '#eef0fa');
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, 800, 500);
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.arc(400, 390, 177, Math.PI, Math.PI * 2);
    ctx.strokeStyle = '#b9b9c4';
    ctx.lineWidth = 15;
    ctx.stroke();
    ctx.strokeStyle = colour(bandColour);
    ctx.lineWidth = 11;
    ctx.stroke();
    const step = Math.min(.12, 1.7 / Math.max(tokens.length - 1, 1));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    tokens.forEach((token, index) => {
      const angle = (index - (tokens.length - 1) / 2) * step;
      ctx.save();
      ctx.translate(400 + Math.sin(angle) * 225, 390 - Math.cos(angle) * 225);
      ctx.rotate(angle);
      ctx.fillStyle = ink;
      if (token === ' ' && shape && wording) {
        ctx.beginPath();
        if (shape.toLowerCase() === 'heart') {
          ctx.moveTo(0, 12);
          ctx.bezierCurveTo(-30, -6, -8, -23, 0, -9);
          ctx.bezierCurveTo(8, -23, 30, -6, 0, 12);
        } else if (shape.toLowerCase() === 'star') {
          for (let point = 0; point < 10; point++) {
            const theta = point * Math.PI / 5 - Math.PI / 2;
            const radius = point % 2 ? 7 : 16;
            ctx.lineTo(Math.cos(theta) * radius, Math.sin(theta) * radius);
          }
          ctx.closePath();
        } else {
          ctx.font = 'bold 11px Arial';
          ctx.fillText(shape.slice(0, 10), 0, 0);
        }
        ctx.fill();
      } else if (token !== ' ') {
        ctx.font = '900 31px Georgia, serif';
        ctx.lineWidth = 5;
        ctx.strokeStyle = '#fff';
        ctx.strokeText(token, 0, 0);
        ctx.fillText(token, 0, 0);
        if (glitter) {
          // A static fleck texture avoids flashing while suggesting glitter.
          ctx.globalCompositeOperation = 'source-atop';
          ctx.fillStyle = '#fff9';
          for (let fleck = 0; fleck < 12; fleck++) {
            ctx.fillRect(((fleck * 7 + index * 3) % 19) - 9, ((fleck * 11) % 24) - 12, 1.5, 1.5);
          }
          ctx.globalCompositeOperation = 'source-over';
        }
      }
      ctx.restore();
    });
    ctx.fillStyle = '#69718a';
    ctx.font = '15px Arial';
    ctx.fillText('CL CREATES  ·  DESIGN PREVIEW', 400, 465);
  }
  window.renderHeadbandPreview = render;
})();
