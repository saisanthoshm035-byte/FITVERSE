/* ============================================================
   FITVERSE 5.0 — procedural 3D engine (zero dependencies).
   A slow-rotating wireframe globe + orbital particle ring drawn
   on one fixed background <canvas>. Roughly ~300 rotating points
   with perspective projection: real 3D math, GPU-free, and it
   self-throttles (pauses when the tab is hidden, halves FPS on
   small screens / low battery API signal). Respects
   prefers-reduced-motion by drawing a single static frame.
   app.js stays the owner of layout; this file only paints z=-1.
   ============================================================ */
(function () {
  'use strict';
  if (window.__fv3dLoaded) return; window.__fv3dLoaded = true;

  var reduced = false, small = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  function measure() { small = window.innerWidth <= 760; }
  measure();

  var canvas = document.createElement('canvas');
  canvas.id = 'fv3d';
  canvas.setAttribute('aria-hidden', 'true');
  (document.body || document.documentElement).appendChild(canvas);
  var ctx = canvas.getContext('2d', { alpha: true });

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, small ? 1.3 : 1.8);
    canvas.width = Math.floor(window.innerWidth * dpr);
    canvas.height = Math.floor(window.innerHeight * dpr);
    canvas.style.width = window.innerWidth + 'px';
    canvas.style.height = window.innerHeight + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reduced) drawFrame(0.001, true); // one static frame for reduced motion
  }
  window.addEventListener('resize', function () { measure(); resize(); }, { passive: true });

  // ---- scene: globe points (fibonacci sphere) + ring particles ----
  var N = small ? 130 : 230, R = small ? 210 : 300, RING = small ? 40 : 80;
  var pts = [];
  var ga = Math.PI * (3 - Math.sqrt(5));
  for (var i = 0; i < N; i++) {
    var y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
    pts.push({ x: Math.cos(th) * r, y: y, z: Math.sin(th) * r });
  }
  var ring = [];
  for (var j = 0; j < RING; j++) {
    var a = (j / RING) * Math.PI * 2, rr = 1.35 + (j % 5) * 0.045;
    ring.push({ x: Math.cos(a) * rr, y: (Math.random() - 0.5) * 0.16, z: Math.sin(a) * rr, s: 0.5 + Math.random() });
  }

  var t = 0, last = 0, hidden = false;
  document.addEventListener('visibilitychange', function () { hidden = document.hidden; });
  try { // Battery API: save cycles when the device is unplugged and low
    navigator.getBattery && navigator.getBattery().then(function (b) {
      if (b.level < 0.2 && !b.charging) { N = Math.floor(N / 2); RING = Math.floor(RING / 2); }
    });
  } catch (e) {}

  function project(p, rotY, rotX) {
    var cy = Math.cos(rotY), sy = Math.sin(rotY);
    var x1 = p.x * cy - p.z * sy, z1 = p.x * sy + p.z * cy;
    var cx = Math.cos(rotX), sx = Math.sin(rotX);
    var y1 = p.y * cx - z1 * sx, z2 = p.y * sx + z1 * cx;
    var pers = 1 / (2.6 - z2 * 0.9);
    return { sx: x1 * pers, sy: y1 * pers, z: z2, s: pers };
  }

  function drawFrame(dt, still) {
    var w = window.innerWidth, h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);
    if (!still) t += dt;
    var rotY = t * 0.11, rotX = 0.42 + Math.sin(t * 0.13) * 0.07;
    var cx = w > 980 ? w * 0.78 : w * 0.5, cy = h * (w > 980 ? 0.42 : 0.3), scale = Math.min(w, h) * (small ? 0.42 : 0.5);
    var lime = 'rgba(140, 200, 70, ', ink = 'rgba(70, 110, 80, ';

    // globe points (far points dimmer + smaller = depth)
    for (var i = 0; i < pts.length; i++) {
      var q = project(pts[i], rotY, rotX);
      var px = cx + q.sx * scale, py = cy + q.sy * scale;
      var depth = (q.z + 1) / 2;
      var a = 0.10 + depth * 0.30;
      ctx.fillStyle = (q.z > 0 ? lime : ink) + a.toFixed(3) + ')';
      var r = 1 + q.s * 1.6 * (0.5 + depth * 0.8);
      ctx.beginPath(); ctx.arc(px, py, r, 0, 6.283); ctx.fill();
    }
    // orbital ring (particles orbit slightly faster than the globe spins)
    for (var k = 0; k < ring.length; k++) {
      var p2 = ring[k], ang = rotY * 1.6 + k * 0.19;
      var wob = still ? 0 : Math.sin(t * 0.8 + k) * 0.03;
      var q2 = project({ x: Math.cos(ang) * (p2.x), y: p2.y + wob, z: Math.sin(ang) * (p2.x) }, rotY * 0.4, rotX);
      var qx = cx + q2.sx * scale, qy = cy + q2.sy * scale;
      var d2 = (q2.z + 1.6) / 2.6;
      ctx.fillStyle = lime + (0.05 + d2 * 0.22).toFixed(3) + ')';
      ctx.beginPath(); ctx.arc(qx, qy, 0.8 + p2.s * q2.s * 2, 0, 6.283); ctx.fill();
    }
  }

  var frameGap = 33;
  function loop(ts) {
    requestAnimationFrame(loop);
    if (hidden) return;
    if (ts - last < frameGap) return;
    var dt = Math.min(0.05, (ts - last) / 1000); last = ts;
    drawFrame(dt, false);
  }
  function start() { resize(); if (reduced) { drawFrame(0.001, true); return; } frameGap = small ? 50 : 33; requestAnimationFrame(loop); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
