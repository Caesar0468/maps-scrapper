let map;
let markersGroup;
let userMarker = null;

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    initEventListeners();
    fetchRestaurants();
});

function initMap() {
    map = L.map('map', { zoomControl: false }).setView([17.4065, 78.4772], 12);
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    markersGroup = L.markerClusterGroup({
        chunkedLoading: true,
        showCoverageOnHover: false
    });
    map.addLayer(markersGroup);
}

function initEventListeners() {
    const triggerFetch = () => {
        updateActiveFilterBadge();
        fetchRestaurants();
    };

    let debounceTimer;
    document.getElementById('search-input').addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(triggerFetch, 300);
    });

    // List of element IDs that trigger fetch on change/input
    [
        'locality-filter', 'sort-select', 'cuisine-filter', 'dietary-filter',
        'fake-risk-filter', 'hype-filter', 'vibe-filter', 'open-now-filter',
        'late-night-filter', 'pure-veg-filter', 'exclude-avoid-veg',
        'exclude-avoid-nonveg', 'low-fake-risk'  // NEW
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', triggerFetch);
            el.addEventListener('input', triggerFetch);
        }
    });

    // GPS
    const gpsBtn = document.getElementById('gps-btn');
    const distChipsContainer = document.getElementById('distance-chips');
    gpsBtn.addEventListener('click', () => {
        if (!navigator.geolocation) {
            alert('Geolocation is not supported.');
            return;
        }
        gpsBtn.textContent = '📍 Locating…';
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                window.userLat = pos.coords.latitude;
                window.userLon = pos.coords.longitude;
                window.selectedRadius = window.selectedRadius || 5;

                gpsBtn.textContent = '📍 Location Active';
                gpsBtn.classList.replace('bg-emerald-600', 'bg-emerald-800');
                distChipsContainer.classList.remove('hidden');

                if (userMarker) map.removeLayer(userMarker);
                userMarker = L.circleMarker([window.userLat, window.userLon], {
                    radius: 8,
                    fillColor: '#2563eb',
                    color: '#ffffff',
                    weight: 2,
                    fillOpacity: 0.9
                }).addTo(map).bindPopup('You are here').openPopup();

                map.setView([window.userLat, window.userLon], 13);
                triggerFetch();
            },
            (err) => {
                alert(`Geolocation error: ${err.message}`);
                gpsBtn.textContent = '📍 Use My Location';
            }
        );
    });

    // Distance chips
    document.querySelectorAll('.dist-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
            document.querySelectorAll('.dist-chip').forEach(c => c.classList.remove('bg-slate-800', 'text-white'));
            e.target.classList.add('bg-slate-800', 'text-white');
            window.selectedRadius = parseFloat(e.target.dataset.km);
            triggerFetch();
        });
    });

    // Reset filters
    document.getElementById('reset-filters').addEventListener('click', () => {
        document.getElementById('search-input').value = '';
        document.getElementById('locality-filter').value = '';
        document.getElementById('sort-select').value = 'reviews';
        document.getElementById('cuisine-filter').selectedIndex = -1;
        document.getElementById('dietary-filter').value = '';
        document.getElementById('fake-risk-filter').value = '';
        document.getElementById('hype-filter').value = '';
        document.getElementById('vibe-filter').selectedIndex = -1;

        ['open-now-filter', 'late-night-filter', 'pure-veg-filter',
         'exclude-avoid-veg', 'exclude-avoid-nonveg', 'low-fake-risk'].forEach(id => {
            document.getElementById(id).checked = false;
        });

        window.userLat = null;
        window.userLon = null;
        window.selectedRadius = null;
        if (userMarker) { map.removeLayer(userMarker); userMarker = null; }
        gpsBtn.textContent = '📍 Use My Location';
        gpsBtn.classList.replace('bg-emerald-800', 'bg-emerald-600');
        distChipsContainer.classList.add('hidden');

        triggerFetch();
    });

    // Sidebar collapse/expand
    const sidebar = document.getElementById('sidebar');
    const collapseBtn = document.getElementById('collapse-btn');
    const expandBtn = document.getElementById('expand-btn');

    collapseBtn.addEventListener('click', () => {
        sidebar.classList.add('-translate-x-full');
        sidebar.style.display = 'none';
        expandBtn.classList.remove('hidden');
    });

    expandBtn.addEventListener('click', () => {
        sidebar.style.display = 'flex';
        sidebar.classList.remove('-translate-x-full');
        expandBtn.classList.add('hidden');
    });

    // Pipeline trigger
    const pipelineBtn = document.getElementById('pipeline-btn');
    const pipelineStatus = document.getElementById('pipeline-status');

    pipelineBtn.addEventListener('click', async () => {
        pipelineBtn.disabled = true;
        pipelineBtn.textContent = 'Starting…';
        pipelineStatus.classList.remove('hidden');
        pipelineStatus.textContent = 'Initializing pipeline…';

        try {
            const res = await fetch('/api/pipeline/run?max_targets=5&skip_scrape=false', { method: 'POST' });
            if (!res.ok) throw new Error((await res.json()).message || 'Failed to trigger');

            const poller = setInterval(async () => {
                const sRes = await fetch('/api/pipeline/status');
                const state = await sRes.json();
                pipelineStatus.textContent = `Stage: ${state.stage || 'running…'}`;

                if (!state.running) {
                    clearInterval(poller);
                    pipelineBtn.disabled = false;
                    pipelineBtn.textContent = 'Run Pipeline';
                    pipelineStatus.textContent = `Completed: ${state.stage}`;
                    fetchRestaurants();
                    setTimeout(() => pipelineStatus.classList.add('hidden'), 4000);
                }
            }, 1500);
        } catch (e) {
            pipelineStatus.textContent = `Error: ${e.message}`;
            pipelineBtn.disabled = false;
            pipelineBtn.textContent = 'Run Pipeline';
        }
    });
}

function updateActiveFilterBadge() {
    const filters = getFilters();
    const count = countActiveFilters(filters);
    const badge = document.getElementById('active-filter-count');
    if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

async function fetchRestaurants() {
    const params = new URLSearchParams(getFilters());
    try {
        const res = await fetch(`/api/restaurants?${params.toString()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        updateUI(data.restaurants || []);
    } catch (e) {
        console.error('Failed to fetch restaurants:', e);
    }
}

function updateUI(restaurants) {
    const listEl = document.getElementById('restaurant-list');
    const emptyEl = document.getElementById('empty-state');
    const countBadge = document.getElementById('count-badge');

    countBadge.textContent = `${restaurants.length} place${restaurants.length === 1 ? '' : 's'} found`;
    listEl.innerHTML = '';
    markersGroup.clearLayers();

    if (restaurants.length === 0) {
        emptyEl.classList.remove('hidden');
        return;
    }
    emptyEl.classList.add('hidden');

    restaurants.forEach(r => {
        const ai = r.ai_analysis || {};
        
        // List card
        const li = document.createElement('li');
        li.className = 'p-3 bg-white border border-slate-200 rounded-xl hover:border-blue-400 hover:shadow transition cursor-pointer';
        li.innerHTML = `
            <div class="flex justify-between items-start">
                <h3 class="font-bold text-sm text-slate-800">${r.name}</h3>
                <span class="text-xs font-semibold px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">${r.rating || 'N/A'} ★</span>
            </div>
            <p class="text-xs text-slate-500 mt-0.5">${r.locality || 'Hyderabad'} · ${(r.review_count || 0).toLocaleString()} reviews</p>
            <div class="flex flex-wrap gap-1 mt-2">
                ${ai.hype_verdict ? `<span class="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-700 border border-amber-200 rounded">${ai.hype_verdict}</span>` : ''}
                ${ai.is_pure_veg ? `<span class="text-[10px] px-1.5 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded">Pure Veg</span>` : ''}
                ${ai.calculated_spend_for_two ? `<span class="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-700 rounded">₹${ai.calculated_spend_for_two} for 2</span>` : ''}
            </div>
            <div class="mt-2 flex justify-between items-center pt-2 border-t border-slate-100">
                <a href="/restaurant/${r.slug}" class="text-xs text-blue-600 font-medium hover:underline">View AI Intel →</a>
                ${r.google_maps_url ? `<a href="${r.google_maps_url}" target="_blank" class="text-xs text-slate-400 hover:text-slate-600">Maps ↗</a>` : ''}
            </div>
        `;

        li.addEventListener('click', (e) => {
            if (e.target.tagName !== 'A' && r.latitude && r.longitude) {
                map.setView([r.latitude, r.longitude], 16);
            }
        });

        listEl.appendChild(li);

        // Map marker
        if (r.latitude && r.longitude) {
            const marker = L.marker([r.latitude, r.longitude]);
            marker.bindPopup(`
                <div class="p-1">
                    <h4 class="font-bold text-sm">${r.name}</h4>
                    <p class="text-xs text-slate-600">${r.rating || 'N/A'} ★ (${(r.review_count || 0).toLocaleString()} reviews)</p>
                    <p class="text-xs text-slate-500 mt-1">${r.address || r.locality || ''}</p>
                    <a href="/restaurant/${r.slug}" class="inline-block mt-2 text-xs text-blue-600 font-semibold hover:underline">Full Analysis & Menu →</a>
                </div>
            `);
            markersGroup.addLayer(marker);
        }
    });
}