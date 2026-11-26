// The calendar, a Google Calendar week view: what it did and when, who did it (a reaction of
// the tree, on its own, or the owner's entry), how each ended, what the safety layer refused,
// when it was asleep, and what it means to do next. The owner and it both put entries on it.
import { esc, tt, outcome, usd } from './i18n.js'
import { get, post } from './api.js'
import { $, $$, el, dialog, closeDialog } from './ui.js'

// days are added on the calendar, not as 24 hours, so a change of summer time keeps midnights
const plus = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
// pixels an hour: the whole day fits the window when it can, as Google Calendar's week does at its size
let HOUR = 23.4
const SHOW = { owner: true, own: true, learn: true, reflex: true, sleep: true }
let anchor = startOfDay(new Date()), view = 'week', entries = [], card = null

function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
function weekStart(d) { const x = startOfDay(d); const k = (x.getDay() + 6) % 7; x.setDate(x.getDate() - k); return x }
const time = (v) => (typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v))
const hours = (d) => d.getHours() + d.getMinutes() / 60
const days = () => (view === 'day' ? [startOfDay(anchor)] : Array.from({ length: 7 }, (_, i) => plus(weekStart(anchor), i)))
const monthTitle = (d) => tt(`${d.getFullYear()}年${d.getMonth() + 1}月`, d.toLocaleString('en', { month: 'long', year: 'numeric' }))

// what an entry is drawn as
function cls(e) {
    if (e.kind === 'asleep') return 'sleep'
    if (e.who === 'tree') return 'reflex'
    if (e.kind === 'plan' || (e.planned && e.by === 'agent' && time(e.start) > new Date())) return 'plan'
    if (e.who === 'owner' || e.by === 'owner') return 'owner'
    if (e.learning || e.kind === 'learn' || e.kind === 'practice' || e.kind === 'review') return 'learn'
    return 'own'
}
const filter = (c) => SHOW[c === 'plan' ? 'own' : c] !== false

export async function open(app) {
    const host = $('.pc')
    host.innerHTML = `
  <div class="pc-left"><button class="pc-create">＋ ${tt('创建', 'Create')}</button>
    <div class="pc-mini"></div>
    <div class="pc-cals"><b>${tt('我的日历', 'My calendars')}</b>
      ${[['owner', tt('你放的', 'From you')], ['own', tt('它主动做的', 'On its own')], ['learn', tt('学习', 'Learning')], ['reflex', tt('反射树的反应', 'Reflexes')], ['sleep', tt('睡觉', 'Asleep')]]
        .map(([k, n]) => `<label class="${k}${SHOW[k] ? '' : ' offcal'}" data-cal="${k}">${n}</label>`).join('')}</div>
    <div class="pc-budget"><b>${tt('今天的预算', "Today's budget")}</b><div class="ubar"><i></i></div><small></small></div>
  </div>
  <div class="pc-main">
    <div class="pc-head" data-tauri-drag-region="deep"><button class="pc-today">${tt('今天', 'Today')}</button><button class="pg-ic" data-step="-1" aria-label="${tt('上一段', 'Previous')}">‹</button><button class="pg-ic" data-step="1" aria-label="${tt('下一段', 'Next')}">›</button><b></b>
      <span class="pc-views">${[['day', '日', 'Day'], ['week', '周', 'Week'], ['month', '月', 'Month'], ['year', '年', 'Year']].map(([k, z, e]) => `<button data-view="${k}" class="${k === view ? 'on' : ''}">${tt(z, e)}</button>`).join('')}</span></div>
    <div class="pc-body"></div>
  </div>`
    host.querySelector('.pc-create').onclick = () => create(app)
    host.querySelector('.pc-today').onclick = () => { anchor = startOfDay(new Date()); load(app) }
    $$('[data-step]', host).forEach((b) => { b.onclick = () => { step(+b.dataset.step); load(app) } })
    $$('[data-view]', host).forEach((b) => { b.onclick = () => { view = b.dataset.view; $$('[data-view]', host).forEach((x) => x.classList.toggle('on', x === b)); load(app) } })
    $$('[data-cal]', host).forEach((l) => { l.onclick = () => { SHOW[l.dataset.cal] = !SHOW[l.dataset.cal]; l.classList.toggle('offcal', !SHOW[l.dataset.cal]); draw(app) } })
    await load(app)
}

function step(n) {
    const d = new Date(anchor)
    if (view === 'day') d.setDate(d.getDate() + n)
    else if (view === 'week') d.setDate(d.getDate() + 7 * n)
    else if (view === 'month') d.setMonth(d.getMonth() + n)
    else d.setFullYear(d.getFullYear() + n)
    anchor = startOfDay(d)
}

function range() {
    if (view === 'month') { const a = new Date(anchor.getFullYear(), anchor.getMonth(), 1); return [weekStart(a), plus(weekStart(a), 42)] }
    if (view === 'year') return [new Date(anchor.getFullYear(), 0, 1), new Date(anchor.getFullYear() + 1, 0, 1)]
    const d = days(); return [d[0], plus(d[d.length - 1], 1)]
}

export async function load(app) {
    const [from, to] = range()
    const got = await get('/api/agent/calendar', { identity: app.identity.id, from: from.toISOString(), to: to.toISOString() })
    entries = (got && got.entries) || []
    app.calendarMissing = !got
    draw(app)
    budget(app)
}

function mini() {
    const m = new Date(anchor.getFullYear(), anchor.getMonth(), 1), s = weekStart(m), today = startOfDay(new Date()).getTime()
    $('.pc-mini').innerHTML = `<b>${monthTitle(anchor)}</b><div>${tt('一二三四五六日', 'MTWTFSS').split('').map((d) => `<i>${d}</i>`).join('')}`
        + Array.from({ length: 35 }, (_, i) => { const d = plus(s, i); return `<button data-day="${d.getTime()}" class="${d.getTime() === today ? 'on' : ''}${d.getMonth() !== m.getMonth() ? ' out' : ''}">${d.getDate()}</button>` }).join('') + '</div>'
    $$('.pc-mini [data-day]').forEach((b) => { b.onclick = () => { anchor = new Date(+b.dataset.day); load(window.harnessApp) } })
}

function draw(app) {
    if (card) { card.remove(); card = null }
    mini()
    $('.pc-head b').textContent = monthTitle(view === 'week' ? weekStart(anchor) : anchor)
    const body = $('.pc-body')
    if (view === 'month') return month(body)
    if (view === 'year') return year(body)
    const ds = days(), today = startOfDay(new Date()).getTime()
    const names = tt(['周一', '周二', '周三', '周四', '周五', '周六', '周日'], ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    body.style.cssText = `display:flex;flex-direction:column;flex:1;min-height:0;--days:${ds.length}`
    HOUR = Math.max(18, (body.clientHeight - 56) / 24)
    body.innerHTML = `<div class="pc-days"><span></span>${ds.map((d) => `<span class="${d.getTime() === today ? 'on' : ''}">${names[(d.getDay() + 6) % 7]}<b>${d.getDate()}</b></span>`).join('')}</div>
<div class="pc-scroll"><div class="pc-grid" style="--hour:${HOUR}px">${Array.from({ length: 8 }, (_, i) => `<div class="pc-hour" style="top:${i * 3 * HOUR}px;height:${3 * HOUR}px"><span>${String(i * 3).padStart(2, '0')}:00</span></div>`).join('')}
${ds.map((d, i) => `<div class="pc-col${d.getTime() === today ? ' on' : ''}" data-d="${i}" style="grid-column:${i + 2}"></div>`).join('')}<div class="pc-now"></div></div></div>
${app.calendarMissing ? `<div class="pc-note">${tt('这台 host 还没有日历', 'This host has no calendar yet')}</div>` : (!entries.length ? `<div class="pc-note">${tt('这段时间日历上没有事', 'Nothing on the calendar in this stretch')}</div>` : '')}`
    for (const e of entries) {
        const c = cls(e); if (!filter(c)) continue
        const a = time(e.start), b = e.end ? time(e.end) : null
        ds.forEach((d, i) => {
            const end = plus(d, 1)
            if (c === 'reflex') {
                if (a < d || a >= end) return
                const dot = el('div', 'pc-dot', `<i></i><span>${esc(e.title)}</span>`); dot.style.top = hours(a) * HOUR + 'px'; dot._e = e
                $(`.pc-col[data-d="${i}"]`).append(dot); return
            }
            const s = a < d ? d : a, f = !b ? new Date(s.getTime() + 30 * 60000) : b > end ? end : b
            if (f <= d || s >= end) return
            const top = (s - d) / 3600000 * HOUR, h = Math.max(16, (f - s) / 3600000 * HOUR - 2)
            const oc = e.refused ? 'refused' : e.outcome
            const box = el('button', `pc-ev ${c}${e.waiting || e.outcome === 'waiting' ? ' wait' : ''}`, `<b>${esc(e.title)}</b>${oc && oc !== 'waiting' ? `<span class="oc ${esc(oc)}"></span>` : ''}${h > 34 && e.note ? `<small>${esc(e.note)}</small>` : ''}`)
            box.style.top = top + 'px'; box.style.height = h + 'px'; box._e = e
            $(`.pc-col[data-d="${i}"]`).append(box)
        })
    }
    const now = new Date(), k = ds.findIndex((d) => d.getTime() === today)
    const line = $('.pc-now')
    if (k < 0) line.remove()
    else { line.style.top = hours(now) * HOUR + 'px'; line.style.left = `calc(48px + ${k} * (100% - 48px) / ${ds.length})`; line.style.width = `calc((100% - 48px) / ${ds.length})` }
    const scroll = $('.pc-scroll'); scroll.scrollTop = Math.max(0, (hours(now) - 4) * HOUR)
    scroll.onclick = (ev) => { const t = ev.target.closest('.pc-ev, .pc-dot'); if (t && t._e && !t.classList.contains('sleep')) show(app, t, t._e) }
}

function month(body) {
    const m = new Date(anchor.getFullYear(), anchor.getMonth(), 1), s = weekStart(m)
    body.style.cssText = 'display:grid;grid-template-columns:repeat(7,minmax(0,1fr));flex:1;min-height:0;overflow:auto;border-top:1px solid var(--ar-line)'
    body.innerHTML = Array.from({ length: 42 }, (_, i) => {
        const d = plus(s, i), e = entries.filter((x) => startOfDay(time(x.start)).getTime() === d.getTime() && filter(cls(x)) && cls(x) !== 'sleep')
        return `<div style="border-right:1px solid var(--ar-raise);border-bottom:1px solid var(--ar-raise);padding:4px;min-height:64px;overflow:hidden;${d.getMonth() !== m.getMonth() ? 'opacity:.5' : ''}"><b style="font:500 13px var(--ar-display)">${d.getDate()}</b>${e.slice(0, 3).map((x) => `<div style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(x.title)}</div>`).join('')}${e.length > 3 ? `<div style="font:400 10px var(--ar-mono);color:var(--ar-dim)">+${e.length - 3}</div>` : ''}</div>`
    }).join('')
}
function year(body) {
    body.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:18px;flex:1;min-height:0;overflow:auto;padding-top:8px'
    const busy = new Set(entries.filter((x) => cls(x) !== 'sleep').map((x) => startOfDay(time(x.start)).getTime()))
    body.innerHTML = Array.from({ length: 12 }, (_, k) => {
        const m = new Date(anchor.getFullYear(), k, 1), s = weekStart(m)
        return `<div class="pc-mini"><b>${monthTitle(m)}</b><div>${Array.from({ length: 42 }, (_, i) => { const d = plus(s, i); return `<i class="${d.getMonth() !== k ? 'out' : busy.has(d.getTime()) ? 'on' : ''}">${d.getDate()}</i>` }).join('')}</div></div>`
    }).join('')
}

function show(app, target, e) {
    if (card) card.remove()
    const r = target.getBoundingClientRect(), a = time(e.start), b = e.end ? time(e.end) : null
    const hm = (d) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    const who = { tree: tt('反射树', 'the tree of reactions'), own: tt('它自己', 'on its own'), owner: tt('你', 'you') }[e.who] || (e.by === 'owner' ? tt('你', 'you') : tt('它', 'it'))
    card = el('div', 'pc-card', `<b>${hm(a)}${b ? '–' + hm(b) : ''} ${esc(e.title)}</b>`
        + (e.refused ? `<div><span class="oc refused"></span> ${tt('安全层拒绝了', 'refused by the safety layer')}${e.reason ? ': ' + esc(e.reason) : ''}</div>` : e.outcome && e.outcome !== 'waiting' ? `<div><span class="oc ${esc(e.outcome)}"></span> ${outcome(e.outcome)}</div>` : '')
        + `<div class="k">${tt('谁', 'who')}</div><div>${esc(who)}</div>`
        + (e.reflex ? `<div class="k">${tt('反射树', 'reflex')}</div><div>${esc(e.reflex)}</div>` : '')
        + (e.note ? `<div class="k">${tt('它的判断', 'its judgement')}</div><div>${esc(e.note)}</div>` : '')
        + `<div class="na">${e.chat ? `<button class="lnk" data-chat>${tt('打开那个对话 →', 'Open that chat →')}</button>` : ''}${e.planned ? `<button data-remove>${tt('删除', 'Remove')}</button>` : ''}</div>`)
    document.body.append(card)
    card.style.left = Math.min(window.innerWidth - card.offsetWidth - 12, r.right + 10) + 'px'
    card.style.top = Math.max(12, Math.min(window.innerHeight - card.offsetHeight - 12, r.top - 20)) + 'px'
    const c = card.querySelector('[data-chat]'); if (c) c.onclick = () => { card.remove(); card = null; app.openChat(e.chat) }
    const x = card.querySelector('[data-remove]'); if (x) x.onclick = async () => { await post('/api/agent/calendar', { identity: app.identity.id, action: 'remove', id: e.id }); load(app) }
    setTimeout(() => document.addEventListener('click', function off(ev) { if (card && !card.contains(ev.target)) { card.remove(); card = null; document.removeEventListener('click', off) } }), 0)
}

async function budget(app) {
    const u = (await get('/api/agent/usage', { identity: app.identity.id })) || {}
    const d = u.today || {}, total = d.daily_budget || 2, reserve = d.reserve ?? 0.5, own = d.own_usd ?? d.own ?? 0
    const free = Math.max(0.01, total - reserve)
    $('.pc-budget i').style.width = Math.min(100, (own / free) * 100) + '%'
    $('.pc-budget small').textContent = tt(`它主动用了 ${usd(own)} / ${usd(free)} · 给你留 ${usd(reserve)}`, `on its own: ${usd(own)} of ${usd(free)} · ${usd(reserve)} kept for you`)
}

function create(app) {
    const d0 = startOfDay(anchor), iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    const start = new Date(d0.getTime() + 9 * 3600000)
    const d = dialog(`<h5>${tt('放一件事到日历上', 'Put something on the calendar')}</h5>
<label><span>${tt('标题', 'Title')}</span><input class="field" data-t placeholder="${tt('每天发群摘要', 'Daily group summary')}"></label>
<label><span>${tt('种类', 'Kind')}</span><select class="field" data-k><option value="task">${tt('任务', 'task')}</option><option value="reminder">${tt('提醒', 'reminder')}</option><option value="goal">${tt('目标', 'goal')}</option></select></label>
<label><span>${tt('开始', 'Start')}</span><input class="field" type="datetime-local" data-s value="${iso(start)}"></label>
<label><span>${tt('结束', 'End')}</span><input class="field" type="datetime-local" data-e value="${iso(new Date(start.getTime() + 3600000))}"></label>
<p class="note">${tt('到时间时叫醒它。', 'It is woken when this comes due.')}</p><div class="row"><span class="res"></span><button class="btn">${tt('保存', 'Save')}</button></div>`)
    d.querySelector('.btn').onclick = async () => {
        const body = { identity: app.identity.id, action: 'add', title: d.querySelector('[data-t]').value, kind: d.querySelector('[data-k]').value,
            at: new Date(d.querySelector('[data-s]').value).getTime() / 1000, until: new Date(d.querySelector('[data-e]').value).getTime() / 1000 }
        if (!body.title) return
        const r = await post('/api/agent/calendar', body)
        if (r.ok) { closeDialog(); load(app) } else d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`
    }
}

export const refresh = (app) => load(app)
