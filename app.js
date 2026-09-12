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
function syncAvatars() { if (me().avatar_url) AVATARS[me().id || 1] = me().avatar_url; if (pageData.profile?.avatar_url) AVATARS[pageData.profile.id || 1] = pageData.profile.avatar_url; }
const photoAvatar = (name, i, size = 36) => {
  const custom = AVATARS[Number(i)];
  const src = custom || PHOTOS['p' + (1 + (Math.abs(Number(i) || 1) - 1) % 12)];
  return `<span class="pavatar" style="background-image:url('${src}')"></span>`;
};
const sportLabel = (sport) => (String(sport || '').toLowerCase().includes('run') ? 'Run' : String(sport || '').toLowerCase().includes('cycl') ? 'Cycling' : String(sport || '').toLowerCase().includes('yoga') ? 'Yoga' : String(sport || '').toLowerCase().includes('gym') ? 'Gym' : 'Basketball');
let sessionToken = localStorage.getItem('fitverse-session') || '';
const state = { page: 'home', xp: 0, streak: 0, activities: 0, friends: false, joined: false, challenge: 'pending', booking: false, liked: false, comments: 0, detailId: 0 };
const pageData = { bookings: [], businesses: [], users: [], challenges: [], communities: [], events: [], activities: [], feed: [], conversations: [], activeConversation: 1, messages: [], notifications: [], achievements: [], friends: [], reports: [], xpLedger: [], recommendations: [], counts: {}, stats: {}, coach: 'Ask about people, activities, challenges or events.', profile: {}, reels: [], dash: {}, buddy: [], fitmatch: [], exercises: [], workouts: [], nutrition: {}, water: {}, progressEntries: [], settings: {}, coachChat: [], review: {}, leaderboards: {} };
const apiHeaders = () => ({ 'Content-Type': 'application/json', ...(sessionToken ? { 'X-Session': sessionToken } : {}) });
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'We could not complete that action.');
  return data;
}
const escapeHtml = (v) => String(v ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const avatar = (name, tone = 'coral') => `<div class="avatar ${tone}">${escapeHtml(String(name || '?').split(' ').map(x => x[0]).join('').slice(0, 2))}</div>`;
const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); };
const inr = (n) => (n > 0 ? `₹${Number(n).toLocaleString('en-IN')}` : 'Free');
const dayShort = (iso) => { try { return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }); } catch { return iso; } };
const timeShort = (iso) => { try { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); } catch { return iso; } };
const nav = [['home', '◈', 'Home'], ['discover', '⌕', 'Discover'], ['posts', '▶', 'Posts & Reels'], ['workout', '🏋', 'Workout'], ['nutrition', '🍽', 'Nutrition'], ['progress', '📈', 'Progress'], ['challenges', '◉', 'Challenges'], ['communities', '◌', 'Communities'], ['events', '◫', 'Events'], ['messages', '✉', 'Messages'], ['friends', '👥', 'Friends'], ['coach', '✦', 'AI Coach'], ['businesses', '▦', 'Businesses']];
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
const levelName = () => ['Rookie', 'Mover', 'Athlete', 'Warrior', 'Legend'][Math.min(4, level() - 1)];
const progress = () => Math.min(100, Math.round(((state.xp || 0) % 500) / 5));
const me = () => pageData.profile || {};

async function hydrate() {
  if (!apiEnabled) return;
  const safe = (p, fb) => api(p).then(d => d).catch(() => fb);
  const [boot, feed, notifs, convs, achievements, buddy, fitmatch] = await Promise.all([
    api('/api/bootstrap').catch(() => null), safe('/api/feed', { items: [] }), safe('/api/notifications', { items: [] }),
    safe('/api/conversations', { items: [] }), safe('/api/achievements', { items: [] }),
    safe('/api/ai/buddy', { items: [] }), safe('/api/fitmatch', { items: [] }),
  ]);
  if (boot) {
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
  syncAvatars();
  if (pageData.conversations.length && !pageData.conversations.some(c => c.id === pageData.activeConversation)) pageData.activeConversation = pageData.conversations[0].id;
  if (state.page === 'home') loadDashboard();
}
async function loadDashboard() {
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
  if (!apiEnabled) return;
  const tasks = [];
  const add = (p, fn) => tasks.push(fn.then(items => { pageData[p] = items; }).catch(() => {}));
  if (page === 'discover') {
    add('users', api('/api/users').then(d => d.items || []));
    add('recommendations', api('/api/recommendations').then(d => d.items || []));
    add('activities', api('/api/activities').then(d => d.items || []));
    add('events', api('/api/events').then(d => d.items || []));
    add('communities', api('/api/communities').then(d => d.items || []));
    add('businesses', api('/api/businesses').then(d => d.items || []));
  }
  if (page === 'challenges') add('challenges', api('/api/challenges').then(d => d.items || []));
  if (page === 'communities') add('communities', api('/api/communities').then(d => d.items || []));
  if (page === 'events') add('events', api('/api/events').then(d => d.items || []));
  if (page === 'messages') {
    add('conversations', api('/api/conversations').then(d => d.items || []));
    add('messages', api(`/api/conversations/${pageData.activeConversation}`).then(d => d.items || []));
  }
  if (page === 'profile') { add('xpLedger', api('/api/xp').then(d => d.items || [])); add('achievements', api('/api/achievements').then(d => d.items || [])); add('friends', api('/api/friends').then(d => d.items || [])); }
  if (page === 'reels' || page === 'posts') { add('reels', api('/api/reels').then(d => d.items || [])); if (!pageData.feed.length) add('feed', api('/api/feed').then(d => d.items || [])); }
  if (page === 'businesses') add('businesses', api('/api/businesses').then(d => d.items || []));
  if (page === 'workout') { add('workouts', api('/api/workouts').then(d => d.items || [])); add('prs', api('/api/workouts/prs').then(d => d.items || [])); }
  if (page === 'nutrition') { add('nutrition', api('/api/nutrition').then(d => d).catch(() => ({}))); add('water', api('/api/water').then(d => d).catch(() => ({}))); }
  if (page === 'progress') { add('progressEntries', api('/api/progress').then(d => d.items || [])); add('review', api('/api/ai/review').then(d => d.item || {}).catch(() => ({}))); }
  if (page === 'friends') { add('fitmatch', api('/api/fitmatch').then(d => d.items || [])); add('friendsData', api('/api/friends').then(d => d).catch(() => ({}))); }
  if (page === 'library') add('exercises', api('/api/exercises').then(d => d.items || []));
  if (page === 'coach') add('coachChat', api('/api/ai/coach').then(d => d.items || []).catch(() => []));
  if (page === 'communityDetail' && state.detailId) add('detailData', api(`/api/community?id=${state.detailId}`).then(d => d.item || {}));
  if (page === 'athleteProfile' && state.detailId) add('detailData', api(`/api/athletes/${state.detailId}`).then(d => d.item || {}));
  if (page === 'bookings') add('bookings', api('/api/bookings').then(d => d.items || []));
  if (page === 'business') { add('businesses', api('/api/businesses').then(d => d.items || [])); add('bookings', api('/api/bookings').then(d => d.items || [])); }
  if (page === 'admin') { add('stats', api('/api/stats').then(d => d.items || {})); add('reports', api('/api/reports').then(d => d.items || [])); }
  if (page === 'home') { add('activities', api('/api/activities').then(d => d.items || [])); loadWeather(); loadQuote(); }
  await Promise.all(tasks);
  if (tasks.length) render();
}
async function loadMessages() {
  try { pageData.messages = (await api(`/api/conversations/${pageData.activeConversation}`)).items || []; }
  catch (e) { toast(e.message); }
  render();
}

function shell(content) {
  const u = unread();
  return `<div class="app-shell">
  <aside class="sidebar"><a class="brand" data-page="home"><i>F</i> FITVERSE</a><p class="eyebrow">PLAY TOGETHER</p><nav>${nav.map(([id, icon, label]) => `<button class="nav-item ${state.page === id ? 'active' : ''}" data-page="${id}"><span>${icon}</span>${label}${id === 'messages' && u ? `<b>${u}</b>` : ''}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="mini-profile">${photoAvatar(me().name, 1)}<div><strong>${escapeHtml(me().name || 'Sai Kumar')}</strong><small>Level ${level()} · ${levelName()}</small></div></div><button class="create-btn" data-action="create">＋ Create</button></div></aside>
  <main>${content}</main><nav class="mobile-nav" aria-label="Primary">${mobileNav.map(([p, i]) => `<button data-page="${p}" class="${state.page === p ? 'active' : ''}" aria-label="${p}"><span aria-hidden="true">${i}</span><small>${p}</small></button>`).join('')}</nav><div id="toast" role="status" aria-live="polite"></div><div id="modal"></div></div>`;
}
function pageHeader(title, sub = 'Your fitness world, in motion.') {
  const u = unread();
  return `<header class="top"><div><span class="eyebrow">FITVERSE / ${state.page.toUpperCase()}</span><h1>${title}</h1><p>${sub}</p></div><div class="top-actions"><button class="icon-btn" data-action="notifications" title="Notifications">♧${u ? `<em>${u}</em>` : ''}</button><button class="icon-btn" data-action="cmdk" title="Search (Ctrl+K)">⌕</button><button class="profile-chip" data-page="profile">${photoAvatar(me().name, 1)}<span>Sai</span><i>⌄</i></button></div></header>`;
}
function home() {
  const s = pageData.dash || {};
  const notes = pageData.buddy || [];
  const post = pageData.feed[0];
  const topRec = (pageData.fitmatch || pageData.recommendations)[0] || pageData.recommendations[0];
  return shell(`${pageHeader(`Good ${greeting()}, ${escapeHtml((me().name || 'Sai').split(' ')[0])} 👋`, s.today_line || 'Here’s your day at a glance.')}
<section class="hero photo" style="background-image:linear-gradient(100deg, rgba(8,18,13,.96) 42%, rgba(8,18,13,.62) 100%), url('${PHOTOS.heroBasketball}')"><div><span class="pill lime">● WEEK ${weekNumber()}</span><h2>Fitness is better<br/>when it’s a <span>game.</span></h2><p id="wx-advice">${wx ? workoutAdvice() : 'Keep your streak alive. You’re one activity away from your weekly goal.'}</p><div id="wx-chip" class="wx-chip">${wx ? weatherChipHtml() : 'Loading live weather…'}</div><div class="hero-actions"><button class="primary" data-page="workout">Start today’s session <b>→</b></button><button class="text-btn" data-page="coach">Ask FITVERSE AI</button></div></div><div class="hero-orbit"><div class="orbit-core">${state.streak}<small>DAY STREAK</small></div><div class="float-card one">🔥<strong>${pageData.counts.friends || 0} friends</strong><small>in your circle</small></div><div class="float-card two">⚡<strong>Level ${level()}</strong><small>${levelName()}</small></div></div></section>
<section class="dash-grid">
  <article class="stat-card"><span>🍽</span><div><small>CALORIES</small><strong>${s.kcal ? `${s.kcal.eaten.toLocaleString()} <em>/ ${s.kcal.target.toLocaleString()}</em>` : '—'}</strong></div><i>${s.kcal ? `${Math.round(s.kcal.eaten / Math.max(1, s.kcal.target) * 100)}%` : ''}</i><div class="bar slim"><i style="width:${s.kcal ? Math.min(100, s.kcal.eaten / Math.max(1, s.kcal.target) * 100) : 0}%"></i></div></article>
  <article class="stat-card"><span>🥩</span><div><small>PROTEIN</small><strong>${s.kcal ? `${s.kcal.protein}<em>/${s.kcal.proteinTarget}g</em>` : '—'}</strong></div><i>${s.kcal ? Math.round(s.kcal.protein / Math.max(1, s.kcal.proteinTarget) * 100) + '%' : ''}</i><div class="bar slim"><i style="width:${s.kcal ? Math.min(100, s.kcal.protein / Math.max(1, s.kcal.proteinTarget) * 100) : 0}%"></i></div></article>
  <article class="stat-card"><span>💧</span><div><small>WATER</small><strong>${s.water ? `${(s.water.today_ml / 1000).toFixed(1)}<em>/${(s.water.target_ml / 1000).toFixed(1)}L</em>` : '—'}</strong></div><i>${s.water ? Math.round(s.water.today_ml / Math.max(1, s.water.target_ml) * 100) + '%' : ''}</i><div class="bar slim"><i style="width:${s.water ? Math.min(100, s.water.today_ml / Math.max(1, s.water.target_ml) * 100) : 0}%"></i></div></article>
  <article class="stat-card"><span>🏋</span><div><small>THIS WEEK</small><strong>${s.week && s.week.sessions != null ? `${s.week.sessions}<em> workouts</em>` : `${Math.min(4, state.activities)}<em>/4</em>`}</strong></div><i>${s.week && s.week.kcal ? `${s.week.kcal} kcal` : ''}</i></article>
</section>
${notes.length ? `<section class="buddy-strip"><span class="pill lime">✦ FITVERSE AI</span>${notes.slice(0, 3).map(n => `<p>${n.note}</p>`).join('')}</section>` : ''}
<section class="stat-grid"><div class="stat-card"><span>🔥</span><div><small>STREAK</small><strong>${state.streak} days</strong></div><i>↗ ${s.week ? (s.week.sessions >= 3 ? 'on fire' : 'building') : ''}</i></div><div class="stat-card"><span>⚡</span><div><small>YOUR XP</small><strong>${state.xp.toLocaleString()} <em>XP</em></strong></div><i>LEVEL ${level()}</i></div><div class="stat-card goal"><div><small>WEEKLY GOAL</small><strong>${s.week && s.week.sessions != null ? Math.min(s.week.sessions, s.week.goal || 4) : Math.min(4, state.activities)} / ${s.week ? s.week.goal || 4 : 4} workouts</strong></div><div class="bar"><i style="width:${Math.min(100, ((s.week ? s.week.sessions : state.activities) / (s.week ? s.week.goal || 4 : 4)) * 100)}%"></i></div><button data-action="complete">Complete activity +</button></div></section>
<section class="section-head"><div><span class="eyebrow">FROM YOUR CREW</span><h2>The FITVERSE feed</h2></div><button class="link" data-action="create">Share an update <b>→</b></button></section>
<div class="tabs" id="feed-tabs">${['For You', 'Following', 'Trending'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-ftab="${t.toLowerCase().replace(' ', '')}">${t}</button>`).join('')}</div>
<div id="feed-foryou">${pageData.feed.length ? pageData.feed.slice(0, 8).map(postCard).join('') : emptyState('📭', 'No posts yet', 'Share your first fitness update or follow some athletes to fill your feed.', 'create', 'Create a post')}</div>
<div id="feed-following" style="display:none">${emptyState('👥', 'Follow more athletes', 'Posts from people you follow appear here. Find your crew on Discover.', 'discover', 'Find people')}</div>
<div id="feed-trending" style="display:none">${pageData.feed.length ? [...pageData.feed].sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 6).map(postCard).join('') : emptyState('📈', 'Nothing trending yet', 'Be the spark — post your last workout.', 'create', 'Create a post')}</div>
<section class="home-split"><div><div class="section-head"><div><span class="eyebrow">FIT MATCH</span><h2>Your #1 training match</h2></div><button class="link" data-page="friends">See all matches <b>→</b></button></div><div class="match-card"><div class="match-art"><span>${topRec ? topRec.score : 94}%</span><small>FIT MATCH</small></div><div class="match-copy">${photoAvatar(topRec ? topRec.name : 'Rahul Menon', topRec?.id || 2)}<div><h3>${escapeHtml(topRec ? topRec.name : 'Rahul Menon')} <i>✓</i></h3><p>${escapeHtml(topRec ? `${topRec.activity} · ${topRec.fitnessLevel || topRec.fitness_level} · ${topRec.preferredTime || topRec.preferred_time}` : 'Basketball · Intermediate · 5–6 PM')}</p><div class="tag-row">${((topRec?.reasons) || ['Same sport', 'Nearby']).map(r => `<span>${escapeHtml(r)}</span>`).join('')}</div></div><button class="primary small" data-action="friend" data-id="${topRec?.id || 2}">${state.friends ? 'Friends ✓' : 'Add friend'}</button></div></div></div><div class="feed-mini"><div class="section-head"><div><span class="eyebrow">TRENDING NOW</span><h2>Popular with friends</h2></div></div>${post ? postCard(post) : '<article class="post"><p>No posts yet — be the first to share.</p></article>'}</div></section>
<section class="quote-bar" id="quote-bar">${quote || 'Small steps every day.'}</section>`);
}
function emptyState(icon, title, body, page, cta) {
  return `<div class="empty-state"><span aria-hidden="true">${icon}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${page ? `<button class="primary small" data-page="${page}">${escapeHtml(cta)}</button>` : ''}</div>`;
}
function greeting() { const h = new Date().getHours(); return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'; }
function weekNumber() { const d = new Date(); const start = new Date(d.getFullYear(), 0, 1); return Math.ceil((((d - start) / 86400000) + start.getDay() + 1) / 7); }
const POST_KINDS = { fitness_update: ['✦', 'Update'], workout: ['🏋', 'Workout'], progress: ['📈', 'Progress'], meal: ['🍽', 'Meal'], achievement: ['🏆', 'Achievement'], challenge: ['⚡', 'Challenge'], motivation: ['🔥', 'Motivation'], question: ['❓', 'Question'], reel: ['🎬', 'Reel'], activity: ['🏃', 'Activity'], community: ['◌', 'Community'] };
function postCard(p) {
  const [icon, label] = POST_KINDS[p.kind] || ['✦', 'Update'];
  return `<article class="post" data-post="${p.id}"><div class="post-author">${photoAvatar(p.name, p.author_id || p.id)}<div><strong>${escapeHtml(p.name)}</strong><small>${icon} ${label} · ${timeShort(p.created_at)}</small></div><button data-action="postMenu" data-id="${p.id}">•••</button></div><p>${escapeHtml(p.body)}</p>${p.photo ? (p.media === 'video' ? `<video class="post-photo" src="${p.photo}" controls preload="metadata"></video>` : `<img class="post-photo" src="${p.photo}" alt="" loading="lazy"/>`) : ''}<div class="post-actions"><button data-action="like" data-id="${p.id}">${p.liked ? '♥ Liked' : '♡ Like'} <small>${p.likes}</small></button><button data-action="comment" data-id="${p.id}">◌ Comment <small>${p.comments}</small></button><button data-action="share" data-id="${p.id}">↗ Share</button></div></article>`;
}
function activity(icon, title, people, time, place, type, id, joined) {
  return `<article class="activity-card" data-action="activityDetail" data-id="${id || 1}" style="cursor:pointer"><div class="activity-icon photo-tile" style="background-image:url('${sportPhoto(type)}')"><span>${icon}</span></div><div class="activity-meta"><span>${escapeHtml(type)}</span><h3>${escapeHtml(title)}</h3><p>◉ ${escapeHtml(place)}</p><div><b>◷ ${escapeHtml(time)}</b><b>◉ ${escapeHtml(people)}</b></div></div><button class="join ${joined ? 'joined' : ''}" data-action="joinActivity" data-id="${id || 1}">${joined ? 'Joined ✓' : 'Join +'}</button></article>`;
}
function discover() {
  const recs = pageData.recommendations.length ? pageData.recommendations : [];
  const top = recs[0];
  const others = recs.slice(1, 7);
  return shell(`${pageHeader('Discover your people', 'Matches, activities and communities around Chennai.')}
<div class="discover-intro"><div><span class="pill lime">✦ MATCHED FOR YOU</span><h2>Find your <em>fitness people.</em></h2><p>Our matching engine considers activity preference, schedules, goals, location and intensity.</p></div><button class="filter" data-action="filters">☷ Filters <b>⌄</b></button></div><div class="tabs" id="discover-tabs">${['People', 'Activities', 'Communities', 'Events', 'Businesses'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-tab="${t.toLowerCase()}">${t}</button>`).join('')}</div><div class="search">⌕ <input id="discover-search" placeholder="Search people, activities, communities..."/><span>⌘ K</span></div>
<div id="tab-people">${top ? `<section class="match-feature"><div class="match-big-art"><div>${top.score}<small>%</small></div><span>YOUR TOP MATCH</span></div><div class="match-feature-copy">${avatar(top.name, 'blue')}<span class="verified">${escapeHtml(top.name)} ✓</span><h2>Designed for the<br/><em>same rhythm.</em></h2><p>You both love ${escapeHtml(top.activity)} and your schedules and intensity line up well.</p><div class="compat"><b>Why ${top.score}%?</b>${(top.reasons || []).map(r => `<span>✓ ${escapeHtml(r)}</span>`).join('')}</div><div class="hero-actions"><button class="primary" data-action="friend" data-id="${top.id}">${state.friends ? 'Friends ✓' : 'Add friend'}</button><button class="outline" data-action="challenge" data-id="${top.id}">Challenge ${escapeHtml(top.name.split(' ')[0])}</button></div></div><div class="match-score"><strong>${top.score}<span>%</span></strong><small>COMPATIBILITY SCORE</small><div class="bar"><i style="width:${top.score}%"></i></div><p>Excellent match</p></div></section>` : ''}
<section class="section-head"><div><span class="eyebrow">MORE FOR YOU</span><h2>Keep the momentum going</h2></div><button class="link" data-page="challenges">View all <b>→</b></button></section><div class="people-grid">${others.map(p => personCard(p)).join('') || '<article class="person-card"><div class="person-cover orange"><span>92% match</span></div><div class="person-info">' + avatar('Vikram Shah', 'orange') + '<h3>Vikram Shah <i>✓</i></h3><p>Basketball · Advanced</p><div><button class="outline" data-action="friend" data-id="2">Add friend</button><button class="more" data-action="personMenu" data-id="2">•••</button></div></div></article>'}</div></div>
<div id="tab-activities" style="display:none"><div class="activity-grid">${pageData.activities.map(a => activity('🏀', a.title, `${a.participant_count} people`, `${dayShort(a.starts_at)} · ${timeShort(a.starts_at)}`, a.location_label, a.sport, a.id, a.joined)).join('') || '<p class="loading">No activities yet.</p>'}</div></div>
<div id="tab-communities" style="display:none"><div class="community-grid">${pageData.communities.map(communityCard).join('') || '<p class="loading">No communities yet.</p>'}</div></div>
<div id="tab-events" style="display:none"><div class="event-grid">${pageData.events.map(eventCard).join('') || '<p class="loading">No events yet.</p>'}</div></div>
<div id="tab-businesses" style="display:none"><table class="data-table"><thead><tr><th>BUSINESS</th><th>CATEGORY</th><th>LOCATION</th><th>RATING</th></tr></thead><tbody>${pageData.businesses.map(row => `<tr><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.category)}</td><td>${escapeHtml(row.location_label)}</td><td>★ ${row.rating}</td></tr>`).join('') || '<tr><td colspan="4">Loading…</td></tr>'}</tbody></table></div>`);
}
function personCard(p) {
  const score = p.score ?? (80 + (p.id * 3) % 18);
  return `<article class="person-card" data-person="${p.id}"><div class="person-cover photo" style="background-image:linear-gradient(rgba(20,40,60,.15), rgba(20,40,60,.55)), url('${p.photo || sportPhoto(p.activity || p.favorite_activity)}')"><span>${score}% match</span></div><div class="person-info">${photoAvatar(p.name, p.id)}<h3>${escapeHtml(p.name)} <i>✓</i></h3><p>${escapeHtml(p.activity || p.favorite_activity || '')} · ${escapeHtml(p.fitnessLevel || p.fitness_level || '')}</p><div><button class="outline" data-action="friend" data-id="${p.id}">Add friend</button><button class="more" data-action="personMenu" data-id="${p.id}">•••</button></div></div></article>`;
}
function challenges() {
  const c = pageData.challenges[0];
  const active = state.challenge === 'accepted' || state.challenge === 'won';
  const oppProgress = c ? (c.opponent_id === 1 ? c.opponent_progress : c.challenger_progress) : 4.2;
  const myProgress = c ? (c.challenger_id === 1 ? c.challenger_progress : c.opponent_progress) : 3.8;
  return shell(`${pageHeader('Challenges', 'Play harder with the people who keep you going.')}
<section class="challenge-hero"><div><span class="pill coral">HEAD TO HEAD</span><h2>${state.challenge === 'won' ? 'You took the win.' : active ? 'The run is on.' : 'Rahul challenged you.'}</h2><p>${state.challenge === 'won' ? 'Victory looks good on you. Start another challenge?' : active ? `You have until ${c ? dayShort(c.ends_at) : 'Sunday'} to make your move.` : 'A 5K race is waiting for your answer.'}</p><div class="versus"><div>${avatar(c?.challenger_name || 'Rahul Menon', 'blue')}<strong>${escapeHtml((c?.challenger_name || 'Rahul').split(' ')[0])}</strong><small>${oppProgress} km</small></div><b>VS</b><div>${avatar('Sai Kumar', 'mint')}<strong>You</strong><small>${myProgress} km</small></div></div>${state.challenge === 'pending' ? '<button class="primary" data-action="accept">Accept challenge <b>→</b></button>' : state.challenge === 'accepted' ? '<button class="primary" data-action="win">Mark activity complete +120 XP</button>' : '<button class="primary" data-action="challenge" data-id="2">New challenge vs Rahul</button>'}</div><div class="challenge-kpi"><span>🏃</span><small>5K RUN</small><strong>${active ? '4 days' : '7 days'}</strong><p>${active ? 'remaining' : 'to accept'}</p></div></section>
<section class="section-head"><div><span class="eyebrow">YOUR ARENA</span><h2>Active challenges</h2></div><button class="create-inline" data-action="challenge">＋ New challenge</button></section><div class="challenge-list">${pageData.challenges.map(ch => `<article><span>⚡</span><div><b>${escapeHtml(ch.title)}</b><p>${escapeHtml(ch.challenge_type)} · vs ${escapeHtml(ch.challenger_id === 1 ? ch.opponent_name : ch.challenger_name)}</p></div><div class="challenge-progress"><strong>${ch.status}</strong><div class="bar"><i style="width:${Math.min(100, Math.round(((ch.challenger_id === 1 ? ch.challenger_progress : ch.opponent_progress) / (ch.target_value || 5)) * 100))}%"></i></div></div>${ch.status === 'active' ? '<button class="outline" data-action="win">Complete</button>' : `<button class="outline" data-action="challengeView" data-id="${ch.id}">View</button>`}</article>`).join('') || '<article><span>⚡</span><div><b>September Streak</b><p>Complete 4 activities this week</p></div><div class="challenge-progress"><strong>' + Math.min(4, state.activities) + '/4</strong><div class="bar"><i style="width:' + Math.min(100, state.activities * 25) + '%"></i></div></div><button class="outline" data-action="complete">Log activity</button></article>'}</div>
<section class="leaderboard"><div><span class="eyebrow">CAMPUS LEADERBOARD</span><h2>XP leaders this week</h2>${(pageData.leaderboard || []).slice(0, 5).map((r, i) => `<div class="rank ${r.name === me().name ? 'you' : ''}"><b>0${i + 1}</b>${avatar(r.name, ['blue', 'mint', 'teal', 'orange', 'purple'][i % 5])}<strong>${escapeHtml(r.name === me().name ? 'You' : r.name)}</strong><em>${r.xp.toLocaleString()} XP</em></div>`).join('')}</div><div class="level-card"><span>LEVEL ${level()}</span><h3>${levelName()}</h3><p>${Math.max(0, 500 - (state.xp % 500))} XP until ${levelName(1) || 'next'} level</p><div class="bar"><i style="width:${progress()}%"></i></div></div></section>`);
}
function communityCard(c) {
  return `<article class="community-card" data-community="${c.id}"><div class="community-cover photo" style="background-image:linear-gradient(rgba(11,23,17,.25), rgba(11,23,17,.45)), url('${sportPhoto(c.activity)}')" data-action="communityOpen" data-id="${c.id}" role="button" title="Open community"><span>🏀</span><small>${(c.member_count || 0).toLocaleString()} members</small></div><div><h3 data-action="communityOpen" data-id="${c.id}" role="button">${escapeHtml(c.name)}</h3><p>${escapeHtml(c.description)}</p><button class="${c.joined ? 'outline' : 'primary small'}" data-action="${c.joined ? 'leaveCommunity' : 'joinCommunity'}" data-id="${c.id}">${c.joined ? 'Joined ✓' : 'Join community'}</button><button class="more" data-action="communityMenu" data-id="${c.id}">•••</button></div></article>`;
}
function communities() {
  return shell(`${pageHeader('Communities', 'Find a place to belong, wherever you move.')}
<div class="community-hero"><span class="pill lime">YOUR COMMUNITIES</span><h2>Move with your <em>people.</em></h2><p>From first-time runners to court regulars — your next crew is here.</p><button class="primary" data-action="createCommunity">＋ Create community</button></div><div class="community-grid">${pageData.communities.map(communityCard).join('') || '<p class="loading">Loading communities…</p>'}</div>`);
}
function eventCard(e) {
  return `<article class="event-card" data-event="${e.id}"><div class="event-img photo" style="background-image:url('img/${e.photo}')"><span>${escapeHtml(e.category.toUpperCase())}</span><b>${dayShort(e.starts_at)}</b></div><div><h3>${escapeHtml(e.name)}</h3><p>⌖ ${escapeHtml(e.location_label)} · ${e.booked_count || 0} attending</p><strong>${inr(e.price_inr)}</strong><div style="display:flex;gap:6px"><button class="outline" data-action="bookEvent" data-id="${e.id}">${e.booked ? 'Booked ✓' : 'Book now'}</button><button class="more" data-action="eventDetail" data-id="${e.id}" title="Details">ℹ</button></div></div></article>`;
}
function events() {
  const hero = pageData.events.find(e => e.id === 1) || pageData.events[0];
  const rest = pageData.events.filter(e => e !== hero);
  return shell(`${pageHeader('Fitness events', 'Save your spot. Show up for the story.')}
${hero ? `<div class="event-hero photo" style="background-image:linear-gradient(90deg, rgba(10,16,20,.94) 45%, rgba(10,16,20,.45) 100%), url('${sportPhoto(hero.category)}')"><div><span class="pill coral">FEATURED · ${dayShort(hero.starts_at).toUpperCase()}</span><h2>${escapeHtml(hero.name.split(' ').slice(0, -1).join(' '))} <em>${escapeHtml(hero.name.split(' ').slice(-1))}</em></h2><p>${escapeHtml(hero.description)}</p><div class="event-details"><span>◷ ${dayShort(hero.starts_at)} · ${timeShort(hero.starts_at)}</span><span>⌖ ${escapeHtml(hero.location_label)}</span></div><button class="primary" data-action="bookEvent" data-id="${hero.id}">${hero.booked ? 'Booked ✓' : `Book ${inr(hero.price_inr)}`} <b>→</b></button></div><div class="event-art"><div class="moon"></div><span>RUN<br/>THE<br/>NIGHT</span><small>${escapeHtml(hero.category.toUpperCase())}</small></div></div>` : '<p class="loading">Loading events…</p>'}<section class="section-head"><div><span class="eyebrow">UP NEXT</span><h2>More ways to show up</h2></div><button class="filter" data-action="eventFilter">All categories ⌄</button></section><div class="event-grid">${rest.map(eventCard).join('')}</div>`);
}
function messages() {
  const convs = pageData.conversations.length ? pageData.conversations : [{ id: 1, title: 'Rahul Menon', kind: 'direct' }];
  const active = convs.find(c => c.id === pageData.activeConversation) || convs[0];
  const msgs = pageData.messages;
  // Group consecutive messages by sender; day dividers; photo avatars.
  const bubbles = msgs.map((m, i) => {
    const prev = msgs[i - 1];
    const mine = m.sender_id === 1;
    const grouped = prev && prev.sender_id === m.sender_id;
    const showDay = !prev || new Date(prev.created_at).toDateString() !== new Date(m.created_at).toDateString();
    return `${showDay ? `<div class="day-divider"><span>${dayShort(m.created_at)}</span></div>` : ''}<div class="msg-row ${mine ? 'mine' : ''} ${grouped ? 'grouped' : ''}">${!grouped ? photoAvatar(m.name || (mine ? 'Sai' : 'Rahul'), m.sender_id) : '<span class="pavatar-spacer"></span>'}<p class="${mine ? 'sent' : 'received'}">${escapeHtml(m.body)}<time>${m.created_at?.includes('T') ? timeShort(m.created_at) : escapeHtml(m.created_at || 'now')}</time></p></div>`;
  }).join('') || '<p style="opacity:.6">Say hi 👋</p>';
  return shell(`${pageHeader('Messages', 'Real conversations, stored in your database.')}
<div class="message-layout"><aside class="conversation-list"><div class="message-search">⌕ <input id="chat-search" placeholder="Search chats" style="border:0;background:none;outline:0;width:80%"/></div>${convs.map(c => `<button class="conversation ${c.id === pageData.activeConversation ? 'selected' : ''}" data-conv="${c.id}">${photoAvatar(c.title, c.id)}<div><strong>${escapeHtml(c.title)}</strong><small>${escapeHtml((c.last_message || 'Say hi').slice(0, 34))}</small></div><time>${c.last_at ? timeShort(c.last_at) : ''}</time></button>`).join('')}</aside><section class="chat"><div class="chat-head">${photoAvatar(active.title, active.id)}<div><strong>${escapeHtml(active.title)}</strong><small>${escapeHtml(active.kind)} · <span class="live-dot">●</span> live</small></div><button data-action="convMenu" data-id="${active.id}">•••</button></div><div class="bubbles" id="bubbles">${bubbles}</div><div class="typing" id="typing" style="display:none"><span></span><span></span><span></span></div><form class="composer" data-form="message" data-conv="${active.id}"><input id="composer-input" placeholder="Message ${escapeHtml(String(active.title).split(' ')[0])}..." maxlength="1000" required/><button aria-label="Send message">➤</button></form></section></div>`);
}
function profile() {
  const p = me();
  const unlocked = pageData.achievements.filter(a => a.unlocked_at).length;
  return shell(`${pageHeader('Your profile', 'Your progress tells a story.')}
<section class="profile-hero"><div class="profile-cover photo" style="background-image:linear-gradient(110deg, rgba(22,79,62,.88), rgba(110,175,112,.6)), url('${PHOTOS.heroRun}')"></div><div class="profile-info">${avatar(p.name, 'mint')}<div><span class="pill lime">LEVEL ${level()} · ${levelName().toUpperCase()}</span><h2>${escapeHtml(p.name || 'Sai Kumar')} <i>✓</i></h2><p>@${escapeHtml(p.username || 'saikumar')} · ${escapeHtml(p.city || 'Chennai')}</p><p class="bio">${escapeHtml(p.bio || '')}</p></div><div class="profile-actions"><button class="outline" data-action="edit">Edit profile</button><button class="text-btn" data-action="account">Account</button></div></div><div class="profile-stats"><span><b>${state.streak}</b> day streak</span><span><b>${state.xp.toLocaleString()}</b> XP</span><span><b>${state.activities}</b> activities</span><span><b>${pageData.friends.length}</b> friends</span></div></section><div class="profile-tools"><button class="outline" data-page="bookings">🎟 My bookings</button><button class="outline" data-page="coach">✦ AI Coach</button><button class="outline" data-page="business">▦ Business</button><button class="outline" data-page="admin">◫ Admin</button></div><div class="tabs" id="profile-tabs">${['Posts', 'Friends', 'Achievements'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-ptab="${t.toLowerCase()}">${t}</button>`).join('')}</div>
<div id="ptab-posts">${pageData.feed.filter(x => x.username === p.username).map(postCard).join('') || '<p class="loading">No posts yet — create one from the ＋ button.</p>'}</div>
<div id="ptab-friends" style="display:none">${pageData.friends.map(f => `<article class="person-card" style="max-width:420px"><div class="person-info" style="padding:14px">${avatar(f.name, 'teal')}<h3>${escapeHtml(f.name)} <i>✓</i></h3><p>@${escapeHtml(f.username)} · ${escapeHtml(f.status)}</p></div></article>`).join('') || '<p class="loading">No friends yet — find matches on Discover.</p>'}</div>
<div id="ptab-achievements" style="display:none"><div class="achievement-row">${pageData.achievements.map(a => `<article class="${a.unlocked_at ? '' : 'locked'}" style="${a.unlocked_at ? '' : 'opacity:.45'}"><span>${a.icon}</span><b>${escapeHtml(a.name)}</b><small>${escapeHtml(a.description)}</small></article>`).join('')}</div><p class="loading">${unlocked}/${pageData.achievements.length} unlocked</p></div>`);
}
function bookings() {
  return shell(`${pageHeader('My bookings', 'Your upcoming experiences, all in one place.')}
<section class="section-head"><div><span class="eyebrow">YOUR TICKETS</span><h2>Ready when you are</h2></div><button class="link" data-page="events">Find events <b>→</b></button></section><div class="booking-list">${pageData.bookings.length ? pageData.bookings.map(item => `<article class="booking-item"><span class="ticket-check">✓</span><div><span class="eyebrow">${escapeHtml(item.status.toUpperCase())}</span><h3>${escapeHtml(item.name)}</h3><p>${dayShort(item.starts_at)} · ${escapeHtml(item.location_label)} · ${item.quantity} ticket${item.quantity > 1 ? 's' : ''}</p><strong>${escapeHtml(item.booking_code)}</strong></div><div class="qr">▦<br/>▥</div></article>`).join('') : `<article class="booking-item"><span>🎟️</span><div><h3>No bookings yet</h3><p>Find an event that moves you, then your digital ticket will appear here.</p></div><button class="outline" data-page="events">Browse events</button></article>`}</div>`);
}
function coach() {
  return shell(`${pageHeader('FITVERSE Coach', 'Contextual recommendations from your profile and the FITVERSE network.')}
<section class="coach-layout"><span class="pill lime">DETERMINISTIC RECOMMENDATIONS</span><h2>What can I help you move toward?</h2><p class="coach-answer">${escapeHtml(pageData.coach)}</p><form class="composer" data-form="coach"><input placeholder="Ask what you should do today..." maxlength="250" required/><button aria-label="Ask coach">➤</button></form><div class="coach-prompts"><button data-action="coachPrompt" data-q="Find basketball players">Find basketball players</button><button data-action="coachPrompt" data-q="Suggest a challenge">Suggest a challenge</button><button data-action="coachPrompt" data-q="Find an event this weekend">Find an event this weekend</button></div></section>`);
}
// ===== FITVERSE 2.0 pages =====
function workoutPage() {
  const w = pageData.workouts || [];
  const prs = pageData.prs || [];
  return shell(`${pageHeader('Workout', 'Log sessions, track volume, celebrate PRs.')}
<div class="workout-top"><button class="primary" data-action="logWorkout">＋ Log a workout</button><button class="outline" data-action="generateWorkout">✦ Generate with AI</button><button class="outline" data-page="library">Exercise library</button></div>
<section class="section-head"><div><span class="eyebrow">HISTORY</span><h2>Recent sessions</h2></div></section>
${w.length ? `<div class="session-list">${w.map(s => `<article class="session-card">
  <div class="session-date"><b>${dayShort(s.created_at)}</b><small>${timeShort(s.created_at)}</small></div>
  <div class="session-body"><h3>${escapeHtml(s.title)}</h3>
    ${s.logs.map(l => `<p class="setline">${escapeHtml(l.name)} <b>${l.sets}×${l.reps}</b>${l.weight > 0 ? ` @ ${l.weight}kg` : ''}${l.is_pr ? ' <span class="pr-flag">🔥 PR</span>' : ''}</p>`).join('')}
    <div class="session-stats"><span>⏱ ${s.duration_min} min</span><span>🏋 ${Math.round(s.total_volume).toLocaleString()} kg volume</span><span>⚡ ~${s.est_kcal} kcal</span>${s.pr_count ? `<span class="pr-flag">🔥 ${s.pr_count} PR${s.pr_count > 1 ? 's' : ''}</span>` : ''}</div>
  </div>
</article>`).join('')}</div>` : emptyState('🏋', 'No workouts yet', 'Complete your first workout to start building your fitness history.', null, null)}
${prs.length ? `<section class="section-head"><div><span class="eyebrow">PERSONAL RECORDS</span><h2>Your best lifts</h2></div></section><div class="pr-grid">${prs.map(p => `<article class="pr-card"><b>${escapeHtml(p.name)}</b><strong>${p.max_w ? p.max_w + ' kg' : Math.round(p.max_vol || 0) + ' vol'}</strong><small>${p.n} sessions logged</small></article>`).join('')}</div>` : ''}`);
}
function nutritionPage() {
  const n = pageData.nutrition || {};
  const t = n.targets || {};
  const tot = n.totals || { kcal: 0, protein: 0, carbs: 0, fat: 0 };
  const meals = ['breakfast', 'lunch', 'dinner', 'snacks'];
  const water = pageData.water || {};
  return shell(`${pageHeader('Nutrition', 'Fuel the work. Log meals, hit your targets.')}
<div class="macro-hero"><div class="macro-main"><span class="eyebrow">CALORIES TODAY</span><div class="macro-big"><b>${(tot.kcal || 0).toLocaleString()}</b><em>/ ${(t.kcal_target || 2200).toLocaleString()} kcal</em></div><div class="bar"><i style="width:${Math.min(100, (tot.kcal || 0) / Math.max(1, t.kcal_target || 2200) * 100)}%"></i></div><small class="est-note">${t.estimate_note || ''}</small></div>
<div class="macro-row">
  <div class="macro-chip p"><b>${tot.protein || 0}g</b><small>/ ${t.protein_target || 130}g protein</small><div class="bar slim"><i style="width:${Math.min(100, (tot.protein || 0) / Math.max(1, t.protein_target || 130) * 100)}%"></i></div></div>
  <div class="macro-chip c"><b>${tot.carbs || 0}g</b><small>/ ${t.carbs_target || 250}g carbs</small><div class="bar slim"><i style="width:${Math.min(100, (tot.carbs || 0) / Math.max(1, t.carbs_target || 250) * 100)}%"></i></div></div>
  <div class="macro-chip f"><b>${tot.fat || 0}g</b><small>/ ${t.fat_target || 70}g fat</small><div class="bar slim"><i style="width:${Math.min(100, (tot.fat || 0) / Math.max(1, t.fat_target || 70) * 100)}%"></i></div></div>
</div></div>
<div class="water-card"><div><span class="eyebrow">HYDRATION</span><div class="macro-big"><b>${((water.today_ml || 0) / 1000).toFixed(2)}L</b><em>/ ${((water.target_ml || 2500) / 1000).toFixed(1)}L</em></div><div class="bar"><i style="width:${Math.min(100, (water.today_ml || 0) / Math.max(1, water.target_ml || 2500) * 100)}%"></i></div></div>
<div class="water-actions"><button class="outline" data-action="addWater" data-ml="250">+250ml</button><button class="outline" data-action="addWater" data-ml="500">+500ml</button><button class="primary small" data-action="addWater" data-ml="750">+750ml</button></div></div>
<div class="section-head" style="margin-top:22px"><div><span class="eyebrow">FOOD DIARY</span><h2>Today's meals</h2></div><button class="primary small" data-action="logMeal">＋ Log food</button><button class="outline small" data-action="scanMeal">✦ AI meal scan</button></div>
${meals.map(m => {
  const items = (n.items || []).filter(x => x.meal === m);
  const mkcal = items.reduce((a, b) => a + b.kcal, 0);
  return `<div class="meal-block"><h4>${m[0].toUpperCase() + m.slice(1)} <small>${mkcal ? mkcal + ' kcal' : ''}</small></h4>
  ${items.length ? items.map(i => `<div class="meal-item"><span>${escapeHtml(i.name)}</span><b>${i.kcal} kcal · ${Math.round(i.protein_g)}g protein</b><button class="more" data-action="delMeal" data-id="${i.id}" aria-label="Delete">×</button></div>`).join('') : '<p class="loading">Nothing logged yet.</p>'}</div>`;
}).join('')}`);
}
function progressPage() {
  const entries = pageData.progressEntries || [];
  const weights = entries.filter(e => e.weight_kg).slice(0, 12).reverse();
  const review = pageData.review && pageData.review.week ? pageData.review : null;
  return shell(`${pageHeader('Progress', 'Private by default. Visible to you alone.')}
${review ? `<section class="review-card"><div class="review-head"><span class="pill lime">✦ YOUR WEEKLY RECAP</span><h3>${escapeHtml(review.week)}</h3><button class="more" data-action="shareRecap" title="Share card">↗</button></div>
<div class="review-grid"><div><b>${review.workouts}</b><small>workouts</small></div><div><b>${review.calories_burned.toLocaleString()}</b><small>kcal burned</small></div><div><b>${review.avg_protein}g</b><small>avg protein</small></div><div><b>${review.new_prs}</b><small>new PRs</small></div><div><b>${review.consistency}%</b><small>consistency</small></div><div><b>${review.streak}</b><small>day streak</small></div></div>
<div class="review-tips">${review.suggestions.map(s => `<p>💡 ${escapeHtml(s)}</p>`).join('')}</div></section>` : ''}
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
  return shell(`${pageHeader('Friends', 'Your people. Your crew. Your competition.')}
${incoming.length ? `<section class="req-strip"><span class="pill coral">${incoming.length} REQUEST${incoming.length > 1 ? 'S' : ''}</span>${incoming.map(r => `<div class="req-row">${photoAvatar(r.name, r.id)}<div><b>${escapeHtml(r.name)}</b><small>@${escapeHtml(r.username)}</small></div><button class="primary small" data-action="acceptFriend" data-id="${r.req_id}">Accept</button><button class="more" data-action="rejectFriend" data-id="${r.req_id}">×</button></div>`).join('')}</section>` : ''}
<section class="section-head"><div><span class="eyebrow">✦ AI MATCHING</span><h2>FIT MATCH</h2></div></section>
${fm.length ? `<div class="people-grid">${fm.map(p => personCard(p)).join('')}</div>` : emptyState('🧬', 'No matches yet', 'Set your goals in onboarding so FIT MATCH can find your training partners.')}
<section class="section-head"><div><span class="eyebrow">YOUR CIRCLE</span><h2>${friends.length} friend${friends.length === 1 ? '' : 's'}</h2></div></section>
${friends.length ? `<div class="friend-rows">${friends.map(f => `<div class="req-row" data-action="athlete" data-id="${f.id}" style="cursor:pointer">${photoAvatar(f.name, f.id)}<div><b>${escapeHtml(f.name)}</b><small>${escapeHtml(f.favorite_activity || '')} · ${f.streak}-day streak</small></div><button class="outline small" data-action="challenge" data-id="${f.id}">Challenge</button></div>`).join('')}</div>` : emptyState('👥', 'No friends yet', 'Send friend requests from Discover or FIT MATCH — fitness is better together.')}`);
}
function libraryPage() {
  const ex = pageData.exercises || [];
  const muscles = ['All', 'Chest', 'Back', 'Shoulders', 'Arms', 'Legs', 'Glutes', 'Core', 'Cardio', 'Full Body'];
  return shell(`${pageHeader('Exercise library', 'Technique, mistakes and alternatives for ${ex.length} movements.')}
<div class="search">⌕ <input id="lib-search" placeholder="Search exercises..."/></div>
<div class="tabs" id="lib-tabs">${muscles.map((m, i) => `<button class="${i === 0 ? 'active' : ''}" data-muscle="${m}">${m}</button>`).join('')}</div>
<div class="lib-grid">${ex.length ? ex.map(e => `<article class="lib-card" data-action="exerciseDetail" data-id="${e.id}">
  <span class="lib-muscle">${escapeHtml(e.muscle)}</span><h3>${escapeHtml(e.name)}</h3>
  <p>${escapeHtml(e.equipment)} · ${escapeHtml(e.difficulty)}</p>
</article>`).join('') : emptyState('🏋', 'No exercises found', 'Try a different muscle group or search.')}</div>`);
}
function coachPage() {
  const chat = pageData.coachChat || [];
  return shell(`${pageHeader('FITVERSE AI', 'Your personal coach — powered by your real data.')}
<section class="ai-chat" id="ai-chat">
  <div class="ai-intro"><span class="pill lime">✦ FITVERSE AI</span><p>Ask me anything: workouts, nutrition, your progress, or plan my week.</p></div>
  ${chat.map(m => `<div class="ai-msg ${m.role}"><p>${m.content.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</p></div>`).join('')}
</section>
<div class="coach-prompts wrap"><button data-action="coachAsk" data-q="What workout should I do today?">Today's workout?</button><button data-action="coachAsk" data-q="How much protein should I eat?">Protein target?</button><button data-action="coachAsk" data-q="Create a 5-day gym routine">5-day routine</button><button data-action="coachAsk" data-q="I only have dumbbells">Home workout</button><button data-action="generateWorkout">✦ Generate workout</button><button data-action="weeklyReview">📊 Weekly recap</button></div>
<form class="composer wide" id="coach-form"><input placeholder="Ask FITVERSE anything..." maxlength="500" required/><button aria-label="Send">➤</button></form>`);
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
<div class="review-tips">${(r.suggestions || []).map(s => `<p>💡 ${escapeHtml(s)}</p>`).join('')}</div></section>
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
</div>
${tab === 'reels' ? reelsGrid : `${postsTab}${postsGrid}`}`);
}
function businesses() {
  return shell(`${pageHeader('Businesses', 'Gyms, studios and stores — reviewed by the community.')}
<div class="community-hero"><span class="pill lime">LOCAL PARTNERS</span><h2>Where the city <em>trains.</em></h2><p>Every business is real, rated and reviewed by FITVERSE athletes.</p></div>
<div class="biz-grid">${pageData.businesses.map(b => `
<article class="biz-card" data-business="${b.id}">
  <div class="biz-photo photo" style="background-image:url('img/${b.photo || 'workout.jpg'}')"><span>${escapeHtml(b.category)}</span></div>
  <div class="biz-body">
    <h3>${escapeHtml(b.name)}</h3>
    <p>⌖ ${escapeHtml(b.location_label)}</p>
    <div class="biz-row"><span class="stars" title="${b.rating}">${'★'.repeat(Math.round(b.rating))}${'☆'.repeat(5 - Math.round(b.rating))}</span><b>${b.rating}</b><button class="outline small" data-action="businessDetail" data-id="${b.id}">Reviews & details</button></div>
  </div>
</article>`).join('') || '<p class="loading">Loading businesses…</p>'}</div>`);
}
let detailData = null;
function communityDetail() {
  const c = pageData.detailData; if (!c || !c.members) return shell('<p class="loading">Loading community…</p>');
  const joined = c.members.some(m => m.id === (me().id || 1));
  return shell(`${pageHeader(c.name, c.description)}
<div class="community-cover photo big" style="background-image:linear-gradient(rgba(11,23,17,.35), rgba(11,23,17,.55)), url('${sportPhoto(c.activity)}')"><span>◌</span><small>${c.members.length} members · ${escapeHtml(c.activity)}</small></div>
<div class="people-row" style="margin:12px 0">${c.members.map(m => `<button class="pavatar-btn" data-action="athlete" data-id="${m.id}" title="${escapeHtml(m.name)}">${photoAvatar(m.name, m.id)}</button>`).join('')}</div>
<form class="composer wide" id="community-post-form" data-cid="${c.id}"><input placeholder="Share something with ${escapeHtml(c.name.split(' ')[0])}..." maxlength="2000" required/><button aria-label="Post">➤</button></form>
<div class="feed-col">${c.posts.map(postCard).join('') || '<p class="loading">No posts yet — start the conversation!</p>'}</div>
<section class="section-head"><div><span class="eyebrow">COMMUNITY EVENTS</span><h2>Coming up</h2></div></section>
<div class="event-grid">${c.events.map(eventCard).join('') || '<p class="loading">No events for this community yet.</p>'}</div>
<div class="hero-actions" style="margin-top:14px"><button class="${joined ? 'outline' : 'primary'}" data-action="${joined ? 'leaveCommunity' : 'joinCommunity'}" data-id="${c.id}" data-back="community">${joined ? 'Joined ✓ — leave' : 'Join community'}</button><button class="outline" data-page="communities">All communities</button></div>`);
}
function athleteProfile() {
  const a = pageData.detailData; if (!a || !a.badges) return shell('<p class="loading">Loading athlete…</p>');
  const isMe = a.id === (me().id || 1);
  return shell(`${pageHeader(a.name, '@' + (a.username || '') + ' · ' + (a.city || 'Chennai'))}
<section class="profile-hero"><div class="profile-cover photo" style="background-image:linear-gradient(110deg, rgba(22,79,62,.88), rgba(110,175,112,.6)), url('${a.photo || sportPhoto(a.favorite_activity)}')"></div>
<div class="profile-info">${photoAvatar(a.name, a.id)}<div><span class="pill lime">LEVEL ${Math.floor((a.xp || 0) / 500) + 1} · ${['Rookie', 'Mover', 'Athlete', 'Warrior', 'Legend'][Math.min(4, Math.floor((a.xp || 0) / 500))]}</span><h2>${escapeHtml(a.name)} <i>✓</i></h2><p class="bio">${escapeHtml(a.bio || 'No bio yet.')}</p><p>${escapeHtml(a.favorite_activity || '')} · ${escapeHtml(a.fitness_level || '')} · ${escapeHtml(a.preferred_time || '')}</p></div>
<div class="profile-actions">${isMe ? '<button class="outline" data-page="profile">Your profile</button>' : `<button class="primary" data-action="friend" data-id="${a.id}">Add friend</button><button class="outline" data-action="challenge" data-id="${a.id}">Challenge</button><button class="outline" data-action="messageUser" data-id="${a.id}">Message</button>`}</div></div>
<div class="profile-stats"><span><b>${a.streak || 0}</b> day streak</span><span><b>${(a.xp || 0).toLocaleString()}</b> XP</span><span><b>${a.activities || 0}</b> activities</span><span><b>${a.badges.length}</b> badges</span></div></section>
<div class="tabs" id="athlete-tabs">${['Posts', 'Activities', 'Badges'].map((t, i) => `<button class="${i === 0 ? 'active' : ''}" data-atab="${t.toLowerCase()}">${t}</button>`).join('')}</div>
<div id="atab-posts">${a.posts.map(postCard).join('') || '<p class="loading">No posts yet.</p>'}</div>
<div id="atab-activities" style="display:none"><div class="activity-grid">${a.activities.map(x => activity('🏀', x.title, `${x.participant_count} people`, `${dayShort(x.starts_at)} · ${timeShort(x.starts_at)}`, x.location_label, x.sport, x.id, x.joined)).join('') || '<p class="loading">Not hosting anything right now.</p>'}</div></div>
<div id="atab-badges" style="display:none"><div class="achievement-row">${a.badges.map(b => `<article><span>${b.icon}</span><b>${escapeHtml(b.name)}</b><small>Unlocked ${dayShort(b.unlocked_at)}</small></article>`).join('') || '<p class="loading">No badges yet.</p>'}</div></div>`);
}
function render() {
  const pages = { home, discover, posts: reels, reels, challenges, communities, events, messages, profile, bookings, business, admin, businesses, communityDetail, athleteProfile, workout: workoutPage, nutrition: nutritionPage, progress: progressPage, friends: friendsPage, library: libraryPage, coach: coachPage, weeklyReview: weeklyReviewPage };
  $('#app').innerHTML = (pages[state.page] || home)();
  bind();
}
function modal(content) { $('#modal').innerHTML = `<div class="modal-backdrop" data-action="close"></div><section class="modal-card">${content}<button class="modal-x" data-action="close">×</button></section>`; }
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
  <div class="hero-actions"><button class="primary" type="submit">${isReel ? 'Publish reel' : 'Publish post'}</button></div>
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
  $('#composer-form').onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    if (isReel && !mediaPath) { toast('Reels need a video or photo — pick one above'); return; }
    try {
      await api('/api/posts', { method: 'POST', body: JSON.stringify({ body: f.body, kind: f.kind, photo: mediaPath || undefined, meta: mediaIsVideo ? 'video' : undefined }) });
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
function shareCard(kind) {
  const r = pageData.review || {};
  const canvas = document.createElement('canvas');
  canvas.width = 1080; canvas.height = 1350;
  const c = canvas.getContext('2d');
  const grad = c.createLinearGradient(0, 0, 1080, 1350);
  grad.addColorStop(0, '#0b1711'); grad.addColorStop(1, '#1d3a2d');
  c.fillStyle = grad; c.fillRect(0, 0, 1080, 1350);
  c.fillStyle = '#c9f36b'; c.font = '800 64px Manrope, Arial'; c.fillText('FITVERSE', 80, 140);
  c.fillStyle = '#ffffff'; c.font = '800 88px Manrope, Arial';
  c.fillText('Weekly Recap', 80, 320);
  c.font = '500 40px Manrope, Arial'; c.fillStyle = '#9fb3a4';
  c.fillText(r.week || new Date().toDateString(), 80, 390);
  const stats = [[r.workouts || 0, 'workouts'], [(r.calories_burned || 0).toLocaleString(), 'kcal burned'], [r.avg_protein || 0, 'avg protein g'], [r.new_prs || 0, 'new PRs'], [(r.consistency || 0) + '%', 'consistency'], [r.streak || 0, 'day streak']];
  stats.forEach(([v, label], i) => {
    const x = 80 + (i % 2) * 480, y = 540 + Math.floor(i / 2) * 240;
    c.fillStyle = '#ffffff22'; c.fillRect(x, y - 110, 420, 170);
    c.fillStyle = '#c9f36b'; c.font = '800 84px Manrope, Arial'; c.fillText(String(v), x + 30, y);
    c.fillStyle = '#9fb3a4'; c.font = '500 34px Manrope, Arial'; c.fillText(label, x + 30, y + 44);
  });
  c.fillStyle = '#9fb3a4'; c.font = '500 32px Manrope, Arial';
  c.fillText('Fitness is more fun together → fitverse.app', 80, 1260);
  const a = document.createElement('a');
  a.download = `fitverse-recap.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
  toast('Recap card downloaded — share it anywhere 📲');
}
function scrollBubbles() { const b = $('#bubbles'); if (b) b.scrollTop = b.scrollHeight; }
// Live updates: poll notifications + active conversation so chats and badges stay fresh.
let lastMsgId = 0, pollTimer = null, lastOwnType = 0;
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (!apiEnabled || document.hidden) return;
    try {
      const n = await api(`/api/notifications/since?since=${pageData.notifications[0]?.id || 0}`);
      if (n.items?.length) { pageData.notifications = [...n.items, ...pageData.notifications]; n.items.slice(0, 2).forEach(x => toast(`${x.title} — ${x.body}`)); if (state.page !== 'messages') render(); }
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
function bind() {
  $$('[data-page]').forEach(b => b.onclick = async () => { state.page = b.dataset.page; render(); loadPageData(state.page); window.scrollTo(0, 0); });
  $$('[data-conv]').forEach(b => b.onclick = async () => { pageData.activeConversation = Number(b.dataset.conv); await loadMessages(); window.scrollTo(0, 0); });
  $$('[data-action]').forEach(b => b.onclick = () => action(b.dataset.action, b));
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
  $$('[data-ftab]').forEach(b => b.onclick = () => {
    $$('[data-ftab]').forEach(x => x.classList.toggle('active', x === b));
    ['foryou', 'following', 'trending'].forEach(t => { const el = $(`#feed-${t}`); if (el) el.style.display = t === b.dataset.ftab ? '' : 'none'; });
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
    render();
    try {
      const r = await api('/api/ai/coach', { method: 'POST', body: JSON.stringify({ message: msg }) });
      pageData.coachChat.push({ role: 'coach', content: r.reply });
    } catch (err) {
      pageData.coachChat.push({ role: 'coach', content: 'I could not reach the server just now — give it another shot.' });
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
      pageData.messages.push({ sender_id: 1, body: message, created_at: new Date().toISOString() });
      render(); scrollBubbles();
      await api('/api/messages', { method: 'POST', body: JSON.stringify({ body: message, conversation_id: f.dataset.conv || 1 }) });
      await new Promise(r => setTimeout(r, 600));
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
  const chatSearch = $('#chat-search');
  if (chatSearch) chatSearch.oninput = () => {
    const term = chatSearch.value.toLowerCase();
    $$('.conversation').forEach(c => { c.style.display = c.textContent.toLowerCase().includes(term) ? '' : 'none'; });
  };
  if (state.page === 'messages') {
    setTimeout(() => { scrollBubbles(); const ci = $('#composer-input'); if (ci && document.activeElement !== ci && !document.querySelector('.modal-card')) ci.focus(); }, 60);
  }
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
  const done = (msg, fn) => api('/api/actions', { method: 'POST', body: JSON.stringify({ action: a === 'joinActivity' ? 'join' : a, state: {} }) }).then(async (d) => { if (d.state) applyServerState(d.state); if (fn) await fn(); await hydrate(); render(); toast(msg); }).catch(e => toast(e.message));
  switch (a) {
    case 'account': {
      modal(`<span class="eyebrow">YOUR ACCOUNT</span><h2>Sign in to FITVERSE</h2><p>Use the demo account or create a new profile. Your session is stored only in this browser.</p><form class="activity-form" id="account-form"><label>Username or email<input name="username" value="saikumar" required></label><label>Password<input name="password" type="password" value="demo1234" required></label><button class="primary" type="submit">Sign in</button></form><p class="auth-hint">New here? <button class="text-btn" data-action="register">Create an account</button></p>`);
      $('#account-form').onsubmit = async (e) => {
        e.preventDefault(); const f = new FormData(e.currentTarget);
        try {
          const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: f.get('username'), password: f.get('password') }) });
          sessionToken = result.token; localStorage.setItem('fitverse-session', sessionToken);
          $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast(`Welcome back, ${result.user.name}`);
        } catch (error) { toast(error.message); }
      }; bind(); return;
    }
    case 'register': {
      modal(`<span class="eyebrow">JOIN FITVERSE</span><h2>Create your account</h2><form class="activity-form" id="register-form"><label>Display name<input name="name" required></label><label>Username<input name="username" required></label><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" minlength="6" required></label><button class="primary" type="submit">Create account</button></form>`);
      $('#register-form').onsubmit = async (e) => {
        e.preventDefault(); const f = new FormData(e.currentTarget);
        try {
          const result = await api('/api/auth/register', { method: 'POST', body: JSON.stringify(Object.fromEntries(f)) });
          sessionToken = result.token; localStorage.setItem('fitverse-session', sessionToken);
          $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast('Welcome to FITVERSE!');
        } catch (error) { toast(error.message); }
      }; bind(); return;
    }
    case 'logout': sessionToken = ''; localStorage.removeItem('fitverse-session'); $('#modal').innerHTML = ''; hydrate().then(render); toast('Signed out of this browser session'); return;
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
      state.page = 'messages'; render(); loadPageData('messages');
      toast('Pick a chat and say hi');
      return;
    }
    case 'athlete': {
      $('#modal').innerHTML = '';
      state.page = 'athleteProfile'; state.detailId = id; pageData.detailData = null;
      render(); loadPageData('athleteProfile'); window.scrollTo(0, 0);
      return;
    }
    case 'communityOpen': {
      $('#modal').innerHTML = '';
      state.page = 'communityDetail'; state.detailId = id; pageData.detailData = null;
      render(); loadPageData('communityDetail'); window.scrollTo(0, 0);
      return;
    }    case 'businessDetail': {
      (async () => {
        try {
          const { item: b } = await api(`/api/businesses/${id}`);
        modal(`<div class="detail-photo" style="background-image:url('img/${b.photo || 'workout.jpg'}')"></div><span class="eyebrow">${escapeHtml(b.category.toUpperCase())}</span><h2>${escapeHtml(b.name)}</h2><p>${escapeHtml(b.description || '')}</p><div class="compat"><span>⌖ ${escapeHtml(b.location_label)}</span><span class="stars">${'★'.repeat(Math.round(b.rating))}${'☆'.repeat(5 - Math.round(b.rating))}</span><b>${b.rating}</b></div><span class="eyebrow" style="display:block;margin-top:14px">REVIEWS</span><div class="comment-list">${(b.reviews || []).map(r => `<div class="comment">${avatar(r.name, 'teal')}<div><strong>${escapeHtml(r.name)}</strong><p>${'★'.repeat(r.rating)}</p><p>${escapeHtml(r.body)}</p><small>${timeShort(r.created_at)}</small></div></div>`).join('') || '<p>No reviews yet — be the first.</p>'}</div><form class="activity-form" id="review-form"><label>Your rating<select name="rating"><option value="5">★★★★★</option><option value="4">★★★★</option><option value="3">★★★</option><option value="2">★★</option><option value="1">★</option></select></label><label>Your review<input name="body" placeholder="Great coaches, spotless floor..." required maxlength="600"></label><button class="primary" type="submit">Post review</button></form>`);
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
    case 'bookEvent':
      api(`/api/events/${id}/book`, { method: 'POST', body: JSON.stringify({ quantity: 1 }) })
        .then(async (d) => {
          $('#modal').innerHTML = ''; await loadPageData(state.page); render();
          modal(`<span class="ticket-check">✓</span><span class="eyebrow">BOOKING CONFIRMED</span><h2>You’re in.</h2><div class="ticket"><div class="qr">▦<br/>▥</div><div><b>${escapeHtml(d.bookingCode)}</b><small>${dayShort(new Date().toISOString())} · Show at the gate</small></div></div><button class="primary" data-action="close">Done</button>`);
          toast('Booking confirmed'); bind();
        }).catch(e => toast(e.message));
      return;
    case 'eventFilter': toast('Filters coming to the demo soon — all categories shown'); return;
    case 'challenge': {
      modal(`<span class="eyebrow">NEW CHALLENGE</span><h2>Start a rivalry</h2><form class="activity-form" id="challenge-form"><label>Opponent<select name="opponent_id">${pageData.users.filter(u => u.id !== 1).map(u => `<option value="${u.id}">${escapeHtml(u.name)}</option>`).join('') || '<option value="2">Rahul Menon</option>'}</select></label><label>Type<select name="challenge_type"><option value="running_distance">Running distance (km)</option><option value="gym_sessions">Gym sessions</option><option value="cycling_distance">Cycling distance (km)</option></select></label><label>Target value<input name="target_value" type="number" value="5" min="1" step="0.5"></label><button class="primary" type="submit">Send challenge</button></form>`);
      $('#challenge-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/challenges', { method: 'POST', body: JSON.stringify({ ...f, opponent_id: Number(f.opponent_id), target_value: Number(f.target_value) }) }); $('#modal').innerHTML = ''; await loadPageData('challenges'); state.page = 'challenges'; render(); toast('Challenge sent!'); }
        catch (error) { toast(error.message); }
      }; bind(); return;
    }
    case 'challengeView': toast(`Challenge ${id}: ${state.challenge === 'won' ? 'you won this one' : 'keep pushing!'}`); return;
    case 'accept': done('Challenge accepted — game on!'); return;
    case 'win': done('Challenge complete! +120 XP'); return;
    case 'complete': done('Activity logged! +80 XP'); return;
    case 'coachPrompt': api('/api/coach?q=' + encodeURIComponent(btn.dataset.q)).then(r => { pageData.coach = r.reply; render(); }).catch(e => toast(e.message)); return;
    case 'resolveReport': api(`/api/reports/${id}/resolve`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData('admin'); render(); toast('Report resolved'); }).catch(e => toast(e.message)); return;
    case 'filters': toast('Filters: matching is automatic for now'); return;
    case 'convMenu': toast(`Chat with #${id} — messages are stored in your SQLite database`); return;
    case 'joinActivityById': api(`/api/activities/${id}/join`, { method: 'POST', body: '{}' }).then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast('You joined! See you there'); }).catch(e => toast(e.message)); return;
    case 'leaveActivity': api(`/api/activities/${id}/leave`, { method: 'POST', body: '{}' }).then(async () => { $('#modal').innerHTML = ''; await hydrate(); await loadPageData(state.page); render(); toast('You left the activity'); }).catch(e => toast(e.message)); return;
    case 'completeActivity': api(`/api/activities/${id}/complete`, { method: 'POST', body: '{}' }).then(async (d) => { $('#modal').innerHTML = ''; if (d.state) applyServerState(d.state); await hydrate(); await loadPageData(state.page); render(); toast(d.message || '+80 XP earned!'); }).catch(e => toast(e.message)); return;
    case 'createPost': openComposer('post'); return;
    case 'createReel': openComposer('reel'); return;
    case 'activityDetail': activityDetail(id); return;
    // ===== FITVERSE 2.0 actions =====
    case 'logWorkout': {
      const exs = pageData.exercises.length ? pageData.exercises : (await api('/api/exercises')).items || [];
      pageData.exercises = exs;
      modal(`<span class="eyebrow">LOG WORKOUT</span><h2>How did it go?</h2><form class="activity-form" id="wo-form">
      <label>Session title<input name="title" value="Training session" required maxlength="80"></label>
      <label>Duration (minutes)<input name="duration_min" type="number" value="45" min="5" max="240"></label>
      <div id="wo-rows"><div class="wo-row"><select name="exercise_id">${exs.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${e.muscle})</option>`).join('')}</select><input name="sets" type="number" value="3" min="1" max="20" title="Sets"/><input name="reps" type="number" value="10" min="1" max="100" title="Reps"/><input name="weight" type="number" value="0" min="0" step="0.5" title="Weight kg"/></div></div>
      <button type="button" class="outline small" id="wo-add">＋ Add exercise</button>
      <button class="primary" type="submit">Save workout</button></form>`);
      bind();
      $('#wo-add').onclick = () => $('#wo-rows').insertAdjacentHTML('beforeend', `<div class="wo-row"><select name="exercise_id">${exs.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${e.muscle})</option>`).join('')}</select><input name="sets" type="number" value="3" min="1" max="20"/><input name="reps" type="number" value="10" min="1" max="100"/><input name="weight" type="number" value="0" min="0" step="0.5"/></div>`);
      $('#wo-form').onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        const rows = $$('#wo-rows .wo-row').map(r => { const fd = new FormData(); $$("select,input", r).forEach(el => fd.append(el.name, el.value)); return Object.fromEntries(fd); });
        try {
          const res = await api('/api/workouts', { method: 'POST', body: JSON.stringify({ title: f.get('title'), duration_min: Number(f.get('duration_min')), logs: rows.map(r => ({ exercise_id: Number(r.exercise_id), sets: Number(r.sets), reps: Number(r.reps), weight: Number(r.weight) })) }) });
          $('#modal').innerHTML = '';
          if (res.pr_count > 0) celebrate(res.pr_count);
          toast(`Workout saved! ${res.pr_count ? `🔥 ${res.pr_count} PR${res.pr_count > 1 ? 's' : ''}!` : '+60 XP'}`);
          await hydrate(); await loadPageData('workout'); state.page = 'workout'; render();
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'generateWorkout': {
      modal(`<span class="eyebrow">✦ AI GENERATOR</span><h2>Build my workout</h2><form class="activity-form" id="gen-form">
      <label>Goal<select name="goal"><option>Build muscle</option><option>Lose fat</option><option>Get stronger</option><option>Endurance</option></select></label>
      <label>Duration (min)<select name="duration"><option>30</option><option selected>45</option><option>60</option><option>75</option></select></label>
      <label>Focus<select name="style"><option value="upper">Upper body</option><option value="lower">Lower body</option><option value="push">Push (chest/shoulders/arms)</option><option value="pull">Pull (back/arms)</option><option value="legs">Legs & glutes</option><option value="full">Full body</option></select></label>
      <label>Equipment<select name="equipment"><option>Full gym</option><option>Home dumbbells</option><option>Bodyweight</option></select></label>
      <button class="primary" type="submit">✦ Generate</button></form>`);
      bind();
      $('#gen-form').onsubmit = async (e) => {
        e.preventDefault();
        const f = Object.fromEntries(new FormData(e.currentTarget));
        const styleMap = { upper: ['Chest', 'Back', 'Shoulders'], lower: ['Legs', 'Glutes', 'Core'], push: ['Chest', 'Shoulders', 'Arms'], pull: ['Back', 'Arms'], legs: ['Legs', 'Glutes'], full: ['Chest', 'Back', 'Legs', 'Core'] };
        try {
          const { item: plan } = await api('/api/ai/workout', { method: 'POST', body: JSON.stringify({ goal: f.goal.toLowerCase(), duration: Number(f.duration), equipment: f.equipment, muscles: styleMap[f.style] }) });
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
      const p = window.__lastPlan; if (!p) return;
      $('#modal').innerHTML = '';
      const exs = (await api('/api/exercises')).items || [];
      pageData.exercises = exs;
      const byName = Object.fromEntries(exs.map(e => [e.name, e.id]));
      const logs = p.items.map(x => ({ exercise_id: byName[x.exercise] || exs[0].id, sets: x.sets, reps: parseInt(x.reps) || 10, weight: 0 })).filter(x => x.exercise_id);
      try {
        const res = await api('/api/workouts', { method: 'POST', body: JSON.stringify({ title: p.title, duration_min: parseInt(p.params.duration) || 45, logs }) });
        if (res.pr_count) celebrate(res.pr_count);
        toast(`Workout saved — +60 XP${res.pr_count ? ` · 🔥 ${res.pr_count} PR!` : ''}`);
        state.page = 'workout'; await loadPageData('workout'); render();
      } catch (err) { toast(err.message); }
      return;
    }
    case 'logMeal': {
      modal(`<span class="eyebrow">LOG FOOD</span><h2>What did you eat?</h2><form class="activity-form" id="meal-form">
      <label>Meal<select name="meal"><option value="breakfast">Breakfast</option><option value="lunch" selected>Lunch</option><option value="dinner">Dinner</option><option value="snacks">Snack</option></select></label>
      <label>Food<input name="name" placeholder="Grilled chicken and rice" required maxlength="100"></label>
      <label>Calories<input name="kcal" type="number" value="400" min="0" max="3000" required></label>
      <label>Protein (g)<input name="protein_g" type="number" value="30" min="0" max="300"></label>
      <button class="primary" type="submit">Add to diary</button></form>`);
      bind();
      $('#meal-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try { await api('/api/nutrition', { method: 'POST', body: JSON.stringify({ ...f, kcal: Number(f.kcal), protein_g: Number(f.protein_g) }) }); $('#modal').innerHTML = ''; await loadPageData('nutrition'); render(); toast('Meal logged · +5 XP'); }
        catch (err) { toast(err.message); }
      };
      return;
    }
    case 'scanMeal': {
      modal(`<span class="eyebrow">✦ AI MEAL SCANNER</span><h2>Describe your meal</h2><p class="loading">The AI estimates nutrition from your description. Photo scanning with real vision models is coming soon.</p>
      <form class="activity-form" id="scan-form"><label>What's on the plate?<input name="desc" placeholder="grilled chicken with rice and broccoli" required maxlength="200"></label>
      <label>Portion (grams)<input name="grams" type="number" value="400" min="50" max="2000"></label>
      <button class="primary" type="submit">✦ Analyze</button></form>`);
      bind();
      $('#scan-form').onsubmit = async (e) => {
        e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget));
        try {
          const { item: r } = await api('/api/ai/meal', { method: 'POST', body: JSON.stringify(f) });
          if (!r.matched) { toast(r.note); return; }
          modal(`<span class="eyebrow">✦ ESTIMATED</span><h2>${escapeHtml(r.title)}</h2>
          <div class="scan-result"><div class="scan-big"><b>${r.totals.kcal}</b><em>kcal</em></div>
          <div class="scan-macros"><span><b>${r.totals.protein_g}g</b><small>protein</small></span><span><b>${r.totals.carbs_g}g</b><small>carbs</small></span><span><b>${r.totals.fat_g}g</b><small>fat</small></span></div>
          ${r.items.map(i => `<p class="loading">${escapeHtml(i.food)} · ${i.grams}g · ${i.kcal} kcal</p>`).join('')}
          <p class="loading est-note">${escapeHtml(r.note)}</p></div>
          <div class="hero-actions"><button class="primary" id="scan-add" data-meal="lunch">Add to diary</button><button class="outline" data-action="close">Edit instead</button></div>`);
          bind();
          $('#scan-add').onclick = async () => {
            try { await api('/api/nutrition', { method: 'POST', body: JSON.stringify({ name: r.title, meal: 'lunch', kcal: r.totals.kcal, protein_g: r.totals.protein_g, carbs_g: r.totals.carbs_g, fat_g: r.totals.fat_g }) }); $('#modal').innerHTML = ''; await loadPageData('nutrition'); render(); toast('Added to diary'); } catch (err) { toast(err.message); }
          };
        } catch (err) { toast(err.message); }
      };
      return;
    }
    case 'delMeal':
      api(`/api/nutrition/${id}`, { method: 'POST', body: '{}' }).then(async () => { await loadPageData('nutrition'); render(); toast('Removed'); }).catch(e => toast(e.message)); return;
    case 'addWater':
      api('/api/water', { method: 'POST', body: JSON.stringify({ ml: Number(btn.dataset.ml) }) }).then(async () => { await loadPageData('nutrition'); render(); toast(`💧 +${btn.dataset.ml}ml logged`); }).catch(e => toast(e.message)); return;
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
      modal(`<span class="eyebrow">${escapeHtml(e.muscle.toUpperCase())} · ${escapeHtml(e.equipment.toUpperCase())}</span><h2>${escapeHtml(e.name)}</h2>
      <p>${escapeHtml(e.instructions)}</p>
      <div class="mistake-box"><b>⚠ Common mistakes</b><p>${escapeHtml(e.mistakes)}</p></div>
      <p class="loading">${escapeHtml(e.difficulty)} · ${e.met} MET intensity</p>
      <div class="hero-actions"><button class="primary" data-action="logWorkout">Log a session</button></div>`);
      bind(); return;
    }
    case 'coachAsk': {
      const q = btn.dataset.q;
      pageData.coachChat = pageData.coachChat || [];
      pageData.coachChat.push({ role: 'user', content: q });
      render();
      try {
        const r = await api('/api/ai/coach', { method: 'POST', body: JSON.stringify({ message: q }) });
        pageData.coachChat.push({ role: 'coach', content: r.reply });
      } catch (err) { pageData.coachChat.push({ role: 'coach', content: 'I hit a snag reaching the server — try again in a moment.' }); }
      render(); return;
    }
    case 'weeklyReview':
      $('#modal').innerHTML = ''; state.page = 'progress'; await loadPageData('progress'); render(); window.scrollTo(0, 0); return;
    case 'shareRecap': shareCard('weekly-recap'); return;
    case 'genWorkoutFromOnboarding': $('#modal').innerHTML = ''; action('generateWorkout', null); return;
    case 'cmdk': cmdk(); return;
    case 'close': $('#modal').innerHTML = ''; return;
    default: toast('Coming soon in the demo'); return;
  }
}
// ---- Server-Sent Events: instant chat & notification push (replaces polling for chat) ----
let evtSource = null;
function startSSE() {
  if (!apiEnabled || evtSource) return;
  try {
    evtSource = new EventSource(`/api/stream?since=${pageData.notifications[0]?.id || 0}`);
    evtSource.addEventListener('message', (e) => {
      const m = JSON.parse(e.data);
      if (state.page === 'messages' && Number(m.conversation_id) === Number(pageData.activeConversation)) {
        pageData.messages.push(m); render(); scrollBubbles();
      }
    });
    evtSource.addEventListener('notification', (e) => {
      const n = JSON.parse(e.data);
      if (!pageData.notifications.some(x => x.id === n.id)) { pageData.notifications.unshift(n); toast(`${n.title} — ${n.body}`); if (state.page !== 'messages') render(); }
    });
    evtSource.addEventListener('typing', (e) => {
      try {
        const t = JSON.parse(e.data);
        const el = $('#typing');
        const show = (t.conversations || []).includes(Number(pageData.activeConversation));
        if (el) el.style.display = show ? 'flex' : 'none';
      } catch (_) {}
    });
    evtSource.onerror = () => { /* browser auto-reconnects */ };
  } catch (_) { /* SSE unsupported — polling still runs */ }
}
// Onboarding: multi-step profile setup for new users
function runOnboarding() {
  const steps = [
    { title: 'Welcome to FITVERSE 👋', body: `<p class="loading">Let's personalize your experience. A few quick questions — skip anything you'd rather not share.</p><label>Your age<input name="age" type="number" min="13" max="90" placeholder="21"></label><label>Sex (for calorie estimates)<select name="sex"><option value="male">Male</option><option value="female">Female</option></select></label>` },
    { title: 'Your body stats', body: `<label>Height (cm)<input name="height_cm" type="number" min="120" max="230" placeholder="175"></label><label>Weight (kg)<input name="weight_kg" type="number" min="30" max="300" step="0.5" placeholder="70"></label>` },
    { title: 'Your goal', body: `<label>Main goal<select name="goal"><option>Build muscle</option><option>Lose weight</option><option>Maintain</option><option>Endurance</option><option>General fitness</option></select></label><label>Experience<select name="experience"><option>Beginner</option><option selected>Intermediate</option><option>Advanced</option></select></label>` },
    { title: 'Training style', body: `<label>Days per week<select name="days_per_week"><option>2</option><option>3</option><option selected>4</option><option>5</option><option>6</option></select></label><label>Session length<select name="session_minutes"><option>30</option><option selected>45</option><option>60</option><option>90</option></select></label><label>Equipment<select name="equipment"><option>Full gym</option><option>Home dumbbells</option><option>Bodyweight only</option></select></label>` },
    { title: 'Lifestyle', body: `<label>Activity level (outside workouts)<select name="activity_level"><option value="low">Mostly sitting</option><option value="moderate" selected>Moderately active</option><option value="high">Very active</option></select></label><label>Diet preference<select name="diet_pref"><option>balanced</option><option>vegetarian</option><option>high-protein</option></select></label>` },
  ];
  let step = 0;
  const answers = {};
  function draw() {
    const s = steps[step];
    modal(`<span class="eyebrow">SETUP ${step + 1}/${steps.length}</span><h2>${s.title}</h2><form class="activity-form" id="ob-form">${s.body}
    <div class="hero-actions"><button class="primary" type="submit">${step === steps.length - 1 ? 'Finish → generate my plan' : 'Next →'}</button>${step > 0 ? '<button class="text-btn" type="button" id="ob-back">Back</button>' : ''}<button class="text-btn" type="button" id="ob-skip">Skip all</button></div></form>`);
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
      try {
        const r = await api('/api/onboarding', { method: 'POST', body: JSON.stringify(payload) });
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
    $('#ob-skip').onclick = () => { api('/api/settings', { method: 'POST', body: JSON.stringify({ onboarded: 1 }) }).finally(() => { $('#modal').innerHTML = ''; }); };
  }
  draw();
}
render();
hydrate().then(async () => {
  render(); loadPageData(state.page); startPolling(); startSSE(); loadWeather(); loadQuote();
  try {
    const s = await api('/api/me/settings');
    if (s.item && !s.item.onboarded) runOnboarding();
  } catch (_) {}
});
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdk(); }
  if (e.key === 'Escape') $('#modal').innerHTML = '';
});
