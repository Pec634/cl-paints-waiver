(() => {
    const period = document.getElementById('reportPeriod');
    document.querySelectorAll('.reports-filters input[type="date"]').forEach(input => {
        input.addEventListener('change', () => { period.value = 'custom'; });
    });
    const markers = JSON.parse(document.getElementById('reportMapData').textContent);
    const status = document.getElementById('reportMapStatus');
    if (!window.L) {
        status.textContent = 'The map could not load. Postcode totals remain available below.';
        return;
    }
    const map = L.map('reportMap', { scrollWheelZoom: false }).setView([54.2, -2.5], 5);
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 12,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    tiles.on('tileerror', () => { status.textContent = 'Some map tiles could not load. Postcode totals remain available.'; });
    const venue = document.querySelector('select[name="location"]').value === 'venue';
    const bounds = [];
    markers.forEach(area => {
        const value = venue ? area.bookings : area.clients;
        const point = [area.latitude, area.longitude];
        const popup = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = `${area.outcode}${area.town ? ' · ' + area.town : ''}`;
        popup.append(title, document.createElement('br'),
            document.createTextNode(`${area.clients} clients · ${area.bookings} requests · ${area.accepted} accepted`));
        L.circleMarker(point, { radius: Math.min(32, 7 + Math.sqrt(value) * 3),
            color: '#a51252', fillColor: '#f52f83', fillOpacity: 0.55, weight: 2
        }).addTo(map).bindPopup(popup);
        bounds.push(point);
    });
    if (bounds.length) {
        map.fitBounds(bounds, { padding: [35, 35], maxZoom: 10 });
        status.textContent = `${bounds.length} postcode districts mapped. Select a circle to view its totals.`;
    }
})();
