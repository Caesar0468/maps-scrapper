// Load cuisines and vibes from API
async function loadFilterOptions() {
    try {
        const [cuisineRes, vibeRes] = await Promise.all([
            fetch('/api/cuisines'),
            fetch('/api/vibes')
        ]);
        const cuisines = await cuisineRes.json();
        const vibes = await vibeRes.json();
        
        const cuisineSelect = document.getElementById('cuisine-filter');
        cuisineSelect.innerHTML = cuisines.cuisines.map(c => `<option value="${c}">${c}</option>`).join('');
        
        const vibeSelect = document.getElementById('vibe-filter');
        vibeSelect.innerHTML = vibes.vibes.map(v => `<option value="${v}">${v}</option>`).join('');
    } catch (e) {
        console.warn('Could not load dynamic filter options', e);
    }
}

// Get all filter values
function getFilters() {
    const cuisineSelect = document.getElementById('cuisine-filter');
    const selectedCuisines = Array.from(cuisineSelect.selectedOptions).map(opt => opt.value);
    const vibeSelect = document.getElementById('vibe-filter');
    const selectedVibes = Array.from(vibeSelect.selectedOptions).map(opt => opt.value);
    
    const filterObj = {
        q: document.getElementById('search-input').value.trim(),
        locality: document.getElementById('locality-filter').value,
        cuisine: selectedCuisines.join(','),
        open_now: document.getElementById('open-now-filter').checked,
        late_night: document.getElementById('late-night-filter').checked,
        pure_veg: document.getElementById('pure-veg-filter').checked,
        exclude_avoid_veg: document.getElementById('exclude-avoid-veg').checked,
        exclude_avoid_nonveg: document.getElementById('exclude-avoid-nonveg').checked,
        hype: document.getElementById('hype-filter').value,
        fake_risk: document.getElementById('fake-risk-filter').value,
        dietary: document.getElementById('dietary-filter').value,
        low_fake_risk: document.getElementById('low-fake-risk').checked,  // NEW
        vibe: selectedVibes.join(','),
        sort: document.getElementById('sort-select').value,
    };

    // Only add location if we have valid numbers
    if (window.userLat && window.userLon && window.selectedRadius) {
        filterObj.lat = window.userLat;
        filterObj.lon = window.userLon;
        filterObj.radius_km = window.selectedRadius;
    }
    return filterObj;
}

// Count active filters
function countActiveFilters(filters) {
    let count = 0;
    if (filters.q) count++;
    if (filters.locality) count++;
    if (filters.cuisine) count++;
    if (filters.open_now) count++;
    if (filters.late_night) count++;
    if (filters.pure_veg) count++;
    if (filters.exclude_avoid_veg) count++;
    if (filters.exclude_avoid_nonveg) count++;
    if (filters.hype) count++;
    if (filters.fake_risk) count++;
    if (filters.dietary) count++;
    if (filters.low_fake_risk) count++;  // NEW
    if (filters.vibe) count++;
    if (filters.lat && filters.radius_km) count++;
    return count;
}

// Expose functions globally
window.getFilters = getFilters;
window.countActiveFilters = countActiveFilters;
window.loadFilterOptions = loadFilterOptions;

// Load options on page load
document.addEventListener('DOMContentLoaded', loadFilterOptions);