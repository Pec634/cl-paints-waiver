(() => {
  const views = document.querySelectorAll('[data-report-view]');
  const tabs = document.querySelectorAll('[data-report-tab]');
  const validViews = ['overview', 'targets', 'details', 'locations'];
  function selectView(view) {
    if (!validViews.includes(view)) view = 'overview';
    views.forEach(panel => { panel.hidden = panel.dataset.reportView !== view; });
    document.getElementById('report-view-input').value = view;
    tabs.forEach(tab => {
      tab.classList.toggle('primary', tab.dataset.reportTab === view);
      tab.setAttribute('aria-pressed', String(tab.dataset.reportTab === view));
    });
    window.dispatchEvent(new Event('report-view-change'));
  }
  tabs.forEach(tab => tab.addEventListener('click', () => {
    const url = new URL(window.location.href);
    url.searchParams.set('view', tab.dataset.reportTab);
    history.replaceState(null, '', url);
    selectView(tab.dataset.reportTab);
  }));
  selectView(new URLSearchParams(location.search).get('view'));
  document.querySelectorAll('.report-suggest-target').forEach(button => {
    button.addEventListener('click', () => {
      const field = document.querySelector(`input[name="${button.dataset.targetInput}"]`);
      const value = Number(button.dataset.baseline) * 1.1;
      field.value = button.dataset.money === 'true' ? value.toFixed(2) : Math.ceil(value);
      field.dispatchEvent(new Event('input', {bubbles: true}));
    });
  });
  const data = JSON.parse(document.getElementById('reportChartData').textContent);
  const colours = ['#f52f83', '#10213f', '#18a566', '#6478d2', '#e7a33b', '#16a4af', '#9853aa'];
  const svgNS = 'http://www.w3.org/2000/svg';
  function svgElement(tag, attrs, text) {
    const element = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  document.querySelectorAll('[data-pie-chart]').forEach(container => {
    const rows = data[container.dataset.pieChart].filter(row => row.value > 0);
    const total = rows.reduce((sum, row) => sum + row.value, 0);
    if (!total) { container.textContent = 'No records in this period.'; return; }
    const layout = document.createElement('div'); layout.className = 'report-donut-layout';
    const chart = svgElement('svg', {viewBox: '0 0 200 200', role: 'img', 'aria-label': 'Distribution; exact values listed alongside'});
    let offset = 0;
    const circumference = 2 * Math.PI * 70;
    const legend = document.createElement('ul'); legend.className = 'report-chart-legend';
    rows.forEach((row, index) => {
      const fraction = row.value / total;
      chart.append(svgElement('circle', {cx: 100, cy: 100, r: 70, fill: 'none', stroke: colours[index % colours.length], 'stroke-width': 30,
        'stroke-dasharray': `${fraction * circumference} ${circumference}`, 'stroke-dashoffset': -offset * circumference, transform: 'rotate(-90 100 100)'}));
      offset += fraction;
      const item = document.createElement('li');
      const swatch = document.createElement('span'); swatch.style.backgroundColor = colours[index % colours.length]; swatch.className = 'report-chart-swatch';
      item.append(swatch, document.createTextNode(`${row.label}: ${row.value} (${(fraction * 100).toFixed(1)}%)`));
      legend.append(item);
    });
    chart.append(svgElement('text', {x: 100, y: 106, 'text-anchor': 'middle', 'font-size': 26, fill: '#10213f'}, total));
    layout.append(chart, legend); container.append(layout);
  });
  document.querySelectorAll('[data-line-chart]').forEach(container => {
    const rows = data[container.dataset.lineChart];
    if (!rows.length || !rows.some(row => row.value)) { container.textContent = 'No records in this period.'; return; }
    const width = 600, height = 230, max = Math.max(1, ...rows.map(row => row.value));
    const chart = svgElement('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Monthly booking requests; exact values available below'});
    [0, 0.5, 1].forEach(fraction => {
      const y = 185 - fraction * 150;
      chart.append(svgElement('line', {x1: 45, y1: y, x2: 565, y2: y, stroke: '#e1e6ef'}));
      chart.append(svgElement('text', {x: 35, y: y + 5, 'text-anchor': 'end', 'font-size': 13}, (max * fraction).toFixed(max < 2 ? 1 : 0)));
    });
    const points = rows.map((row, index) => [rows.length === 1 ? 305 : 45 + index / (rows.length - 1) * 520, 185 - row.value / max * 150]);
    chart.append(svgElement('polyline', {points: points.map(point => point.join(',')).join(' '), fill: 'none', stroke: '#f52f83', 'stroke-width': 3}));
    rows.forEach((row, index) => {
      const [x, y] = points[index];
      const point = svgElement('circle', {cx: x, cy: y, r: 4, fill: '#f52f83'});
      point.append(svgElement('title', {}, `${row.label}: ${row.value}`)); chart.append(point);
      if (index === 0 || index === rows.length - 1 || (rows.length <= 12 && index % Math.ceil(rows.length / 6) === 0)) {
        chart.append(svgElement('text', {x, y: 215, 'text-anchor': 'middle', 'font-size': 12}, row.label));
      }
    });
    container.append(chart);
  });
})();
