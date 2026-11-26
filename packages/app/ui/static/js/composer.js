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
import { get, failed, agent } from './api.js'
import { $, ic, toast, said, menu, confirm } from './ui.js'
import { icon } from './icons.js'
import { perChat } from './prefs.js'
import { label } from './keys.js'
import { choiceLabel } from './names.js'
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
    <form class="pg-compose"><div class="pg-atts" hidden></div><textarea rows="1" placeholder="${tt('告诉它要做什么', 'Tell it what to do')}" aria-label="${tt('给它的消息', 'Message to it')}"></textarea>
      <div class="pg-tools">${ic('plus', tt('添加文件', 'Attach files'), { act: 'attach' })}<input type="file" multiple hidden tabindex="-1" aria-hidden="true"><select class="pick ws" aria-label="${tt('在哪里做', 'Where to work')}" data-tip="${tt('在哪里做', 'Where to work')}"></select><span class="grow"></span>`
        + `<button type="button" class="pick model" data-act="model-pick" data-tip="${tt('这个对话用的模型', "This chat's model")}"></button><button type="button" class="pick effort" data-act="effort-pick" data-tip="${tt('思考强度', 'Reasoning effort')}" hidden></button>`
        + `<button type="button" class="stop" data-act="turn-stop" aria-label="${tt('停下', 'Stop')}" data-tip="${tt('停下这一回合', 'Stop this turn')}" data-keys="Esc" hidden>${icon('stop')}</button>`
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
    const ws = $('.pg-compose .ws')
    const r = await agent.say(app.identity.id, chat, text, { ...(ws.hidden || !ws.value ? {} : { place: ws.value }), ...(files.length ? { files: files.map((f) => f.id) } : {}) })
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
const effortSpec = (app) => ((app.schema || {}).model || {}).reasoning_effort || {}
const entry = (id) => sources.models.find((m) => m.id === id)
const defaultEntry = () => { const llm = (sources.status || {}).llm || {}; return entry(llm.id) || (llm.model ? llm : null) }
// A model as people read it; an agent under the owner's plan goes by its own name.
function shownName(m) {
    if (!m) return ''
    if (String(m.provider || '').startsWith('acp:') && (!m.model || m.model === 'default')) return m.name && m.name !== 'default' ? m.name : m.provider.slice(4)
    return modelName(m.model) || m.name || ''
}
function sourceNote(m) {
    const provider = String(m.provider || '')
    if (provider.startsWith('acp:')) return tt('这台电脑上已登录的 agent · 用你自己的订阅', 'an agent signed in on this computer · your own plan')
    if (((sources.found || {}).local || []).some((l) => l.provider === provider)) return tt('这台电脑上的模型', 'a model on this computer')
    const known = (((sources.status || {}).providers) || []).find((p) => p.id === provider)
    return `${known ? known.name : provider} · key`
}
const ready = () => { const llm = (sources.status || {}).llm; return !llm || llm.ready !== false }
const current = (app) => entry(chatRow(app).model) || defaultEntry()

export async function pickModel(app, anchor) {
    // the list as last read opens at once; it is read again for the next time
    if (sources.read) loadSources({ found: true })
    else if (!(await loadSources({ found: true }))) return said(failed.get('/api/app/models'), tt('模型列表没有读出来', 'The models could not be read'))
    const row = chatRow(app), base = defaultEntry()
    const listed = sources.models.filter((m) => m.enabled !== false)
    const has = (provider, model) => sources.models.some((m) => m.provider === provider && (m.model || 'default') === (model || 'default'))
    const f = sources.found || {}
    const fresh = [...(f.agents || []).filter(onboarding.agentUsable).map((a) => ({ provider: a.provider, model: a.model, title: a.name })), ...(f.keys || []).map((k) => ({ provider: k.provider, model: k.model, title: `${k.name}${k.model ? ' · ' + modelName(k.model) : ''}` })),
        ...(f.local || []).map((l) => ({ provider: l.provider, model: l.model, title: l.model }))].filter((s) => s.model && !has(s.provider, s.model))
    const setUp = () => onboarding.modelDialog(app, { after: () => app.refresh() })
    const items = [
        { head: tt('这个对话用哪个模型', 'The model of this chat') },
        { label: tt(`默认${base ? ' · ' + shownName(base) : ''}`, `Default${base ? ' · ' + shownName(base) : ''}`), sub: tt('新对话用的那个；在 设置 › 模型 里改', 'what new chats use; Settings › Model changes it'), checked: !row.model, run: () => choose(app, null) },
        ...listed.map((m) => ({ label: shownName(m), sub: sourceNote(m), checked: row.model === m.id, run: () => choose(app, m.id) })),
        ...(fresh.length ? [{ head: tt('在这台电脑上找到，还没设好', 'Found on this computer, not set up yet') }] : []),
        ...fresh.map((s) => ({ label: s.title, sub: tt('试一次并设为默认…', 'try it once and make it the default…'), icon: 'plus', run: setUp })),
        '-',
        { label: tt('添加模型或提供商…', 'Add a model or a provider…'), icon: 'plus', run: setUp },
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
    const r = await agent.chatsAct(app.identity.id, 'model', chat, { model: id || null, ...(effort !== undefined ? { effort } : {}) })
    if (!r.ok) return said(r, tt('没换成', 'The model was not changed'))
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app); app.kick()
    if (!same) toast(tt(`这个对话现在用 ${shownName(entry(id) || defaultEntry())}`, `This chat now uses ${shownName(entry(id) || defaultEntry())}`))
}
export function pickEffort(app, anchor) {
    const row = chatRow(app), m = current(app) || {}
    menu(anchor, [{ head: tt('思考强度 · 这个对话', 'Reasoning effort · this chat') },
        ...['default', ...(m.efforts || [])].map((e) => ({ label: choiceLabel(effortSpec(app), e), checked: (row.effort || 'default') === e, run: () => choose(app, row.model || null, e === 'default' ? null : e) }))],
    { side: 'top', align: 'end' })
}

// ── what the composer shows of the chat's state ──
export function draw(app) {
    const row = chatRow(app), a = area()
    if (!a) return
    const busy = app.busy(app.chat)
    // the workspace picker only where the owner gives work: not in a place's own chat
    const ws = $('.pg-compose .ws'), place = row.kind === 'place' || row.kind === 'earlier'
    // where the owner's work is done: a folder, the browser or the desktop that is connected; nowhere in particular unless one is picked
    const workable = (app.life.places || []).filter((p) => ['folder', 'browser', 'desktop'].includes(p.kind))
    ws.hidden = place || !workable.length
    const options = `<option value="">${tt('在哪里做：它定', 'Where: it decides')}</option>` + workable.map((p) => `<option value="${esc(p.id)}">${esc(p.title || p.id)}</option>`).join('')
    if (ws._html !== options) { const choice = ws.value; ws.innerHTML = options; ws._html = options; if (choice) ws.value = choice }
    a.disabled = row.kind === 'earlier'
    a.placeholder = row.kind === 'earlier' ? tt('这个对话只能看', 'This chat can be read only') : busy ? tt('接着说：它做完手上的就看', 'Say more: it reads it when this turn is done') : tt('告诉它要做什么', 'Tell it what to do')
    $('.pg-compose .stop').hidden = !busy
    const sendButton = $('.pg-compose .send')
    sendButton.dataset.tip = busy ? tt('排队发送', 'Send to the queue') : tt('发送', 'Send')
    sendButton.setAttribute('aria-label', sendButton.dataset.tip)
    // until the models were read once, nothing is said about them (a host that does not answer is not "no model")
    const model = $('.pick.model'), m = current(app), usable = !sources.read || (ready() && !!m)
    model.textContent = !sources.read ? tt('模型', 'Model') : usable ? shownName(m) : tt('选一个模型', 'Choose a model')
    model.classList.toggle('warn', !usable)
    model.classList.toggle('own', !!row.model)
    const effort = $('.pick.effort')
    effort.hidden = !usable || !m || !(m.efforts || []).length
    if (!effort.hidden) effort.textContent = choiceLabel(effortSpec(app), row.effort || 'default')
    // beside the composer: what is still missing before it can answer
    const notice = $('.pg-notice')
    notice.hidden = usable
    const html = usable ? '' : `${icon('alert', 14)}<span>${esc(tt('还没有可用的模型，它现在答不了话。', 'No model is usable yet, so it cannot answer.'))}</span><button type="button" class="b" data-act="model-choose">${esc(tt('选一个模型', 'Choose a model'))}</button>`
    if (notice._html !== html) { notice.innerHTML = html; notice._html = html }
    drawQueue(app)
}
export const modelOf = (app) => { const m = current(app); return m ? { name: shownName(m), id: m.model || '', usable: ready() } : { name: sources.read ? tt('选一个模型', 'Choose a model') : '', id: '', usable: !sources.read } }
