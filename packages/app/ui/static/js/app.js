// The app: the left column (New chat, Calendar, the chats, Settings and the identity), the
// chat with its title bar, records, timeline and composer, the tools rail and side panel. It
// follows the identity's life by polling the host; with the page closed the life goes on.
import { get, post, failed } from './api.js'
import { esc, tt, when, usd, setLanguage, modelName } from './i18n.js'
import { $, dialog, closeDialog, tips, toast } from './ui.js'
import { rows } from './chat.js'
import * as panel from './panel.js'
import * as timeline from './timeline.js'
import * as settings from './settings.js'
import * as calendar from './calendar.js'
import * as onboarding from './onboarding.js'
import * as update from './update.js'
import * as titlebar from './titlebar.js'

const POLL_MS = 1500

const app = window.harnessApp = {
    identity: { id: null, name: '' }, identities: [], life: { places: [], busy: [] }, chats: [], chat: 'main',
    records: {}, meta: {}, last: {}, usage: {}, model: '', view: 'chat', section: null, approvals: [], summary: null,
    showTimeline: false, find: '',
}

function theme(choice) {
    const system = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
    document.documentElement.dataset.theme = choice === 'light' || choice === 'dark' ? choice : system
}

// ── the frame ──
function frame() {
    document.body.innerHTML = `
<div class="app" data-view="chat">
<aside class="pg-side">
  <div class="pg-top"><span class="pg-mode">The Harness</span><button class="pg-ic bell" data-bell aria-label="${tt('等你批准', 'Waiting for you')}" data-tip="${tt('等你批准', 'Waiting for you')}">◔</button><button class="pg-ic" data-find aria-label="${tt('找对话', 'Find a chat')}" data-tip="${tt('找对话', 'Find a chat')}">⌕</button><button class="pg-ic" data-hide aria-label="${tt('收起', 'Hide')}" data-tip="${tt('收起', 'Hide')}">◧</button></div>
  <button class="pg-new" data-new>✎ ${tt('新对话', 'New chat')}</button>
  <button class="pg-new cal" data-cal>▦ ${tt('日历', 'Calendar')}</button>
  <input class="pg-find" placeholder="${tt('找对话', 'Find a chat')}">
  <div class="pg-lhead"><span>${tt('对话', 'Chats')}</span><span></span></div>
  <div class="pg-list"></div>
  <div class="pg-foot"><div class="pg-upd" hidden></div><button class="set" data-settings>⚙ ${tt('设置', 'Settings')}</button>
    <button class="pg-me"><div class="pg-avatar"></div><div><b></b><small></small></div></button></div>
</aside>
<div class="pg-main">
  <section class="pg-chatarea">
    <header class="pg-bar"><button class="pg-ic menu" data-menu aria-label="${tt('对话', 'Chats')}">☰</button><span class="title"></span><span class="state"></span><span class="cost"></span><button class="pg-ic" data-timeline aria-label="${tt('时间线', 'Timeline')}" data-tip="${tt('时间线', 'Timeline')}">⧉</button></header>
    <div class="pg-thread"><div class="pg-feed"></div></div>
    <div class="tl" hidden></div>
    <form class="pg-compose"><textarea rows="1" placeholder="${tt('告诉它要做什么', 'Tell it what to do')}"></textarea>
      <div class="pg-tools"><span aria-hidden="true">＋</span><select class="pick ws" aria-label="${tt('在哪里做', 'Where to work')}"></select><button type="button" class="pick model" data-model></button><button class="send" aria-label="${tt('发送', 'Send')}">↑</button></div></form>
    <div class="pg-hint">${HINT()}</div>
  </section>
  <section class="pg-panel"><div class="pg-tabs"></div><div class="pg-pane"></div></section>
</div>
<nav class="pg-rail">${panel.railHtml()}</nav>
<section class="pc"></section>
<section class="pg-settings"><nav></nav><div class="pane"></div></section>
<div class="pg-idmenu"></div>
<div class="pg-layer"></div>
</div>`
    tips(document.body)
}

// ── the left column ──
function drawList() {
    const list = $('.pg-list'), q = app.find.toLowerCase()
    const busy = new Set(app.life.busy || [])
    list.innerHTML = app.chats.filter((c) => !q || (c.title || '').toLowerCase().includes(q)).map((c) => {
        const waiting = c.waiting === 'desktop' ? tt('等桌面', 'waiting for desktop') : c.waiting === 'approval' ? tt('等你批准', 'waits for you') : ''
        const on = app.view === 'chat' && c.chat === app.chat
        return `<button class="pg-chat${on ? ' on' : ''}${c.unread && !on ? ' unread' : ''}${c.busy || busy.has(c.chat) ? ' busy' : ''}${waiting ? ' waiting' : ''}${c.kind === 'earlier' ? ' earlier' : ''}" data-c="${esc(c.chat)}">`
            + `<b>${esc(title(c))}</b><small>${esc(waiting || when(c.updated))}</small><span class="dot"></span></button>`
    }).join('')
    $('.pg-new.cal').classList.toggle('on', app.view === 'calendar')
    const bell = $('[data-bell]'); bell.classList.toggle('ping', app.approvals.length > 0)
}
function title(c) {
    if (c.kind === 'main') return tt('主对话', 'Main conversation')
    return c.title || c.chat
}
function drawMe() {
    const me = app.identity, places = (app.life.places || []).length
    $('.pg-me .pg-avatar').textContent = (me.name || me.id || '?').slice(0, 1).toUpperCase()
    $('.pg-me b').textContent = me.name || me.id
    $('.pg-me small').textContent = `${me.id} · ${tt(`${places} 个环境`, `${places} place${places === 1 ? '' : 's'}`)} · ${tt('今天', '')}${usd((app.usage.today || {}).cost_usd)}${tt('', ' today')}`
}

// ── the chat ──
function drawBar() {
    const c = app.chats.find((x) => x.chat === app.chat) || { chat: app.chat, kind: 'new', title: app.chat }
    $('.pg-bar .title').textContent = title(c)
    const s = $('.pg-bar .state'), busy = (app.life.busy || []).includes(app.chat) || c.busy
    const wait = app.approvals.some((a) => a.chat === app.chat)
    s.className = 'state' + (busy ? ' busy' : wait ? ' wait' : '')
    s.textContent = app.life.paused ? tt('‖ 已暂停', '‖ paused') : busy ? tt('● 工作中', '● working') : wait ? tt('● 等你', '● waits for you') : tt('● 空闲', '● idle')
    $('.pg-bar .cost').textContent = usd((app.usage.today || {}).cost_usd)
    // the workspace picker only where the owner gives work: not in a place's own chat
    const ws = $('.pg-compose .ws'), place = c.kind === 'place' || c.kind === 'earlier'
    ws.hidden = place || !(app.life.places || []).length
    const choice = ws.value
    ws.innerHTML = (app.life.places || []).map((p) => `<option value="${esc(p.id)}">${esc(p.title || p.id)}</option>`).join('')
    if (choice) ws.value = choice
    $('.pg-compose textarea').disabled = c.kind === 'earlier'
    $('[data-model]').textContent = modelName(app.model) || tt('模型', 'model')
}

function drawFeed(stick) {
    const feed = $('.pg-feed'), near = stick || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80
    const recs = app.records[app.chat] || []
    const html = rows(recs, { name: app.identity.name, titles: Object.fromEntries(app.chats.map((c) => [c.chat, title(c)])) })
    if ((app.life.busy || []).includes(app.chat)) html.push(`<div class="pe think">${tt('思考中', 'thinking')}<b></b><b></b><b></b></div>`)
    // An empty main chat says how to begin: things to say, one click away.
    if (!html.length) html.push(app.chat === 'main'
        ? `<div class="pg-empty start"><b>${tt('说说你想让它做什么', 'Say what you want done')}</b>${onboarding.STARTERS().map((s) => `<button class="starter" data-starter="${esc(s)}">${esc(s)}</button>`).join('')}</div>`
        : `<div class="pg-empty">${tt('这里还没有记录。', 'Nothing here yet.')}</div>`)
    // only rows that are new or changed are drawn again (and rise in); the others stay as they are
    const old = feed.dataset.chat === app.chat ? feed._rows || [] : []
    let k = 0
    while (k < old.length && k < html.length && old[k] === html[k]) k++
    if (!old.length) feed.innerHTML = ''
    while (feed.children.length > k) feed.lastElementChild.remove()
    feed.insertAdjacentHTML('beforeend', html.slice(k).join(''))
    feed._rows = html; feed.dataset.chat = app.chat
    if (near) feed.scrollTop = feed.scrollHeight
    if (app.showTimeline) timeline.draw($('.tl'), recs)
}

async function pullChat(chat) {
    const after = app.last[chat] || 0
    const got = await get('/api/agent/chat', { identity: app.identity.id, chat, after })
    if (!got) return false
    app.meta[chat] = got.meta || {}
    if (!got.records.length) return false
    app.records[chat] = [...(app.records[chat] || []), ...got.records].slice(-800)
    app.last[chat] = got.records[got.records.length - 1].seq
    return true
}

async function openChat(chat) {
    app.view = 'chat'; app.chat = chat
    $('.app').dataset.view = 'chat'; $('.app').classList.remove('side-open')
    settings.closeSettings(app)
    await pullChat(chat)
    drawList(); drawBar(); drawFeed(true); panel.render(app)
    post('/api/agent/opened', { identity: app.identity.id, chat })
}
app.openChat = openChat

async function send(given) {
    const area = $('.pg-compose textarea'), text = (typeof given === 'string' ? given : area.value).trim()
    if (!text) return
    area.value = ''; grow(area)
    const ws = $('.pg-compose .ws')
    const r = await post('/api/agent/say', { identity: app.identity.id, chat: app.chat, text, ...(ws.hidden || !ws.value ? {} : { place: ws.value }) })
    if (!r.ok) { area.value = text; grow(area); toast([r.error || tt('没发出去', 'Not sent'), r.fix].filter(Boolean).join(' — ')); return }
    await tick()
}
app.say = send

// Under the composer: that no model is chosen yet, with the way to choose one (the first
// run was left for later, or the model stopped being usable).
app.modelHint = async () => {
    const status = await get('/api/app')
    const ready = !status || !status.llm || status.llm.ready
    const hint = $('.pg-hint')
    if (!hint) return
    hint.classList.toggle('warn', !ready)
    hint.innerHTML = ready ? esc(HINT())
        : `${esc(tt('还没有可用的模型，它现在答不了话。', 'No model is usable yet, so it cannot answer.'))} <button class="link" data-choose-model>${esc(tt('选一个模型', 'Choose a model'))}</button>`
}
const HINT = () => tt('它同时接着好几处。付款和发送前会先问你；登录由你来。', 'It is connected to several places at once. It asks you before paying or sending; logins stay yours.')

// The whole page could not start: what went wrong, what to do, and a way to try again.
function pageProblem(title, problem) {
    const p = problem || {}
    $('.pg-feed').innerHTML = `<div class="pg-empty problem"><b>${esc(title)}</b>${p.error ? `<span>${esc(p.error)}</span>` : ''}${p.fix ? `<span class="fix">${esc(p.fix)}</span>` : ''}${p.log ? `<small>${esc(p.log)}</small>` : ''}<button class="starter" data-reload>${esc(tt('重试', 'Try again'))}</button></div>`
}
function grow(area) { area.style.height = 'auto'; area.style.height = Math.min(180, area.scrollHeight) + 'px' }

// ── the identity ──
async function loadIdentity() {
    const rows = (await get('/api/agent/identities')) || []
    app.identities = Array.isArray(rows) ? rows : rows.identities || []
    const current = app.identities.find((i) => i.current) || app.identities[0]
    if (current) app.identity = { id: current.id, name: current.name || current.id }
}

function idMenu() {
    const m = $('.pg-idmenu')
    if (m.classList.contains('open')) { m.classList.remove('open'); return }
    const places = (app.life.places || []).length
    m.innerHTML = app.identities.map((i) => `<button class="id${i.id === app.identity.id ? ' on' : ''}" data-use="${esc(i.id)}"><span class="av">${esc((i.name || i.id).slice(0, 1).toUpperCase())}</span><span><b>${esc(i.name || i.id)}</b><small>${esc(i.id)}${i.id === app.identity.id ? ` · ${tt(`${places} 个环境`, `${places} places`)} · ${usd((app.usage.today || {}).cost_usd)} ${tt('今天', 'today')}` : ''}</small></span>${i.id === app.identity.id ? '<i>✓</i>' : ''}</button>`).join('')
        + `<hr>${update.menuItem()}<button class="act" data-new-id>＋ ${tt('新建身份', 'New identity')}</button><button class="act" data-import-id>⇣ ${tt('从 OpenClaw 或 Hermes 导入…', 'Import from OpenClaw or Hermes…')}</button>`
    m.classList.add('open')
}

async function useIdentity(id) {
    const r = await post('/api/agent/identity', { action: 'use', id })
    if (!r.ok) return toast(r.error)
    app.records = {}; app.last = {}; app.meta = {}; app.summary = null
    await loadIdentity(); await tick(); openChat('main')
}

function newIdentity() {
    const d = dialog(`<h5>${tt('新建身份', 'New identity')}</h5>
<label><span>${tt('显示名', 'Display name')}</span><input class="field" data-name></label>
<label><span>id</span><input class="field" data-id pattern="[A-Za-z0-9_-]+"></label>
<p class="note">${tt('id 是文件夹名，只能用英文字母、数字和连字符，建好后不能改；显示名随时能改。', 'The id names the folder: letters, digits and hyphens only, fixed once created. The display name can change any time.')}</p>
<label><span>${tt('从现有身份克隆', 'Clone from')}</span><select class="field" data-from><option value="">${tt('不克隆', 'none')}</option>${app.identities.map((i) => `<option value="${esc(i.id)}"${i.id === app.identity.id ? ' selected' : ''}>${esc(i.name)} (${esc(i.id)})</option>`).join('')}</select></label>
<div class="checks"><span class="ck on fixed">${tt('人设', 'Persona')}</span><span class="ck on fixed">${tt('技能和反应', 'Skills and reactions')}</span><span class="ck fixed">${tt('记忆（不带）', 'Memory (not copied)')}</span></div>
<div class="row"><span class="res"></span><button class="btn">${tt('创建', 'Create')}</button></div>`)
    const name = d.querySelector('[data-name]'), id = d.querySelector('[data-id]')
    name.oninput = () => { if (!id.dataset.touched) id.value = name.value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') }
    id.oninput = () => { id.dataset.touched = '1' }
    d.querySelector('.btn').onclick = async () => {
        if (!/^[A-Za-z0-9_-]+$/.test(id.value)) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${tt('id 只能用英文字母、数字和连字符', 'letters, digits and hyphens only')}</span>`; return }
        const from = d.querySelector('[data-from]').value
        const r = await post('/api/agent/identity', { action: 'new', id: id.value, name: name.value || id.value, ...(from ? { from } : {}) })
        if (!r.ok) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
        d.querySelector('.res').innerHTML = `<span class="c-done">✓ ${tt('已创建', 'created')} agents/${esc(id.value)}</span>`
        setTimeout(() => { closeDialog(); useIdentity(id.value) }, 700)
    }
}

// ── following the life ──
let ticking = false
async function tick() {
    if (ticking || !app.identity.id) return
    ticking = true
    try {
        const [life, chats, approvals] = await Promise.all([
            get('/api/agent/life', { identity: app.identity.id }),
            get('/api/agent/chats', { identity: app.identity.id }),
            get('/api/agent/approvals', { identity: app.identity.id }),
        ])
        if (life) app.life = life
        if (chats) app.chats = chats.chats || []
        app.approvals = (approvals && approvals.pending) || []
        const changed = app.view === 'chat' ? await pullChat(app.chat) : false
        drawList(); drawMe()
        if (app.view === 'chat') { drawBar(); if (changed || (life && (life.busy || []).length)) drawFeed() }
    } finally { ticking = false }
}
async function slow() {
    app.usage = (await get('/api/agent/usage', { identity: app.identity.id })) || {}
    const status = await get('/api/app')
    if (status && status.llm) app.model = status.llm.model || ''
    drawMe(); if (app.view === 'chat') drawBar()
}
app.refresh = async () => { await tick(); await slow() }

// ── events ──
function wire() {
    const root = $('.app')
    root.addEventListener('click', async (e) => {
        const t = e.target
        if (!t.closest('.pg-idmenu') && !t.closest('.pg-me')) $('.pg-idmenu').classList.remove('open')
        const chat = t.closest('.pg-chat'); if (chat) return openChat(chat.dataset.c)
        if (t.closest('[data-new]')) { const r = await post('/api/agent/new_chat', { identity: app.identity.id, title: tt('新对话', 'New chat') }); if (r.ok) { await tick(); openChat(r.data.chat) } return }
        if (t.closest('[data-cal]')) { app.view = 'calendar'; root.dataset.view = 'calendar'; root.classList.remove('side-open'); settings.closeSettings(app); drawList(); return calendar.open(app) }
        if (t.closest('[data-settings]')) return settings.open(app, app.section || 'general')
        if (t.closest('[data-close-settings]')) return settings.closeSettings(app)
        const sec = t.closest('[data-sec]'); if (sec) return settings.open(app, sec.dataset.sec)
        const open = t.closest('[data-open-settings]'); if (open) return settings.open(app, open.dataset.openSettings)
        if (t.closest('.pg-me')) return idMenu()
        if (t.closest('[data-upd-go]')) return update.restart(app)
        if (t.closest('[data-upd-interrupt]')) return update.restart(app, true)
        if (t.closest('[data-upd-cancel]')) return update.cancel(app)
        if (t.closest('[data-upd-hide]')) return update.dismiss(app)
        if (t.closest('[data-upd-check]')) return update.check(app)
        const use = t.closest('[data-use]'); if (use) { $('.pg-idmenu').classList.remove('open'); return use.dataset.use === app.identity.id ? null : useIdentity(use.dataset.use) }
        if (t.closest('[data-new-id]')) { $('.pg-idmenu').classList.remove('open'); return newIdentity() }
        if (t.closest('[data-import-id]')) { $('.pg-idmenu').classList.remove('open'); return onboarding.importDialog(app) }
        const ap = t.closest('[data-approve], [data-reject]')
        if (ap) {
            const code = ap.dataset.approve || ap.dataset.reject
            const r = await post('/api/agent/approvals', { identity: app.identity.id, code, accept: !!ap.dataset.approve })
            if (!r.ok) toast(r.error || ''); return tick()
        }
        if (t.closest('[data-dismiss]')) { t.closest('.pe').remove(); return }
        if (t.closest('[data-bell]')) { if (app.approvals.length) return openChat(app.approvals[0].chat || 'main'); return toast(tt('没有等你批准的事', 'Nothing waits for you')) }
        if (t.closest('[data-find]')) { const f = $('.pg-find'); f.classList.toggle('on'); if (f.classList.contains('on')) f.focus(); else { app.find = ''; f.value = ''; drawList() } return }
        if (t.closest('[data-hide]') || t.closest('[data-menu]')) { root.classList.toggle('side-open'); return }
        if (t.closest('[data-timeline]')) { app.showTimeline = !app.showTimeline; $('.tl').hidden = !app.showTimeline; t.closest('[data-timeline]').classList.toggle('on', app.showTimeline); return drawFeed() }
        if (t.closest('[data-model]')) return settings.open(app, 'model')
        if (t.closest('[data-choose-model]')) return onboarding.modelDialog(app, { first: false })
        if (t.closest('[data-reload]')) return location.reload()
        const starter = t.closest('[data-starter]'); if (starter) return send(starter.dataset.starter)
        const rail = t.closest('[data-r]'); if (rail) { const cur = $('.pg-panel').classList.contains('open') && rail.classList.contains('on'); return cur ? panel.close(app, rail.dataset.r) : panel.open(app, rail.dataset.r) }
        const tab = t.closest('[data-close]'); if (tab) return panel.close(app, tab.dataset.close)
        const tb = t.closest('[data-tab]'); if (tb) return panel.open(app, tb.dataset.tab)
    })
    $('.pg-find').oninput = (e) => { app.find = e.target.value; drawList() }
    const area = $('.pg-compose textarea')
    area.addEventListener('input', () => grow(area))
    area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() } })
    $('.pg-compose').addEventListener('submit', (e) => { e.preventDefault(); send() })
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return
        if (closeDialog()) return
        if ($('.pg-idmenu').classList.contains('open')) return $('.pg-idmenu').classList.remove('open')
        if (app.section) return settings.closeSettings(app)
    })
}

async function main() {
    const values = ((await get('/api/app/settings')) || {}).values || {}
    setLanguage((values.general || {}).language)
    theme((values.general || {}).theme)
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => theme((values.general || {}).theme))
    frame(); titlebar.start(); wire()
    await loadIdentity()
    if (!app.identity.id) {
        // No identity to show: the host says why (a package it left out, or the request's own failure).
        const host = (await get('/api/host')) || {}
        const left = Object.values(host.problems || {})
        return pageProblem(tt('它现在起不来', 'It could not start'), left.length ? { error: left.join(' · ') }
            : failed.get('/api/agent/identities') || { error: tt('后台没有给出身份。', 'The host gave no identity.'), fix: tt('在终端运行 harness doctor 查看原因。', 'Run harness doctor in a terminal to see why.') })
    }
    await tick(); await slow()
    const view = new URLSearchParams(location.search).get('view')
    const chat = new URLSearchParams(location.search).get('chat')
    await openChat(chat || 'main')
    if (view === 'calendar') $('[data-cal]').click()
    else if (view && view.startsWith('settings')) settings.open(app, view.split(':')[1] || 'general')
    setInterval(tick, POLL_MS); setInterval(slow, 10000)
    onboarding.start(app)
    update.start(app)
}

main()
