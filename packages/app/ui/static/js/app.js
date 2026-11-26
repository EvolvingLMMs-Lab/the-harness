// The app: the left column (sidebar.js), the chat with its title bar, transcript (thread.js),
// timeline, composer (composer.js) and status bar (statusbar.js), the tools rail and side panel
// (panel.js), Settings and the calendar over them. This file holds what they share: the state
// read from the host, how it is kept up to date, and the frame's own actions and keys.
//
// The window is Hermes Desktop's: chats on the left, the chat in the middle, tools on the
// right, Settings over all of it, everything reachable from the keyboard (keys.js) and the
// command palette (palette.js). The calendar's entry in the left column, the timeline under
// the chat and the tools rail are the plan's own design.
//
// Following the life. The page asks the host; nothing is pushed to it. The host's event stream
// (/api/stream) carries one task run's trace, not an identity's chats, so it could only be a
// second source beside the chat's record; the record (GET /api/agent/chat?after=N, which also
// carries the reply being written) stays the one source, asked often enough to feel immediate:
// every 250 ms while the open chat is at work or something was just sent, every 1.5 s
// otherwise. The list, the life and the approvals are asked every 1.5 s; usage and the models
// every 10 s. With the page closed the life goes on.
import { get, post, failed, onReach, unreachable, agent } from './api.js'
import { esc, tt, usd, setLanguage, SECTIONS, sectionName } from './i18n.js'
import { $, ic, tips, toast, said, dialog, closeDialog, dialogOpen, wireDialogs, wireActions, on, press, menu, closeMenu, menuOpen, loading, problem, copy } from './ui.js'
import { icon } from './icons.js'
import { prefs } from './prefs.js'
import * as keys from './keys.js'
import { openPalette, closePalette, paletteOpen, openShortcuts } from './palette.js'
import { plainError } from './chat.js'
import * as sidebar from './sidebar.js'
import * as thread from './thread.js'
import * as composer from './composer.js'
import * as statusbar from './statusbar.js'
import * as panel from './panel.js'
import * as settings from './settings.js'
import * as calendar from './calendar.js'
import * as onboarding from './onboarding.js'
import * as update from './update.js'
import * as titlebar from './titlebar.js'

// Milliseconds between two reads of the open chat: while it is at work, and otherwise; of the
// list, the life and the approvals; of usage and the models.
const LIVE_MS = 250, IDLE_MS = 1500, LIST_MS = 1500, SLOW_MS = 10000
// After something was sent or stopped, the chat is read at the fast pace this long whatever it says.
const EXPECT_MS = 4000
// Records of a chat kept in the page.
const KEPT = 800

const app = window.harnessApp = {
    identity: { id: null, name: '' }, identities: [], life: { places: [], busy: [] }, chats: [], chat: 'main',
    records: {}, meta: {}, last: {}, live: {}, queue: {}, loaded: {}, problems: {},
    usage: {}, view: 'chat', section: null, approvals: [], values: {}, schema: {},
    showTimeline: prefs.get('timeline.show', false), expect: 0, hasQueue: true,
}
// A turn is at work in the chat: a reply is being written, a message of the owner is being
// answered, or the life says so (its own turns).
app.busy = (chat) => !!app.live[chat] || !!(app.queue[chat] && app.queue[chat].running) || (app.life.busy || []).includes(chat)
app.titles = () => Object.fromEntries(app.chats.map((c) => [c.chat, sidebar.title(c)]))
// The list's row of a chat (the open one by default); a chat that is not in the list (an
// archived one that is open) is known from the archive's listing or from its own record.
app.row = (chat = app.chat) => app.chats.find((c) => c.chat === chat) || sidebar.known(chat)
    || { chat, kind: (app.meta[chat] || {}).kind || (chat === 'main' ? 'main' : 'new'), title: (app.meta[chat] || {}).title || chat }
const row = () => app.row()

function theme(choice) {
    const system = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
    document.documentElement.dataset.theme = choice === 'light' || choice === 'dark' ? choice : system
}
const narrow = () => matchMedia('(max-width: 760px)').matches

// ── the frame ──
function frame() {
    document.body.innerHTML = `
<div class="app${prefs.get('side.hidden', false) ? ' side-hidden' : ''}" data-view="chat">
${sidebar.frameHtml()}
<div class="pg-main">
  <section class="pg-chatarea" aria-label="${tt('对话', 'Chat')}">
    <header class="pg-bar">${ic('sidebar', tt('展开左栏', 'Show the sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar'), cls: 'show-side' })}<h1 class="title"></h1><span class="state"></span><span class="cost" data-tip="${tt('今天花的', 'Spent today')}"></span>${ic('search', tt('在这个对话里查找', 'Find in this chat'), { act: 'find', keys: keys.keysOf('find') })}${ic('timeline', tt('时间线', 'Timeline'), { act: 'timeline', attrs: `aria-pressed="${app.showTimeline}"`, cls: app.showTimeline ? 'on' : '' })}</header>
    <div class="pg-reach" hidden></div>
    ${thread.frameHtml()}
    <div class="tl"${app.showTimeline ? '' : ' hidden'}></div>
    ${composer.frameHtml()}
    ${statusbar.frameHtml()}
    <div class="pg-drop" aria-hidden="true"><span>${icon('plus')}${tt('松手，作为下一条消息的附件', 'Drop to attach to your next message')}</span></div>
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
    sidebar.mount(app); thread.mount(app); composer.mount(app)
    reach(unreachable())
}

// The host does not answer: say so over the chat, and keep asking (the polling goes on).
function reach(down) {
    const bar = $('.pg-reach'); if (!bar) return
    bar.hidden = !down
    bar.innerHTML = down ? `${icon('alert')}<span><b>${esc(down.error)}</b> ${esc(down.fix)}</span><button type="button" class="b" data-act="refresh">${esc(tt('重试', 'Try again'))}</button>` : ''
}

// ── the chat ──
function drawBar() {
    const c = row()
    $('.pg-bar .title').textContent = sidebar.title(c)
    const s = $('.pg-bar .state'), busy = app.busy(app.chat) || c.busy
    const wait = app.approvals.some((a) => a.chat === app.chat)
    s.className = 'state' + (wait ? ' wait' : busy ? ' busy' : '')
    s.textContent = app.life.paused ? tt('‖ 已暂停', '‖ paused') : wait ? tt('● 等你', '● waits for you') : busy ? tt('● 工作中', '● working') : tt('● 空闲', '● idle')
    $('.pg-bar .cost').textContent = usd((app.usage.today || {}).cost_usd)
}
function drawChat() {
    if (app.view !== 'chat') return
    drawBar(); thread.draw(app); composer.draw(app); statusbar.draw(app)
}

// Read the open chat: its record after what is held, the reply being written, its queue.
let pulling = null
function pull() {
    if (!pulling) pulling = read().finally(() => { pulling = null })
    return pulling
}
async function read() {
    const chat = app.chat, id = app.identity.id
    if (!id) return
    const [got, queue] = await Promise.all([agent.chat(id, chat, app.last[chat] || 0), app.hasQueue ? agent.queue(id, chat) : null])
    if (app.chat !== chat || app.identity.id !== id) return
    // a host without the queue is asked once, not four times a second
    if (app.hasQueue && queue === null && (failed.get('/api/agent/queue') || {}).status === 404) app.hasQueue = false
    if (queue) app.queue[chat] = queue
    if (!got) {
        if (!app.loaded[chat]) app.problems[chat] = failed.get('/api/agent/chat')
        return drawChat()
    }
    delete app.problems[chat]
    app.loaded[chat] = true
    app.meta[chat] = got.meta || {}
    const fresh = got.records || []
    if (fresh.length) {
        app.records[chat] = [...(app.records[chat] || []), ...fresh].slice(-KEPT)
        app.last[chat] = fresh[fresh.length - 1].seq
    }
    app.live[chat] = got.live || null
    drawChat()
    if (fresh.length) {
        // the turn may just have ended or begun: the life and the list say so
        tick()
        if (!document.hidden) agent.opened(id, chat)
    }
}
const active = () => app.view === 'chat' && (app.busy(app.chat) || Date.now() < app.expect
    || !!(app.queue[app.chat] && app.queue[app.chat].queued.length && !app.queue[app.chat].held))
let timer = null
function loop() {
    clearTimeout(timer)
    timer = setTimeout(async () => {
        if (app.view === 'chat' && app.identity.id) await pull()
        loop()
    }, active() && !document.hidden ? LIVE_MS : IDLE_MS)
}
// Something was just sent, stopped or changed: read now, and keep the fast pace for a moment.
app.kick = async () => {
    app.expect = Date.now() + EXPECT_MS
    if (pulling) await pulling
    await pull()
    loop()
}

async function openChat(chat) {
    const root = $('.app')
    if (app.view === 'chat') composer.leave(app)
    app.view = 'chat'; app.chat = chat
    root.dataset.view = 'chat'; root.classList.remove('side-open')
    settings.closeSettings(app)
    composer.show(app)
    sidebar.draw(app); drawChat(); panel.render(app)
    if (pulling) await pulling
    await pull()
    loop()
    if (app.chat === chat) { agent.opened(app.identity.id, chat); if (!document.querySelector('.pg-layer.open')) composer.focus() }
}
app.openChat = openChat
app.say = (text) => composer.send(app, text)
app.focusComposer = () => composer.focus()
app.openSettings = (section) => settings.open(app, section)

// Whether a model is usable changed (the first run ended, a model was chosen): the composer says it.
app.modelHint = async () => { await composer.loadSources({ found: true }); if (app.view === 'chat') { composer.draw(app); statusbar.draw(app) } }

// ── the views ──
function openCalendar() {
    const root = $('.app')
    if (app.view === 'chat') composer.leave(app)
    app.view = 'calendar'; root.dataset.view = 'calendar'; root.classList.remove('side-open')
    settings.closeSettings(app); sidebar.draw(app)
    return calendar.open(app)
}
function sideToggle() {
    const root = $('.app')
    if (narrow()) { root.classList.toggle('side-open'); return }
    const hidden = root.classList.toggle('side-hidden')
    prefs.set('side.hidden', hidden)
    if (hidden && root.querySelector('.pg-side').contains(document.activeElement)) composer.focus()
}
app.showSide = () => {
    const root = $('.app')
    if (narrow()) root.classList.add('side-open')
    else if (root.classList.contains('side-hidden')) sideToggle()
}
async function newChat() {
    // an empty new chat is already open: that is the new chat
    if (app.view === 'chat' && row().kind === 'new' && app.loaded[app.chat] && !(app.records[app.chat] || []).length && !app.section) return composer.focus()
    const r = await agent.newChat(app.identity.id, tt('新对话', 'New chat'))
    if (!r.ok) return said(r)
    await refreshList()
    await openChat(r.data.chat)
}
function toggleTimeline() {
    app.showTimeline = !app.showTimeline
    prefs.set('timeline.show', app.showTimeline)
    $('.tl').hidden = !app.showTimeline
    const b = $('[data-act="timeline"]'); b.classList.toggle('on', app.showTimeline); b.setAttribute('aria-pressed', app.showTimeline)
    if (app.showTimeline) thread.drawTimeline(app)
}
async function find() {
    if (app.view !== 'chat' || app.section) await openChat(app.chat)
    thread.openFind()
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
    menu(anchor, [
        { head: tt('身份', 'Identities') },
        ...app.identities.map((i) => ({ label: i.name || i.id, checked: i.id === app.identity.id,
            sub: i.id === app.identity.id ? `${i.id} · ${tt(`${places} 个环境`, `${places} place${places === 1 ? '' : 's'}`)} · ${usd((app.usage.today || {}).cost_usd)} ${tt('今天', 'today')}` : i.id,
            run: () => { if (i.id !== app.identity.id) useIdentity(i.id) } })),
        '-', update.menuItem(app),
        { label: tt('新建身份…', 'New identity…'), icon: 'plus', run: newIdentity },
        { label: tt('从 OpenClaw 或 Hermes 导入…', 'Import from OpenClaw or Hermes…'), icon: 'latest', run: () => onboarding.importDialog(app) },
    ], { side: 'top', label: tt('身份', 'Identities') })
}

async function useIdentity(id) {
    const r = await post('/api/agent/identity', { action: 'use', id })
    if (!r.ok) return said(r)
    if (app.view === 'chat') composer.leave(app)
    Object.assign(app, { records: {}, last: {}, meta: {}, live: {}, queue: {}, loaded: {}, problems: {}, chats: [], approvals: [], chat: 'main' })
    await loadIdentity(); await refreshList(); await slow()
    openChat('main')
}

function newIdentity() {
    const d = dialog(`<h5>${tt('新建身份', 'New identity')}</h5>
<label><span>${tt('显示名', 'Display name')}</span><input class="field" data-name></label>
<label><span>id</span><input class="field" data-id pattern="[A-Za-z0-9_-]+"></label>
<p class="note">${tt('id 是文件夹名，只能用英文字母、数字和连字符，建好后不能改；显示名随时能改。', 'The id names the folder: letters, digits and hyphens only, fixed once created. The display name can change any time.')}</p>
<label><span>${tt('从现有身份克隆', 'Clone from')}</span><select class="field" data-from><option value="">${tt('不克隆', 'none')}</option>${app.identities.map((i) => `<option value="${esc(i.id)}"${i.id === app.identity.id ? ' selected' : ''}>${esc(i.name)} (${esc(i.id)})</option>`).join('')}</select></label>
<div class="checks"><span class="ck on fixed">${tt('人设', 'Persona')}</span><span class="ck on fixed">${tt('技能和反应', 'Skills and reactions')}</span><span class="ck fixed">${tt('记忆（不带）', 'Memory (not copied)')}</span></div>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('创建', 'Create')}</button></div>`)
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

// ── following the life: the list, the life, the approvals ──
let ticking = null
function tick() {
    if (!ticking) ticking = list().finally(() => { ticking = null })
    return ticking
}
// the list as it is after what was just done (not a read that was already on its way)
async function refreshList() { if (ticking) await ticking; return tick() }
async function list() {
    const id = app.identity.id
    if (!id) return
    const more = sidebar.query() // a search, or the archived chats, beside the list itself
    const [life, chats, approvals, extra] = await Promise.all([get('/api/agent/life', { identity: id }), agent.chats(id), agent.approvals(id), more ? agent.chats(id, more) : null])
    if (app.identity.id !== id) return
    if (life) app.life = life
    if (chats) app.chats = chats.chats || []
    if (approvals) app.approvals = approvals.pending || []
    if (more && JSON.stringify(more) === JSON.stringify(sidebar.query())) sidebar.results(app, extra)
    else sidebar.draw(app)
    if (app.view === 'chat') { drawBar(); composer.draw(app); statusbar.draw(app) }
}
async function slow() {
    const id = app.identity.id
    if (!id) return
    const [usage] = await Promise.all([get('/api/agent/usage', { identity: id }), composer.loadSources()])
    if (app.identity.id !== id) return
    app.usage = usage || app.usage
    sidebar.draw(app)
    if (app.view === 'chat') { drawBar(); composer.draw(app); statusbar.draw(app) }
}
app.refresh = async () => { await Promise.all([refreshList(), slow()]); if (app.view === 'chat') await app.kick() }
app.refreshList = refreshList
app.redrawChat = () => drawChat()

// A setting changed on a settings page, from the palette or from the status bar: what shows it at once.
app.applied = (section, key, value) => {
    app.values[section] = { ...(app.values[section] || {}), [key]: value }
    if (section === 'general' && key === 'theme') theme(value)
    if (section === 'general' && key === 'language') { setLanguage(value); redraw() }
    if (app.view === 'chat') statusbar.draw(app)
}
async function setGeneral(key, value) {
    const r = await post('/api/app/settings', { general: { [key]: value } })
    if (!r.ok) return said(r)
    app.applied('general', key, value)
}
// Thinking shown or hidden in every chat (a preference of this window, like the reading positions).
app.showThinking = (shown) => { prefs.set('thinking.show', !!shown); $('.pg-feed')._rows = ['']; if (app.view === 'chat') thread.draw(app) }

// The frame again in the page's language, on the view that was open.
function redraw() {
    const section = app.section
    if (app.view === 'chat') composer.leave(app)
    frame()
    composer.show(app)
    sidebar.draw(app); drawChat(); panel.render(app)
    if (app.view === 'calendar') openCalendar()
    if (section) settings.open(app, section)
    update.draw(app)
}

// ── approvals and failed turns ──
async function answer(code, accept, reason = '') {
    const r = await agent.answer(app.identity.id, code, accept, reason)
    if (!r.ok) said(r)
    else if (r.data && r.data.handled_elsewhere) toast(tt('这个请求已经在别处回答过了。', 'This request was already answered elsewhere.'))
    await Promise.all([refreshList(), app.kick()])
    composer.focus()
}
const record = (seq) => (app.records[app.chat] || []).find((r) => String(r.seq) === String(seq))
// Retry a failed turn: say again what the turn was asked.
function retry(seq) {
    const recs = app.records[app.chat] || []
    let i = recs.findIndex((r) => String(r.seq) === String(seq))
    while (i >= 0 && recs[i].event !== 'user') i--
    if (i < 0) return toast(tt('这一回合的那句话不在记录里，没法重试；请再说一遍。', "This turn's message is not in the record, so it cannot be retried; say it again."), { error: true })
    return composer.send(app, recs[i].text)
}
function copyError(seq) {
    const r = record(seq) || {}, model = composer.modelOf(app)
    return copy([tt('The Harness：一个回合失败了', 'The Harness: a turn failed'), `${tt('原因', 'reason')}: ${r.error || ''}`, r.fix ? `${tt('怎么修', 'fix')}: ${r.fix}` : '', r.code ? `code: ${r.code}` : '',
        `${tt('模型', 'model')}: ${model.id || model.name}`, `${tt('对话', 'chat')}: ${app.chat}`, r.time ? `${tt('时间', 'time')}: ${new Date(r.time * 1000).toISOString()}` : '', r.log ? `${tt('日志', 'log')}: ${r.log}` : ''].filter(Boolean).join('\n'),
    tt('错误已复制', 'Error copied'))
}
// Open logs: the end of the host's log, in the window (the page may be on another computer than the log).
async function openLogs(seq) {
    const r = record(seq) || {}
    const close = `<div class="row"><span class="res"></span><button type="button" class="btn quiet" data-copy hidden>${tt('复制', 'Copy')}</button><button type="button" class="btn" data-default>${tt('关闭', 'Close')}</button></div>`
    const d = dialog(`<h5>${tt('日志', 'Logs')}</h5><div class="logs">${loading()}</div>${close}`)
    d.classList.add('wide')
    d.querySelector('[data-default]').onclick = closeDialog
    const got = await get('/api/app/log', { lines: 200 })
    if (!document.contains(d)) return
    const box = d.querySelector('.logs'), copyButton = d.querySelector('[data-copy]')
    let text = ''
    if (got && Array.isArray(got.lines)) {
        text = got.lines.join('\n')
        box.innerHTML = `<p class="note">${esc(got.path || '')}</p><pre class="logtail" tabindex="0">${esc(text) || esc(tt('（日志是空的）', '(the log is empty)'))}</pre>`
        const pre = box.querySelector('pre'); pre.scrollTop = pre.scrollHeight
    } else {
        const why = failed.get('/api/app/log') || {}
        const missing = why.status === 404
        text = r.log || ''
        box.innerHTML = problem(missing ? { error: tt('这个后台还不能把日志给窗口看。', 'This host cannot show its log in the window yet.'), fix: tt('日志是数据目录下 logs 文件夹里的 host.log。', 'The log is host.log, in the logs folder of the data folder.') } : why, { title: tt('日志没有读出来', 'The log could not be read') })
            + (r.log ? `<p class="note">${esc(tt('日志文件：', 'Log file: '))}<code>${esc(r.log)}</code></p>` : '')
    }
    copyButton.hidden = !text
    copyButton.onclick = () => copy(text)
}

// ── the palette: every place and action by name ──
function commands() {
    const go = tt('前往', 'Go to'), act = tt('操作', 'Action'), look = tt('外观', 'Appearance')
    const inChat = app.view === 'chat' && !app.section
    const tool = (id) => ({ title: tt(`打开${panel.toolName(id)}`, `Open ${panel.toolName(id)}`), group: tt('工具', 'Tools'), icon: id, run: async () => { if (!inChat) await openChat(app.chat); panel.open(app, id) } })
    const themes = [['system', '跟随系统', 'follow the system'], ['light', '亮色', 'light'], ['dark', '暗色', 'dark']]
    const languages = [['system', '跟随系统', 'follow the system'], ['zh', '中文', '中文'], ['en', 'English', 'English']]
    const thinking = prefs.get('thinking.show', true)
    return [
        { title: tt('新对话', 'New chat'), group: act, icon: 'edit', keys: keys.keysOf('new-chat'), run: newChat },
        ...(inChat && app.busy(app.chat) ? [{ title: tt('停下这一回合', 'Stop this turn'), group: act, icon: 'stop', keys: 'Esc', run: () => composer.stop(app) }] : []),
        { title: tt('在这个对话里查找', 'Find in this chat'), group: act, icon: 'search', keys: keys.keysOf('find'), run: find },
        { title: tt('搜索对话', 'Search chats'), group: act, icon: 'search', keys: keys.keysOf('search-chats'), run: () => sidebar.search(app) },
        { title: tt('换这个对话的模型…', 'Change the model of this chat…'), group: act, icon: 'model', also: 'model 模型', run: async () => { if (!inChat) await openChat(app.chat); composer.pickModel(app) } },
        ...sidebar.commands(app),
        { title: tt('日历', 'Calendar'), group: go, icon: 'calendar', run: openCalendar },
        { title: tt('设置', 'Settings'), group: go, icon: 'settings', keys: keys.keysOf('settings'), run: () => settings.open(app, app.section || 'general') },
        { title: tt('收起或展开左栏', 'Hide or show the sidebar'), group: act, icon: 'sidebar', keys: keys.keysOf('sidebar'), run: sideToggle },
        { title: tt('打开或收起工具面板', 'Open or close the tools panel'), group: act, icon: 'context', keys: keys.keysOf('tools'), run: () => panel.toggle(app) },
        ...panel.RAIL.map(([id]) => tool(id)),
        { title: tt('显示或隐藏时间线', 'Show or hide the timeline'), group: act, icon: 'timeline', run: toggleTimeline },
        { title: thinking ? tt('隐藏思考内容', 'Hide thinking') : tt('显示思考内容', 'Show thinking'), group: look, also: 'thinking reasoning 思考', run: () => app.showThinking(!thinking) },
        { title: tt('快捷键', 'Keyboard shortcuts'), group: go, icon: 'keyboard', keys: keys.keysOf('shortcuts'), run: openShortcuts },
        ...SECTIONS.map(([id]) => ({ title: `${tt('设置', 'Settings')} › ${sectionName(id)}`, group: go, icon: 'settings', run: () => settings.open(app, id) })),
        ...themes.map(([id, zh, en]) => ({ title: tt(`主题：${zh}`, `Theme: ${en}`), group: look, also: 'theme dark light 主题', run: () => setGeneral('theme', id) })),
        ...languages.map(([id, zh, en]) => ({ title: tt(`语言：${zh}`, `Language: ${en}`), group: look, also: 'language 语言', run: () => setGeneral('language', id) })),
        ...app.identities.filter((i) => i.id !== app.identity.id).map((i) => ({ title: tt(`切换到身份 ${i.name || i.id}`, `Switch to identity ${i.name || i.id}`), group: tt('身份', 'Identity'), also: i.id, run: () => useIdentity(i.id) })),
        ...app.chats.map((c) => ({ title: sidebar.title(c), group: tt('对话', 'Chat'), also: c.chat, run: () => openChat(c.chat) })),
    ]
}

// ── actions and keys ──
function actions() {
    on('chat-open', (n) => openChat(n.dataset.arg))
    on('chat-new', newChat)
    on('calendar', openCalendar)
    on('settings', (n) => settings.open(app, n.dataset.arg || app.section || 'general'))
    on('settings-close', () => settings.closeSettings(app))
    on('identity-menu', (n) => idMenu(n))
    on('approvals-next', () => (app.approvals.length ? openChat(app.approvals[0].chat || 'main') : toast(tt('没有等你批准的事', 'Nothing waits for you'))))
    on('side-toggle', sideToggle)
    on('timeline', toggleTimeline)
    on('find', find)
    on('find-next', () => thread.step(1))
    on('find-prev', () => thread.step(-1))
    on('find-close', () => thread.closeFind())
    on('latest', () => thread.toLatest())
    on('copy-code', (n) => copy(n.closest('.cb').querySelector('pre').textContent))
    on('model-choose', () => onboarding.modelDialog(app, { first: false, after: () => app.refresh() }))
    on('model-pick', (n) => composer.pickModel(app, n))
    on('effort-pick', (n) => composer.pickEffort(app, n))
    on('approvals-level', (n) => statusbar.approvalsMenu(app, n))
    on('reload', () => location.reload())
    on('refresh', () => app.refresh())
    on('starter', (n) => composer.send(app, n.dataset.arg))
    on('turn-stop', () => composer.stop(app))
    on('attach', () => composer.attachPick())
    on('attach-remove', (n) => composer.attachRemove(app, +n.dataset.arg))
    on('attach-retry', (n) => composer.attachRetry(app, +n.dataset.arg))
    on('queue-toggle', () => composer.queueToggle(app))
    on('queue-edit', (n) => composer.queueEdit(app, n.dataset.arg))
    on('queue-save', () => composer.queueSave(app))
    on('queue-cancel', () => composer.queueCancel(app))
    on('queue-remove', (n) => composer.queueRemove(app, n.dataset.arg))
    on('queue-now', (n) => composer.queueNow(app, n.dataset.arg))
    on('queue-resume', () => composer.queueResume(app))
    on('queue-clear', () => composer.queueClear(app))
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
    on('decline-why', (n) => thread.declineWhy(n))
    on('decline', (n) => answer(n.dataset.arg, false, thread.reasonOf(n)))
    on('card-dismiss', (n) => n.closest('.pe').remove())
    on('turn-retry', (n) => retry(n.dataset.arg))
    on('turn-model', () => composer.pickModel(app))
    on('turn-logs', (n) => openLogs(n.dataset.arg))
    on('turn-copy', (n) => copyError(n.dataset.arg))
    sidebar.actions(app)
}

function shortcuts() {
    keys.bind('palette', () => openPalette(commands()))
    keys.bind('shortcuts', openShortcuts)
    keys.bind('settings', () => (app.section ? settings.closeSettings(app) : settings.open(app, 'general')))
    keys.bind('new-chat', newChat)
    keys.bind('sidebar', sideToggle)
    keys.bind('tools', () => { if (app.view === 'chat' && !app.section) panel.toggle(app) })
    keys.bind('find', find)
    keys.bind('search-chats', () => sidebar.search(app))
    // Esc, asked in this order: what is open over the page, then what has the keyboard, then
    // the views, and with nothing left the turn at work
    const within = (selector) => !!(document.activeElement && document.activeElement.closest && document.activeElement.closest(selector))
    keys.onEscape(10, closePalette)
    keys.onEscape(20, () => closeMenu(true))
    keys.onEscape(30, closeDialog)
    keys.onEscape(40, () => within('.pg-findbar') && thread.closeFind())
    keys.onEscape(42, () => thread.escapeCard((code) => answer(code, false)))
    keys.onEscape(44, () => within('.pg-queue') && composer.queueCancel(app))
    keys.onEscape(46, () => sidebar.escape(app))
    keys.onEscape(50, () => thread.closeFind())
    keys.onEscape(60, () => { if (!app.section) return false; settings.closeSettings(app); return true })
    keys.onEscape(70, () => { const root = $('.app'); if (!root.classList.contains('side-open')) return false; root.classList.remove('side-open'); return true })
    keys.onEscape(90, () => { if (app.view !== 'chat' || !app.busy(app.chat)) return false; composer.stop(app); return true })
    // with a dialog, a menu or the palette open, the keys are theirs
    keys.start({ blocked: (id) => (dialogOpen() || menuOpen() || paletteOpen()) && id !== 'palette' })
}

async function main() {
    const set = (await get('/api/app/settings')) || {}
    app.values = set.values || {}; app.schema = set.schema || {}
    setLanguage((app.values.general || {}).language)
    theme((app.values.general || {}).theme)
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
    await Promise.all([tick(), slow()])
    const view = new URLSearchParams(location.search).get('view')
    const chat = new URLSearchParams(location.search).get('chat')
    await openChat(chat || 'main')
    if (view === 'calendar') openCalendar()
    else if (view && view.startsWith('settings')) settings.open(app, view.split(':')[1] || 'general')
    setInterval(tick, LIST_MS); setInterval(slow, SLOW_MS)
    document.addEventListener('visibilitychange', () => { if (!document.hidden && app.view === 'chat') app.kick() })
    onboarding.start(app)
    update.start(app)
}

main()
