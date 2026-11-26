// The composer, after Hermes Desktop's "Chat" and "Choosing a model":
//   - Enter sends, Shift+Enter is a new line, and an input method that is composing keeps its
//     Enter; while it works, what is sent joins the queue;
//   - the queue sits above the composer: each waiting message can be edited, deleted or sent
//     now. It is the host's (GET/POST /api/agent/queue), so it survives a restart and every
//     window on the chat shows the same list. Stop (or Esc) with messages waiting holds the
//     queue and opens it; Resume lets it go on;
//   - an unsent draft is kept per chat (this window's storage, prefs.js);
//   - Up and Down in an empty composer recall the messages sent in this chat;
//   - files dropped anywhere on the chat, pasted images and the + button become attachments
//     of the next message;
//   - the model picker beside the input changes the model of this chat only; signed-in agents,
//     keys and local models are one list. Settings › Model changes the default.
import { esc, tt, modelName } from './i18n.js'
import { get, post, failed, agent } from './api.js'
import { $, ic, toast, said, menu, confirm, dialog, closeDialog } from './ui.js'
import { icon } from './icons.js'
import { perChat } from './prefs.js'
import { label } from './keys.js'
import * as models from './models.js'
import * as onboarding from './onboarding.js'

const drafts = perChat('draft')
const state = new Map() // "identity/chat" -> {files: [attachment], editing: queued id | null}
const key = (app) => `${app.identity.id}/${app.chat}`
const of = (app) => { if (!state.has(key(app))) state.set(key(app), { files: [], editing: null }); return state.get(key(app)) }

let shown = null // the chat whose draft the textarea holds
let queueOpen = true // the list of waiting messages is shown, not only its heading
let recall = null // browsing sent messages: {at, kept (what was in the composer before)}
let saving = null
let sources = { status: null, models: [], found: null, read: false } // what the model picker lists

export function frameHtml() {
    return `<div class="pg-queue" hidden></div><div class="pg-notice" hidden></div>
    <form class="pg-compose"><div class="pg-atts" hidden></div><div class="pg-ac" hidden role="listbox"></div><textarea rows="1" placeholder="${tt('输入消息，@ 引用文件，/ 调起命令…', 'Ask anything, @ for files, / for commands…')}" aria-label="${tt('消息', 'Message')}"></textarea>
      <div class="pg-tools">${ic('plus', tt('添加文件', 'Attach files'), { act: 'attach' })}<input type="file" multiple hidden tabindex="-1" aria-hidden="true"><button type="button" class="pick mode" data-act="mode-pick" data-tip="${tt('执行模式', 'Execution mode')}"></button><button type="button" class="pick where" data-act="where-pick" data-tip="${tt('工作项目', 'Project')}"></button><span class="grow"></span>`
        + `<button type="button" class="pick model" data-act="model-pick" data-tip="${tt('模型', 'Model')}"></button><button type="button" class="pick effort" data-act="effort-pick" data-tip="${tt('思考强度', 'Reasoning effort')}" hidden></button>`
        + `<button type="button" class="stop" data-act="turn-stop" aria-label="${tt('停止', 'Stop')}" data-tip="${tt('停止', 'Stop')}" data-keys="Esc" hidden>${icon('stop')}</button>`
        + `<button type="submit" class="send" aria-label="${tt('发送', 'Send')}" data-tip="${tt('发送', 'Send')}" data-keys="${label('enter')}">${icon('send')}</button></div></form>`
}

const area = () => $('.pg-compose textarea')
function grow() { const a = area(); a.style.height = 'auto'; a.style.height = Math.min(180, a.scrollHeight) + 'px' }
export function focus() { const a = area(); if (a && !a.disabled) a.focus() }
function setText(text) { const a = area(); a.value = text; grow(); a.setSelectionRange(text.length, text.length) }

export function mount(app) {
    const a = area(), form = $('.pg-compose')
    a.addEventListener('input', () => {
        grow(); recall = null
        clearTimeout(saving)
        const mine = key(app)
        saving = setTimeout(() => { if (key(app) === mine) drafts.set(app, a.value) }, 250)
    })
    a.addEventListener('keydown', (e) => {
        if (e.isComposing || e.keyCode === 229) return // the input method's own Enter and arrows
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); send(app); return }
        if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && (recall || !a.value)) {
            if (history(app, e.key === 'ArrowUp' ? -1 : 1)) e.preventDefault()
        }
    })
    a.addEventListener('paste', (e) => {
        const files = [...((e.clipboardData && e.clipboardData.files) || [])]
        if (!files.length) return
        e.preventDefault(); attach(app, files)
    })
    form.addEventListener('submit', (e) => { e.preventDefault(); send(app) })
    const picker = form.querySelector('input[type=file]')
    picker.addEventListener('change', () => { attach(app, [...picker.files]); picker.value = '' })
    // files dropped anywhere on the chat
    const zone = $('.pg-chatarea')
    let depth = 0
    const carries = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files')
    zone.addEventListener('dragenter', (e) => { if (!carries(e)) return; e.preventDefault(); depth++; zone.classList.add('dropping') })
    zone.addEventListener('dragover', (e) => { if (carries(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' } })
    zone.addEventListener('dragleave', (e) => { if (!carries(e)) return; depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('dropping') })
    zone.addEventListener('drop', (e) => {
        if (!carries(e)) return
        e.preventDefault(); depth = 0; zone.classList.remove('dropping')
        attach(app, [...e.dataTransfer.files]); focus()
    })
    // a queued message being edited: Enter saves it
    $('.pg-queue').addEventListener('keydown', (e) => {
        if (e.target.tagName !== 'TEXTAREA' || e.isComposing || e.keyCode === 229) return
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); queueSave(app) }
    })
}

// The chat that is open changed: its own draft and attachments.
export function show(app) {
    const a = area()
    clearTimeout(saving)
    recall = null
    shown = key(app)
    a.value = drafts.get(app, '')
    grow()
    drawFiles(app)
}
// Before leaving a chat: what is typed is its draft.
export function leave(app) { clearTimeout(saving); if (shown === key(app)) drafts.set(app, area().value); shown = null }

// ── sending ──
let sending = false
export async function send(app, given) {
    const a = area(), mine = of(app), chat = app.chat
    const text = (typeof given === 'string' ? given : a.value).trim()
    const files = mine.files
    if (sending || (!text && !files.length)) return
    if (files.some((f) => f.state === 'failed')) return toast(tt('有附件没传上去：先去掉它或重试，再发送。', 'An attachment was not uploaded: remove it or retry it, then send.'), { error: true })
    if (files.some((f) => f.state === 'uploading')) return toast(tt('附件还在上传，稍等一下。', 'Attachments are still uploading; one moment.'))
    sending = true
    const typed = typeof given !== 'string'
    if (typed) { a.value = ''; grow() }
    // the main conversation says where with each message; a chat opened on a place works there by itself
    const at = whereOf(app)
    const r = await agent.say(app.identity.id, chat, text, { ...(at && at.kind === 'main' && at.place ? { place: at.place } : {}), ...(files.length ? { files: files.map((f) => f.id) } : {}) })
    sending = false
    if (!r.ok) {
        // not sent: the words are back in the composer, to change and send again
        if (typed && app.chat === chat) setText(a.value ? `${text}\n${a.value}` : text)
        return said(r, tt('没发出去', 'Not sent'))
    }
    if (app.chat === chat) { drafts.set(app, ''); recall = null }
    for (const f of files) if (f.url) URL.revokeObjectURL(f.url)
    mine.files = []
    drawFiles(app)
    app.kick()
}

// Up and Down in an empty composer: the messages sent in this chat, the newest first.
function history(app, step) {
    const sent = []
    for (const r of app.records[app.chat] || []) if (r.event === 'user' && r.text && sent[sent.length - 1] !== r.text) sent.push(r.text)
    if (!recall) {
        if (step > 0 || !sent.length) return false
        recall = { at: sent.length, kept: area().value }
    }
    const at = recall.at + step
    if (at < 0) return true
    if (at >= sent.length) { const kept = recall.kept; recall = null; setText(kept); return true }
    const kept = recall.kept
    setText(sent[at])
    recall = { at, kept } // setText does not fire input, so the browsing goes on
    return true
}

// ── attachments ──
const size = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`)
function attach(app, files) {
    const mine = of(app)
    for (const file of files) {
        const item = { file, name: file.name || tt('粘贴的图片', 'pasted image'), size: file.size, type: file.type || 'application/octet-stream', state: 'uploading', id: null,
            url: (file.type || '').startsWith('image/') ? URL.createObjectURL(file) : null }
        mine.files.push(item)
        upload(app, item)
    }
    drawFiles(app)
}
async function upload(app, item) {
    const identity = app.identity.id, chat = app.chat, where = key(app)
    item.state = 'uploading'; item.problem = null
    let data
    try {
        data = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(String(reader.result).split(',')[1] || ''); reader.onerror = () => fail(reader.error); reader.readAsDataURL(item.file) })
    } catch (error) {
        item.state = 'failed'; item.problem = { error: tt('这个文件读不出来。', 'This file could not be read.'), fix: String((error && error.message) || '') }
        if (key(app) === where) drawFiles(app)
        return
    }
    const r = await agent.attach(identity, chat, { name: item.name, type: item.type, data })
    if (r.ok && r.data && r.data.id) { item.state = 'done'; item.id = r.data.id } else {
        item.state = 'failed'
        item.problem = r.status === 404
            ? { error: tt('这个后台还不能接收附件。', 'This host cannot receive attachments yet.'), fix: tt('更新 The Harness 后再试；文件没有发出去。', 'Update The Harness and try again; the file was not sent.') }
            : { error: r.error || tt('没传上去', 'The upload failed'), fix: r.fix || '' }
    }
    if (key(app) === where) drawFiles(app)
}
function drawFiles(app) {
    const box = $('.pg-atts'), files = of(app).files
    box.hidden = !files.length
    box.innerHTML = files.map((f, i) => `<div class="att ${f.state}"${f.problem ? ` data-tip="${esc([f.problem.error, f.problem.fix].filter(Boolean).join(' '))}" tabindex="0"` : ''}>`
        + (f.url ? `<img src="${f.url}" alt="">` : icon(f.type.startsWith('image/') ? 'image' : 'file', 14))
        + `<span class="an"><b>${esc(f.name)}</b><small>${f.state === 'uploading' ? `<span class="spin"></span>${tt('正在上传', 'uploading')}` : f.state === 'failed' ? esc(f.problem.error) : size(f.size)}</small></span>`
        + (f.state === 'failed' ? ic('retry', tt('重试上传', 'Retry the upload'), { act: 'attach-retry', attrs: `data-arg="${i}"` }) : '')
        + ic('close', tt(`去掉 ${f.name}`, `Remove ${f.name}`), { act: 'attach-remove', attrs: `data-arg="${i}"` }) + `</div>`).join('')
}
export function attachRemove(app, index) {
    const files = of(app).files, [gone] = files.splice(index, 1)
    if (gone && gone.url) URL.revokeObjectURL(gone.url)
    drawFiles(app); focus()
}
export function attachRetry(app, index) { const item = of(app).files[index]; if (!item) return null; const going = upload(app, item); drawFiles(app); return going }
export function attachPick() { $('.pg-compose input[type=file]').click() }

// ── the queue above the composer ──
const queueOf = (app) => app.queue[app.chat] || { held: false, running: null, queued: [] }
function drawQueue(app) {
    const box = $('.pg-queue'), q = queueOf(app), mine = of(app)
    if (mine.editing && !q.queued.some((m) => m.id === mine.editing)) mine.editing = null // it started, or was removed elsewhere
    if (mine.editing && box.querySelector('textarea')) return // being edited: left alone until saved or cancelled
    const n = q.queued.length
    if (!n) { box.hidden = true; box.innerHTML = ''; box._html = ''; return }
    const open = queueOpen || q.held
    const html = `<div class="qh"><button type="button" class="qt" data-act="queue-toggle" aria-expanded="${open}">${icon(open ? 'down' : 'right', 12)}${icon('clock', 14)}<b>${tt(`${n} 条在排队`, `${n} queued`)}</b>`
        + `<span>${q.held ? tt('停下之后暂停了，点“继续”接着发', 'paused after the stop; Resume sends them on') : open ? '' : esc(q.queued[0].text)}</span></button>`
        + (q.held ? `<button type="button" class="b" data-act="queue-resume">${icon('play', 12)}${tt('继续', 'Resume')}</button>` : '')
        + (n > 1 ? `<button type="button" class="b" data-act="queue-clear">${tt('全部去掉', 'Clear all')}</button>` : '') + `</div>`
        + (open ? `<ol class="ql">${q.queued.map((m) => (m.id === mine.editing
            ? `<li data-id="${esc(m.id)}" class="editing"><textarea rows="2" aria-label="${tt('改这条排队的消息', 'Edit this queued message')}">${esc(m.text)}</textarea><span class="qa"><button type="button" class="b" data-act="queue-save">${tt('保存', 'Save')}</button><button type="button" class="b quiet" data-act="queue-cancel">${tt('取消', 'Cancel')}</button></span></li>`
            : `<li data-id="${esc(m.id)}"><span class="qx">${esc(m.text)}</span><span class="qa">${ic('send', tt('现在就发（停下正在做的）', 'Send now (stops what it is doing)'), { act: 'queue-now', attrs: `data-arg="${esc(m.id)}"` })}${ic('edit', tt('编辑', 'Edit'), { act: 'queue-edit', attrs: `data-arg="${esc(m.id)}"` })}${ic('trash', tt('删除', 'Delete'), { act: 'queue-remove', attrs: `data-arg="${esc(m.id)}"` })}</span></li>`)).join('')}</ol>` : '')
    box.hidden = false
    if (box._html === html) return
    box._html = html; box.innerHTML = html
    const editor = box.querySelector('textarea')
    if (editor) { editor.focus(); editor.setSelectionRange(editor.value.length, editor.value.length) }
}
// One change of the queue: the host answers with the queue after it.
async function queueDo(app, action, more) {
    const chat = app.chat
    const r = await agent.queueAct(app.identity.id, chat, action, more)
    if (!r.ok) { said(r); app.kick(); return false }
    if (r.data && Array.isArray(r.data.queued)) app.queue[chat] = r.data
    if (app.chat === chat) drawQueue(app)
    app.kick()
    return true
}
export function queueToggle(app) { queueOpen = !(queueOpen || queueOf(app).held); $('.pg-queue')._html = ''; drawQueue(app) }
export function queueEdit(app, id) { of(app).editing = id; queueOpen = true; $('.pg-queue')._html = ''; $('.pg-queue').innerHTML = ''; drawQueue(app) }
export function queueCancel(app) {
    const mine = of(app)
    if (!mine.editing) return false
    mine.editing = null
    $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''
    drawQueue(app); focus()
    return true
}
export async function queueSave(app) {
    const mine = of(app), editor = $('.pg-queue textarea')
    if (!mine.editing || !editor) return
    const text = editor.value.trim(), id = mine.editing
    if (!text) return queueRemoveNow(app, id)
    mine.editing = null
    $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''
    await queueDo(app, 'edit', { id, text })
    focus()
}
async function queueRemoveNow(app, id) { of(app).editing = null; $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''; await queueDo(app, 'remove', { id }); focus() }
export const queueRemove = (app, id) => queueDo(app, 'remove', { id })
export const queueNow = (app, id) => queueDo(app, 'send_now', { id })
export const queueResume = (app) => queueDo(app, 'resume')
export async function queueClear(app) {
    const n = queueOf(app).queued.length
    if (!(await confirm({ title: tt(`去掉排队的 ${n} 条消息？`, `Clear the ${n} queued messages?`), text: tt('它们不会被发出去。', 'They will not be sent.'), yes: tt('全部去掉', 'Clear all'), danger: true }))) return
    return queueDo(app, 'clear')
}

// Stop the turn at work in this chat (the button, or Esc). With messages waiting, the queue
// is held and shown, to resume, send, edit or delete from there.
export async function stop(app) {
    if (!app.busy(app.chat)) return false
    const chat = app.chat, held = queueOf(app).queued.length > 0
    const r = await agent.stop(app.identity.id, chat, held)
    if (!r.ok) { said(r, tt('没能停下', 'It could not be stopped')); return true }
    if (r.data && r.data.held) queueOpen = true
    if (r.data && r.data.stopped === false) toast(tt('它现在没有在做事。', 'It is not doing anything now.'))
    app.kick()
    return true
}

// ── the model of this chat ──
// What can be the model: the model in use and the model list, and (found: true) what the host
// finds on this computer, which takes it a moment (it looks for agents signed in here).
export async function loadSources({ found = false } = {}) {
    const [status, list, here] = await Promise.all([get('/api/app'), get('/api/app/models'), found || !sources.found ? get('/api/app/found') : null])
    sources = { status: status || sources.status, models: list ? list.models || [] : sources.models, found: here || sources.found, read: sources.read || !!list }
    return !!list
}
const chatRow = (app) => app.row()
const entry = (id) => sources.models.find((m) => m.id === id)
const defaultEntry = () => { const llm = (sources.status || {}).llm || {}; return entry(llm.id) || (llm.model ? llm : null) }
// A model by its own name; its source is said beside it, never in its place (models.js).
const shownName = (m) => models.modelLabel(m)
const ready = () => { const llm = (sources.status || {}).llm; return !llm || llm.ready !== false }
const current = (app) => entry(chatRow(app).model) || defaultEntry()

// The models to pick from, by source: under each source the models of it that are kept, and
// a row that opens every other model that source offers (an agent declares a handful, a
// provider has a catalog). The source is the heading; a row is a model.
export async function pickModel(app, anchor) {
    // the list as last read opens at once; it is read again for the next time
    if (sources.read) loadSources({ found: true })
    else if (!(await loadSources({ found: true }))) return said(failed.get('/api/app/models'), tt('模型列表没有读出来', 'The models could not be read'))
    const row = chatRow(app), base = defaultEntry()
    const listed = sources.models.filter((m) => m.enabled !== false)
    const has = (provider) => sources.models.some((m) => m.provider === provider)
    const f = sources.found || {}
    // sources found on this computer that have no model in the list yet
    const fresh = [...(f.agents || []).filter(onboarding.agentUsable).map((a) => ({ provider: a.provider, title: a.name })), ...(f.keys || []).map((k) => ({ provider: k.provider, title: k.name })),
        ...(f.local || []).map((l) => ({ provider: l.provider, title: l.name || l.provider }))].filter((x, i, all) => !has(x.provider) && all.findIndex((y) => y.provider === x.provider) === i)
    const setUp = () => onboarding.modelDialog(app, { after: () => app.refresh() })
    const groups = models.bySource(listed).flatMap((g) => [
        { head: g.source },
        ...g.models.map((m) => ({ label: shownName(m), checked: row.model === m.id, run: () => choose(app, m.id) })),
        { label: tt(`${g.source} 的其它模型…`, `More models of ${g.source}…`), icon: 'plus',
            run: () => models.more(g.provider, g.source, { current: (current(app) || {}).provider === g.provider ? (current(app) || {}).model : '', then: async (kept) => { await loadSources(); choose(app, kept.id) } }) },
    ])
    const items = [
        { head: tt('这个对话用哪个模型', 'The model of this chat') },
        { label: tt(`默认${base ? ' · ' + shownName(base) : ''}`, `Default${base ? ' · ' + shownName(base) : ''}`), sub: base ? models.sourceLabel(base) : '', checked: !row.model, run: () => choose(app, null) },
        ...groups,
        ...(fresh.length ? [{ head: tt('还没设好', 'Not set up yet') }] : []),
        ...fresh.map((x) => ({ label: x.title, sub: '', icon: 'plus', run: setUp })),
        '-',
        { label: tt('添加来源…', 'Add a source…'), icon: 'plus', run: setUp },
        { label: tt('设置 › 模型', 'Settings › Model'), icon: 'settings', run: () => app.openSettings('model') },
    ]
    menu(anchor && document.contains(anchor) ? anchor : $('.pick.model'), items, { side: 'top', align: 'end', label: tt('这个对话用哪个模型', 'The model of this chat'), filter: listed.length > 8 ? tt('找模型', 'Find a model') : '' })
}
async function choose(app, id, effort) {
    const row = chatRow(app), chat = app.chat
    const same = (row.model || null) === (id || null)
    if (same && effort === undefined) return
    // in the middle of a chat a switch costs: ask first (Hermes Desktop: "Switch anyway" / "Keep current model")
    if (!same && (app.records[chat] || []).some((r) => r.event === 'reply')) {
        const go = await confirm({ title: tt('在这个对话中途换模型？', 'Switch the model in the middle of this chat?'),
            text: tt('下一条消息会让新模型把整个对话从头读一遍，按完整的输入价格算。', 'With the next message the new model reads the whole conversation again, at the full input price.'),
            yes: tt('仍然切换', 'Switch anyway'), no: tt('保留现在的模型', 'Keep current model') })
        if (!go) return
    }
    // an effort belongs to its model: another model starts from its own default
    const next = entry(id) || defaultEntry() || {}
    const level = effort !== undefined ? effort : same ? row.effort : null
    const r = await agent.chatsAct(app.identity.id, 'model', chat, { model: id || null, effort: level && (next.efforts || []).includes(level) ? level : null })
    if (!r.ok) return said(r, tt('没换成', 'The model was not changed'))
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app); app.kick()
    if (!same) toast(tt(`这个对话现在用 ${shownName(next)}（${models.sourceLabel(next)}）`, `This chat now uses ${shownName(next)} (${models.sourceLabel(next)})`))
}
// How hard this chat's model thinks: the levels that model has, as its source names them.
export function pickEffort(app, anchor) {
    const row = chatRow(app), m = current(app) || {}
    menu(anchor, [{ head: tt(`思考强度 · ${shownName(m)}`, `Reasoning effort · ${shownName(m)}`) },
        ...['default', ...(m.efforts || [])].map((e) => ({ label: models.effortLabel(e), checked: (row.effort || 'default') === e, run: () => choose(app, row.model || null, e === 'default' ? null : e) }))],
    { side: 'top', align: 'end' })
}
// A model kept before its source was asked what it has (an entry without effort levels): the
// source is asked once, behind the page, and the entry gets its levels.
const told = new Set()
async function describe(app, m) {
    if (!m || !m.id || (m.efforts || []).length || told.has(m.id)) return
    told.add(m.id)
    const r = await post('/api/app/models', { action: 'describe', id: m.id })
    if (r.ok && r.data && Array.isArray(r.data.models) && JSON.stringify(r.data.models) !== JSON.stringify(sources.models)) { sources.models = r.data.models; draw(app) }
}

// ── where this chat works ──
// As a session of Claude Code or Codex is opened on a project: a chat the owner started works in
// one place (a project folder, the browser, the desktop), kept with the chat by the host, and for
// a git project either in the folder itself or in an isolated copy of it (a worktree on the
// chat's own branch). The main conversation is not tied to one place: its choice is said with
// each message, and remembered by this window.
const mainWhere = perChat('where')
const placeOf = (app, id) => (app.life.places || []).find((p) => p.id === id) || null
export function whereOf(app) {
    const row = chatRow(app)
    if (row.kind === 'new') return { kind: 'new', place: placeOf(app, row.place) ? row.place : null, isolation: row.isolation || null, branch: row.branch || '' }
    if (row.kind === 'main') { const kept = mainWhere.get(app, ''); return { kind: 'main', place: placeOf(app, kept) ? kept : null, isolation: null } }
    return null
}
async function setWhere(app, place, isolation = null) {
    const row = chatRow(app)
    if (row.kind === 'main') { mainWhere.set(app, place || ''); return draw(app) }
    const r = await agent.chatsAct(app.identity.id, 'place', app.chat, { place: place || null, isolation })
    if (!r.ok) return said(r, tt('没改成', 'It was not changed'))
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app); app.kick()
    const p = placeOf(app, place)
    toast(!p ? tt('无项目', 'No project')
        : isolation === 'worktree' ? `${(p.title || p.id).replace(/^folder\s*·\s*/i, '')} · Worktree`
            : (p.title || p.id).replace(/^folder\s*·\s*/i, ''))
}
const MODES = [
    ['auto', '自动', 'Auto', 'shield'],
    ['plan', '计划', 'Plan', 'plan'],
    ['ask', '询问', 'Ask', 'shield'],
]
export function pickMode(app, anchor) {
    const cur = chatRow(app).mode || 'auto'
    menu(anchor && document.contains(anchor) ? anchor : $('.pick.mode'), [
        { head: tt('执行模式', 'Execution mode') },
        ...MODES.map(([id, zh, en, icName]) => ({
            label: tt(zh, en), icon: icName, checked: cur === id,
            run: async () => {
                const r = await agent.chatsAct(app.identity.id, 'mode', app.chat, { mode: id })
                if (!r.ok) return said(r)
                if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
                draw(app)
            },
        })),
        '-',
        { label: tt('权限设置…', 'Permissions…'), icon: 'settings', run: () => app.openSettings('permissions') },
    ], { side: 'top', align: 'start', label: tt('执行模式', 'Execution mode') })
}
export function pickWhere(app, anchor) {
    const at = whereOf(app)
    if (!at) return
    const places = app.life.places || [], own = at.kind === 'new'
    const folders = places.filter((p) => p.kind === 'folder'), others = places.filter((p) => ['browser', 'desktop'].includes(p.kind))
    const clean = (p) => (p.title || p.id).replace(/^folder\s*·\s*/i, '')
    const items = [
        { head: tt('项目', 'Project') },
        { label: tt('无项目', 'No project'), sub: '', checked: !at.place, run: () => setWhere(app, null) },
        ...folders.flatMap((p) => [
            { label: clean(p), sub: p.folder || '', icon: 'folder', checked: at.place === p.id && at.isolation !== 'worktree', run: () => setWhere(app, p.id) },
            ...(own && p.git ? [{ label: `${clean(p)} · Worktree`, sub: '', icon: 'branch', checked: at.place === p.id && at.isolation === 'worktree', run: () => setWhere(app, p.id, 'worktree') }] : []),
        ]),
        { label: tt('打开文件夹…', 'Open folder…'), icon: 'folderPlus', run: () => openFolder(app) },
        ...(others.length ? [{ head: tt('环境', 'Places') }] : []),
        ...others.map((p) => ({ label: p.title || p.id, icon: p.kind === 'browser' ? 'browser' : 'terminal', checked: at.place === p.id, run: () => setWhere(app, p.id) })),
    ]
    menu(anchor && document.contains(anchor) ? anchor : $('.pick.where'), items, { side: 'top', align: 'start', label: tt('项目', 'Project'), filter: folders.length > 8 ? tt('搜索项目', 'Find project') : '' })
}
// "Open folder": the folders of this computer, to walk through and choose one, as an editor's
// Open Folder (the host lists them: a page cannot read the paths of the computer itself).
export async function openFolder(app, { then } = {}) {
    const d = dialog(`<h5>${tt('打开文件夹', 'Open folder')}</h5>
<label><span>${tt('路径', 'Path')}</span><input class="field" data-path spellcheck="false" autocomplete="off" aria-label="${tt('文件夹的路径', 'The folder’s path')}"></label>
<div class="picks folders" data-list role="listbox" aria-label="${tt('里面的文件夹', 'Folders inside')}"></div>

<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('用这个文件夹', 'Use this folder')}</button></div>`)
    const path = d.querySelector('[data-path]'), list = d.querySelector('[data-list]'), res = d.querySelector('.res'), ok = d.querySelector('[data-default]')
    d.querySelector('[data-no]').onclick = closeDialog
    const show = async (where) => {
        const got = await get('/api/app/folders', where ? { path: where } : {})
        if (!d.isConnected) return
        if (!got) { const why = failed.get('/api/app/folders') || {}; res.innerHTML = `<span class="c-failed">✕ ${esc(why.error || tt('这个文件夹读不出来', 'That folder could not be read'))}</span>${why.fix ? `<small class="fix">${esc(why.fix)}</small>` : ''}`; return }
        res.innerHTML = ''
        path.value = got.path
        const rows = [...(got.parent ? [{ name: '..', path: got.parent, up: true }] : (got.roots || []).filter((r) => r !== got.path).map((r) => ({ name: r, path: r, up: true }))), ...got.folders]
        list.innerHTML = rows.map((f) => `<button type="button" class="opt" role="option" data-go="${esc(f.path)}">${icon(f.up ? 'up' : 'folder', 14)}<b>${esc(f.up && f.name === '..' ? tt('上一级', 'Up one level') : f.name)}</b>${f.git ? `<em>git</em>` : ''}</button>`).join('') || `<p class="note">${tt('里面没有文件夹。', 'No folders inside.')}</p>`
        list.scrollTop = 0
        ok.textContent = got.git ? tt('用这个文件夹（git 项目）', 'Use this folder (a git project)') : tt('用这个文件夹', 'Use this folder')
    }
    list.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) show(b.dataset.go) }
    list.onkeydown = (e) => {
        const all = [...list.querySelectorAll('[data-go]')], i = all.indexOf(document.activeElement)
        if (e.key === 'ArrowDown' && all[i + 1]) { e.preventDefault(); all[i + 1].focus() }
        else if (e.key === 'ArrowUp') { e.preventDefault(); (all[i - 1] || path).focus() }
    }
    path.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); show(path.value.trim()) }
        else if (e.key === 'ArrowDown' && list.querySelector('[data-go]')) { e.preventDefault(); list.querySelector('[data-go]').focus() }
    }
    ok.onclick = async () => {
        ok.disabled = true
        res.innerHTML = `<span class="spin"></span>${tt('正在接上这个项目…', 'connecting the project…')}`
        const r = await agent.places(app.identity.id, { action: 'project', folder: path.value.trim() })
        if (!r.ok) { ok.disabled = false; res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog()
        await app.refresh()
        if (then) return then(r.data.place)
        return setWhere(app, r.data.place)
    }
    // it opens beside the project this chat is on, else in the home folder
    const now = placeOf(app, (whereOf(app) || {}).place)
    await show(now && now.folder ? now.folder.replace(/[\\/][^\\/]+[\\/]?$/, '') : '')
    path.focus(); path.select()
}

// ── what the composer shows of the chat's state ──
export function draw(app) {
    const row = chatRow(app), a = area()
    if (!a) return
    const busy = app.busy(app.chat)
    const modeBtn = $('.pg-compose .mode')
    if (modeBtn) {
        const curMode = row.mode || 'auto'
        const mInfo = MODES.find((x) => x[0] === curMode) || MODES[0]
        const mHtml = `${icon(mInfo[3], 13)}<span>${esc(tt(mInfo[1], mInfo[2]))}</span>`
        if (modeBtn._html !== mHtml) { modeBtn.innerHTML = mHtml; modeBtn._html = mHtml }
        modeBtn.classList.toggle('own', curMode !== 'auto')
    }
    const where = $('.pg-compose .where'), at = whereOf(app)
    where.hidden = !at
    if (at) {
        const p = placeOf(app, at.place)
        const name = p ? (p.title || p.id).replace(/^folder\s*·\s*/i, '') : ''
        const label = !p ? tt('无项目', 'No project') : `${name}${at.isolation === 'worktree' ? ' · Worktree' : ''}`
        const html = `${icon(p ? (at.isolation === 'worktree' ? 'branch' : ({ folder: 'folder', browser: 'browser', desktop: 'terminal' })[p.kind] || 'folder') : 'folder', 13)}<span>${esc(label)}</span>`
        if (where._html !== html) { where.innerHTML = html; where._html = html }
        where.classList.toggle('own', !!p)
        where.dataset.tip = !p ? tt('项目', 'Project')
            : at.isolation === 'worktree' ? `Worktree · ${at.branch || ''}`
                : p.folder || name
    }
    a.disabled = row.kind === 'earlier'
    a.placeholder = row.kind === 'earlier' ? tt('只读对话', 'Read-only') : busy ? tt('继续补充…', 'Add a follow-up…') : tt('输入消息，@ 引用文件，/ 调起命令…', 'Ask anything, @ for files, / for commands…')
    $('.pg-compose .stop').hidden = !busy
    const sendButton = $('.pg-compose .send')
    sendButton.dataset.tip = busy ? tt('排队发送', 'Queue message') : tt('发送', 'Send')
    sendButton.setAttribute('aria-label', sendButton.dataset.tip)
    // until the models were read once, nothing is said about them (a host that does not answer is not "no model")
    const model = $('.pick.model'), m = current(app), usable = !sources.read || (ready() && !!m)
    model.textContent = !sources.read ? tt('模型', 'Model') : usable ? shownName(m) : tt('选择模型', 'Select model')
    // the button names the model; where it comes from is its tip
    model.dataset.tip = usable && m ? `${shownName(m)} · ${models.sourceLabel(m)}` : tt('模型', 'Model')
    if (usable && m) describe(app, m)
    model.classList.toggle('warn', !usable)
    model.classList.toggle('own', !!row.model)
    const effort = $('.pick.effort')
    effort.hidden = !usable || !m || !(m.efforts || []).length
    if (!effort.hidden) { effort.textContent = models.effortLabel(row.effort || 'default'); effort.dataset.tip = `${tt('思考强度', 'Reasoning effort')} · ${shownName(m)}` }
    // beside the composer: what is still missing before it can answer
    const notice = $('.pg-notice')
    notice.hidden = usable
    const html = usable ? '' : `${icon('alert', 14)}<span>${esc(tt('还没有可用的模型', 'No model is usable yet'))}</span><button type="button" class="b" data-act="model-choose">${esc(tt('选一个模型', 'Choose a model'))}</button>`
    if (notice._html !== html) { notice.innerHTML = html; notice._html = html }
    drawQueue(app)
}
export const modelOf = (app) => { const m = current(app); return m ? { name: shownName(m), id: m.model || '', source: models.sourceLabel(m), usable: ready() } : { name: sources.read ? tt('选一个模型', 'Choose a model') : '', id: '', usable: !sources.read } }
