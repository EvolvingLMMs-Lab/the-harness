// The timeline below a chat: when the model, the place's actions, its tasks and their own
// parts (the core's lanes of a task run, GET /api/lanes) were busy, as coloured bars with lane
// names and a time axis; no text on the bars. The chat's own lanes are folded from its record.
import { esc, tt } from './i18n.js'
import { get } from './api.js'

// {lanes: [{label, spans: [{start, end, cls}]}], marks: [{time, cls}], t0, t1}
export function fold(records, now = Date.now() / 1000) {
    const lanes = new Map(), marks = []
    const lane = (key, labelText) => { if (!lanes.has(key)) lanes.set(key, { label: labelText, spans: [] }); return lanes.get(key) }
    let request = null
    const open = []
    for (const r of records) {
        const t = r.time
        if (typeof t !== 'number') continue
        if (r.event === 'model_request') request = t
        else if (r.event === 'model_reply' && request !== null) { lane('model', tt('模型', 'model')).spans.push({ start: request, end: t, cls: 'model' }); request = null }
        else if (r.event === 'action') {
            const place = r.verb === 'task' ? 'task' : String(r.verb || 'action').split('.')[0]
            const span = { start: t, end: null, cls: r.verb === 'task' ? 'task open' : 'open', verb: r.verb }
            lane('a:' + place, r.verb === 'task' ? tt('任务', 'tasks') : place).spans.push(span); open.push(span)
        } else if (r.event === 'outcome') {
            let i = open.length - 1
            while (i >= 0 && (open[i].verb !== r.verb)) i--
            if (i >= 0) { const s = open.splice(i, 1)[0]; s.end = t; s.cls = r.verb === 'task' ? 'task' : (r.end || 'done'); s.run = r.run }
        } else if (r.event === 'user') marks.push({ time: t, cls: 'said' })
        else if (r.event === 'event' || r.event === 'reaction') marks.push({ time: t, cls: 'event' })
    }
    if (request !== null) lane('model', tt('模型', 'model')).spans.push({ start: request, end: null, cls: 'model open' })
    const all = [...lanes.values()].flatMap((l) => l.spans)
    const times = [...all.map((s) => s.start), ...all.map((s) => s.end || now), ...marks.map((m) => m.time)]
    const t1 = times.length ? Math.max(...times) : now
    const t0 = times.length ? Math.max(Math.min(...times), t1 - 3 * 3600) : now - 600
    return { lanes: [...lanes.values()], marks, t0, t1: Math.max(t1, t0 + 60) }
}

// A task run's lanes from the core (core/lanes.py snapshot), as lanes of this timeline.
async function runLanes(run) {
    const snap = await get('/api/lanes', { run })
    if (!snap || !snap.lanes) return []
    return snap.lanes.filter((l) => (l.spans || []).length).slice(0, 6).map((l) => ({
        label: `  ${l.label || l.kind}`, spans: l.spans.map((s) => ({ start: s.start, end: s.end, cls: l.kind === 'model' ? 'model' : s.status === 'error' ? 'failed' : 'task' })),
    }))
}

const generations = new WeakMap()

function nextGeneration(host) {
    const gen = (generations.get(host) || 0) + 1
    generations.set(host, gen)
    return gen
}

export function cancel(host) {
    if (!host) return
    nextGeneration(host)
}

export async function draw(host, records, { isCurrent } = {}) {
    if (!host) return false
    const gen = nextGeneration(host)
    const current = () => generations.get(host) === gen && host.isConnected !== false && (!isCurrent || isCurrent())
    if (!current()) return false
    const data = fold(records)
    const runs = data.lanes.flatMap((l) => l.spans).filter((s) => s.run).slice(-1)
    for (const s of runs) {
        const lanes = await runLanes(s.run)
        if (!current()) return false
        data.lanes.push(...lanes)
    }
    if (!current()) return false
    if (!data.lanes.length && !data.marks.length) { host.innerHTML = `<div class="tl-empty">${tt('这段时间没有事在跑', 'nothing ran in this chat yet')}</div>`; return true }
    const span = data.t1 - data.t0, x = (t) => Math.max(0, Math.min(100, ((t - data.t0) / span) * 100))
    const bar = (s) => { const a = x(s.start), b = x(s.end || data.t1); return `<i class="tl-bar ${s.cls}" style="left:${a}%;width:${Math.max(0.3, b - a)}%"></i>` }
    const clock = (t) => { const d = new Date(t * 1000); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` }
    host.innerHTML = (data.marks.length ? `<div class="tl-row"><span>${tt('消息', 'messages')}</span><div class="tl-track">${data.marks.map((m) => `<i class="tl-mark ${m.cls}" style="left:${x(m.time)}%"></i>`).join('')}</div></div>` : '')
        + data.lanes.map((l) => `<div class="tl-row"><span>${esc(l.label)}</span><div class="tl-track">${l.spans.map(bar).join('')}</div></div>`).join('')
        + `<div class="tl-axis"><span></span><div><span>${clock(data.t0)}</span><span>${clock(data.t0 + span / 2)}</span><span>${clock(data.t1)}</span></div></div>`
    return true
}
