/* ============================================================================
   PHOSPHOR · ambient.js   (zero dependencies)
   Heavier, canvas-based realizations of the "subtle animated background"
   pattern — reach for these when the CSS options (ambient.css) aren't enough.
   THREE tasteful modes, none of them ASCII, none of them generic AI-slop
   particle confetti:

     'flow'      — streaks drifting along a smooth flow field (organic, premium)
     'grid'      — a technical dot-grid breathing under a travelling wave
     'network'   — sparse slow nodes with short links (distributed / security feel)
     'wireframe' — a slowly rotating 3-D polyhedron drawn as glowing lines + nodes
                   (the RICH, non-ASCII answer to "the Libretto rotating shape";
                   opts.shape = icosahedron | octahedron | cube, opts.parallax)

   Pick by product domain (see references/ambient-backgrounds.md). One per page,
   in the hero, low opacity.

   USAGE
     <canvas id="bg" style="color: var(--accent)"></canvas>
     <script src="ambient.js"></script>
     <script>
       phosphorAmbient(document.getElementById('bg'), {
         mode: 'flow',      // 'flow' | 'grid' | 'network' | 'wireframe'
         opacity: 0.5,      // overall alpha — keep it subtle
         mobile: 'reduce',  // 'reduce' (default) | 'off' | 'full'
       });
     </script>

   PERFORMANCE / COMPAT (all automatic):
   - DPR capped at 2; ResizeObserver-driven.
   - prefers-reduced-motion OR navigator.connection.saveData → one static frame.
   - mobile ('reduce'): half density + 30fps cap; ('off'): static frame.
   - IntersectionObserver pauses the rAF loop when scrolled offscreen.
   - Color follows the canvas's CSS `color` (or pass opts.color).
   ============================================================================ */
(function (global) {
  "use strict";

  // ── 3-D helpers for the 'wireframe' mode ──
  function v3dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }
  function rot3(p, ax, ay) {
    var cx = Math.cos(ax), sx = Math.sin(ax), cy = Math.cos(ay), sy = Math.sin(ay);
    var y1 = p[1] * cx - p[2] * sx, z1 = p[1] * sx + p[2] * cx;   // rotate X
    var x2 = p[0] * cy + z1 * sy, z2 = -p[0] * sy + z1 * cy;       // rotate Y
    return [x2, y1, z2];
  }
  function buildSolid(name) {
    var v;
    if (name === "octahedron") {
      v = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
    } else if (name === "cube") {
      v = [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
    } else { // icosahedron (golden-ratio vertices)
      var g = (1 + Math.sqrt(5)) / 2;
      v = [[0,1,g],[0,1,-g],[0,-1,g],[0,-1,-g],[1,g,0],[1,-g,0],
           [-1,g,0],[-1,-g,0],[g,0,1],[g,0,-1],[-g,0,1],[-g,0,-1]];
    }
    v = v.map(function (p) { var l = Math.hypot(p[0], p[1], p[2]) || 1; return [p[0]/l, p[1]/l, p[2]/l]; });
    // edges = vertex pairs at the minimum pairwise distance (works for any convex solid)
    var min = Infinity, i, j;
    for (i = 0; i < v.length; i++) for (j = i + 1; j < v.length; j++) { var d = v3dist(v[i], v[j]); if (d < min) min = d; }
    var e = [];
    for (i = 0; i < v.length; i++) for (j = i + 1; j < v.length; j++) { if (v3dist(v[i], v[j]) <= min * 1.08) e.push([i, j]); }
    return { v: v, e: e };
  }
  function vnorm(p) { var l = Math.hypot(p[0], p[1], p[2]) || 1; return [p[0]/l, p[1]/l, p[2]/l]; }
  // A geodesic point cloud: subdivide each triangular face into `freq` rows of
  // points on the unit sphere; each point remembers its parent face (for facet
  // shading). Triangular solids only (icosahedron / octahedron).
  function buildGeodesic(name, freq) {
    var base = buildSolid(name === "octahedron" ? "octahedron" : "icosahedron");
    var V = base.v, adj = {};
    base.e.forEach(function (e) { (adj[e[0]] = adj[e[0]] || {})[e[1]] = 1; (adj[e[1]] = adj[e[1]] || {})[e[0]] = 1; });
    function isE(a, b) { return adj[a] && adj[a][b]; }
    var faces = [], seen = {};
    base.e.forEach(function (e) {
      var a = e[0], b = e[1], c;
      for (c = 0; c < V.length; c++) {
        if (c !== a && c !== b && isE(a, c) && isE(b, c)) {
          var k = [a, b, c].slice().sort(function (x, y) { return x - y; }).join(",");
          if (!seen[k]) { seen[k] = 1; faces.push([a, b, c]); }
        }
      }
    });
    var points = [], faceNormals = [];
    faces.forEach(function (face, fi) {
      var A = V[face[0]], B = V[face[1]], C = V[face[2]];
      faceNormals.push(vnorm([A[0]+B[0]+C[0], A[1]+B[1]+C[1], A[2]+B[2]+C[2]]));
      for (var i = 0; i <= freq; i++) for (var j = 0; j <= freq - i; j++) {
        var w0 = (freq - i - j) / freq, w1 = i / freq, w2 = j / freq;
        points.push({ p: vnorm([A[0]*w0+B[0]*w1+C[0]*w2, A[1]*w0+B[1]*w1+C[1]*w2, A[2]*w0+B[2]*w1+C[2]*w2]), f: fi });
      }
    });
    return { points: points, faceNormals: faceNormals };
  }

  function phosphorAmbient(canvas, opts) {
    opts = opts || {};
    var mode = opts.mode || "flow";
    var opacity = opts.opacity != null ? opts.opacity : 0.5;
    var mobilePolicy = opts.mobile || "reduce";
    var ctx = canvas.getContext("2d");
    if (!ctx) return { stop: function () {} };
    var parent = canvas.parentElement || canvas;

    var mql = global.matchMedia;
    var reduced = mql && mql("(prefers-reduced-motion: reduce)").matches;
    var saveData = global.navigator && global.navigator.connection && global.navigator.connection.saveData;
    var isMobile = mql && mql("(max-width: 760px)").matches;
    var lowCore = global.navigator && global.navigator.hardwareConcurrency && global.navigator.hardwareConcurrency < 4;
    var constrained = isMobile || lowCore;

    var staticOnly = reduced || saveData || (constrained && mobilePolicy === "off");
    var densityScale = constrained && mobilePolicy === "reduce" ? 0.5 : 1;
    var minFrameMs = constrained && mobilePolicy === "reduce" ? 33 : 0; // ~30fps on phones

    var W = 1, H = 1, dpr = 1, raf = 0, last = 0, t = 0, visible = true;
    var r = 80, g = 220, b = 120;
    var pointer = { x: 0.5, y: 0.5 }, onMove = null;

    function resolveColor() {
      var c = opts.color || getComputedStyle(canvas).color || "rgb(80,220,120)";
      ctx.fillStyle = c; ctx.fillRect(0, 0, 1, 1);
      var p = ctx.getImageData(0, 0, 1, 1).data; r = p[0]; g = p[1]; b = p[2];
      ctx.clearRect(0, 0, 1, 1);
    }
    function rgba(a) { return "rgba(" + r + "," + g + "," + b + "," + a + ")"; }

    /* ── modes ── each: build(state), draw(state, time) ── */
    var state = {};
    var modes = {
      flow: {
        build: function () {
          var n = Math.round((W * H) / 9000 * densityScale);
          n = Math.max(24, Math.min(n, 360));
          state.p = [];
          for (var i = 0; i < n; i++) state.p.push({ x: Math.random(), y: Math.random() });
        },
        draw: function (time) {
          ctx.clearRect(0, 0, W, H);
          ctx.lineCap = "round";
          var s = 3.2; // field scale
          for (var i = 0; i < state.p.length; i++) {
            var pt = state.p[i];
            var fx = pt.x * s, fy = pt.y * s;
            var ang = (Math.sin(fx * 1.1 + time) * Math.cos(fy * 1.3 - time * 0.7) + Math.sin((fx + fy) * 0.7 + time * 0.5)) * Math.PI;
            var vx = Math.cos(ang), vy = Math.sin(ang);
            var px = pt.x * W, py = pt.y * H;
            var len = 14;
            ctx.strokeStyle = rgba(opacity * 0.5);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(px, py);
            ctx.lineTo(px + vx * len, py + vy * len);
            ctx.stroke();
            pt.x += vx * 0.0011; pt.y += vy * 0.0011;
            if (pt.x < -0.02) pt.x = 1.02; if (pt.x > 1.02) pt.x = -0.02;
            if (pt.y < -0.02) pt.y = 1.02; if (pt.y > 1.02) pt.y = -0.02;
          }
        },
      },
      grid: {
        build: function () {
          state.gap = constrained ? 34 : 26;
        },
        draw: function (time) {
          ctx.clearRect(0, 0, W, H);
          var gap = state.gap, cols = Math.ceil(W / gap), rows = Math.ceil(H / gap);
          for (var yi = 0; yi <= rows; yi++) {
            for (var xi = 0; xi <= cols; xi++) {
              var x = xi * gap, y = yi * gap;
              var wave = Math.sin(x * 0.012 + y * 0.01 + time * 1.4);
              var a = (wave * 0.5 + 0.5);
              // vertical fade so it dissolves toward the bottom
              var fade = 1 - (y / H);
              var alpha = opacity * 0.5 * a * a * fade;
              if (alpha < 0.012) continue;
              var rad = 0.7 + a * 1.4;
              ctx.fillStyle = rgba(alpha);
              ctx.beginPath();
              ctx.arc(x, y, rad, 0, 6.2832);
              ctx.fill();
            }
          }
        },
      },
      network: {
        build: function () {
          var n = Math.round((W * H) / 26000 * densityScale);
          n = Math.max(14, Math.min(n, 90));
          state.p = [];
          for (var i = 0; i < n; i++) {
            state.p.push({
              x: Math.random() * W, y: Math.random() * H,
              vx: (Math.random() - 0.5) * 0.16, vy: (Math.random() - 0.5) * 0.16,
            });
          }
          state.link = constrained ? 120 : 150;
        },
        draw: function () {
          ctx.clearRect(0, 0, W, H);
          var P = state.p, L = state.link, i, j;
          for (i = 0; i < P.length; i++) {
            var p = P[i];
            p.x += p.vx; p.y += p.vy;
            if (p.x < 0 || p.x > W) p.vx *= -1;
            if (p.y < 0 || p.y > H) p.vy *= -1;
          }
          for (i = 0; i < P.length; i++) {
            for (j = i + 1; j < P.length; j++) {
              var dx = P[i].x - P[j].x, dy = P[i].y - P[j].y;
              var d = Math.hypot(dx, dy);
              if (d > L) continue;
              ctx.strokeStyle = rgba(opacity * 0.5 * (1 - d / L) * (1 - P[i].y / H));
              ctx.lineWidth = 1;
              ctx.beginPath(); ctx.moveTo(P[i].x, P[i].y); ctx.lineTo(P[j].x, P[j].y); ctx.stroke();
            }
            ctx.fillStyle = rgba(opacity * 0.7 * (1 - P[i].y / H));
            ctx.beginPath(); ctx.arc(P[i].x, P[i].y, 1.4, 0, 6.2832); ctx.fill();
          }
        },
      },
      // ── 'wireframe' — a rotating 3-D polyhedron as glowing lines + nodes ──
      // The rich, non-ASCII replacement for the old ASCII solid. Depth-faded
      // edges (front brighter), node dots, optional cursor parallax.
      wireframe: {
        build: function () {
          state.geo = buildSolid(opts.shape || "icosahedron");
          state.tilt = -0.42;                 // fixed X tilt so it reads 3-D
          state.spin = opts.spinSpeed || 0.5; // radians/sec-ish
          state.scaleK = opts.objectScale || 1;
        },
        draw: function (time) {
          ctx.clearRect(0, 0, W, H);
          var V = state.geo.v, E = state.geo.e;
          var ay = time * state.spin + (pointer.x - 0.5) * 0.9;  // spin + parallax
          var ax = state.tilt + (pointer.y - 0.5) * 0.45;
          var cx = W / 2, cy = H / 2;
          var scale = Math.min(W, H) * 0.34 * state.scaleK;
          var focal = 3.4, P = [], i;
          for (i = 0; i < V.length; i++) {
            var p = rot3(V[i], ax, ay);
            var persp = focal / (focal - p[2]);
            P.push({ x: cx + p[0] * scale * persp, y: cy - p[1] * scale * persp, z: p[2] });
          }
          ctx.lineCap = "round";
          ctx.shadowColor = rgba(Math.min(1, opacity * 0.8));
          for (i = 0; i < E.length; i++) {
            var a = P[E[i][0]], b = P[E[i][1]];
            var depth = ((a.z + b.z) / 2 + 1) / 2;            // 0 back … 1 front
            ctx.strokeStyle = rgba(opacity * (0.12 + depth * 0.62));
            ctx.lineWidth = 0.6 + depth * 1.2;
            ctx.shadowBlur = 7 * depth;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
          ctx.shadowBlur = 9;
          for (i = 0; i < P.length; i++) {
            var d2 = (P[i].z + 1) / 2;
            ctx.fillStyle = rgba(opacity * (0.3 + d2 * 0.7));
            ctx.beginPath(); ctx.arc(P[i].x, P[i].y, 1 + d2 * 1.8, 0, 6.2832); ctx.fill();
          }
          ctx.shadowBlur = 0;
        },
      },
      // ── 'orb' — a large, faint, shaded faceted SPHERE of fine dots ──
      // The faithful, non-ASCII take on the Libretto hedron: a geodesic point
      // cloud, facet-lit, additive-blended so density reads as soft glow, with a
      // radial mask so the silhouette dissolves into the dark. Built to BLEND —
      // very low effective alpha — never to compete with the hero text.
      orb: {
        build: function () {
          var freq = constrained ? 3 : 6;
          state.geo = buildGeodesic(opts.shape || "icosahedron", freq);
          state.tilt = -0.32;
          state.spin = opts.spinSpeed || 0.3;
          state.scaleK = opts.objectScale || 1;
          state.cxf = (opts.center && opts.center.x) || 0.5;
          state.cyf = (opts.center && opts.center.y) || 0.5;
          state.light = vnorm([0.35, 0.7, 0.62]);
        },
        draw: function (time) {
          ctx.clearRect(0, 0, W, H);
          var pts = state.geo.points, fn = state.geo.faceNormals, L = state.light;
          var ay = time * state.spin + (pointer.x - 0.5) * 0.5;
          var ax = state.tilt + (pointer.y - 0.5) * 0.22;
          var cx = W * state.cxf, cy = H * state.cyf;
          var R = Math.min(W, H) * 0.52 * state.scaleK;
          var focal = 3.8, i;
          // rotate face normals once per frame (≤20)
          var rfn = [];
          for (i = 0; i < fn.length; i++) rfn[i] = rot3(fn[i], ax, ay);
          ctx.save();
          ctx.globalCompositeOperation = "lighter";
          for (i = 0; i < pts.length; i++) {
            var n = rfn[pts[i].f];
            var facing = n[2];                       // >0 → faces the camera
            if (facing < -0.15) continue;            // cull the deep far side
            var p = rot3(pts[i].p, ax, ay);
            var persp = focal / (focal - p[2]);
            var sx = cx + p[0] * R * persp, sy = cy - p[1] * R * persp;
            var ndotl = Math.max(0, n[0]*L[0] + n[1]*L[1] + n[2]*L[2]);
            var shade = 0.12 + 0.88 * Math.pow(ndotl, 0.8);   // deeper facet contrast
            var face = facing > 0 ? (0.32 + 0.68 * facing) : 0.1 * (1 + facing / 0.15);
            var rd = Math.hypot(sx - cx, sy - cy) / (R * 1.04);
            var mask = rd < 0.82 ? 1 : Math.max(0, 1 - (rd - 0.82) / 0.42);
            var a = opacity * 0.6 * shade * face * mask;
            if (a < 0.008) continue;
            ctx.fillStyle = rgba(a);
            ctx.beginPath(); ctx.arc(sx, sy, 0.85 + face * 1.05, 0, 6.2832); ctx.fill();
          }
          ctx.restore();
        },
      },
    };
    var impl = modes[mode] || modes.flow;

    function resize() {
      var box = parent.getBoundingClientRect();
      W = Math.max(1, box.width); H = Math.max(1, box.height);
      dpr = Math.min(global.devicePixelRatio || 1, 2);
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      canvas.style.width = W + "px"; canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      resolveColor();
      impl.build();
    }

    function loop(now) {
      if (!visible) { raf = 0; return; }
      if (now - last >= minFrameMs) { t += 0.0016 * (now - last || 16); impl.draw(t); last = now; }
      raf = global.requestAnimationFrame(loop);
    }

    resize();
    var ro = new ResizeObserver(resize); ro.observe(parent);

    var io = null;
    if (!staticOnly && global.IntersectionObserver) {
      io = new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        if (visible && !raf) { last = 0; raf = global.requestAnimationFrame(loop); }
      });
      io.observe(canvas);
    }

    // Cursor parallax (wireframe / orb; skipped when static or opted out).
    if ((mode === "wireframe" || mode === "orb") && opts.parallax !== false && !staticOnly) {
      onMove = function (ev) {
        var box = parent.getBoundingClientRect();
        pointer.x = (ev.clientX - box.left) / Math.max(box.width, 1);
        pointer.y = (ev.clientY - box.top) / Math.max(box.height, 1);
      };
      global.addEventListener("pointermove", onMove, { passive: true });
    }

    if (staticOnly) { t = 1.2; impl.draw(t); }
    else raf = global.requestAnimationFrame(loop);

    return {
      stop: function () {
        global.cancelAnimationFrame(raf);
        ro.disconnect(); if (io) io.disconnect();
        if (onMove) global.removeEventListener("pointermove", onMove);
      },
    };
  }

  global.phosphorAmbient = phosphorAmbient;
})(typeof window !== "undefined" ? window : this);
