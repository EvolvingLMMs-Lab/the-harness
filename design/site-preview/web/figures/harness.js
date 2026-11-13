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
export function harness(el, { hold = -1, lift = hold >= 0 ? 26 : 20, label = LABEL, activity = false } = {}) {
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
  let clock = 0, active = -2;
  const programParts = [], modelMarks = [];
  let reactiveDots, dotRadii, chaseIndex = 0, chaseElapsed = 0;
  if(activity)el.setAttribute('data-activity','running');
  for (let L = 1; L <= 3; L++) {
    const grp = mk("g", {}, g), plate = solid(grp), parts = [];
    if (L === 1) {
      const dial = mk("path", { class: "nf dash" }, grp), dots = [];
      const dotCount=activity?48:12;
      for (let k = 0; k < dotCount; k++) dots.push(flatDot(grp, C, activity?.72:1.1, k === 0 ? "dot m" : "dot off"));
      if(activity)dial.style.display="none";
      if(activity){reactiveDots=dots;dotRadii=dots.map((dot)=>[Number(dot.getAttribute("rx")),Number(dot.getAttribute("ry"))]);dots.forEach((dot,k)=>dot.setAttribute("data-reactive-dot",String(k)));}
      parts.push((z) => {
        const ring = [];
        for (let k = 0; k <= 48; k++) {
          const a = (k / 48) * Math.PI * 2;
          ring.push(P(60 + 38 * Math.cos(a), 60 + 38 * Math.sin(a), z));
        }
        dial.setAttribute("d", poly(ring));
        dots.forEach((dot, k) => {
          const a = (k / dotCount) * Math.PI * 2 - Math.PI / 2;
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
        if(activity){body.g.setAttribute('data-program-part',String(programParts.length));programParts.push({body,marks,dots});}
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
      const lines = [0,1,2].map((i)=>mk("path",{class:i?'nf lo':'nf'},grp));
      modelMarks.push(...lines);
      parts.push((z) => lines.forEach((line,i)=>line.setAttribute('d',seg(P(26,34+i*20,z),P([96,82,90][i],34+i*20,z)))));
    }
    layers.push({ L, plate, parts, tw: tween(REST[L]), drawn: NaN });
  }

  function draw(layer, dz) {
    const z0 = BASE[layer.L] + dz;
    put(layer.plate, prism(P, front, pr, pi, z0, z0 + T));
    layer.parts.forEach((part) => part(z0 + T));
  }

  const envelope=(time,start,end)=>{
    if(time<start||time>end)return 0;
    const x=Math.min(1,(time-start)/.45,(end-time)/.55);
    return x*x*(3-2*x);
  };
  const glow=(node,level)=>{
    if(!node)return;
    node.style.stroke=`color-mix(in srgb, var(--pink) ${Math.round(level*100)}%, var(--hl-edge))`;
    node.style.strokeWidth=String(1+level*.65);
  };
  function animateActivity(dt){
    const reduced=HL.reducedMotion(),t=reduced?0:clock;
    // The ring itself consists of 48 lamps: no extra unaddressed dash marks.
    // Advance at most one neighbour per rendered frame, including after stalls.
    if(!reduced){
      chaseElapsed+=dt;
      if(chaseElapsed>=.06){chaseIndex=(chaseIndex+1)%reactiveDots.length;chaseElapsed%=.06;}
    }
    const lit=chaseIndex;
    reactiveDots.forEach((dot,k)=>{
      const on=!reduced&&k===lit;
      dot.style.fill=on?'#ff2baf':'var(--hl-lo)';
      dot.style.opacity=on?'1':'.65';
      // The lit dot grows instead of gaining a stroke or a filter: mobile WebKit leaves the
      // old pixels of a filtered SVG element behind as it moves on.
      const grow=on?2:1;
      dot.setAttribute('rx',String(dotRadii[k][0]*grow));
      dot.setAttribute('ry',String(dotRadii[k][1]*grow));
      dot.style.transition='none';
      dot.dataset.lit=String(on);
    });
    // Deliberately independent schedules: bursts, idle gaps and real overlap.
    const cycle=t%22;
    const thinking=reduced?0:Math.max(envelope(cycle,1.1,4.8),envelope(cycle,9.2,12.1),envelope(cycle,16.3,20.0));
    glow(layers[2].plate.sil,Math.max(active===3?.85:0,thinking*.8));
    modelMarks.forEach((line,i)=>{
      const pulse=thinking*(.45+.55*(.5+.5*Math.sin(t*4.4-i*1.4)));
      glow(line,pulse);
      line.style.strokeDasharray=thinking>.01?'14 5':'none';
      line.style.strokeDashoffset=String(-t*16+i*7);
    });
    const schedules=[[[.3,2.4],[6.4,8.0],[11.0,13.7],[18.0,21.0]],[[2.8,5.2],[8.8,10.4],[14.2,15.6],[19.2,21.7]],[[1.8,3.5],[7.1,9.3],[12.8,15.0],[17.1,18.8]],[[4.3,6.0],[10.0,11.9],[15.0,17.4],[20.0,21.8]]];
    let working=0;
    programParts.forEach((part,i)=>{
      const level=reduced?0:Math.max(...schedules[i].map(([a,b])=>envelope(cycle,a,b)));
      if(level>.1)working++;
      glow(part.body.sil,level);glow(part.body.cr,level*.55);glow(part.marks,level);
      part.dots.forEach((dot,k)=>{dot.style.fill=level>.2?'var(--pink)':'var(--hl-edge)';dot.style.opacity=String(level>.2?.6+.4*Math.sin(t*3+k)**2:.6);});
      part.body.g.dataset.working=String(level>.1);
    });
    el.dataset.thinking=String(thinking>.1);el.dataset.working=String(working);el.dataset.activeDot=String(lit);
  }
  const loop = register(el, (dt, now) => {
    if(document.hidden)return false;
    let moving = false;
    if(activity&&!HL.reducedMotion())clock+=dt;
    for (const layer of layers) {
      const v = tval(layer.tw, now);
      if (v !== layer.drawn) { draw(layer, v); layer.drawn = v; }
      if (!tdone(layer.tw, now)) moving = true;
    }
    if(activity)animateActivity(dt);
    return moving || (activity&&!HL.reducedMotion());
  });
  const resume=()=>{if(!document.hidden)loop.wake();};
  document.addEventListener('visibilitychange',resume);
  bag.add(()=>document.removeEventListener('visibilitychange',resume));
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
    restTile.classList.toggle("hi", a < 0 && !activity);
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
