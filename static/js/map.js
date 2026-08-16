let map;
let markersGroup;
let userMarker = null;
let pollInterval = null;
let fetchController = null;
let lastRestaurants = [];

const $ = id => document.getElementById(id);
const safe = (v) => {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };
    return String(v ?? '').replace(/[&<>"']/g, ch => map[ch]);
};

const VERDICT = {
  'Hidden Gem': 'gem',
  'Justified Hype': 'hype',
  'Reliable Classic': 'classic',
  'Overhyped': 'overhyped'
};

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initEventListeners();
  animateEntrance();
  fetchRestaurants();
});

function animateEntrance(){
  if(!window.anime) return;
  anime.animate('.sidebar-head,.search-panel,.filter-card,.location-card,.pipeline-card,.list-heading',{opacity:[0,1],x:[-18,0],duration:900,delay:anime.stagger(75),ease:'out(4)'});
}

function initMap(){
  map = L.map('map', {
    zoomControl:false,
    preferCanvas:true,
    zoomSnap:0.25,
    zoomDelta:0.5,
    wheelDebounceTime:30,
    wheelPxPerZoomLevel:100
  }).setView([17.4065, 78.4772], 12);

  L.control.zoom({position:'bottomright'}).addTo(map);

  const tiles = L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
    maxZoom:20,
    attribution:'&copy; Stadia Maps &copy; OpenMapTiles &copy; OpenStreetMap contributors',
    subdomains:'abcd'
  }).addTo(map);

  tiles.on('tileerror', () => {
    if(!map._fallbackTiles){
      map._fallbackTiles = true;
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom:20,
        attribution:'&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains:'abcd'
      }).addTo(map);
    }
  });

  markersGroup = L.markerClusterGroup({
    chunkedLoading:true,
    showCoverageOnHover:false,
    spiderfyOnMaxZoom:true,
    removeOutsideVisibleBounds:true,
    maxClusterRadius:52,
    iconCreateFunction(cluster){
      const count=cluster.getChildCount();
      const size=count>99?'xl':count>9?'lg':'md';
      return L.divIcon({className:'food-cluster-wrap',html:`<div class="food-cluster ${size}"><span>${count}</span><i></i></div>`,iconSize:null});
    }
  });
  map.addLayer(markersGroup);

  map.on('moveend',()=>{
    const c=map.getCenter();
    $('map-status-text').textContent=`${c.lat.toFixed(2)}°, ${c.lng.toFixed(2)}° · ${map.getZoom().toFixed(1)}×`;
  });

  map.on('zoomstart',()=>document.body.classList.add('is-map-moving'));
  map.on('zoomend moveend',()=>document.body.classList.remove('is-map-moving'));
}

function initEventListeners(){
  const triggerFetch=()=>{updateActiveFilterBadge();fetchRestaurants()};
  let debounceTimer;
  $('search-input').addEventListener('input',()=>{clearTimeout(debounceTimer);debounceTimer=setTimeout(triggerFetch,280)});
  ['locality-filter','sort-select','cuisine-filter','dietary-filter','fake-risk-filter','hype-filter','vibe-filter','open-now-filter','late-night-filter','pure-veg-filter','exclude-avoid-veg','exclude-avoid-nonveg','low-fake-risk']
    .forEach(id=>{const el=$(id);if(el){el.addEventListener('change',triggerFetch);el.addEventListener('input',triggerFetch)}});

  document.querySelectorAll('.quick-chip').forEach(btn=>btn.addEventListener('click',()=>{
    const already=btn.classList.contains('active');
    document.querySelectorAll('.quick-chip').forEach(x=>x.classList.remove('active'));
    if(already){
      $('open-now-filter').checked=false;$('pure-veg-filter').checked=false;$('hype-filter').value='';
    }else{
      btn.classList.add('active');
      const q=btn.dataset.quick;
      if(q==='open'){$('open-now-filter').checked=true;$('pure-veg-filter').checked=false;$('hype-filter').value=''}
      if(q==='veg'){$('pure-veg-filter').checked=true;$('open-now-filter').checked=false;$('hype-filter').value=''}
      if(q==='gem'){$('hype-filter').value='Hidden Gem';$('open-now-filter').checked=false;$('pure-veg-filter').checked=false}
    }
    triggerFetch(); pulse(btn);
  }));

  $('gps-btn').addEventListener('click',useLocation);
  document.querySelectorAll('.dist-chip').forEach(chip=>chip.addEventListener('click',()=>{
    document.querySelectorAll('.dist-chip').forEach(c=>c.classList.remove('active'));
    chip.classList.add('active');window.selectedRadius=+chip.dataset.km;triggerFetch();pulse(chip)
  }));

  $('reset-filters').addEventListener('click',()=>{resetFilters();pulse($('reset-filters'))});

  $('collapse-btn').addEventListener('click',()=>{
    $('sidebar').classList.add('collapsed');$('expand-btn').classList.remove('hidden');setTimeout(()=>map.invalidateSize(),450);
  });
  $('expand-btn').addEventListener('click',()=>{
    $('sidebar').classList.remove('collapsed');$('expand-btn').classList.add('hidden');setTimeout(()=>map.invalidateSize(),450);
  });

  $('pipeline-btn').addEventListener('click',runPipeline);
  document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('search-input').focus();pulse($('search-input'))}});

  document.querySelectorAll('.magnetic').forEach(el=>{
    if(!matchMedia('(pointer:fine)').matches)return;
    el.addEventListener('pointermove',e=>{const r=el.getBoundingClientRect();el.style.transform=`translate(${(e.clientX-r.left-r.width/2)*.08}px,${(e.clientY-r.top-r.height/2)*.08}px)`});
    el.addEventListener('pointerleave',()=>el.style.transform='');
  });
}

function pulse(el){
  if(!window.anime || !el) return;
  anime.animate(el,{scale:[1,1.045,1],duration:420,ease:'out(4)'});
}

function useLocation(){
  if(!navigator.geolocation){alert('Geolocation is not supported.');return}
  const b=$('gps-btn');b.disabled=true;b.innerHTML='Locating <span class="spinner-dot"></span>';
  navigator.geolocation.getCurrentPosition(pos=>{
    window.userLat=pos.coords.latitude;window.userLon=pos.coords.longitude;window.selectedRadius=window.selectedRadius||5;
    b.disabled=false;b.innerHTML='Location active <span>✓</span>';b.classList.add('location-live');$('distance-chips').classList.remove('hidden');
    if(userMarker) map.removeLayer(userMarker);
    userMarker=L.circleMarker([window.userLat,window.userLon],{radius:8,fillColor:'#7dffca',color:'#0b0f18',weight:4,fillOpacity:1}).addTo(map);
    userMarker.bindPopup('<div class="user-popup"><b>You are here</b><span>Distance mode enabled</span></div>').openPopup();
    map.flyTo([window.userLat,window.userLon],14,{duration:1.4,easeLinearity:.2});fetchRestaurants();
  },err=>{b.disabled=false;b.innerHTML='Use my location <span>→</span>';alert(`Location error: ${err.message}`)});
}

function resetFilters(){
  ['search-input','locality-filter'].forEach(id=>$(id).value='');$('sort-select').value='reviews';['cuisine-filter','vibe-filter'].forEach(id=>$(id).selectedIndex=-1);['dietary-filter','fake-risk-filter','hype-filter'].forEach(id=>$(id).value='');
  ['open-now-filter','late-night-filter','pure-veg-filter','exclude-avoid-veg','exclude-avoid-nonveg','low-fake-risk'].forEach(id=>$(id).checked=false);
  window.userLat=window.userLon=window.selectedRadius=null;if(userMarker){map.removeLayer(userMarker);userMarker=null}$('distance-chips').classList.add('hidden');$('gps-btn').classList.remove('location-live');$('gps-btn').innerHTML='Use my location <span>→</span>';document.querySelectorAll('.quick-chip').forEach(x=>x.classList.remove('active'));updateActiveFilterBadge();fetchRestaurants();
}

function updateActiveFilterBadge(){const n=countActiveFilters(getFilters()),b=$('active-filter-count');b.textContent=n;b.classList.toggle('hidden',!n)}

async function fetchRestaurants(){
  if(fetchController)fetchController.abort();fetchController=new AbortController();$('count-badge').textContent='Scanning the field…';document.body.classList.add('is-loading');
  try{const params=new URLSearchParams(getFilters());const res=await fetch(`/api/restaurants?${params}`,{signal:fetchController.signal});if(!res.ok)throw Error(`HTTP ${res.status}`);const data=await res.json();lastRestaurants=data.restaurants||[];updateUI(lastRestaurants)}
  catch(e){if(e.name!=='AbortError'){$('count-badge').textContent='Could not load';console.error(e)}}
  finally{document.body.classList.remove('is-loading')}
}

function makeMarker(r,i){
  const ai=r.ai_analysis||{};const verdict=VERDICT[ai.hype_verdict]||'classic';const score=ai.hype_score!=null?Math.round(Number(ai.hype_score)):'—';
  const icon=L.divIcon({className:'food-pin-wrap',html:`<div class="food-pin ${verdict}"><div class="pin-pulse"></div><div class="pin-core"><span>${score}</span></div><label>${safe(r.name)}</label></div>`,iconSize:[32,32],iconAnchor:[16,16],popupAnchor:[0,-12]});
  const marker=L.marker([r.latitude,r.longitude],{icon, riseOnHover:true});
  marker.bindPopup(`<div class="popup-card"><div class="popup-kicker">${safe(ai.hype_verdict||'RESTAURANT')}</div><div class="popup-title">${safe(r.name)}</div><div class="popup-meta"><b>${safe(r.rating||'N/A')} ★</b> · ${(r.review_count||0).toLocaleString()} reviews</div><div class="popup-meta">${safe(r.address||r.locality||'')}</div><div class="popup-actions"><a href="/restaurant/${encodeURIComponent(r.slug)}">Full intel ↗</a>${r.google_maps_url?`<a href="${safe(r.google_maps_url)}" target="_blank">Maps ↗</a>`:''}</div></div>`,{maxWidth:280});
  marker.on('click', () => {
    document.querySelectorAll('.restaurant-card').forEach(x => x.classList.remove('selected'));
    const card = document.querySelectorAll('.restaurant-card')[i];
    if (card) {
      card.classList.add('selected');
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });
  return marker;
}

function updateUI(restaurants){
  const list=$('restaurant-list'),empty=$('empty-state');$('count-badge').textContent=`${restaurants.length} ${restaurants.length===1?'place':'places'}`;list.innerHTML='';markersGroup.clearLayers();
  if(!restaurants.length){empty.classList.remove('hidden');return}empty.classList.add('hidden');
  const markers=[];
  restaurants.forEach((r,i)=>{
    const ai=r.ai_analysis||{},verdict=VERDICT[ai.hype_verdict]||'';const li=document.createElement('li');li.className='restaurant-card';li.dataset.slug=r.slug;
    li.innerHTML=`<div class="card-index">${String(i+1).padStart(2,'0')}</div><div class="r-top"><div><div class="r-name">${safe(r.name)}</div><div class="r-meta">${safe(r.locality||'Hyderabad')} · ${(r.review_count||0).toLocaleString()} reviews</div></div><span class="rating-pill">${safe(r.rating||'N/A')} ★</span></div><div class="tag-row">${ai.hype_verdict?`<span class="tag ${verdict}">${safe(ai.hype_verdict)}</span>`:''}${ai.is_pure_veg?'<span class="tag gem">PURE VEG</span>':''}${ai.calculated_spend_for_two?`<span class="tag">₹${safe(ai.calculated_spend_for_two)} / 2</span>`:''}${ai.fake_review_risk?`<span class="tag risk">${safe(ai.fake_review_risk)} RISK</span>`:''}</div><div class="r-bottom"><a class="r-link" href="/restaurant/${encodeURIComponent(r.slug)}">Open field note ↗</a>${r.google_maps_url?`<a class="maps-link" href="${safe(r.google_maps_url)}" target="_blank">Maps ↗</a>`:''}</div>`;
    li.addEventListener('click',e=>{if(e.target.closest('a'))return;document.querySelectorAll('.restaurant-card').forEach(x=>x.classList.remove('selected'));li.classList.add('selected');pulse(li);if(r.latitude&&r.longitude)map.flyTo([r.latitude,r.longitude],16,{duration:.9,easeLinearity:.2})});
    list.appendChild(li);
    if(r.latitude&&r.longitude)markers.push(makeMarker(r,i));
  });
  markersGroup.addLayers(markers);
  if(window.anime){anime.animate('.restaurant-card',{opacity:[0,1],x:[-18,0],delay:anime.stagger(38),duration:640,ease:'out(4)'});anime.animate('.food-pin',{scale:[0,1],opacity:[0,1],delay:anime.stagger(20),duration:700,ease:'out(4)'})}
}

async function runPipeline(){
  const b=$('pipeline-btn'),s=$('pipeline-status'),text=$('pipeline-progress-text'),bar=$('pipeline-progress-bar'),pct=$('pipeline-percent');b.disabled=true;b.classList.add('running');b.querySelector('span').textContent='Engine running';s.classList.remove('hidden');text.textContent='Initializing pipeline…';bar.style.width='0%';pct.textContent='0%';
  try{
    const res=await fetch('/api/pipeline/run?max_targets=5&skip_scrape=false',{method:'POST'});if(!res.ok)throw Error((await res.json()).message||'Failed to trigger');
    if(pollInterval)clearInterval(pollInterval);
    pollInterval=setInterval(async()=>{
      const r=await fetch('/api/pipeline/status');const state=await r.json();let stageText=state.stage||'running…',detail='';
      if(state.progress&&typeof state.progress==='object'){if(state.progress.message)detail=state.progress.message;else if(state.progress.current&&state.progress.total)detail=`${state.progress.current}/${state.progress.total}`}
      text.textContent=`${stageText}${detail?' · '+detail:''}`;let percent=0;if(state.progress&&state.progress.current&&state.progress.total)percent=Math.min(100,Math.round((state.progress.current/state.progress.total)*100));bar.style.width=`${percent}%`;pct.textContent=`${percent}%`;
      if(!state.running){clearInterval(pollInterval);pollInterval=null;b.disabled=false;b.classList.remove('running');b.querySelector('span').textContent='Run pipeline';bar.style.width='100%';pct.textContent='100%';text.textContent=`Completed · ${state.stage||'done'}`;fetchRestaurants();pulse(b);setTimeout(()=>{s.classList.add('hidden');bar.style.width='0%';pct.textContent='0%'},5000)}
    },1000);
  }catch(e){text.textContent=`Error · ${e.message}`;b.disabled=false;b.classList.remove('running');b.querySelector('span').textContent='Try again'}
}