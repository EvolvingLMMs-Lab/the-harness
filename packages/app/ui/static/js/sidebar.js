// The left column: New chat, Calendar, the chats, Settings and the identity at the bottom.
// The list is Hermes Desktop's session list ("Sessions & profiles", the left sidebar): search
// (the host looks in titles and in what was said), pinned chats first, archiving to keep the
// list short, rename and delete; each from the row's menu, the right mouse button or the
// keyboard (Shift+F10 the menu, F2 rename, Delete). The chats are the host's
// (GET/POST /api/agent/chats), the same ones the terminal shows; one made there appears here
// with the next reading of the list. The calendar's entry here is the plan's own.
import { esc, tt, when, usd } from './i18n.js'
import { agent, failed } from './api.js'
import { $, $$, ic, on, menu, said, toast, confirm, ask, loading, empty, problem } from './ui.js'
import { icon } from './icons.js'
import * as keys from './keys.js'

// Milliseconds after the last key before the host is asked to search.
const SEARCH_MS = 200

let q = '' // what the search field holds
let archived = false // the list shows the archived chats
let found = null // the host's answer for the search or the archived chats; null while it is read
let searching = null

export const title = (c) => (c.kind === 'main' ? tt('主对话', 'Main conversation') : c.title || c.chat)

export function frameHtml() {
    return `<aside class="pg-side" aria-label="${tt('对话', 'Chats')}">
  <div class="pg-top"><span class="pg-mode">The Harness</span>${ic('bell', tt('等你批准', 'Waiting for you'), { act: 'approvals-next', cls: 'bell' })}${ic('search', tt('搜索对话', 'Search chats'), { act: 'chats-search', keys: keys.keysOf('search-chats') })}${ic('sidebar', tt('收起左栏', 'Hide the sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar') })}</div>
  <button type="button" class="pg-new" data-act="chat-new" data-tip="${tt('新对话', 'New chat')}" data-keys="${keys.keysOf('new-chat')}">${icon('edit')}<span>${tt('新对话', 'New chat')}</span></button>
  <button type="button" class="pg-new cal" data-act="calendar">${icon('calendar')}<span>${tt('日历', 'Calendar')}</span></button>
  <input class="pg-find${q ? ' on' : ''}" type="search" value="${esc(q)}" placeholder="${tt('搜索标题和内容', 'Search titles and what was said')}" aria-label="${tt('搜索对话', 'Search chats')}">
  <div class="pg-lhead"><span></span><button type="button" data-act="chats-archived" aria-pressed="false"></button></div>
  <nav class="pg-list" aria-label="${tt('对话', 'Chats')}">${loading()}</nav>
  <div class="pg-foot"><div class="pg-upd" hidden></div><button type="button" class="set" data-act="settings" data-tip="${tt('设置', 'Settings')}" data-keys="${keys.keysOf('settings')}">${icon('settings')}<span>${tt('设置', 'Settings')}</span></button>
    <button type="button" class="pg-me" data-act="identity-menu" aria-label="${tt('切换身份', 'Switch identity')}"><div class="pg-avatar"></div><div><b></b><small></small></div></button></div>
</aside>`
}

const filtering = () => !!q || archived
// What the list asks the host for besides the chats themselves: the search or the archived ones.
export const query = () => (filtering() ? { q, archived } : null)
export function results(app, answer) {
    found = answer ? answer.chats || [] : found
    draw(app)
}
// A chat the list knows though it is not among the open ones (an archived chat that is open).
export const known = (chat) => (found || []).find((c) => c.chat === chat) || null
const rowOf = (app, chat) => app.chats.find((c) => c.chat === chat) || known(chat) || { chat, kind: 'new', title: chat }

export function mount(app) {
    const field = $('.pg-find'), list = $('.pg-list')
    field.oninput = () => {
        q = field.value.trim()
        found = filtering() ? null : found
        clearTimeout(searching)
        searching = setTimeout(() => app.refreshList(), SEARCH_MS)
        draw(app)
    }
    // the keyboard in the list: the arrows move, F2 renames, Delete deletes, Shift+F10 opens the menu
    list.addEventListener('keydown', (e) => {
        const row = e.target.closest('.pg-row')
        if (!row || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return
        const chat = row.dataset.chat, rows = $$('.pg-row', list)
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            const next = rows[rows.indexOf(row) + (e.key === 'ArrowDown' ? 1 : -1)]
            if (next) next.querySelector('.pg-chat').focus()
        } else if (e.key === 'F2') { e.preventDefault(); rename(app, chat) }
        else if (e.key === 'Delete') { e.preventDefault(); remove(app, chat) }
        else if ((e.key === 'F10' && e.shiftKey) || e.key === 'ContextMenu') { e.preventDefault(); chatMenu(app, chat, row.querySelector('.more')) }
    })
    list.addEventListener('contextmenu', (e) => {
        const row = e.target.closest('.pg-row')
        if (!row) return
        e.preventDefault()
        chatMenu(app, row.dataset.chat, row.querySelector('.more'), { x: e.clientX, y: e.clientY })
    })
}
export function actions(app) {
    on('chats-search', () => { const f = $('.pg-find'); if (f.classList.contains('on') && !f.value && document.activeElement === f) { f.classList.remove('on'); return } search(app) })
    on('chats-archived', () => { archived = !archived; found = filtering() ? null : found; draw(app); return app.refreshList() })
    on('chat-menu', (n) => chatMenu(app, n.dataset.arg, n))
    on('chats-retry', () => app.refreshList())
}

function rowHtml(app, c, busy) {
    const waiting = c.waiting === 'desktop' ? tt('等桌面', 'waiting for desktop') : c.waiting === 'approval' ? tt('等你批准', 'waits for you') : ''
    const shown = app.view === 'chat' && c.chat === app.chat
    const name = title(c)
    return `<div class="pg-row${shown ? ' on' : ''}" data-chat="${esc(c.chat)}">`
        + `<button type="button" class="pg-chat${shown ? ' on' : ''}${c.unread && !shown ? ' unread' : ''}${c.busy || busy.has(c.chat) ? ' busy' : ''}${waiting ? ' waiting' : ''}${c.kind === 'earlier' ? ' earlier' : ''}" data-act="chat-open" data-arg="${esc(c.chat)}"${shown ? ' aria-current="page"' : ''}>`
        + `<b>${c.pinned ? icon('pin', 12) : ''}<span>${esc(name)}</span></b><small>${esc(waiting || (q && c.match && c.match !== name ? c.match : when(c.updated)))}</small><span class="dot"></span></button>`
        + (c.kind === 'main' ? '' : ic('more', tt(`“${name}”的菜单`, `Menu of "${name}"`), { act: 'chat-menu', cls: 'more', attrs: `data-arg="${esc(c.chat)}"` })) + `</div>`
}

export function draw(app) {
    const list = $('.pg-list'); if (!list) return
    const busy = new Set(app.life.busy || [])
    const head = $('.pg-lhead span'), toggle = $('.pg-lhead button')
    head.textContent = archived ? tt('已归档', 'Archived') : q ? tt('搜索结果', 'Search results') : tt('对话', 'Chats')
    toggle.textContent = archived ? tt('回到对话', 'Back to chats') : tt('已归档', 'Archived')
    toggle.setAttribute('aria-pressed', archived ? 'true' : 'false')
    let html
    if (filtering()) {
        html = found === null ? loading(tt('正在找…', 'Searching…'))
            : found.length ? found.map((c) => rowHtml(app, c, busy)).join('')
                : q ? empty(tt(`没有对话匹配“${q}”`, `No chat matches "${q}"`), archived ? tt('在已归档的对话里找过了。', 'Looked in the archived chats.') : tt('标题和说过的话里都没有。已归档的对话要到"已归档"里找。', 'Neither a title nor what was said has it. Archived chats are searched under Archived.'))
                    : empty(tt('没有已归档的对话', 'No archived chats'), tt('归档一个对话，它就从列表里收到这里。', 'Archive a chat and it moves from the list to here.'))
    } else if (!app.chats.length) {
        const why = failed.get('/api/agent/chats')
        html = why ? problem(why, { title: tt('对话列表没有读出来', 'The chats could not be read'), retry: 'chats-retry' }) : loading()
    } else {
        const pinned = app.chats.filter((c) => c.pinned && c.kind !== 'main'), rest = app.chats.filter((c) => !c.pinned || c.kind === 'main')
        const others = rest.filter((c) => c.kind !== 'main')
        html = rest.filter((c) => c.kind === 'main').map((c) => rowHtml(app, c, busy)).join('')
            + (pinned.length ? `<div class="pg-sub">${tt('置顶', 'Pinned')}</div>` + pinned.map((c) => rowHtml(app, c, busy)).join('') + (others.length ? `<div class="pg-sub">${tt('其他', 'Others')}</div>` : '') : '')
            + others.map((c) => rowHtml(app, c, busy)).join('')
    }
    if (list._html !== html) {
        // drawn again only when something changed, and the keyboard stays on the row it was on
        const at = document.activeElement && list.contains(document.activeElement) ? document.activeElement : null
        const where = at ? [at.closest('.pg-row') && at.closest('.pg-row').dataset.chat, at.classList.contains('more')] : null
        list._html = html; list.innerHTML = html
        if (where && where[0]) { const row = $$('.pg-row', list).find((r) => r.dataset.chat === where[0]); if (row) (row.querySelector(where[1] ? '.more' : '.pg-chat') || row.querySelector('.pg-chat')).focus() }
    }
    $('.pg-new.cal').classList.toggle('on', app.view === 'calendar')
    $('.pg-ic.bell').classList.toggle('ping', app.approvals.length > 0)
    const me = app.identity, places = (app.life.places || []).length
    $('.pg-me .pg-avatar').textContent = (me.name || me.id || '?').slice(0, 1).toUpperCase()
    $('.pg-me b').textContent = me.name || me.id
    $('.pg-me small').textContent = `${me.id} · ${tt(`${places} 个环境`, `${places} place${places === 1 ? '' : 's'}`)} · ${tt('今天', '')}${usd((app.usage.today || {}).cost_usd)}${tt('', ' today')}`
}

// Ctrl+Shift+F: the search field, with the keyboard in it.
export function search(app) {
    app.showSide()
    const f = $('.pg-find')
    f.classList.add('on'); f.focus(); f.select()
}
// Esc in the search field: the whole list again.
export function escape(app) {
    const f = $('.pg-find')
    if (document.activeElement !== f) return false
    clearTimeout(searching)
    f.value = ''; q = ''; f.classList.remove('on')
    if (!filtering()) found = null
    draw(app); app.refreshList()
    const current = $('.pg-chat.on') || $('.pg-chat')
    if (current) current.focus()
    return true
}

// ── what can be done with a chat ──
// One change of the list: the host answers with the list after it.
async function change(app, action, chat, more) {
    const r = await agent.chatsAct(app.identity.id, action, chat, more)
    if (!r.ok) { said(r); return false }
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    if (filtering()) found = (found || []).filter((c) => c.chat !== chat || action === 'rename' || action === 'pin' || action === 'unpin')
    draw(app)
    await app.refreshList()
    return true
}
export async function rename(app, chat) {
    const c = rowOf(app, chat)
    if (c.kind === 'main') return
    const name = await ask({ title: tt('给对话改名', 'Rename the chat'), label: tt('标题', 'Title'), value: title(c), yes: tt('改名', 'Rename') })
    if (name === null || !name || name === title(c)) return
    if (await change(app, 'rename', chat, { title: name })) app.redrawChat()
}
export async function remove(app, chat) {
    const c = rowOf(app, chat)
    if (c.kind === 'main') return
    const go = await confirm({ title: tt(`删除“${title(c)}”？`, `Delete "${title(c)}"?`), text: tt('这个对话的记录会被删掉，找不回来。想留着又不想看见它，可以归档。', "This chat's record is deleted for good. To keep it out of sight instead, archive it."), yes: tt('删除', 'Delete'), danger: true })
    if (!go) return
    const open = app.chat === chat
    if (await change(app, 'delete', chat) && open) await app.openChat('main')
}
async function archive(app, chat, away) {
    const open = app.chat === chat
    if (!(await change(app, away ? 'archive' : 'unarchive', chat))) return
    toast(away ? tt('已归档：在列表上方的"已归档"里', 'Archived: it is under Archived, above the list') : tt('已放回对话列表', 'Back in the list of chats'))
    if (away && open) await app.openChat('main')
}
function chatMenu(app, chat, anchor, point) {
    const c = rowOf(app, chat)
    if (c.kind === 'main') return
    menu(anchor, [
        c.pinned ? { label: tt('取消置顶', 'Unpin'), icon: 'pin', run: () => change(app, 'unpin', chat) } : { label: tt('置顶', 'Pin'), icon: 'pin', run: () => change(app, 'pin', chat) },
        { label: tt('改名…', 'Rename…'), icon: 'edit', keys: 'F2', run: () => rename(app, chat) },
        c.archived ? { label: tt('取消归档', 'Unarchive'), icon: 'archive', run: () => archive(app, chat, false) } : { label: tt('归档', 'Archive'), icon: 'archive', run: () => archive(app, chat, true) },
        '-',
        { label: tt('删除…', 'Delete…'), icon: 'trash', keys: keys.label('delete'), danger: true, run: () => remove(app, chat) },
    ], { label: title(c), point })
}

// The palette's entries for the chat that is open.
export function commands(app) {
    const c = rowOf(app, app.chat)
    if (app.view !== 'chat' || c.kind === 'main') return []
    const group = tt('这个对话', 'This chat')
    return [
        { title: tt('给这个对话改名…', 'Rename this chat…'), group, icon: 'edit', run: () => rename(app, c.chat) },
        { title: c.pinned ? tt('取消置顶这个对话', 'Unpin this chat') : tt('置顶这个对话', 'Pin this chat'), group, icon: 'pin', run: () => change(app, c.pinned ? 'unpin' : 'pin', c.chat) },
        { title: c.archived ? tt('取消归档这个对话', 'Unarchive this chat') : tt('归档这个对话', 'Archive this chat'), group, icon: 'archive', run: () => archive(app, c.chat, !c.archived) },
        { title: tt('删除这个对话…', 'Delete this chat…'), group, icon: 'trash', run: () => remove(app, c.chat) },
    ]
}
