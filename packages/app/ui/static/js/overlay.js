// The timeline overlay (harness_app/overlay.py): one run's lanes from the core (GET /api/lanes),
// the last `seconds` of them, followed while they are written; without a run, the newest
// session of the host that runs, and the next one that starts.
import { get } from './api.js'
import { esc } from './i18n.js'

const q = new URLSearchParams(location.search)
const seconds = parseFloat(q.get('seconds') || '60')
document.body.style.setProperty('--alpha', q.get('alpha') || '0.72')

async function run() {
    if (q.get('run')) return q.get('run')
    const s = await get('/api/sessions')
    const rows = (s && s.sessions) || []
    const live = rows.find((r) => r.live) || rows[0]
    return live ? live.id : null
}

async function draw() {
    const name = await run()
    const host = document.querySelector('.tl')
    document.querySelector('.run').textContent = name || ''
    if (!name) { host.innerHTML = '<div class="tl-empty">no session runs</div>'; return }
    const snap = await get('/api/lanes', { run: name })
    if (!snap) return
    const t1 = snap.ended ? (snap.last || Date.now() / 1000) : Date.now() / 1000, t0 = t1 - seconds
    document.querySelector('.st').textContent = snap.ended ? 'ended' : 'running'
    const x = (t) => Math.max(0, Math.min(100, ((t - t0) / seconds) * 100))
    host.innerHTML = (snap.lanes || []).map((l) => `<div class="tl-row"><span>${'  '.repeat(l.depth || 0)}${esc(l.label || l.kind)}</span><div class="tl-track">`
        + (l.spans || []).filter((s) => (s.end || t1) >= t0).map((s) => { const a = x(s.start), b = x(s.end || t1); return `<i class="tl-bar ${l.kind === 'model' ? 'model' : s.status === 'error' ? 'failed' : s.end ? 'task' : 'open'}" style="left:${a}%;width:${Math.max(0.4, b - a)}%"></i>` }).join('')
        + '</div></div>').join('')
}

draw(); setInterval(draw, 1000)
