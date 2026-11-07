/**
 * The layer stack as a Hairline figure, drawn on the package's own engine (its ten rules:
 * one stroke, rounded solids, the bright stroke as the only highlight, no words inside).
 *
 * Four rounded plates, a little apart. The bottom one is a rimmed tray (the shield); above
 * it a thin plate carries a dashed dial with twelve dots (the reactive layer, every step);
 * above that a plate holds two low tiles with engraved lines (programs) and two taller
 * pillars with a dot mark (learned policies); the top plate is engraved with three lines
 * (the model) and floats clear at rest, since it is asked least often. The plate under the
 * pointer opens: the plates above it rise, it rises less, and its silhouette takes the
 * bright stroke. At rest one program tile is bright; a figure that holds a layer returns
 * to that layer instead.
 */
import { HL } from "./hairline-kernel.js";

const {
  Cam, clamp, facing, fit, prism, proj, rings, rrect, ringAt, poly, seg,
  tween, tset, tval, tdone, flatDot, mk, place, pointer, put, register, disposer, solid, inject,
} = HL;

const F = 120, T = 4, TRAY = 9;
const BASE = [0, 32, 64, 104];
const REST = [0, 0, 0, 34];
const TOP = [TRAY, BASE[1] + T, BASE[2] + T, BASE[3] + T];
export const LAYERS = ["shield", "reactive", "programs", "model"];
// program tiles (low, engraved) and policy pillars (tall, dotted), on the programs plate
const TILES = [[14, 16, 50, 46, 7], [16, 64, 52, 98, 7]];
const PILLARS = [[70, 16, 98, 42, 21], [74, 68, 102, 96, 21]];
const LABEL = "Four stacked plates: the model, programs and learned policies, the reactive layer and the shield.";

/**
 * Draws the stack into `el`. `hold` (0 shield … 3 model) keeps that layer open when the
 * pointer is away; `lift` is how far the plates above an open layer rise, in world units.
 */
export function harness(el, { hold = -1, lift = hold >= 0 ? 26 : 20, label = LABEL } = {}) {
  inject(el.ownerDocument);
  el.setAttribute("data-hairline", "harness");
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", label);
  const svg = mk("svg", { viewBox: "0 0 400 320", "aria-hidden": "true" }, el);
  const live = el.ownerDocument.createElement("span");
  live.setAttribute("data-hairline-live", "");
  live.setAttribute("aria-live", "polite");
  el.append(live);

  const bag = disposer();
  const C = Cam(45, 0.5, 1.12);
  fit(C, [[-6, -6, 0], [F + 6, F + 6, 0], [F + 6, -6, 0], [-6, F + 6, 0],
    [0, 0, TOP[3] + REST[3] + 32 + 4], [F, F, TOP[3] + REST[3] + 32]], 200, 162);
  const P = proj(C), front = facing(C);
  const g = mk("g", {}, svg);

  // the shield: a rimmed tray that never moves
  const [tr, ti] = rings(-6, -6, F + 6, F + 6, 11, 2.2);
  const shield = solid(g);
  put(shield, prism(P, front, tr, ti, 0, TRAY));
  mk("path", { d: poly(ringAt(P, rrect(0, 0, F, F, 7, 6), TRAY)), class: "nf lo" }, g);

  const [pr, pi] = rings(0, 0, F, F, 9, 1.6);
  const layers = [];
  let restTile = null;
  for (let L = 1; L <= 3; L++) {
    const grp = mk("g", {}, g), plate = solid(grp), parts = [];
    if (L === 1) {
      const dial = mk("path", { class: "nf dash" }, grp), dots = [];
      for (let k = 0; k < 12; k++) dots.push(flatDot(grp, C, 1.1, k === 0 ? "dot m" : "dot off"));
      parts.push((z) => {
        const ring = [];
        for (let k = 0; k <= 48; k++) {
          const a = (k / 48) * Math.PI * 2;
          ring.push(P(60 + 38 * Math.cos(a), 60 + 38 * Math.sin(a), z));
        }
        dial.setAttribute("d", poly(ring));
        dots.forEach((dot, k) => {
          const a = (k / 12) * Math.PI * 2 - Math.PI / 2;
          place(dot, P(60 + 38 * Math.cos(a), 60 + 38 * Math.sin(a), z));
        });
      });
    }
    if (L === 2) {
      // back to front, by x + y
      const solids = TILES.map((b) => ({ b, tile: true })).concat(PILLARS.map((b) => ({ b, tile: false })))
        .sort((p, q) => p.b[0] + p.b[1] - (q.b[0] + q.b[1]));
      for (const { b, tile } of solids) {
        const [x0, y0, x1, y1, h] = b, [ring, inner] = rings(x0, y0, x1, y1, tile ? 3 : 6, 1.2);
        const body = solid(grp);
        const marks = tile ? mk("path", { class: "nf lo" }, grp) : null;
        const dots = tile ? [] : [0, 1, 2, 3].map((k) => flatDot(grp, C, 0.9, k === 0 ? "dot" : "dot m"));
        if (tile && x0 === 16) restTile = body.sil;
        parts.push((z) => {
          put(body, prism(P, front, ring, inner, z, z + h));
          if (marks) {
            marks.setAttribute("d", [0.3, 0.55].map((f, k) =>
              seg(P(x0 + 5, y0 + (y1 - y0) * f, z + h), P(x1 - 5 - k * 9, y0 + (y1 - y0) * f, z + h))).join(""));
          }
          dots.forEach((dot, k) => place(dot, P((x0 + x1) / 2 + ((k % 2) - 0.5) * 6,
            (y0 + y1) / 2 + (Math.floor(k / 2) - 0.5) * 6, z + h)));
        });
      }
    }
    if (L === 3) {
      const first = mk("path", { class: "nf" }, grp), rest = mk("path", { class: "nf lo" }, grp);
      parts.push((z) => {
        first.setAttribute("d", seg(P(26, 34, z), P(96, 34, z)));
        rest.setAttribute("d", seg(P(26, 54, z), P(82, 54, z)) + seg(P(26, 74, z), P(90, 74, z)));
      });
    }
    layers.push({ L, plate, parts, tw: tween(REST[L]), drawn: NaN });
  }

  function draw(layer, dz) {
    const z0 = BASE[layer.L] + dz;
    put(layer.plate, prism(P, front, pr, pi, z0, z0 + T));
    layer.parts.forEach((part) => part(z0 + T));
  }

  const loop = register(el, (_dt, now) => {
    let moving = false;
    for (const layer of layers) {
      const v = tval(layer.tw, now);
      if (v !== layer.drawn) { draw(layer, v); layer.drawn = v; }
      if (!tdone(layer.tw, now)) moving = true;
    }
    return moving;
  });
  bag.add(loop.unregister);

  // The layer whose resting middle is nearest the pointer on screen, inside the stack's span;
  // -1 off it. Rest poses only, so a rising plate never moves its own hit area (rule 01).
  const mid = [0, 1, 2, 3].map((L) => P(F / 2, F / 2, TOP[L] + REST[L])[1]);
  const xs = [P(0, F, 0)[0], P(F, 0, 0)[0]];
  function hit([sx, sy]) {
    if (sx < xs[0] || sx > xs[1] || sy < mid[3] - 40 || sy > mid[0] + 40) return -1;
    let best = 0;
    for (let L = 1; L < 4; L++) if (Math.abs(sy - mid[L]) < Math.abs(sy - mid[best])) best = L;
    return best;
  }

  let active = -2;
  function open(a, animate = true) {
    if (a === active) return;
    const now = performance.now(), from = a >= 0 ? a : Math.max(active, 0);
    active = a;
    for (const layer of layers) {
      const dz = REST[layer.L] + (a < 0 ? 0 : layer.L > a ? clamp(lift, 0, 32) : layer.L === a ? clamp(lift * 0.4, 0, 14) : 0);
      if (animate) tset(layer.tw, dz, now, Math.abs(layer.L - from) * 45);
      else layer.tw = tween(dz);
      layer.plate.sil.classList.toggle("hi", layer.L === a);
    }
    restTile.classList.toggle("hi", a < 0);
    shield.sil.classList.toggle("hi", a === 0);
    live.textContent = a < 0 ? "" : LAYERS[a];
    loop.wake();
  }

  open(hold, false);
  bag.add(pointer(el, {
    move: (p) => { const a = hit(p); open(a < 0 ? hold : a); },
    leave: () => open(hold),
  }));
  bag.add(() => { svg.remove(); live.remove(); });
  return { destroy: bag.dispose };
}
