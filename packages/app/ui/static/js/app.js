// The app: the left column (New chat, Calendar, the chats, Settings and the identity), the
// chat with its title bar, records, timeline and composer, the tools rail and side panel. It
// follows the identity's life by polling the host; with the page closed the life goes on.
//
// The window is Hermes Desktop's: chats on the left, the chat in the middle, tools on the
// right, Settings over all of it, everything reachable from the keyboard (keys.js) and the
// command palette (palette.js). The calendar's entry in the left column, the timeline under
// the chat and the tools rail are the plan's own design.
import { get, post, failed, onReach, unreachable } from './api.js'
import { esc, tt, when, usd, setLanguage, modelName, SECTIONS, sectionName } from './i18n.js'
import { $, ic, tips, toast, said, dialog, closeDialog, dialogOpen, wireDialogs, wireActions, on, press, menu, closeMenu, menuOpen, loading, problem } from './ui.js'
import { icon } from './icons.js'
import { prefs } from './prefs.js'
import * as keys from './keys.js'
import { openPalette, closePalette, paletteOpen, openShortcuts } from './palette.js'
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
    showTimeline: false, find: '', values: {},
}

function theme(choice) {
    const system = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
    document.documentElement.dataset.theme = choice === 'light' || choice === 'dark' ? choice : system
}
const narrow = () => matchMedia('(max-width: 760px)').matches

// ── the frame ──
function frame() {
    document.body.innerHTML = `
<div class="app${prefs.get('side.hidden', false) ? ' side-hidden' : ''}" data-view="chat">
<aside class="pg-side" aria-label="${tt('对话', 'Chats')}">
  <div class="pg-top"><span class="pg-mode">The Harness</span>${ic('bell', tt('等你批准', 'Waiting for you'), { act: 'approvals-next', cls: 'bell' })}${ic('search', tt('搜索对话', 'Search chats'), { act: 'chats-search', keys: keys.keysOf('search-chats') })}${ic('sidebar', tt('收起左栏', 'Hide the sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar') })}</div>
  <button type="button" class="pg-new" data-act="chat-new" data-tip="${tt('新对话', 'New chat')}" data-keys="${keys.keysOf('new-chat')}">${icon('edit')}<span>${tt('新对话', 'New chat')}</span></button>
  <button type="button" class="pg-new cal" data-act="calendar">${icon('calendar')}<span>${tt('日历', 'Calendar')}</span></button>
  <input class="pg-find" type="search" placeholder="${tt('搜索对话', 'Search chats')}" aria-label="${tt('搜索对话', 'Search chats')}">
  <div class="pg-lhead"><span>${tt('对话', 'Chats')}</span><span></span></div>
  <nav class="pg-list" aria-label="${tt('对话', 'Chats')}"></nav>
  <div class="pg-foot"><div class="pg-upd" hidden></div><button type="button" class="set" data-act="settings" data-tip="${tt('设置', 'Settings')}" data-keys="${keys.keysOf('settings')}">${icon('settings')}<span>${tt('设置', 'Settings')}</span></button>
    <button type="button" class="pg-me" data-act="identity-menu" aria-label="${tt('切换身份', 'Switch identity')}"><div class="pg-avatar"></div><div><b></b><small></small></div></button></div>
</aside>
<div class="pg-main">
  <section class="pg-chatarea" aria-label="${tt('对话', 'Chat')}">
    <header class="pg-bar">${ic('sidebar', tt('展开左栏', 'Show the sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar'), cls: 'show-side' })}<span class="title"></span><span class="state"></span><span class="cost"></span>${ic('timeline', tt('时间线', 'Timeline'), { act: 'timeline' })}</header>
    <div class="pg-reach" hidden></div>
    <div class="pg-thread"><div class="pg-feed" tabindex="-1">${loading()}</div></div>
    <div class="tl" hidden></div>
    <form class="pg-compose"><textarea rows="1" placeholder="${tt('告诉它要做什么', 'Tell it what to do')}" aria-label="${tt('给它的消息', 'Message to it')}"></textarea>
      <div class="pg-tools"><select class="pick ws" aria-label="${tt('在哪里做', 'Where to work')}"></select><button type="button" class="pick model" data-act="model"></button><button class="send" aria-label="${tt('发送', 'Send')}" data-tip="${tt('发送', 'Send')}" data-keys="${keys.label('enter')}">${icon('send')}</button></div></form>
    <div class="pg-hint">${HINT()}</div>
  </section>
  <section class="pg-panel" aria-label="${tt('工具', 'Tools')}"><div class="pg-tabs" role="tablist"></div><div class="pg-pane"></div></section>
</div>
<nav class="pg-rail" aria-label="${tt('工具', 'Tools')}">${panel.railHtml()}</nav>
<section class="pc"></section>
<section class="pg-settings" aria-label="${tt('设置', 'Settings')}"><nav></nav><div class="pane"></div></section>
<div class="pg-layer"></div>
</div>`
    wireDialogs()
    titlebar.start()
    wire()
    reach(unreachable())
}

// The host does not answer: say so over the chat, and keep asking (the polling goes on).
function reach(down) {
    const bar = $('.pg-reach'); if (!bar) return
    bar.hidden = !down
    bar.innerHTML = down ? `${icon('alert')}<span><b>${esc(down.error)}</b> ${esc(down.fix)}</span><button type="button" class="b" data-act="refresh">${esc(tt('重试', 'Try again'))}</button>` : ''
}

// ── the left column ──
function drawList() {
    const list = $('.pg-list'), q = app.find.toLowerCase()
    const busy = new Set(app.life.busy || [])
    list.innerHTML = app.chats.filter((c) => !q || (c.title || '').toLowerCase().includes(q)).map((c) => {
        const waiting = c.waiting === 'desktop' ? tt('等桌面', 'waiting for desktop') : c.waiting === 'approval' ? tt('等你批准', 'waits for you') : ''
        const on = app.view === 'chat' && c.chat === app.chat
        return `<button type="button" class="pg-chat${on ? ' on' : ''}${c.unread && !on ? ' unread' : ''}${c.busy || busy.has(c.chat) ? ' busy' : ''}${waiting ? ' waiting' : ''}${c.kind === 'earlier' ? ' earlier' : ''}" data-act="chat-open" data-arg="${esc(c.chat)}"${on ? ' aria-current="page"' : ''}>`
            + `<b>${esc(title(c))}</b><small>${esc(waiting || when(c.updated))}</small><span class="dot"></span></button>`
    }).join('')
    $('.pg-new.cal').classList.toggle('on', app.view === 'calendar')
    const bell = $('.pg-ic.bell'); bell.classList.toggle('ping', app.approvals.length > 0)
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
    $('.pick.model').textContent = modelName(app.model) || tt('模型', 'model')
}

function drawFeed(stick) {
    const feed = $('.pg-feed'), near = stick || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80
    const recs = app.records[app.chat] || []
    const html = rows(recs, { name: app.identity.name, titles: Object.fromEntries(app.chats.map((c) => [c.chat, title(c)])) })
    if ((app.life.busy || []).includes(app.chat)) html.push(`<div class="pe think">${tt('思考中', 'thinking')}<b></b><b></b><b></b></div>`)
    // An empty main chat says how to begin: things to say, one click away.
    if (!html.length) html.push(app.chat === 'main'
        ? `<div class="pg-empty start"><b>${tt('说说你想让它做什么', 'Say what you want done')}</b>${onboarding.STARTERS().map((s) => `<button type="button" class="starter" data-act="starter" data-arg="${esc(s)}">${esc(s)}</button>`).join('')}</div>`
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
    if (!r.ok) { area.value = text; grow(area); said(r, tt('没发出去', 'Not sent')); return }
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
        : `${esc(tt('还没有可用的模型，它现在答不了话。', 'No model is usable yet, so it cannot answer.'))} <button type="button" class="link" data-act="model-choose">${esc(tt('选一个模型', 'Choose a model'))}</button>`
}
const HINT = () => tt('它同时接着好几处。付款和发送前会先问你；登录由你来。', 'It is connected to several places at once. It asks you before paying or sending; logins stay yours.')

function grow(area) { area.style.height = 'auto'; area.style.height = Math.min(180, area.scrollHeight) + 'px' }

// ── the views ──
function openCalendar() {
    const root = $('.app')
    app.view = 'calendar'; root.dataset.view = 'calendar'; root.classList.remove('side-open')
    settings.closeSettings(app); drawList()
    return calendar.open(app)
}
function sideToggle() {
    const root = $('.app')
    if (narrow()) { root.classList.toggle('side-open'); return }
    const hidden = root.classList.toggle('side-hidden')
    prefs.set('side.hidden', hidden)
    if (hidden && root.querySelector('.pg-side').contains(document.activeElement)) $('.pg-compose textarea').focus()
}
function searchChats() {
    const root = $('.app')
    if (narrow()) root.classList.add('side-open')
    else if (root.classList.contains('side-hidden')) sideToggle()
    const f = $('.pg-find')
    f.classList.add('on'); f.focus(); f.select()
}
async function newChat() {
    const r = await post('/api/agent/new_chat', { identity: app.identity.id, title: tt('新对话', 'New chat') })
    if (!r.ok) return said(r)
    await tick(); await openChat(r.data.chat)
    $('.pg-compose textarea').focus()
}
function toggleTimeline() {
    app.showTimeline = !app.showTimeline
    $('.tl').hidden = !app.showTimeline
    const b = $('[data-act="timeline"]'); b.classList.toggle('on', app.showTimeline); b.setAttribute('aria-pressed', app.showTimeline)
    drawFeed()
}

// ── the identity ──
async function loadIdentity() {
    const rows = (await get('/api/agent/identities')) || []
    app.identities = Array.isArray(rows) ? rows : rows.identities || []
    const current = app.identities.find((i) => i.current) || app.identities[0]
    if (current) app.identity = { id: current.id, name: current.name || current.id }
}

function idMenu(anchor) {
    const places = (app.life.places || []).length
    const upd = update.menuItem(app)
    menu(anchor, [
        { head: tt('身份', 'Identities') },
        ...app.identities.map((i) => ({ label: i.name || i.id, checked: i.id === app.identity.id,
            sub: i.id === app.identity.id ? `${i.id} · ${tt(`${places} 个环境`, `${places} place${places === 1 ? '' : 's'}`)} · ${usd((app.usage.today || {}).cost_usd)} ${tt('今天', 'today')}` : i.id,
            run: () => { if (i.id !== app.identity.id) useIdentity(i.id) } })),
        '-', upd,
        { label: tt('新建身份…', 'New identity…'), icon: 'plus', run: newIdentity },
        { label: tt('从 OpenClaw 或 Hermes 导入…', 'Import from OpenClaw or Hermes…'), icon: 'latest', run: () => onboarding.importDialog(app) },
    ], { side: 'top', label: tt('身份', 'Identities') })
}

async function useIdentity(id) {
    const r = await post('/api/agent/identity', { action: 'use', id })
    if (!r.ok) return said(r)
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
<div class="row"><span class="res"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('创建', 'Create')}</button></div>`)
    const name = d.querySelector('[data-name]'), id = d.querySelector('[data-id]'), res = d.querySelector('.res')
    name.oninput = () => { if (!id.dataset.touched) id.value = name.value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') }
    id.oninput = () => { id.dataset.touched = '1' }
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        if (!/^[A-Za-z0-9_-]+$/.test(id.value)) { res.innerHTML = `<span class="c-failed">✕ ${tt('id 只能用英文字母、数字和连字符', 'letters, digits and hyphens only')}</span>`; id.focus(); return }
        const from = d.querySelector('[data-from]').value
        const r = await post('/api/agent/identity', { action: 'new', id: id.value, name: name.value || id.value, ...(from ? { from } : {}) })
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog(); toast(tt(`已创建 ${id.value}`, `Created ${id.value}`))
        await useIdentity(id.value)
    })
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
    if (!app.identity.id) return
    app.usage = (await get('/api/agent/usage', { identity: app.identity.id })) || app.usage
    const status = await get('/api/app')
    if (status && status.llm) app.model = status.llm.model || ''
    drawMe(); if (app.view === 'chat') drawBar()
}
app.refresh = async () => { await tick(); await slow() }

// A setting changed on a settings page or from the palette: what shows it at once.
app.applied = (section, key, value) => {
    app.values[section] = { ...(app.values[section] || {}), [key]: value }
    if (section !== 'general') return
    if (key === 'theme') theme(value)
    if (key === 'language') { setLanguage(value); redraw() }
}
async function setGeneral(key, value) {
    const r = await post('/api/app/settings', { general: { [key]: value } })
    if (!r.ok) return said(r)
    app.applied('general', key, value)
}

// The frame again in the page's language, on the view that was open.
function redraw() {
    const section = app.section
    frame()
    drawList(); drawMe(); drawBar(); drawFeed(true); panel.render(app)
    if (app.view === 'calendar') openCalendar()
    if (section) settings.open(app, section)
    app.modelHint(); update.draw(app)
}

// ── the palette: every place and action by name ──
function commands() {
    const go = tt('前往', 'Go to'), act = tt('操作', 'Action'), look = tt('外观', 'Appearance')
    const tool = (id) => ({ title: tt(`打开${panel.toolName(id)}`, `Open ${panel.toolName(id)}`), group: tt('工具', 'Tools'), icon: id, run: () => { if (app.view !== 'chat') openChat(app.chat); panel.open(app, id) } })
    const themes = [['system', '跟随系统', 'follow the system'], ['light', '亮色', 'light'], ['dark', '暗色', 'dark']]
    const languages = [['system', '跟随系统', 'follow the system'], ['zh', '中文', '中文'], ['en', 'English', 'English']]
    return [
        { title: tt('新对话', 'New chat'), group: act, icon: 'edit', keys: keys.keysOf('new-chat'), run: newChat },
        { title: tt('日历', 'Calendar'), group: go, icon: 'calendar', run: openCalendar },
        { title: tt('设置', 'Settings'), group: go, icon: 'settings', keys: keys.keysOf('settings'), run: () => settings.open(app, app.section || 'general') },
        ...SECTIONS.map(([id]) => ({ title: `${tt('设置', 'Settings')} › ${sectionName(id)}`, group: go, icon: 'settings', run: () => settings.open(app, id) })),
        { title: tt('搜索对话', 'Search chats'), group: act, icon: 'search', keys: keys.keysOf('search-chats'), run: searchChats },
        { title: tt('收起或展开左栏', 'Hide or show the sidebar'), group: act, icon: 'sidebar', keys: keys.keysOf('sidebar'), run: sideToggle },
        { title: tt('打开或收起工具面板', 'Open or close the tools panel'), group: act, icon: 'context', keys: keys.keysOf('tools'), run: () => panel.toggle(app) },
        ...panel.RAIL.map(([id]) => tool(id)),
        { title: tt('显示或隐藏时间线', 'Show or hide the timeline'), group: act, icon: 'timeline', run: toggleTimeline },
        { title: tt('换模型…', 'Change the model…'), group: act, icon: 'model', run: () => settings.open(app, 'model') },
        { title: tt('快捷键', 'Keyboard shortcuts'), group: go, icon: 'keyboard', keys: keys.keysOf('shortcuts'), run: openShortcuts },
        ...themes.map(([id, zh, en]) => ({ title: tt(`主题：${zh}`, `Theme: ${en}`), group: look, also: 'theme dark light 主题', run: () => setGeneral('theme', id) })),
        ...languages.map(([id, zh, en]) => ({ title: tt(`语言：${zh}`, `Language: ${en}`), group: look, also: 'language 语言', run: () => setGeneral('language', id) })),
        ...app.identities.filter((i) => i.id !== app.identity.id).map((i) => ({ title: tt(`切换到身份 ${i.name || i.id}`, `Switch to identity ${i.name || i.id}`), group: tt('身份', 'Identity'), also: i.id, run: () => useIdentity(i.id) })),
        ...app.chats.map((c) => ({ title: title(c), group: tt('对话', 'Chat'), also: c.chat, run: () => openChat(c.chat) })),
    ]
}

// ── events ──
function actions() {
    on('chat-open', (n) => openChat(n.dataset.arg))
    on('chat-new', newChat)
    on('calendar', openCalendar)
    on('settings', (n) => settings.open(app, n.dataset.arg || app.section || 'general'))
    on('settings-close', () => settings.closeSettings(app))
    on('identity-menu', (n) => idMenu(n))
    on('approvals-next', () => (app.approvals.length ? openChat(app.approvals[0].chat || 'main') : toast(tt('没有等你批准的事', 'Nothing waits for you'))))
    on('chats-search', () => { const f = $('.pg-find'); if (f.classList.contains('on') && !f.value) { f.classList.remove('on'); return } searchChats() })
    on('side-toggle', sideToggle)
    on('timeline', toggleTimeline)
    on('model', () => settings.open(app, 'model'))
    on('model-choose', () => onboarding.modelDialog(app, { first: false }))
    on('reload', () => location.reload())
    on('refresh', () => app.refresh())
    on('starter', (n) => send(n.dataset.arg))
    on('tool', (n) => { const cur = $('.pg-panel').classList.contains('open') && n.classList.contains('on'); return cur ? panel.close(app, n.dataset.arg) : panel.open(app, n.dataset.arg) })
    on('tool-close', (n) => panel.close(app, n.dataset.arg))
    on('tool-tab', (n) => panel.open(app, n.dataset.arg))
    on('tools-toggle', () => panel.toggle(app))
    on('tool-retry', () => panel.render(app))
    on('update-go', () => update.restart(app))
    on('update-interrupt', () => update.restart(app, true))
    on('update-cancel', () => update.cancel(app))
    on('update-hide', () => update.dismiss(app))
    on('update-check', () => update.check(app))
    on('approve', (n) => answer(n.dataset.arg, true))
    on('decline', (n) => answer(n.dataset.arg, false))
    on('card-dismiss', (n) => n.closest('.pe').remove())
}
async function answer(code, accept) {
    const r = await post('/api/agent/approvals', { identity: app.identity.id, code, accept })
    if (!r.ok) said(r)
    return tick()
}

function shortcuts() {
    keys.bind('palette', () => openPalette(commands()))
    keys.bind('shortcuts', openShortcuts)
    keys.bind('settings', () => (app.section ? settings.closeSettings(app) : settings.open(app, 'general')))
    keys.bind('new-chat', newChat)
    keys.bind('sidebar', sideToggle)
    keys.bind('tools', () => { if (app.view === 'chat' && !app.section) panel.toggle(app) })
    keys.bind('search-chats', searchChats)
    keys.onEscape(10, closePalette)
    keys.onEscape(20, () => closeMenu(true))
    keys.onEscape(30, closeDialog)
    keys.onEscape(50, () => { const f = $('.pg-find'); if (document.activeElement !== f) return false; f.value = ''; app.find = ''; f.classList.remove('on'); drawList(); return true })
    keys.onEscape(60, () => { if (!app.section) return false; settings.closeSettings(app); return true })
    keys.onEscape(70, () => { const root = $('.app'); if (!root.classList.contains('side-open')) return false; root.classList.remove('side-open'); return true })
    // with a dialog, a menu or the palette open, the keys are theirs
    keys.start({ blocked: (id) => (dialogOpen() || menuOpen() || paletteOpen()) && id !== 'palette' })
}

// what hangs on the frame's own elements (wired again when the frame is drawn again)
function wire() {
    $('.pg-find').oninput = (e) => { app.find = e.target.value; drawList() }
    const area = $('.pg-compose textarea')
    area.addEventListener('input', () => grow(area))
    area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send() } })
    $('.pg-compose').addEventListener('submit', (e) => { e.preventDefault(); send() })
}

async function main() {
    const values = ((await get('/api/app/settings')) || {}).values || {}
    app.values = values
    setLanguage((values.general || {}).language)
    theme((values.general || {}).theme)
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => theme((app.values.general || {}).theme))
    actions(); shortcuts()
    wireActions(document); tips(document)
    onReach(reach)
    frame()
    await loadIdentity()
    if (!app.identity.id) {
        // No identity to show: the host says why (a package it left out, or the request's own failure).
        const host = (await get('/api/host')) || {}
        const left = Object.values(host.problems || {})
        $('.pg-feed').innerHTML = problem(left.length ? { error: left.join(' · ') }
            : failed.get('/api/agent/identities') || { error: tt('后台没有给出身份。', 'The host gave no identity.'), fix: tt('在终端运行 harness doctor 查看原因。', 'Run harness doctor in a terminal to see why.') },
        { title: tt('它现在起不来', 'It could not start'), retry: 'reload' })
        return
    }
    await tick(); await slow()
    const view = new URLSearchParams(location.search).get('view')
    const chat = new URLSearchParams(location.search).get('chat')
    await openChat(chat || 'main')
    if (view === 'calendar') openCalendar()
    else if (view && view.startsWith('settings')) settings.open(app, view.split(':')[1] || 'general')
    setInterval(tick, POLL_MS); setInterval(slow, 10000)
    onboarding.start(app)
    update.start(app)
}

main()
