/* LMMs-Lab logo: cyberpunk and 3D treatments of the lockup itself (no LWM story).
   Depends on lmms-pixelfont.js (window.LMMSFont).

   c  Voxel      Solid pixel blocks: cyan face, cyan-lit top and left walls, magenta-lit right
                 walls, navy underside, ink edges. The X is a magenta neon bar set behind the
                 letters. Load: the flat logo extrudes column by column and the X lights.
                 Hover: the depth swings with the pointer and the X shifts against the letters.
   d  Neon sign  Channel letters: dark faces and walls, a cyan neon tube on every outline edge,
                 a magenta tube X. Load: the tubes light with two flashes, the X with one.
                 Hover: one 0.21 s glitch (at most once a second), then a brighter tube
                 with a cyan/magenta fringe.
   e  Echo       Four echo layers step from cyan through blue to magenta behind the letters,
                 and the X gets its own four layers in darkening magenta. Load: the layers
                 slide out once. No hover motion and no repeat: after the load it stays still.

   Two palettes. neon, the default, is the cyberpunk pass: electric cyan letters lit from
   above in five row bands, a hot pink X, indigo ink and darks, violet in the echoes.
   shipped keeps the site's cyan, raspberry and warm ink.

   Every treatment rests still: one frame is drawn at rest and the frame loop runs only while
   something moves. Front faces sit on whole device pixels. The whole logo flashes at most 3
   times in its intro; reduced: true turns off the intro, the glitch and the pointer motion.

   Usage:
     const ctl = LMMSCyber.attach(canvas, { variant: 'c', size: 'header', mode: 'live' });
     ctl.pointer(nx, ny);            // -1..1 across the logo box
     ctl.hover(true); ctl.hover(false); ctl.replay();
     ctl.set({ autoplay: false, scrub: 0.4, speed: 0.25 }); ctl.destroy();
   size : 'header' (cell 3.54 CSS px, the shipped size) | 'stage' (cell 14 CSS px)
   palette : 'neon' | 'shipped'
   mode : 'live' (load, hover, tap) | 'demo' (scripted load and pointer sweep, repeating; E: load once);
   in demo mode autoplay false holds the frame at scrub (0..1).
   LMMSCyber.front and LMMSCyber.mark paint the flat letters and X for other engines. */
(function (global) {
  'use strict';

  // Depth and light tones are mixed in oklch from each palette's cyan, its X colour and the
  // header teal #03639A. bands: the letter face row by row, top to bottom; null draws it flat.
  var PALETTES = {
    neon: {
      cy: '#18F0FF', mg: '#FF2C96', ink: '#0E0928',
      bands: ['#C9FDFF', '#8EF9FF', '#18F0FF', '#13DBF9', '#13C7F4'],
      cTop: '#B9FDFF', cLeft: '#0EB1CD', cRight: '#6D0B47', cBottom: '#1D183E',
      dFace: '#16142E', dSide: '#0A081B', dDim: '#4A5B77', dCore: '#E7FEFF',
      mgCore: '#FEDEE9', mgDim: '#6C314A', scan: 'rgba(10,8,27,0.24)',
      echo: ['#60CBFF', '#7DA5FE', '#AB6FFE', '#D52FC7'],
      markEcho: ['#CB1982', '#9D1172', '#750E63', '#530E53'],
    },
    shipped: {
      cy: '#38F0E7', mg: '#FB315E', ink: '#120F0B', bands: null,
      cTop: '#AAF8F2', cLeft: '#23BEB7', cRight: '#6A0921', cBottom: '#042136',
      dFace: '#0A1F2F', dSide: '#02111D', dDim: '#4C6A67', dCore: '#DCFDFA',
      mgCore: '#FED1D3', mgDim: '#6E3C40', scan: 'rgba(2,17,29,0.22)',
      echo: ['#6FC9FD', '#9C9CFC', '#D65AD2', '#EA1551'],
      markEcho: ['#CB234A', '#A21037', '#7F0327', '#5E051C'],
    },
  };
  var F = null;

  function font() { return F || (F = global.LMMSFont); }
  function palette(name) { return PALETTES[name] || PALETTES.neon; }
  function face(g) { return g.pal.bands || g.pal.cy; }
  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function smooth(t) { t = clamp01(t); return t * t * (3 - 2 * t); }
  function rgb(hex) { return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]; }
  function mixHex(a, b, t) {
    var p = rgb(a), q = rgb(b);
    return 'rgb(' + Math.round(lerp(p[0], q[0], t)) + ',' + Math.round(lerp(p[1], q[1], t)) + ',' + Math.round(lerp(p[2], q[2], t)) + ')';
  }
  function alpha(hex, a) { var p = rgb(hex); return 'rgba(' + p[0] + ',' + p[1] + ',' + p[2] + ',' + a + ')'; }

  /* ---- geometry: cells, device px ------------------------------------ */

  var HEADER_CELL_CSS = 46 * 30 / 390, STAGE_CELL_CSS = 14;
  var COLS = 44, ROWS = 19, OX = 3;               // canvas size in cells; the logo starts at column OX
  var CENTER = [17.5, 2.5], FOCAL = 74;           // logo centre and focal length, in cells
  var MARK = { cx: 28.6, cy: 2.96, w: 17.35 };    // the X on 'Lab', as in the lockup
  var MARK_Z = { c: 2.5, d: 1.2 };                // how far the X sits behind the letters
  var REST = { intro: 1, nx: -1, ny: 0, hov: 0, glitch: -1 };

  function geometry(size, dpr) {
    var cell = Math.max(2, Math.round((size === 'stage' ? STAGE_CELL_CSS : HEADER_CELL_CSS) * dpr));
    return {
      cell: cell, ow: Math.max(1, Math.round(cell * 0.075)),
      W: COLS * cell, H: ROWS * cell, ox: OX * cell, oy: (ROWS - 5) / 2 * cell,
    };
  }
  function X(g, x) { return g.ox + x * g.cell; }
  function Y(g, y) { return g.oy + y * g.cell; }

  // Off-axis perspective: the front plane (z = 0) is drawn exactly as the flat logo, and
  // depth recedes toward a vanishing point. At rest it sits low and far right, so the
  // walls fall to the bottom right; the pointer swings it left and right.
  function vanish(st) { return [CENTER[0] - 70 * st.nx, CENTER[1] + 40 - 12 * st.ny]; }
  function persp(z) { return FOCAL / (FOCAL + z); }

  /* ---- model ---------------------------------------------------------- */

  var model = null;
  function getModel() {
    if (model) return model;
    var cells = font().layout('LMMs-Lab').cells, filled = {}, faces = [], i, c;
    for (i = 0; i < cells.length; i++) filled[cells[i].c + ',' + cells[i].r] = true;
    function open(cc, rr) { return !filled[cc + ',' + rr]; }
    // Each exposed side of a cell is one outline edge [x0, y0, x1, y1] and one wall.
    for (i = 0; i < cells.length; i++) {
      c = cells[i];
      if (open(c.c + 1, c.r)) faces.push({ c: c.c, side: 'R', e: [c.c + 1, c.r, c.c + 1, c.r + 1] });
      if (open(c.c - 1, c.r)) faces.push({ c: c.c, side: 'L', e: [c.c, c.r + 1, c.c, c.r] });
      if (open(c.c, c.r + 1)) faces.push({ c: c.c, side: 'B', e: [c.c + 1, c.r + 1, c.c, c.r + 1] });
      if (open(c.c, c.r - 1)) faces.push({ c: c.c, side: 'T', e: [c.c, c.r, c.c + 1, c.r] });
    }
    model = { cells: cells, faces: faces };
    return model;
  }

  // The X model is placed so that at the rest vanishing point it projects exactly onto
  // the lockup; when the vanishing point moves, the X shifts against the letters.
  function markAt(z) {
    var v0 = vanish(REST), s0 = persp(z);
    return { cx: v0[0] + (MARK.cx - v0[0]) / s0, cy: v0[1] + (MARK.cy - v0[1]) / s0, w: MARK.w / s0, z: z };
  }

  /* ---- drawing -------------------------------------------------------- */

  // fill: one colour, or one per cell row (the neon bands).
  function drawFront(ctx, g, fill, dx, dy) {
    var cells = getModel().cells, cs = g.cell, ow = g.ow, flat = typeof fill === 'string', i, c;
    ctx.fillStyle = g.pal.ink;
    for (i = 0; i < cells.length; i++) { c = cells[i]; ctx.fillRect(X(g, c.c) + dx - ow, Y(g, c.r) + dy - ow, cs + 2 * ow, cs + 2 * ow); }
    if (flat) ctx.fillStyle = fill;
    for (i = 0; i < cells.length; i++) {
      c = cells[i];
      if (!flat) ctx.fillStyle = fill[c.r];
      ctx.fillRect(X(g, c.c) + dx, Y(g, c.r) + dy, cs, cs);
    }
  }

  // Walls of the extruded letters: only the ones facing the vanishing point, far ones first.
  function drawWalls(ctx, g, vp, depthAt, colors) {
    var faces = getModel().faces, list = [], i, f, e, d, s, mx, my;
    for (i = 0; i < faces.length; i++) {
      f = faces[i]; e = f.e;
      if (f.side === 'R' ? vp[0] <= e[0] : f.side === 'L' ? vp[0] >= e[0] : f.side === 'B' ? vp[1] <= e[1] : vp[1] >= e[1]) continue;
      d = depthAt(f.c);
      if (d <= 0.001) continue;
      mx = (e[0] + e[2]) / 2 - vp[0]; my = (e[1] + e[3]) / 2 - vp[1];
      list.push({ f: f, d: d, k: mx * mx + my * my });
    }
    list.sort(function (p, q) { return q.k - p.k; });
    ctx.lineWidth = g.ow; ctx.strokeStyle = g.pal.ink; ctx.lineJoin = 'miter';
    for (i = 0; i < list.length; i++) {
      e = list[i].f.e; s = persp(list[i].d);
      ctx.beginPath();
      ctx.moveTo(X(g, e[0]), Y(g, e[1]));
      ctx.lineTo(X(g, e[2]), Y(g, e[3]));
      ctx.lineTo(X(g, vp[0] + (e[2] - vp[0]) * s), Y(g, vp[1] + (e[3] - vp[1]) * s));
      ctx.lineTo(X(g, vp[0] + (e[0] - vp[0]) * s), Y(g, vp[1] + (e[1] - vp[1]) * s));
      ctx.closePath();
      ctx.fillStyle = colors[list[i].f.side];
      ctx.fill();
      ctx.stroke();
    }
  }

  // The X; with m (from markAt) and a vanishing point it is drawn in depth, without them flat.
  function drawMark(ctx, g, vp, m, color, glow, core) {
    var Fn = font(), s = m ? persp(m.z) : 1;
    var w = (m ? m.w : MARK.w) * s, h = w * Fn.MARK_AR;
    var cx = m ? vp[0] + (m.cx - vp[0]) * s : MARK.cx, cy = m ? vp[1] + (m.cy - vp[1]) * s : MARK.cy;
    var lw = w * 0.062 * g.cell;
    function strokes(width) {
      ctx.lineWidth = width;
      for (var i = 0; i < Fn.MARK.length; i++) {
        var p = Fn.MARK[i];
        ctx.beginPath();
        ctx.moveTo(X(g, cx - w / 2 + p[0][0] * w), Y(g, cy - h / 2 + p[0][1] * h));
        ctx.lineTo(X(g, cx - w / 2 + p[1][0] * w), Y(g, cy - h / 2 + p[1][1] * h));
        ctx.stroke();
      }
    }
    ctx.save();
    ctx.lineCap = 'butt';
    ctx.strokeStyle = color;
    if (glow > 0) { ctx.shadowColor = alpha(g.pal.mg, 0.9); ctx.shadowBlur = glow * g.cell; }
    strokes(lw);
    ctx.shadowBlur = 0; ctx.shadowColor = 'transparent';
    if (core) { ctx.strokeStyle = core; strokes(Math.max(1, lw * 0.3)); }
    ctx.restore();
  }

  // The flat X moved by (dx, dy) device px, with an ink edge like the letters. All three
  // ink strokes go down before the colour, so the crossings stay clean.
  function drawMarkLayer(ctx, g, color, dx, dy) {
    var Fn = font(), w = MARK.w, h = w * Fn.MARK_AR, lw = w * 0.062 * g.cell, ow = g.ow;
    var pass, i, p, x0, y0, x1, y1, len, ux, uy;
    ctx.save();
    ctx.lineCap = 'butt';
    for (pass = 0; pass < 2; pass++) {
      ctx.strokeStyle = pass ? color : g.pal.ink;
      ctx.lineWidth = pass ? lw : lw + 2 * ow;
      for (i = 0; i < Fn.MARK.length; i++) {
        p = Fn.MARK[i];
        x0 = X(g, MARK.cx - w / 2 + p[0][0] * w) + dx; y0 = Y(g, MARK.cy - h / 2 + p[0][1] * h) + dy;
        x1 = X(g, MARK.cx - w / 2 + p[1][0] * w) + dx; y1 = Y(g, MARK.cy - h / 2 + p[1][1] * h) + dy;
        // the ink pass runs one outline width past both ends so the ends are edged too
        len = Math.sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0)) || 1;
        ux = pass ? 0 : (x1 - x0) / len * ow; uy = pass ? 0 : (y1 - y0) / len * ow;
        ctx.beginPath();
        ctx.moveTo(x0 - ux, y0 - uy);
        ctx.lineTo(x1 + ux, y1 + uy);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  // Brightness of a neon part while it lights: off, n short flashes (1 or 2), then a ramp.
  function ignite(t, a, b, n) {
    var u = (t - a) / (b - a), Fn = font();
    if (u <= 0) return 0;
    if (u >= 1) return 1;
    if (u < 0.12) return 1;
    if (n > 1) {
      if (u < 0.28) return 0.15;
      if (u < 0.36) return 1;
      if (u < 0.5) return 0.35;
      return 0.35 + 0.65 * Fn.easeOut((u - 0.5) / 0.5);
    }
    if (u < 0.3) return 0.25;
    return 0.25 + 0.75 * Fn.easeOut((u - 0.3) / 0.7);
  }

  function outlinePath(ctx, g) {
    var faces = getModel().faces, i, e;
    ctx.beginPath();
    for (i = 0; i < faces.length; i++) { e = faces[i].e; ctx.moveTo(X(g, e[0]), Y(g, e[1])); ctx.lineTo(X(g, e[2]), Y(g, e[3])); }
  }

  // Neon tubes on every outline edge. Widths are even so the tube sits on whole pixels;
  // the white core only appears once a cell is 9 device px or more.
  function drawTubes(ctx, g, b) {
    var T = g.layers[1], tc = T.getContext('2d'), cs = g.cell, P = g.pal;
    var tw = 2 * Math.max(1, Math.round(cs * 0.15)), core = 2 * Math.round(cs * 0.06);
    tc.clearRect(0, 0, g.W, g.H);
    tc.lineCap = 'square';
    tc.lineWidth = tw + 2 * g.ow; tc.strokeStyle = P.ink;
    outlinePath(tc, g); tc.stroke();
    tc.lineWidth = tw; tc.strokeStyle = b > 0.02 ? mixHex(P.dDim, P.cy, Math.min(1, b)) : P.dDim;
    outlinePath(tc, g); tc.stroke();
    ctx.save();
    if (b > 0.02) {
      ctx.shadowColor = alpha(P.cy, Math.min(1, 0.85 * b));
      ctx.shadowBlur = 0.5 * cs; ctx.drawImage(T, 0, 0);
      ctx.shadowBlur = 1.6 * cs * Math.min(1.25, b); ctx.drawImage(T, 0, 0);
      ctx.shadowBlur = 0; ctx.shadowColor = 'transparent';
    }
    ctx.drawImage(T, 0, 0);
    if (b > 0.5 && core > 0) {
      ctx.globalAlpha = Math.min(1, b);
      ctx.lineCap = 'square'; ctx.lineWidth = core; ctx.strokeStyle = P.dCore;
      outlinePath(ctx, g); ctx.stroke();
    }
    ctx.restore();
  }

  // Faint scan lines over what is drawn; only at stage size, they turn to noise in the header.
  function scanlines(ctx, g) {
    var gap = Math.max(3, Math.round(g.cell * 0.22)), y;
    ctx.save();
    ctx.globalCompositeOperation = 'source-atop';
    ctx.fillStyle = g.pal.scan;
    for (y = 0; y < g.H; y += gap) ctx.fillRect(0, y, g.W, 1);
    ctx.restore();
  }

  function tint(g, idx, color) {
    var T = g.layers[idx], tc = T.getContext('2d');
    tc.globalCompositeOperation = 'source-over';
    tc.clearRect(0, 0, g.W, g.H);
    tc.drawImage(g.layers[0], 0, 0);
    tc.globalCompositeOperation = 'source-in';
    tc.fillStyle = color;
    tc.fillRect(0, 0, g.W, g.H);
    tc.globalCompositeOperation = 'source-over';
    return T;
  }

  // Glitch frames: [top, bottom] as a fraction of the canvas height, shift in cells.
  var GLITCH = [
    [[0.36, 0.45, -1.4], [0.55, 0.6, 0.9]],
    [[0.38, 0.47, 0.8], [0.5, 0.58, -1.6], [0.6, 0.66, 0.5]],
    [[0.44, 0.52, -0.7]],
  ];

  function composite(ctx, g, st) {
    var L = g.layers[0], cs = g.cell, burst = st.glitch >= 0 && st.glitch < 1, i, b, y0, y1;
    var split = burst ? Math.max(1, Math.round(cs * 0.25)) : Math.round(st.hov * Math.max(1, Math.round(cs * 0.1)));
    ctx.clearRect(0, 0, g.W, g.H);
    if (split > 0) {
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = burst ? 0.7 : 0.5;
      ctx.drawImage(tint(g, 2, g.pal.cy), -split, 0);
      ctx.drawImage(tint(g, 3, g.pal.mg), split, 0);
      ctx.restore();
    }
    ctx.drawImage(L, 0, 0);
    if (!burst) return;
    b = GLITCH[Math.min(2, Math.floor(st.glitch * 3))];
    for (i = 0; i < b.length; i++) {
      y0 = Math.round(b[i][0] * g.H); y1 = Math.round(b[i][1] * g.H);
      ctx.clearRect(0, y0, g.W, y1 - y0);
      ctx.drawImage(L, 0, y0, g.W, y1 - y0, Math.round(b[i][2] * cs), y0, g.W, y1 - y0);
    }
  }

  /* ---- scenes: st = { intro 0..1 (1 = rest), nx, ny, hov 0..1, glitch -1 | 0..1 } ---- */

  function sceneC(ctx, g, st) {
    var Fn = font(), P = g.pal, vp = vanish(st), lit = ignite(st.intro, 0.45, 0.95, 2);
    var depthAt = function (c) { return 0.9 * Fn.easeOut(clamp01((st.intro - c / 35 * 0.35) / 0.65)); };
    ctx.clearRect(0, 0, g.W, g.H);
    drawMark(ctx, g, vp, g.markC, lit > 0 ? mixHex(P.mgDim, P.mg, lit) : P.mgDim, 1.1 * lit, lit > 0.9 ? P.mgCore : null);
    drawWalls(ctx, g, vp, depthAt, { R: P.cRight, L: P.cLeft, B: P.cBottom, T: P.cTop });
    drawFront(ctx, g, face(g), 0, 0);
  }

  function sceneD(ctx, g, st) {
    var P = g.pal, vp = vanish(st), tube = ignite(st.intro, 0.08, 0.7, 2) * (1 + 0.18 * st.hov), lit = ignite(st.intro, 0.6, 1, 1);
    var lc = g.layers[0].getContext('2d');
    lc.clearRect(0, 0, g.W, g.H);
    drawMark(lc, g, vp, g.markD, lit > 0 ? mixHex(P.mgDim, P.mg, lit) : P.mgDim, 1.3 * lit, lit > 0.9 ? P.mgCore : null);
    drawWalls(lc, g, vp, function () { return 0.35; }, { R: P.dSide, L: P.dSide, B: P.dSide, T: P.dSide });
    drawFront(lc, g, P.dFace, 0, 0);
    drawTubes(lc, g, tube);
    if (g.cell >= 10) scanlines(lc, g);
    composite(ctx, g, st);
  }

  // E takes no pointer input: the echo always falls to the bottom right.
  function sceneE(ctx, g, st) {
    var Fn = font(), step = 0.42 * g.cell, sx = [], sy = [], i, k;
    // Whole-pixel steps keep every layer sharp, at rest and while it slides out.
    for (i = 1; i <= 4; i++) {
      k = Fn.easeOut(clamp01((st.intro - (i - 1) * 0.06) / 0.82));
      sx[i] = i * Math.round(0.8 * step * k);
      sy[i] = i * Math.round(0.6 * step * k);
    }
    ctx.clearRect(0, 0, g.W, g.H);
    // The X sits behind the letters, so all of its layers go down first.
    for (i = 4; i >= 1; i--) drawMarkLayer(ctx, g, g.pal.markEcho[i - 1], sx[i], sy[i]);
    drawMarkLayer(ctx, g, g.pal.mg, 0, 0);
    for (i = 4; i >= 1; i--) drawFront(ctx, g, g.pal.echo[i - 1], sx[i], sy[i]);
    drawFront(ctx, g, face(g), 0, 0);
  }

  var SCENES = { c: sceneC, d: sceneD, e: sceneE };

  /* ---- driver --------------------------------------------------------- */

  var INTRO = { c: 700, d: 1000, e: 640 };
  var GLITCH_MS = 210, BOOT_MS = 400, OMEGA = 18;
  var DEMO = { lead: 600, gap: 800, sweep: 2600, leave: 700, rest: 900 };

  function demoCycle(v) { return DEMO.lead + INTRO[v] + DEMO.gap + DEMO.sweep + DEMO.leave + DEMO.rest; }

  // Scripted state for the repeating stage: load, a pause, a pointer sweep, leave, rest.
  function demoState(v, tau) {
    var st = { intro: 1, nx: -1, ny: 0, hov: 0, glitch: -1 }, t = tau - DEMO.lead, u, w;
    if (t < 0) { st.intro = 0; return st; }
    if (t < INTRO[v]) { st.intro = t / INTRO[v]; return st; }
    t -= INTRO[v] + DEMO.gap;
    if (t < 0) return st;
    if (t < DEMO.sweep) {
      u = t / DEMO.sweep;
      st.hov = smooth(t / 260);
      st.nx = lerp(-1, -Math.cos(1.5 * Math.PI * u), st.hov);
      st.ny = 0.5 * Math.sin(2 * Math.PI * u) * st.hov;
      if (v === 'd' && t < GLITCH_MS) st.glitch = t / GLITCH_MS;
      return st;
    }
    t -= DEMO.sweep;
    if (t < DEMO.leave) {
      w = smooth(t / DEMO.leave);
      st.hov = 1 - w; st.nx = lerp(0, -1, w);
    }
    return st;
  }

  function spring(s, to, dt) {
    var n = Math.max(1, Math.ceil(dt / 8)), h = dt / n / 1000, i, a;
    for (i = 0; i < n; i++) { a = OMEGA * OMEGA * (to - s.x) - 2 * OMEGA * s.v; s.v += a * h; s.x += s.v * h; }
    if (Math.abs(to - s.x) < 1e-3 && Math.abs(s.v) < 1e-3) { s.x = to; s.v = 0; return false; }
    return true;
  }

  function attach(canvas, opts) {
    var o = { variant: 'c', size: 'header', mode: 'live', palette: 'neon', autoplay: true, speed: 1, scrub: 0, reduced: false };
    for (var key in opts) if (Object.prototype.hasOwnProperty.call(opts, key) && opts[key] !== undefined) o[key] = opts[key];
    var ctx = canvas.getContext('2d'), g = null;
    var raf = 0, dead = false, bootT = 0, last = 0, t0 = performance.now();
    var introStart = null, introHold = false, glitchStart = null;
    var hovering = false, target = [-1, 0], lastGlitch = -1e9;
    var sx = { x: -1, v: 0 }, sy = { x: 0, v: 0 }, sh = { x: 0, v: 0 };

    function still() { return o.mode === 'demo' && !o.autoplay; }

    function layout() {
      var dpr = global.devicePixelRatio || 1, i, c;
      g = geometry(o.size, dpr);
      g.pal = palette(o.palette);
      g.markC = markAt(MARK_Z.c);
      g.markD = markAt(MARK_Z.d);
      if (canvas.width !== g.W || canvas.height !== g.H) { canvas.width = g.W; canvas.height = g.H; }
      canvas.style.width = g.W / dpr + 'px';
      canvas.style.height = g.H / dpr + 'px';
      if (o.size === 'header') {
        // the logo's front face lands on the 44 px logo box, snapped to a device pixel
        canvas.style.left = -g.ox / dpr + 'px';
        canvas.style.top = Math.round((44 - g.H / dpr) / 2 * dpr) / dpr + 'px';
      }
      g.layers = [];
      if (o.variant === 'd') for (i = 0; i < 4; i++) { c = global.document.createElement('canvas'); c.width = g.W; c.height = g.H; g.layers.push(c); }
    }

    function liveState(now) {
      var st = { intro: 1, nx: sx.x, ny: sy.x, hov: sh.x, glitch: -1 }, p;
      if (introHold) st.intro = 0;
      else if (introStart !== null) {
        p = (now - introStart) * o.speed / INTRO[o.variant];
        if (p >= 1) introStart = null; else st.intro = p;
      }
      if (glitchStart !== null) {
        p = (now - glitchStart) * o.speed / GLITCH_MS;
        if (p >= 1) glitchStart = null; else st.glitch = p;
      }
      return st;
    }

    function frame(now) {
      raf = 0;
      if (dead) return;
      var dt = last ? Math.min(64, now - last) * o.speed : 16, st, more;
      last = now;
      if (o.mode === 'demo' && o.variant === 'e') {
        // E plays its load once and then stays still: no repeat, no pointer sweep.
        var once = DEMO.lead + INTRO.e, tau = still() ? o.scrub * once : Math.min(once, (now - t0) * o.speed);
        st = demoState('e', tau);
        more = !still() && tau < once;
      } else if (o.mode === 'demo') {
        var cyc = demoCycle(o.variant);
        st = demoState(o.variant, still() ? o.scrub * cyc : ((now - t0) * o.speed) % cyc);
        more = !still();
      } else {
        var mx = false, my = false, mh = false;
        if (!o.reduced) {
          mx = spring(sx, hovering ? target[0] : -1, dt);
          my = spring(sy, hovering ? target[1] : 0, dt);
          mh = spring(sh, hovering ? 1 : 0, dt);
        }
        st = liveState(now);
        more = mx || my || mh || introStart !== null || glitchStart !== null;
      }
      SCENES[o.variant](ctx, g, st);
      if (more) raf = requestAnimationFrame(frame);
      else last = 0;
    }

    function kick() { if (!raf && !dead) raf = requestAnimationFrame(frame); }

    function startIntro() {
      introHold = false;
      introStart = performance.now();
      kick();
    }

    var ctl = {
      canvas: canvas,
      pointer: function (nx, ny) {
        target = [Math.max(-1, Math.min(1, nx)), Math.max(-1, Math.min(1, ny))];
        if (hovering) kick();
      },
      hover: function (on) {
        if (o.mode !== 'live' || o.variant === 'e' || hovering === on) return;
        hovering = on;
        if (o.reduced) return;
        if (on && o.variant === 'd' && performance.now() - lastGlitch > 1000) glitchStart = lastGlitch = performance.now();
        kick();
      },
      replay: function () {
        if (o.mode !== 'live' || o.reduced) return;
        clearTimeout(bootT);
        startIntro();
      },
      set: function (next) {
        var prev = o, changed = false, k;
        o = {};
        for (k in prev) o[k] = prev[k];
        for (k in next) if (Object.prototype.hasOwnProperty.call(next, k) && next[k] !== undefined) o[k] = next[k];
        for (k in o) if (o[k] !== prev[k]) changed = true;
        if (!changed) return;
        if (o.variant !== prev.variant || o.size !== prev.size) layout();
        else if (o.palette !== prev.palette) g.pal = palette(o.palette);
        if (o.mode !== prev.mode || o.autoplay !== prev.autoplay || o.speed !== prev.speed) t0 = performance.now();
        if (o.mode === 'live' && o.autoplay && !prev.autoplay && !o.reduced) startIntro();
        kick();
      },
      destroy: function () {
        dead = true;
        cancelAnimationFrame(raf);
        raf = 0;
        clearTimeout(bootT);
      },
    };

    layout();
    if (o.mode === 'live' && o.autoplay && !o.reduced) {
      introHold = true;
      bootT = setTimeout(function () { if (!dead) startIntro(); }, BOOT_MS);
    }
    kick();
    return ctl;
  }

  global.LMMSCyber = {
    attach: attach, INTRO: INTRO, GLITCH_MS: GLITCH_MS, demoCycle: demoCycle,
    PALETTES: PALETTES, MARK: MARK, front: drawFront, mark: drawMarkLayer,
  };
})(window);
