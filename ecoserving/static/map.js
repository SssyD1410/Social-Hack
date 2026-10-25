/* EcoServing maps: Leaflet + OpenStreetMap tiles, driving routes from the public OSRM demo server.
 * If routing is unavailable, a straight dashed line is drawn instead. */
(function () {
  const DEFAULT_CENTER = [44.9778, -93.2650];   // Minneapolis, when nothing is known yet
  const COLORS = {me: '#2f6fd1', post: '#1f7f3a', target: '#ff6d1f', active: '#c4410c'};
  const routeCache = new Map();

  function baseMap(el) {
    // Minimal look: Esri "Light Gray Canvas" (pale grey, faint roads and water, no buildings or
    // transit), no Leaflet prefix, a short credit. Free for light use without a key; credit required.
    const map = L.map(el, {scrollWheelZoom: false, attributionControl: false});
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 16, minZoom: 9,
    }).addTo(map);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 16, minZoom: 9, opacity: 0.8,   // faint place names only
    }).addTo(map);
    L.control.attribution({prefix: false}).addAttribution(
      'Tiles &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, OpenStreetMap contributors'
    ).addTo(map);
    map.setView(DEFAULT_CENTER, 11);
    return map;
  }

  // Pin content: ME (a person icon), DOT (a plain dot), or a short label such as a number.
  const ME = 'me', DOT = 'dot';
  const ICONS = '/static/icons.svg';
  function pin(color, label) {
    const inner = label === ME ? `<svg class="icon"><use href="${ICONS}#user"></use></svg>`
                : label === DOT ? '<i class="pin-dot"></i>' : (label ?? '');
    return L.divIcon({
      className: 'es-pin',
      html: `<span style="background:${color}">${inner}</span>`,
      iconSize: [26, 26], iconAnchor: [13, 26], popupAnchor: [0, -24],
    });
  }

  function popup(p) {
    const div = document.createElement('div');
    const b = document.createElement(p.url ? 'a' : 'b');
    if (p.url) b.href = p.url;
    b.textContent = p.title;
    div.append(b);
    if (p.subtitle) { div.append(document.createElement('br'), p.subtitle); }
    if (p.km != null) { div.append(document.createElement('br'), `${p.km} km away`); }
    return div;
  }

  async function route(from, to) {
    const key = `${from.lat},${from.lng};${to.lat},${to.lng}`;
    if (routeCache.has(key)) return routeCache.get(key);
    const promise = (async () => {
      try {
        const url = `https://router.project-osrm.org/route/v1/driving/${from.lng},${from.lat};${to.lng},${to.lat}?overview=full&geometries=geojson`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        const r = data.routes && data.routes[0];
        if (!r) throw new Error('no route');
        return {line: r.geometry.coordinates.map(([lng, lat]) => [lat, lng]), km: r.distance / 1000, min: r.duration / 60, road: true};
      } catch (e) {
        return {line: [[from.lat, from.lng], [to.lat, to.lng]], road: false};
      }
    })();
    routeCache.set(key, promise);
    return promise;
  }

  function fit(map, latlngs) {
    if (latlngs.length === 1) map.setView(latlngs[0], 14);
    else if (latlngs.length > 1) map.fitBounds(L.latLngBounds(latlngs).pad(0.15));
  }

  /* Dashboard: your posts, the top N counterparts, and a route that moves to the next one every second. */
  function dashboard(el, data, captionEl) {
    const map = baseMap(el);
    const all = [];
    if (data.me) { L.marker([data.me.lat, data.me.lng], {icon: pin(COLORS.me, ME), zIndexOffset: 1000}).addTo(map).bindPopup(popup(data.me)); all.push([data.me.lat, data.me.lng]); }
    data.posts.forEach(p => { L.marker([p.lat, p.lng], {icon: pin(COLORS.post, DOT)}).addTo(map).bindPopup(popup(p)); all.push([p.lat, p.lng]); });
    const markers = data.targets.map((t, i) => {
      all.push([t.lat, t.lng]);
      return L.marker([t.lat, t.lng], {icon: pin(COLORS.target, i + 1)}).addTo(map).bindPopup(popup(t));
    });
    fit(map, all);

    if (!data.me || !data.targets.length) {
      if (captionEl && !data.me && data.targets.length) captionEl.textContent = 'Set your location on your profile to see planned routes.';
      return map;
    }

    let line = null, i = -1, paused = false;
    async function step() {
      if (paused) return;
      i = (i + 1) % data.targets.length;
      const t = data.targets[i];
      const r = await route(data.me, t);
      if (line) line.remove();
      line = L.polyline(r.line, {color: COLORS.active, weight: 4, opacity: .8, dashArray: r.road ? null : '6 8'}).addTo(map);
      markers.forEach((m, j) => m.setIcon(pin(j === i ? COLORS.active : COLORS.target, j + 1)));
      if (captionEl) {
        const dist = r.road ? `${r.km.toFixed(1)} km, about ${Math.max(1, Math.round(r.min))} min by car` : `${t.km} km straight-line`;
        captionEl.textContent = '';
        captionEl.append(`Route ${i + 1}/${data.targets.length}: `);
        const a = document.createElement('a'); a.href = t.url; a.textContent = t.title;
        captionEl.append(a, ` (${t.subtitle}) · ${dist}`);
      }
    }
    step();
    setInterval(step, 1000);
    el.addEventListener('mouseenter', () => { paused = true; });
    el.addEventListener('mouseleave', () => { paused = false; });
    return map;
  }

  /* A set of points (e.g. food requests list), with a route from you to the first one if `focus`. */
  function points(el, data) {
    const map = baseMap(el);
    const all = [];
    if (data.me) { L.marker([data.me.lat, data.me.lng], {icon: pin(COLORS.me, ME)}).addTo(map).bindPopup(popup(data.me)); all.push([data.me.lat, data.me.lng]); }
    data.points.forEach((p, i) => {
      L.marker([p.lat, p.lng], {icon: pin(data.focus ? COLORS.active : COLORS.target, data.points.length > 1 ? i + 1 : DOT)}).addTo(map).bindPopup(popup(p));
      all.push([p.lat, p.lng]);
    });
    fit(map, all);
    if (data.focus && data.me && data.points.length) {
      route(data.me, data.points[0]).then(r => {
        L.polyline(r.line, {color: COLORS.active, weight: 4, opacity: .8, dashArray: r.road ? null : '6 8'}).addTo(map);
        if (data.captionEl) data.captionEl.textContent = r.road
          ? `Planned route from you: ${r.km.toFixed(1)} km, about ${Math.max(1, Math.round(r.min))} min by car.`
          : 'Straight-line distance shown (route service unavailable).';
      });
    }
    return map;
  }

  /* Location picker for forms: click the map, search an address, or use the device's location. */
  function picker(root) {
    const latIn = root.querySelector('input[name=lat]');
    const lngIn = root.querySelector('input[name=lng]');
    const status = root.querySelector('.picker-status');
    const map = baseMap(root.querySelector('.map'));
    let marker = null;

    function set(lat, lng, zoom) {
      latIn.value = lat.toFixed(6); lngIn.value = lng.toFixed(6);
      if (marker) marker.setLatLng([lat, lng]);
      else marker = L.marker([lat, lng], {icon: pin(COLORS.post, DOT), draggable: true}).addTo(map)
        .on('dragend', e => { const p = e.target.getLatLng(); set(p.lat, p.lng); });
      if (zoom) map.setView([lat, lng], zoom);
      status.textContent = 'Location set. Drag the pin or click the map to adjust.';
    }
    if (latIn.value && lngIn.value) set(+latIn.value, +lngIn.value, 15);
    map.on('click', e => set(e.latlng.lat, e.latlng.lng));

    root.querySelector('.picker-search')?.addEventListener('click', async () => {
      const form = root.closest('form');
      const q = [form.querySelector('[name=location], [name=address]')?.value, form.querySelector('[name=city]')?.value]
        .filter(Boolean).join(', ');
      if (!q) { status.textContent = 'Type an address first.'; return; }
      status.textContent = 'Searching…';
      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
        const hits = await res.json();
        if (hits.length) set(+hits[0].lat, +hits[0].lon, 16);
        else status.textContent = 'Address not found. Click the map instead.';
      } catch (e) { status.textContent = 'Search unavailable. Click the map instead.'; }
    });
    root.querySelector('.picker-locate')?.addEventListener('click', () => {
      if (!navigator.geolocation) { status.textContent = 'Location not available on this device.'; return; }
      status.textContent = 'Finding you…';
      navigator.geolocation.getCurrentPosition(p => set(p.coords.latitude, p.coords.longitude, 16),
        () => { status.textContent = 'Could not get your location. Click the map instead.'; });
    });
    root.querySelector('.picker-clear')?.addEventListener('click', () => {
      latIn.value = lngIn.value = '';
      if (marker) { marker.remove(); marker = null; }
      status.textContent = 'No location set.';
    });
    return map;
  }

  window.ESMap = {dashboard, points, picker};
  document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('[data-location-picker]').forEach(picker));
})();
