const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const apiEnabled = location.protocol === 'http:' || location.protocol === 'https:';
// Curated local photos (no repeats, no template feel): sport imagery + avatar shots.
const PHOTOS = {
  basketball: 'img/basketball.jpg', running: 'img/running.jpg', cycling: 'img/cycling.jpg',
  yoga: 'img/yoga.jpg', gym: 'img/gym.jpg', workout: 'img/workout.jpg',
  heroRun: 'img/hero-run.jpg', heroBasketball: 'img/hero-basketball.jpg',
  p1: 'img/p1.jpg', p2: 'img/p2.jpg', p3: 'img/p3.jpg', p4: 'img/p4.jpg', p5: 'img/p5.jpg', p6: 'img/p6.jpg', p7: 'img/p7.jpg', p8: 'img/p8.jpg', p9: 'img/p9.jpg', p10: 'img/p10.jpg', p11: 'img/p11.jpg', p12: 'img/p12.jpg',
};
const sportPhoto = (sport) => PHOTOS[String(sport || '').toLowerCase()] || PHOTOS.workout;
const AVATARS = {};
function syncAvatars() {
  if (me().avatar_url) AVATARS[me().id || 1] = me().avatar_url;
  if (pageData.profile?.avatar_url) AVATARS[pageData.profile.id || 1] = pageData.profile.avatar_url;
  // Real uploaded photos win over stock placeholders — collect them from every payload.
  const collect = (arr) => (arr || []).forEach(x => { const id = Number(x.sender_id || x.author_id || x.user_id || x.id); if (id && x.avatar_url) AVATARS[id] = x.avatar_url; });
  collect(pageData.feed); collect(pageData.reels); collect(pageData.messages); collect(pageData.users);
  collect(pageData.friends); collect(pageData.fitmatch); collect(pageData.recommendations); collect(pageData.notifications);
  (pageData.conversations || []).forEach(c => {
    if (c.kind !== 'direct' || !c.other_avatar_url) return;
    // Resolve the other participant's id from the thread's messages (they share the title).
    const other = (pageData.messages || []).find(m => !me().id || m.sender_id !== me().id) || (pageData.messages || []).find(m => m.name === c.title);
    if (other && other.avatar_url) AVATARS[Number(other.sender_id)] = other.avatar_url;
  });
}
const photoAvatar = (name, i, size = 36, url = '') => {
  // A real uploaded photo when we have one; otherwise a clean initial-based
  // avatar. Random stock photos are never used as someone's face.
  const custom = url || AVATARS[Number(i)];
  if (custom) return `<span class="pavatar" style="background-image:url('${custom}')"></span>`;
  const initials = String(name || '?').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase();
  const tones = ['mint', 'blue', 'purple', 'teal', 'orange', 'coral'];
  const tone = tones[Math.abs(Number(i) || 0) % tones.length];
  return `<span class="pavatar init-avatar ${tone}">${escapeHtml(initials)}</span>`;
};
const sportLabel = (sport) => (String(sport || '').toLowerCase().includes('run') ? 'Run' : String(sport || '').toLowerCase().includes('cycl') ? 'Cycling' : String(sport || '').toLowerCase().includes('yoga') ? 'Yoga' : String(sport || '').toLowerCase().includes('gym') ? 'Gym' : 'Basketball');
let sessionToken = localStorage.getItem('fitverse-session') || '';
const state = { page: 'home', xp: 0, streak: 0, activities: 0, friends: false, joined: false, challenge: 'pending', booking: false, liked: false, comments: 0, detailId: 0, onboardingActive: false };
// Restart the onboarding wizard after any full re-render (render() rewrites #app, which contains #modal).
function redrawOnboarding() { if (state.onboardingActive && typeof drawOnboardingStep === 'function') drawOnboardingStep(); }
function clearOnboarding() { state.onboardingActive = false; $('#modal').innerHTML = ''; }
// Back navigation: every programmatic/page navigation pushes onto navTrail so
// the ← button in the header returns you to the PREVIOUS screen, not Home.
const navTrail = ['home'];
function pushTrail(p) { if (p && navTrail[navTrail.length - 1] !== p) { navTrail.push(p); if (navTrail.length > 30) navTrail.shift(); } }
function goBack() {
  $('#modal').innerHTML = '';
  if (navTrail.length > 1) navTrail.pop();
  const p = navTrail[navTrail.length - 1] || 'home';
  state.page = p; render(); loadPageData(p); window.scrollTo(0, 0);
}
const pageData = { bookings: [], businesses: [], users: [], allUsers: [], challenges: [], communities: [], events: [], activities: [], feed: [], conversations: [], activeConversation: 1, messages: [], notifications: [], achievements: [], friends: [], reports: [], xpLedger: [], recommendations: [], counts: {}, stats: {}, coach: 'Ask about people, activities, challenges or events.', profile: {}, reels: [], dash: {}, buddy: [], fitmatch: [], exercises: [], workouts: [], nutrition: {}, water: {}, progressEntries: [], settings: {}, coachChat: [], review: {}, leaderboards: {}, mySettings: null };
let drawOnboardingStep = null; // set by runOnboarding; render() re-draws the wizard if a re-render wipes #modal
const apiHeaders = () => ({ 'Content-Type': 'application/json', ...(sessionToken ? { 'X-Session': sessionToken } : {}) });
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // A dead token must never log the user out silently: only a MANUAL logout clears the session.
    if (response.status === 401 && sessionToken) {
      try {
        const r2 = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: localStorage.getItem('fitverse-user') || '', password: localStorage.getItem('fitverse-pass') || '' }) });
        if (r2.ok) { const d2 = await r2.json(); sessionToken = d2.token; localStorage.setItem('fitverse-session', d2.token); return api(path, options); }
      } catch (_) {}
      // No saved credentials or re-login failed: fall back to the cookie session if the server still honors it.
      try { const me2 = await fetch('/api/bootstrap', { credentials: 'include' }); if (me2.ok) { const j2 = await me2.json(); if (j2?.user?.id) { const t2 = document.cookie.match(/fv_session=([^;]+)/); if (t2) { sessionToken = t2[1]; localStorage.setItem('fitverse-session', sessionToken); return api(path, options); } } } } catch (_) {}
    }
    const err = new Error(data.error || 'We could not complete that action.'); err.status = response.status; throw err;
  }
  return data;
}
const escapeHtml = (v) => String(v ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
// Parse Google Takeout Fit export .json files into per-day {day, steps, distance_km}.
async function parseTakeoutFiles(files) {
  const days = {};
  for (const f of files) {
    if (!/\.json$/i.test(f.name)) continue;
    try {
      const j = JSON.parse(await f.text());
      for (const b of (j.bucket || [])) {
        const day = new Date(Number(b.startTimeMillis)).toISOString().slice(0, 10);
        if (!days[day]) days[day] = { steps: 0, distance_km: 0 };
        for (const ds of (b.dataset || [])) {
          const id = ds.dataSourceId || '';
          for (const pt of (ds.point || [])) {
            const v = (pt.value || [])[0] || {};
            if (id.includes('step_count') && v.intVal != null) days[day].steps += v.intVal;
            if (id.includes('distance') && v.fpVal != null) days[day].distance_km += v.fpVal / 1000;
          }
        }
      }
    } catch (_) {}
  }
  return Object.entries(days).filter(([, v]) => v.steps || v.distance_km)
    .map(([day, v]) => ({ day, steps: Math.round(v.steps), distance_km: Math.round(v.distance_km * 100) / 100 }));
}
const avatar = (name, tone = 'coral') => `<div class="avatar ${tone}">${escapeHtml(String(name || '?').split(' ').map(x => x[0]).join('').slice(0, 2))}</div>`;
const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); };
// FITVERSE 6.0: parse a Takeout-shaped object (bucket → dataset → point) into days.
// Used by the in-app sample import; real file uploads go through parseTakeoutFiles.
async function importTakeoutSample(sampleJson) {
  const days = {};
  for (const b of (sampleJson.bucket || [])) {
    const day = new Date(Number(b.startTimeMillis)).toISOString().slice(0, 10);
    if (!days[day]) days[day] = { day, steps: 0, distance_km: 0 };
    for (const ds of (b.dataset || [])) {
      const id = ds.dataSourceId || '';
      for (const pt of (ds.point || [])) {
        const v = (pt.value || [])[0] || {};
        if (id.includes('step_count') && v.intVal != null) days[day].steps += v.intVal;
        if (id.includes('distance') && v.fpVal != null) days[day].distance_km += v.fpVal / 1000;
      }
    }
  }
  return { days: Object.values(days).filter(v => v.steps || v.distance_km).map(v => ({ ...v, steps: Math.round(v.steps), distance_km: Math.round(v.distance_km * 100) / 100 })) };
}
const inr = (n) => (n > 0 ? `₹${Number(n).toLocaleString('en-IN')}` : 'Free');
const dayShort = (iso) => { try { return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }); } catch { return iso; } };
// FITVERSE 5.0: parse Health Connect exports / Takeout Fit files into flexible records.
// Pure client-side: reads real user-provided files, never invents values. ZIP needs the
// server-side JSON path (paste or unzip first); .json/.csv parse directly here.
async function parseHealthExportFiles(files) {
  const recs = [];
  const pushMetric = (type, day, val) => { if (type && day && val > 0) recs.push({ type, day, value: val }); };
  const pushWorkout = (day, name, durMin, km, kcal) => { if (day && (durMin > 0 || km > 0 || kcal > 0)) recs.push({ type: 'workout', day, name: String(name || 'Workout').slice(0, 60), duration_min: durMin || 0, distance_km: km || 0, kcal: kcal || 0 }); };
  const fromAggregationWindow = (w, cb) => { try { cb(new Date(Number(w.startTimeMillis)).toISOString().slice(0, 10), new Date(Number(w.endTimeMillis)).toISOString().slice(0, 10)); } catch (_) {} };
  for (const f of files) {
    try {
      const text = await f.text();
      if (/\.csv$/i.test(f.name)) {
        const lines = text.split(/\r?\n/).filter(Boolean);
        if (!lines.length) continue;
        const head = lines[0].split(',').map(h => h.trim().toLowerCase());
        const col = (...names) => { for (const n of names) { const i = head.indexOf(n); if (i >= 0) return i; } return -1; };
        const iD = col('date', 'day', 'start_date'), iT = col('type', 'metric'), iV = col('value', 'steps', 'amount');
        for (const ln of lines.slice(1)) {
          const cells = ln.split(',');
          const day = (cells[iD] || '').trim().slice(0, 10);
          if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
          if (iT >= 0 && iV >= 0) pushMetric((cells[iT] || '').trim().toLowerCase(), day, parseFloat(cells[iV]));
          else if (iV >= 0 && head[iV] === 'steps') pushMetric('steps', day, parseFloat(cells[iV]));
        }
        continue;
      }
      if (!/\.json$/i.test(f.name)) continue;
      const j = JSON.parse(text);
      const bins = Array.isArray(j) ? j : (j.bucket || []);
      for (const b of bins) {   // Takeout Fit shape: bucket → dataset → point
        let day = '';
        fromAggregationWindow(b, (d0) => { day = d0; });
        for (const ds of (b.dataset || [])) {
          const id = ds.dataSourceId || '';
          for (const pt of (ds.point || [])) {
            const v = (pt.value || [])[0] || {};
            if (id.includes('step_count') && v.intVal != null) pushMetric('steps', day, v.intVal);
            if (id.includes('distance') && v.fpVal != null) pushMetric('distance', day, v.fpVal / 1000);
          }
        }
      }
      if (j.session) {          // Takeout Fit sessions (workouts)
        for (const s of j.session) {
          let day = '', min = 0;
          try { day = new Date(s.startTimeMillis).toISOString().slice(0, 10); min = Math.round((Number(s.endTimeMillis) - Number(s.startTimeMillis)) / 60000); } catch (_) {}
          pushWorkout(day, s.name || 'Workout', min, 0, 0);
        }
      }
      const flat = Array.isArray(j) ? j : null;
      const records = flat || (j.records || j.days || j.data || j.metrics || null);
      if (records && Array.isArray(records)) {   // flexible record list
        for (const r of records) {
          if (!r || typeof r !== 'object') continue;
          const day = String(r.day || r.date || '').slice(0, 10);
          if (r.type || r.metric) {
            const t = String(r.type || r.metric).toLowerCase();
            if (t === 'workout' || t === 'exercise' || t === 'activity') pushWorkout(day, r.name || r.sport, Number(r.duration_min) || 0, Number(r.distance_km) || 0, Number(r.kcal) || 0);
            else pushMetric(t, day, Number(r.value ?? r.amount) || 0);
          } else if (r.steps != null) pushMetric('steps', day, Number(r.steps));
          else if (r.sleep_min != null) pushMetric('sleep_min', day, Number(r.sleep_min));
          else if (r.weight_kg != null) pushMetric('weight_kg', day, Number(r.weight_kg));
          else if (r.resting_hr != null) pushMetric('resting_hr', day, Number(r.resting_hr));
          else if (r.hydration_ml != null) pushMetric('hydration_ml', day, Number(r.hydration_ml));
        }
      }
    } catch (_) {}
  }
  return recs.slice(0, 1000);
}
// Upload a file via the existing base64 /api/upload endpoint. Returns { path, media } or null.
async function uploadImageFile(file, forceVideo = false) {
  const isVid = forceVideo || (file.type || '').startsWith('video');
  const ext = (file.name.split('.').pop() || (isVid ? 'mp4' : 'jpg')).toLowerCase();
  const dataUrl = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  return api('/api/upload', { method: 'POST', body: JSON.stringify({ data: dataUrl, ext, kind: isVid ? 'video' : 'image' }) });
}
// Subtle notification sound — WebAudio, gated on user preference + interaction.
function notifSound() {
  try {
    if (localStorage.getItem('fvSound') !== '1') return;
    const Ctx = window.AudioContext || window.webkitAudioContext; if (!Ctx) return;
    const ctx = new Ctx();
    const o = ctx.createOscillator(); const g = ctx.createGain();
    o.type = 'sine'; o.frequency.setValueAtTime(880, ctx.currentTime);
    o.frequency.setValueAtTime(1320, ctx.currentTime + 0.09);
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.4);
    setTimeout(() => { try { ctx.close(); } catch (_) {} }, 600);
  } catch (_) {}
}
const timeShort = (iso) => { try { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); } catch { return iso; } };
const nav = [['home', '◈', 'Home'], ['intelligence', '🧬', 'Fitness DNA'], ['connectHealth', '🔌', 'Health Data'], ['discover', '⌕', 'Discover'], ['posts', '▶', 'Posts & Reels'], ['workout', '🏋', 'Workout'], ['nutrition', '🍽', 'Nutrition'], ['progress', '📈', 'Progress'], ['challenges', '◉', 'Challenges'], ['communities', '◌', 'Communities'], ['events', '◫', 'Events'], ['messages', '✉', 'Messages'], ['friends', '👥', 'Friends'], ['coach', '✦', 'AI Coach'], ['businesses', '▦', 'Businesses']];
const mobileNav = [['home', '⌂'], ['discover', '⌕'], ['workout', '🏋'], ['nutrition', '🍽'], ['profile', '●']];
const unread = () => pageData.notifications.filter(n => !n.is_read).length;
// ---- free live APIs: weather (open-meteo), air quality (open-meteo), quotes (zenquotes), wikipedia ----
let wx = null;
async function loadWeather() {
  try {
    const [w, a] = await Promise.all([
      fetch('https://api.open-meteo.com/v1/forecast?latitude=13.08&longitude=80.27&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m').then(r => r.json()),
      fetch('https://air-quality-api.open-meteo.com/v1/air-quality?latitude=13.08&longitude=80.27&current=us_aqi').then(r => r.json()),
    ]);
    const c = w.current || {};
    wx = { temp: Math.round(c.temperature_2m), feels: Math.round(c.apparent_temperature), humidity: c.relative_humidity_2m, wind: Math.round(c.wind_speed_10m), aqi: a.current?.us_aqi ?? null, code: c.weather_code };
    const chip = $('#wx-chip'); if (chip) chip.innerHTML = weatherChipHtml();
    const adv = $('#wx-advice'); if (adv) adv.innerHTML = workoutAdvice();
  } catch (_) { wx = null; }
}
function weatherChipHtml() {
  if (!wx) return 'Weather unavailable';
  const icons = { 0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️', 45: '🌫️', 48: '🌫️', 51: '🌦️', 61: '🌧️', 63: '🌧️', 65: '⛈️', 80: '🌦️', 95: '⛈️' };
  return `<b>${wx.temp}°C</b> ${icons[wx.code] || '🌡️'} · feels ${wx.feels}° · AQI ${wx.aqi ?? '—'}`;
}
function workoutAdvice() {
  if (!wx) return '';
  const hot = wx.feels >= 36, humid = wx.humidity >= 75, badAir = (wx.aqi || 0) > 100;
  if (badAir) return '🌬️ Air quality is poor — best to train indoors today.';
  if (hot && humid) return '🥵 Hot & humid — hydrate well and aim for early morning or evening sessions.';
  if (hot) return '☀️ Warm out — light colors, extra water, shade breaks.';
  if (humid) return '💧 Humid conditions — pace yourself and electrolytes help.';
  return '✅ Great conditions for training — make it count!';
}
let quote = null;
const FALLBACK_QUOTES = [
  '“The body achieves what the mind believes.” — Napoleon Hill',
  '“Take care of your body. It’s the only place you have to live.” — Jim Rohn',
  '“Motivation gets you going, habit keeps you growing.” — John C. Maxwell',
  '“The last three or four reps is what makes the muscle grow.” — Arnold Schwarzenegger',
  '“A one hour workout is 4% of your day. No excuses.” — Unknown',
];
async function loadQuote() {
  try { const r = await fetch('https://dummyjson.com/quotes/random'); const d = await r.json(); if (d?.quote) quote = `“${d.quote}” — ${d.author}`; } catch (_) { /* fall through */ }
  if (!quote) quote = FALLBACK_QUOTES[new Date().getDate() % FALLBACK_QUOTES.length];
  const el = $('#quote-bar'); if (el) el.textContent = quote;
}
async function sportSpotlight(sport) {
  try {
    const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(sport)}?redirect=true`);
    const d = await r.json();
    return d.extract ? d.extract.split('. ').slice(0, 2).join('. ') : null;
  } catch (_) { return null; }
}
const mapEmbed = (place) => `https://www.openstreetmap.org/export/embed.html?bbox=80.20%2C12.95%2C80.32%2C13.12&layer=mapnik&marker=13.05%2C80.25`;
const level = () => Math.max(1, Math.floor((state.xp || 0) / 500) + 1);
const levelName = () => ['Beginner', 'Rising Athlete', 'Athlete', 'Beast', 'Elite', 'Legend'][Math.min(5, level() - 1)];
const progress = () => Math.min(100, Math.round(((state.xp || 0) % 500) / 5));
const me = () => pageData.profile || {};

async function hydrate() {
  if (!apiEnabled) return;
  const safe = (p, fb) => api(p).then(d => d).catch(() => fb);
  const signedIn = !!sessionToken;
  const guestItems = (v) => Promise.resolve(v);
  pageData.aiStatus = await safe('/api/ai/status', null);   // which brain is answering: groq vs builtin
  const [boot, feed, notifs, convs, achievements, buddy, fitmatch, intel, fr] = await Promise.all([
    api('/api/bootstrap').catch(() => null), safe('/api/feed', { items: [] }),
    signedIn ? safe('/api/notifications', { items: [] }) : guestItems({ items: [] }),
    signedIn ? safe('/api/conversations', { items: [] }) : guestItems({ items: [] }),
    signedIn ? safe('/api/achievements', { items: [] }) : guestItems({ items: [] }),
    signedIn ? safe('/api/ai/buddy', { items: [] }) : guestItems({ items: [] }),
    signedIn ? safe('/api/fitmatch', { items: [] }) : guestItems({ items: [] }),
    signedIn ? safe('/api/intelligence', {}) : guestItems({}),
    signedIn ? safe('/api/friends', { items: [] }) : guestItems({ items: [] }),
  ]);
  pageData.intel = (intel && intel.dna) ? intel : pageData.intel;
  if (boot && boot.state) {
    applyServerState(boot.state);
    pageData.profile = boot.user || {};
    pageData.counts = boot.counts || {};
    pageData.leaderboard = boot.leaderboard || [];
  }
  pageData.feed = feed.items || [];
  pageData.notifications = notifs.items || [];
  pageData.conversations = convs.items || [];
  pageData.achievements = achievements.items || [];
  pageData.buddy = (buddy.items || []).map(x => ({ note: x.note }));
  pageData.fitmatch = fitmatch.items || [];
  pageData.friendsData = fr.items ? fr : pageData.friendsData;  // Messages "start a chat" strip
  // PERF: the daily brief loads in parallel instead of blocking every hydrate.
  if (signedIn) api('/api/ai/daily', { method: 'POST', body: '{}' }).then(d => { pageData.daily = d; if (state.page === 'home') render(); }).catch(() => {});
  else pageData.daily = null;
  syncAvatars();
  if (pageData.conversations.length && !pageData.conversations.some(c => c.id === pageData.activeConversation)) pageData.activeConversation = pageData.conversations[0].id;
  if (state.page === 'home' && sessionToken) loadDashboard();
}
async function loadDashboard() {
  // ME() NOW: first dashboard paint carries the real name/level — no generic
  // "Welcome" flash while the slower bootstrap request catches up.
  if (!me().name) {
    try { const b = await api('/api/bootstrap'); if (b.state) applyServerState(b.state); pageData.profile = b.user || pageData.profile; pageData.counts = b.counts || pageData.counts; } catch (_) {}
  }
  const [nut, wat, wk] = await Promise.all([
    api('/api/nutrition').then(d => d).catch(() => null),
    api('/api/water').then(d => d).catch(() => null),
    api('/api/ai/review').then(d => d).catch(() => null),
  ]);
  pageData.dash = {
    kcal: nut ? { eaten: nut.totals.kcal, target: nut.targets.kcal_target, protein: nut.totals.protein, proteinTarget: nut.targets.protein_target } : null,
    water: wat || null,
    week: wk ? { sessions: wk.item.workouts, kcal: wk.item.calories_burned, goal: 4 } : null,
    today_line: wk && wk.item.workouts ? `You've trained ${wk.item.workouts}× this week — ${wk.item.workouts >= 4 ? 'goal crushed. ' : 'keep it rolling. '}${wk.item.new_prs ? wk.item.new_prs + ' new PR' + (wk.item.new_prs > 1 ? 's' : '') + '!' : ''}` : 'Here’s your day at a glance.',
  };
  if (state.page === 'home') render();
  startDashLive();
}
// FITVERSE 6.2: page-level loading state. Every panel sets pageData.__loading
// while its data is in flight; pages render a consistent "syncing" strip so
// the user always knows WHY a section is empty instead of seeing a glitch.
function loadingStrip(label) {
  return `<div class="fv-loading"><span class="spin">✦</span> ${escapeHtml(label || 'Loading')}…</div>`;
}
function bootBadge() {
  // Top-right badge on the app shell: shows while the profile/identity loads.
  return `<div class="boot-badge" id="boot-badge"><span class="spin">✦</span> loading your profile…</div>`;
}
// FITVERSE 6.2: form guidance for EVERY exercise/yoga pose — a YouTube search
// deep-link (works for any movement, incl. AI-created ones) plus the exercise
// photo tile. No invented URLs: the query is the exercise name itself.
function ytSearch(name) {
  return 'https://www.youtube.com/results?search_query=' + encodeURIComponent(String(name || '').replace(/[()]/g, '').trim() + ' proper form');
}
function formGuide(name, small) {
  return `<a class="fg-link" href="${ytSearch(name)}" target="_blank" rel="noopener" title="Learn proper form for ${escapeHtml(String(name))}">▶ ${small ? 'form' : 'Watch proper form'}</a>`;
}
function exerciseImage(name) {
  const n = String(name || '').toLowerCase();
  const key = /yoga|pose|flow|stretch|dog|warrior|bridge|plank/i.test(n) ? 'yoga'
    : /run|walk|jog|sprint|treadmill|cardio/i.test(n) ? 'running'
    : /cycl|bike|spin/i.test(n) ? 'cycling'
    : /curl|press|deadlift|squat|row|bench|lunge/i.test(n) ? 'gym'
    : 'workout';
  return PHOTOS[key];
}
// Home nutrition cards flash a LIVE tag + glow for 6s after any food/water log.
function pulseHome() {
  if (state.page !== 'home') return;
  pageData.__livePulse = true; render();
  clearTimeout(window.__pulseT);
  window.__pulseT = setTimeout(() => { if (pageData.__livePulse) { pageData.__livePulse = false; if (state.page === 'home') render(); } }, 6000);
}
// Nutrition/water totals refresh every 15s on home, plus right after any log action.
function startDashLive() {
  if (window.__dashLive) return; window.__dashLive = true;
  setInterval(async () => {
    if (document.hidden || state.page !== 'home' || !sessionToken) return;
    const [nut, wat] = await Promise.all([api('/api/nutrition').catch(() => null), api('/api/water').catch(() => null)]);
    if (!me().name && sessionToken) { try { const b = await api('/api/bootstrap'); if (b.state) applyServerState(b.state); pageData.profile = b.user || pageData.profile; } catch (_) {} }
    if (!nut && !wat) return;
    pageData.nutrition = nut || pageData.nutrition; pageData.water = wat || pageData.water;
    pageData.dash.kcal = nut ? { eaten: nut.totals.kcal, target: nut.targets.kcal_target, protein: nut.totals.protein, proteinTarget: nut.targets.protein_target } : pageData.dash.kcal;
    pageData.dash.water = wat || pageData.dash.water;
    render();
  }, 15000);
  // Cross-panel live sync: any page announces fresh nutrition/water/workout data.
  window.addEventListener('fv:data-updated', (e) => {
    const d = e.detail || {};
    if (d.nutrition) { pageData.nutrition = d.nutrition; pageData.dash.kcal = { eaten: d.nutrition.totals.kcal, target: d.nutrition.targets.kcal_target, protein: d.nutrition.totals.protein, proteinTarget: d.nutrition.targets.protein_target }; }
    if (d.water) { pageData.water = d.water; pageData.dash.water = d.water; }
    if (d.week) pageData.dash.week = d.week;
    if (state.page === 'home') { pulseHome(); } else { render(); }
  });
}
function applyServerState(s) {
  Object.assign(state, {
    xp: s.xp || 0, streak: s.streak || 0, activities: s.activities || 0,
    friends: !!s.is_friend_with_rahul, joined: !!s.joined_activity,
    challenge: s.challenge_status || 'pending', booking: !!s.booked_event,
    liked: !!s.liked_featured_post, comments: s.comments ?? 0,
  });
}
async function loadPageData(page) {
  // FITVERSE 6.2: visible "syncing" state for the whole data flight.
  pageData.__loading = true; render();
  const finish = () => { pageData.__loading = false; render(); };
  if (!apiEnabled) return;
  const tasks = [];
  const add = (p, fn) => tasks.push(fn.then(items => { pageData[p] = items; }).catch(() => {}));
  if (page === 'discover') {
    // PERF: one fetch feeds both lists (was two identical /api/users calls).
    const usersP = api('/api/users').then(d => d.items || []).catch(() => []);
    add('users', usersP);
    add('allUsers', usersP);
    add('recommendations', api('/api/recommendations').then(d => d.items || []));
    add('activities', api('/api/activities').then(d => d.items || []));
    add('events', api('/api/events').then(d => d.items || []));
    add('communities', api('/api/communities').then(d => d.items || []));
    add('businesses', api('/api/businesses').then(d => d.items || []));
  }
  if (page === 'challenges') {
    // PERF: one fetch for all three challenge views (was three identical calls).
    const chP = api('/api/challenges').then(d => d).catch(() => ({}));
    add('challenges', chP.then(d => d.items || []));
    add('challengeFriends', chP.then(d => d.friends || []));
    add('challengeBoard', chP.then(d => d.leaderboard || []));
  }
  if (page === 'communities') add('communities', api('/api/communities').then(d => d.items || []));
  if (page === 'events') { add('events', api('/api/events').then(d => d.items || [])); if (sessionToken) add('bookings', api('/api/bookings').then(d => d.items || []).catch(() => [])); }
  if (page === 'messages') {
    add('conversations', api('/api/conversations').then(d => d.items || []));
    add('messages', api(`/api/conversations/${pageData.activeConversation}`).then(d => d.items || []));
  }
  if (page === 'profile' && sessionToken) { add('xpLedger', api('/api/xp').then(d => d.items || [])); add('achievements', api('/api/achievements').then(d => d.items || [])); add('friends', api('/api/friends').then(d => d.items || [])); add('mission', api('/api/missions').then(d => d.item || {})); }
  if (page === 'home') { if (sessionToken) { add('mission', api('/api/missions').then(d => d.item || {})); add('moments', api('/api/moments').then(d => d.items || [])); } add('friendsActivity', api('/api/friends/activity').then(d => d.items || [])); add('socialCtx', api('/api/social/context').then(d => d).catch(() => ({}))); }
  if (page === 'reels' || page === 'posts') { add('reels', api('/api/reels').then(d => d.items || [])); if (!pageData.feed.length) add('feed', api('/api/feed').then(d => d.items || [])); }
  // PERF: /api/businesses is fetched once, in the businesses block below (was twice).
  if (page === 'workout' && sessionToken) { add('workouts', api('/api/workouts').then(d => d.items || [])); add('prs', api('/api/workouts/prs').then(d => d.items || [])); if (!pageData.exercises.length) add('exercises', api('/api/exercises').then(d => d.items || []).catch(() => [])); }
  if (page === 'intelligence' && sessionToken) {
    add('intel', api('/api/intelligence').then(d => d));
    add('mission', api('/api/missions').then(d => d.item || {}));
    add('missionHistory', api('/api/missions').then(d => d.history || []));
    add('teams', api('/api/teams').then(d => d.items || []));
    add('trajectory', api('/api/intelligence/trajectory?scenario=' + (pageData.trajScenario || 'current')).then(d => d.item || {}));
  }
  if (page === 'nutrition' && sessionToken) { add('nutrition', api('/api/nutrition').then(d => d).catch(() => ({}))); add('water', api('/api/water').then(d => d).catch(() => ({}))); }
  if (page === 'progress' && sessionToken) { add('progressEntries', api('/api/progress').then(d => d.items || [])); add('review', api('/api/ai/review').then(d => d.item || {}).catch(() => ({}))); }
  if (page === 'friends') { if (sessionToken) add('fitmatch', api('/api/fitmatch').then(d => d.items || [])); add('friendsData', api('/api/friends').then(d => d).catch(() => ({}))); }
  if (page === 'library') add('exercises', api('/api/exercises').then(d => d.items || []));
  if (page === 'posts' && sessionToken && !(pageData.workouts || []).length) add('workouts', api('/api/workouts').then(d => d.items || []).catch(() => []));
  if (page === 'coach' && sessionToken) {
    // Conversation-aware AI chat: loads the selected thread + the saved-chat list.
    // coachConvId === 0 means "explicit blank new chat" — don't fall back to the newest.
    const blankNew = pageData.coachConvId === 0;
    add('coachChat', api('/api/ai/coach' + (pageData.coachConvId ? `?conversation_id=${Number(pageData.coachConvId)}` : '')).then(d => { pageData.aiConversations = d.conversations || []; if (!blankNew) pageData.coachConvId = d.conversationId; return blankNew ? [] : (d.items || []); }).catch(() => []));
  }
  // Joined crews power the Communities + Bookings panels (real data, no demo rows).
  add('myCommunities', api('/api/communities').then(d => (d.items || []).filter(c => c.joined)).catch(() => []));
  // AI training suggestion from imported health data (nutrition page strip).
  add('healthSuggest', api('/api/health/suggest', { method: 'POST', body: '{}' }).catch(() => null));
  if (page === 'connectHealth') {
    add('healthIntegrations', api('/api/health/integrations').then(d => d).catch(() => null));
    add('healthOverview', api('/api/health/overview').then(d => d).catch(() => null));
    add('healthCardio', api('/api/health/cardio').then(d => d).catch(() => null));
    add('healthRec', api('/api/health/recommendation').then(d => d).catch(() => null));
    add('healthInsights', api('/api/health/insights').then(d => d).catch(() => null));
  }
  if (page === 'businesses') {
    // PERF: single /api/businesses fetch (the page was fetched twice before).
    const bizP = api('/api/businesses').then(d => d.items || []);
    add('businesses', bizP);
    add('myBusinesses', api('/api/businesses/mine').then(d => d.items || []).catch(() => []));
  }
  if (page === 'businessChannel') {
    add('bizDetail', api(`/api/businesses/${Number(state.bizId) || 1}`).then(d => d.item || {}).catch(() => null));
  }
  if (page === 'communityDetail' && state.detailId) add('detailData', api(`/api/community?id=${state.detailId}`).then(d => d.item || {}));
  if (page === 'athleteProfile' && state.detailId) add('detailData', api(`/api/athletes/${state.detailId}`).then(d => d.item || {}));
  if (page === 'bookings') add('bookings', api('/api/bookings').then(d => d.items || []));
  if (page === 'business') { add('businesses', api('/api/businesses').then(d => d.items || [])); add('bookings', api('/api/bookings').then(d => d.items || [])); }
  if (page === 'admin') { add('stats', api('/api/stats').then(d => d.items || {})); add('reports', api('/api/reports').then(d => d.items || [])); }
  if (page === 'home') { add('activities', api('/api/activities').then(d => d.items || [])); loadWeather(); loadQuote(); }
  await Promise.all(tasks);
  finish();  // clears pageData.__loading + repaints with the fresh data
}
async function loadMessages() {
  try { pageData.messages = (await api(`/api/conversations/${pageData.activeConversation}`)).items || []; }
  catch (e) { toast(e.message); }
  render();
}

function shell(content) {
  const u = unread();
  const dmUnread = (pageData.conversations || []).reduce((t, c) => t + (Number(c.unread) || 0), 0);
  return `<div class="app-shell">
  ${!me().name && sessionToken ? bootBadge() : ''}
  <aside class="sidebar"><a class="brand" data-page="home"><i>F</i> FITVERSE</a><p class="eyebrow">PLAY TOGETHER</p><nav>${nav.map(([id, icon, label]) => `<button class="nav-item ${state.page === id ? 'active' : ''}" data-page="${id}"><span>${icon}</span>${label}${id === 'messages' && dmUnread ? `<b>${dmUnread}</b>` : ''}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="mini-profile">${me().name ? photoAvatar(me().name, 1) : '<div class="avatar skeleton" style="border-radius:50%"></div>'}<div>${me().name ? `<strong>${escapeHtml(me().name)}</strong><small>Level ${level()} · ${levelName()}</small>` : (sessionToken ? '<strong class="skeleton" style="display:block;height:12px;width:70%"></strong><small class="skeleton" style="display:block;height:9px;width:55%;margin-top:6px"></small>' : '<strong>Welcome</strong><small>Sign in to personalize</small>')}</div></div><button class="create-btn" data-action="create">＋ Create</button></div></aside>
  <main>${content}</main><nav class="mobile-nav" aria-label="Primary">${mobileNav.map(([p, i]) => `<button data-page="${p}" class="${state.page === p ? 'active' : ''}" aria-label="${p}"><span aria-hidden="true">${i}</span><small>${p}</small></button>`).join('')}<button class="mobile-more-btn" data-action="moreMenu" aria-label="All pages" style="align-self:center">⊞</button></nav><div id="toast" role="status" aria-live="polite"></div><div id="modal"></div></div>`;
}
function pageHeader(title, sub = 'Your fitness world, in motion.') {
  const u = unread();
  const topRight = sessionToken
    ? `<button class="icon-btn" data-action="notificationsOpen" title="Notification center">🔔${u ? `<em>${u}</em>` : ''}</button><button class="icon-btn" data-action="cmdk" title="Search (Ctrl+K)">⌕</button><button class="profile-chip" data-page="profile">${photoAvatar(me().name, me().id || 1)}<span>${escapeHtml((me().name || 'You').split(' ')[0])}</span><i>⌄</i></button><button class="outline auth-btn" data-action="logout" title="Log out">Logout</button>`
    : `<button class="outline auth-btn" data-action="account">Log in</button><button class="primary auth-btn" data-action="register">Sign up</button>`;
  const backBtn = navTrail.length > 1 ? '<button class="icon-btn back-btn" data-action="goBack" title="Back" aria-label="Go back">←</button>' : '';
  return `<header class="top"><div><span class="eyebrow">FITVERSE / ${state.page.toUpperCase()}</span><h1>${title}</h1><p>${sub}</p></div><div class="top-actions">${backBtn}${topRight}</div></header>`;
}
function home() {
  const s = pageData.dash || {};
  const notes = pageData.buddy || [];
  const post = pageData.feed[0];
  const topRec = (pageData.fitmatch || pageData.recommendations)[0] || pageData.recommendations[0];
  const intel = pageData.intel || {};
  const dna = intel.dna || {};
  const dsc = dna.scores || {};
  const debt = (intel.debt || {});
  const mission = pageData.mission || ({});
  const heroTitle = me().name ? `Good ${greeting()}, ${escapeHtml(me().name.split(' ')[0])} 👋` : 'Welcome to FITVERSE 👋';
  return shell(`${pageHeader(heroTitle, me().name ? (s.today_line || 'Here’s your day at a glance.') : 'Fitness is more fun together. Sign in to start your streak.')}
<section class="hero photo" style="background-image:linear-gradient(100deg, rgba(8,18,13,.96) 42%, rgba(8,18,13,.62) 100%), url('${PHOTOS.heroBasketball}')"><div><span class="pill lime">● WEEK ${weekNumber()}</span><h2>Fitness is better<br/>when it’s a <span>game.</span></h2><p id="wx-advice">${wx ? workoutAdvice() : 'Keep your streak alive. You’re one activity away from your weekly goal.'}</p><div id="wx-chip" class="wx-chip">${wx ? weatherChipHtml() : 'Loading live weather…'}</div><div class="hero-actions"><button class="primary" data-page="workout">Start today’s session <b>→</b></button><button class="text-btn" data-page="coach">Ask FITVERSE AI</button></div></div><div class="hero-orbit" id="hero3d-mount"><div class="orbit-hud" id="hero3d-hud">drag to rotate · tap for power</div><div class="orbit-core">${state.streak}<small>DAY STREAK</small></div><div class="float-card one">🔥<strong>${pageData.counts.friends || 0} friends</strong><small>in your circle</small></div><div class="float-card two">⚡<strong>Level ${level()}</strong><small>${levelName()}</small></div></div></section>
<section class="dash-grid">
  <article class="stat-card ${pageData.__livePulse ? 'live-pulse' : ''}"><span>🍽</span><div><small>CALORIES${pageData.__livePulse ? '<b class="live-tag">LIVE</b>' : ''}</small><strong>${s.kcal ? `${s.kcal.eaten.toLocaleString()} <em>/ ${s.kcal.target.toLocaleString()}</em>` : '—'}</strong></div><i>${s.kcal ? `${Math.round(s.kcal.eaten / Math.max(1, s.kcal.target) * 100)}%` : ''}</i><div class="bar slim"><i style="width:${s.kcal ? Math.min(100, s.kcal.eaten / Math.max(1, s.kcal.target) * 100) : 0}%"></i></div></article>
  <article class="stat-card ${pageData.__livePulse ? 'live-pulse' : ''}"><span>🥩</span><div><small>PROTEIN${pageData.__livePulse ? '<b class="live-tag">LIVE</b>' : ''}</small><strong>${s.kcal ? `${s.kcal.protein}<em>/${s.kcal.proteinTarget}g</em>` : '—'}</strong></div><i>${s.kcal ? Math.round(s.kcal.protein / Math.max(1, s.kcal.proteinTarget) * 100) + '%' : ''}</i><div class="bar slim"><i style="width:${s.kcal ? Math.min(100, s.kcal.protein / Math.max(1, s.kcal.proteinTarget) * 100) : 0}%"></i></div></article>
  <article class="stat-card"><span>💧</span><div><small>WATER</small><strong>${s.water ? `${(s.water.today_ml / 1000).toFixed(1)}<em>/${(s.water.target_ml / 1000).toFixed(1)}L</em>` : '—'}</strong></div><i>${s.water ? Math.round(s.water.today_ml / Math.max(1, s.water.target_ml) * 100) + '%' : ''}</i><div class="bar slim"><i style="width:${s.water ? Math.min(100, s.water.today_ml / Math.max(1, s.water.target_ml) * 100) : 0}%"></i></div></article>
  <article class="stat-card"><span>🏋</span><div><small>THIS WEEK</small><strong>${s.week && s.week.sessions != null ? `${s.week.sessions}<em> workouts</em>` : `${Math.min(4, state.activities)}<em>/4</em>`}</strong></div><i>${s.week && s.week.kcal ? `${s.week.kcal} kcal` : ''}</i></article>
</section>
${me().name && pageData.mySettings && !pageData.mySettings.onboarded ? `<section class="ob-reminder"><span>🧭</span><div><b>Finish your FITVERSE setup</b><p>Answer a few quick questions so AI, meals, workouts and friend matches actually fit you.</p></div><button class="primary small" data-action="runOnboarding">Finish setup</button><button class="outline small" data-action="dismissOnboarding">Dismiss</button></section>` : ''}
${notes.length ? `<section class="buddy-strip"><span class="pill lime">✦ FITVERSE AI</span>${notes.slice(0, 3).map(n => `<p>${n.note}</p>`).join('')}</section>` : ''}
<section class="eco-strip">
  <a class="eco-card dna" data-page="intelligence"><span class="eyebrow">🧬 FITNESS DNA</span><div class="eco-main"><div class="dna-ring" style="--v:${dsc.consistency || 0}"><b>${dsc.consistency ?? '—'}</b></div><div><h3>${escapeHtml(dna.personality || 'The Explorer')}</h3><p>Focus: ${escapeHtml(dna.focus || 'Log a session to unlock')}</p></div></div><span class="eco-more">Open DNA →</span></a>
  <a class="eco-card ${debt.debt ? 'debt' : 'clear'}" data-page="intelligence"><span class="eyebrow">⚡ FITNESS DEBT</span><div class="eco-main"><b class="eco-big">${debt.debt ?? 0}</b><div><h3>${debt.debt ? `${debt.debt} session${debt.debt > 1 ? 's' : ''} owed` : 'All caught up'}</h3><p>${debt.completed ?? 0}/${debt.target ?? 4} this week</p></div></div><span class="eco-more">Recover →</span></a>
  <a class="eco-card mission" data-page="intelligence"><span class="eyebrow">🎯 MISSION</span><div class="eco-main"><span class="mission-mini">${mission.icon || '🎯'}</span><div><h3>${escapeHtml(mission.title || 'Start your first mission')}</h3><p>${mission.progress != null ? `${mission.progress}/${mission.target} · ` : ''}+${mission.reward_xp || 0} XP</p></div></div><span class="eco-more">View →</span></a>
</section>
${momentsSection()}
${dailyCompanionCard()}
${friendsActivitySection()}
<section class="stat-grid"><div class="stat-card"><span>🔥</span><div><small>STREAK</small><strong>${state.streak} days</strong></div><i>↗ ${s.week ? (s.week.sessions >= 3 ? 'on fire' : 'building') : ''}</i></div><div class="stat-card"><span>⚡</span><div><small>YOUR XP</small><strong>${state.xp.toLocaleString()} <em>XP</em></strong></div><i>LEVEL ${level()}</i></div><div class="stat-card goal"><div><small>WEEKLY GOAL</small><strong>${s.week && s.week.sessions != null ? Math.min(s.week.sessions, s.week.goal || 4) : Math.min(4, state.activities)} / ${s.week ? s.week.goal || 4 : 4} workouts</strong></div><div class="bar"><i style="width:${Math.min(100, ((s.week ? s.week.sessions : state.activities) / (s.week ? s.week.goal || 4 : 4)) * 100)}%"></i></div><button data-action="complete">Complete activity +</button></div></section>
<section class="section-head"><div><span class="eyebrow">FROM YOUR CREW</span><h2>The FITVERSE feed</h2></div><button class="link" data-action="create">Share an update <b>→</b></button></section>
<div class="tabs" id="feed-tabs">${['For You', 'Following', 'Trending'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-ftab="${t.toLowerCase().replace(' ', '')}">${t}</button>`).join('')}</div>
<div id="feed-foryou">${pageData.feed.length ? pageData.feed.slice(0, 8).map(postCard).join('') : emptyState('📭', 'No posts yet', 'Share your first fitness update or follow some athletes to fill your feed.', 'create', 'Create a post')}</div>
<div id="feed-following" style="display:none">${emptyState('👥', 'Follow more athletes', 'Posts from people you follow appear here. Find your crew on Discover.', 'discover', 'Find people')}</div>
<div id="feed-trending" style="display:none">${pageData.feed.length ? [...pageData.feed].sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 6).map(postCard).join('') : emptyState('📈', 'Nothing trending yet', 'Be the spark — post your last workout.', 'create', 'Create a post')}</div>
<section class="home-split"><div><div class="section-head"><div><span class="eyebrow">FIT MATCH</span><h2>Your #1 training match</h2></div><button class="link" data-page="friends">See all matches <b>→</b></button></div><div class="match-card">${topRec ? `<div class="match-art"><span>${topRec.score}%</span><small>FIT MATCH</small></div><div class="match-copy">${photoAvatar(topRec.name, topRec.id)}<div><h3>${escapeHtml(topRec.name)} <i>✓</i></h3><p>${escapeHtml(`${topRec.activity} · ${topRec.fitnessLevel || topRec.fitness_level} · ${topRec.preferredTime || topRec.preferred_time}`)}</p><div class="tag-row">${(topRec.reasons || []).map(r => `<span>${escapeHtml(r)}</span>`).join('')}</div></div><button class="primary small" data-action="friend" data-id="${topRec.id}">${(state.friends || []).some(f => f.id === topRec.id) ? 'Friends ✓' : 'Add friend'}</button></div>` : `<div class="match-art"><span>🎯</span><small>FIT MATCH</small></div><div class="match-copy"><div class="avatar" style="background:var(--navy)">✨</div><div><h3>Find your training match</h3><p>We'll pair you with people who share your sport, level and schedule once you start training.</p></div><button class="primary small" data-page="discover">Browse people →</button></div>`}</div></div><div class="feed-mini"><div class="section-head"><div><span class="eyebrow">TRENDING NOW</span><h2>Popular with friends</h2></div></div>${post ? postCard(post) : '<article class="post"><p>No posts yet — be the first to share.</p></article>'}</div></section>
<section class="quote-bar" id="quote-bar">${quote || 'Small steps every day.'}</section>`);
}
function momentsSection() {
  const items = pageData.moments || [];
  if (!items.length) return '';
  return `<section class="moments-strip"><div class="section-head"><div><span class="eyebrow">🏆 FITVERSE MOMENTS</span><h2>Your recent wins</h2></div></div><div class="moments-row">${items.slice(0, 4).map((m, i) => `<article class="moment-card k${i % 4}"><span class="moment-icon">${m.icon}</span><div><small>${escapeHtml(m.card.headline)}</small><h3>${escapeHtml(m.card.main)}</h3><b>${escapeHtml(m.card.big)}</b></div><button class="moment-share" data-action="shareMoment" data-i="${i}" title="Share this moment" aria-label="Share moment">↗</button></article>`).join('')}</div></section>`;
}

function socialChip(type, id) {
  const ctx = pageData.socialCtx && pageData.socialCtx[type];
  const info = ctx && ctx[String(id)];
  if (!info || !info.n) return '';
  const label = { communities: 'members', activities: 'attending', challenges: 'competing', posts: 'commented' }[type];
  const who = (info.names || []).slice(0, 2).map(n => n.split(' ')[0]).join(' & ');
  return `<span class="social-chip" title="${escapeHtml((info.names || []).join(', '))}">👥 ${info.n} friend${info.n > 1 ? 's' : ''} ${label}${info.n === 1 && who ? ' · ' + escapeHtml(who) : ''}</span>`;
}

function friendsActivitySection() {
  const items = pageData.friendsActivity || [];
  if (!items.length) return '';
  return `<section class="friends-activity"><div class="section-head"><div><span class="eyebrow">👥 FRIENDS ACTIVITY</span><h2>Your crew is moving</h2></div><button class="link" data-page="friends">See friends <b>→</b></button></div><div class="fa-list">${items.slice(0, 6).map(a => `
    <article class="fa-row" ${a.user_id ? `data-action="athlete" data-id="${a.user_id}" role="button" title="Open profile"` : ''}>
      <span class="fa-icon">${a.icon}</span>
      <div class="fa-copy"><b>${escapeHtml(a.name)}</b> ${escapeHtml(a.text)}</div>
      ${a.link ? `<button class="text-btn small" data-page="${a.link}">View</button>` : ''}
      <time>${timeShort(a.at)}</time>
    </article>`).join('')}</div></section>`;
}

function emptyState(icon, title, body, page, cta) {
  return `<div class="empty-state"><span aria-hidden="true">${icon}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${page ? `<button class="primary small" data-page="${page}">${escapeHtml(cta)}</button>` : ''}</div>`;
}
function greeting() { const h = new Date().getHours(); return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'; }
function weekNumber() { const d = new Date(); const start = new Date(d.getFullYear(), 0, 1); return Math.ceil((((d - start) / 86400000) + start.getDay() + 1) / 7); }
const POST_KINDS = { fitness_update: ['✦', 'Update'], workout: ['🏋', 'Workout'], progress: ['📈', 'Progress'], meal: ['🍽', 'Meal'], achievement: ['🏆', 'Achievement'], challenge: ['⚡', 'Challenge'], motivation: ['🔥', 'Motivation'], question: ['❓', 'Question'], reel: ['🎬', 'Reel'], activity: ['🏃', 'Activity'], community: ['◌', 'Community'] };
function postCard(p) {
  if (p.__skel) return `<article class="post"><div class="post-author"><div class="avatar skeleton" style="border-radius:50%"></div><div style="flex:1"><strong class="skeleton" style="display:block;height:12px;width:42%"></strong><small class="skeleton" style="display:block;height:9px;width:60%;margin-top:7px"></small></div></div><p class="skeleton" style="height:46px;border-radius:10px;margin:12px 0 0"></p></article>`;
  const [icon, label] = POST_KINDS[p.kind] || ['✦', 'Update'];
  const REACTIONS = [['beast', '🔥', 'Beast'], ['respect', '💪', 'Respect'], ['keepgoing', '🫡', 'Keep going'], ['support', '❤️', 'Support']];
  const rmap = {}; (p.reactions || []).forEach(r => { rmap[r.reaction] = r.n; });
  const mine = new Set(p.my_reactions || []);
  const reactBtns = REACTIONS.map(([k, ic, lab]) => `<button class="react ${mine.has(k) ? 'on' : ''}" data-action="react" data-id="${p.id}" data-reaction="${k}" aria-label="${lab}">${ic}${rmap[k] ? ` <small>${rmap[k]}</small>` : ''}</button>`).join('');
  return `<article class="post" data-post="${p.id}"><div class="post-author">${photoAvatar(p.name, p.author_id || p.id)}<div><strong>${escapeHtml(p.name)}</strong><small>${icon} ${label} · ${timeShort(p.created_at)}</small></div><button data-action="postMenu" data-id="${p.id}">•••</button></div>${socialChip('posts', p.id)}<p>${escapeHtml(p.body)}</p>${p.photo ? (p.media === 'video' ? `<video class="post-photo" src="${p.photo}" controls preload="metadata" onerror="this.closest('article').querySelector('.post-photo-wrap')?.remove()"></video>` : `<span class="post-photo-wrap"><img class="post-photo" src="${p.photo}" alt="" loading="lazy" onerror="this.parentElement.remove()"/></span>`) : ''}<div class="react-row">${reactBtns}</div><div class="post-actions"><button data-action="like" data-id="${p.id}">${p.liked ? '♥ Liked' : '♡ Like'} <small>${p.likes}</small></button><button data-action="comment" data-id="${p.id}">◌ Comment <small>${p.comments}</small></button><button data-action="share" data-id="${p.id}">↗ Share</button></div></article>`;
}
function activity(icon, title, people, time, place, type, id, joined) {
  return `<article class="activity-card" data-action="activityDetail" data-id="${id || 1}" style="cursor:pointer"><div class="activity-icon photo-tile" style="background-image:url('${sportPhoto(type)}')"><span>${icon}</span></div><div class="activity-meta"><span>${escapeHtml(type)}</span><h3>${escapeHtml(title)}</h3>${socialChip('activities', id)}<p>◉ ${escapeHtml(place)}</p><div><b>◷ ${escapeHtml(time)}</b><b>◉ ${escapeHtml(people)}</b></div></div><button class="join ${joined ? 'joined' : ''}" data-action="joinActivity" data-id="${id || 1}">${joined ? 'Joined ✓' : 'Join +'}</button></article>`;
}
function discover() {
  const recs = pageData.recommendations.length ? pageData.recommendations : [];
  const top = recs[0];
  const others = recs.slice(1, 7);
  return shell(`${pageHeader('Discover your people', 'Matches, activities and communities around Chennai.')}
<div class="discover-intro"><div><span class="pill lime">✦ MATCHED FOR YOU</span><h2>Find your <em>fitness people.</em></h2><p>Our matching engine considers activity preference, schedules, goals, location and intensity.</p></div><button class="filter" data-action="filters">☷ Filters <b>⌄</b></button></div><div class="tabs" id="discover-tabs">${['People', 'Activities', 'Communities', 'Events', 'Businesses'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-tab="${t.toLowerCase()}">${t}</button>`).join('')}</div><div class="search">⌕ <input id="discover-search" placeholder="Search people, activities, communities..."/><span>⌘ K</span></div>
<div id="tab-people">${(pageData.friendsData && (pageData.friendsData.items || []).length) ? `<section class="section-head"><div><span class="eyebrow">✓ YOUR FRIENDS</span><h2>Already on your crew</h2></div><button class="link" data-page="messages">Message them <b>→</b></button></section><div class="people-grid">${(pageData.friendsData.items || []).slice(0, 6).map(f => personCard({ ...f, is_friend: true })).join('')}</div>` : ''}
${top ? `<section class="match-feature"><div class="match-big-art"><div>${top.score}<small>%</small></div><span>YOUR TOP MATCH</span></div><div class="match-feature-copy">${avatar(top.name, 'blue')}<span class="verified">${escapeHtml(top.name)} ✓</span><h2>Designed for the<br/><em>same rhythm.</em></h2><p>You both love ${escapeHtml(top.activity)} and your schedules and intensity line up well.</p><div class="compat"><b>Why ${top.score}%?</b>${(top.reasons || []).map(r => `<span>✓ ${escapeHtml(r)}</span>`).join('')}</div><div class="hero-actions"><button class="primary" data-action="friend" data-id="${top.id}">${state.friends ? 'Friends ✓' : 'Add friend'}</button><button class="outline" data-action="challenge" data-id="${top.id}">Challenge ${escapeHtml(top.name.split(' ')[0])}</button></div></div><div class="match-score"><strong>${top.score}<span>%</span></strong><small>COMPATIBILITY SCORE</small><div class="bar"><i style="width:${top.score}%"></i></div><p>Excellent match</p></div></section>` : ''}
<section class="section-head"><div><span class="eyebrow">FIND PEOPLE</span><h2>Search the community</h2></div></section><div class="search people-search">⌕ <input id="people-search" placeholder="Search people by name or @username (press Enter)..."/></div><section class="section-head"><div><span class="eyebrow">ON FITVERSE</span><h2>${(pageData.allUsers || []).length} registered athlete${(pageData.allUsers || []).length === 1 ? '' : 's'}</h2></div><button class="link" data-page="challenges">Challenges <b>→</b></button></section><div class="people-grid" id="people-grid">${(pageData.allUsers || []).map(p => personCard(p)).join('') || '<p class="loading">No athletes found — try another name.</p>'}</div></div>
<div id="tab-activities" style="display:none"><div class="activity-grid">${pageData.activities.map(a => activity('🏀', a.title, `${a.participant_count} people`, `${dayShort(a.starts_at)} · ${timeShort(a.starts_at)}`, a.location_label, a.sport, a.id, a.joined)).join('') || '<p class="loading">No activities yet.</p>'}</div></div>
<div id="tab-communities" style="display:none">${(pageData.myCommunities || []).length ? `<section class="section-head"><div><span class="eyebrow">✓ YOUR CREWS</span><h2>Communities you joined</h2></div></section><div class="community-grid">${pageData.myCommunities.map(communityCard).join('')}</div><section class="section-head"><div><span class="eyebrow">DISCOVER MORE</span><h2>Find new crews</h2></div></section>` : ''}<div class="community-grid">${pageData.communities.map(communityCard).join('') || '<p class="loading">No communities yet.</p>'}</div></div>
<div id="tab-events" style="display:none">${(pageData.bookings || []).length ? `<section class="section-head"><div><span class="eyebrow">🎟 YOUR TICKETS</span><h2>Events you booked</h2></div><button class="link" data-page="bookings">All bookings <b>→</b></button></section><div class="event-grid">${pageData.events.filter(e => (pageData.bookings || []).some(b => b.name === e.name)).map(eventCard).join('')}</div>` : ''}<section class="section-head"><div><span class="eyebrow">ALL EVENTS</span><h2>Browse everything</h2></div></section><div class="event-grid">${pageData.events.map(eventCard).join('') || '<p class="loading">No events yet.</p>'}</div></div>
<div id="tab-businesses" style="display:none"><table class="data-table"><thead><tr><th>BUSINESS</th><th>CATEGORY</th><th>LOCATION</th><th>RATING</th></tr></thead><tbody>${pageData.businesses.map(row => `<tr><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.category)}</td><td>${escapeHtml(row.location_label)}</td><td>★ ${row.rating}</td></tr>`).join('') || '<tr><td colspan="4">Loading…</td></tr>'}</tbody></table></div>`);
}
function personCard(p) {
  const score = p.score ?? (80 + (p.id * 3) % 18);
  const isFriend = p.is_friend || (state.friends || []).some(f => f.id === p.id);
  return `<article class="person-card" data-person="${p.id}"><div class="person-cover photo" style="background-image:linear-gradient(rgba(20,40,60,.15), rgba(20,40,60,.55)), url('${p.photo || sportPhoto(p.activity || p.favorite_activity)}')"><span>${isFriend ? '👥 FRIEND' : score + '% match'}</span></div><div class="person-info">${photoAvatar(p.name, p.id)}<h3>${escapeHtml(p.name)} <i>✓</i></h3><p>${escapeHtml(p.activity || p.favorite_activity || '')} · ${escapeHtml(p.fitnessLevel || p.fitness_level || '')}</p><div>${isFriend ? '<button class="join joined" disabled>Friends ✓</button>' : `<button class="outline" data-action="friend" data-id="${p.id}">Add friend</button>`}<button class="primary" data-action="messageUser" data-id="${p.id}">Message</button><button class="more" data-action="personMenu" data-id="${p.id}">•••</button></div></div></article>`;
}
function challenges() {
  const c = pageData.challenges[0];
  const active = state.challenge === 'accepted' || state.challenge === 'won';
  const myId = me().id || 0;
  const oppProgress = c ? (c.opponent_id === myId ? c.challenger_progress : c.opponent_progress) : 0;
  const myProgress = c ? (c.challenger_id === myId ? c.challenger_progress : c.opponent_progress) : 0;
  return shell(`${pageHeader('Challenges', 'Play harder with the people who keep you going.')}
<section class="challenge-hero"><div><span class="pill coral">HEAD TO HEAD</span><h2>${state.challenge === 'won' ? 'You took the win.' : active ? 'The run is on.' : c ? `${escapeHtml((c.challenger_name || 'Your rival').split(' ')[0])} challenged you.` : 'Start a head-to-head.'}</h2><p>${state.challenge === 'won' ? 'Victory looks good on you. Start another challenge?' : active && c ? `You have until ${dayShort(c.ends_at)} to make your move.` : c ? 'A challenge is waiting for your answer.' : 'Challenge a friend and make fitness more fun.'}</p><div class="versus"><div>${avatar(c ? c.challenger_name : '?', 'blue')}<strong>${escapeHtml(c ? (c.challenger_name || 'Rival').split(' ')[0] : '—')}</strong><small>${oppProgress} ${c ? (c.challenge_type || '').includes('distance') ? 'km' : 'sessions' : ''}</small></div><b>VS</b><div>${avatar(me().name || 'You', 'mint')}<strong>You</strong><small>${myProgress}</small></div></div>${state.challenge === 'pending' && c ? '<button class="primary" data-action="accept">Accept challenge <b>→</b></button>' : state.challenge === 'accepted' ? '<button class="primary" data-action="win">Mark activity complete +120 XP</button>' : '<button class="primary" data-action="challenge">New challenge</button>'}</div><div class="challenge-kpi"><span>⚔️</span><small>HEAD TO HEAD</small><strong>${(pageData.challenges || []).length}</strong><p>${(pageData.challenges || []).length === 1 ? 'challenge' : 'challenges'}</p></div></section>
<section class="section-head"><div><span class="eyebrow">YOUR ARENA</span><h2>Active challenges</h2></div><button class="create-inline" data-action="challenge">＋ New challenge</button></section><div class="challenge-list">${(pageData.challenges || []).map(ch => {
  const myP = ch.challenger_id === (me().id || 1) ? ch.challenger_progress : ch.opponent_progress;
  const pct = Math.min(100, Math.round(((myP || 0) / (ch.target_value || 5)) * 100));
  const ops = ch.status === 'pending' && ch.opponent_id === (me().id || 1)
    ? `<button class="primary small" data-action="chAccept" data-id="${ch.id}">Accept</button><button class="text-btn small" data-action="chDecline" data-id="${ch.id}">Decline</button>`
    : ch.status === 'active' && ch.joined
      ? `<button class="outline small" data-action="chProgress" data-id="${ch.id}" data-target="${ch.target_value}">+ Log progress</button>${ch.involved ? '' : `<button class="more" data-action="chInvite" data-id="${ch.id}" title="Invite friend">＋👥</button>`}`
      : ch.status === 'completed' && ch.winner_id ? `<span class="pill lime">${ch.winner_id === (me().id || 1) ? 'You won 🏆' : 'Decided'}</span>` : `<button class="outline small" data-action="chInvite" data-id="${ch.id}">Join</button>`;
  return `<article><span>⚡</span><div><b>${escapeHtml(ch.title)}</b><p>${escapeHtml(ch.challenge_type)} · vs ${escapeHtml(ch.challenger_id === (me().id || 1) ? ch.opponent_name : ch.challenger_name)} · target ${ch.target_value}</p>${socialChip('challenges', ch.id)}<div class="bar slim"><i style="width:${pct}%"></i></div></div><div class="challenge-progress"><strong>${ch.status}</strong><em>${myP || 0}/${ch.target_value}</em></div><div class="ch-ops">${ops}</div></article>`;
}).join('') || emptyState('⚔️', 'No challenges yet', 'Challenge a friend and make fitness more fun.', null, '')}</div>
${(pageData.challengeBoard || []).length ? `<section class="section-head"><div><span class="eyebrow">HALL OF WINS</span><h2>Most challenge victories</h2></div></section><section class="win-board">${(pageData.challengeBoard || []).map((r, i) => `<div class="rank"><b>0${i + 1}</b>${avatar(r.name, ['blue', 'mint', 'teal', 'orange', 'purple'][i % 5])}<strong>${escapeHtml(r.name === me().name ? 'You' : r.name)}</strong><em>${r.wins} win${r.wins > 1 ? 's' : ''}</em></div>`).join('')}</section>` : ''}
<section class="section-head"><div><span class="eyebrow">✦ AI COACH</span><h2>Who should you challenge?</h2></div></section>
<div class="ai-ideas">${(pageData.challengeFriends || []).slice(0, 3).map((f, i) => {
  const fa = ['Revenge match — they beat you last time.', 'You two are level — settle it this week.', 'Their streak is on fire — break it!'][i % 3];
  return `<div class="ai-idea-row" role="button" data-action="challengeFriend" data-id="${f.id}"><span>⚔️</span><div><b>${escapeHtml(f.name)}</b><small>${fa}</small></div><button class="primary small" tabindex="-1">Challenge</button></div>`;
}).join('') || '<p class="loading">Add friends to get AI-powered challenge suggestions.</p>'}</div>
<section class="leaderboard"><div><span class="eyebrow">CAMPUS LEADERBOARD</span><h2>XP leaders this week</h2>${(pageData.leaderboard || []).slice(0, 5).map((r, i) => `<div class="rank ${r.name === me().name ? 'you' : ''}"><b>0${i + 1}</b>${avatar(r.name, ['blue', 'mint', 'teal', 'orange', 'purple'][i % 5])}<strong>${escapeHtml(r.name === me().name ? 'You' : r.name)}</strong><em>${r.xp.toLocaleString()} XP</em></div>`).join('')}</div><div class="level-card"><span>LEVEL ${level()}</span><h3>${levelName()}</h3><p>${Math.max(0, 500 - (state.xp % 500))} XP until ${levelName(1) || 'next'} level</p><div class="bar"><i style="width:${progress()}%"></i></div></div></section>`);
}
function communityCard(c) {
  return `<article class="community-card" data-community="${c.id}"><div class="community-cover photo" style="background-image:linear-gradient(rgba(11,23,17,.25), rgba(11,23,17,.45)), url('${sportPhoto(c.activity)}')" data-action="communityOpen" data-id="${c.id}" role="button" title="Open community"><span>🏀</span><small>${(c.member_count || 0).toLocaleString()} members</small></div>    <div><h3 data-action="communityOpen" data-id="${c.id}" role="button">${escapeHtml(c.name)}</h3>${socialChip('communities', c.id)}<p>${escapeHtml(c.description)}</p><button class="${c.joined ? 'outline' : 'primary small'}" data-action="${c.joined ? 'leaveCommunity' : 'joinCommunity'}" data-id="${c.id}">${c.joined ? 'Joined ✓' : 'Join community'}</button><button class="outline small" data-action="communityChallenge" data-id="${c.id}" title="Challenge a member">⚔️</button><button class="more" data-action="communityMenu" data-id="${c.id}">•••</button></div></article>`;
}
function communities() {
  const mine = (pageData.myCommunities || []).filter(c => c.joined);
  return shell(`${pageHeader('Communities', 'Find a place to belong, wherever you move.')}
<div class="community-hero"><span class="pill lime">YOUR COMMUNITIES</span><h2>Move with your <em>people.</em></h2><p>From first-time runners to court regulars — your next crew is here.</p><button class="primary" data-action="createCommunity">＋ Create community</button></div>
${mine.length ? `<section class="section-head"><div><span class="eyebrow">✓ YOUR CREWS</span><h2>Communities you joined</h2></div></section><div class="community-grid">${mine.map(communityCard).join('')}</div>` : ''}
<div class="community-grid">${pageData.communities.map(communityCard).join('') || '<p class="loading">Loading communities…</p>'}</div>`);
}
function eventCard(e) {
  return `<article class="event-card" data-event="${e.id}"><div class="event-img photo" style="background-image:url('img/${e.photo}')"><span>${escapeHtml(e.category.toUpperCase())}</span><b>${dayShort(e.starts_at)}</b></div><div><h3>${escapeHtml(e.name)}</h3>${socialChip('activities', e.id)}<p>⌖ ${escapeHtml(e.location_label)} · ${e.booked_count || 0} attending</p><strong>${e.price_inr > 0 ? inr(e.price_inr) : 'FREE'}</strong><div style="display:flex;gap:6px"><button class="outline" data-action="bookEvent" data-id="${e.id}">${e.booked ? 'Booked ✓' : e.price_inr > 0 ? `Book · ${inr(e.price_inr)}` : 'Book free'}</button><button class="more" data-action="eventDetail" data-id="${e.id}" title="Details">ℹ</button><button class="more" data-action="eventInvite" data-id="${e.id}" title="Invite a friend">✉</button></div></div></article>`;
}
function events() {
  const evs = pageData.events || [];
  const hero = evs.find(e => e.id === 1) || evs[0];
  const rest = evs.filter(e => e !== hero);
  // FITVERSE 6.2: booked events live in their OWN section ("Your tickets"),
  // so the browse grid only shows events you have NOT booked.
  const mine = evs.filter(e => e.booked);
  const browse = rest.filter(e => !e.booked);
  const evLoading = pageData.__loading && !evs.length;
  return shell(`${pageHeader('Fitness events', 'Save your spot. Show up for the story.')}
${mine.length ? `<section class="section-head" style="margin-top:8px"><div><span class="eyebrow">🎟 YOUR BOOKINGS</span><h2>Events you're going to</h2></div><button class="link" data-page="bookings">All tickets <b>→</b></button></section><div class="event-grid">${mine.map(eventCard).join('')}</div>` : ''}
${hero ? `<div class="event-hero photo" style="background-image:linear-gradient(90deg, rgba(10,16,20,.94) 45%, rgba(10,16,20,.45) 100%), url('${sportPhoto(hero.category)}')"><div><span class="pill coral">FEATURED · ${dayShort(hero.starts_at).toUpperCase()}</span><h2>${escapeHtml(hero.name.split(' ').slice(0, -1).join(' '))} <em>${escapeHtml(hero.name.split(' ').slice(-1))}</em></h2><p>${escapeHtml(hero.description)}</p><div class="event-details"><span>◷ ${dayShort(hero.starts_at)} · ${timeShort(hero.starts_at)}</span><span>⌖ ${escapeHtml(hero.location_label)}</span></div><button class="primary" data-action="bookEvent" data-id="${hero.id}">${hero.booked ? 'Booked ✓' : hero.price_inr > 0 ? `Book ${inr(hero.price_inr)}` : 'Book free'} <b>→</b></button></div><div class="event-art"><div class="moon"></div><span>RUN<br/>THE<br/>NIGHT</span><small>${escapeHtml(hero.category.toUpperCase())}</small></div></div>` : evLoading ? loadingStrip('Loading events') : '<p class="loading">No events scheduled right now.</p>'}
<div class="ai-ideas"><div class="ai-idea-row" role="button" data-action="quickAction" data-qa="workout"><span>🏃</span><div><b>Train for the next event</b><p style="margin:2px 0 0;color:var(--fv-mut);font-size:11px">Build a cardio plan from your health data so you show up race-ready.</p></div><button class="primary small" tabindex="-1">Build</button></div><div class="ai-idea-row" role="button" data-action="eventInvite" data-id="1"><span>✉</span><div><b>Bring your crew</b><p style="margin:2px 0 0;color:var(--fv-mut);font-size:11px">Groups show up and finish — invite a friend to the featured event.</p></div><button class="primary small" tabindex="-1">Invite</button></div></div>
<section class="section-head"><div><span class="eyebrow">UP NEXT</span><h2>More ways to show up</h2></div><button class="filter" data-action="eventFilter">All categories ⌄</button></section>${evLoading && !hero ? '' : `<div class="event-grid">${browse.map(eventCard).join('') || (evLoading ? loadingStrip('Loading events') : '<p class="loading">No more events — you have seen them all.</p>')}</div>`}`);
}
function messages() {
  const convs = pageData.conversations;
  if (!sessionToken) return shell(`${pageHeader('Messages', 'Private chats between real FITVERSE athletes.')}
<section class="hero photo" style="background-image:linear-gradient(100deg, rgba(8,18,13,.94) 45%, rgba(8,18,13,.55) 100%), url('${PHOTOS.heroRun}')"><div><span class="pill lime">✉ REAL MESSAGES</span><h2>Chat with real athletes,<br/>not bots.</h2><p>Messages are private, stored in your account and delivered instantly. Sign in to open your inbox.</p><div class="hero-actions"><button class="primary" data-action="register">Create your account <b>→</b></button><button class="outline" data-action="account">Log in</button></div></div></section>`);
  if (!convs.length && pageData.__loading) return shell(`${pageHeader('Messages', 'Private chats between real FITVERSE athletes.')}
${loadingStrip('Syncing your inbox')}`);
  if (!convs.length) return shell(`${pageHeader('Messages', 'Private chats between real FITVERSE athletes.')}
${emptyState('✉', 'No conversations yet', 'Open any athlete’s profile and tap Message — your chat stays private between the two of you.', 'discover', 'Find athletes')}`);
  const active = convs.find(c => c.id === pageData.activeConversation) || convs[0];
  const msgs = pageData.messages;
  // FITVERSE 6.3: every sender carries a resolved name+avatar — optimistic sends
  // and SSE pushes used to arrive nameless and the row rendered glitchy.
  const ME_ID = Number(me().id || 1);
  const nameOf = (m) => {
    if (m.sender_id === ME_ID) return me().name || 'You';
    return m.name || active.title || 'Athlete';
  };
  // Group consecutive messages by sender; day dividers; photo avatars.
  const bubbles = msgs.map((m, i) => {
    const prev = msgs[i - 1];
    const mine = m.sender_id === ME_ID;
    const grouped = prev && prev.sender_id === m.sender_id;
    const showDay = !prev || new Date(prev.created_at).toDateString() !== new Date(m.created_at).toDateString();
    const who = nameOf(m);
    return `${showDay ? `<div class="day-divider"><span>${dayShort(m.created_at)}</span></div>` : ''}<div class="msg-row ${mine ? 'mine' : ''} ${grouped ? 'grouped' : ''}">${!grouped ? photoAvatar(who, m.sender_id, 36, m.avatar_url) : '<span class="pavatar-spacer"></span>'}<p class="${mine ? 'sent' : 'received'}">${escapeHtml(m.body)}<time>${m.created_at?.includes('T') ? timeShort(m.created_at) : escapeHtml(m.created_at || 'now')}</time></p></div>`;
  }).join('') || '<p style="opacity:.6">Say hi 👋</p>';
  return shell(`${pageHeader('Messages', 'Real conversations, stored in your database.')}
<div class="message-layout"><aside class="conversation-list"><div class="message-search">⌕ <input id="chat-search" placeholder="Search chats" style="border:0;background:none;outline:0;width:80%"/></div>${convs.map(c => `<button class="conversation ${c.id === pageData.activeConversation ? 'selected' : ''}" data-conv="${c.id}">${photoAvatar(c.title, c.other_id || c.id, 36, c.other_avatar_url)}<div><strong>${escapeHtml(c.title)}</strong><small>${escapeHtml((c.last_message || 'Say hi').slice(0, 34))}</small></div><time>${c.last_at ? timeShort(c.last_at) : ''}</time></button>`).join('')}
${(pageData.friendsData && (pageData.friendsData.items || []).length) ? `<div class="newchat-strip"><span class="eyebrow" style="padding:8px 8px 4px;display:block">START A NEW CHAT</span>${(pageData.friendsData.items || []).slice(0, 6).map(f => `<button class="conversation" data-action="newChatPick" data-fid="${f.id}">${photoAvatar(f.name, f.id, 36, f.avatar_url)}<div><strong>${escapeHtml(f.name)}</strong><small>Say hi 👋</small></div></button>`).join('')}</div>` : ''}</aside><section class="chat"><div class="chat-head">${photoAvatar(active.title, active.other_id || active.id, 36, active.other_avatar_url)}<div><strong>${escapeHtml(active.title)}</strong><small>${escapeHtml(active.kind)} · <span class="live-dot">●</span> live</small></div><button data-action="convMenu" data-id="${active.id}">•••</button></div><div class="bubbles" id="bubbles">${bubbles}</div><div class="typing" id="typing" style="display:none"><span></span><span></span><span></span></div><form class="composer" data-form="message" data-conv="${active.id}"><input id="composer-input" placeholder="Message ${escapeHtml(String(active.title).split(' ')[0])}..." maxlength="1000" required/><button aria-label="Send message">➤</button></form></section></div>`);
}
function profile() {
  const p = me();
  const unlocked = pageData.achievements.filter(a => a.unlocked_at).length;
  if (!p.name && pageData.__loading) return shell(`${pageHeader('Your profile', 'Your progress tells a story.')}
${loadingStrip('Loading your profile')}`);
  return shell(`${pageHeader('Your profile', 'Your progress tells a story.')}
<section class="profile-hero"><div class="profile-cover photo" style="background-image:linear-gradient(110deg, rgba(22,79,62,.88), rgba(110,175,112,.6)), url('${PHOTOS.heroRun}')"></div><div class="profile-info">${avatar(p.name, 'mint')}<div><span class="pill lime">LEVEL ${level()} · ${levelName().toUpperCase()}</span><h2>${escapeHtml(p.name || 'Your profile')} <i>✓</i></h2><p>@${escapeHtml(p.username || 'you')} · ${escapeHtml(p.city || 'Your city')}</p><p class="bio">${escapeHtml(p.bio || '')}</p></div><div class="profile-actions"><button class="outline" data-action="edit">Edit profile</button><button class="text-btn" data-action="account">Account</button></div></div><div class="profile-stats"><span><b>${state.streak}</b> day streak</span><span><b>${state.xp.toLocaleString()}</b> XP</span><span><b>${state.activities}</b> activities</span><span><b>${pageData.friends.length}</b> friends</span></div></section>${pageData.intel && pageData.intel.dna ? `<a class="dna-mini" data-page="intelligence" role="button" style="cursor:pointer"><span class="mini-ring" style="--v:${pageData.intel.dna.scores ? pageData.intel.dna.scores.consistency : 0}"><b>${pageData.intel.dna.scores ? pageData.intel.dna.scores.consistency : '—'}</b></span><span><b>🧬 ${escapeHtml(pageData.intel.dna.personality || 'The Explorer')}</b><small>Fitness DNA · tap to open your full profile</small></span></a>` : ''}<div class="profile-tools"><button class="outline" data-page="bookings">🎟 My bookings</button><button class="outline" data-page="coach">✦ AI Coach</button><button class="outline" data-page="business">▦ Business</button><button class="outline" data-page="admin">◫ Admin</button><button class="outline" data-action="indianDiet">🍛 Indian diet</button><button class="outline ob-btn" data-action="runOnboarding">🧭 Setup wizard${pageData.mySettings && !pageData.mySettings.onboarded ? ' · not finished' : ''}</button></div><div class="tabs" id="profile-tabs">${['Posts', 'Friends', 'Achievements'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-ptab="${t.toLowerCase()}">${t}</button>`).join('')}</div>
<a class="pill lime" data-page="connectHealth" style="cursor:pointer;text-decoration:none;display:inline-block;margin:0 0 14px">🔌 Connect Health Data — import, track & AI insights →</a>
${profileVitalsCard()}
<div id="ptab-posts">${pageData.feed.filter(x => x.username === p.username).map(postCard).join('') || '<p class="loading">No posts yet — create one from the ＋ button.</p>'}</div>
<div id="ptab-friends" style="display:none">${pageData.friends.map(f => `<article class="person-card" style="max-width:420px"><div class="person-info" style="padding:14px">${avatar(f.name, 'teal')}<h3>${escapeHtml(f.name)} <i>✓</i></h3><p>@${escapeHtml(f.username)} · ${escapeHtml(f.status)}</p></div></article>`).join('') || '<p class="loading">No friends yet — find matches on Discover.</p>'}</div>
<div id="ptab-achievements" style="display:none"><div class="achievement-row">${pageData.achievements.map(a => `<article class="${a.unlocked_at ? '' : 'locked'}" style="${a.unlocked_at ? '' : 'opacity:.45'}"><span>${a.icon}</span><b>${escapeHtml(a.name)}</b><small>${escapeHtml(a.description)}</small></article>`).join('')}</div><p class="loading">${unlocked}/${pageData.achievements.length} unlocked</p></div>`);
}
function bookings() {
  const items = pageData.bookings || [];
  return shell(`${pageHeader('My bookings', 'Your upcoming experiences, all in one place.')}
<section class="section-head"><div><span class="eyebrow">YOUR TICKETS</span><h2>Ready when you are</h2></div><button class="link" data-page="events">Find events <b>→</b></button></section><div class="booking-list">${items.length ? items.map(item => `<article class="booking-item"><span class="ticket-check">✓</span><div><span class="eyebrow">${escapeHtml(String(item.status || 'CONFIRMED').toUpperCase())}</span><h3>${escapeHtml(item.name)}</h3><p>${dayShort(item.starts_at)} · ${escapeHtml(item.location_label)} · ${item.quantity} ticket${item.quantity > 1 ? 's' : ''}</p><strong>${escapeHtml(item.booking_code)}</strong></div><div style="display:flex;gap:6px;margin-left:auto"><button class="outline small" data-action="bookingsDownload" data-code="${escapeHtml(item.booking_code)}" data-name="${escapeHtml(item.name)}">⬇ Ticket</button></div><div class="qr">▦<br/>▥</div></article>`).join('') : `<article class="booking-item"><span>🎟️</span><div><h3>No bookings yet</h3><p>Find an event that moves you, then your digital ticket will appear here.</p></div><button class="outline" data-page="events">Browse events</button></article>`}</div>`);
}
function coach() {
  return shell(`${pageHeader('FITVERSE Coach', 'Contextual recommendations from your profile and the FITVERSE network.')}
<section class="coach-layout"><span class="pill lime">DETERMINISTIC RECOMMENDATIONS</span><h2>What can I help you move toward?</h2><p class="coach-answer">${escapeHtml(pageData.coach)}</p><form class="composer" data-form="coach"><input placeholder="Ask what you should do today..." maxlength="250" required/><button aria-label="Ask coach">➤</button></form><div class="coach-prompts"><button data-action="coachPrompt" data-q="Find basketball players">Find basketball players</button><button data-action="coachPrompt" data-q="Suggest a challenge">Suggest a challenge</button><button data-action="coachPrompt" data-q="Find an event this weekend">Find an event this weekend</button></div></section>`);
}
// ===== FITVERSE 2.0 pages =====
function workoutPage() {
  const w = pageData.workouts || [];
  const prs = pageData.prs || [];
  const exs = pageData.exercises || [];
  const sess = pageData.activeSession;
  const editor = sess ? `<section class="finish-session ${sess.finishing ? 'finishing' : ''}" id="finish-session">
  <div class="fs-head"><span class="pill lime">● SESSION IN PROGRESS</span><div><h3>${escapeHtml(sess.title)}</h3><small>Started ${timeShort(sess.startedAt)} · volume so far <b>${Math.round(sess.logs.reduce((a, x) => a + (x.weight * x.reps * x.sets || 0), 0)).toLocaleString()} kg</b></small></div></div>
  <div class="fs-rows" id="fs-rows">${sess.logs.map((x, i) => {
    const isNew = x.exercise_id === 'NEW' || !(exs.length ? exs : []).some(e => e.id === x.exercise_id);
    const opts = `${(exs.length ? exs : [{ id: 0, name: 'Exercise', muscle: '' }]).map(e => `<option value="${e.id}" ${!isNew && e.id === x.exercise_id ? 'selected' : ''}>${escapeHtml(e.name)} ${e.muscle ? '(' + escapeHtml(e.muscle) + ')' : ''}</option>`).join('')}${isNew ? `<option value="NEW" selected>+ ${escapeHtml(x.name || x.ai_name || 'New exercise')} — add to library</option>` : ''}`;
    return `<div class="wo-row"><select data-i="${i}" data-k="exercise_id">${opts}</select><input type="number" value="${x.sets}" min="1" max="20" data-i="${i}" data-k="sets" aria-label="Sets"/><input type="number" value="${x.reps}" min="1" max="100" data-i="${i}" data-k="reps" aria-label="Reps"/><input type="number" value="${x.weight}" min="0" step="0.5" data-i="${i}" data-k="weight" aria-label="Weight kg"/><button class="more" data-action="fsRemoveRow" data-i="${i}" aria-label="Remove" title="Remove exercise">×</button></div>`;
  }).join('')}</div>
  <div class="fs-actions">
    <button class="outline small" data-action="fsAddRow">＋ Exercise</button>
    <button class="outline small" data-action="fsAiFill">✦ AI fill this session</button>
    <button class="outline small" data-action="fsDiscard">Discard</button>
    <button class="primary" data-action="fsFinish">✓ FINISH WORKOUT</button>
  </div>
  <p class="loading fs-note">Volume = weight × reps × sets. PRs are detected automatically when you finish.</p>
</section>` : '';
  return shell(`${pageHeader('Workout', 'Log sessions, track volume, celebrate PRs.')}
${(pageData.workouts || []).length && pageData.woFilter ? `<p class="loading">Filtered by <b>${escapeHtml(String(pageData.woFilter))}</b> — <button class="text-btn" data-action="woFilter" data-id="">show all</button></p>` : ''}
<div class="workout-top"><button class="primary" data-action="logWorkout">＋ Log a workout</button><button class="outline" data-action="fsStart">▶ Start session · Finish later</button><button class="outline" data-action="generateWorkout">✦ Generate with AI</button><button class="outline" data-page="library">Exercise library</button><button class="outline" data-action="customExercise">✚ Custom exercise</button></div>
<div class="wo-style-chips"><button class="chip" data-action="quickAction" data-qa="easy">🪶 Easy & gentle</button><button class="chip" data-action="genStyle" data-style="cardio">🏃 Cardio</button><button class="chip" data-action="genStyle" data-style="home">🏠 Home workout</button><button class="chip" data-action="genStyle" data-style="yoga">🧘 Yoga</button></div>
${editor}
<section class="section-head"><div><span class="eyebrow">HISTORY</span><h2>Recent sessions</h2></div></section>  ${w.length ? `<div class="workout-filters"><button class="chip ${!pageData.woFilter ? 'active' : ''}" data-action="woFilter" data-id="">All</button>${['Push', 'Pull', 'Legs', 'Full'].map(f => `<button class="chip ${pageData.woFilter === f ? 'active' : ''}" data-action="woFilter" data-id="${f}">${f}</button>`).join('')}</div>
<div class="session-list">${w.filter(s => !pageData.woFilter || s.title.toLowerCase().includes(String(pageData.woFilter).toLowerCase())).map(s => {
  const open = pageData.openSession === s.id;
  return `<article class="session-card ${open ? 'open' : ''}" data-action="woToggle" data-id="${s.id}">
  <div class="session-date"><b>${dayShort(s.created_at)}</b><small>${timeShort(s.created_at)}</small></div>
  <div class="session-body"><h3>${escapeHtml(s.title)} <span class="wo-chev">${open ? '▴' : '⌄'}</span></h3>
    ${open ? `<div class="wo-detail">${s.logs.map(l => `<div class="wo-line"><img class="wo-img" src="${exerciseImage(l.name)}" alt="" loading="lazy"/><span class="wo-mus">${escapeHtml(l.muscle || '')}</span><span class="wo-ex">${escapeHtml(l.name)}</span>${formGuide(l.name, true)}<span class="wo-sets"><b>${l.sets}</b>×${l.reps}${l.weight > 0 ? ` @ ${l.weight}kg` : ' (bw)'}${l.is_pr ? ' <span class="pr-flag">🔥 PR</span>' : ''}</span></div>`).join('')}
    <div class="wo-session-actions" data-stop>
      <button class="outline small" data-action="woAiTweak" data-id="${s.id}" data-k="easier">🪶 Make easier</button>
      <button class="outline small" data-action="woAiTweak" data-id="${s.id}" data-k="harder">🔥 Make harder</button>
      <button class="outline small" data-action="woAiTweak" data-id="${s.id}" data-k="swap">⇄ Different exercises</button>
      <button class="outline small" data-action="woRest">⏱ Rest timer</button>
      <button class="more wo-del" data-action="woDelete" data-id="${s.id}" title="Delete session">🗑</button>
    </div></div>` : s.logs.slice(0, 3).map(l => `<p class="setline">${escapeHtml(l.name)} <b>${l.sets}×${l.reps}</b>${l.weight > 0 ? ` @ ${l.weight}kg` : ''}${l.is_pr ? ' <span class="pr-flag">🔥 PR</span>' : ''}</p>`).join('')}${!open && s.logs.length > 3 ? `<p class="loading">+${s.logs.length - 3} more — tap to expand</p>` : ''}
    <div class="session-stats"><span>⏱ ${s.duration_min} min</span><span>🏋 ${Math.round(s.total_volume).toLocaleString()} kg volume</span><span>⚡ ~${s.est_kcal} kcal</span>${s.pr_count ? `<span class="pr-flag">🔥 ${s.pr_count} PR${s.pr_count > 1 ? 's' : ''}</span>` : ''}</div>
  </div>
</article>`; }).join('')}</div>` : emptyState('🏋', 'No workouts yet', 'Complete your first workout to start building your fitness history.', null, null)}
${prs.length ? `<section class="section-head"><div><span class="eyebrow">PERSONAL RECORDS</span><h2>Your best lifts</h2></div></section><div class="pr-grid">${prs.map(p => {
  // FITVERSE 6.1: never show a dead "0 vol" — fall back to per-session volume,
  // then best sets×reps as bodyweight volume. Volume = weight×reps×sets.
  const vol = Math.round(p.max_vol || p.best_session_vol || (p.max_w ? p.max_w * (p.best_reps || 0) * 3 : 0) || 0);
  const val = p.max_w ? `${p.max_w} kg` : vol ? `${vol.toLocaleString()} vol` : '—';
  const sub = p.max_w || vol ? `${p.n} session${p.n > 1 ? 's' : ''} logged` : `${p.n} logged · no volume yet — add weight or more reps`;
  return `<article class="pr-card"><b>${escapeHtml(p.name)}</b><strong>${val}</strong><small>${sub}</small></article>`;
}).join('')}</div>` : ''}`);
}
function nutritionPage() {
  const n = pageData.nutrition || {};
  const t = n.targets || {};
  const tot = n.totals || { kcal: 0, protein: 0, carbs: 0, fat: 0 };
  const meals = ['breakfast', 'lunch', 'dinner', 'snacks'];
  const water = pageData.water || {};
  if (pageData.__loading && !n.items) return shell(`${pageHeader('Nutrition', 'Fuel the work. Log meals, hit your targets.')}
${loadingStrip('Opening your food diary')}`);
  return shell(`${pageHeader('Nutrition', 'Fuel the work. Log meals, hit your targets.')}
<div class="section-head" style="margin-top:6px"><div><span class="eyebrow">YOUR PLAN</span><h2>Daily targets</h2></div><button class="outline small" data-action="setTargets">⚙ Set Daily Targets</button></div>
<div class="macro-hero"><div class="macro-main"><span class="eyebrow">CALORIES TODAY</span><div class="macro-big"><b>${(tot.kcal || 0).toLocaleString()}</b><em>/ ${(t.kcal_target || 2200).toLocaleString()} kcal</em></div><div class="bar kcal-bar ${kcalBarClass(tot.kcal || 0, t.kcal_target || 2200)}"><i style="width:${Math.min(100, (tot.kcal || 0) / Math.max(1, t.kcal_target || 2200) * 100)}%"></i></div><small class="est-note">${(tot.kcal || 0) > (t.kcal_target || 2200) ? `⚠ ${(tot.kcal - t.kcal_target).toLocaleString()} kcal over your daily target` : (t.estimate_note || '')}</small></div>
<div class="macro-row">
  <div class="macro-chip p"><b>${tot.protein || 0}g</b><small>/ ${t.protein_target || 130}g protein</small><div class="bar slim"><i style="width:${Math.min(100, (tot.protein || 0) / Math.max(1, t.protein_target || 130) * 100)}%"></i></div></div>
  <div class="macro-chip c"><b>${tot.carbs || 0}g</b><small>/ ${t.carbs_target || 250}g carbs</small><div class="bar slim"><i style="width:${Math.min(100, (tot.carbs || 0) / Math.max(1, t.carbs_target || 250) * 100)}%"></i></div></div>
  <div class="macro-chip f"><b>${tot.fat || 0}g</b><small>/ ${t.fat_target || 70}g fat</small><div class="bar slim"><i style="width:${Math.min(100, (tot.fat || 0) / Math.max(1, t.fat_target || 70) * 100)}%"></i></div></div>
</div></div>
<div class="water-card"><div><span class="eyebrow">HYDRATION</span><div class="macro-big"><b>${((water.today_ml || 0) / 1000).toFixed(2)}L</b><em>/ ${((water.target_ml || 2500) / 1000).toFixed(1)}L</em></div><div class="bar"><i style="width:${Math.min(100, (water.today_ml || 0) / Math.max(1, water.target_ml || 2500) * 100)}%"></i></div></div>
<div class="water-actions"><button class="outline" data-action="addWater" data-ml="250">+250ml</button><button class="outline" data-action="addWater" data-ml="500">+500ml</button><button class="primary small" data-action="addWater" data-ml="750">+750ml</button><button class="outline small" data-action="addWaterCustom">＋ Add Water</button></div></div>
${suggestStrip()}
<section class="section-head" style="margin-top:22px"><div><span class="eyebrow">🇮🇳 HEALTH-DATA DIET</span><h2>Indian plate plan</h2></div><button class="outline small" data-action="indianDiet">✦ Build my plan</button></section>
<p class="loading" style="margin:0 0 14px">Roti-dal-sabzi plates auto-tuned to your calorie target, diet preference and — if you're 30+ and tracking them — your blood pressure and fasting sugar. High BP adds low-salt swaps; high sugar adds low-GI swaps and post-meal walks.</p>
<div class="section-head"><div><span class="eyebrow">FOOD DIARY</span><h2>Today's meals</h2></div><div style="display:flex;gap:8px"><button class="primary small" data-action="logMeal">＋ Log food</button><button class="outline small" data-action="scanMeal">✦ AI meal scan</button></div></div>
${meals.map(m => {
  const items = (n.items || []).filter(x => x.meal === m);
  const mkcal = items.reduce((a, b) => a + b.kcal, 0);
  return `<div class="meal-block"><h4>${m[0].toUpperCase() + m.slice(1)} <small>${mkcal ? mkcal + ' kcal' : ''}</small></h4>
  <div class="meal-quick"><button class="text-btn" data-action="quickMeal" data-meal="${m}">＋ quick add</button><button class="text-btn" data-action="aiSuggestLog" data-meal="${m}">✦ ask AI</button></div>
  ${items.length ? items.map(i => `<div class="meal-item"><span>${escapeHtml(i.name)}</span><b>${i.kcal} kcal · ${Math.round(i.protein_g)}g protein</b><button class="more" data-action="delMeal" data-id="${i.id}" aria-label="Delete">×</button></div>`).join('') : ''}
  ${items.length ? '' : `<p class="loading">Nothing in ${m} yet — use <b>＋ quick add</b> or <b>✦ ask AI</b> above.</p>`}
  </div>`;
}).join('')}`);
}
// AI training suggestion, built from the user's imported health data.
function suggestStrip() {
  const s = pageData.healthSuggest;
  if (!s) return `<div class="ai-suggest" id="health-suggest"><span class="spin">✦</span><p>Checking your imported health data for today's best training…</p></div>`;
  if (s.insufficient) return `<div class="ai-suggest"><span>📥</span><p><b>Unlock AI training suggestions:</b> import your health data (Takeout or Health Connect file) or log a few days of metrics — the Health Brain then picks your training from YOUR numbers.</p></div>`;
  const g = s.suggestion || {};
  const facts = (g.facts || {});
  const bpAvg = facts.avg_bp, sugarAvg = facts.avg_sugar;
  const vPills = `${bpAvg ? `<span class="v-pill ${bpAvg >= 140 ? 'warn' : 'good'}">🩺 BP ${bpAvg}</span>` : ''}${sugarAvg ? `<span class="v-pill ${sugarAvg >= 126 ? 'warn' : 'good'}">🩸 Sugar ${sugarAvg}</span>` : ''}`;
  const ageNote = facts.age >= 55 ? ' · joint-friendly picks for you' : '';
  return `<div class="ai-suggest"><span>🧠</span><div><b>${escapeHtml(g.title || 'Today\'s session')}</b><p>${escapeHtml(g.why || '')}</p><small class="dim">Your numbers: ${facts.avg_steps || 0} avg steps · ${facts.avg_sleep_h ?? '—'}h sleep · ${facts.km_cardio || 0} km cardio · ${facts.sessions_recent || 0} recent sessions${ageNote}</small>${vPills ? `<div style="margin-top:7px">${vPills}</div>` : ''}</div>
  <div class="as-actions"><button class="primary small" data-action="aiSuggestWorkout">Build this workout</button><button class="outline small" data-action="saveSuggestion">Save to plan</button></div>
  ${s.ai ? `<p class="as-ai">✦ ${mdLite(s.ai)}</p>` : ''}${s.engine === 'groq' ? '<span class="ai-status-chip live"><i></i>GROQ</span>' : ''}</div>`;
}
// Calorie bar color contract (uses each user's OWN configured target):
// <50% red · 51–70% orange · 71–90% yellow · 91–100% green · >target+300 red + glow.
function kcalBarClass(eaten, target) {
  const pct = eaten / Math.max(1, target) * 100;
  if (eaten > target + 300) return 'over';
  if (pct > 100) return 'warn';           // over target but ≤ +300: amber, no glow
  if (pct >= 91) return 'ok';
  if (pct >= 71) return 'mid';
  if (pct >= 51) return 'low';
  return 'empty';
}
function setTargetsModal() {
  const t = (pageData.nutrition && pageData.nutrition.targets) || {};
  const water = pageData.water || {};
  modal(`<span class="eyebrow">NUTRITION</span><h2>Set Daily Targets</h2><p>Your targets are yours alone — changing them never affects anyone else. Leave calories/protein as 0 to keep the automatic estimate.</p><form class="activity-form" id="targets-form">
  <label>Calories (kcal/day)<input name="kcal_target" type="number" min="0" max="6000" value="${t.kcal_target || 0}"></label>
  <label>Protein (g/day)<input name="protein_target" type="number" min="0" max="400" value="${t.protein_target || 0}"></label>
  <label>Carbs (g/day)<input name="carbs_target" type="number" min="0" max="800" value="${t.carbs_target || 0}"></label>
  <label>Fats (g/day)<input name="fat_target" type="number" min="0" max="300" value="${t.fat_target || 0}"></label>
  <label>Water (ml/day)<input name="water_target_ml" type="number" min="500" max="10000" step="50" value="${water.target_ml || 2500}"></label>
  <button class="primary" type="submit">Save targets</button></form>`);
  $('#targets-form').onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api('/api/settings', { method: 'POST', body: JSON.stringify({ kcal_target: Number(f.kcal_target) || 0, protein_target: Number(f.protein_target) || 0, water_target_ml: Number(f.water_target_ml) || 2500 }) });
      await api('/api/nutrition/targets', { method: 'POST', body: JSON.stringify({ carbs_target: Number(f.carbs_target) || 0, fat_target: Number(f.fat_target) || 0 }) }).catch(() => {});
      $('#modal').innerHTML = ''; await hydrate(); await loadPageData('nutrition'); render(); toast('Daily targets saved');
    } catch (err) { toast(err.message); }
  };
  bind();
}
function progressPage() {
  const entries = pageData.progressEntries || [];
  const weights = entries.filter(e => e.weight_kg).slice(0, 12).reverse();
  const review = pageData.review && pageData.review.week ? pageData.review : null;
  return shell(`${pageHeader('Progress', 'Private by default. Visible to you alone.')}
${review ? `<section class="review-card"><div class="review-head"><span class="pill lime">✦ YOUR WEEKLY RECAP</span><h3>${escapeHtml(review.week)}</h3><button class="more" data-action="shareRecap" title="Share card">↗</button></div>
<div class="review-grid"><div><b>${review.workouts}</b><small>workouts</small></div><div><b>${review.calories_burned.toLocaleString()}</b><small>kcal burned</small></div><div><b>${review.avg_protein}g</b><small>avg protein</small></div><div><b>${review.new_prs}</b><small>new PRs</small></div><div><b>${review.consistency}%</b><small>consistency</small></div><div><b>${review.streak}</b><small>day streak</small></div></div>
<div class="review-tips">${review.ai_summary ? `<p class="review-ai">✦ ${escapeHtml(review.ai_summary)}</p>` : ''}${review.suggestions.map(s => `<p>💡 ${escapeHtml(s)}</p>`).join('')}</div></section>` : ''}
<div class="progress-actions"><button class="primary" data-action="addProgress">＋ Log measurements</button></div>
<section class="section-head"><div><span class="eyebrow">WEIGHT TREND</span><h2>Your trajectory</h2></div></section>
${weights.length >= 2 ? `<div class="chart-card">${lineChart(weights.map(e => ({ x: dayShort(e.entry_date), y: e.weight_kg })), 'kg')}</div>` : emptyState('📈', 'Not enough data yet', 'Log your weight twice to see your trend line here.')}
<section class="section-head"><div><span class="eyebrow">MEASUREMENTS</span><h2>History</h2></div></section>
${entries.length ? `<div class="session-list">${entries.map(e => `<article class="session-card"><div class="session-date"><b>${dayShort(e.entry_date)}</b></div><div class="session-body">${e.weight_kg ? `<p class="setline">Weight <b>${e.weight_kg} kg</b></p>` : ''}${e.body_fat ? `<p class="setline">Body fat <b>${e.body_fat}%</b></p>` : ''}${e.waist_cm ? `<p class="setline">Waist <b>${e.waist_cm} cm</b></p>` : ''}${e.note ? `<p class="setline"><i>${escapeHtml(e.note)}</i></p>` : ''}<small class="lock-note">🔒 Private</small></div></article>`).join('')}</div>` : emptyState('📏', 'No measurements yet', 'Log your weight or measurements to build your private timeline.')}`);
}
function friendsPage() {
  const fm = pageData.fitmatch || [];
  const fr = pageData.friendsData || {};
  const friends = fr.items || [];
  const incoming = fr.incoming || [];
  // Real activity: recent friend-type notifications turned into a live timeline.
  const friendNews = (pageData.notifications || []).filter(n => n.type === 'friend' || n.type === 'friend_request').slice(0, 6);
  return shell(`${pageHeader('Friends', 'Your people. Your crew. Your competition.')}
${incoming.length ? `<section class="req-strip"><span class="pill coral">${incoming.length} REQUEST${incoming.length > 1 ? 'S' : ''}</span>${incoming.map(r => `<div class="req-row">${photoAvatar(r.name, r.id)}<div><b>${escapeHtml(r.name)}</b><small>@${escapeHtml(r.username)} sent you a friend request</small></div><button class="primary small" data-action="acceptFriend" data-id="${r.req_id}">Accept</button><button class="more" data-action="rejectFriend" data-id="${r.req_id}">×</button></div>`).join('')}</section>` : ''}
${friendNews.length ? `<section class="req-strip"><span class="pill lime">RECENT FRIEND ACTIVITY</span>${friendNews.map(n => `<div class="req-row"><span class="notif-ico">👥</span><div><b>${escapeHtml(n.title)}</b><small>${escapeHtml(n.body)}</small></div></div>`).join('')}</section>` : ''}
<section class="section-head"><div><span class="eyebrow">✦ AI MATCHING</span><h2>FIT MATCH</h2></div></section>
${fm.length ? `<div class="people-grid">${fm.map(p => personCard(p)).join('')}</div>` : emptyState('🧬', 'No matches yet', 'Set your goals in onboarding so FIT MATCH can find your training partners.')}
<section class="section-head"><div><span class="eyebrow">YOUR CIRCLE</span><h2>${friends.length} friend${friends.length === 1 ? '' : 's'}</h2></div></section>
${friends.length ? `<div class="friend-rows">${friends.map(f => `<div class="req-row" data-action="athlete" data-id="${f.id}" style="cursor:pointer">${photoAvatar(f.name, f.id)}<div><b>${escapeHtml(f.name)}</b><small>${escapeHtml(f.favorite_activity || '')} · ${f.streak}-day streak${f.city ? ' · ' + escapeHtml(f.city) : ''}</small></div><button class="outline small" data-action="challenge" data-id="${f.id}">Challenge</button><button class="primary small" data-action="messageUser" data-id="${f.id}">Message</button></div>`).join('')}</div>` : emptyState('👥', 'No friends yet', 'Send friend requests from Discover or FIT MATCH — fitness is better together.')}
<section class="section-head"><div><span class="eyebrow">COMPETE TOGETHER</span><h2>Start something</h2></div></section>
<div class="ai-ideas">
<div class="ai-idea-row" role="button" data-action="challenge"><span>⚔️</span><div><b>New head-to-head</b><small>Steps, km or sessions — pick a rival and a target.</small></div><button class="primary small" tabindex="-1">Start</button></div>
<div class="ai-idea-row" role="button" data-action="communityInvite"><span>◌</span><div><b>Bring a friend into a community</b><small>Crews train more — invite someone to your crew.</small></div><button class="primary small" tabindex="-1">Invite</button></div>
<div class="ai-idea-row" role="button" data-action="quickAction" data-qa="dna"><span>🧬</span><div><b>Compare Fitness DNA</b><small>See how your consistency and cardio scores stack up, then challenge the gap.</small></div><button class="primary small" tabindex="-1">Open</button></div>
</div>`);
}
function libraryPage() {
  const ex = pageData.exercises || [];
  const muscles = ['All', 'Chest', 'Back', 'Shoulders', 'Arms', 'Legs', 'Glutes', 'Core', 'Cardio', 'Full Body'];
  return shell(`${pageHeader('Exercise library', 'Technique, mistakes and alternatives for ${ex.length} movements.')}
<div class="search">⌕ <input id="lib-search" placeholder="Search exercises..."/></div><button class="primary small" data-action="customExercise" style="margin:10px 0">＋ Add Custom Exercise</button>
<div class="tabs" id="lib-tabs">${muscles.map((m, i) => `<button class="${i === 0 ? 'active' : ''}" data-muscle="${m}">${m}</button>`).join('')}</div>
<div class="lib-grid">${ex.length ? ex.map(e => `<article class="lib-card" data-action="exerciseDetail" data-id="${e.id}">
  <div class="lib-photo" style="background-image:url('${exerciseImage(e.name)}')"><span class="lib-muscle">${escapeHtml(e.muscle)}</span></div><h3>${escapeHtml(e.name)}</h3>
  <p>${escapeHtml(e.equipment)} · ${escapeHtml(e.difficulty)}</p>
  ${formGuide(e.name, true)}
</article>`).join('') : emptyState('🏋', 'No exercises found', 'Try a different muscle group or search.')}</div>`);
}
function coachPage() {
  const chat = pageData.coachChat || [];
  const convs = pageData.aiConversations || [];
  const ai = pageData.aiStatus || {};
  const brain = ai.configured
    ? `<span class="ai-status-chip live" title="Real LLM via Groq is answering"><i></i>GROQ · ${escapeHtml((ai.model || '').split('/').pop())} ONLINE</span>`
    : `<span class="ai-status-chip demo" title="Set GROQ_API_KEY on the server to enable the full model"><i></i>BUILT-IN COACH</span>`;
  const msgs = (chat.length || pageData.coachTyping) ? chat.map(m => {
    const mine = m.role === 'user';
    const shared = m.shared ? ' <span class="pill ghost" style="font-size:9px;padding:1px 7px">SHARED</span>' : '';
    return `<div class="ai-msg ${mine ? 'user' : 'coach'}"><span class="ai-ava ${mine ? 'me' : ''}">${mine ? escapeHtml(String(me().name || 'You').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase()) : '✦'}</span><p>${mdLite(m.content)}${shared}</p></div>`;
  }).join('') + (pageData.coachTyping ? `<div class="ai-msg coach"><span class="ai-ava">✦</span><p class="ai-typing"><span></span><span></span><span></span> thinking…</p></div>` : '')
    : `<div class="ai-welcome"><span class="ai-ava big">✦</span><h3>Hey ${escapeHtml(String(me().name || 'there').split(' ')[0])} — I'm your FITVERSE coach.</h3><p>I know your training, nutrition, health data and goals. Ask me anything.</p></div>`;
  const convItem = c => `<div class="conv-item ${String(c.id) === String(pageData.coachConvId || '') ? 'sel' : ''}" data-action="aiOpenConv" data-id="${c.id}" role="button"><div class="ci-title">${escapeHtml(c.title || 'Coach chat')}${c.pinned ? '<span class="ci-pin"> 📌</span>' : ''}<small>${escapeHtml(String(c.created_at || '').slice(0, 10))}</small></div><div class="ci-ops"><button title="Pin / unpin" data-action="aiPinChat" data-id="${c.id}">📌</button><button title="Rename" data-action="aiRenameChat" data-id="${c.id}">✎</button><button title="Share with a friend" data-action="aiShareChat" data-id="${c.id}">↗</button><button class="ci-del" title="Delete chat" data-action="aiDeleteChat" data-id="${c.id}">🗑</button></div></div>`;
  const html = shell(`${pageHeader('FITVERSE AI', 'Your 24/7 coach — save, pin, rename and share chats with friends.')}
<section class="ai-chat-full" id="ai-chat"><div class="ai-msgs" id="ai-msgs">${msgs}</div>
<div class="ai-chips"><button data-action="aiNewChat">＋ New chat</button><button data-action="coachAsk" data-q="What workout should I do today?">🏋 Today's workout</button><button data-action="coachAsk" data-q="Make me an indian diet plan">🍛 Indian diet plan</button><button data-action="coachAsk" data-q="How is my blood pressure and sugar?">🩺 BP & sugar</button><button data-action="generateWorkout">✦ Generate workout</button><button data-action="weeklyReview">📈 Weekly recap</button></div>
<form class="ai-inputbar" id="coach-form"><input placeholder="Message FITVERSE AI…" maxlength="500" autocomplete="off" required/><button type="submit" aria-label="Send">➤</button></form></section>
<aside class="conv-side"><div class="conv-side-head"><b>SAVED CHATS</b>${brain}<button class="outline small" data-action="aiNewChat">＋ New</button></div>${convs.length ? convs.map(convItem).join('') : '<p class="loading">No saved chats yet — send your first message and it lands here.</p>'}</aside>`);
  // Land at the latest message like ChatGPT — never at the top of history.
  requestAnimationFrame(() => { const m = $('#ai-msgs'); if (m) m.scrollTop = m.scrollHeight; });
  return html;
}
// Friends list helper with pageData cache (used by every invite/share picker).
async function getFriends() {
  if (pageData.friends && pageData.friends.length) return pageData.friends;
  try { const d = await api('/api/friends'); pageData.friends = d.items || []; } catch (_) { pageData.friends = []; }
  return pageData.friends;
}
// Share an AI conversation (or DM) picker: sends a readable copy into Messages.
async function shareChatModal(convId) {
  let friends = (pageData.friends && pageData.friends.length ? pageData.friends : null);
  if (!friends) { try { friends = (await api('/api/friends')).items || []; pageData.friends = friends; } catch (_) { friends = []; } }
  if (!friends.length) { toast('Add a friend first — then you can share chats with them'); return; }
  modal(`<span class="eyebrow">🤝 SHARE CHAT</span><h2>Send this conversation to…</h2><p class="loading">They'll get the full chat in Messages — every reply readable.</p><div class="pick-list">${friends.map(f => `<button data-action="aiShareChat" data-id="${convId}" data-fid="${f.id}">${escapeHtml(f.name)}</button>`).join('')}</div>`);
  bind();
}
function intelligencePage() {
  const d = pageData.intel || {};
  const dna = d.dna || {};
  const scores = dna.scores || {};
  const twin = d.twin || {};
  const debt = d.debt || {};
  const patterns = d.patterns || [];
  const mission = pageData.mission || {};
  const traj = pageData.trajectory || {};
  const sc = dna.scores ? Object.entries(scores) : [];
  const now0 = sc.length ? sc[0] : null;
  // radar polygon points (7 axes, 140px radius, center 160,150)
  const axes = sc.length;
  const R = 128, CX = 160, CY = 142;
  const pt = (i, val) => { const a = (Math.PI * 2 * i / axes) - Math.PI / 2; return [CX + Math.cos(a) * R * val / 100, CY + Math.sin(a) * R * val / 100]; };
  const poly = sc.map(([, v], i) => pt(i, v).map(n => n.toFixed(1)).join(',')).join(' ');
  const grid = [25, 50, 75, 100].map(g => `<polygon points="${sc.map((_, i) => pt(i, g).map(n => n.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="rgba(163,230,53,.14)" stroke-width="1"/>`).join('');
  const spokes = sc.map((_, i) => { const [x, y] = pt(i, 100); return `<line x1="${CX}" y1="${CY}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(163,230,53,.12)"/>`; }).join('');
    const labels = sc.map(([k, v], i) => { const [x, y] = pt(i, 112); const anchor = x < CX - 15 ? 'start' : x > CX + 15 ? 'end' : 'middle'; const tx = anchor === 'start' ? x + 3 : anchor === 'end' ? x - 3 : x; return `<text x="${tx.toFixed(1)}" y="${y.toFixed(1)}" fill="rgba(201,231,255,.66)" font-size="10" text-anchor="${anchor}">${k} ${v}</text>`; }).join('');
  const debtColor = debt.level === 'clear' ? 'var(--lime)' : debt.level === 'low' ? '#facc15' : debt.level === 'moderate' ? '#fb923c' : '#f87171';
  return shell(`${pageHeader('Fitness DNA', 'How you train, decoded from your real activity.')}
<div class="intel-grid">
  <section class="card dna-card">
    <div class="dna-head"><div><span class="eyebrow">🧬 YOUR FITNESS DNA</span><h2>${escapeHtml(dna.personality || 'Evolving')}</h2><p class="muted">Updates automatically as you train, eat, and compete.</p></div><button class="outline small" data-action="shareDna">Share card ↗</button></div>
    <div class="dna-body">
      <div id="dna3d-mount"><div class="dna3d-hud">DRAG YOUR DNA · it never sleeps</div></div>
      <svg viewBox="-10 -20 340 306" class="radar" role="img" aria-label="Fitness DNA radar chart">${grid}${spokes}<polygon points="${poly}" fill="rgba(163,230,53,.22)" stroke="var(--lime)" stroke-width="2"/>${labels}</svg>
      <div class="dna-scores">${sc.map(([k, v]) => `<div class="dna-row"><span>${k}</span><div class="bar"><i style="width:${v}%"></i></div><b>${v}</b></div>`).join('')}</div>
    </div>
    <div class="dna-tags">
      <div><span class="eyebrow">STRENGTHS</span><p>${(dna.strengths || []).map(escapeHtml).join(' · ') || '—'}</p></div>
      <div><span class="eyebrow">AREAS TO IMPROVE</span><p>${(dna.improve || []).map(escapeHtml).join(' · ') || '—'}</p></div>
      <div><span class="eyebrow">CURRENT FOCUS</span><p>${escapeHtml(dna.focus || '—')}</p></div>
    </div>
  </section>
  <section class="card twin-card">
    <span class="eyebrow">🤖 AI FITNESS TWIN</span>
    <h2>Where you are</h2>
    <div class="twin-stats">
      <div><b>${twin.where_now ? twin.where_now.sessions_28d : '—'}</b><small>sessions · 28d</small></div>
      <div><b>${twin.where_now ? twin.where_now.weekly_avg : '—'}</b><small>avg / week</small></div>
      <div><b>${twin.where_now ? twin.where_now.streak : '—'}</b><small>day streak</small></div>
      <div><b>${twin.where_now && twin.where_now.top_lif ? twin.where_now.top_lif.w + 'kg' : '—'}</b><small>${twin.where_now && twin.where_now.top_lif ? escapeHtml(twin.where_now.top_lif.name) : 'top lift'}</small></div>
    </div>
    <div class="twin-block"><span class="eyebrow">WHAT'S HOLDING YOU BACK</span><p>${escapeHtml(twin.holding_back || 'Log a few sessions to unlock analysis.')}</p></div>
    <div class="twin-block"><span class="eyebrow">WHERE YOU COULD GO</span><p>${escapeHtml(twin.where_could_go || '—')}</p></div>
    <div class="twin-block next"><span class="eyebrow">DO THIS NEXT</span><p>${escapeHtml(twin.next || '—')}</p></div>
    <p class="disclaimer">${escapeHtml(twin.disclaimer || '')}</p>
  </section>
  <section class="card traj-card">
    <span class="eyebrow">🔮 TRAJECTORY SIMULATOR</span>
    <h2>What if…</h2>
    <div class="chip-row" id="traj-chips">${[['current', 'Current routine'], ['3days', 'Train 3 d/wk'], ['4days', 'Train 4 d/wk'], ['5days', 'Train 5 d/wk'], ['consistency', 'Improve consistency'], ['cardio', 'More cardio'], ['strength', 'Focus strength']].map(([k, l]) => `<button class="chip ${pageData.trajScenario === k ? 'active' : ''}" data-action="traj" data-id="${k}">${l}</button>`).join('')}</div>
    ${traj.label ? `<div class="traj-result">
      <h3>${traj.horizon_days}-DAY SCENARIO · ${escapeHtml(traj.label)}</h3>
      <div class="traj-rows">
        <div><span>Current consistency</span><b>${traj.current_consistency}%</b><span class="muted">→</span><b class="lime">${traj.projected_consistency}%</b></div>
        <div><span>Weekly sessions</span><b>${traj.weekly_sessions.now}</b><span class="muted">→</span><b class="lime">${traj.weekly_sessions.projected}</b></div>
        <div><span>Est. volume</span><b class="${traj.volume_delta_pct >= 0 ? 'lime' : 'warn'}">${traj.volume_delta_pct >= 0 ? '+' : ''}${traj.volume_delta_pct}%</b></div>
        <div><span>Est. sessions in ${traj.horizon_days}d</span><b>${traj.estimated_sessions}</b></div>
        ${traj.debt_clearance ? `<div><span>Debt</span><b class="lime">${escapeHtml(traj.debt_clearance)}</b></div>` : ''}
      </div>
      <p class="pill ${traj.direction === 'positive' ? 'lime' : 'ghost'}">Trajectory: ${traj.direction}</p>
      <p class="disclaimer">${escapeHtml(traj.disclaimer)}</p>
    </div>` : ''}
  </section>
  <section class="card patterns-card">
    <span class="eyebrow">🧠 PATTERN DETECTOR</span>
    <h2>What we noticed</h2>
    ${patterns.map(p => `<div class="pattern sev-${p.severity}"><div class="pattern-head"><span>${p.icon}</span><h3>${escapeHtml(p.title)}</h3></div><p>${escapeHtml(p.detail)}</p><p class="why"><b>Why it matters:</b> ${escapeHtml(p.why)}</p><p class="fix"><b>Suggested fix:</b> ${escapeHtml(p.fix)}</p></div>`).join('')}
  </section>
  <section class="card debt-card">
    <span class="eyebrow">⚡ FITNESS DEBT</span>
    <div class="debt-top"><div><h2 class="debt-num" style="color:${debtColor}">${debt.debt ?? '—'}</h2><small>session${debt.debt === 1 ? '' : 's'} owed this week</small></div>
    <div class="debt-meta"><div><b>${debt.completed ?? '—'}/${debt.target ?? '—'}</b><small>this week</small></div><div><b>${debt.reduction > 0 ? '-' + debt.reduction : debt.previous_debt || 0}</b><small>${debt.reduction > 0 ? 'reduced from last week' : 'last week'}</small></div></div></div>
    <div class="bar big"><i style="width:${debt.week_progress || 0}%; background:${debtColor}"></i></div>
    <p class="debt-advice">${escapeHtml(debt.advice || '')}</p>
    <p class="disclaimer">Debt encourages steady consistency — never extreme make-up training.</p>
  </section>
  <section class="card mission-card">
    <span class="eyebrow">🎯 MISSION ENGINE</span>
    ${mission.id ? `<div class="mission-live">
      <div class="mission-head"><span class="mission-icon">${mission.icon || '🎯'}</span><div><h3>${escapeHtml(mission.title)}</h3><p>${escapeHtml(mission.description || '')}</p></div><b class="xp-pill">+${mission.reward_xp} XP</b></div>
      <div class="bar big"><i style="width:${Math.min(100, Math.round(100 * (mission.progress || 0) / mission.target))}%"></i></div>
      <p class="muted">${mission.progress || 0} / ${mission.target} this week</p>
      <div class="mission-actions">
        ${mission.status === 'active' ? `<button class="primary small" data-action="missionStart" data-id="${mission.id}">On it — track progress</button>` : ''}
        <button class="outline small" data-action="missionInvite">Invite friend</button>
        <button class="text-btn small" data-action="missionShare">Share mission</button>
        ${mission.invited_friend_id ? `<span class="pill lime">friend invited ✓</span>` : ''}
      </div>
    </div>` : '<p class="muted">Log a workout and your first mission will be forged from your DNA.</p>'}
    ${pageData.missionHistory && pageData.missionHistory.length ? `<div class="mission-hist"><span class="eyebrow">RECENT MISSIONS</span>${pageData.missionHistory.map(h => `<div class="mh-row"><span>${h.icon || '🎯'} ${escapeHtml(h.title)}</span><em class="${h.status}">${h.status === 'completed' ? '✓ done' : escapeHtml(h.status)}</em><b>+${h.reward_xp}</b></div>`).join('')}</div>` : ''}
  </section>
  <section class="card teams-card">
    <span class="eyebrow">🌎 COMMUNITY MISSION ENGINE</span>
    <h2>Team Fitness War</h2>
    ${(pageData.teams || []).map((t, i) => `<div class="team-row ${t.is_mine ? 'mine' : ''}">
      <b class="rank">${String(i + 1).padStart(2, '0')}</b>
      <div class="team-info"><h3>${escapeHtml(t.name)} ${t.is_mine ? '<span class="pill lime">your team</span>' : ''}</h3><p>${t.members} members · top: ${t.top && t.top.length ? escapeHtml(t.top[0].name) : '—'}</p>
      <div class="bar"><i style="width:${Math.max(4, Math.round(100 * t.team_xp / Math.max(1, (pageData.teams[0] || t).team_xp)))}%"></i></div></div>
      <div class="team-xp"><b>${(t.team_xp || 0).toLocaleString()}</b><small>team XP</small></div>
      ${t.is_mine ? '' : `<button class="outline small" data-action="teamJoin" data-id="${t.id}">Join</button>`}
    </div>`).join('')}
    <p class="disclaimer">Every legitimate XP you earn — workouts, challenges, missions — fuels your team's war score.</p>
  </section>
</div>`);
}

function weeklyReviewPage() {
  const r = pageData.review || {};
  return shell(`${pageHeader('Weekly recap', r.week || 'Your FITVERSE week in review.')}
<section class="review-card big"><div class="review-head"><span class="pill lime">✦ YOUR WEEKLY RECAP</span><h3>${escapeHtml(r.week || '')}</h3><button class="more" data-action="shareRecap">↗</button></div>
<div class="review-grid">
<div><b>${r.workouts || 0}</b><small>workouts</small></div><div><b>${(r.calories_burned || 0).toLocaleString()}</b><small>kcal burned</small></div>
<div><b>${r.avg_protein || 0}g</b><small>avg protein</small></div><div><b>${r.new_prs || 0}</b><small>new PRs</small></div>
<div><b>${r.consistency || 0}%</b><small>consistency</small></div><div><b>${r.streak || 0}</b><small>day streak</small></div></div>
${r.best_exercise ? `<p class="loading">Best exercise: <b>${escapeHtml(r.best_exercise)}</b> · Meals logged ${r.days_meals_logged || 0}/7 days</p>` : ''}
<div class="review-tips">${r.ai_summary ? `<p class="review-ai">✦ ${escapeHtml(r.ai_summary)}</p>` : ''}${(r.suggestions || []).map(s => `<p>💡 ${escapeHtml(s)}</p>`).join('')}</div></section>
<div class="hero-actions"><button class="primary" data-action="shareRecap">Share recap card</button><button class="outline" data-page="coach">Ask the coach</button></div>`);
}
function lineChart(points, unit) {
  if (points.length < 2) return '';
  const w = 640, h = 180, pad = 34;
  const ys = points.map(p => p.y);
  const min = Math.min(...ys) - 1, max = Math.max(...ys) + 1;
  const sx = i => pad + i * (w - pad * 2) / (points.length - 1);
  const sy = v => h - pad - (v - min) / Math.max(0.1, max - min) * (h - pad * 2);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
  const dots = points.map((p, i) => `<circle cx="${sx(i)}" cy="${sy(p.y)}" r="4" class="chart-dot"><title>${p.x}: ${p.y}${unit}</title></circle>`).join('');
  const labels = points.map((p, i) => i % Math.ceil(points.length / 6) === 0 ? `<text x="${sx(i)}" y="${h - 8}" class="chart-label">${p.x}</text>` : '').join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Trend chart" class="trend-svg"><path d="${path}" class="chart-line" fill="none"/>${dots}${labels}</svg><p class="loading">Range: ${min.toFixed(1)}–${max.toFixed(1)} ${unit}</p>`;
}
function business() {
  const myBookings = pageData.bookings.length;
  return shell(`${pageHeader('Business dashboard', 'A focused view of your fitness business and its event reach.')}
<div class="admin-grid"><article><span class="eyebrow">PROFILE VIEWS</span><b>1,284</b><small>Last 30 days</small></article><article><span class="eyebrow">EVENT BOOKINGS</span><b>${myBookings}</b><small>Bookings via FITVERSE</small></article><article><span class="eyebrow">BUSINESSES</span><b>${pageData.businesses.length}</b><small>On the platform</small></article><article><span class="eyebrow">ENGAGEMENT</span><b>8.4%</b><small>Healthy growth</small></article></div><section class="section-head"><div><span class="eyebrow">BUSINESSES</span><h2>Local fitness partners</h2></div><button class="create-inline" data-action="createBusinessEvent">＋ Create event</button></section><table class="data-table"><thead><tr><th>BUSINESS</th><th>CATEGORY</th><th>LOCATION</th><th>RATING</th></tr></thead><tbody>${pageData.businesses.map(row => `<tr><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.category)}</td><td>${escapeHtml(row.location_label)}</td><td>★ ${row.rating}</td></tr>`).join('') || '<tr><td colspan="4">Loading business data…</td></tr>'}</tbody></table>`);
}
function dailyCompanionCard() {
  const d = pageData.daily;
  if (!d || !d.recommendation) return '';
  const rec = d.recommendation;
  return `<section class="daily-companion" id="daily-companion"><div class="dc-head"><span class="pill lime">✦ AI COMPANION</span><b>${escapeHtml(d.greeting || 'Hello')}</b>${d.streak ? `<span class="dc-streak">🔥 ${d.streak} day streak</span>` : ''}</div>
  ${d.lines.map(l => `<p class="dc-line">${escapeHtml(l)}</p>`).join('')}
  ${d.ai_tip ? `<p class="dc-line ai-tip">✦ <b>Tip of the day:</b> ${mdLite(d.ai_tip)}</p>` : ''}
  <div class="dc-rec"><b>${escapeHtml(rec.title)}</b><p>${escapeHtml(rec.why)}</p></div>
  <div class="dc-actions"><button class="primary small" data-action="dailyPlan">Build my plan</button><a class="outline small" href="#" data-action="dailyCoach" style="text-decoration:none;display:inline-block">Ask the coach</a></div></section>`;
}
function mdLite(t) {
  return escapeHtml(t)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^#{1,4}\s*(.+)$/gm, '<b>$1</b>')
    .replace(/^[-*]\s+(.+)$/gm, '• $1')
    .replace(/\n/g, '<br/>');
}

function indianDietCard(plan) {
  if (!plan || !plan.items) return '';
  return `<div class="meal-plan-grid" id="indian-diet">${plan.items.map(it => `<div class="meal-plan-row"><span class="mp-ico">${it.meal === 'Breakfast' ? '🌅' : it.meal === 'Lunch' ? '🍛' : it.meal === 'Snacks' ? '🥜' : '🌙'}</span><div><b>${escapeHtml(it.meal)} · ~${it.kcal} kcal · ${it.protein_g}g protein</b><p>${escapeHtml(it.food)}</p></div></div>`).join('')}</div>
  <div class="hero-actions" style="margin:0 0 18px"><button class="outline small" data-action="indianDietRefresh">✦ Regenerate from my vitals</button><button class="outline small" data-page="connectHealth">🩺 Update BP / sugar</button></div>`;
}

// Vitals card: BP + sugar trend with color-coded status (feeds profile + health page).
function vitalsStrip() {
  const s = pageData.healthSuggest;
  const f = (s && s.suggestion && s.suggestion.facts) || {};
  const bp = f.avg_bp, sg = f.avg_sugar, age = f.age;
  if (!bp && !sg && !(age >= 30)) return '';
  const pill = (label, val, warnAt) => val ? `<span class="v-pill ${val >= warnAt ? 'warn' : 'good'}">${label} ${val}${label.includes('BP') ? '' : ' mg/dL'}</span>` : '';
  return `<div class="vitals-strip"><span>🩺</span><div><b>Your vitals, tracked</b><p>${bp || sg ? '7-day averages from your logged readings — your workouts, diet plans and AI coach adapt to these automatically.' : 'You\'re 30+ — log blood pressure and fasting sugar below (or import them). FITVERSE then tunes workouts, Indian diet plans and coaching around them.'}</p>
  <div>${pill('🩺 BP', bp, 140)}${pill('🩸 Sugar', sg, 126)}${age >= 30 ? '<span class="v-pill good">Age ' + age + ' · vitals mode ON</span>' : ''}</div></div>
  <div class="vs-actions"><button class="outline small" data-action="gotoMetrics">＋ Log BP / sugar</button><button class="outline small" data-action="indianDiet">🍛 BP/sugar diet</button></div></div>`;
}

function profileVitalsCard() {
  const s = pageData.healthSuggest;
  const f = (s && s.suggestion && s.suggestion.facts) || {};
  const age = f.age || ((pageData.mySettings || {}).age || 0);
  const bp = f.avg_bp, sg = f.avg_sugar;
  if (age < 30 && !bp && !sg) return '';
  const meta = [bp ? 'BP ' + bp : '', sg ? 'Sugar ' + sg + ' mg/dL' : '', age >= 30 ? 'age ' + age : ''].filter(Boolean).join(' · ');
  return `<a class="vitals-strip" data-page="connectHealth" role="button" style="cursor:pointer;text-decoration:none"><span>🩺</span><div><b>${bp || sg ? 'Vitals tracked' : 'Vitals mode available'}</b><p>${meta ? meta + ' — tap to update readings; your plan adapts instantly.' : 'Add your readings once — your plan adapts instantly.'}</p></div><span class="outline small" style="padding:8px 12px">Open</span></a>`;
}

function healthBrainCard(ins) {
  if (!ins) return `<div class="hc-rec"><b>⚡ Health Brain warming up…</b><p>Analyzing your stored data.</p></div>`;
  if (ins.insufficient) return `<div class="hc-rec"><b>🧠 No data to analyze yet</b><p>${escapeHtml(ins.need || 'Track a few days of metrics first.')}</p></div>`;
  const st = ins.stats || {};
  const badge = ins.engine === 'groq'
    ? `<span class="ai-status-chip live"><i></i>GROQ · instant analysis</span>`
    : `<span class="ai-status-chip demo"><i></i>BUILT-IN ANALYSIS — add GROQ_API_KEY for full AI</span>`;
  const facts = `<div class="hc-stats wide"><div><b>${st.workouts_7d ?? 0}</b><small>workouts (7d)</small></div><div><b>${st.kcal_burned_7d ?? 0}</b><small>kcal burned</small></div><div><b>${st.km_7d ?? 0} km</b><small>distance (7d)</small></div><div><b>${st.steps_avg ?? 0}</b><small>avg steps</small></div><div><b>${st.sleep_avg_min ? Math.round(st.sleep_avg_min / 60 * 10) / 10 + 'h' : '—'}</b><small>avg sleep</small></div><div><b>${st.resting_hr_avg || '—'}</b><small>resting HR</small></div></div>`;
  return `${badge}${facts}${ins.ai ? `<div class="hc-rec"><b>🧠 Health Brain says</b><p>${mdLite(ins.ai)}</p></div>` : ''}`;
}

function connectHealth() {
  const insights = pageData.healthInsights || null;
  const integ = pageData.healthIntegrations || { items: [] };
  const ov = pageData.healthOverview || {};
  const cardio = pageData.healthCardio || {};
  const rec = pageData.healthRec || {};
  const gf = integ.items.find(i => i.provider === 'google_fit') || {};
  const hc = integ.items.find(i => i.provider === 'health_connect') || { connected: false };
  const s = ov.today || {};
  const week = ov.week || {};
  const weekRow = (label, val, sub) => `<div class="hc-week-row"><span>${label}</span><b>${val}</b><small>${sub}</small></div>`;
  const cardioBody = cardio.insufficient
    ? `<div class="hc-empty"><span>🫀</span><b>Not enough data yet</b><p>${escapeHtml(cardio.need || 'Log cardio workouts with distance to unlock pace and consistency analysis.')}</p></div>`
    : `<div class="hc-stats"><div><b>${cardio.sessions ?? '—'}</b><small>sessions (28d)</small></div><div><b>${cardio.total_km ?? '—'} km</b><small>total distance</small></div><div><b>${cardio.avg_pace_min_km ? cardio.avg_pace_min_km + ' min/km' : '—'}</b><small>avg pace</small></div><div><b>${cardio.pace_trend_pct != null ? (cardio.pace_trend_pct > 0 ? '▲ ' : '▼ ') + Math.abs(cardio.pace_trend_pct) + '%' : '—'}</b><small>pace trend</small></div><div><b>${cardio.avg_hr ? cardio.avg_hr + ' bpm' : '—'}</b><small>avg heart rate</small></div><div><b>${cardio.consistency_days ?? '—'}</b><small>active days</small></div></div>
       ${cardio.typical_gap_days ? `<p class="hc-note">Typical gap between cardio sessions: ${cardio.typical_gap_days} days · sports: ${escapeHtml((cardio.sports || []).join(', '))}</p>` : ''}`;
  return shell(`${pageHeader('Connect Health Data', 'Bring your real training data into FITVERSE — always your choice, always private.')}
${vitalsStrip()}
<section class="hc-hero"><div><span class="pill lime">🔒 PRIVATE BY DESIGN</span><h2>Your data, <em>your control.</em></h2><p>Health data stays on your account, is never public, and is used only for your own insights. Disconnect anytime to delete synced data.</p></div></section>
<section class="hc-connections">
  <article class="hc-card"><div class="hc-card-head"><span class="hc-logo">📥</span><div><h3>Google Takeout import</h3><p>The reliable way to bring your full Google Fit history in — no sign-in, no OAuth, works instantly on desktop and mobile.</p></div><span class="hc-state on">Works now</span></div>
    <div class="hc-actions"><label class="hc-import-btn">📎 Choose Takeout file(s)<input id="takeout-input" type="file" accept=".json" multiple style="display:none"/></label><button class="outline small" data-action="sampleTakeout">🧪 Try our sample file</button></div>
    <small class="hc-scope">From <span class="code">takeout.google.com</span> → select only <b>Fit</b> → export → unzip → pick the .json files. No account yet? Tap the sample — it imports real demo days so you can see the AI work.</small>
    <p class="hc-note" id="takeout-status"></p>
  </article>
  <article class="hc-card"><div class="hc-card-head"><span class="hc-logo">🤖</span><div><h3>Health Connect (Android)</h3><p>Steps, sleep, heart rate, hydration and more — from your phone's health hub.</p></div>${hc.connected ? '<span class="hc-state on">Imported data active</span>' : '<span class="hc-state">Import available</span>'}</div>
    <div class="hc-setup">
      <p><b>Honest note:</b> Health Connect is a device-local Android API — a website can't read it directly. FITVERSE never fakes health data, so here's what genuinely works today:</p>
      <ol class="hc-steps">
        <li><b>Import your export:</b> on your phone open Health Connect → ⚙ Settings → <b>Export data</b> (or use Google Takeout → Fit), then use the importer below. Everything lands in <i>your</i> account.</li>
        <li><b>Import your Google history</b> with the Takeout importer (card above) — no sign-in needed.</li>
        <li><b>Log manually</b> in the Daily metrics form below — it feeds the same insights.</li>
      </ol>
      <p class="hc-note">A future FITVERSE Android app can sync Health Connect automatically. ${hc.imported_days ? `You currently have <b>${hc.imported_days}</b> imported day${hc.imported_days == 1 ? '' : 's'} and <b>${hc.imported_activities || 0}</b> activit${hc.imported_activities == 1 ? 'y' : 'ies'}.` : 'No imported data yet.'}</p>
    </div>
    <div class="hc-actions"><label class="hc-import-btn">📎 Import health data file<input id="hc-import-input" type="file" accept=".json,.zip,.csv" multiple style="display:none"/></label>${hc.imported_days || hc.imported_activities ? '<button class="outline small" data-action="hcRemoveData">Remove imported data</button>' : ''}</div>
    <p class="hc-note" id="hc-import-status"></p>
  </article>
</section>
<section class="hc-section"><div class="section-head"><div><span class="eyebrow">UNIFIED VIEW</span><h2>Your fitness data today</h2></div></div>
  <div class="hc-stats wide"><div><b>${ov.streak ?? 0}</b><small>day streak</small></div><div><b>${week.sessions ?? 0}</b><small>workouts this week</small></div><div><b>${week.kcal ?? 0}</b><small>kcal burned (7d)</small></div><div><b>${s.kcal ?? 0}<em>/${s.kcal_target || '—'}</em></b><small>kcal today</small></div><div><b>${s.protein ?? 0}<em>/${s.protein_target || '—'}g</em></b><small>protein today</small></div><div><b>${s.water_ml != null ? (s.water_ml / 1000).toFixed(1) : '—'}<em>/${s.water_target_ml ? (s.water_target_ml / 1000).toFixed(1) : '—'}L</em></b><small>hydration</small></div></div>
</section>
<section class="hc-section"><div class="section-head"><div><span class="eyebrow">CARDIO ANALYSIS</span><h2>Heart & legs, in numbers</h2></div><small class="hc-note">From your logged distance workouts</small></div>
  ${cardioBody}
</section>
<section class="hc-section"><div class="section-head"><div><span class="eyebrow">GROQ HEALTH BRAIN</span><h2>Instant AI analysis of YOUR data</h2></div></div>
  ${healthBrainCard(insights)}
</section>
<section class="hc-section"><div class="section-head"><div><span class="eyebrow">SMART RECOMMENDATION</span><h2>Today's smart suggestion</h2></div></div>
  <div class="hc-rec"><b>${escapeHtml(rec.title || 'Log a workout to unlock')}</b><p>${escapeHtml(rec.why || '')}</p>${(rec.tips || []).map(t => `<p class="hc-tip">💡 ${escapeHtml(t)}</p>`).join('')}</div>
</section>
<section class="hc-section"><div class="section-head"><div><span class="eyebrow">MANUAL LOG</span><h2>Daily metrics</h2></div></div>
  <form class="hc-form" id="metrics-form"><label>Steps<input name="steps" type="number" min="0" placeholder="8000"/></label><label>Weight (kg)<input name="weight_kg" type="number" step="0.1" placeholder="68.5"/></label><label>Sleep (min)<input name="sleep_min" type="number" min="0" placeholder="450"/></label><label>Resting HR<input name="resting_hr" type="number" min="30" max="120" placeholder="62"/></label><label>-blood pressure (systolic)<input name="blood_pressure" type="number" min="60" max="260" placeholder="128"/></label><label>-blood sugar, fasting (mg/dL)<input name="blood_sugar" type="number" min="30" max="600" placeholder="110"/></label><button class="primary">Save today</button></form>
</section>`);
}
function businessChannel() {
  const b = pageData.bizDetail || {};
  if (!b.id) return shell(`${pageHeader('Business', 'Loading…')}<p class="loading">Loading business…</p>`);
  const mapHtml = (b.lat && b.lng)
    ? `<div id="biz-map" class="biz-map" data-lat="${b.lat}" data-lng="${b.lng}" data-name="${escapeHtml(b.name)}"></div><a class="outline small" href="https://www.openstreetmap.org/?mlat=${b.lat}&mlon=${b.lng}#map=16/${b.lat}/${b.lng}" target="_blank" rel="noopener">🧭 Open directions</a>`
    : '';
  const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const hoursRows = b.hours && Object.keys(b.hours).length
    ? DOW.map((d, i) => b.hours[String(i)] ? `<div class="biz-hours-row"><span>${d}</span><b>${b.hours[String(i)][0]} – ${b.hours[String(i)][1]}</b></div>` : '').join('')
    : (b.hours_note ? `<p class="biz-hours-note">◷ ${escapeHtml(b.hours_note)}</p>` : '');
  const products = (b.products || []).map(p => `<article class="biz-product"><div class="biz-product-img" style="background-image:url('${p.image || 'img/workout.jpg'}')"></div><div><h4>${escapeHtml(p.name)}</h4><p>${escapeHtml(p.description)}</p><div class="biz-product-row">${p.price ? `<b>${escapeHtml(p.price)}</b>` : ''}${p.link ? `<a href="${escapeHtml(p.link)}" target="_blank" rel="noopener">View →</a>` : ''}</div></div></article>`).join('');
  const photos = (b.photos || []).map(p => `<div class="biz-photo-thumb" style="background-image:url('${p}')"></div>`).join('');
  const posts = (b.channel_posts || []).map(p => `<article class="biz-post"><p>${escapeHtml(p.body)}</p>${p.media_url ? (p.media_type === 'video' ? `<video src="${p.media_url}" controls></video>` : `<img src="${p.media_url}" alt=""/>`) : ''}<small>${escapeHtml(p.author_name || '')} · ${timeShort(p.created_at)}</small></article>`).join('') || '<p class="muted">No posts from this business yet.</p>';
  const ownerTools = b.is_owner ? `<div class="biz-owner-tools"><button class="primary small" data-action="bizEdit" data-id="${b.id}">Edit profile</button><button class="outline small" data-action="bizAddProduct" data-id="${b.id}">＋ Product</button><button class="outline small" data-action="bizAddPhoto" data-id="${b.id}">📷 Photo</button><button class="outline small" data-action="bizSetHours" data-id="${b.id}">◷ Hours</button><button class="outline small" data-action="bizCompose" data-id="${b.id}">✎ Write post</button></div>` : '';
  return shell(`<div class="biz-channel-hero photo" style="background-image:url('${b.cover || 'img/' + (b.photo || 'gym.jpg')}')">
    <div class="biz-channel-head"><span class="biz-channel-logo" style="background-image:url('${b.logo || ''}')">${b.logo ? '' : '🏋'}</span>
    <div><span class="pill lime">FITVERSE BUSINESS${b.verified ? ' · VERIFIED' : ''}</span><h2>${escapeHtml(b.name)}</h2><p>${escapeHtml(b.tagline || b.category + ' · ' + (b.location_label || ''))}</p></div>
    <div class="biz-channel-actions"><button class="${b.is_following ? 'outline' : 'primary'}" data-action="bizFollow" data-id="${b.id}">${b.is_following ? 'Following ✓' : 'Follow'}</button><small>${b.followers ?? 0} followers</small></div></div></div>
  ${ownerTools}
  <section class="biz-channel-grid">
    <div class="biz-channel-main">
      <span class="eyebrow">ABOUT</span><p>${escapeHtml(b.description)}</p>
      ${b.website ? `<a class="biz-link" href="${escapeHtml(b.website)}" target="_blank" rel="noopener">🌐 ${escapeHtml(b.website)}</a>` : ''}
      ${b.phone ? `<a class="biz-link" href="tel:${escapeHtml(b.phone)}">📞 ${escapeHtml(b.phone)}</a>` : ''}
      ${b.address ? `<p class="biz-link">⌖ ${escapeHtml(b.address)}</p>` : ''}
      ${hoursRows ? `<span class="eyebrow" style="margin-top:14px">OPENING HOURS</span>${hoursRows}` : ''}
      <span class="eyebrow" style="margin-top:14px">POSTS</span>
      ${ownerTools ? '' : ''}
      ${posts}
      ${photos ? `<span class="eyebrow" style="margin-top:14px">PHOTOS</span><div class="biz-photos">${photos}</div>` : ''}
    </div>
    <aside class="biz-channel-side">
      ${products ? `<span class="eyebrow">PRODUCTS & SERVICES</span>${products}` : ''}
      ${mapHtml ? `<span class="eyebrow">LOCATION</span>${mapHtml}` : (b.address ? `<span class="eyebrow">LOCATION</span><p class="muted">Map coming soon — address: ${escapeHtml(b.address)}</p>` : '')}
    </aside>
  </section>`);
}
function admin() {
  const s = pageData.stats || {};
  return shell(`${pageHeader('Admin dashboard', 'Moderation and platform health for the FITVERSE demo.')}
<div class="admin-grid"><article><span class="eyebrow">USERS</span><b>${s.users ?? '…'}</b><small>Registered</small></article><article><span class="eyebrow">ACTIVITIES</span><b>${s.activities ?? '…'}</b><small>Scheduled</small></article><article><span class="eyebrow">COMMUNITIES</span><b>${s.communities ?? '…'}</b><small>Active groups</small></article><article><span class="eyebrow">EVENTS</span><b>${s.events ?? '…'}</b><small>Upcoming</small></article><article><span class="eyebrow">POSTS</span><b>${s.posts ?? '…'}</b><small>Shared</small></article><article><span class="eyebrow">BOOKINGS</span><b>${s.bookings ?? '…'}</b><small>Tickets sold</small></article><article><span class="eyebrow">CHALLENGES</span><b>${s.challenges ?? '…'}</b><small>All time</small></article><article><span class="eyebrow">MESSAGES</span><b>${s.messages ?? '…'}</b><small>Exchanged</small></article></div><section class="leaderboard"><div><span class="eyebrow">MODERATION QUEUE</span><h2>Reports</h2>${pageData.reports.length ? pageData.reports.map(r => `<div class="notice"><b>${escapeHtml(r.target_type)} #${r.target_id} — ${escapeHtml(r.reason)}</b><p><button class="outline" data-action="resolveReport" data-id="${r.id}">Resolve</button></p></div>`).join('') : '<p>No open reports in the demo database.</p>'}</div><div class="level-card"><span>SAFE BY DESIGN</span><h3>Privacy aware</h3><p>Only approximate public activity locations are displayed.</p></div></section>`);
}
function reels() {
  const items = pageData.reels || [];
  const tab = state.prTab || 'reels';
  const postsTab = `<section class="composer-bar" data-action="createPost" role="button" tabindex="0">${photoAvatar(me().name, 1)}<span>Share a workout, progress or a reel…</span><button class="primary small" tabindex="-1">Post</button></section>`;
  const reelsGrid = `<div class="reels-wrap">${items.length ? items.map((r, i) => `
<div class="reel" data-reel="${r.id}">
  ${r.media === 'video' && r.photo
    ? `<video class="reel-video" src="${r.photo}" loop playsinline controls preload="metadata"></video>`
    : `<div class="reel-photo" style="background-image:url('${String(r.photo).startsWith('uploads/') ? '' : 'img/'}${r.photo}')"></div>`}
  <div class="reel-overlay">
    <div class="reel-author" data-action="athlete" data-id="${r.author_id}">${photoAvatar(r.name, r.author_id)}<div><strong>${escapeHtml(r.name)}</strong><small>@${escapeHtml(r.username || '')}</small></div></div>
    <p class="reel-caption">${escapeHtml(r.body)}</p>
  </div>
  <div class="reel-side">
    <button class="reel-act ${r.liked ? 'on' : ''}" data-action="like" data-id="${r.id}" data-src="reels"><span>${r.liked ? '♥' : '♡'}</span><small>${r.likes}</small></button>
    <button class="reel-act" data-action="comment" data-id="${r.id}"><span>◌</span><small>${r.comments}</small></button>
    <button class="reel-act" data-action="share" data-id="${r.id}"><span>↗</span><small>Share</small></button>
  </div>
</div>`).join('') : emptyState('🎬', 'No reels yet', 'Create the first reel — pick Reel in the composer and add a background.', 'createReel', 'Create a reel')}</div>`;
  const postsGrid = `${pageData.feed.length ? pageData.feed.map(postCard).join('') : emptyState('📭', 'No posts yet', 'Share your first update — training, meals, questions, wins.', 'createPost', 'Create a post')}`;
  return shell(`${pageHeader('Posts & Reels', 'The FITVERSE feed — updates and short-form reels.')}
<div class="tabs" id="pr-tabs">
  <button class="${tab === 'reels' ? 'active' : ''}" data-prtab="reels">Reels</button>
  <button class="${tab === 'posts' ? 'active' : ''}" data-prtab="posts">Posts</button>
  <button class="${tab === 'ai' ? 'active' : ''}" data-prtab="ai">✦ For you</button>
</div>
${tab === 'ai' ? aiIdeasSection('posts') : tab === 'reels' ? reelsGrid : `${postsTab}${postsGrid}`}`);
}
// FITVERSE 6.0 cross-panel brain: AI next-actions linking feed ↔ workout ↔ nutrition ↔ health.
function aiIdeasSection(page) {
  const s = pageData.healthSuggest;
  const g = (s && s.suggestion) || {};
  const f = g.facts || {};
  const bp = f.avg_bp, sg = f.avg_sugar;
  const wr = (pageData.workouts || [])[0];
  const last = wr ? `last session “${wr.title}”` : 'your first session';
  const items = [
    { icon: '🏋', t: 'Train what the data says', d: `${g.title || 'Build today\'s session'} — tuned to ${last}${bp ? ' and your BP' : ''}.`, act: 'quickAction', qa: 'workout', cta: 'Open' },
    { icon: '🍛', t: 'Eat for your numbers', d: `${bp || sg ? 'BP/sugar-aware Indian plate plan is ready.' : 'Get an Indian diet plan built from your targets.'}`, act: 'indianDiet', cta: 'Plan' },
    { icon: '⚔️', t: 'Challenge a friend', d: 'Head-to-head on steps, km or sessions — loser buys the protein.', act: 'quickAction', qa: 'challenges', cta: 'Start' },
    { icon: '🧬', t: 'See your Fitness DNA', d: 'Seven scores decoded from your real training, food and social activity.', act: 'quickAction', qa: 'dna', cta: 'View' },
  ];
  if (bp || sg || f.age >= 30) items.splice(1, 0, { icon: '🩺', t: 'Check your vitals trend', d: `${bp ? 'BP ' + bp : ''}${bp && sg ? ' · ' : ''}${sg ? 'Sugar ' + sg + ' mg/dL' : ''} — log today's reading to keep the AI sharp.`, act: 'quickAction', qa: 'health', cta: 'Log' });
  return `<div class="ai-ideas">${items.map(i => `<div class="ai-idea-row" role="button" data-action="${i.act}" ${i.qa ? `data-qa="${i.qa}"` : ''}><span>${i.icon}</span><div><b>${i.t}</b><small>${i.d}</small></div><button class="primary small" tabindex="-1">${i.cta}</button></div>`).join('')}</div>`;
}
function businesses() {
  const mine = pageData.myBusinesses || [];
  const cats = ['All', ...new Set((pageData.businesses || []).map(b => b.category).filter(Boolean))];
  const active = state.bizCat || 'All';
  const q = (state.bizQuery || '').toLowerCase();
  const list = (pageData.businesses || []).filter(b => (active === 'All' || b.category === active) && (!q || (b.name + ' ' + b.category + ' ' + (b.location_label || '')).toLowerCase().includes(q)));
  return shell(`${pageHeader('Businesses', 'Gyms, studios, stores and coaches — the FITVERSE business ecosystem.')}
<div class="community-hero"><span class="pill lime">LOCAL PARTNERS</span><h2>Where the city <em>trains.</em></h2><p>Real businesses, real owners, real reviews. Own one? Put it on the map.</p>
  <div class="biz-cta"><button class="primary" data-action="bizCreate">🏪 Add your business</button>${mine.length ? `<button class="outline" data-action="bizOpenMine" data-id="${mine[0].id}">My business dashboard</button>` : ''}</div></div>
<div class="ai-ideas"><div class="ai-idea-row" role="button" data-action="quickAction" data-qa="workout"><span>🏋</span><div><b>Pick a venue, build the session</b><p style="margin:2px 0 0;color:var(--fv-mut);font-size:11px">Choose where you train, then let the AI design today's workout for it.</p></div><button class="primary small" tabindex="-1">Start</button></div><div class="ai-idea-row" role="button" data-action="indianDiet"><span>🍛</span><div><b>Fuel around your training</b><p style="margin:2px 0 0;color:var(--fv-mut);font-size:11px">An Indian plate plan matched to your calories and vitals.</p></div><button class="primary small" tabindex="-1">Plan</button></div></div>
<div class="biz-filters"><div class="tabs" id="biz-cats">${cats.map(c => `<button class="${c === active ? 'active' : ''}" data-bcat="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}</div>
<div class="search"><input id="biz-search" placeholder="Search gyms, stores, coaches…" value="${escapeHtml(state.bizQuery || '')}"/><span>⌕</span></div></div>
<div class="biz-grid">${list.map(b => `
<article class="biz-card" data-business="${b.id}">
  <div class="biz-photo photo" style="background-image:url('${b.cover || 'img/' + (b.photo || 'workout.jpg')}')"><span>${escapeHtml(b.category)}</span></div>
  <div class="biz-body">
    <h3>${escapeHtml(b.name)}${b.owner_id ? ' <i class="biz-owned">★ owned</i>' : ''}</h3>
    ${b.tagline ? `<p class="biz-tagline">${escapeHtml(b.tagline)}</p>` : ''}
    <p>⌖ ${escapeHtml(b.location_label)}</p>
    <div class="biz-row"><span class="stars" title="${b.rating}">${'★'.repeat(Math.round(b.rating))}${'☆'.repeat(5 - Math.round(b.rating))}</span><b>${b.rating}</b><button class="outline small" data-action="bizOpen" data-id="${b.id}">Open channel</button><button class="outline small" data-action="businessDetail" data-id="${b.id}">Reviews</button></div>
  </div>
</article>`).join('') || `<p class="loading">No businesses match${q ? ' “' + escapeHtml(state.bizQuery) + '”' : ''}.</p>`}</div>`);
}
let detailData = null;
function communityDetail() {
  const c = pageData.detailData; if (!c || !c.members) return shell('<p class="loading">Loading community…</p>');
  const joined = c.members.some(m => m.id === (me().id || 1));
  return shell(`${pageHeader(c.name, c.description)}
<div class="community-cover photo big" style="background-image:linear-gradient(rgba(11,23,17,.35), rgba(11,23,17,.55)), url('${sportPhoto(c.activity)}')"><span>◌</span><small>${c.members.length} members · ${escapeHtml(c.activity)}</small></div>
<div class="people-row" style="margin:12px 0">${c.members.map(m => `<button class="pavatar-btn" data-action="athlete" data-id="${m.id}" title="${escapeHtml(m.name)}">${photoAvatar(m.name, m.id)}</button>`).join('')}</div>
<div class="hero-actions" style="margin:0 0 14px"><button class="outline small" data-action="communityChallenge" data-id="${c.id}">⚔️ Challenge a member</button><a class="outline small" style="text-decoration:none;display:inline-block" data-action="communityInvite" data-id="${c.id}">✉ Invite a friend</a></div>
<form class="composer wide" id="community-post-form" data-cid="${c.id}"><input placeholder="Share something with ${escapeHtml(c.name.split(' ')[0])}..." maxlength="2000" required/><button aria-label="Post">➤</button></form>
<div class="feed-col">${c.posts.map(postCard).join('') || '<p class="loading">No posts yet — start the conversation!</p>'}</div>
<section class="section-head"><div><span class="eyebrow">COMMUNITY EVENTS</span><h2>Coming up</h2></div></section>
<div class="event-grid">${c.events.map(eventCard).join('') || '<p class="loading">No events for this community yet.</p>'}</div>
<div class="hero-actions" style="margin-top:14px"><button class="${joined ? 'outline' : 'primary'}" data-action="${joined ? 'leaveCommunity' : 'joinCommunity'}" data-id="${c.id}" data-back="community">${joined ? 'Joined ✓ — leave' : 'Join community'}</button><button class="outline" data-page="communities">All communities</button></div>`);
}
function athleteProfile() {
  const a = pageData.detailData; if (!a || !a.badges) return shell('<p class="loading">Loading athlete…</p>');
  const isMe = me().id ? a.id === me().id : false;
  return shell(`${pageHeader(a.name, '@' + (a.username || '') + ' · ' + (a.city || 'Chennai'))}
<section class="profile-hero"><div class="profile-cover photo" style="background-image:linear-gradient(110deg, rgba(22,79,62,.88), rgba(110,175,112,.6)), url('${a.photo || sportPhoto(a.favorite_activity)}')"></div>
<div class="profile-info">${photoAvatar(a.name, a.id)}<div><span class="pill lime">LEVEL ${Math.floor((a.xp || 0) / 500) + 1} · ${['Rookie', 'Mover', 'Athlete', 'Warrior', 'Legend'][Math.min(4, Math.floor((a.xp || 0) / 500))]}</span><h2>${escapeHtml(a.name)} <i>✓</i></h2><p class="bio">${escapeHtml(a.bio || 'No bio yet.')}</p><p>${escapeHtml(a.favorite_activity || '')} · ${escapeHtml(a.fitness_level || '')} · ${escapeHtml(a.preferred_time || '')}</p></div>
<div class="profile-actions">${isMe ? '<button class="outline" data-page="profile">Your profile</button>' : sessionToken ? `<button class="primary" data-action="friend" data-id="${a.id}">Add friend</button><button class="outline" data-action="challenge" data-id="${a.id}">Challenge</button><button class="outline" data-action="messageUser" data-id="${a.id}">Message</button>` : `<button class="primary" data-action="register">Sign up to connect</button><button class="outline" data-action="account">Log in</button>`}</div></div>
<div class="profile-stats"><span><b>${a.streak || 0}</b> day streak</span><span><b>${(a.xp || 0).toLocaleString()}</b> XP</span><span><b>${a.activities || 0}</b> activities</span><span><b>${a.badges.length}</b> badges</span></div></section>
<div class="tabs" id="athlete-tabs">${['Posts', 'Activities', 'Badges'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-atab="${t.toLowerCase()}">${t}</button>`).join('')}</div>
<div id="atab-posts">${a.posts.map(postCard).join('') || '<p class="loading">No posts yet.</p>'}</div>
<div id="atab-activities" style="display:none"><div class="activity-grid">${a.activities.map(x => activity('🏀', x.title, `${x.participant_count} people`, `${dayShort(x.starts_at)} · ${timeShort(x.starts_at)}`, x.location_label, x.sport, x.id, x.joined)).join('') || '<p class="loading">Not hosting anything right now.</p>'}</div></div>
<div id="atab-badges" style="display:none"><div class="achievement-row">${a.badges.map(b => `<article><span>${b.icon}</span><b>${escapeHtml(b.name)}</b><small>Unlocked ${dayShort(b.unlocked_at)}</small></article>`).join('') || '<p class="loading">No badges yet.</p>'}</div></div>`);
}
function render() {
  if (render.__skip) return;  // data-refresh pass that must not disturb a live modal
  const pages = { home, discover, posts: reels, reels, challenges, communities, events, messages, profile, bookings, business, admin, businesses, communityDetail, athleteProfile, workout: workoutPage, nutrition: nutritionPage, progress: progressPage, friends: friendsPage, library: libraryPage, coach: coachPage, weeklyReview: weeklyReviewPage, intelligence: intelligencePage, connectHealth, businessChannel };
  // FITVERSE 6.1: repaint freely, then RESTORE any active typing session.
  // Background renders used to wipe the user's half-typed text/focus (the
  // Discover/Messages glitch). Now: capture value+caret before, refocus after.
  const ae = document.activeElement;
  const typing = (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA') && $('#app').contains(ae))
    ? { sel: ae.id ? '#' + CSS.escape(ae.id) : null, tag: ae.tagName, name: ae.name || null, val: ae.value, s: ae.selectionStart, e: ae.selectionEnd } : null;
  $('#app').innerHTML = (pages[state.page] || home)();
  bind();
  redrawOnboarding(); // keeps the setup wizard alive across re-renders (fixes pop-in-then-vanish glitch)
  // FITVERSE 6.2: boot badge disappears once the profile has actually loaded.
  const bb = $('#boot-badge'); if (bb && me().name) bb.remove();
  if (typing) {
    let el = typing.sel ? $(typing.sel) : null;
    if (!el && typing.name) el = $(`#app ${typing.tag.toLowerCase()}[name="${typing.name}"]`);
    if (el) { el.value = typing.val; el.focus(); try { el.setSelectionRange(typing.s, typing.e); } catch (_) {} }
  }
}
function modal(content) { $('#modal').innerHTML = `<div class="modal-backdrop" data-action="close"></div><section class="modal-card">${content}<button class="modal-x" data-action="close">×</button></section>`; }
function modalWide(content) { $('#modal').innerHTML = `<div class="modal-backdrop" data-action="close"></div><section class="modal-card wide">${content}<button class="modal-x" data-action="close">×</button></section>`; }
// Unified post/reel composer with types and optional photo
function openComposer(mode = 'post', presetKind = '') {
  const isReel = mode === 'reel';
  const types = isReel
    ? [['reel', '🎬 Reel'], ['motivation', '🔥 Motivation'], ['achievement', '🏆 Achievement']]
    : [['fitness_update', '✦ Update'], ['workout', '🏋 Workout'], ['progress', '📈 Progress'], ['meal', '🍽 Meal'], ['achievement', '🏆 Achievement'], ['challenge', '⚡ Challenge'], ['motivation', '🔥 Motivation'], ['question', '❓ Question']];
  const kind = presetKind || (isReel ? 'reel' : 'fitness_update');
  modal(`<span class="eyebrow">${isReel ? 'NEW REEL' : 'NEW POST'}</span><h2>${isReel ? 'Create a reel' : 'Share with the FITVERSE'}</h2>
  <form class="activity-form" id="composer-form">
  <label>Type<select name="kind">${types.map(([v, l]) => `<option value="${v}" ${v === kind ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
  <label>${isReel ? 'Caption' : "What's happening?"}<textarea name="body" rows="${isReel ? 3 : 4}" placeholder="${isReel ? 'Say something about your clip…' : 'Training, meals, questions, wins…'}" required maxlength="2000"></textarea></label>
  <label class="file-label">${isReel ? 'Video or photo' : 'Photo'} <span class="dim">(${isReel ? 'optional, up to 25MB · mp4/webm/mov' : 'optional, up to 3MB'})</span><input type="file" id="composer-media" accept="${isReel ? 'video/mp4,video/webm,video/quicktime,image/*' : 'image/*'}" ${isReel ? '' : 'capture="environment"'}></label>
  <div id="composer-preview"></div>
  <div class="composer-ai-bar" id="composer-ai-bar"><span>✦ AI assist ready — polishes wording + adds hashtags</span></div>
  <div class="hero-actions"><button class="outline" type="button" id="composer-ai-btn">✦ Assist</button><button class="primary" type="submit">${isReel ? 'Publish reel' : 'Publish post'}</button></div>
  </form>`);
  bind();
  let mediaPath = '', mediaIsVideo = false;
  const mediaInput = $('#composer-media');
  const uploadMedia = (file) => {
    const isVid = file.type.startsWith('video/');
    const limit = isVid ? 25_000_000 : 3_000_000;
    if (file.size > limit) { toast(`Too large — max ${isVid ? 25 : 3}MB`); return; }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const ext = (file.name.split('.').pop() || (isVid ? 'mp4' : 'jpg')).toLowerCase().replace(/[^a-z0-9]/g, '') || (isVid ? 'mp4' : 'jpg');
        const r = await api('/api/upload', { method: 'POST', body: JSON.stringify({ data: reader.result, ext, kind: isVid ? 'video' : 'image' }) });
        mediaPath = r.path; mediaIsVideo = r.media === 'video';
        $('#composer-preview').innerHTML = mediaIsVideo
          ? `<video src="${r.path}" class="composer-thumb" muted playsinline></video><p class="loading">Video attached ✓</p>`
          : `<img src="${r.path}" alt="preview" class="composer-thumb"/>`;
      } catch (err) { toast(err.message); }
    };
    reader.readAsDataURL(file);
  };
  mediaInput.onchange = (e) => { const f = e.target.files?.[0]; if (f) uploadMedia(f); };
  const formEl = $('#composer-form');
  const bar = $('#composer-ai-bar');
  let composeAi = null;
  const aiBtn = $('#composer-ai-btn');
  if (aiBtn) aiBtn.onclick = async () => {
    const txt = (formEl ? new FormData(formEl).get('body') : '') || '';
    if (!String(txt).trim()) { toast('Write something first — then tap ✦ Assist'); return; }
    aiBtn.disabled = true; aiBtn.textContent = '✦ Thinking…';
    try {
      const r = await api('/api/ai/compose', { method: 'POST', body: JSON.stringify({ text: txt }) });
      if (r.ok) {
        composeAi = r;
        $('textarea', $('#composer-form')).value = r.text;
        if (bar) bar.innerHTML = `<span>✦ ${r.engine === 'groq' ? 'AI polished' : 'tidied'}${r.hashtags && r.hashtags.length ? ' · tags: ' + r.hashtags.map(t => '#' + escapeHtml(t)).join(' ') : ''} — publishes on Post${r.engine === 'groq' ? '' : ' (offline mode)'}</span><button type="button" class="outline small" id="composer-ai-undo">Undo</button>`;
        const undo = $('#composer-ai-undo');
        if (undo) undo.onclick = () => { $('textarea', $('#composer-form')).value = txt; composeAi = null; if (bar) bar.innerHTML = '<span>✦ AI assist ready — tap Assist again after editing</span>'; };
      } else { toast(r.error || 'Nothing to polish'); }
    } catch (err) { toast(err.message); }
    aiBtn.disabled = false; aiBtn.textContent = '✦ Assist';
  };
  $('#composer-form').onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    if (isReel && !mediaPath) { toast('Reels need a video or photo — pick one above'); return; }
    try {
      let body = f.body;
      if (composeAi && composeAi.text) {
        body = composeAi.text;
        const existing = (f.body.match(/#\w+/g) || []).map(t => t.toLowerCase());
        const add = (composeAi.hashtags || []).filter(t => !existing.includes(t));
        if (add.length) body += '\n\n' + add.map(t => '#' + t).join(' ');
        composeAi = null;
      }
      await api('/api/posts', { method: 'POST', body: JSON.stringify({ body, kind: f.kind, photo: mediaPath || undefined, meta: mediaIsVideo ? 'video' : undefined }) });
      $('#modal').innerHTML = '';
      toast(isReel ? 'Reel published 🎬' : 'Posted to the feed ✦');
      await hydrate();
      state.prTab = isReel ? 'reels' : 'posts';
      state.page = 'posts';
      await loadPageData('posts');
      render();
    } catch (err) { toast(err.message); }
  };
}
// PR celebration overlay with confetti
function celebrate(prCount) {
  const el = document.createElement('div');
  el.className = 'celebrate';
  el.innerHTML = `<div class="celebrate-card"><div class="confetti">${'<i></i>'.repeat(24)}</div><span class="pill coral">🔥 NEW PERSONAL RECORD${prCount > 1 ? 'S' : ''}</span><h2>${prCount} PR${prCount > 1 ? 's' : ''} just landed</h2><p>All that work is paying off.</p><button class="primary" onclick="this.closest('.celebrate').remove()">Let's go 🎉</button></div>`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}
// Shareable card via canvas
function momentCard(m) {
  const canvas = document.createElement('canvas');
  canvas.width = 1080; canvas.height = 1080;
  const c = canvas.getContext('2d');
  const g = c.createLinearGradient(0, 0, 1080, 1080);
  g.addColorStop(0, '#0b1711'); g.addColorStop(1, '#1d3a2d');
  c.fillStyle = g; c.fillRect(0, 0, 1080, 1080);
  c.fillStyle = '#c9f36b'; c.font = '800 56px Manrope, Arial'; c.fillText('FITVERSE', 80, 140);
  c.fillStyle = '#c9f36b'; c.font = '700 44px Manrope, Arial'; c.fillText(m.card.headline, 80, 400);
  c.fillStyle = '#ffffff'; c.font = '800 92px Manrope, Arial'; c.fillText(m.card.main.slice(0, 22), 80, 520);
  c.font = '800 150px Manrope, Arial'; c.fillStyle = '#ffffff'; c.fillText(String(m.card.big).slice(0, 14), 80, 720);
  const streak = state.streak || 0;
  if (streak > 0) { c.fillStyle = '#9fb3a4'; c.font = '500 40px Manrope, Arial'; c.fillText('🔥 ' + streak + '-day streak', 80, 830); }
  c.fillStyle = '#9fb3a4'; c.font = '500 32px Manrope, Arial';
  c.fillText('Fitness is more fun together → fitverse.app', 80, 980);
  const a = document.createElement('a');
  a.download = 'fitverse-moment.png';
  a.href = canvas.toDataURL('image/png');
  a.click();
  toast('Moment card downloaded — post it anywhere 📲');
}

function shareCard(kind) {
  const canvas = document.createElement('canvas');
  canvas.width = 1080; canvas.height = 1350;
  const c = canvas.getContext('2d');
  const grad = c.createLinearGradient(0, 0, 1080, 1350);
  grad.addColorStop(0, '#0b1711'); grad.addColorStop(1, '#1d3a2d');
  c.fillStyle = grad; c.fillRect(0, 0, 1080, 1350);
  c.fillStyle = '#c9f36b'; c.font = '800 64px Manrope, Arial'; c.fillText('FITVERSE', 80, 140);
  let title = 'Weekly Recap', stats;
  if (kind === 'fitness-dna') {
    const d = (pageData.intel || {});
    const dna = d.dna || {};
    title = 'Fitness DNA';
    c.fillStyle = '#ffffff'; c.font = '800 88px Manrope, Arial'; c.fillText('Fitness DNA', 80, 320);
    c.font = '500 40px Manrope, Arial'; c.fillStyle = '#9fb3a4';
    c.fillText(dna.personality || 'The Explorer', 80, 390);
    const sc = dna.scores || {};
    stats = Object.entries(sc).map(([k, v]) => [v, k]);
  } else {
    const r = pageData.review || {};
    c.fillStyle = '#ffffff'; c.font = '800 88px Manrope, Arial'; c.fillText('Weekly Recap', 80, 320);
    c.font = '500 40px Manrope, Arial'; c.fillStyle = '#9fb3a4';
    c.fillText(r.week || new Date().toDateString(), 80, 390);
    stats = [[r.workouts || 0, 'workouts'], [(r.calories_burned || 0).toLocaleString(), 'kcal burned'], [r.avg_protein || 0, 'avg protein g'], [r.new_prs || 0, 'new PRs'], [(r.consistency || 0) + '%', 'consistency'], [r.streak || 0, 'day streak']];
  }
  stats.slice(0, 8).forEach(([v, label], i) => {
    const x = 80 + (i % 2) * 480, y = 540 + Math.floor(i / 2) * 200;
    c.fillStyle = '#ffffff22'; c.fillRect(x, y - 110, 420, 160);
    c.fillStyle = '#c9f36b'; c.font = '800 74px Manrope, Arial'; c.fillText(String(v), x + 30, y);
    c.fillStyle = '#9fb3a4'; c.font = '500 32px Manrope, Arial'; c.fillText(label, x + 30, y + 42);
  });
  c.fillStyle = '#9fb3a4'; c.font = '500 32px Manrope, Arial';
  c.fillText('Fitness is more fun together → fitverse.app', 80, 1260);
  const a = document.createElement('a');
  a.download = `fitverse-${kind}.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
  toast('Card downloaded — share it anywhere 📲');
}
function scrollBubbles() { const b = $('#bubbles'); if (b) b.scrollTop = b.scrollHeight; }
// Live updates: poll notifications + active conversation so chats and badges stay fresh.
let lastMsgId = 0, pollTimer = null, lastOwnType = 0;
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (!apiEnabled || document.hidden || !sessionToken) return;
    try {
      const n = await api(`/api/notifications/since?since=${pageData.notifications[0]?.id || 0}`);
      if (n.items?.length) { pageData.notifications = [...n.items, ...pageData.notifications]; n.items.slice(0, 2).forEach(x => toast(`${x.title} — ${x.body}`)); if (state.page !== 'messages') render(); }
      // Live home stats: nutrition + water stay current without any manual refresh.
      // FITVERSE 6.1: surgical DOM updates instead of full re-render — the old
      // render() here stole focus and scrolled the page while users browsed.
      if (state.page === 'home') {
        const [nut, wat] = await Promise.all([api('/api/nutrition').catch(() => null), api('/api/water').catch(() => null)]);
        if (nut) { pageData.nutrition = nut; pageData.dash.kcal = { eaten: nut.totals.kcal, target: nut.targets.kcal_target, protein: nut.totals.protein, proteinTarget: nut.targets.protein_target }; }
        if (wat) { pageData.water = wat; pageData.dash.water = wat; }
        $$('.dash-grid .stat-card').forEach((card, i) => {
          const texts = { 0: s => s.kcal ? `${s.kcal.eaten.toLocaleString()} / ${s.kcal.target.toLocaleString()}` : '—', 1: s => s.kcal ? `${s.kcal.protein}/${s.kcal.proteinTarget}g` : '—', 2: s => s.water ? `${(s.water.today_ml / 1000).toFixed(1)}/${(s.water.target_ml / 1000).toFixed(1)}L` : '—', 3: s => s.week && s.week.sessions != null ? `${s.week.sessions} workouts` : '—' };
          const strong = card.querySelector('strong'); const fn = texts[i];
          if (strong && fn) { const t = fn(pageData.dash || {}); if (strong.textContent.trim() !== t.replace(/\s+/g, ' ').trim()) strong.innerHTML = t; }
        });
      }
      if (state.page === 'messages') {
        const fresh = (await api(`/api/conversations/${pageData.activeConversation}`)).items || [];
        const newest = fresh[fresh.length - 1]?.id || 0;
        if (newest > lastMsgId) { lastMsgId = newest; pageData.messages = fresh; render(); scrollBubbles(); }
        const convs = (await api('/api/conversations')).items || [];
        if (convs.length) pageData.conversations = convs;
      }
    } catch (_) { /* offline — ignore */ }
  }, 4000);
}
function cmdk() {
  modal(`<span class="eyebrow">SEARCH FITVERSE</span><h2>Find anything ⌘K</h2><input id="cmdk-input" placeholder="People, activities, communities, events..." style="width:100%;border:1px solid #e7ebe7;border-radius:9px;padding:11px 13px;font:inherit"/><div id="cmdk-results" style="margin-top:12px;display:grid;gap:6px;max-height:320px;overflow:auto"></div>`);
  const input = $('#cmdk-input'); input.focus();
  input.oninput = async () => {
    const q = input.value.trim(); if (q.length < 2) { $('#cmdk-results').innerHTML = ''; return; }
    try {
      const r = await api('/api/search?q=' + encodeURIComponent(q));
      const s = r.items || {};
      $('#cmdk-results').innerHTML = [
        ...(s.users || []).map(u => `<button class="cmdk-row" data-cmd="person" data-id="${u.id}">👤 <b>${escapeHtml(u.name)}</b> <small>@${escapeHtml(u.username)} · ${u.xp} XP</small></button>`),
        ...(s.activities || []).map(a => `<button class="cmdk-row" data-cmd="activity" data-id="${a.id}">🏀 <b>${escapeHtml(a.title)}</b> <small>${escapeHtml(a.sport)} · ${dayShort(a.starts_at)}</small></button>`),
        ...(s.communities || []).map(c => `<button class="cmdk-row" data-cmd="community" data-id="${c.id}">◌ <b>${escapeHtml(c.name)}</b> <small>${escapeHtml((c.description || '').slice(0, 40))}</small></button>`),
        ...(s.events || []).map(ev => `<button class="cmdk-row" data-cmd="event" data-id="${ev.id}">◫ <b>${escapeHtml(ev.name)}</b> <small>${escapeHtml(ev.category)} · ${inr(ev.price_inr)}</small></button>`),
      ].join('') || '<p class="loading">No matches.</p>';
      $$('.cmdk-row').forEach(b => b.onclick = () => { $('#modal').innerHTML = ''; if (b.dataset.cmd === 'person') personModal(Number(b.dataset.id)); else if (b.dataset.cmd === 'activity') activityDetail(Number(b.dataset.id)); else { state.page = b.dataset.cmd + 's'; render(); loadPageData(state.page); } });
    } catch (e) { $('#cmdk-results').innerHTML = `<p class="loading">${escapeHtml(e.message)}</p>`; }
  };
}
async function personModal(id) {
  try {
    const u = (pageData.users.length ? pageData.users : (await api('/api/users')).items || []).find(x => x.id === id) || pageData.recommendations.find(x => x.id === id);
    if (!u) return toast('Profile not found');
    action('personMenu', { dataset: { id: String(id) } });
  } catch (e) { toast(e.message); }
}
async function activityDetail(id) {
  try {
    const { item: a } = await api(`/api/activities/${id}`);
    modal(`<div class="detail-photo" style="background-image:url('${sportPhoto(a.sport)}')"></div><span class="eyebrow">${escapeHtml(a.sport.toUpperCase())} · ${a.participant_count}/${a.max_participants} JOINED</span><h2>${escapeHtml(a.title)}</h2><p>${escapeHtml(a.description || 'No description yet.')}</p><div class="compat"><span>◷ ${dayShort(a.starts_at)} · ${timeShort(a.starts_at)}</span><span>⌖ ${escapeHtml(a.location_label)}</span><span>⚡ ${escapeHtml(a.fitness_level)} · ${escapeHtml(a.intensity)}</span></div><p class="loading">Hosted by <b>${escapeHtml(a.host_name)}</b></p><div class="people-row">${(a.participants || []).map((p, i) => photoAvatar(p.name, p.id)).join('')}</div><div class="hero-actions">${a.completed ? '<button class="outline" disabled>Completed ✓</button>' : a.joined ? `<button class="primary" data-action="completeActivity" data-id="${a.id}">Mark complete +80 XP</button><button class="outline" data-action="leaveActivity" data-id="${a.id}">Leave</button>` : `<button class="primary" data-action="joinActivityById" data-id="${a.id}">Join activity</button>`}</div>`);
    bind();
  } catch (e) { toast(e.message); }
}
// FITVERSE 6.1: ONE delegated click listener for navigation/actions — installed
// once and reused across every re-render. Re-binding thousands of per-node
// handlers on each keystroke render made Discover/Messages drop keystrokes,// steal focus and feel glitchy; delegation removes all of that.
document.addEventListener('click', (e) => {
  const t = e.target instanceof Element ? e.target : null; if (!t) return;
  const pageEl = t.closest('[data-page]');
  if (pageEl) { if (pageEl.dataset.bizid) state.bizId = Number(pageEl.dataset.bizid); pushTrail(pageEl.dataset.page); state.page = pageEl.dataset.page; render(); loadPageData(state.page); window.scrollTo(0, 0); return; }
  const bcat = t.closest('[data-bcat]');
  if (bcat) { state.bizCat = bcat.dataset.bcat; render(); const inp = $('#biz-search'); if (inp) { inp.focus(); inp.value = state.bizQuery || ''; } return; }
  const conv = t.closest('[data-conv]');
  if (conv) { (async () => { pageData.activeConversation = Number(conv.dataset.conv); await loadMessages(); api('/api/conversations').then(d => { pageData.conversations = d.items || []; if (state.page === 'messages') render(); }).catch(() => {}); window.scrollTo(0, 0); })(); return; }
  const act = t.closest('[data-action]');
  if (act) action(act.dataset.action, act);
});
function bind() {
  // NAV / ACTIONS / CONVERSATIONS: handled by the single delegated listener
  // above (installed once at boot). Only inputs and their direct effects bind
  // per-render below.
  const bizSearch = $('#biz-search');
  if (bizSearch) { let t; bizSearch.oninput = () => { clearTimeout(t); t = setTimeout(() => { state.bizQuery = bizSearch.value; render(); const inp = $('#biz-search'); if (inp) { inp.focus(); inp.value = state.bizQuery; } }, 250); }; }
  $$('[data-tab]').forEach(b => b.onclick = () => {
    $$('[data-tab]').forEach(x => x.classList.toggle('active', x === b));
    ['people', 'activities', 'communities', 'events', 'businesses'].forEach(t => { const el = $(`#tab-${t}`); if (el) el.style.display = t === b.dataset.tab ? '' : 'none'; });
  });
  $$('[data-ptab]').forEach(b => b.onclick = () => {
    $$('[data-ptab]').forEach(x => x.classList.toggle('active', x === b));
    ['posts', 'friends', 'achievements'].forEach(t => { const el = $(`#ptab-${t}`); if (el) el.style.display = t === b.dataset.ptab ? '' : 'none'; });
  });
  $$('[data-atab]').forEach(b => b.onclick = () => {
    $$('[data-atab]').forEach(x => x.classList.toggle('active', x === b));
    ['posts', 'activities', 'badges'].forEach(t => { const el = $(`#atab-${t}`); if (el) el.style.display = t === b.dataset.atab ? '' : 'none'; });
  });
  $$('[data-ftab]').forEach(b => b.onclick = async () => {
    $$('[data-ftab]').forEach(x => x.classList.toggle('active', x === b));
    ['foryou', 'following', 'trending'].forEach(t => { const el = $(`#feed-${t}`); if (el) el.style.display = t === b.dataset.ftab ? '' : 'none'; });
    const tab = b.dataset.ftab;
    const holder = $(`#feed-${tab}`);
    if (!holder || holder.dataset.loaded === '1') return;
    holder.innerHTML = '<p class="loading">Loading…</p>';
    try {
      const d = await api('/api/feed/tabs?tab=' + tab);
      holder.innerHTML = d.items.length ? d.items.map(postCard).join('') : emptyState(tab === 'following' ? '👥' : '🔥', tab === 'following' ? 'Follow more athletes' : 'Nothing trending yet', tab === 'following' ? 'Posts from people you follow appear here. Find your crew on Discover.' : 'Interact with posts and the hottest ones rise here.');
      holder.dataset.loaded = '1';
      bind();
    } catch { holder.innerHTML = '<p class="loading">Could not load this tab.</p>'; }
  });
  $$('[data-prtab]').forEach(b => b.onclick = () => {
    state.prTab = b.dataset.prtab;
    render();
    loadPageData(state.page === 'posts' ? 'posts' : 'reels');
  });
  $$('[data-muscle]').forEach(b => b.onclick = async () => {
    $$('[data-muscle]').forEach(x => x.classList.toggle('active', x === b));
    const m = b.dataset.muscle;
    const q = m === 'All' ? '' : `?muscle=${m}`;
    try { pageData.exercises = (await api('/api/exercises' + q)).items || []; const grid = $('.lib-grid'); if (grid) { grid.innerHTML = libraryPage().split('<div class="lib-grid">')[1]?.split('</div>')[0] || ''; } render(); } catch (e) { toast(e.message); }
  });
  const libSearch = $('#lib-search');
  if (libSearch) libSearch.oninput = async () => {
    const q = libSearch.value.trim();
    try { pageData.exercises = (await api('/api/exercises?q=' + encodeURIComponent(q))).items || []; render(); const inp = $('#lib-search'); if (inp) { inp.focus(); inp.value = q; } } catch (e) {}
  };
  const coachForm = $('#coach-form');
  if (coachForm) coachForm.onsubmit = async (e) => {
    e.preventDefault();
    const input = $('input', coachForm); const msg = input.value.trim(); if (!msg) return;
    input.value = ''; input.focus();
    pageData.coachChat = pageData.coachChat || [];
    pageData.coachChat.push({ role: 'user', content: msg });
    pageData.coachTyping = true; render();  // typing indicator shows immediately
    try {
      const r = await api('/api/ai/companion', { method: 'POST', body: JSON.stringify({ message: msg, conversationId: pageData.coachConvId }) });
      pageData.coachConvId = r.conversationId;
      pageData.coachChat.push({ role: 'coach', content: r.reply });
      pageData.coachTyping = false;
      await loadPageData('coach');  // refresh saved-chats sidebar (titles, pins)
    } catch (err) {
      pageData.coachChat.push({ role: 'coach', content: 'I could not reach the server just now — give it another shot.' });
      pageData.coachTyping = false;
    }
    render();
  };
  const cpf = $('#community-post-form');
  if (cpf) cpf.onsubmit = async (e) => {
    e.preventDefault();
    const input = $('input', cpf); const bodyTxt = input.value.trim(); if (!bodyTxt) return;
    input.value = '';
    try { await api('/api/community/posts', { method: 'POST', body: JSON.stringify({ community_id: Number(cpf.dataset.cid), body: bodyTxt }) }); await loadPageData('communityDetail'); toast('Posted to the community'); }
    catch (err) { toast(err.message); input.value = bodyTxt; }
  };
  // FITVERSE 4.0: daily metrics form (Connect Health Data page)
  const mf = $('#metrics-form');
  if (mf) mf.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    try { await api('/api/health/metrics', { method: 'POST', body: JSON.stringify(f) }); toast('Saved — vitals, workouts and diet plans update instantly'); await loadPageData(state.page); render(); }
    catch (err) { toast(err.message); }
  };
  // FITVERSE 5.0: Health Connect export / Takeout ZIP import (real data, honest flow)
  const hi = $('#hc-import-input');
  if (hi) hi.onchange = async () => {
    const st = $('#hc-import-status');
    if (!hi.files || !hi.files.length) return;
    try {
      if (st) st.textContent = 'Reading your export…';
      const recs = await parseHealthExportFiles([...hi.files]);
      if (!recs.length) { if (st) st.textContent = 'Could not find steps/sleep/heart-rate/workout records in those files. Export from Health Connect (Settings → Export data) or Takeout → Fit as JSON, or paste rows as [{"type":"steps","day":"2026-01-31","value":8000}].'; return; }
      if (st) st.textContent = `Importing ${recs.length} records…`;
      const r = await api('/api/health/import/file', { method: 'POST', body: JSON.stringify({ records: recs }) });
      if (st) st.textContent = `✅ Stored ${r.days_stored} day-records and ${r.activities_stored} workout${r.activities_stored == 1 ? '' : 's'}${r.skipped ? ` · ${r.skipped} unrecognized entries skipped (never guessed)` : ''}.`;
      toast('Health data imported to your account');
    } catch (e) { if (st) st.textContent = e.message; }
  };
  // FITVERSE 4.0: Google Takeout import (zero-setup real health data)
  const ti = $('#takeout-input');
  if (ti) ti.onchange = async () => {
    const st = $('#takeout-status');
    if (!ti.files || !ti.files.length) return;
    try {
      if (st) st.textContent = 'Parsing your export…';
      const days = await parseTakeoutFiles([...ti.files]);
      if (!days.length) { if (st) st.textContent = 'No Google Fit data found in those files — pick the .json files from a Fit export.'; return; }
      if (st) st.textContent = `Importing ${days.length} days…`;
      const r = await api('/api/health/import/takeout', { method: 'POST', body: JSON.stringify({ days }) });
      if (st) st.textContent = `✅ Imported ${r.days} days of steps and ${r.activities} days of distance.`;
      toast('Google Fit data imported');
    } catch (e) { if (st) st.textContent = e.message; }
  };
  // FITVERSE 4.0: business channel Leaflet map (free OpenStreetMap tiles, no API key)
  const mapEl = $('#biz-map');
  if (mapEl && !mapEl._init && window.L) {
    mapEl._init = true;
    const lat = Number(mapEl.dataset.lat), lng = Number(mapEl.dataset.lng);
    try {
      const map = L.map(mapEl, { scrollWheelZoom: false, attributionControl: true }).setView([lat, lng], 16);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(map);
      L.marker([lat, lng]).addTo(map).bindPopup(escapeHtml(mapEl.dataset.name || ''));
      setTimeout(() => map.invalidateSize(), 150);
    } catch (_) {}
  }
  if (mapEl && !window.L && !mapEl._warned) { mapEl._warned = true; mapEl.innerHTML = '<div class="biz-map-fallback">🗺 Map tiles need internet — address: ' + escapeHtml(mapEl.dataset.name || '') + '</div>'; }
  // Typing indicator: broadcast while the user types (throttled), and show partner typing via SSE.
  const ci = $('#composer-input');
  if (ci) ci.oninput = () => {
    const now = Date.now();
    if (now - lastOwnType > 1800) { lastOwnType = now; api('/api/typing', { method: 'POST', body: JSON.stringify({ conversation_id: Number(pageData.activeConversation) }) }).catch(() => {}); }
  };
  $$('[data-form]').forEach(f => f.onsubmit = async (e) => {
    e.preventDefault();
    const input = $('input', f); if (!input.value.trim()) return;
    const message = input.value.trim(); input.value = '';
    try {
      if (f.dataset.form === 'coach') { const result = await api('/api/coach?q=' + encodeURIComponent(message)); pageData.coach = result.reply; render(); return; }
      // Optimistic send: show instantly, then sync with the server (which may auto-reply).
      // v6.3: carry id=0 + avatar so the pending bubble renders identically.
      pageData.messages.push({ id: 0, sender_id: me().id || 1, name: me().name || 'You', body: message, created_at: new Date().toISOString(), avatar_url: me().avatar_url || '' });
      render(); scrollBubbles();
      await api('/api/messages', { method: 'POST', body: JSON.stringify({ body: message, conversation_id: f.dataset.conv || 1 }) });
      const fresh = (await api(`/api/conversations/${f.dataset.conv || 1}`)).items || [];
      if (f.dataset.conv == pageData.activeConversation && state.page === 'messages') { pageData.messages = fresh; render(); }
      const conv = pageData.conversations.find(c => c.id == f.dataset.conv);
      if (conv) { conv.last_message = message; }
    } catch (error) { toast(error.message); input.value = message; }
    const next = $('#composer-input'); if (next) next.focus();
  });
  const search = $('#discover-search');
  if (search) search.oninput = () => {
    const term = search.value.toLowerCase();
    $$('.person-card, .activity-card, .community-card, .event-card').forEach(card => { card.style.display = card.textContent.toLowerCase().includes(term) ? '' : 'none'; });
  };
  const psearch = $('#people-search');
  if (psearch) {
    const applyPeople = (items) => { const g = $('#people-grid'); if (g) g.innerHTML = items.length ? items.map(p => personCard(p)).join('') : '<p class="loading">No athletes found — try another name.</p>'; bind(); };
    psearch.oninput = () => { const term = psearch.value.trim().toLowerCase(); applyPeople((pageData.allUsers || []).filter(u => !term || String(u.name).toLowerCase().includes(term) || String(u.username).toLowerCase().includes(term))); };
    psearch.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); const t = psearch.value.trim(); if (!t) return; api('/api/users?q=' + encodeURIComponent(t)).then(d => applyPeople(d.items || [])).catch(err => toast(err.message)); } };
  }
  const chatSearch = $('#chat-search');
  if (chatSearch) chatSearch.oninput = () => {
    const term = chatSearch.value.toLowerCase();
    $$('.conversation').forEach(c => { c.style.display = c.textContent.toLowerCase().includes(term) ? '' : 'none'; });
  };
  if (state.page === 'messages') {
    setTimeout(() => { scrollBubbles(); const ci = $('#composer-input'); if (ci && document.activeElement !== ci && !document.querySelector('.modal-card')) ci.focus(); }, 60);
  }
}
function customExerciseModal(onSaved) {
  modal(`<span class="eyebrow">EXERCISE LIBRARY</span><h2>Add a custom exercise</h2><p>Your exercise is private to you and shows up in your library and workout logging.</p><form class="activity-form" id="cex-form"><label>Exercise name<input name="name" required maxlength="80" placeholder="e.g. Preacher Curl"></label><label>Muscle group<select name="muscle">${['Chest','Back','Shoulders','Arms','Legs','Glutes','Core','Cardio','Full Body','Other'].map(m => `<option>${m}</option>`).join('')}</select></label><label>Equipment<input name="equipment" placeholder="Dumbbell, barbell, machine…" maxlength="30"></label><button class="primary" type="submit">Save exercise</button></form>`);
  $('#cex-form').onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
    try { await api('/api/exercises', { method: 'POST', body: JSON.stringify(f) }); toast(`"${f.name}" added to your library`); if (onSaved) onSaved(); }
    catch (err) { toast(err.message); }
  };
  bind();
}
function openComments(postId) {
  api(`/api/comments?post_id=${postId}`).then(d => {
    const items = d.items || [];
    modal(`<span class="eyebrow">COMMENTS</span><h2>Join the conversation</h2><div class="comment-list">${items.map(c => `<div class="comment">${avatar(c.name, 'purple')}<div><strong>${escapeHtml(c.name)}</strong><p>${escapeHtml(c.body)}</p><small>${timeShort(c.created_at)}</small></div></div>`).join('') || '<p>No comments yet.</p>'}</div><form class="activity-form" id="comment-form"><input name="body" placeholder="Add a comment..." required maxlength="1000" style="width:100%;border:1px solid #e7ebe7;border-radius:7px;padding:9px"/><button class="primary" type="submit">Post comment</button></form>`);
    $('#comment-form').onsubmit = async (e) => {
      e.preventDefault();
      const body = new FormData(e.currentTarget).get('body');
      try { await api(`/api/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify({ body }) }); await hydrate(); $('#modal').innerHTML = ''; render(); toast('Comment posted'); }
      catch (err) { toast(err.message); }
    };
  }).catch(e => toast(e.message));
}
async function action(a, btn) {
  const id = btn ? Number(btn.dataset.id) : 0;
  const _now = Date.now();
  if (_now - (action._t || 0) < 300 && action._n === a + id) return;  // double-click guard: one action per tap
  action._t = _now; action._n = a + id;
  const done = (msg, fn) => api('/api/actions', { method: 'POST', body: JSON.stringify({ action: a === 'joinActivity' ? 'join' : a, state: {} }) }).then(async (d) => { if (d.state) applyServerState(d.state); if (fn) await fn(); await hydrate(); render(); toast(msg); }).catch(e => toast(e.message));
  switch (a) {
    case 'account': {
      modal(`<span class="eyebrow">YOUR ACCOUNT</span><h2>Sign in to FITVERSE</h2><p>Welcome back — your session is stored only in this browser.</p><button class="google-btn" data-action="googleLogin"><span class="g-logo">G</span>Continue with Google</button><div class="auth-divider"><span>or sign in with email</span></div><form class="activity-form" id="account-form"><label>Username or email<input name="username" required autocomplete="username"></label><label>Password<input name="password" type="password" required autocomplete="current-password"></label><button class="primary" type="submit">Sign in</button></form><p class="auth-hint">New here? <button class="text-btn" data-action="register">Create an account</button></p>`);
      $('#account-form').onsubmit = async (e) => {
        e.preventDefault(); const f = new FormData(e.currentTarget);
        try {
          const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: f.get('username'), password: f.get('password') }) });
          sessionToken = result.token; localStorage.setItem('fitverse-session', sessionToken); localStorage.setItem('fitverse-user', String(f.get('username') || '').toLowerCase()); localStorage.setItem('fitverse-pass', String(f.get('password') || ''));
          evtSource?.close(); evtSource = null; startSSE();
          $('#modal').innerHTML = '';
          // Instant feedback: user is IN — heavy data loads in the background.
          sessionToken = result.token; localStorage.setItem('fitverse-session', sessionToken); localStorage.setItem('fitverse-user', String(f.get('username') || '').toLowerCase()); localStorage.setItem('fitverse-pass', String(f.get('password') || ''));
          evtSource?.close(); evtSource = null; startSSE();
          render(); toast(`✅ Signed in as ${result.user.name}`);
          hydrate().then(() => { render(); loadPageData(state.page); toast(`Welcome back, ${result.user.name} 💪`); });
        } catch (error) { toast(error.message); }
      }; bind(); return;
    }
    case 'register': {
      modal(`<span class="eyebrow">JOIN FITVERSE</span><h2>Create your account</h2><p>Track workouts, compete with friends and grow your Fitness DNA.</p><button class="google-btn" data-action="googleLogin" type="button"><span class="g-logo">G</span>Continue with Google</button><div class="auth-divider"><span>or sign up with email</span></div><form class="activity-form" id="register-form" novalidate><label>Full name<input name="name" autocomplete="name" required placeholder="e.g. Arjun Rao"></label><label>Email<input name="email" type="email" autocomplete="email" required placeholder="you@example.com"></label><label>Username<input name="username" autocomplete="username" required minlength="3" placeholder="lowercase, no spaces"></label><label>Password<input name="password" type="password" id="reg-pw" autocomplete="new-password" required placeholder="min 8 chars, letters + numbers"><small class="pw-hint">At least 8 characters, including a letter and a number.</small><div class="pw-meter"><i></i></div></label><label>Confirm password<input name="confirm" type="password" autocomplete="new-password" required placeholder="retype your password"></label><div class="form-error" id="reg-error" hidden></div><button class="primary" type="submit">Create account</button></form><p class="auth-hint">Already training with us? <button class="text-btn" data-action="account">Log in</button></p>`);
      const form = $('#register-form'); const errBox = $('#reg-error'); const pw = $('#reg-pw'); const meter = form.querySelector('.pw-meter i');
      const pwOk = (v) => v.length >= 8 && /[a-zA-Z]/.test(v) && /\d/.test(v);
      const fail = (msg) => { errBox.textContent = msg; errBox.hidden = false; };
      pw.oninput = () => { const v = pw.value; const score = (v.length >= 8 ? 1 : 0) + (/[a-zA-Z]/.test(v) ? 1 : 0) + (/\d/.test(v) ? 1 : 0); meter.style.width = (v ? score / 3 * 100 : 0) + '%'; meter.className = score === 3 ? 'strong' : score === 2 ? 'mid' : ''; };
      form.onsubmit = async (e) => {
        e.preventDefault(); errBox.hidden = true; const f = new FormData(form);
        const name = String(f.get('name')).trim(), email = String(f.get('email')).trim().toLowerCase(), username = String(f.get('username')).trim().toLowerCase(), pass = String(f.get('password')), confirm = String(f.get('confirm'));
        if (!name || !email || !username || !pass) return fail('Please fill in every field.');
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return fail("That email address doesn't look right — please check it.");
        if (/\s/.test(username) || username.length < 3) return fail('Username needs at least 3 characters and no spaces.');
        if (!pwOk(pass)) return fail('Password needs at least 8 characters, including a letter and a number.');
        if (pass !== confirm) return fail("Passwords don't match — please retype them.");
        const btn = form.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Creating your account…';
        try {
          const result = await api('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, email, username, password: pass }) });
          sessionToken = result.token; localStorage.setItem('fitverse-session', sessionToken); localStorage.setItem('fitverse-user', username); localStorage.setItem('fitverse-pass', pass);
          evtSource?.close(); evtSource = null; startSSE();
          $('#modal').innerHTML = '';
          render(); toast(`✅ Account created — you're in, ${name.split(' ')[0]}!`);
          hydrate().then(() => { render(); loadPageData(state.page); toast(`🎉 Welcome to FITVERSE, ${name.split(' ')[0]}! Your account is ready.`); });
        } catch (error) { btn.disabled = false; btn.textContent = 'Create account'; fail(error.message); }
      }; bind(); return;
    }
    case 'googleLogin': authWithGoogle(); return;
    case 'logout': api('/api/auth/logout', { method: 'POST' }).catch(() => {}).finally(() => { document.cookie = 'fv_session=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT'; }); sessionToken = ''; localStorage.removeItem('fitverse-session'); localStorage.removeItem('fitverse-user'); localStorage.removeItem('fitverse-pass'); evtSource?.close(); evtSource = null; $('#modal').innerHTML = ''; hydrate().then(render); toast('Signed out — see you soon 💪'); return;
    case 'notifications': {
      modal(`<span class="eyebrow">NOTIFICATIONS</span><h2>Your fitness loop</h2>${pageData.notifications.length ? pageData.notifications.map(n => `<div class="notice" style="${n.is_read ? 'opacity:.5' : ''}"><b>${escapeHtml(n.title)}</b><p>${escapeHtml(n.body)}</p><small>${timeShort(n.created_at)}</small></div>`).join('') : '<p>No notifications.</p>'}<button class="outline" data-action="readNotifications">Mark all read</button>`);
      bind(); return;
    }
    case 'readNotifications': api('/api/notifications/read', { method: 'POST', body: '{}' }).then(async () => { await hydrate(); $('#modal').innerHTML = ''; render(); toast('All caught up'); }).catch(e => toast(e.message)); return;
    case 'create':
      modal(`<span class="eyebrow">CREATE</span><h2>What are we making?</h2><div class="create-options">
      <button data-action="createPost">✦<b>Post</b><small>Update, workout, meal or question</small></button>
      <button data-action="createReel">🎬<b>Reel</b><small>Short-form with a background</small></button>
      <button data-action="createActivity">🏀<b>Activity</b><small>Get your crew moving</small></button>
      <button data-action="challenge">⚡<b>Challenge</b><small>Start a friendly rivalry</small></button>
      <button data-action="createCommunity">◌<b>Community</b><small>Gather your people</small></button>
      <button data-action="logWorkout">🏋<b>Log workout</b><small>Sets, reps and PRs</small></button>
      </div>`);
      bind(); return;
    case 'createActivity':
      modal(`<span class="eyebrow">NEW ACTIVITY</span><h2>Bring people together.</h2><form class="activity-form" id="activity-form"><label>Activity<input name="sport" value="Basketball" required></label><label>Title<input name="title" value="Evening session" required></label><label>When<input name="starts_at" type="datetime-local" required></label><label>Location<input name="location_label" value="Campus Sports Ground" required></label><button class="primary" type="submit">Create activity</button></form>`);
      $('#activity-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/activities', { method: 'POST', body: JSON.stringify({ ...f, max_participants: 8, fitness_level: 'Intermediate', intensity: 'Moderate' }) }); $('#modal').innerHTML = ''; await loadPageData(state.page); render(); toast('Activity created — people can now join'); }
        catch (error) { toast(error.message); }
      }; bind(); return;
    case 'createCommunity':
      modal(`<span class="eyebrow">NEW COMMUNITY</span><h2>Gather your people.</h2><form class="activity-form" id="community-form"><label>Name<input name="name" required placeholder="Morning Yoga Crew"></label><label>Description<input name="description" required placeholder="What is this crew about?"></label><label>Activity<input name="activity" value="Fitness"></label><button class="primary" type="submit">Create community</button></form>`);
      $('#community-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/communities', { method: 'POST', body: JSON.stringify(f) }); $('#modal').innerHTML = ''; await loadPageData(state.page); render(); toast('Community created — you are the owner'); }
        catch (error) { toast(error.message); }
      }; bind(); return;
    case 'createBusinessEvent':
      modal(`<span class="eyebrow">BUSINESS EVENT</span><h2>New event</h2><form class="activity-form" id="business-event-form"><label>Name<input name="name" value="Community Fitness Open" required></label><label>When<input name="starts_at" type="datetime-local" required></label><label>Location<input name="location_label" value="Chennai" required></label><label>Price (₹)<input name="price_inr" type="number" value="0" min="0"></label><button class="primary" type="submit">Publish event</button></form>`);
      $('#business-event-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/events', { method: 'POST', body: JSON.stringify({ ...f, category: 'Community', organizer: 'FITVERSE Business', capacity: 50, description: 'Created from the business dashboard.' }) }); $('#modal').innerHTML = ''; await loadPageData(state.page); render(); toast('Event published to the marketplace'); }
        catch (error) { toast(error.message); }
      }; bind(); return;
    case 'edit':
      modal(`<span class="eyebrow">YOUR PROFILE</span><h2>Edit your profile</h2>
      <div class="avatar-upload"><span class="avatar-edit-wrap">${photoAvatar(me().name, me().id || 1)}<span class="avatar-edit-ring"></span></span>
      <div><b>${escapeHtml(me().name || 'You')}</b><label class="file-label" style="margin-top:6px">📷 Change photo<input type="file" id="avatar-input" accept="image/*" hidden></label></div></div>
      <p class="loading" id="avatar-status"></p>
      <form class="activity-form" id="profile-form"><label>Display name<input name="name" value="${escapeHtml(me().name || '')}" required></label><label>Bio<input name="bio" value="${escapeHtml(me().bio || '')}" required></label><label>Fitness goal<input name="fitness_goal" value="${escapeHtml(me().fitness_goal || 'General fitness')}" required></label><label>City<input name="city" value="${escapeHtml(me().city || 'Chennai')}"></label><button class="primary" type="submit">Save changes</button></form>`);
      bind();
      let newAvatar = '';
      $('#avatar-input').onchange = (e) => {
        const file = e.target.files?.[0]; if (!file) return;
        if (file.size > 3_000_000) { toast('Photo too large — pick one under 3MB'); return; }
        const reader = new FileReader();
        reader.onload = async () => {
          try {
            const ext = (file.name.split('.').pop() || 'jpg').toLowerCase().replace(/[^a-z0-9]/g, '') || 'jpg';
            const r = await api('/api/upload', { method: 'POST', body: JSON.stringify({ data: reader.result, ext, kind: 'image' }) });
            newAvatar = r.path;
            $('#avatar-status').textContent = 'Photo ready — hit Save changes to apply.';
            $('.avatar-edit-wrap .pavatar').style.backgroundImage = `url('${r.path}')`;
          } catch (err) { toast(err.message); }
        };
        reader.readAsDataURL(file);
      };
      $('#profile-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        if (newAvatar) f.avatar_url = newAvatar;
        try { await api('/api/profile', { method: 'POST', body: JSON.stringify(f) }); $('#modal').innerHTML = ''; await hydrate(); render(); toast(newAvatar ? 'Profile photo updated 📸' : 'Profile saved'); }
        catch (error) { toast(error.message); }
      }; return;
    case 'joinActivity': done(state.joined ? 'You left the activity' : 'You joined the activity!'); return;
    case 'leaveActivity': done('You left the activity'); return;
    case 'friend':
      api('/api/friends/request', { method: 'POST', body: JSON.stringify({ user_id: id || 2 }) })
        .then(async () => { state.friends = true; await hydrate(); render(); toast('Friend request sent'); })
        .catch((e) => { if (/already|exist/i.test(e.message)) { state.friends = true; render(); toast('Already connected'); } else toast(e.message); });
      return;
    case 'acceptFriend':
      api('/api/friendships/respond', { method: 'POST', body: JSON.stringify({ request_id: id, decision: 'accept' }) })
        .then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData('friends'); render(); toast("Friend added — you're in each other's circle 🎉"); })
        .catch(e => toast(e.message)); return;
    case 'rejectFriend':
      api('/api/friendships/respond', { method: 'POST', body: JSON.stringify({ request_id: id, decision: 'decline' }) })
        .then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData('friends'); render(); toast('Request declined'); })
        .catch(e => toast(e.message)); return;
    case 'like': api(`/api/posts/${id}/like`, { method: 'POST', body: '{}' }).then(async () => { if (state.page === 'reels' || state.page === 'posts') { if ((state.prTab || 'reels') === 'reels') { pageData.reels = (await api('/api/reels')).items || []; } else { pageData.feed = (await api('/api/feed')).items || []; } render(); } else { await hydrate(); render(); } }).catch(e => toast(e.message)); return;
    case 'comment': openComments(id); return;
    case 'share': {
      const url = `${location.origin}/?post=${id}`;
      if (navigator.share) navigator.share({ title: 'FITVERSE', url }).catch(() => {});
      else { navigator.clipboard?.writeText(url).then(() => toast('Post link copied')).catch(() => toast(`Share link: ${url}`)); }
      return;
    }
    case 'postMenu': {
      modal(`<span class="eyebrow">POST OPTIONS</span><h2>What next?</h2><div class="create-options" style="grid-template-columns:1fr"><button data-action="savePost" data-id="${id}">🔖<b>Save post</b><small>Keep it for later</small></button><button data-action="copyPost" data-id="${id}">↗<b>Copy link</b><small>Share anywhere</small></button><button data-action="reportPost" data-id="${id}">⚑<b>Report</b><small>Flag for moderators</small></button></div>`);
      bind(); return;
    }
    case 'savePost': api(`/api/posts/${id}/save`, { method: 'POST', body: '{}' }).then(async (d) => { $('#modal').innerHTML = ''; await hydrate(); render(); toast(d.saved ? 'Post saved' : 'Post removed from saved'); }).catch(e => toast(e.message)); return;
    case 'copyPost': navigator.clipboard?.writeText(`${location.origin}/?post=${id}`).then(() => toast('Link copied')).catch(() => toast('Could not copy link')); $('#modal').innerHTML = ''; return;
    case 'reportPost':
      modal(`<span class="eyebrow">REPORT</span><h2>Flag this content</h2><form class="activity-form" id="report-form"><label>Reason<input name="reason" value="Inappropriate content" required></label><button class="primary" type="submit">Submit report</button></form>`);
      $('#report-form').onsubmit = async (e) => {
        e.preventDefault(); const reason = new FormData(e.currentTarget).get('reason');
        try { await api('/api/reports', { method: 'POST', body: JSON.stringify({ target_type: 'post', target_id: id, reason }) }); $('#modal').innerHTML = ''; toast('Report submitted — moderators will review'); }
        catch (err) { toast(err.message); }
      }; bind(); return;
    case 'personMenu': {
      const p = pageData.users.find(x => x.id === id) || pageData.recommendations.find(x => x.id === id) || {};
      modal(`<span class="eyebrow">${escapeHtml(p.name || 'ATHLETE')}</span><h2>@${escapeHtml(p.username || '')}</h2><p>${escapeHtml(p.favorite_activity || p.activity || '')} · ${escapeHtml(p.fitness_level || p.fitnessLevel || '')} · ${escapeHtml(p.preferred_time || p.preferredTime || '')}</p><div class="create-options" style="grid-template-columns:1fr"><button data-action="friend" data-id="${id}">＋<b>Add friend</b><small>Send a friend request</small></button><button data-action="challenge" data-id="${id}">⚡<b>Challenge</b><small>Start a head-to-head</small></button><button data-action="messageUser" data-id="${id}">✉<b>Message</b><small>Open a chat</small></button></div>`);
      bind(); return;
    }
    case 'messageUser': {
      $('#modal').innerHTML = '';
      if (!sessionToken) { action('account', btn); return; }
      const uid = id;
      state.page = 'messages'; render();
      (async () => {
        try {
          const r = await api('/api/dm/start', { method: 'POST', body: JSON.stringify({ to_user_id: uid }) });
          pageData.activeConversation = r.conversation_id;
          pageData.conversations = (await api('/api/conversations')).items || [];
          render(); loadMessages(); window.scrollTo(0, 0);
        } catch (e) { toast(e.message); }
      })();
      return;
    }
    case 'athlete': {
      $('#modal').innerHTML = '';
      pushTrail('athleteProfile'); state.page = 'athleteProfile'; state.detailId = id; pageData.detailData = null;
      render(); loadPageData('athleteProfile'); window.scrollTo(0, 0);
      return;
    }
    case 'communityOpen': {
      $('#modal').innerHTML = '';
      pushTrail('communityDetail'); state.page = 'communityDetail'; state.detailId = id; pageData.detailData = null;
      render(); loadPageData('communityDetail'); window.scrollTo(0, 0);
      return;
    }    case 'businessDetail': {
      (async () => {
        try {
          const { item: b } = await api(`/api/businesses/${id}`);
        modal(`<div class="detail-photo" style="background-image:url('img/${b.photo || 'workout.jpg'}')"></div><span class="eyebrow">${escapeHtml(b.category.toUpperCase())}</span><h2>${escapeHtml(b.name)}</h2><p>${escapeHtml(b.description || '')}</p><div class="compat"><span>⌖ ${escapeHtml(b.location_label)}</span><span class="stars">${'★'.repeat(Math.round(b.rating))}${'☆'.repeat(5 - Math.round(b.rating))}</span><b>${b.rating}</b></div><div class="hero-actions"><button class="primary" data-action="bizOpen" data-id="${b.id}">Open channel</button></div><span class="eyebrow" style="display:block;margin-top:14px">REVIEWS</span><div class="comment-list">${(b.reviews || []).map(r => `<div class="comment">${avatar(r.name, 'teal')}<div><strong>${escapeHtml(r.name)}</strong><p>${'★'.repeat(r.rating)}</p><p>${escapeHtml(r.body)}</p><small>${timeShort(r.created_at)}</small></div></div>`).join('') || '<p>No reviews yet — be the first.</p>'}</div><form class="activity-form" id="review-form"><label>Your rating<select name="rating"><option value="5">★★★★★</option><option value="4">★★★★</option><option value="3">★★★</option><option value="2">★★</option><option value="1">★</option></select></label><label>Your review<input name="body" placeholder="Great coaches, spotless floor..." required maxlength="600"></label><button class="primary" type="submit">Post review</button></form>`);
        bind();
        $('#review-form').onsubmit = async (e) => {
          e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
          try { await api('/api/reviews', { method: 'POST', body: JSON.stringify({ business_id: id, rating: Number(f.rating), body: f.body }) }); $('#modal').innerHTML = ''; action('businessDetail', { dataset: { id: String(id) } }); toast('Review posted'); }
          catch (err) { toast(err.message); }
        };
        } catch (e) { toast(e.message); }
      })();
      return;
    }
    case 'bizOpen': {
      (async () => {
        try {
          const probe = await api(`/api/businesses/${id}`);
          state.bizId = id; pushTrail('businessChannel'); pushTrail('businessChannel'); state.page = 'businessChannel'; render(); await loadPageData('businessChannel'); render(); window.scrollTo(0, 0);
        } catch (e) { toast(e.message); }
      })();
      return;
    }
    case 'bizCreate': {
      const cats = ['Gym', 'Yoga studio', 'Powerlifting gym', 'Running store', 'Sports academy', 'Cycling shop', 'Swim school', 'Climbing gym', 'Nutrition store', 'Personal training', 'Physiotherapy', 'Sports clinic'];
      modal(`<span class="eyebrow">BUSINESS OWNERS</span><h2>Add your business</h2><form class="activity-form" id="biz-form">
        <label>Business name<input name="name" required maxlength="100" placeholder="Powerhouse Fitness"></label>
        <label>Category<select name="category">${cats.map(c => `<option>${c}</option>`).join('')}</select></label>
        <label>Tagline<input name="tagline" maxlength="120" placeholder="Strength training for everyone"></label>
        <label>Description<textarea name="description" rows="3" maxlength="1200" placeholder="What makes your business special?"></textarea></label>
        <label>Area / locality<input name="location_label" maxlength="80" placeholder="Adyar, Chennai"></label>
        <label>Full address<input name="address" maxlength="200" placeholder="12 Beach Rd, Adyar"></label>
        <label>Website<input name="website" type="url" maxlength="200" placeholder="https://..."></label>
        <label>Phone<input name="phone" maxlength="30" placeholder="+91 ..."></label>
        <label>Opening hours (short)<input name="hours_note" maxlength="140" placeholder="Mon-Sat 6:00-22:00, Sun 7-13"></label>
        <div class="biz-map-hint">📍 Map pin: after creating, open your channel and use Edit profile to set latitude/longitude.</div>
        <button class="primary" type="submit">Create business channel</button></form>`);
      bind();
      $('#biz-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const btn = e.currentTarget.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Creating…';
        try {
          const r = await api('/api/businesses', { method: 'POST', body: JSON.stringify(f) });
          $('#modal').innerHTML = ''; toast('🏪 Business created — welcome to the ecosystem!');
          await loadPageData('businesses'); state.bizId = r.id; state.page = 'businessChannel'; render(); await loadPageData('businessChannel'); render();
        } catch (err) { btn.disabled = false; btn.textContent = 'Create business channel'; toast(err.message); }
      };
      return;
    }
    case 'bizOpenMine': state.bizId = id; state.page = 'businessChannel'; render(); loadPageData('businessChannel'); window.scrollTo(0, 0); return;
    case 'bizFollow': api(`/api/businesses/${id}/follow`, { method: 'POST', body: '{}' }).then(async (r) => { await loadPageData('businessChannel'); render(); toast(r.following ? 'Following — you\'ll see their posts' : 'Unfollowed'); }).catch(e => toast(e.message)); return;
    case 'bizEdit': {
      (async () => {
        const { item: b } = await api(`/api/businesses/${id}`);
        modal(`<span class="eyebrow">OWNER TOOLS</span><h2>Edit business</h2><form class="activity-form" id="biz-edit-form">
          <label>Name<input name="name" value="${escapeHtml(b.name || '')}" required maxlength="100"></label>
          <label>Tagline<input name="tagline" value="${escapeHtml(b.tagline || '')}" maxlength="120"></label>
          <label>Description<textarea name="description" rows="3" maxlength="1200">${escapeHtml(b.description || '')}</textarea></label>
          <label>Area / locality<input name="location_label" value="${escapeHtml(b.location_label || '')}" maxlength="80"></label>
          <label>Address<input name="address" value="${escapeHtml(b.address || '')}" maxlength="200"></label>
          <label>Website<input name="website" value="${escapeHtml(b.website || '')}" maxlength="200"></label>
          <label>Phone<input name="phone" value="${escapeHtml(b.phone || '')}" maxlength="30"></label>
          <label>Opening hours (short)<input name="hours_note" value="${escapeHtml(b.hours_note || '')}" maxlength="140"></label>
          <label>Latitude<input name="lat" type="number" step="any" value="${b.lat ?? ''}" placeholder="13.0068"></label>
          <label>Longitude<input name="lng" type="number" step="any" value="${b.lng ?? ''}" placeholder="80.2573"></label>
          <div class="biz-map-hint">Tip: right-click your spot on <a href="https://www.openstreetmap.org" target="_blank" rel="noopener">openstreetmap.org</a> and copy the latitude/longitude.</div>
          <button class="primary" type="submit">Save changes</button></form>`);
        bind();
        $('#biz-edit-form').onsubmit = async (e) => {
          e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
          try { await api(`/api/businesses/${id}/edit`, { method: 'POST', body: JSON.stringify(f) }); $('#modal').innerHTML = ''; toast('Business updated'); await loadPageData('businessChannel'); render(); }
          catch (err) { toast(err.message); }
        };
      })();
      return;
    }
    case 'bizAddProduct': {
      modal(`<span class="eyebrow">OWNER TOOLS</span><h2>Add product or service</h2><form class="activity-form" id="biz-prod-form">
        <label>Name<input name="name" required maxlength="120" placeholder="Monthly strength membership"></label>
        <label>Description<textarea name="description" rows="2" maxlength="600" placeholder="What's included?"></textarea></label>
        <label>Price<input name="price" maxlength="40" placeholder="₹2,500 / month"></label>
        <label>Link<input name="link" type="url" maxlength="300" placeholder="https://... (optional)"></label>
        <label>Image<input name="img" type="file" accept="image/*"></label>
        <button class="primary" type="submit">Add product</button></form>`);
      bind();
      $('#biz-prod-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const btn = e.currentTarget.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Saving…';
        try {
          let image = '';
          const fileInput = e.currentTarget.querySelector('input[name=img]');
          if (fileInput.files && fileInput.files[0]) {
            const r = await uploadImageFile(fileInput.files[0]);
            if (r && r.path) image = r.path;
          }
          await api(`/api/businesses/${id}/products`, { method: 'POST', body: JSON.stringify({ ...f, image }) });
          $('#modal').innerHTML = ''; toast('Product added'); await loadPageData('businessChannel'); render();
        } catch (err) { btn.disabled = false; btn.textContent = 'Add product'; toast(err.message); }
      };
      return;
    }
    case 'bizAddPhoto': {
      modal(`<span class="eyebrow">OWNER TOOLS</span><h2>Add a photo</h2><form class="activity-form" id="biz-photo-form">
        <label>Photo<input name="img" type="file" accept="image/*" required></label>
        <button class="primary" type="submit">Upload photo</button></form>`);
      bind();
      $('#biz-photo-form').onsubmit = async (e) => {
        e.preventDefault();
        const fileInput = e.currentTarget.querySelector('input[name=img]');
        if (!fileInput.files || !fileInput.files[0]) return;
        const btn = e.currentTarget.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Uploading…';
        try {
          const r = await uploadImageFile(fileInput.files[0]);
          if (r && r.path) await api(`/api/businesses/${id}/photos`, { method: 'POST', body: JSON.stringify({ path: r.path }) });
          $('#modal').innerHTML = ''; toast('Photo added'); await loadPageData('businessChannel'); render();
        } catch (err) { btn.disabled = false; btn.textContent = 'Upload photo'; toast(err.message); }
      };
      return;
    }
    case 'bizSetHours': {
      modal(`<span class="eyebrow">OWNER TOOLS</span><h2>Opening hours</h2><form class="activity-form" id="biz-hours-form">
        <div class="biz-hours-presets"><button type="button" class="outline small" data-preset="weekday">Mon-Fri 6-22, Sat 7-14</button><button type="button" class="outline small" data-preset="daily">Every day 6-22</button><button type="button" class="outline small" data-preset="mornings">Mon-Sat 6-11</button></div>
        <label>Short hours note (shown on your profile)<input name="hours_note" maxlength="140" placeholder="Mon-Sat 6:00-22:00"></label>
        <button class="primary" type="submit">Save hours</button></form>`);
      bind();
      $$('#biz-hours-form [data-preset]').forEach(b => b.onclick = () => { $('#biz-hours-form [name=hours_note]').value = { weekday: 'Mon-Fri 6:00-22:00, Sat 7:00-14:00', daily: 'Every day 6:00-22:00', mornings: 'Mon-Sat 6:00-11:00' }[b.dataset.preset]; });
      $('#biz-hours-form').onsubmit = async (e) => {
        e.preventDefault(); const note = new FormData(e.currentTarget).get('hours_note');
        try {
          await api(`/api/businesses/${id}/hours`, { method: 'POST', body: JSON.stringify({ hours: {} }) });
          await api(`/api/businesses/${id}/edit`, { method: 'POST', body: JSON.stringify({ hours_note: note }) });
          $('#modal').innerHTML = ''; toast('Hours updated'); await loadPageData('businessChannel'); render();
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'bizCompose': {
      modal(`<span class="eyebrow">BUSINESS CHANNEL</span><h2>Write a post</h2><form class="activity-form" id="biz-post-form">
        <label>What's new?<textarea name="body" rows="4" maxlength="2000" required placeholder="New equipment, offers, events, tips…"></textarea></label>
        <label>Attach photo or video<input name="media" type="file" accept="image/*,video/*"></label>
        <button class="primary" type="submit">Publish to channel</button></form>`);
      bind();
      $('#biz-post-form').onsubmit = async (e) => {
        e.preventDefault(); const body = new FormData(e.currentTarget).get('body');
        const btn = e.currentTarget.querySelector('button[type=submit]'); btn.disabled = true; btn.textContent = 'Publishing…';
        try {
          let media_url = '';
          const fileInput = e.currentTarget.querySelector('input[name=media]');
          if (fileInput.files && fileInput.files[0]) {
            const isVid = fileInput.files[0].type.startsWith('video');
            const r = await uploadImageFile(fileInput.files[0], isVid);
            if (r && r.path) media_url = r.path;
          }
          await api(`/api/businesses/${id}/post`, { method: 'POST', body: JSON.stringify({ body, media_url }) });
          $('#modal').innerHTML = ''; toast('📣 Published to your followers'); await loadPageData('businessChannel'); render();
        } catch (err) { btn.disabled = false; btn.textContent = 'Publish to channel'; toast(err.message); }
      };
      return;
    }
    case 'dailyPlan': case 'dailyCoach': $('#modal').innerHTML = ''; state.page = 'coach'; render(); loadPageData('coach'); window.scrollTo(0, 0); return;
    case 'hcRemoveData': {
      (async () => {
        try { await api('/api/health/disconnect', { method: 'POST', body: JSON.stringify({ provider: 'health_connect' }) }); toast('Imported health data removed'); await loadPageData('connectHealth'); render(); }
        catch (e) { toast(e.message); }
      })();
      return;
    }
    case 'notificationsOpen': {
      (async () => {
        try {
          const data = await api('/api/notifications/center');
          const prefs = data.prefs || {};
          const CATS = [['friend', '👥', 'Friend requests'], ['message', '💬', 'Messages'], ['achievement', '🏆', 'Achievements'], ['challenge', '⚔️', 'Challenges'], ['workout', '🏋', 'Workouts'], ['hydration', '💧', 'Hydration'], ['event', '🎉', 'Events'], ['community', '◌', 'Community'], ['business', '📣', 'Businesses'], ['ai', '🤖', 'AI coach']];
          const ICONS = { friend: '👥', message: '💬', achievement: '🏆', challenge: '⚔️', workout: '🏋', hydration: '💧', event: '🎉', community: '◌', business: '📣', ai: '🤖', xp: '⚡', activity: '🏀' };
          modalWide(`<div class="notif-center notif-scroll"><div class="notif-head"><span class="eyebrow">NOTIFICATION CENTER</span><h2 style="font-size:20px;margin:2px 0">All activity</h2><button class="outline small" data-action="readNotifications">Mark all read</button></div>
          <div class="notif-list">${(data.items || []).slice(0, 30).map(n => {
            const jump = n.type === 'friend' || n.type === 'friend_request' ? 'friends' : n.type === 'event' || String(n.title || '').toLowerCase().includes('book') ? 'bookings' : n.type === 'community' ? 'communities' : n.type === 'challenge' ? 'challenges' : n.type === 'message' ? 'messages' : n.type === 'achievement' ? 'profile' : n.type === 'business' ? 'business' : null;
            return `<button class="notif-item ${n.is_read ? 'read' : ''}" data-notif-jump="${jump || ''}"><span class="notif-ico">${ICONS[n.type] || '🔔'}</span><div><b>${escapeHtml(n.title)}</b><p>${escapeHtml(n.body)}</p><small>${timeShort(n.created_at)}</small></div>${n.is_read ? '' : '<i class="notif-dot"></i>'}</button>`;
          }).join('') || '<p class="muted">No notifications yet — they\'ll appear here.</p>'}</div>
          <span class="eyebrow">PREFERENCES</span>
          <div class="notif-prefs">${CATS.map(([c, ic, label]) => `<label class="notif-pref"><span>${ic} ${label}</span><input type="checkbox" data-npref="${c}" ${prefs[c] && prefs[c].enabled ? 'checked' : ''}/></label>`).join('')}</div>
          <label class="notif-pref sound"><span>🔊 Notification sound</span><input type="checkbox" id="notif-sound-toggle" ${localStorage.getItem('fvSound') === '1' ? 'checked' : ''}/></label>
          <p class="hc-note">Sound is a subtle tone and only plays after you've interacted with the app (browser rule). Mute categories anytime.</p></div>`);
          bind();
          $$('#modal [data-notif-jump]').forEach(b => b.onclick = () => {
            const target = b.dataset.notifJump;
            $('#modal').innerHTML = '';
            if (target && target !== 'null') { state.page = target; render(); loadPageData(target); window.scrollTo(0, 0); }
          });
          $$('#modal [data-npref]').forEach(cb => cb.onchange = async () => {
            await api('/api/notifications/prefs', { method: 'POST', body: JSON.stringify({ category: cb.dataset.npref, enabled: cb.checked }) });
            toast(cb.checked ? 'Notifications on for this category' : 'Muted — you won\'t be notified');
          });
          const st = $('#notif-sound-toggle'); if (st) st.onchange = () => { localStorage.setItem('fvSound', st.checked ? '1' : '0'); if (st.checked) notifSound(); };
        } catch (e) { toast(e.message); }
      })();
      return;
    }
    case 'communityMenu': {
      modal(`<span class="eyebrow">COMMUNITY</span><h2>Options</h2><div class="create-options" style="grid-template-columns:1fr"><button data-action="joinCommunity" data-id="${id}">＋<b>Join community</b><small>Become a member</small></button><button data-action="reportCommunity" data-id="${id}">⚑<b>Report</b><small>Flag for moderators</small></button></div>`);
      bind(); return;
    }
    case 'reportCommunity':
      modal(`<span class="eyebrow">REPORT</span><h2>Flag this community</h2><form class="activity-form" id="report-form"><label>Reason<input name="reason" value="Inappropriate content" required></label><button class="primary" type="submit">Submit report</button></form>`);
      $('#report-form').onsubmit = async (e) => {
        e.preventDefault(); const reason = new FormData(e.currentTarget).get('reason');
        try { await api('/api/reports', { method: 'POST', body: JSON.stringify({ target_type: 'community', target_id: id, reason }) }); $('#modal').innerHTML = ''; toast('Report submitted'); } catch (err) { toast(err.message); }
      }; bind(); return;
    case 'joinCommunity': api(`/api/communities/${id}/join`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData(state.page); render(); toast('Welcome to the community!'); }).catch(e => toast(e.message)); return;
    case 'leaveCommunity': api(`/api/communities/${id}/leave`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData(state.page); render(); toast('You left the community'); }).catch(e => toast(e.message)); return;
    case 'eventDetail':
      (async () => {
        try {
          const { items } = await api('/api/events'); const ev = items.find(x => x.id === id);
          if (!ev) return toast('Event not found');
          modal(`<div class="detail-photo" style="background-image:url('img/${ev.photo}')"></div><span class="eyebrow">${escapeHtml(ev.category.toUpperCase())} · ${ev.booked_count}/${ev.capacity} TICKETS</span><h2>${escapeHtml(ev.name)}</h2><p>${escapeHtml(ev.description)}</p><div class="compat"><span>◷ ${dayShort(ev.starts_at)} · ${timeShort(ev.starts_at)}</span><span>⌖ ${escapeHtml(ev.location_label)}</span><span>🎟 ${inr(ev.price_inr)} · by ${escapeHtml(ev.organizer)}</span></div><div id="ev-wx" class="wx-chip">Loading event-day weather…</div><iframe class="map-embed" loading="lazy" src="https://www.openstreetmap.org/export/embed.html?bbox=80.15%2C12.90%2C80.36%2C13.16&layer=mapnik"></iframe><div class="hero-actions"><button class="primary" data-action="bookEvent" data-id="${ev.id}" ${ev.booked ? 'disabled' : ''}>${ev.booked ? 'Booked ✓' : `Book ${inr(ev.price_inr)}`}</button><a class="outline" href="/api/events/${ev.id}/calendar.ics" download style="text-decoration:none;display:inline-block">📅 Add to calendar</a></div>`);
          bind();
          fetch('https://api.open-meteo.com/v1/forecast?latitude=13.08&longitude=80.27&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=16')
            .then(r => r.json()).then(d => {
              const days = d.daily?.time || []; const idx = days.findIndex(t => t === ev.starts_at.slice(0, 10));
              const el = $('#ev-wx'); if (!el) return;
              if (d.error || !d.daily) { el.innerHTML = '⛅ Forecast updates closer to event day (live weather API rate-limited right now).'; return; }
              if (idx >= 0) el.innerHTML = `Event day: <b>${d.daily.temperature_2m_max[idx]}°C</b> high · ${d.daily.temperature_2m_min[idx]}°C low · 🌧️ ${d.daily.precipitation_probability_max[idx]}% rain chance`;
              else el.innerHTML = `📅 ${dayShort(ev.starts_at)} — forecast available ~16 days before the event.`;
            }).catch(() => {});
        } catch (e) { toast(e.message); }
      })();
      return;
    // FITVERSE 6.2: paid events show a UPI checkout step BEFORE the ticket;
    // free events book instantly. The booking POST carries the UPI reference.
    case 'bookEvent': {
      const ev = (pageData.events || []).find(e => e.id === Number(id));
      const price = Number(ev?.price_inr || 0);
      if (ev?.booked) { toast('Already booked ✓ — see My bookings'); return; }
      if (price > 0) {
        const evName = ev?.name || 'FITVERSE Event';
        const upiId = 'fitverse@upi';
        modal(`<span class="eyebrow">UPI CHECKOUT</span><h2>Pay ${inr(price)}</h2>
        <div class="ticket"><div class="qr">▦<br/>▥</div><div><b>${escapeHtml(evName)}</b><small>${dayShort(ev?.starts_at)} · ${escapeHtml(ev?.location_label || '')}</small></div></div>
        <div class="code" style="margin:12px 0;word-break:break-all">upi://pay?pa=${upiId}&pn=FITVERSE&am=${price}&cu=INR&tn=${encodeURIComponent('FITVERSE ' + evName)}</div>
        <p class="loading">Scan with any UPI app (GPay · PhonePe · Paytm · BHIM), or pay to <b>${upiId}</b>. Then paste the 12-digit UTR / reference number from your payment app to confirm.</p>
        <form class="activity-form" id="upi-form"><label>UPI reference / UTR number<input name="utr" required minlength="6" maxlength="30" placeholder="e.g. 415223456789"></label>
        <button class="primary" type="submit">✓ I've paid — confirm booking</button></form>
        <p class="loading est-note">Demo checkout: FITVERSE verifies the reference and issues your ticket instantly. Refunds land back on the same UPI ID.</p>`);
        bind();
        $('#upi-form').onsubmit = async (e2) => {
          e2.preventDefault();
          const utr = String(new FormData(e2.currentTarget).get('utr') || '').trim();
          const btn2 = e2.currentTarget.querySelector('button[type=submit]');
          if (btn2) { btn2.disabled = true; btn2.textContent = 'Verifying payment…'; }
          try {
            const d = await api(`/api/events/${id}/book`, { method: 'POST', body: JSON.stringify({ quantity: 1, payment_ref: utr, payment_method: 'upi' }) });
            $('#modal').innerHTML = ''; await loadPageData('events'); render();
            modal(`<span class="ticket-check">✓</span><span class="eyebrow">PAYMENT VERIFIED · BOOKING CONFIRMED</span><h2>You're in.</h2><div class="ticket"><div class="qr">▦<br/>▥</div><div><b>${escapeHtml(d.bookingCode)}</b><small>${dayShort(new Date().toISOString())} · Show at the gate</small></div></div><div class="hero-actions"><button class="primary" data-action="close">Done</button><button class="outline" data-action="downloadTicket" data-code="${escapeHtml(d.bookingCode)}" data-name="Event ticket">⬇ Download ticket</button></div>`);
            bind(); toast('Payment received — ticket issued 🎟');
          } catch (err) { if (btn2) { btn2.disabled = false; btn2.textContent = "✓ I've paid — confirm booking"; } toast(err.message); }
        };
        return;
      }
      api(`/api/events/${id}/book`, { method: 'POST', body: JSON.stringify({ quantity: 1, payment_method: 'free' }) })
        .then(async (d) => {
          $('#modal').innerHTML = ''; await loadPageData('events'); render();
          modal(`<span class="ticket-check">✓</span><span class="eyebrow">FREE ENTRY CONFIRMED</span><h2>You're in.</h2><div class="ticket"><div class="qr">▦<br/>▥</div><div><b>${escapeHtml(d.bookingCode)}</b><small>${dayShort(new Date().toISOString())} · Show at the gate</small></div></div><div class="hero-actions"><button class="primary" data-action="close">Done</button><button class="outline" data-action="downloadTicket" data-code="${escapeHtml(d.bookingCode)}" data-name="Event ticket">⬇ Download ticket</button></div>`);
          toast('Booked — see you there'); bind();
        }).catch(e => toast(e.message));
      return;
    }
    case 'downloadTicket': {
      const code = btn?.dataset?.code || 'FITVERSE-TICKET';
      const evName = btn?.dataset?.name || 'FITVERSE Event';
      const w = open('', '_blank');
      if (!w) { toast('Allow pop-ups to download your ticket'); return; }
      w.document.write(`<!doctype html><title>Ticket ${escapeHtml(code)}</title><body style="font-family:Arial,sans-serif;background:#0a0f22;color:#eaf2ff;display:grid;place-items:center;min-height:100vh;margin:0">
      <div style="border:2px dashed rgba(0,229,255,.6);border-radius:18px;padding:34px;text-align:center;background:linear-gradient(160deg,rgba(22,28,58,.9),rgba(9,13,30,.95))">
      <p style="letter-spacing:2px;font-size:11px;color:#00e5ff;margin:0">FITVERSE · OFFICIAL TICKET</p>
      <h1 style="margin:10px 0">${escapeHtml(evName)}</h1>
      <div style="font-size:40px;letter-spacing:6px;margin:14px 0;font-weight:800">${escapeHtml(code)}</div>
      <p style="color:#93a0c8;margin:0">Show this code at the gate · Screenshot or print this page</p>
      <button onclick="window.print()" style="margin-top:18px;padding:10px 22px;border-radius:10px;border:0;background:linear-gradient(92deg,#00e5ff,#8b5cf6);color:#04060f;font-weight:800;cursor:pointer">⬇ Save / Print ticket</button></div></body>`);
      w.document.close();
      return;
    }
    case 'bookingsDownload': {
      const code = btn?.dataset?.code, nm = btn?.dataset?.name || 'Event';
      const w2 = open('', '_blank');
      if (!w2) { toast('Allow pop-ups to download your ticket'); return; }
      w2.document.write(`<!doctype html><title>Ticket ${escapeHtml(code)}</title><body style="font-family:Arial,sans-serif;background:#0a0f22;color:#eaf2ff;display:grid;place-items:center;min-height:100vh;margin:0">
      <div style="border:2px dashed rgba(0,229,255,.6);border-radius:18px;padding:34px;text-align:center;background:linear-gradient(160deg,rgba(22,28,58,.9),rgba(9,13,30,.95))">
      <p style="letter-spacing:2px;font-size:11px;color:#00e5ff;margin:0">FITVERSE · OFFICIAL TICKET</p>
      <h1 style="margin:10px 0">${escapeHtml(nm)}</h1>
      <div style="font-size:40px;letter-spacing:6px;margin:14px 0;font-weight:800">${escapeHtml(code)}</div>
      <p style="color:#93a0c8;margin:0">Show this code at the gate · Screenshot or print this page</p>
      <button onclick="window.print()" style="margin-top:18px;padding:10px 22px;border-radius:10px;border:0;background:linear-gradient(92deg,#00e5ff,#8b5cf6);color:#04060f;font-weight:800;cursor:pointer">⬇ Save / Print ticket</button></div></body>`);
      w2.document.close();
      return;
    }
    case 'eventFilter': toast('Filters coming to the demo soon — all categories shown'); return;
    case 'challenge': {
      let chFriends = (pageData.challengeFriends || []);
      if (!chFriends.length) { try { chFriends = (await api('/api/challenges')).friends || []; } catch (_) {} pageData.challengeFriends = chFriends; }
      if (!chFriends.length) { toast('Add a friend first — challenges are between real friends'); return; }
      modal(`<span class="eyebrow">NEW CHALLENGE</span><h2>Start a rivalry</h2><form class="activity-form" id="challenge-form"><label>Challenge a friend<select name="opponent_id">${chFriends.map(u => `<option value="${u.id}" ${Number(pageData.challengePreselect || 0) === u.id ? 'selected' : ''}>${escapeHtml(u.name)}</option>`).join('')}</select></label><label>Type<select name="challenge_type"><option value="running_distance">Running distance (km)</option><option value="gym_sessions">Gym sessions</option><option value="cycling_distance">Cycling distance (km)</option></select></label><label>Target value<input name="target_value" type="number" value="5" min="1" step="0.5"></label><button class="primary" type="submit">Send challenge</button></form>`);
      $('#challenge-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/challenges', { method: 'POST', body: JSON.stringify({ ...f, opponent_id: Number(f.opponent_id), target_value: Number(f.target_value) }) }); $('#modal').innerHTML = ''; await loadPageData('challenges'); state.page = 'challenges'; render(); toast('Challenge sent!'); }
        catch (error) { toast(error.message); }
      }; bind(); return;
    }
    case 'challengeView': toast(`Challenge ${id}: ${state.challenge === 'won' ? 'you won this one' : 'keep pushing!'}`); return;
    case 'chAccept': {
      try { await api('/api/challenges/' + id + '/accept', { method: 'POST', body: '{}' }); toast('Challenge accepted — game on! ⚔️'); await loadPageData('challenges'); render(); } catch (e) { toast(e.message); }
      return;
    }
    case 'chDecline': {
      try { await api('/api/challenges/' + id + '/decline', { method: 'POST', body: '{}' }); toast('Challenge declined.'); await loadPageData('challenges'); render(); } catch (e) { toast(e.message); }
      return;
    }
    case 'chProgress': {
      const target = btn.dataset.target || 5;
      modal(`<span class="eyebrow">LOG PROGRESS</span><h2>How much did you add?</h2><form class="activity-form" id="chp-form"><label>Progress amount<input name="amount" type="number" min="0.1" step="0.1" value="1" required/><small style="color:var(--muted)">Challenge target: ${target}</small></label><button class="primary" type="submit">Add progress</button></form>`);
      bind();
      $('#chp-form').onsubmit = async (e) => {
        e.preventDefault();
        const amount = Number(Object.fromEntries(new FormData(e.currentTarget)).amount);
        try {
          const res = await api('/api/challenges/' + id + '/progress', { method: 'POST', body: JSON.stringify({ amount }) });
          $('#modal').innerHTML = '';
          if (res.completed && res.completed.won) { celebrate(1); toast(`🏆 Challenge won! +${res.completed.xp} XP`); }
          else toast(`Progress logged: ${res.progress}/${target}`);
          await loadPageData('challenges'); state.page = 'challenges'; render();
        } catch (e) { toast(e.message); }
      };
      return;
    }
    case 'chInvite': {
      const friends = pageData.challengeFriends && pageData.challengeFriends.length ? pageData.challengeFriends : [];
      if (!friends.length) { toast('Add friends first, then pull them into your challenges!'); return; }
      modal(`<span class="eyebrow">INVITE TO CHALLENGE</span><h2>Pull someone in</h2><div class="pick-list">${friends.map(f => `<button data-action="chInvitePick" data-id="${f.id}" data-cid="${id}">${escapeHtml(f.name)}</button>`).join('')}</div>`);
      bind();
      return;
    }
    case 'chInvitePick': {
      try {
        const res = await api('/api/challenges/' + Number(btn.dataset.cid) + '/invite', { method: 'POST', body: JSON.stringify({ friend_id: Number(btn.dataset.id) }) });
        $('#modal').innerHTML = ''; toast(`Invited ${res.invited} 🤝`);
      } catch (e) { toast(e.message); }
      return;
    }
    case 'accept': done('Challenge accepted — game on!'); return;
    case 'win': done('Challenge complete! +120 XP'); return;
    case 'complete': done('Activity logged! +80 XP'); return;
    case 'coachPrompt': api('/api/coach?q=' + encodeURIComponent(btn.dataset.q)).then(r => { pageData.coach = r.reply; render(); }).catch(e => toast(e.message)); return;
    case 'resolveReport': api(`/api/reports/${id}/resolve`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData('admin'); render(); toast('Report resolved'); }).catch(e => toast(e.message)); return;
    case 'filters': toast('Filters: matching is automatic for now'); return;
    case 'convMenu': await shareChatModal(id); return;
    case 'newChatPick': {
      const fidN = Number(btn.dataset.fid || 0);
      if (!fidN) { return; }
      try {
        const r = await api('/api/dm/start', { method: 'POST', body: JSON.stringify({ to_user_id: fidN }) });
        pageData.activeConversation = r.conversation_id;
        $('#modal').innerHTML = '';
        state.page = 'messages'; render();
        pageData.conversations = (await api('/api/conversations')).items || [];
        render(); loadMessages();
      } catch (e) { toast(e.message); }
      return;
    }
    case 'joinActivityById': api(`/api/activities/${id}/join`, { method: 'POST', body: '{}' }).then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast('You joined! See you there'); }).catch(e => toast(e.message)); return;
    case 'leaveActivity': api(`/api/activities/${id}/leave`, { method: 'POST', body: '{}' }).then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast('You left the activity'); }).catch(e => toast(e.message)); return;
    case 'completeActivity': api(`/api/activities/${id}/complete`, { method: 'POST', body: '{}' }).then(async (d) => { $('#modal').innerHTML = ''; if (d.state) applyServerState(d.state); await hydrate(); await loadPageData(state.page); render(); toast(d.message || '+80 XP earned!'); }).catch(e => toast(e.message)); return;
    case 'createPost': openComposer('post'); return;
    case 'createReel': openComposer('reel'); return;
    case 'activityDetail': activityDetail(id); return;
    // ===== FITVERSE 2.0 actions =====
    case 'woToggle': {
      if (btn.closest('[data-stop]')) return;
      pageData.openSession = pageData.openSession === id ? 0 : id;
      render();
      return;
    }
    case 'woFilter': pageData.woFilter = btn.dataset.id || ''; render(); return;
    case 'woDelete': {
      if (!confirm('Delete this workout session? Its volume and PRs are removed from your history.')) return;
      try { await api(`/api/workouts/${id}`, { method: 'POST', body: '{}' }); pageData.openSession = 0; await loadPageData('workout'); await hydrate(); render(); toast('Session deleted'); }
      catch (e) { toast(e.message); }
      return;
    }
    case 'woRest': {
      const mins = 2; let left = mins * 60;
      modal(`<span class="eyebrow">⏱ REST TIMER</span><h2>Chill — I'll call you.</h2><div class="scan-result"><div class="scan-big"><b id="rest-num">${mins}:00</b><em>rest remaining</em></div></div><div class="hero-actions"><button class="outline" data-action="close">Skip rest</button></div>`);
      bind();
      const iv = setInterval(() => {
        left -= 1;
        const el = $('#rest-num');
        if (!el) { clearInterval(iv); return; }
        el.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
        if (left <= 0) { clearInterval(iv); el.textContent = "GO!"; notifSound(); toast("Rest over — next set 💪"); setTimeout(() => { $('#modal').innerHTML = ''; }, 900); }
      }, 1000);
      return;
    }
    case 'woAiTweak': {
      const s = (pageData.workouts || []).find(x => x.id === id); if (!s) return;
      const kind = btn.dataset.k;
      const params = {
        goal: kind === 'harder' ? 'build muscle' : kind === 'easier' ? 'general fitness' : 'build muscle',
        duration: s.duration_min || 45, style: kind === 'swap' ? 'full' : 'push',
        equipment: 'Full gym', harder: kind === 'harder', easier: kind === 'easier', fast: true,
      };
      toast(kind === 'harder' ? '🔥 Leveling it up…' : kind === 'easier' ? '🪶 Easing it down…' : '⇄ Swapping exercises…');
      try {
        const plan = (await api('/api/ai/workout', { method: 'POST', body: JSON.stringify(params) })).item || {};
        const exs = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
        pageData.exercises = exs;
        const byIdT = Object.fromEntries(exs.map(e => [String(e.id), e.id]));
        const byNameT = Object.fromEntries(exs.map(e => [e.name, e.id]));
        pageData.activeSession = { title: plan.title || `${kind === 'harder' ? 'Harder' : kind === 'easier' ? 'Lighter' : 'Remixed'} ${s.title}`, startedAt: new Date().toISOString(), logs: (plan.items || []).map(x => ({ exercise_id: (x.id && byIdT[String(x.id)]) || byNameT[x.exercise] || 0, sets: x.sets || 3, reps: parseInt(x.reps) || 10, weight: Math.round(((s.logs || []).find(l => l.name === x.exercise)?.weight) || 0) })).filter(x => x.exercise_id) };
        state.page = 'workout'; render();
        toast('✦ Loaded into your session — set weights and FINISH WORKOUT');
        window.scrollTo(0, 0);
      } catch (e) { toast(e.message); }
      return;
    }
    case 'fsStart': {
      const exs0 = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
      pageData.exercises = exs0;
      pageData.activeSession = { title: 'Training session', startedAt: new Date().toISOString(), logs: [{ exercise_id: exs0[0]?.id || 0, sets: 3, reps: 10, weight: 0 }] };
      render(); toast('Session started — fill it in, then hit FINISH WORKOUT');
      return;
    }
    case 'fsAddRow': {
      const s1 = pageData.activeSession; if (!s1) return;
      const exs1 = pageData.exercises || [];
      s1.logs.push({ exercise_id: exs1[0]?.id || 0, sets: 3, reps: 10, weight: 0 });
      render();
      return;
    }
    case 'fsRemoveRow': {
      const s2 = pageData.activeSession; if (!s2) return;
      s2.logs.splice(Number(btn.dataset.i), 1);
      render();
      return;
    }
    case 'fsAiFill': {
      const s3 = pageData.activeSession; if (!s3) return;
      try {
        toast('✦ AI is building your session…');
        const plan = (await api('/api/ai/workout', { method: 'POST', body: JSON.stringify({ goal: 'Build muscle', duration: 45, style: 'full', equipment: 'Full gym', fast: true }) })).item || {};
        const exs3 = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
        pageData.exercises = exs3;
        const byId3 = Object.fromEntries(exs3.map(e => [String(e.id), e.id]));
        const byName3 = Object.fromEntries(exs3.map(e => [e.name, e.id]));
        s3.title = plan.title || s3.title;
        s3.logs = (plan.items || []).map(x => ({ exercise_id: (x.id && byId3[String(x.id)]) || byName3[x.exercise] || 0, sets: x.sets || 3, reps: parseInt(x.reps) || 10, weight: 0 })).filter(x => x.exercise_id);
        render(); toast(`✦ AI filled ${s3.logs.length} exercises — set your weights, then FINISH`);
      } catch (e) { toast(e.message); }
      return;
    }
    case 'fsDiscard': {
      pageData.activeSession = null; render(); toast('Session discarded');
      return;
    }
    case 'fsFinish': {
      const s4 = pageData.activeSession; if (!s4) return;
      const rows = $$('#fs-rows .wo-row');
      rows.forEach((r, i) => { if (!s4.logs[i]) return; $$('select,input', r).forEach(el => { if (el.dataset.k) s4.logs[i][el.dataset.k] = el.tagName === 'SELECT' ? Number(el.value) : Number(el.value); }); });
      s4.logs = s4.logs.filter(x => x.exercise_id && (x.sets > 0 && x.reps > 0));
      if (!s4.logs.length) { toast('Add at least one exercise with sets & reps'); return; }
      s4.finishing = true; render();
      try {
        // FITVERSE 6.2: anything the AI generated but that is not in the library
        // yet (or the user hand-picked "Add new exercise…") is auto-created
        // server-side (created_by_ai) BEFORE the workout POST — nothing bounces.
        const known = new Set((pageData.exercises || []).map(e => e.id));
        const pendingNames = new Map();
        for (const x of s4.logs) {
          if (x.exercise_id === 'NEW' && x.name) pendingNames.set(x.name, x);
          else if (x.exercise_id === 'NEW' && x.ai_name) pendingNames.set(x.ai_name, x);
          else if (!known.has(Number(x.exercise_id)) && x.__pendingName) pendingNames.set(x.__pendingName, x);
        }
        for (const [nm, x] of pendingNames) {
          try {
            const r2 = await api('/api/exercises', { method: 'POST', body: JSON.stringify({ name: nm, muscle: x.muscle || 'Full Body', equipment: 'Mat / bodyweight', created_by_ai: true }) });
            x.exercise_id = r2.exercise_id;
            if (r2.exercise_id && !known.has(r2.exercise_id)) pageData.exercises.push({ id: r2.exercise_id, name: nm, muscle: x.muscle || 'Full Body' });
          } catch (_) {}
        }
        if (s4.logs.some(x => !x.exercise_id || x.exercise_id === 'NEW')) { s4.finishing = false; render(); toast('Some exercises could not be saved — try again'); return; }
        const dur = Math.max(5, Math.round((Date.now() - new Date(s4.startedAt).getTime()) / 60000)) || 45;
        const res = await api('/api/workouts', { method: 'POST', body: JSON.stringify({ title: s4.title, duration_min: dur, logs: s4.logs.map(x => ({ exercise_id: Number(x.exercise_id), sets: Number(x.sets), reps: Number(x.reps), weight: Number(x.weight) })) }) });
        pageData.activeSession = null;
        dispatchEvent(new CustomEvent('fv:data-updated', { detail: { week: { sessions: (pageData.dash?.week?.sessions || 0) + 1, kcal: (pageData.dash?.week?.kcal || 0) + (res.est_kcal || 0) } } }));
        if (res.pr_count > 0) celebrate(res.pr_count);
        modal(`<span class="ticket-check">✓</span><span class="eyebrow">WORKOUT FINISHED</span><h2>Beast mode complete 💪</h2>
        <div class="scan-result"><div class="scan-big"><b>${(res.total_volume || 0).toLocaleString()}</b><em>kg total volume</em></div>
        <div class="scan-macros"><span><b>${res.est_kcal || '—'}</b><small>kcal burned</small></span><span><b>${res.pr_count || 0}</b><small>new PR${res.pr_count === 1 ? '' : 's'}</small></span></div></div>
        <p class="loading est-note">Saved to your history — your streak, weekly goal, PRs and AI coach now reflect this session.</p>
        <div class="hero-actions"><button class="primary" data-action="close">Done</button><button class="outline" data-action="weeklyReview">View recap</button></div>`);
        bind();
        // FITVERSE 6.1/6.2: the summary modal must SURVIVE the data refresh.
        // #modal lives inside #app, so every render() (including the ones
        // loadPageData fires internally) would wipe it — skip renders until
        // the refresh is fully done, then repaint the page underneath.
        render.__skip = true;
        try { await hydrate(); await loadPageData('workout'); state.page = 'workout'; render(); }
        finally { render.__skip = false; }
        toast(`Finished · ${(res.total_volume || 0).toLocaleString()} kg volume · +60 XP${res.pr_count ? ` · 🔥 ${res.pr_count} PR!` : ''}`);
      } catch (err) { s4.finishing = false; render(); toast(err.message); }
      return;
    }
    case 'logWorkout': {
      const exs = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
      pageData.exercises = exs;
      modal(`<span class="eyebrow">LOG WORKOUT</span><h2>How did it go?</h2><form class="activity-form" id="wo-form">
      <label>Session title<input name="title" value="Training session" required maxlength="80"></label>
      <label>Duration (minutes)<input name="duration_min" type="number" value="45" min="5" max="240"></label>
      <div class="wo-head"><span>EXERCISE</span><span>SETS</span><span>REPS</span><span>WEIGHT (KG)</span></div>
      <div id="wo-rows"><div class="wo-row"><select name="exercise_id">${exs.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${e.muscle})</option>`).join('')}</select><input name="sets" type="number" value="3" min="1" max="20" aria-label="Sets" placeholder="3"/><input name="reps" type="number" value="10" min="1" max="100" aria-label="Reps" placeholder="10"/><input name="weight" type="number" value="0" min="0" step="0.5" aria-label="Weight in kg" placeholder="0"/></div></div>
      <button type="button" class="outline small" id="wo-add">＋ Add exercise</button>
      <button type="button" class="outline small" id="wo-custom">✚ Add custom exercise</button>
      <button class="primary" type="submit">Save workout</button></form>`);
      bind();
      $('#wo-add').onclick = () => $('#wo-rows').insertAdjacentHTML('beforeend', `<div class="wo-row"><select name="exercise_id">${exs.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${e.muscle})</option>`).join('')}</select><input name="sets" type="number" value="3" min="1" max="20" aria-label="Sets"/><input name="reps" type="number" value="10" min="1" max="100" aria-label="Reps"/><input name="weight" type="number" value="0" min="0" step="0.5" aria-label="Weight"/></div>`);
      $('#wo-custom').onclick = () => customExerciseModal(async () => { try { const d = await api('/api/exercises'); pageData.exercises = d.items || []; $('#modal').innerHTML = ''; action('logWorkout', null); } catch (e) { toast(e.message); } });
      $('#wo-form').onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        const rows = $$('#wo-rows .wo-row').map(r => { const fd = new FormData(); $$("select,input", r).forEach(el => fd.append(el.name, el.value)); return Object.fromEntries(fd); });
        try {
          const res = await api('/api/workouts', { method: 'POST', body: JSON.stringify({ title: f.get('title'), duration_min: Number(f.get('duration_min')), logs: rows.map(r => ({ exercise_id: Number(r.exercise_id), sets: Number(r.sets), reps: Number(r.reps), weight: Number(r.weight) })) }) });
          $('#modal').innerHTML = '';
          if (res.pr_count > 0) celebrate(res.pr_count);
          if (res.mission_completed) toast(`🎯 Mission complete: ${res.mission_completed.completed} · +${res.mission_completed.xp} XP!`);
          else toast(`Workout saved! ${res.pr_count ? `🔥 ${res.pr_count} PR${res.pr_count > 1 ? 's' : ''}!` : '+60 XP'}`);
          await hydrate(); await loadPageData('workout'); state.page = 'workout'; render();
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'customExercise':
      customExerciseModal(async () => { try { const d = await api('/api/exercises'); pageData.exercises = d.items || []; if (state.page === 'library') await loadPageData('library'); render(); } catch (e) { toast(e.message); } });
      return;
    case 'generateWorkout': {
      modal(`<span class="eyebrow">✦ AI GENERATOR</span><h2>Build my workout</h2><form class="activity-form" id="gen-form">
      <label>Goal<select name="goal"><option>Build muscle</option><option>Lose fat</option><option>Get stronger</option><option>Endurance</option></select></label>
      <label>Duration (min)<select name="duration"><option>30</option><option selected>45</option><option>60</option><option>75</option></select></label>
      <label>Focus<select name="style"><option value="upper">Upper body</option><option value="lower">Lower body</option><option value="push">Push (chest/shoulders/arms)</option><option value="pull">Pull (back/arms)</option><option value="legs">Legs & glutes</option><option value="full">Full body</option></select></label>
      <label>Equipment<select name="equipment"><option>Full gym</option><option>Home dumbbells</option><option>Bodyweight</option></select></label>
      <div class="wo-style-chips" style="margin:10px 0 4px"><button type="button" class="chip ${pageData.genStyle === 'cardio' ? 'active' : ''}" data-action="genStyle" data-style="cardio">🏃 Cardio</button><button type="button" class="chip ${pageData.genStyle === 'home' ? 'active' : ''}" data-action="genStyle" data-style="home">🏠 Home</button><button type="button" class="chip ${pageData.genStyle === 'yoga' ? 'active' : ''}" data-action="genStyle" data-style="yoga">🧘 Yoga</button><button type="button" class="chip ${pageData.genStyle === 'gentle' ? 'active' : ''}" data-action="genStyle" data-style="gentle">🪶 Gentle</button><button type="button" class="chip ${!pageData.genStyle ? 'active' : ''}" data-action="genStyle" data-style="">💪 Strength</button></div>
      <p class="loading est-note">Cardio, Home and Yoga build gentle, low-impact sessions — ideal if you manage BP or sugar, or just want an easy day.</p>
      <button class="primary" type="submit">✦ Generate</button></form>`);
      bind();
      $('#gen-form').onsubmit = async (e) => {
        e.preventDefault();
        const f = Object.fromEntries(new FormData(e.currentTarget));
        const style = pageData.genStyle || f.style || 'full';
        const styleMap = { upper: ['Chest', 'Back', 'Shoulders'], lower: ['Legs', 'Glutes', 'Core'], push: ['Chest', 'Shoulders', 'Arms'], pull: ['Back', 'Arms'], legs: ['Legs', 'Glutes'], full: ['Chest', 'Back', 'Legs', 'Core'] };
        try {
          const body = style === 'gentle'
            ? { goal: f.goal.toLowerCase(), duration: Number(f.duration), equipment: f.equipment, muscles: styleMap[f.style], easy: true, fast: true }
            : { goal: f.goal.toLowerCase(), duration: Number(f.duration), equipment: f.equipment, muscles: styleMap[f.style], style };
          const { item: plan } = await api('/api/ai/workout', { method: 'POST', body: JSON.stringify(body) });
          if (!plan.items || !plan.items.length) return toast('Could not build that plan — try more equipment options');
          modal(`<span class="eyebrow">✦ GENERATED</span><h2>${escapeHtml(plan.title)}</h2><p class="loading">~${plan.est_kcal} kcal · ${plan.items.length} exercises</p>
          <div class="gen-plan">${plan.items.map((x, i) => `<div class="gen-row"><div><b>${i + 1}. ${escapeHtml(x.exercise)}</b><small>${x.sets} sets × ${x.reps} reps · rest ${x.rest_s}s · ${x.tempo} tempo</small><small class="dim">Alt: ${escapeHtml(x.alt)}</small></div><button class="more" data-action="replaceEx" data-i="${i}" title="Replace">⇄</button></div>`).join('')}</div>
          <p class="loading">${escapeHtml(plan.note)}</p>
          <div class="hero-actions"><button class="primary" data-action="genLogIt">Log this workout</button><button class="outline" data-action="genHarder">Make it harder</button><button class="outline" data-action="genEasier">Make it easier</button></div>`);
          bind();
          window.__lastPlan = plan;
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'genHarder': case 'genEasier': {
      const p = window.__lastPlan; if (!p) return;
      const body = { ...p.params, harder: a === 'genHarder', easier: a === 'genEasier' };
      const { item: plan } = await api('/api/ai/workout', { method: 'POST', body: JSON.stringify(body) });
      window.__lastPlan = plan;
      modal(`<span class="eyebrow">✦ ${a === 'genHarder' ? 'HARDER' : 'EASIER'}</span><h2>${escapeHtml(plan.title)}</h2><div class="gen-plan">${plan.items.map((x, i) => `<div class="gen-row"><div><b>${i + 1}. ${escapeHtml(x.exercise)}</b><small>${x.sets} × ${x.reps} · rest ${x.rest_s}s</small></div></div>`).join('')}</div><div class="hero-actions"><button class="primary" data-action="genLogIt">Log this</button></div>`);
      bind(); return;
    }
    case 'genLogIt': {
      const plan = window.__lastPlan; if (!plan) return;
      $('#modal').innerHTML = '';
        const exs = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
        pageData.exercises = exs;
        // FITVERSE 6.1: plans now carry exercise IDS — map by id first (handles
        // yoga/cardio items missing from this user's library), name as fallback.
        // Matching by name only made yoga plans collapse into "Barbell ...".
        const byId = Object.fromEntries(exs.map(e => [String(e.id), e.id]));
        const byName = Object.fromEntries(exs.map(e => [e.name, e.id]));
        const planName = (plan.title || 'Generated plan').toLowerCase();
        const title = /yoga/.test(planName) ? 'Yoga flow · ' + (plan.params?.duration || 45) + ' min' : plan.title;
        const logs = (plan.items || []).map(x => ({ exercise_id: (x.id && byId[String(x.id)]) || byName[x.exercise] || 0, sets: x.sets, reps: parseInt(x.reps) || 10, weight: 0 })).filter(x => x.exercise_id);
        if (!logs.length) return toast('These exercises are not in your library yet — add them there first');
        // Land the plan in the live Finish-Workout editor so the user can tweak weights first.
        pageData.activeSession = { title, startedAt: new Date().toISOString(), logs };
        state.page = 'workout'; await loadPageData('workout'); render();
        toast('Plan loaded into your session — adjust, then FINISH WORKOUT');
      return;
    }
    case 'logMeal': {
      const preMeal = btn?.dataset?.meal || null;
      const guess = (() => { const h = new Date().getHours(); return h < 11 ? 'breakfast' : h < 16 ? 'lunch' : h < 21 ? 'dinner' : 'snacks'; })();
      const mealSel = (cls, auto) => `<label>Meal<select name="meal" class="${cls}"><option value="breakfast" ${auto === 'breakfast' ? 'selected' : ''}>Breakfast</option><option value="lunch" ${auto === 'lunch' ? 'selected' : ''}>Lunch</option><option value="dinner" ${auto === 'dinner' ? 'selected' : ''}>Dinner</option><option value="snacks" ${auto === 'snacks' ? 'selected' : ''}>Snack</option></select></label>`;
      modal(`<span class="eyebrow">LOG FOOD</span><h2>What did you eat?</h2><p class="loading">Add everything at once, or let AI estimate each item — just type the food.</p>
      <form class="activity-form" id="meal-form">
      ${mealSel('meal-sel', preMeal || guess)}
      <label>Food<input name="name" placeholder="Grilled chicken and rice" required maxlength="100"></label>
      <div class="macro-mini"><label>Calories<input name="kcal" type="number" value="400" min="0" max="3000" required></label><label>Protein (g)<input name="protein_g" type="number" value="30" min="0" max="300"></label><label>Carbs (g)<input name="carbs_g" type="number" value="0" min="0" max="500"></label><label>Fats (g)<input name="fat_g" type="number" value="0" min="0" max="200"></label></div>
      <div class="hero-actions"><button class="outline" type="button" id="meal-add-another">＋ Add another item</button><button class="primary" type="submit">Add to diary</button></div>
      <div id="meal-queue"></div></form>`);
      bind();
      const queue = [];
      const drawQueue = () => { $('#meal-queue').innerHTML = queue.map((q, i) => `<div class="meal-item"><span>${escapeHtml(q.name)}</span><b>${q.kcal} kcal · ${Math.round(q.protein_g)}g protein · ${escapeHtml(q.meal)}</b><button type="button" class="more" data-qdel="${i}">×</button></div>`).join(''); $$('#meal-queue [data-qdel]').forEach(b => b.onclick = () => { queue.splice(Number(b.dataset.qdel), 1); drawQueue(); }); };
      $('#meal-add-another').onclick = (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData($('#meal-form')));
        if (!f.name?.trim()) { toast('Type the food name first'); return; }
        queue.push({ name: f.name.trim(), meal: f.meal, kcal: Number(f.kcal) || 0, protein_g: Number(f.protein_g) || 0, carbs_g: Number(f.carbs_g) || 0, fat_g: Number(f.fat_g) || 0 });
        $('#meal-form input[name=name]').value = ''; drawQueue(); toast('Queued — add more or hit Add to diary');
      };
      $('#meal-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const items = [...queue, { name: f.name.trim(), meal: f.meal, kcal: Number(f.kcal) || 0, protein_g: Number(f.protein_g) || 0, carbs_g: Number(f.carbs_g) || 0, fat_g: Number(f.fat_g) || 0 }].filter(x => x.name);
        if (!items.length) { toast('Add at least one food'); return; }
        try {
          let last = null;
          for (const it of items) last = await api('/api/nutrition', { method: 'POST', body: JSON.stringify(it) });
          if (last?.totals) { pageData.nutrition = { ...(pageData.nutrition || {}), totals: last.totals, items: last.items, targets: pageData.nutrition?.targets || {} }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { nutrition: pageData.nutrition } })); }
          $('#modal').innerHTML = ''; await loadPageData('nutrition'); render();
          toast(`${items.length} item${items.length > 1 ? 's' : ''} logged · +${items.length * 5} XP`);
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'aiSuggestWorkout': {
      const s = pageData.healthSuggest || {};
      const g = s.suggestion || {};
      clearOnboarding();
      action('generateWorkout', null);
      setTimeout(() => { const inp = $('#gen-form textarea[name=preferences]') || $('#gen-form input[name=preferences]'); if (inp && g.focus) { inp.value = `Focus: ${g.focus}. Health facts: ${JSON.stringify(g.facts || {})}`; } }, 400);
      return;
    }
    case 'saveSuggestion': {
      const g2 = (pageData.healthSuggest || {}).suggestion || {};
      modal(`<span class="eyebrow">SAVED PLAN</span><h2>${escapeHtml(g2.title || 'Training suggestion')}</h2><div class="scan-result"><p>${escapeHtml(g2.why || '')}</p><p class="loading est-note">Focus: ${escapeHtml(g2.focus || '—')} · ${g2.duration || 45} min</p></div><p class="loading">Tip: tap “Build this workout” to turn it into a full logged session with exercises.</p><div class="hero-actions"><button class="primary" data-action="close">Got it</button></div>`);
      bind();
      return;
    }
    case 'quickMeal': {
      const m = btn?.dataset?.meal || 'snacks';
      const name = prompt(`Quick add to ${m} — what did you eat?`);
      if (!name?.trim()) return;
      try {
        const r = await api('/api/ai/meal', { method: 'POST', body: JSON.stringify({ desc: name, grams: 350 }) });
        const it = r.item || {};
        const t = it.totals || { kcal: 350, protein_g: 15, carbs_g: 30, fat_g: 10 };
        const rr = await api('/api/nutrition', { method: 'POST', body: JSON.stringify({ name: it.title || name.trim(), meal: m, kcal: t.kcal, protein_g: t.protein_g, carbs_g: t.carbs_g, fat_g: t.fat_g }) });
        if (rr?.totals) { pageData.nutrition = { ...(pageData.nutrition || {}), totals: rr.totals, items: rr.items, targets: pageData.nutrition?.targets || {} }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { nutrition: pageData.nutrition } })); }
        await loadPageData('nutrition'); render(); toast(`Logged to ${m} · AI estimated ${t.kcal} kcal`);
      } catch (e) { toast(e.message); }
      return;
    }
    case 'aiSuggestLog': {
      const m = btn?.dataset?.meal || 'lunch';
      const name = prompt(`What did you have for ${m}? AI will estimate the macros.`);
      if (!name?.trim()) return;
      try {
        const r = await api('/api/ai/meal', { method: 'POST', body: JSON.stringify({ desc: name.trim(), grams: 400 }) });
        const it = r.item || {};
        if (!it.matched && !it.totals) { toast(it.note || 'Could not estimate that — try Log food instead'); return; }
        const t = it.totals || { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 };
        modal(`<span class="eyebrow">✦ AI ESTIMATE</span><h2>${escapeHtml(it.title || name.trim())}</h2>
        <div class="scan-result"><div class="scan-big"><b>${t.kcal}</b><em>kcal</em></div>
        <div class="scan-macros"><span><b>${t.protein_g}g</b><small>protein</small></span><span><b>${t.carbs_g}g</b><small>carbs</small></span><span><b>${t.fat_g}g</b><small>fat</small></span></div></div>
        <div class="hero-actions"><button class="primary" id="ai-log-add">Add to ${escapeHtml(m)}</button><button class="outline" data-action="close">Cancel</button></div>`);
        bind();
        $('#ai-log-add').onclick = async () => {
          try {
            const rr = await api('/api/nutrition', { method: 'POST', body: JSON.stringify({ name: it.title || name.trim(), meal: m, kcal: t.kcal, protein_g: t.protein_g, carbs_g: t.carbs_g, fat_g: t.fat_g }) });
            if (rr?.totals) { pageData.nutrition = { ...(pageData.nutrition || {}), totals: rr.totals, items: rr.items, targets: pageData.nutrition?.targets || {} }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { nutrition: pageData.nutrition } })); }
            $('#modal').innerHTML = ''; await loadPageData('nutrition'); render(); toast(`Added to ${m}`);
          } catch (e2) { toast(e2.message); }
        };
      } catch (e) { toast(e.message); }
      return;
    }
    case 'scanMeal': {
      const h0 = new Date().getHours(); const autoMeal = h0 < 11 ? 'breakfast' : h0 < 16 ? 'lunch' : h0 < 21 ? 'dinner' : 'snacks';
      modal(`<span class="eyebrow">✦ AI MEAL SCANNER</span><h2>Describe your meal</h2><p class="loading">The AI estimates nutrition from your description. Photo scanning with real vision models is coming soon.</p>
      <form class="activity-form" id="scan-form"><label>What's on the plate?<input name="desc" placeholder="grilled chicken with rice and broccoli" required maxlength="200"></label>
      <label>Add to<select name="meal"><option value="breakfast" ${autoMeal === 'breakfast' ? 'selected' : ''}>Breakfast</option><option value="lunch" ${autoMeal === 'lunch' ? 'selected' : ''}>Lunch</option><option value="dinner" ${autoMeal === 'dinner' ? 'selected' : ''}>Dinner</option><option value="snacks" ${autoMeal === 'snacks' ? 'selected' : ''}>Snack</option></select></label>
      <label>Portion (grams)<input name="grams" type="number" value="400" min="50" max="2000"></label>
      <button class="primary" type="submit">✦ Analyze</button></form>`);
      bind();
      $('#scan-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const sb = e.currentTarget.querySelector('button[type=submit]'); if (sb) { sb.disabled = true; sb.textContent = '✦ Analyzing…'; }
        try {
          const { item: r } = await api('/api/ai/meal', { method: 'POST', body: JSON.stringify(f) });
          if (!r.matched) { toast(r.note); return; }
          modal(`<span class="eyebrow">✦ ESTIMATED</span><h2>${escapeHtml(r.title)}</h2>
          <div class="scan-result"><div class="scan-big"><b>${r.totals.kcal}</b><em>kcal</em></div>
          <div class="scan-macros"><span><b>${r.totals.protein_g}g</b><small>protein</small></span><span><b>${r.totals.carbs_g}g</b><small>carbs</small></span><span><b>${r.totals.fat_g}g</b><small>fat</small></span></div>
          ${r.items.map(i => `<p class="loading">${escapeHtml(i.food)} · ${i.grams}g · ${i.kcal} kcal</p>`).join('')}
          <p class="loading est-note">${escapeHtml(r.note)}</p></div>
          <div class="hero-actions"><button class="primary" id="scan-add" data-meal="${f.meal}">Add to ${escapeHtml(f.meal)}</button><button class="outline" data-action="close">Edit instead</button></div>`);
          bind();
          $('#scan-add').onclick = async () => {
            try { const rr = await api('/api/nutrition', { method: 'POST', body: JSON.stringify({ name: r.title, meal: f.meal, kcal: r.totals.kcal, protein_g: r.totals.protein_g, carbs_g: r.totals.carbs_g, fat_g: r.totals.fat_g }) }); $('#modal').innerHTML = ''; if (rr?.totals) { pageData.nutrition = { ...(pageData.nutrition || {}), totals: rr.totals, items: rr.items, targets: pageData.nutrition?.targets || {} }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { nutrition: pageData.nutrition } })); } await loadPageData('nutrition'); render(); toast(`Added to ${f.meal}`); } catch (err) { toast(err.message); }
          };
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'delMeal':
      api(`/api/nutrition/${id}`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData('nutrition'); render(); toast('Removed'); }).catch(e => toast(e.message)); return;
    case 'setTargets': setTargetsModal(); return;
    // FITVERSE 6.1: AI replies show a live typing indicator instead of dead air.
    // serverThinking=true renders animated dots as the LAST chat bubble.
    case 'coachAsk': {
      const q = btn.dataset.q;
      pageData.coachChat = pageData.coachChat || [];
      pageData.coachChat.push({ role: 'user', content: q });
      pageData.coachTyping = true; render();
      try {
        const r = await api('/api/ai/companion', { method: 'POST', body: JSON.stringify({ message: q, conversationId: pageData.coachConvId }) });
        pageData.coachConvId = r.conversationId;
        pageData.coachChat.push({ role: 'coach', content: r.reply });
        pageData.coachTyping = false;
        await loadPageData('coach');
      } catch (err) { pageData.coachChat.push({ role: 'coach', content: 'I hit a snag reaching the server — try again in a moment.' }); pageData.coachTyping = false; }
      render(); return;
    }
    case 'replaceEx': {
      const i = Number(btn.dataset.i || 0);
      const plan = window.__lastPlan;
      if (!plan || !plan.items || !plan.items[i]) return toast('No plan to swap');
      const it = plan.items[i];
      if (!it.alt) return toast('No alternative for this exercise');
      plan.items[i] = { ...it, exercise: it.alt, alt: it.exercise };  // swap
      window.__lastPlan = plan;
      modal(`<span class="eyebrow">✦ GENERATED</span><h2>${escapeHtml(plan.title)}</h2><p class="loading">~${plan.est_kcal} kcal · ${plan.items.length} exercises</p>
      <div class="gen-plan">${plan.items.map((x, j) => `<div class="gen-row"><div><b>${j + 1}. ${escapeHtml(x.exercise)}</b><small>${x.sets} sets × ${x.reps} reps · rest ${x.rest_s}s · ${x.tempo} tempo</small><small class="dim">Alt: ${escapeHtml(x.alt)}</small></div><button class="more" data-action="replaceEx" data-i="${j}" title="Replace">⇄</button></div>`).join('')}</div>
      <p class="loading">${escapeHtml(plan.note)}</p>
      <div class="hero-actions"><button class="primary" data-action="genLogIt">Log this workout</button><button class="outline" data-action="genHarder">Make it harder</button><button class="outline" data-action="genEasier">Make it easier</button></div>`);
      bind();
      return;
    }
    case 'closeModal': $('#modal').innerHTML = ''; return;
    case 'addWater': {
      const ml = Number(btn.dataset.ml || 0);
      if (!(ml > 0)) return toast('Invalid amount');
      try { const wr = await api('/api/water', { method: 'POST', body: JSON.stringify({ ml }) }); if (wr?.today_ml != null) { pageData.water = { ...(pageData.water || {}), today_ml: wr.today_ml, target_ml: wr.target_ml }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { water: pageData.water } })); } await loadPageData(state.page); render(); toast(`+${ml} ml logged 💧`); }
      catch (err) { toast(err.message); }
      return;
    }
    case 'addWaterCustom': {
      modal(`<span class="eyebrow">HYDRATION</span><h2>Add water</h2><form class="activity-form" id="water-form"><label>Amount<input name="amount" type="number" min="1" step="any" required placeholder="e.g. 2"></label><label>Unit<select name="unit"><option value="ml">millilitres (ml)</option><option value="l">litres (L)</option><option value="oz">US fluid ounces (oz)</option><option value="gal">US gallons (gal)</option></select></label><button class="primary" type="submit">Add to today</button></form>`);
      $('#water-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const amt = parseFloat(f.amount);
        if (!(amt > 0)) return toast('Enter an amount greater than 0');
        const ML = { ml: 1, l: 1000, oz: 29.5735, gal: 3785.41 };
        const ml = Math.round(amt * (ML[f.unit] || 1));
        try { const wr = await api('/api/water', { method: 'POST', body: JSON.stringify({ ml }) }); $('#modal').innerHTML = ''; if (wr?.today_ml != null) { pageData.water = { ...(pageData.water || {}), today_ml: wr.today_ml, target_ml: wr.target_ml }; dispatchEvent(new CustomEvent('fv:data-updated', { detail: { water: pageData.water } })); } await loadPageData('nutrition'); render(); toast(`Added ${(ml / 1000).toFixed(2)} L of water 💧`); }
        catch (err) { toast(err.message); }
      };
      bind(); return;
    }
    case 'addProgress':
      modal(`<span class="eyebrow">PRIVATE LOG</span><h2>Measurements</h2><p class="loading">🔒 Progress data is private — only you see it.</p><form class="activity-form" id="prog-form">
      <label>Weight (kg)<input name="weight_kg" type="number" step="0.1" min="30" max="300"></label>
      <label>Body fat % (optional)<input name="body_fat" type="number" step="0.1" min="3" max="60"></label>
      <label>Waist (cm, optional)<input name="waist_cm" type="number" step="0.5" min="40" max="200"></label>
      <label>Note (optional)<input name="note" maxlength="200" placeholder="Feeling stronger this week"></label>
      <button class="primary" type="submit">Save entry</button></form>`);
      bind();
      $('#prog-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        const payload = {}; for (const k of ['weight_kg', 'body_fat', 'waist_cm']) if (f[k]) payload[k] = Number(f[k]);
        payload.note = f.note;
        try { await api('/api/progress', { method: 'POST', body: JSON.stringify(payload) }); $('#modal').innerHTML = ''; await loadPageData('progress'); render(); toast('Progress logged'); } catch (err) { toast(err.message); }
      };
      return;
    case 'exerciseDetail': {
      const e = pageData.exercises.find(x => x.id === id); if (!e) return;
      modal(`<div class="ex-hero" style="background-image:url('${exerciseImage(e.name)}')"></div><span class="eyebrow">${escapeHtml(e.muscle.toUpperCase())} · ${escapeHtml(e.equipment.toUpperCase())}</span><h2>${escapeHtml(e.name)}</h2>
      <p>${escapeHtml(e.instructions || 'Move with control; keep breathing steadily through every rep.')}</p>
      <div class="mistake-box"><b>⚠ Common mistakes</b><p>${escapeHtml(e.mistakes || 'Rushing reps, locking joints, or holding the breath.')}</p></div>
      <p class="loading">${escapeHtml(e.difficulty)} · ${e.met} MET intensity</p>
      <div class="hero-actions"><a class="primary" style="text-decoration:none;display:inline-block" href="${ytSearch(e.name)}" target="_blank" rel="noopener">▶ Watch proper form</a><button class="outline" data-action="logWorkout">Log a session</button></div>`);
      bind(); return;
    }
    case 'weeklyReview':
      $('#modal').innerHTML = ''; state.page = 'progress'; await loadPageData('progress'); render(); window.scrollTo(0, 0); return;
    case 'moreMenu': {
      const pages = [['intelligence', '🧬', 'Fitness DNA'], ['connectHealth', '🔌', 'Health Data'], ['posts', '▶', 'Posts & Reels'], ['progress', '📈', 'Progress'], ['challenges', '◉', 'Challenges'], ['communities', '◌', 'Communities'], ['events', '◫', 'Events'], ['messages', '✉', 'Messages'], ['friends', '👥', 'Friends'], ['coach', '✦', 'AI Coach'], ['businesses', '▦', 'Businesses'], ['bookings', '🎟', 'My bookings'], ['library', '📚', 'Exercise library']];
      modal(`<div class="more-sheet"><span class="eyebrow">ALL OF FITVERSE</span><h2 style="font-size:19px;margin:4px 0 2px">Go to…</h2><div class="sheet-grid">${pages.map(([p, ic, label]) => `<button data-page="${p}" class="${state.page === p ? 'active' : ''}"><span>${ic}</span>${label}</button>`).join('')}</div></div>`);
      bind();
      return;
    }
    case 'shareRecap': shareCard('weekly-recap'); return;
    case 'traj': {
      pageData.trajScenario = btn.dataset.id;
      await loadPageData('intelligence'); state.page = 'intelligence'; render();
      const chips = $('#traj-chips'); if (chips) chips.scrollIntoView({ block: 'nearest' });
      return;
    }
    case 'missionStart': {
      toast('Mission active — progress updates automatically as you train 💪');
      return;
    }
    case 'missionInvite': {
      const friends = (pageData.friends && pageData.friends.length ? pageData.friends : ((await api('/api/friends')).items || []));
      pageData.friends = friends;
      if (!friends.length) { toast('Add friends first — then drag them into your mission!'); return; }
      modal(`<span class="eyebrow">🤝 INVITE A FRIEND</span><h2>Who's joining the mission?</h2><div class="pick-list">${friends.map(f => `<button data-action="missionInvitePick" data-id="${f.id}">${escapeHtml(f.name)}</button>`).join('')}</div>`);
      bind();
      return;
    }
    case 'missionInvitePick': {
      try {
        await api('/api/missions/join', { method: 'POST', body: JSON.stringify({ friend_id: Number(btn.dataset.id) }) });
        $('#modal').innerHTML = ''; toast('Invite sent — accountability unlocked 🤝');
        await loadPageData('intelligence'); render();
      } catch (err) { toast(err.message); }
      return;
    }
    case 'missionShare': {
      const m = pageData.mission || {};
      const text = `🎯 My FITVERSE mission: ${m.title || 'Loading…'} — ${m.description || ''} Reward: +${m.reward_xp || 0} XP. Fitness is more fun together!`;
      if (navigator.share) { navigator.share({ title: 'FITVERSE Mission', text }).catch(() => {}); }
      else { try { await navigator.clipboard.writeText(text); toast('Mission copied — paste it anywhere 📋'); } catch { toast(text); } }
      return;
    }
    case 'teamJoin': {
      try {
        await api('/api/teams/join', { method: 'POST', body: JSON.stringify({ team_id: Number(btn.dataset.id) }) });
        toast('Team joined — your XP now fuels the war ⚔️');
        await loadPageData('intelligence'); render();
      } catch (err) { toast(err.message); }
      return;
    }
    case 'shareDna': shareCard('fitness-dna'); return;
    case 'shareMoment': {
      const m = (pageData.moments || [])[Number(btn.dataset.i)];
      if (!m) return;
      momentCard(m);
      return;
    }
    case 'react': {
      const pid = Number(btn.dataset.id), r = btn.dataset.reaction;
      try {
        const res = await api('/api/reactions', { method: 'POST', body: JSON.stringify({ post_id: pid, reaction: r }) });
        const feedPost = (pageData.feed || []).find(p => p.id === pid);
        if (feedPost) { feedPost.reactions = res.reactions; feedPost.my_reactions = res.mine; }
        render();
      } catch (err) { toast(err.message); }
      return;
    }
    case 'genWorkoutFromOnboarding': clearOnboarding(); action('generateWorkout', null); return;
    case 'runOnboarding': runOnboarding(); return;
    case 'dismissOnboarding': {
      const el = document.querySelector('.ob-reminder'); if (el) el.remove();
      toast('Hidden for this visit — find it later in Profile → Setup wizard.'); return;
    }
    case 'cmdk': cmdk(); return;
    case 'close': $('#modal').innerHTML = ''; return;
    case 'goBack': goBack(); return;
    case 'sampleTakeout': {
      try {
        const res = await fetch('sample_google_takeout.json');
        const sample = await res.json();
        // Same parser the real Takeout files go through — no shortcuts, no faked rows.
        const { days } = await importTakeoutSample(sample);
        const r = await api('/api/health/import/takeout', { method: 'POST', body: JSON.stringify({ days }) });
        const st = $('#takeout-status');
        if (st) st.textContent = `✅ Sample imported: ${r.days} days of steps + distance. Open AI Coach or Nutrition to see vitals-aware suggestions.`;
        toast('Sample health data imported — AI can now train on it');
      } catch (e) { toast(e.message); }
      return;
    }
    case 'aiNewChat': pageData.coachConvId = 0; pageData.coachChat = []; state.page = 'coach'; render(); toast('New chat — send a message to start'); return;
    case 'aiOpenConv': pageData.coachConvId = id; pageData.coachChat = null; await loadPageData('coach'); state.page = 'coach'; render(); return;
    case 'aiDeleteChat': {
      if (!confirm('Delete this chat? All its messages are removed for you.')) return;
      try { await api(`/api/ai/coach/${id}`, { method: 'POST', body: JSON.stringify({ op: 'delete' }) }); if (Number(pageData.coachConvId) === Number(id)) { pageData.coachConvId = 0; pageData.coachChat = []; } await loadPageData('coach'); render(); toast('Chat deleted'); } catch (e) { toast(e.message); }
      return;
    }
    case 'aiPinChat':
      try { const r = await api(`/api/ai/coach/${id}`, { method: 'POST', body: JSON.stringify({ op: 'pin' }) }); await loadPageData('coach'); render(); toast(r.pinned ? '📌 Chat pinned to top' : 'Chat unpinned'); } catch (e) { toast(e.message); }
      return;
    case 'aiRenameChat': {
      const cur = (pageData.aiConversations || []).find(c => String(c.id) === String(id));
      modal(`<span class="eyebrow">SAVED CHATS</span><h2>Rename chat</h2><form class="activity-form" id="ai-ren-form"><label>Chat name<input name="title" required maxlength="80" value="${escapeHtml((cur && cur.title) || '')}"></label><button class="primary" type="submit">Save name</button></form>`);
      bind();
      $('#ai-ren-form').onsubmit = async (e) => {
        e.preventDefault(); const t = new FormData(e.currentTarget).get('title');
        try { await api(`/api/ai/coach/${id}`, { method: 'POST', body: JSON.stringify({ op: 'rename', title: t }) }); $('#modal').innerHTML = ''; await loadPageData('coach'); render(); toast('Chat renamed'); } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'aiShareChat': {
      const fid = Number(btn.dataset.fid || 0);
      if (!fid) { await shareChatModal(id); return; }
      try {
        const d = await api(`/api/ai/coach?conversation_id=${Number(id)}`);
        const items = (d.items || []).slice(-10);
        const title = (d.conversations || []).find(c => String(c.id) === String(id))?.title || 'Coach chat';
        const body = `💬 AI chat · ${title}\n` + items.map(m => `${m.role === 'user' ? 'You' : '✦ Coach'}: ${m.content}`).join('\n').slice(0, 950);
        await api('/api/messages', { method: 'POST', body: JSON.stringify({ to_user_id: fid, body }) });
        $('#modal').innerHTML = ''; toast('Chat shared in Messages ✉');
      } catch (e) { toast(e.message); }
      return;
    }
    case 'quickAction': {
      const qa = btn.dataset.qa;
      if (qa === 'workout') { state.page = 'workout'; await loadPageData('workout'); render(); window.scrollTo(0, 0); return; }
      if (qa === 'meal') { state.page = 'nutrition'; await loadPageData('nutrition'); render(); window.scrollTo(0, 0); return; }
      if (qa === 'health') { state.page = 'connectHealth'; await loadPageData('connectHealth'); render(); window.scrollTo(0, 0); return; }
      if (qa === 'challenges') { state.page = 'challenges'; await loadPageData('challenges'); render(); window.scrollTo(0, 0); return; }
      if (qa === 'dna') { state.page = 'intelligence'; await loadPageData('intelligence'); render(); window.scrollTo(0, 0); return; }
      if (qa === 'easy') { pageData.genStyle = 'gentle'; action('generateWorkout', btn); return; }
      return;
    }
    case 'gotoMetrics': { const el = document.getElementById('metrics-form'); if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); const inp = el.querySelector('[name=blood_pressure]'); if (inp) setTimeout(() => inp.focus(), 450); } return; }
    case 'challengeFriend': pageData.challengePreselect = id; action('challenge', btn); return;
    case 'eventInvite': {
      const fidEv = Number(btn.dataset.fid || 0);
      if (fidEv) {
        try {
          await api('/api/messages', { method: 'POST', body: JSON.stringify({ to_user_id: fidEv, body: `🎟 Join me at "${btn.dataset.name || 'a FITVERSE event'}"! Book your spot from the Events panel — we'll train together. 🏃` }) });
          $('#modal').innerHTML = ''; toast('Invite sent ✉');
        } catch (e) { toast(e.message); }
        return;
      }
      const ev = (pageData.events || []).find(e => e.id === Number(id));
      const name = btn.dataset.name || (ev ? ev.name : 'the featured FITVERSE event');
      const evFriends = await getFriends();
      if (!evFriends.length) { toast('Add a friend first — events are better together'); return; }
      modal(`<span class="eyebrow">✉ EVENT CREW</span><h2>Invite a friend</h2><p class="loading">They'll get the invite in Messages.</p><div class="pick-list">${evFriends.map(f => `<button data-action="eventInvite" data-id="${id}" data-fid="${f.id}" data-name="${escapeHtml(name)}">${escapeHtml(f.name)}</button>`).join('')}</div>`);
      bind(); return;
    }
    case 'communityChallenge': {
      let members = [];
      if (pageData.detailData && pageData.detailData.id === Number(id)) members = pageData.detailData.members || [];
      else { try { members = (await api(`/api/community?id=${Number(id)}`)).item?.members || []; } catch (_) {} }
      if (!members.length) { toast('Open the community to challenge its members'); return; }
      modal(`<span class="eyebrow">⚔️ COMMUNITY RIVALRY</span><h2>Challenge a member</h2><div class="pick-list">${members.filter(m => m.id !== (me().id || 0)).map(m => `<button data-action="challengeFriend" data-id="${m.id}">${escapeHtml(m.name)}</button>`).join('')}</div>`);
      bind(); return;
    }
    case 'communityInvite': {
      const fidC = Number(btn.dataset.fid || 0);
      if (fidC) {
        try {
          await api('/api/messages', { method: 'POST', body: JSON.stringify({ to_user_id: fidC, body: `◌ Join "${btn.dataset.name || 'my community'}" on FITVERSE! Open Communities → tap Join — let's grow together. 💪` }) });
          $('#modal').innerHTML = ''; toast('Invite sent ✉');
        } catch (e) { toast(e.message); }
        return;
      }
      const cFriends = await getFriends();
      if (!cFriends.length) { toast('Add a friend first — then bring them into your crew'); return; }
      let cname = (pageData.detailData && pageData.detailData.name) || '';
      let cid = Number(id || 0) || (pageData.detailData && pageData.detailData.id) || 0;
      if (!cid) { try { cid = ((pageData.myCommunities || [])[0] || {}).id || 0; cname = ((pageData.myCommunities || [])[0] || {}).name || ''; } catch (_) {} }
      if (!cid) { toast('Join a community first, then invite friends'); return; }
      modal(`<span class="eyebrow">◌ GROW YOUR CREW</span><h2>Invite to ${escapeHtml(cname || 'your community')}</h2><div class="pick-list">${cFriends.map(f => `<button data-action="communityInvite" data-id="${cid}" data-fid="${f.id}" data-name="${escapeHtml(cname)}">${escapeHtml(f.name)}</button>`).join('')}</div>`);
      bind(); return;
    }
    case 'genStyle': pageData.genStyle = btn.dataset.style || ''; $$('.wo-style-chips .chip').forEach(c => c.classList.toggle('active', c === btn)); return;
    case 'indianDiet': {
      toast('🍛 Building your Indian plan from targets + vitals…');
      try {
        const d = await api('/api/ai/indian-diet', { method: 'POST', body: '{}' });
        const plan = d.item || {};
        const v = plan.vitals || {};
        modal(`<span class="eyebrow">🇮🇳 NUTRITION AI</span><h2>${escapeHtml(plan.title || 'Indian plate plan')}</h2>
        ${(plan.flags || []).map(f => `<span class="v-pill ${/SODIUM|GI/.test(f) ? 'warn' : 'good'}">${f}</span>`).join(' ')}
        ${v.bp || v.sugar ? `<p class="loading est-note">Tuned to your 7-day vitals: ${v.bp ? 'BP ' + v.bp : ''}${v.bp && v.sugar ? ' · ' : ''}${v.sugar ? 'sugar ' + v.sugar + ' mg/dL' : ''}</p>` : ''}
        ${plan.ai ? `<p class="as-ai" style="margin:10px 0">✦ ${mdLite(plan.ai)}</p>` : ''}
        <div class="meal-plan-grid">${plan.items.map(it => `<div class="meal-plan-row"><span class="mp-ico">${it.meal === 'Breakfast' ? '🌅' : it.meal === 'Lunch' ? '🍛' : it.meal === 'Snacks' ? '🥜' : '🌙'}</span><div><b>${escapeHtml(it.meal)} · ~${it.kcal} kcal · ${it.protein_g}g protein</b><p>${escapeHtml(it.food)}</p></div></div>`).join('')}</div>
        <p class="loading est-note">${escapeHtml(plan.note || '')}</p>
        <div class="hero-actions"><button class="primary" data-action="close">Looks good</button></div>`);
        bind();
      } catch (e) { toast(e.message); }
      return;
    }
    default: toast('Coming soon in the demo'); return;
  }
}
// ---- Server-Sent Events: instant chat & notification push (replaces polling for chat) ----
let evtSource = null;
function startSSE() {
  if (!apiEnabled || evtSource || !sessionToken) return;
  try {
    evtSource = new EventSource(`/api/stream?since=${pageData.notifications[0]?.id || 0}`);
    evtSource.addEventListener('message', (e) => {
      const m = JSON.parse(e.data);
      if (state.page === 'messages' && Number(m.conversation_id) === Number(pageData.activeConversation)) {
        if (!pageData.messages.some(x => x.id === m.id)) { pageData.messages.push(m); render(); scrollBubbles(); }
      }
      // PERF: refresh the conversation list at most every 5s, not on every message.
      if (!startSSE._lastConvSync || Date.now() - startSSE._lastConvSync > 5000) {
        startSSE._lastConvSync = Date.now();
        api('/api/conversations').then(d => { pageData.conversations = d.items || []; syncAvatars(); if (state.page === 'messages') render(); }).catch(() => {});
      }
    });
    evtSource.addEventListener('notification', (e) => {
      const n = JSON.parse(e.data);
      if (!pageData.notifications.some(x => x.id === n.id)) { pageData.notifications.unshift(n); toast(`${n.title} — ${n.body}`); notifSound(); if (state.page !== 'messages') render(); }
    });
    evtSource.addEventListener('typing', (e) => {
      try {
        const t = JSON.parse(e.data);
        const el = $('#typing');
        const show = (t.conversations || []).includes(Number(pageData.activeConversation));
        if (el) el.style.display = show ? 'flex' : 'none';
      } catch (_) {}
    });
    evtSource.onerror = () => { /* browser auto-reconnects */ }
    // LIVE FEED: silent refresh every 20s while browsing social pages (throttled, hidden-tab aware)
    if (!startSSE._feedTimer) {
      startSSE._feedTimer = setInterval(() => {
        if (document.hidden || !['home', 'posts', 'discover', 'reels'].includes(state.page) || startSSE._feedBusy) return;
        startSSE._feedBusy = true;
        api('/api/feed').then(d => {
          const fresh = d.items || [];
          const sig = (a) => a.slice(0, 5).map(x => x.id).join(',');
          if (fresh.length && pageData.feed && sig(fresh) !== sig(pageData.feed)) { pageData.feed = fresh; render(); }
        }).catch(() => {}).finally(() => { startSSE._feedBusy = false; });
      }, 20000);
    };
  } catch (_) { /* SSE unsupported — polling still runs */ }
}
// ---- Google sign-in: opens the official OAuth page; the callback stores the session ----
async function authWithGoogle() {
  try {
    const r = await api('/api/auth/google/url');
    if (!r.configured) {
      const redirect = `${location.origin}/api/auth/google/callback`;
      modal(`<span class="eyebrow">GOOGLE SIGN-IN</span><h2>One free setup step</h2><p>Google requires FITVERSE to be registered in a (free) Google Cloud project before it can vouch for sign-ins. About 5 minutes, no billing, one time:</p><ol class="setup-steps"><li>Open <b>console.cloud.google.com</b> → <b>APIs &amp; Services</b> → <b>OAuth consent screen</b> → pick <b>External</b> → fill only the app name + your email → Save.</li><li>Still in <b>APIs &amp; Services</b> → <b>Credentials</b> → <b>Create credentials</b> → <b>OAuth client ID</b> → type <b>Web application</b>.</li><li>Under <b>Authorized redirect URIs</b>, paste exactly:<div class="code">${escapeHtml(redirect)}</div></li><li>Copy the <b>Client ID</b> and <b>Client secret</b> it shows you.</li><li>Set environment variables <b>GOOGLE_CLIENT_ID</b> and <b>GOOGLE_CLIENT_SECRET</b> (local: the <b>.env</b> file · Render: dashboard → Environment) and restart.</li></ol><p class="loading">Until then, email + password sign-in works fully — Google just can't verify visitors yet.</p><div class="hero-actions" style="margin-top:10px"><button class="outline" data-action="close">Got it</button></div>`);
      bind(); return;
    }
    if (evtSource) { evtSource.close(); evtSource = null; }
    location.href = r.url;
  } catch (e) { toast(e.message); }
}  // Onboarding: multi-step profile setup for new users (shown once; re-openable from Profile)
function runOnboarding() {
  state.onboardingActive = true;
  const steps = [
    { title: 'Welcome to FITVERSE 👋', body: `<p class="loading">Let's personalize your experience. A few quick questions — skip anything you'd rather not share.</p><label>Your age<input name="age" type="number" min="13" max="90" placeholder="21"></label><label>Sex (for calorie estimates)<select name="sex"><option value="male">Male</option><option value="female">Female</option></select></label>` },
    { title: 'Your body stats', body: `<label>Height (cm)<input name="height_cm" type="number" min="120" max="230" placeholder="175"></label><label>Weight (kg)<input name="weight_kg" type="number" min="30" max="300" step="0.5" placeholder="70"></label><div id="ob-vitals"></div>` },
    { title: 'Your goal', body: `<label>Main goal<select name="goal"><option>Build muscle</option><option>Lose weight</option><option>Maintain</option><option>Endurance</option><option>General fitness</option></select></label><label>Experience<select name="experience"><option>Beginner</option><option selected>Intermediate</option><option>Advanced</option></select></label>` },
    { title: 'Training style', body: `<label>Days per week<select name="days_per_week"><option>2</option><option>3</option><option selected>4</option><option>5</option><option>6</option></select></label><label>Session length<select name="session_minutes"><option>30</option><option selected>45</option><option>60</option><option>90</option></select></label><label>Equipment<select name="equipment"><option>Full gym</option><option>Home dumbbells</option><option>Bodyweight only</option></select></label>` },
    { title: 'Lifestyle', body: `<label>Activity level (outside workouts)<select name="activity_level"><option value="low">Mostly sitting</option><option value="moderate" selected>Moderately active</option><option value="high">Very active</option></select></label><label>Diet preference<select name="diet_pref"><option>balanced</option><option>vegetarian</option><option>high-protein</option></select></label>` },
  ];
  let step = 0;
  const answers = {};
  function draw() {
    const s = steps[step];
    modal(`<span class="eyebrow">SETUP ${step + 1}/${steps.length}</span><h2>${s.title}</h2><form class="activity-form" id="ob-form">${s.body}
    <div class="hero-actions"><button class="primary" type="submit">${step === steps.length - 1 ? 'Finish → generate my plan' : 'Next →'}</button>${step > 0 ? '<button class="text-btn" type="button" id="ob-back">Back</button>' : ''}<button class="text-btn" type="button" id="ob-skip">Skip all</button></div><p class="loading ob-note">You can skip now and finish later from your <b>Profile → Setup</b> — everything you share tunes your AI, meals, workouts and friend matches.</p></form>`);
    bind();
    $('#ob-form').onsubmit = async (e) => {
      e.preventDefault();
      Object.assign(answers, Object.fromEntries(new FormData(e.currentTarget)));
      if (step < steps.length - 1) { step++; draw(); return; }
      const payload = {};
      for (const k of ['age', 'height_cm', 'weight_kg']) if (answers[k]) payload[k] = Number(answers[k]);
      for (const k of ['sex', 'goal', 'experience', 'equipment', 'diet_pref', 'activity_level']) if (answers[k]) payload[k] = answers[k];
      if (answers.days_per_week) payload.days_per_week = Number(answers.days_per_week);
      if (answers.session_minutes) payload.session_minutes = Number(answers.session_minutes);
      if (answers.blood_pressure) payload.blood_pressure = Number(answers.blood_pressure);
      if (answers.blood_sugar) payload.blood_sugar = Number(answers.blood_sugar);
      try {
        const r = await api('/api/onboarding', { method: 'POST', body: JSON.stringify(payload) });
        state.onboardingActive = false;
        $('#modal').innerHTML = '';
        const t = r.targets || {};
        modal(`<span class="eyebrow">✦ YOUR PLAN IS READY</span><h2>Welcome to FITVERSE!</h2>
        <div class="scan-result"><div class="scan-big"><b>${t.kcal_target || '—'}</b><em>kcal/day target</em></div>
        <div class="scan-macros"><span><b>${t.protein_target || '—'}g</b><small>protein/day</small></span><span><b>${t.tdee || '—'}</b><small>est. maintenance</small></span></div>
        <p class="loading est-note">${escapeHtml(t.estimate_note || 'These are estimates — adjust as you learn your rhythm.')}</p></div>
        <div class="hero-actions"><button class="primary" data-action="close">Let's go 🎉</button><button class="outline" data-action="genWorkoutFromOnboarding">Generate my first workout</button></div>`);
        bind();
        await hydrate(); render();
      } catch (err) { toast(err.message); }
    };
    const back = $('#ob-back'); if (back) back.onclick = () => { step--; draw(); };
    // FITVERSE 6.0: 30+ users get BP + fasting sugar inputs (vitals mode)
    const drawVitals = () => {
      const v = $('#ob-vitals'); if (!v) return;
      const a = Number($('#ob-form [name=age]')?.value || answers.age || 0);
      if (a >= 30 && !v.innerHTML) {
        v.innerHTML = `<p class="loading est-note">Age 30+ detected — tracking BP & sugar unlocks vitals-aware workouts and Indian diet plans.</p><label>-blood pressure, systolic (optional)<input name="blood_pressure" type="number" min="60" max="260" placeholder="e.g. 128"></label><label>-blood sugar, fasting mg/dL (optional)<input name="blood_sugar" type="number" min="30" max="600" placeholder="e.g. 110"></label>`;
      } else if (a > 0 && a < 30) { v.innerHTML = ''; }
    };
    drawVitals();
    $('#ob-form').addEventListener('input', drawVitals);
    $('#ob-skip').onclick = () => { api('/api/settings', { method: 'POST', body: JSON.stringify({ onboarded: 1 }) }).finally(() => { state.onboardingActive = false; $('#modal').innerHTML = ''; toast('Skipped — finish anytime from Profile → Setup'); }); };
  }
  drawOnboardingStep = draw;
  draw();
}
render();
hydrate().then(async () => {
  render(); loadPageData(state.page); startPolling(); startSSE(); loadWeather(); loadQuote();
  if (sessionToken) try {
    const s = await api('/api/me/settings');
    // Show the setup wizard only for users who haven't onboarded (or skipped) yet.
    if (s.item && !s.item.onboarded) runOnboarding();
    else { pageData.mySettings = s.item; render(); }
  } catch (_) {}
  // Welcome toast after returning from Google sign-in (callback redirects here with ?welcome=Name)
  const w = new URLSearchParams(location.search).get('welcome');
  if (w) { toast(`Welcome to FITVERSE, ${decodeURIComponent(w).split(' ')[0]}!`); history.replaceState({}, '', '/'); }
});
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdk(); }
  if (e.key === 'Escape') $('#modal').innerHTML = '';
});
