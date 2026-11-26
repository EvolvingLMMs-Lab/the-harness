// The calendar. How it is used is Google Calendar's web app: day, week, month and year; a
// click on an empty slot (or a drag over a stretch) opens a small box to name the entry, with
// "More options" for the whole form; an entry is dragged to another time or day and its lower
// edge to another length, each answered with "Saved" and Undo; a click on an entry shows a
// small card; a line marks the current time; entries at the same time stand side by side;
// entries of a whole day or longer sit in a row on top. The keys are those of "Use keyboard
// shortcuts in Google Calendar": d w m y (and 1 2 3) for the views, t today, j or n next,
// k or p previous, c create, e edit, Delete, z undo, / search, r refresh, g go to a date.
//
// What it shows is the plan's own: who put each thing there and who did it (the owner, it on
// its own, the tree of reactions, learning), how each ended and what the safety layer
// refused, and when it was asleep, told apart at a glance; and today's budget. An entry put
// at a time already past was never due: it is "missed", drawn and worded as that. A calendar
// with nothing on it is an ordinary empty calendar.
import { sashHtml } from './sash.js'
import { esc, tt, outcome, usd } from './i18n.js'
import { get, post, failed } from './api.js'
import { $, $$, el, on, dialog, closeDialog, dialogOpen, menuOpen, press, toast, said, ask, loading, problem, ic } from './ui.js'
import { icon } from './icons.js'
import { prefs } from './prefs.js'
import { meant, keysOf } from './keys.js'

// Pixels an hour in the day and week views; minutes a drag snaps to; pixels before a press is a drag.
const HOUR = 44, SNAP = 15, SLOP = 4
const DAY = 86400
// days are added on the calendar, not as 24 hours, so a change of summer time keeps midnights
const plus = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
const SHOW = { owner: true, own: true, learn: true, reflex: true, sleep: true }
const VIEWS = [['day', '日', 'Day', 'd'], ['week', '周', 'Week', 'w'], ['month', '月', 'Month', 'm'], ['year', '年', 'Year', 'y']]
const KINDS = [['task', '任务', 'Task'], ['reminder', '提醒', 'Reminder'], ['goal', '目标', 'Goal']]

let app = null
let anchor = startOfDay(new Date()), view = prefs.get('calendar.view', 'week')
let entries = [], loaded = false, broken = null, pausedOwn = false
let pop = null // the small box that is open: quick create, or an entry's card
let chosen = null // the entry the keyboard acts on
let undo = null // how to take the last change back
let query = '', found = null // the search, and what the host found for it
let clock = null, reloading = null

function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
function weekStart(d) { const x = startOfDay(d); x.setDate(x.getDate() - (x.getDay() + 6) % 7); return x }
const date = (seconds) => new Date(seconds * 1000)
const secs = (d) => d.getTime() / 1000
const hm = (d) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
const days = () => (view === 'day' ? [startOfDay(anchor)] : Array.from({ length: 7 }, (_, i) => plus(weekStart(anchor), i)))
const WEEKDAYS = () => tt(['周一', '周二', '周三', '周四', '周五', '周六', '周日'], ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
const monthName = (d) => tt(`${d.getFullYear()}年${d.getMonth() + 1}月`, d.toLocaleString('en', { month: 'long', year: 'numeric' }))
const dayName = (d) => tt(`${d.getMonth() + 1}月${d.getDate()}日 ${WEEKDAYS()[(d.getDay() + 6) % 7]}`, d.toLocaleDateString('en', { weekday: 'short', month: 'short', day: 'numeric' }))
const local = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
const title = () => (view === 'day' ? tt(`${anchor.getFullYear()}年${anchor.getMonth() + 1}月${anchor.getDate()}日`, anchor.toLocaleDateString('en', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }))
    : view === 'year' ? String(anchor.getFullYear()) : monthName(view === 'week' ? weekStart(anchor) : anchor))

// what an entry is drawn as: whose it is
function cls(e) {
    if (e.kind === 'asleep') return 'sleep'
    if (e.who === 'tree') return 'reflex'
    if (e.kind === 'plan' || (e.planned && e.by === 'agent' && date(e.start) > new Date())) return 'plan'
    if (e.who === 'owner' || e.by === 'owner') return 'owner'
    if (e.learning || e.kind === 'learn' || e.kind === 'practice' || e.kind === 'review' || e.kind === 'learning') return 'learn'
    return 'own'
}
const missed = (e) => !!e.missed || e.outcome === 'missed' // put at a time already past: never due, nothing done
const look = (e) => cls(e) + (missed(e) ? ' missed' : '') + (e.outcome === 'waiting' ? ' wait' : '')
const shownKind = (c) => SHOW[c === 'plan' ? 'own' : c] !== false
const mine = (e) => !!e.planned && !String(e.id).startsWith('log-') // what the owner can change
const movable = (e) => mine(e) && !e.repeat
const whole = (e) => e.end - e.start >= DAY // a whole day or longer: the row on top
const visible = () => entries.filter((e) => shownKind(cls(e)))
const who = (e) => ({ tree: tt('反射树的一个反应', 'a reaction of the tree'), own: tt('它自己', 'it, on its own'), owner: tt('你', 'you') }[e.who]
    || (e.by === 'owner' ? tt('你', 'you') : tt('它', 'it')))
function span(e) {
    const a = date(e.start), b = date(e.end)
    if (whole(e)) { const last = plus(b, b.getHours() || b.getMinutes() ? 0 : -1); return a.toDateString() === last.toDateString() ? dayName(a) : `${dayName(a)} – ${dayName(last)}` }
    return `${dayName(a)} · ${hm(a)}${e.has_end === false && e.planned ? '' : ' – ' + hm(b)}`
}

function range() {
    if (view === 'month') { const a = new Date(anchor.getFullYear(), anchor.getMonth(), 1); return [weekStart(a), plus(weekStart(a), 42)] }
    if (view === 'year') return [new Date(anchor.getFullYear(), 0, 1), new Date(anchor.getFullYear() + 1, 0, 1)]
    const d = days(); return [d[0], plus(d[d.length - 1], 1)]
}
const stretch = () => { const [from, to] = range(); return { from: from.toISOString(), to: to.toISOString() } }

// ── the frame ──
export async function open(given) {
    app = given
    loaded = false; broken = null; chosen = null; query = ''; found = null
    const host = $('.pc')
    host.innerHTML = `
  <div class="pc-left"><button type="button" class="pc-create" data-act="cal-create" data-tip="${tt('新建', 'Create')}" data-keys="C">${icon('plus', 14)}<span>${tt('创建', 'Create')}</span></button>
    <div class="pc-mini"></div>
    <fieldset class="pc-cals"><legend>${tt('显示', 'Shown')}</legend>
      ${[['owner', tt('你放的', 'From you')], ['own', tt('它主动做的', 'On its own')], ['learn', tt('学习', 'Learning')], ['reflex', tt('反射树的反应', 'Reactions of the tree')], ['sleep', tt('睡觉', 'Asleep')]]
        .map(([k, n]) => `<label class="${k}"><input type="checkbox" data-cal="${k}"${SHOW[k] ? ' checked' : ''}><i></i><span>${n}</span></label>`).join('')}</fieldset>
    <div class="pc-own"><label><input type="checkbox" data-own><span>${tt('让它自己做事', 'Let it act on its own')}</span></label></div>
    <div class="pc-budget"><b>${tt('今天的预算', "Today's budget")}</b><div class="ubar"><i></i></div><small></small></div>
  </div>
  ${sashHtml('calendar')}
  <div class="pc-main">
    <div class="pc-head" data-tauri-drag-region="deep">${ic('sidebar', tt('展开左栏', 'Show the sidebar'), { act: 'side-toggle', keys: keysOf('sidebar'), cls: 'show-side' })}<button type="button" class="pc-today" data-act="cal-today" data-tip="${tt('回到今天', 'Go to today')}" data-keys="T">${tt('今天', 'Today')}</button>${ic('left', tt('上一段', 'Previous'), { act: 'cal-step', keys: 'K', cls: 'prev', attrs: 'data-arg="-1"' })}${ic('right', tt('下一段', 'Next'), { act: 'cal-step', keys: 'J', cls: 'next', attrs: 'data-arg="1"' })}<h2></h2>
      <input type="search" class="pc-find" placeholder="${tt('找日历上的事', 'Search the calendar')}" aria-label="${tt('找日历上的事', 'Search the calendar')}" data-tip="${tt('搜索', 'Search')}" data-keys="/">
      <span class="pc-views seg" role="radiogroup" aria-label="${tt('视图', 'View')}">${VIEWS.map(([k, z, e, key]) => `<button type="button" role="radio" aria-checked="${k === view}" data-act="cal-view" data-arg="${k}" data-tip="${tt(z + '视图', e + ' view')}" data-keys="${key.toUpperCase()}">${tt(z, e)}</button>`).join('')}</span></div>
    <div class="pc-body">${loading()}</div>
  </div>`
    $$('[data-cal]', host).forEach((box) => { box.onchange = () => { SHOW[box.dataset.cal] = box.checked; draw() } })
    host.querySelector('[data-own]').onchange = async (e) => {
        const r = await post('/api/agent/calendar', { identity: app.identity.id, action: e.target.checked ? 'resume_own' : 'pause_own', ...stretch() })
        if (!r.ok) { e.target.checked = !e.target.checked; return said(r) }
        pausedOwn = !!r.data.paused_own
        toast(pausedOwn ? tt('它不再自己做事；你的事和点名照常。', 'It no longer acts on its own; what you ask and mentions go on.') : tt('它又会自己做事了。', 'It acts on its own again.'))
    }
    const find = host.querySelector('.pc-find')
    let asking = null
    find.oninput = () => { query = find.value.trim(); clearTimeout(asking); asking = setTimeout(search, 200) }
    wirePointer(host.querySelector('.pc-body'))
    clearInterval(clock); clock = setInterval(() => { if (app.view === 'calendar') nowLine(); else clearInterval(clock) }, 30000)
    clearInterval(reloading); reloading = setInterval(() => { if (app.view !== 'calendar') return clearInterval(reloading); if (!pop && !dragging && !dialogOpen() && !document.hidden) load(true) }, 30000)
    await load()
    budget()
}

export async function load(quiet = false) {
    const asked = `${view}/${anchor.getTime()}`
    const got = await get('/api/agent/calendar', { identity: app.identity.id, ...stretch() })
    if (asked !== `${view}/${anchor.getTime()}` || app.view !== 'calendar') return
    if (!got) { if (!loaded || !quiet) { broken = failed.get('/api/agent/calendar'); draw() } return }
    broken = null; loaded = true
    entries = got.entries || []; pausedOwn = !!got.paused_own
    if (!quiet || !dragging) draw()
}
export const refresh = () => load()

// One change of the calendar: the host answers with the stretch after it and what it made of
// the entry. `back`: how to take it back (said with "Undo", and done by z).
async function change(body, saidText, back) {
    const r = await post('/api/agent/calendar', { identity: app.identity.id, ...body, ...stretch() })
    if (!r.ok) { said(r, tt('没改成', 'It was not changed')); draw(); return null }
    entries = r.data.entries || entries
    found = null
    const made = r.data.result || {}
    undo = back ? () => back(made) : null
    draw()
    // put at a time already past: it is kept as missed, and says so instead of a plain "Saved"
    const text = made.missed && body.action !== 'remove' ? tt('已保存，记为错过：这个时间已经过了，不会去做', 'Saved as missed: that time has already passed, so it will not be done') : saidText
    if (text) toast(text, undo ? { action: { label: tt('撤销', 'Undo'), keys: 'Z', run: undoLast } } : {})
    return made
}
function undoLast() {
    if (!undo) return toast(tt('没有可撤销的', 'Nothing to undo'))
    const back = undo
    undo = null
    $$('.toast.has-act').forEach((old) => old.remove())
    return back()
}
const until = (e) => (e.has_end === false ? null : e.end)
const move = (e, start, end) => change({ action: 'update', id: e.id, at: start, until: end }, tt('已保存', 'Saved'),
    () => change({ action: 'update', id: e.id, at: e.start, until: until(e) }, tt('已撤销', 'Undone')))
const remove = (e) => change({ action: 'remove', id: e.id }, tt('已删除', 'Deleted'), () => change({ action: 'restore', id: e.id }, tt('已放回', 'Put back')))
const add = (fields) => change({ action: 'add', ...fields }, tt('已保存', 'Saved'), (made) => (made.id ? change({ action: 'remove', id: made.id }, tt('已撤销', 'Undone')) : null))

// ── drawing ──
function mini() {
    const m = new Date(anchor.getFullYear(), anchor.getMonth(), 1), s = weekStart(m), today = startOfDay(new Date()).getTime()
    const [from, to] = range()
    $('.pc-mini').innerHTML = `<div class="mh"><b>${monthName(anchor)}</b>${ic('left', tt('上个月', 'Previous month'), { act: 'cal-month', attrs: 'data-arg="-1"' })}${ic('right', tt('下个月', 'Next month'), { act: 'cal-month', attrs: 'data-arg="1"' })}</div><div class="mg">${tt('一二三四五六日', 'MTWTFSS').split('').map((d) => `<i>${d}</i>`).join('')}`
        + Array.from({ length: 42 }, (_, i) => {
            const d = plus(s, i)
            return `<button type="button" tabindex="-1" data-act="cal-goto" data-arg="${d.getTime()}" aria-label="${esc(dayName(d))}" class="${d.getTime() === today ? 'on' : ''}${d.getMonth() !== m.getMonth() ? ' out' : ''}${(view === 'day' || view === 'week') && d >= from && d < to ? ' in' : ''}">${d.getDate()}</button>`
        }).join('') + '</div>'
}

function draw() {
    closePop()
    const host = $('.pc'); if (!host || !host.querySelector('.pc-body')) return
    mini()
    host.querySelector('.pc-head h2').textContent = title()
    $$('.pc-views button', host).forEach((b) => b.setAttribute('aria-checked', b.dataset.arg === view))
    host.querySelector('[data-own]').checked = !pausedOwn
    const body = host.querySelector('.pc-body')
    body.className = `pc-body v-${query ? 'find' : view}`
    if (broken) { body.innerHTML = problem(broken, { title: tt('日历没有读出来', 'The calendar could not be read'), retry: 'cal-refresh' }); return }
    if (!loaded) { body.innerHTML = loading(); return }
    if (query) return results(body)
    if (view === 'month') month(body)
    else if (view === 'year') year(body)
    else grid(body)
    if (chosen) { const back = nodeOf(chosen); if (back) back.classList.add('sel'); else chosen = null }
}

// Entries of one day that overlap stand side by side: each gets a lane of its cluster.
function lanes(list) {
    const sorted = [...list].sort((a, b) => a.s - b.s || b.f - a.f)
    let cluster = [], ends = [], last = -Infinity
    const close = () => { for (const item of cluster) item.of = ends.length; cluster = []; ends = [] }
    for (const item of sorted) {
        if (item.s >= last) close()
        let lane = ends.findIndex((end) => end <= item.s)
        if (lane < 0) { lane = ends.length; ends.push(item.f) } else ends[lane] = item.f
        item.lane = lane; cluster.push(item)
        last = Math.max(last, item.f)
    }
    close()
    return sorted
}
const mark = (e) => { const oc = e.refused ? 'refused' : missed(e) ? 'missed' : e.outcome; return oc && oc !== 'waiting' ? `<span class="oc ${esc(oc)}" title="${esc(outcome(oc))}"></span>` : '' }
const label = (e) => `${e.title}, ${span(e)}, ${who(e)}${e.refused ? ', ' + tt('被安全层拒绝', 'refused by the safety layer') : missed(e) ? ', ' + outcome('missed') : e.outcome ? ', ' + outcome(e.outcome) : ''}`
const nodeOf = (e) => $(`.pc-body .pc-ev[data-id="${CSS.escape(String(e.id))}"][data-start="${e.start}"]`)
const attrs = (e) => `data-id="${esc(e.id)}" data-start="${e.start}" aria-label="${esc(label(e))}"`

function grid(body) {
    const ds = days(), today = startOfDay(new Date()).getTime(), names = WEEKDAYS()
    const from = secs(ds[0]), list = visible()
    // the row on top: what lasts a whole day or longer, each across the days it covers
    const top = []
    for (const e of list.filter((x) => whole(x) && cls(x) !== 'sleep')) {
        const a = Math.max(0, Math.floor((e.start - from) / DAY)), b = Math.min(ds.length, Math.ceil((e.end - from) / DAY))
        if (b <= 0 || a >= ds.length) continue
        let lane = 0
        while (top.some((t) => t.lane === lane && t.a < b && a < t.b)) lane++
        top.push({ e, a, b, lane })
    }
    const allday = `<div class="pc-allday" style="--days:${ds.length}"><span class="gut">${tt('全天', 'all day')}</span><div class="lanes" style="--lanes:${Math.max(1, ...top.map((t) => t.lane + 1))}">`
        + ds.map((d, i) => `<div class="cell" data-day="${d.getTime()}" style="grid-column:${i + 1};grid-row:1 / -1"></div>`).join('')
        + top.map((t) => `<button type="button" class="pc-ev bar ${look(t.e)}${movable(t.e) ? ' can' : ''}" ${attrs(t.e)} style="grid-column:${t.a + 1} / ${t.b + 1};grid-row:${t.lane + 1}"><b>${esc(t.e.title)}</b>${mark(t.e)}</button>`).join('') + `</div></div>`
    // the hours: each day's entries by time, side by side where they overlap
    const columns = ds.map((d, i) => {
        const start = secs(d), end = secs(plus(d, 1))
        const here = list.filter((e) => !whole(e) || cls(e) === 'sleep').filter((e) => e.start < end && e.end > start)
        const bands = here.filter((e) => cls(e) === 'sleep').map((e) => { const s = Math.max(e.start, start), f = Math.min(e.end, end); return `<div class="pc-sleep" style="top:${(s - start) / 3600 * HOUR}px;height:${(f - s) / 3600 * HOUR}px" title="${esc(tt('它在睡觉', 'It was asleep'))}"></div>` }).join('')
        const dots = here.filter((e) => cls(e) === 'reflex').map((e) => `<button type="button" class="pc-ev pc-dot" ${attrs(e)} style="top:${(Math.max(e.start, start) - start) / 3600 * HOUR}px"><i></i><span>${esc(e.title)}</span></button>`).join('')
        const blocks = lanes(here.filter((e) => !['sleep', 'reflex'].includes(cls(e))).map((e) => ({ e, s: Math.max(e.start, start), f: Math.max(Math.min(e.end, end), Math.max(e.start, start) + 900) })))
            .map(({ e, s, f, lane, of }) => {
                const h = Math.max(18, (f - s) / 3600 * HOUR - 2), c = cls(e)
                return `<button type="button" class="pc-ev ${look(e)}${movable(e) ? ' can' : ''}" ${attrs(e)} style="top:${(s - start) / 3600 * HOUR}px;height:${h}px;left:calc(${(lane / of) * 100}% + 2px);width:calc(${100 / of}% - 5px)">`
                    + `<b>${esc(e.title)}</b>${mark(e)}${h > 30 ? `<small>${hm(date(e.start))}${e.has_end === false ? '' : '–' + hm(date(e.end))}</small>` : ''}${movable(e) && e.end <= end ? '<i class="rs"></i>' : ''}</button>`
            }).join('')
        return `<div class="pc-col${d.getTime() === today ? ' on' : ''}" data-day="${d.getTime()}" style="grid-column:${i + 2}">${bands}${blocks}${dots}</div>`
    }).join('')
    const keep = body.querySelector('.pc-scroll') ? body.querySelector('.pc-scroll').scrollTop : null
    body.style.setProperty('--days', ds.length)
    body.innerHTML = `<div class="pc-days" style="--days:${ds.length}"><span class="gut"></span>${ds.map((d) => `<button type="button" class="pc-dayh${d.getTime() === today ? ' on' : ''}" data-act="cal-day" data-arg="${d.getTime()}" aria-label="${esc(dayName(d))}"><span>${names[(d.getDay() + 6) % 7]}</span><b>${d.getDate()}</b></button>`).join('')}</div>`
        + allday + `<div class="pc-scroll" tabindex="-1"><div class="pc-grid" style="--days:${ds.length};--hour:${HOUR}px">`
        + Array.from({ length: 24 }, (_, i) => `<div class="pc-hour" style="top:${i * HOUR}px"><span>${i ? String(i).padStart(2, '0') + ':00' : ''}</span></div>`).join('')
        + columns + `<div class="pc-now" hidden></div></div></div>`
    const scroll = body.querySelector('.pc-scroll')
    scroll.scrollTop = keep !== null ? keep : Math.max(0, (new Date().getHours() - 2) * HOUR)
    nowLine()
}
function nowLine() {
    const line = $('.pc-now'); if (!line) return
    const ds = days(), now = new Date(), k = ds.findIndex((d) => d.getTime() === startOfDay(now).getTime())
    line.hidden = k < 0
    if (k < 0) return
    line.style.top = (now.getHours() + now.getMinutes() / 60) * HOUR + 'px'
    line.style.left = `calc(var(--gut) + ${k} * (100% - var(--gut)) / ${ds.length})`
    line.style.width = `calc((100% - var(--gut)) / ${ds.length})`
}

function month(body) {
    const m = new Date(anchor.getFullYear(), anchor.getMonth(), 1), s = weekStart(m), today = startOfDay(new Date()).getTime()
    const list = visible().filter((e) => cls(e) !== 'sleep')
    body.innerHTML = `<div class="pc-wk">${WEEKDAYS().map((n) => `<span>${n}</span>`).join('')}</div><div class="pc-month">` + Array.from({ length: 42 }, (_, i) => {
        const d = plus(s, i), a = secs(d), b = secs(plus(d, 1))
        const here = list.filter((e) => e.start < b && e.end > a && (whole(e) || (e.start >= a))).sort((x, y) => (whole(y) - whole(x)) || x.start - y.start)
        const room = 3
        return `<div class="cell${d.getMonth() !== m.getMonth() ? ' out' : ''}${d.getTime() === today ? ' on' : ''}" data-day="${d.getTime()}">`
            + `<button type="button" class="num" data-act="cal-day" data-arg="${d.getTime()}" aria-label="${esc(dayName(d))}">${d.getDate()}</button>`
            + here.slice(0, room).map((e) => `<button type="button" class="pc-ev chip ${look(e)}${movable(e) ? ' can' : ''}" ${attrs(e)}>${whole(e) || cls(e) === 'reflex' ? '' : `<small>${hm(date(e.start))}</small>`}<b>${esc(e.title)}</b>${mark(e)}</button>`).join('')
            + (here.length > room ? `<button type="button" class="more" data-act="cal-day" data-arg="${d.getTime()}">${tt(`还有 ${here.length - room} 项`, `${here.length - room} more`)}</button>` : '') + `</div>`
    }).join('') + `</div>`
}

function year(body) {
    const today = startOfDay(new Date()).getTime()
    const count = new Map()
    for (const e of visible().filter((x) => cls(x) !== 'sleep')) { const k = startOfDay(date(e.start)).getTime(); count.set(k, (count.get(k) || 0) + 1) }
    body.innerHTML = `<div class="pc-year">` + Array.from({ length: 12 }, (_, k) => {
        const m = new Date(anchor.getFullYear(), k, 1), s = weekStart(m)
        return `<div class="ym"><button type="button" class="yt" data-act="cal-month-open" data-arg="${m.getTime()}">${tt(`${k + 1}月`, m.toLocaleString('en', { month: 'long' }))}</button><div class="mg">${tt('一二三四五六日', 'MTWTFSS').split('').map((d) => `<i>${d}</i>`).join('')}`
            + Array.from({ length: 42 }, (_, i) => {
                const d = plus(s, i)
                if (d.getMonth() !== k) return '<span></span>'
                const n = count.get(d.getTime()) || 0
                return `<button type="button" data-act="cal-day" data-arg="${d.getTime()}" class="${d.getTime() === today ? 'on' : ''}${n ? ' has' : ''}" aria-label="${esc(dayName(d) + (n ? tt(`，${n} 件事`, `, ${n} entr${n === 1 ? 'y' : 'ies'}`) : ''))}"${n ? ` data-tip="${esc(tt(`${n} 件事`, `${n} entr${n === 1 ? 'y' : 'ies'}`))}"` : ''}>${d.getDate()}</button>`
            }).join('') + `</div></div>`
    }).join('') + `</div>`
}

// ── search: the host looks through titles and notes, a year either side of today ──
let asked = 0
async function search() {
    if (!query) { found = null; return draw() }
    const mine = ++asked, q = query
    const got = await get('/api/agent/calendar', { identity: app.identity.id, q })
    if (mine !== asked || q !== query) return // a newer search is on its way
    found = { q, entries: got ? got.entries || [] : null }
    draw()
}
function results(body) {
    if (!found || found.q !== query) { body.innerHTML = loading(tt('正在找…', 'Searching…')); if (!found) search(); return }
    if (!found.entries) { body.innerHTML = problem(failed.get('/api/agent/calendar'), { title: tt('没搜成', 'The search failed'), retry: 'cal-refresh' }); return }
    const hits = found.entries.filter((e) => cls(e) !== 'sleep')
    body.innerHTML = `<div class="pc-found"><p>${tt(`标题或备注里有“${query}”的 ${hits.length} 件事（今天前后各一年）`, `${hits.length} entr${hits.length === 1 ? 'y' : 'ies'} with "${query}" in the title or note, a year either side of today`)}</p>`
        + (hits.length ? hits.map((e) => `<button type="button" class="hit" data-act="cal-hit" data-arg="${esc(e.id)}" data-start="${e.start}"><i class="sw ${cls(e)}"></i><span class="when">${esc(span(e))}</span><b>${esc(e.title)}</b>${mark(e)}<span class="who">${esc(who(e))}</span></button>`).join('')
            : `<div class="st st-empty"><b>${tt('没有找到', 'Nothing found')}</b><span>${tt('标题和备注里都没有这段文字。', 'Neither a title nor a note has this text.')}</span></div>`) + `</div>`
}

// ── the small boxes: quick create, and an entry's card ──
function closePop(refocus = false) {
    if (!pop) return false
    const back = pop._back
    pop.remove(); pop = null
    $$('.pc .ghost').forEach((g) => g.remove())
    if (refocus && back && document.contains(back)) back.focus()
    return true
}
function place(box, rect) {
    $('.pc').append(box)
    const w = box.offsetWidth, h = box.offsetHeight
    let left = rect.right + 8
    if (left + w > innerWidth - 8) left = rect.left - w - 8
    if (left < 8) left = Math.max(8, Math.min(innerWidth - w - 8, rect.left))
    box.style.left = left + 'px'
    box.style.top = Math.max(8, Math.min(innerHeight - h - 8, rect.top - 8)) + 'px'
    pop = box
    box.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return
        const all = $$('button, input, select, textarea', box).filter((n) => !n.disabled && n.offsetParent !== null)
        if (e.shiftKey && document.activeElement === all[0]) { e.preventDefault(); all[all.length - 1].focus() } else if (!e.shiftKey && document.activeElement === all[all.length - 1]) { e.preventDefault(); all[0].focus() }
    })
}

// Quick create: a title for the stretch that was clicked or dragged out; Enter saves.
function quick(start, end, rect, back) {
    closePop()
    const allDay = end - start >= DAY
    const box = el('form', 'pc-pop quick', `<input type="text" data-title placeholder="${tt('加个标题', 'Add a title')}" aria-label="${tt('标题', 'Title')}">`
        + `<p>${esc(span({ start, end, has_end: true }))}</p>`
        + `<label><span>${tt('种类', 'Kind')}</span><select data-kind>${KINDS.map(([k, z, e]) => `<option value="${k}"${(allDay ? 'goal' : 'task') === k ? ' selected' : ''}>${tt(z, e)}</option>`).join('')}</select></label>`
        + `<div class="pa"><button type="button" class="b quiet" data-more>${tt('更多选项', 'More options')}</button><button type="submit" class="b pri">${tt('保存', 'Save')}</button></div>`)
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', tt('新建一件事', 'New entry'))
    box._back = back
    place(box, rect)
    const name = box.querySelector('[data-title]')
    name.focus()
    box.onsubmit = async (e) => {
        e.preventDefault()
        const fields = { title: name.value.trim() || tt('（没有标题）', '(No title)'), at: start, until: end, kind: box.querySelector('[data-kind]').value }
        closePop()
        await add(fields)
    }
    box.querySelector('[data-more]').onclick = () => { const fields = { title: name.value.trim(), start, end, kind: box.querySelector('[data-kind]').value }; closePop(); form(fields) }
}

// An entry's card: who put it there, what was done, how it ended; edit and delete for what the owner can change.
function card(e, target) {
    closePop()
    chosen = e
    $$('.pc-ev.sel').forEach((n) => n.classList.remove('sel')); target.classList.add('sel')
    const oc = e.refused ? 'refused' : missed(e) ? 'missed' : e.outcome
    const c = cls(e)
    const what = e.planned ? (e.by === 'owner' ? tt('你放在日历上的', 'You put it on the calendar') : tt('它放在日历上的', 'It put it on the calendar'))
        : c === 'reflex' ? tt('反射树的一个反应', 'A reaction of the tree') : e.who === 'owner' ? tt('你交代的事，它做了', 'It did this for you') : c === 'learn' ? tt('它在学习', 'It was learning') : tt('它自己做的', 'It did this on its own')
    const kind = e.planned ? (KINDS.find((k) => k[0] === e.kind) || [e.kind, e.kind === 'plan' ? '它的打算' : e.kind, e.kind === 'plan' ? 'its own plan' : e.kind]) : null
    const box = el('div', 'pc-pop card', `<div class="ph"><i class="sw ${c}"></i><b>${esc(e.title)}</b><span class="pt">`
        + (mine(e) ? ic('edit', tt('编辑', 'Edit'), { keys: 'E', attrs: 'data-edit' }) + ic('trash', tt('删除', 'Delete'), { keys: 'Delete', attrs: 'data-delete' }) : '')
        + ic('close', tt('关闭', 'Close'), { keys: 'Esc', attrs: 'data-close' }) + `</span></div><p>${esc(span(e))}${e.repeat ? ` · ${e.repeat === 'daily' ? tt('每天', 'every day') : tt('每周', 'every week')}` : ''}</p>`
        + `<dl><dt>${tt('谁', 'Who')}</dt><dd>${esc(what)}</dd>`
        + (kind ? `<dt>${tt('种类', 'Kind')}</dt><dd>${esc(tt(kind[1], kind[2]))}</dd>` : '')
        + (oc && oc !== 'waiting' ? `<dt>${tt('结果', 'Outcome')}</dt><dd><span class="oc ${esc(oc)}">${esc(outcome(oc))}</span>${e.refused ? ' ' + esc(tt('安全层拒绝了其中一步', 'the safety layer refused a step')) : ''}${oc === 'missed' ? ' ' + esc(tt('时间已过，没有做', 'its time had passed: not done')) : ''}</dd>` : e.planned && date(e.start) > new Date() ? `<dt>${tt('结果', 'Outcome')}</dt><dd>${tt('还没到时间', 'not due yet')}</dd>` : '')
        + (e.place ? `<dt>${tt('在哪里', 'Where')}</dt><dd>${esc(e.place)}</dd>` : '')
        + (e.note ? `<dt>${tt('备注', 'Note')}</dt><dd>${esc(e.note)}</dd>` : '') + `</dl>`
        + (e.chat ? `<div class="pa"><button type="button" class="b" data-chat>${tt('打开那个对话', 'Open that chat')}</button></div>` : ''))
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', e.title)
    box._back = target
    place(box, target.getBoundingClientRect())
    const open = box.querySelector('[data-chat]'); if (open) open.onclick = () => { closePop(); app.openChat(e.chat) }
    const edit = box.querySelector('[data-edit]'); if (edit) edit.onclick = () => { closePop(); form({ ...e, edit: e }) }
    const del = box.querySelector('[data-delete]'); if (del) del.onclick = () => { closePop(); chosen = null; remove(e) }
    box.querySelector('[data-close]').onclick = () => closePop(true)
    box.tabIndex = -1; box.focus() // the card has the keyboard: E, Delete and Esc act on it, Tab reaches its buttons
}

// The whole form ("More options", Edit, and Create from the keyboard).
function form({ title: name = '', start, end, kind = 'task', repeat = null, note = '', has_end = true, edit = null }) {
    const a = date(start), b = date(end)
    const allDay = end - start >= DAY && a.getHours() === 0 && a.getMinutes() === 0
    const d = dialog(`<h5>${edit ? tt('编辑', 'Edit') : tt('放一件事到日历上', 'Put something on the calendar')}</h5>
<label><span>${tt('标题', 'Title')}</span><input class="field" data-t value="${esc(name)}"></label>
<label><span>${tt('种类', 'Kind')}</span><select class="field" data-k>${KINDS.map(([k, z, e]) => `<option value="${k}"${k === kind ? ' selected' : ''}>${tt(z, e)}</option>`).join('')}${KINDS.some((k) => k[0] === kind) ? '' : `<option value="${esc(kind)}" selected>${esc(kind)}</option>`}</select></label>
<label class="check"><input type="checkbox" data-all${allDay ? ' checked' : ''}><span>${tt('全天', 'All day')}</span></label>
<label><span>${tt('开始', 'Start')}</span><input class="field" type="${allDay ? 'date' : 'datetime-local'}" data-s value="${allDay ? local(a).slice(0, 10) : local(a)}"></label>
<label><span>${tt('结束', 'End')}</span><input class="field" type="${allDay ? 'date' : 'datetime-local'}" data-e value="${allDay ? local(plus(b, -1)).slice(0, 10) : local(b)}"></label>
<label><span>${tt('重复', 'Repeats')}</span><select class="field" data-r><option value="">${tt('不重复', 'Does not repeat')}</option><option value="daily"${repeat === 'daily' ? ' selected' : ''}>${tt('每天', 'Every day')}</option><option value="weekly"${repeat === 'weekly' ? ' selected' : ''}>${tt('每周', 'Every week')}</option></select></label>
<label><span>${tt('备注', 'Note')}</span><textarea class="field" data-n rows="2">${esc(note || '')}</textarea></label>
<p class="note">${''}${edit && edit.repeat ? ' ' + tt('这是一件重复的事：改的是它的每一次；改时间的话，从这一次起算。', 'This entry repeats: every occurrence changes, and a new time counts from this one on.') : ''}</p>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('保存', 'Save')}</button></div>`)
    const all = d.querySelector('[data-all]'), s = d.querySelector('[data-s]'), f = d.querySelector('[data-e]')
    all.onchange = () => {
        // the same days, as whole days or with a time of day (a date alone is read as local midnight)
        const day = (text, fallback) => (text || local(fallback)).slice(0, 10)
        for (const [node, when] of [[s, day(s.value, a)], [f, day(f.value, b)]]) { node.value = ''; node.type = all.checked ? 'date' : 'datetime-local'; node.value = all.checked ? when : when + (node === s ? 'T09:00' : 'T10:00') }
    }
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const res = d.querySelector('.res')
        const from = all.checked ? new Date(`${s.value}T00:00`) : new Date(s.value), to = all.checked ? plus(new Date(`${f.value}T00:00`), 1) : new Date(f.value)
        if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) { res.innerHTML = `<span class="c-failed">✕ ${tt('开始和结束都要填。', 'Give both a start and an end.')}</span>`; return }
        const fields = { title: d.querySelector('[data-t]').value.trim() || tt('（没有标题）', '(No title)'), kind: d.querySelector('[data-k]').value, at: secs(from), until: secs(to), repeat: d.querySelector('[data-r]').value || null, note: d.querySelector('[data-n]').value }
        if (to <= from) { res.innerHTML = `<span class="c-failed">✕ ${tt('结束要晚于开始。', 'The end has to be after the start.')}</span>`; return }
        if (edit) {
            // only what was changed: an occurrence of a repeating entry keeps the times of the others
            const was = { title: edit.title, kind: edit.kind, at: edit.start, until: edit.end, repeat: edit.repeat || null, note: edit.note || '' }
            for (const k of Object.keys(fields)) if (fields[k] === was[k]) delete fields[k]
            if (!Object.keys(fields).length) return closeDialog()
        }
        const r = await post('/api/agent/calendar', { identity: app.identity.id, action: edit ? 'update' : 'add', ...(edit ? { id: edit.id } : {}), ...fields, ...stretch() })
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog()
        entries = r.data.entries || entries; found = null
        const made = r.data.result || {}
        undo = edit ? () => change({ action: 'update', id: edit.id, title: edit.title, kind: edit.kind, at: edit.start, until: until(edit), repeat: edit.repeat || null, note: edit.note || '' }, tt('已撤销', 'Undone'))
            : () => (made.id ? change({ action: 'remove', id: made.id }, tt('已撤销', 'Undone')) : null)
        draw()
        toast(made.missed ? tt('已保存，记为错过：这个时间已经过了，不会去做', 'Saved as missed: that time has already passed, so it will not be done') : tt('已保存', 'Saved'), { action: { label: tt('撤销', 'Undo'), keys: 'Z', run: undoLast } })
    })
}

// ── the pointer: click a slot or drag out a stretch to create, drag an entry to move it, its lower edge to change its length ──
let dragging = null
function wirePointer(body) {
    const at = (x, y) => {
        // the day column and the minutes of the day under a point of the hour grid
        const cols = $$('.pc-col', body)
        const col = cols.find((c) => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right }) || (x < cols[0].getBoundingClientRect().left ? cols[0] : cols[cols.length - 1])
        const top = body.querySelector('.pc-grid').getBoundingClientRect().top
        return { col, day: +col.dataset.day / 1000, minutes: Math.max(0, Math.min(24 * 60, ((y - top) / HOUR) * 60)) }
    }
    const snap = (m) => Math.round(m / SNAP) * SNAP
    const entry = (node) => visible().find((e) => String(e.id) === node.dataset.id && String(e.start) === node.dataset.start)
    const ghost = (col, from, to, text) => {
        $$('.ghost', body).forEach((g) => g.remove())
        const g = el('div', 'pc-ev ghost', `<b>${esc(text)}</b><small>${hm(date(from))}–${hm(date(to))}</small>`)
        const day = +col.dataset.day / 1000
        g.style.top = ((from - day) / 3600) * HOUR + 'px'; g.style.height = Math.max(14, ((to - from) / 3600) * HOUR - 2) + 'px'
        col.append(g)
        return g
    }
    body.addEventListener('pointerdown', (ev) => {
        if (ev.button !== 0 || ev.target.closest('.pc-pop')) return
        const node = ev.target.closest('.pc-ev:not(.ghost)')
        const cell = ev.target.closest('.pc-month .cell, .pc-allday .cell')
        const inGrid = !!ev.target.closest('.pc-grid')
        const e = node ? entry(node) : null
        if (node && !e) return
        if (!node && !cell && !(inGrid && ev.target.closest('.pc-col'))) return
        if (ev.target.closest('.num, .more')) return
        if (!node && closedBy === ev) return
        try { body.setPointerCapture(ev.pointerId) } catch { /* no such pointer: nothing to hold */ }
        const d = dragging = { x: ev.clientX, y: ev.clientY, moved: false, e, node, cell,
            mode: e ? (ev.target.closest('.rs') ? 'size' : 'move') : cell ? 'cell' : 'new', from: inGrid ? at(ev.clientX, ev.clientY) : null, pointer: ev.pointerId }
        if (d.mode === 'move' && d.from) d.grab = d.from.day + d.from.minutes * 60 - Math.max(e.start, d.from.day)
        ev.preventDefault() // no text selection while dragging; the focus is given below
        if (node) node.focus({ preventScroll: true })
    })
    body.addEventListener('pointermove', (ev) => {
        const d = dragging
        if (!d || ev.pointerId !== d.pointer) return
        if (!d.moved && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < SLOP) return
        if (!d.moved) { d.moved = true; closePop(); if (d.e && !movable(d.e)) { dragging = null; return } body.classList.add('dragging'); if (d.node) d.node.classList.add('lifted') }
        if (view === 'month' || (d.e && whole(d.e))) {
            // by days: the cell under the pointer
            const cell = $$('.pc-month .cell, .pc-allday .cell', body).find((c) => { const r = c.getBoundingClientRect(); return ev.clientX >= r.left && ev.clientX < r.right && ev.clientY >= r.top && ev.clientY < r.bottom })
            $$('.cell.over', body).forEach((c) => c.classList.remove('over'))
            if (cell && d.mode === 'move') { cell.classList.add('over'); d.to = +cell.dataset.day / 1000 }
            return
        }
        if (!d.from) return
        // near the upper or lower edge of the hours, they scroll under the pointer
        const sc = body.querySelector('.pc-scroll'), box = sc.getBoundingClientRect()
        if (ev.clientY > box.bottom - 24) sc.scrollTop += 14; else if (ev.clientY < box.top + 24) sc.scrollTop -= 14
        const p = at(ev.clientX, ev.clientY)
        if (d.mode === 'new') {
            const a = snap(Math.min(d.from.minutes, p.minutes)), b = Math.max(a + SNAP, snap(Math.max(d.from.minutes, p.minutes)))
            d.start = d.from.day + a * 60; d.end = d.from.day + b * 60
            ghost(d.from.col, d.start, d.end, tt('（没有标题）', '(No title)'))
        } else if (d.mode === 'move') {
            const length = d.e.end - d.e.start
            d.start = p.day + snap((p.minutes * 60 - d.grab) / 60) * 60
            d.start = Math.max(p.day, Math.min(p.day + DAY - SNAP * 60, d.start)); d.end = d.start + length
            ghost(p.col, d.start, Math.min(d.end, p.day + DAY), d.e.title)
        } else if (d.mode === 'size') {
            const day = Math.floor((d.e.start - d.from.day) / DAY) * DAY + d.from.day
            d.start = d.e.start; d.end = Math.max(d.e.start + SNAP * 60, day + snap(p.minutes) * 60)
            ghost(d.from.col, Math.max(d.start, d.from.day), d.end, d.e.title)
        }
    })
    const finish = (ev) => {
        const d = dragging
        if (!d || ev.pointerId !== d.pointer) return
        dragging = null
        body.classList.remove('dragging')
        $$('.cell.over', body).forEach((c) => c.classList.remove('over'))
        if (d.node) d.node.classList.remove('lifted')
        if (ev.type === 'pointercancel') { $$('.ghost', body).forEach((g) => g.remove()); return }
        if (!d.moved) {
            // a click: an entry's card, or a new entry where there was none
            if (d.e) return card(d.e, d.node)
            if (d.mode === 'cell') { const day = +d.cell.dataset.day / 1000; return quick(day, day + DAY, d.cell.getBoundingClientRect(), d.cell.querySelector('.num') || null) }
            const start = d.from.day + Math.floor(d.from.minutes / 30) * 30 * 60
            const g = ghost(d.from.col, start, start + 3600, tt('（没有标题）', '(No title)'))
            return quick(start, start + 3600, g.getBoundingClientRect(), null)
        }
        if (d.mode === 'new') { const g = body.querySelector('.ghost'); return quick(d.start, d.end, g ? g.getBoundingClientRect() : d.from.col.getBoundingClientRect(), null) }
        $$('.ghost', body).forEach((g) => g.remove())
        if (d.mode === 'move' && (view === 'month' || whole(d.e))) {
            if (d.to === undefined) return
            // to another day, at the same time of day
            const from = startOfDay(date(d.e.start)), shift = Math.round((d.to - secs(from)) / DAY)
            if (!shift) return
            const start = secs(plus(date(d.e.start), shift))
            return move(d.e, start, d.e.has_end === false ? null : start + (d.e.end - d.e.start))
        }
        if (d.start === undefined || (d.start === d.e.start && d.end === d.e.end)) return
        return d.mode === 'size' ? move(d.e, d.e.start, d.end) : move(d.e, d.start, d.e.has_end === false ? null : d.end)
    }
    body.addEventListener('pointerup', finish)
    body.addEventListener('pointercancel', finish)
    // the keyboard on an entry: Enter or Space opens its card
    body.addEventListener('keydown', (ev) => {
        const node = ev.target.closest && ev.target.closest('.pc-ev:not(.ghost)')
        if (!node || (ev.key !== 'Enter' && ev.key !== ' ')) return
        const e = entry(node)
        if (e) { ev.preventDefault(); card(e, node) }
    })
    body.addEventListener('focusin', (ev) => { const node = ev.target.closest && ev.target.closest('.pc-ev:not(.ghost)'); if (node) { const e = entry(node); if (e) chosen = e } })
}

async function budget() {
    const u = (await get('/api/agent/usage', { identity: app.identity.id })) || {}
    const d = u.today || {}, total = d.daily_budget || 0, reserve = d.reserve ?? 0, own = d.own_usd ?? 0
    const free = Math.max(0.01, total - reserve)
    const bar = $('.pc-budget i'); if (!bar) return
    bar.style.width = Math.min(100, (own / free) * 100) + '%'
    $('.pc-budget small').textContent = tt(`它主动用了 ${usd(own)} / ${usd(free)} · 给你留 ${usd(reserve)}`, `on its own: ${usd(own)} of ${usd(free)} · ${usd(reserve)} kept for you`)
}

// ── moving around, and the keys ──
function step(n) {
    const d = new Date(anchor)
    if (view === 'day') d.setDate(d.getDate() + n)
    else if (view === 'week') d.setDate(d.getDate() + 7 * n)
    else if (view === 'month') d.setMonth(d.getMonth() + n, 1)
    else d.setFullYear(d.getFullYear() + n)
    anchor = startOfDay(d)
    return load()
}
function show(next, day = null) {
    view = next; prefs.set('calendar.view', view)
    if (day !== null) anchor = startOfDay(new Date(day))
    loaded = false; draw()
    return load()
}
function create() {
    // from the button or the keyboard: the next whole hour of the day in view (today, when it is in view)
    const [from, to] = range(), now = new Date()
    const day = now >= from && now < to ? startOfDay(now) : startOfDay(view === 'day' ? anchor : from)
    const start = secs(day) + Math.min(23, (day.getTime() === startOfDay(now).getTime() ? now.getHours() + 1 : 9)) * 3600
    form({ start, end: start + 3600 })
}
async function goTo() {
    const text = await ask({ title: tt('去哪一天', 'Go to a date'), label: tt('日期', 'Date'), value: local(anchor).slice(0, 10), yes: tt('去', 'Go'), note: tt('写成 年-月-日，比如 2026-12-24。', 'As year-month-day, for example 2026-12-24.') })
    if (!text) return
    const d = new Date(`${text}T00:00`)
    if (Number.isNaN(d.getTime())) return toast(tt('这不是一个日期。', 'That is not a date.'), { error: true })
    anchor = startOfDay(d)
    return load()
}

// Esc: the small box first, then the search.
export function escape() {
    if (closePop(true)) return true
    const find = $('.pc-find')
    if (find && (query || document.activeElement === find)) { find.value = ''; query = ''; found = null; find.blur(); draw(); return true }
    return false
}
// What each of the calendar's shortcuts (keys.js, where: 'calendar') does.
const KEYS = {
    'cal-day': () => show('day'), 'cal-week': () => show('week'), 'cal-month': () => show('month'), 'cal-year': () => show('year'),
    'cal-today': () => { anchor = startOfDay(new Date()); return load() },
    'cal-next': () => step(1), 'cal-previous': () => step(-1), 'cal-go': goTo, 'cal-create': create, 'cal-undo': undoLast,
    'cal-refresh': () => { found = null; return query ? search() : load() },
    'cal-search': () => { const f = $('.pc-find'); f.focus(); f.select() },
    'cal-open': () => { const node = chosen && nodeOf(chosen); if (node) card(chosen, node) },
    'cal-edit': () => {
        if (!chosen) return
        if (!mine(chosen)) return KEYS['cal-open']() // what was done is a record: its card is all there is
        const e = chosen; closePop()
        form({ ...e, edit: e })
    },
    'cal-delete': () => {
        if (!chosen) return
        if (!mine(chosen)) return toast(tt('做过的事是记录，删不了。', 'What was done is a record and cannot be deleted.'))
        const e = chosen; chosen = null; closePop()
        return remove(e)
    },
}

let closedBy = null // the press that closed a small box: it does not also make a new entry
export function actions(given, { blocked }) {
    app = given
    on('cal-create', create)
    on('cal-today', KEYS['cal-today'])
    on('cal-step', (n) => step(+n.dataset.arg))
    on('cal-month', (n) => { const d = new Date(anchor); d.setMonth(d.getMonth() + +n.dataset.arg, 1); anchor = startOfDay(d); return load() })
    on('cal-view', (n) => show(n.dataset.arg))
    on('cal-day', (n) => show('day', +n.dataset.arg))
    on('cal-month-open', (n) => show('month', +n.dataset.arg))
    on('cal-goto', (n) => { anchor = startOfDay(new Date(+n.dataset.arg)); return load() })
    on('cal-refresh', KEYS['cal-refresh'])
    on('cal-hit', async (n) => {
        const e = ((found && found.entries) || []).find((x) => String(x.id) === n.dataset.arg && String(x.start) === n.dataset.start)
        if (!e) return
        $('.pc-find').value = ''; query = ''
        await show('day', e.start * 1000)
        const node = nodeOf(e)
        if (node) { node.scrollIntoView({ block: 'center' }); card(entries.find((x) => String(x.id) === String(e.id) && x.start === e.start) || e, node) }
    })
    // a press anywhere outside the small box closes it
    document.addEventListener('pointerdown', (ev) => { closedBy = pop && !pop.contains(ev.target) && closePop() ? ev : null }, true)
    // the calendar's own keys, while it is in view and nothing else has the keyboard
    document.addEventListener('keydown', (ev) => {
        if (!app || app.view !== 'calendar' || app.section || ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing || ev.keyCode === 229 || blocked()) return
        const t = ev.target
        if (t && t.closest && t.closest('input:not([type="checkbox"]), textarea, select, [contenteditable]')) return // typing is typing
        const key = meant(ev, 'calendar')
        if (!key) return
        // Enter and Space on a button are the button's; in a small box only what acts on its entry
        if (key.id === 'cal-open' && ev.key === 'Enter') return
        if (pop && !['cal-edit', 'cal-delete'].includes(key.id)) return
        ev.preventDefault()
        KEYS[key.id]()
    })
}
