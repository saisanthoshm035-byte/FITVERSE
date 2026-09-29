/* ============================================================
   FITVERSE 2026 — real interactive 3D models (three.js, WebGL).
   • Home hero:   holographic globe — drag to spin (inertia), click = pulse
   • Fitness DNA: double-helix built from your real DNA score vibe —
                  drag to rotate, auto-orients, spins gently
   Zero build step: three.js loads from unpkg CDN (free, cached).
   Renders only while on-screen & tab visible; inert if WebGL missing;
   static pose under prefers-reduced-motion; auto-rebuilds after each
   SPA re-render via MutationObserver. No data is faked — models are
   pure visuals and never touch your stats.
   ============================================================ */
(function () {
  'use strict';
  if (window.__fvSix) return; window.__fvSix = true;

  var THREE_VERSION = '0.160.0';
  var reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  var STATE = { failed: false };
  var instances = {};

  function loadThree(cb) {
    if (window.THREE) return cb();
    var s = document.createElement('script');
    s.src = 'https://unpkg.com/three@' + THREE_VERSION + '/build/three.min.js';
    s.onload = function () { cb(); };
    s.onerror = function () { STATE.failed = true; };  // offline: site stays fully usable
    document.head.appendChild(s);
  }

  function mountFor(kind) {
    if (kind === 'hero') return document.getElementById('hero3d-mount');
    if (kind === 'dna') return document.getElementById('dna3d-mount');
    return null;
  }

  /* ---------------- model builders (pure visuals) ---------------- */

  function randDir() {
    var v = new THREE.Vector3(Math.random() * 2 - 1, Math.random() * 2 - 1, Math.random() * 2 - 1);
    if (v.lengthSq() === 0) v.set(1, 0, 0);
    return v.normalize();
  }

  // Holographic planet: icosahedron wireframe + inner core + surface dots + orbit ring
  function buildGlobe() {
    var g = new THREE.Group();
    g.add(new THREE.Mesh(
      new THREE.IcosahedronGeometry(14, 2),
      new THREE.MeshBasicMaterial({ color: 0x9fe870, wireframe: true, transparent: true, opacity: 0.5 })));
    g.add(new THREE.Mesh(
      new THREE.IcosahedronGeometry(6.5, 1),
      new THREE.MeshBasicMaterial({ color: 0xc9f36b, wireframe: true, transparent: true, opacity: 0.3 })));
    var dotGeo = new THREE.SphereGeometry(0.55, 6, 6);
    var dotMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9 });
    var ringMat = new THREE.MeshBasicMaterial({ color: 0x8fd0ff, transparent: true, opacity: 0.85 });
    for (var i = 0; i < 42; i++) {
      var m = new THREE.Mesh(dotGeo, dotMat);
      m.position.copy(randDir().multiplyScalar(15));
      g.add(m);
    }
    for (var k = 0; k < 26; k++) {
      var a = (k / 26) * Math.PI * 2;
      var m2 = new THREE.Mesh(dotGeo, k % 4 === 0 ? ringMat : dotMat);
      m2.position.set(Math.cos(a) * 20.5, (k % 2 ? -1 : 1) * 1.6, Math.sin(a) * 20.5);
      g.add(m2);
    }
    return g;
  }

  // DNA double helix: two lime strand dots + blue rungs (built from small spheres)
  function buildHelix() {
    var g = new THREE.Group();
    var strandMat = new THREE.MeshBasicMaterial({ color: 0xc9f36b, transparent: true, opacity: 0.95 });
    var rungMat = new THREE.MeshBasicMaterial({ color: 0x8fd0ff, transparent: true, opacity: 0.8 });
    var nodeGeo = new THREE.SphereGeometry(1, 10, 10);
    var N = 26, R = 9, H = 62;
    for (var i = 0; i < N; i++) {
      var a = (i / N) * Math.PI * 4;
      var y = -H / 2 + (i / (N - 1)) * H;
      var x1 = Math.cos(a) * R, z1 = Math.sin(a) * R;
      var x2 = -x1, z2 = -z1;
      var m1 = new THREE.Mesh(nodeGeo, strandMat); m1.position.set(x1, y, z1); m1.scale.setScalar(1.7);
      var m2 = new THREE.Mesh(nodeGeo, strandMat); m2.position.set(x2, y, z2); m2.scale.setScalar(1.7);
      g.add(m1); g.add(m2);
      if (i % 2 === 0) {           // rung: 5 beads bridging the strands (no rotation math, always aligned)
        for (var b = 1; b <= 5; b++) {
          var f = b / 6;
          var bead = new THREE.Mesh(nodeGeo, rungMat);
          bead.position.set(x1 + (x2 - x1) * f, y, z1 + (z2 - z1) * f);
          bead.scale.setScalar(0.75);
          g.add(bead);
        }
      }
    }
    return g;
  }

  var MODELS = { globe: buildGlobe, helix: buildHelix };

  /* ---------------- scene plumbing ---------------- */

  function makeRenderer(mount, touchAction) {
    var r = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    r.setSize(mount.clientWidth || 300, mount.clientHeight || 300, false);
    r.domElement.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:' + touchAction + ';';
    mount.insertBefore(r.domElement, mount.firstChild);
    return r;
  }

  function makeScene(mount, kind, touchAction) {
    var renderer = makeRenderer(mount, touchAction);
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(38, (mount.clientWidth || 300) / (mount.clientHeight || 300), 0.1, 300);
    camera.position.set(0, 0, 64);
    var model = MODELS[kind]();
    scene.add(model);

    var raf = 0, disposed = false, visible = true;
    var rx = -0.28, ry = 0.6, vry = 0, vrx = 0, dragging = false, lx = 0, ly = 0, pulse = 0, t = 0;
    var el = renderer.domElement;

    function onDown(e) { dragging = true; lx = e.clientX; ly = e.clientY; mount.classList.add('grabbing'); }
    function onMove(e) {
      if (!dragging) return;
      vry = (e.clientX - lx) * 0.006; vrx = (e.clientY - ly) * 0.004;
      ry += vry; rx += vrx; lx = e.clientX; ly = e.clientY;
    }
    function onUp() { dragging = false; mount.classList.remove('grabbing'); }
    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    el.addEventListener('click', function () { pulse = 1; });   // power pulse — visual only
    function onResize() {
      if (disposed) return;
      var W = mount.clientWidth || 300, H = mount.clientHeight || 300;
      camera.aspect = W / H; camera.updateProjectionMatrix();
      renderer.setSize(W, H, false);
    }
    window.addEventListener('resize', onResize);
    if (window.IntersectionObserver) {
      new IntersectionObserver(function (en) { visible = en[0].isIntersecting; }).observe(mount);
    }

    function frame() {
      raf = requestAnimationFrame(frame);
      if (disposed || !visible || document.hidden) return;
      t += 0.016;
      if (!dragging) {
        if (Math.abs(vry) > 1e-4 || Math.abs(vrx) > 1e-4) { ry += vry; rx += vrx; vry *= 0.94; vrx *= 0.94; }
        else if (!reduced) { ry += 0.0035; }                     // idle spin
      }
      model.rotation.y = ry; model.rotation.x = rx;
      if (!reduced) model.position.y = Math.sin(t * 1.2) * 1.4;  // gentle float
      if (pulse > 0) { pulse *= 0.9; model.scale.setScalar(1 + Math.sin((1 - pulse) * Math.PI) * 0.12); }
      renderer.render(scene, camera);
    }
    frame();

    return function dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('resize', onResize);
      renderer.dispose();
      if (el.parentNode) el.parentNode.removeChild(el);
    };
  }

  function ensure(kind, modelKind, touchAction) {
    var mount = mountFor(kind);
    if (!mount || STATE.failed || !window.THREE) return;
    if (instances[kind] && instances[kind].mount === mount) return;   // already live
    if (instances[kind]) { instances[kind].dispose(); delete instances[kind]; }
    try {
      instances[kind] = { dispose: makeScene(mount, modelKind, touchAction), mount: mount };
    } catch (e) {
      STATE.failed = true;   // WebGL unavailable — CSS layer still gives the futuristic feel
    }
  }

  function sweep() {
    ensure('hero', 'globe', 'none');
    ensure('dna', 'helix', 'pan-y');
  }

  var pending = null;
  function start() {
    sweep();
    var app = document.getElementById('app') || document.body;
    new MutationObserver(function () {          // SPA re-renders rebuild the DOM — rebuild with it
      if (pending) clearTimeout(pending);
      pending = setTimeout(sweep, 180);
    }).observe(app, { childList: true, subtree: true });
  }
  loadThree(start);
})();
