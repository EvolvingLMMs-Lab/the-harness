// The left column: New chat, Calendar, the chats, Settings and the identity at the bottom.
// The list is Hermes Desktop's session list ("Sessions & profiles", the left sidebar): search
// (the host looks in titles and in what was said), pinned chats first, archiving to keep the
// list short, rename and delete; each from the row's menu, the right mouse button or the
// keyboard (Shift+F10 the menu, F2 rename, Delete). The chats are the host's
// (GET/POST /api/agent/chats), the same ones the terminal shows; one made there appears here
// with the next reading of the list. The calendar's entry here is the plan's own.
import { esc, tt, when } from './i18n.js'
import { agent, failed } from './api.js'
import { $, $$, ic, on, menu, said, toast, confirm, ask, loading, empty, problem } from './ui.js'
import { icon } from './icons.js'
import { prefs } from './prefs.js'
import * as keys from './keys.js'

// Milliseconds after the last key before the host is asked to search.
const SEARCH_MS = 200

let q = '' // what the search field holds
let archived = false // the list shows the archived chats
let found = null // the host's answer for the search or the archived chats; null while it is read
let searching = null

const DEFAULT_VIEW = { groupBy: 'project', sortChats: 'updated', sortProjects: 'custom', filter: 'all' }
const viewPrefs = () => ({ ...DEFAULT_VIEW, ...(prefs.get('side.view', {}) || {}) })
function setViewPref(patch) {
    prefs.set('side.view', { ...viewPrefs(), ...patch })
}
function hasCustomView() {
    const v = viewPrefs()
    return archived || v.groupBy !== 'project' || v.sortChats !== 'updated' || v.sortProjects !== 'custom' || v.filter !== 'all'
}

const closedProjects = () => new Set(prefs.get('proj.closed', []))
function toggleProject(id) {
    const set = closedProjects()
    if (set.has(id)) set.delete(id)
    else set.add(id)
    prefs.set('proj.closed', [...set])
}
export function expandProject(id) {
    if (!id) return
    const set = closedProjects()
    if (set.delete(id)) prefs.set('proj.closed', [...set])
}

export const title = (c) => (c.kind === 'main' ? tt('主对话', 'Main') : c.title || c.chat)

export function frameHtml() {
    return `<aside class="pg-side" aria-label="${tt('导航', 'Navigation')}">
  <div class="pg-top">
    ${ic('sidebar', tt('收起左栏', 'Hide sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar') })}
    ${ic('arrowLeft', tt('上一个对话', 'Back'), { act: 'nav-back', keys: keys.keysOf('nav-back'), cls: 'nav-back', attrs: 'disabled' })}
    ${ic('arrowRight', tt('下一个对话', 'Forward'), { act: 'nav-forward', keys: keys.keysOf('nav-forward'), cls: 'nav-fwd', attrs: 'disabled' })}
    <span class="grow"></span>
    ${ic('bell', tt('等你批准', 'Pending approvals'), { act: 'approvals-next', cls: 'bell' })}
    ${ic('search', tt('搜索对话', 'Search chats'), { act: 'chats-search', keys: keys.keysOf('search-chats') })}
  </div>
  <div class="pg-nav">
    <button type="button" class="pg-new primary-nav" data-act="chat-new" data-tip="${tt('新对话', 'New Conversation')}" data-keys="${keys.keysOf('new-chat')}">${icon('plus', 15)}<span>${tt('新对话', 'New Conversation')}</span></button>
    <button type="button" class="pg-new cal" data-act="calendar">${icon('calendar', 15)}<span>${tt('日历', 'Calendar')}</span></button>
    <button type="button" class="pg-new cust" data-act="customizations">${icon('sliders', 15)}<span>${tt('自定义', 'Customizations')}</span></button>
  </div>
  <input class="pg-find${q ? ' on' : ''}" type="search" value="${esc(q)}" placeholder="${tt('搜索标题和内容', 'Search titles and messages')}" aria-label="${tt('搜索对话', 'Search chats')}">
  <nav class="pg-list" aria-label="${tt('项目与对话', 'Projects and conversations')}">${loading()}</nav>
  <div class="pg-foot"><div class="pg-upd" hidden></div><button type="button" class="set" data-act="settings" data-tip="${tt('设置', 'Settings')}" data-keys="${keys.keysOf('settings')}">${icon('settings', 15)}<span>${tt('设置', 'Settings')}</span></button>
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
    on('chats-filter', (n) => filterMenu(app, n))
    on('chats-filter-reset', () => { archived = false; prefs.set('side.view', { ...DEFAULT_VIEW }); found = filtering() ? null : found; draw(app); return app.refreshList() })
    on('chat-menu', (n) => chatMenu(app, n.dataset.arg, n))
    on('chats-retry', () => app.refreshList())
    on('project-toggle', (n) => { toggleProject(n.dataset.arg); draw(app) })
    on('project-menu', (n) => projectMenu(app, n.dataset.arg, n))
}

function filterMenu(app, anchor) {
    const v = viewPrefs()
    const pick = (patch) => () => { setViewPref(patch); draw(app) }
    const unread = (app.chats || []).filter((c) => c.unread && c.chat !== app.chat)
    menu(anchor, [
        { head: tt('分组方式', 'Group By') },
        { label: tt('按项目分组', 'Project'), checked: v.groupBy === 'project', run: pick({ groupBy: 'project' }) },
        { label: tt('全部平铺', 'Flat list'), checked: v.groupBy === 'none', run: pick({ groupBy: 'none' }) },
        { head: tt('对话排序', 'Sort Conversations') },
        { label: tt('最近更新', 'Last Updated'), checked: v.sortChats === 'updated', run: pick({ sortChats: 'updated' }) },
        { label: tt('创建时间', 'Created'), checked: v.sortChats === 'created', run: pick({ sortChats: 'created' }) },
        { label: tt('标题名称', 'Title'), checked: v.sortChats === 'title', run: pick({ sortChats: 'title' }) },
        { head: tt('项目排序', 'Sort Projects') },
        { label: tt('默认顺序', 'Custom Order'), checked: v.sortProjects === 'custom', run: pick({ sortProjects: 'custom' }) },
        { label: tt('最近活跃', 'Last Updated'), checked: v.sortProjects === 'updated', run: pick({ sortProjects: 'updated' }) },
        { label: tt('名称排序', 'Name'), checked: v.sortProjects === 'name', run: pick({ sortProjects: 'name' }) },
        { head: tt('筛选', 'Filter') },
        { label: tt('全部对话', 'All'), checked: v.filter === 'all', run: pick({ filter: 'all' }) },
        { label: tt('仅未读', 'Unread'), checked: v.filter === 'unread', run: pick({ filter: 'unread' }) },
        { label: tt('进行中', 'Running'), checked: v.filter === 'busy', run: pick({ filter: 'busy' }) },
        { label: tt('仅置顶', 'Pinned'), checked: v.filter === 'pinned', run: pick({ filter: 'pinned' }) },
        '-',
        { label: tt('仅看已归档', 'Archived Only'), checked: archived, run: () => { archived = !archived; found = filtering() ? null : found; draw(app); app.refreshList() } },
        ...(hasCustomView() ? [{ label: tt('重置筛选与排序', 'Reset filters'), icon: 'retry', run: () => { archived = false; prefs.set('side.view', { ...DEFAULT_VIEW }); found = filtering() ? null : found; draw(app); app.refreshList() } }] : []),
        '-',
        { label: unread.length ? tt(`全部标为已读 (${unread.length})`, `Mark All as Read (${unread.length})`) : tt('全部标为已读', 'Mark All as Read'), icon: 'check', disabled: !unread.length, run: async () => {
            await Promise.all(unread.map((c) => agent.opened(app.identity.id, c.chat)))
            await app.refreshList()
            toast(tt('已全部标为已读', 'Marked all as read'))
        } },
    ], { align: 'end', label: tt('筛选与排序', 'Filter & Sort') })
}

function compactAge(seconds) {
    if (!seconds) return ''
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - seconds))
    if (diff < 60) return tt('刚刚', 'now')
    if (diff < 3600) return `${Math.floor(diff / 60)}m`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d`
    return when(seconds)
}

function rowHtml(app, c, busy, extraCls = '') {
    const waiting = c.waiting === 'desktop' ? tt('等桌面', 'desktop') : c.waiting === 'approval' ? tt('待批', 'approve') : ''
    const shown = app.view === 'chat' && !app.section && c.chat === app.chat
    const name = title(c)
    const isBusy = !!(c.busy || busy.has(c.chat))
    const isUnread = !!(c.unread && !shown)
    const tag = c.isolation === 'worktree' ? `<span class="wt-tag" data-tip="${esc(c.branch || 'worktree')}">${icon('branch', 11)}</span>` : ''
    const rightMeta = waiting
        ? `<span class="chat-meta is-wait">${esc(waiting)}</span>`
        : isBusy
            ? `<span class="chat-meta is-busy" aria-label="${tt('运行中', 'Running')}">⠿</span>`
            : isUnread
                ? `<span class="chat-meta"><span class="dot"></span></span>`
                : `<span class="chat-meta">${esc(compactAge(c.updated))}</span>`
    const matchLine = q && c.match && c.match !== name ? `<small class="chat-match">${esc(c.match)}</small>` : ''
    return `<div class="pg-row${shown ? ' on' : ''}${extraCls ? ' ' + extraCls : ''}" data-chat="${esc(c.chat)}">`
        + `<button type="button" class="pg-chat${shown ? ' on' : ''}${isUnread ? ' unread' : ''}${isBusy ? ' busy' : ''}${waiting ? ' waiting' : ''}${c.kind === 'earlier' ? ' earlier' : ''}${matchLine ? ' has-match' : ''}" data-act="chat-open" data-arg="${esc(c.chat)}"${shown ? ' aria-current="page"' : ''}>`
        + `<span class="chat-line">${c.pinned ? `<span class="pin-ic">${icon('pin', 11)}</span>` : ''}${tag}<span class="chat-name">${esc(name)}</span>${rightMeta}</span>${matchLine}</button>`
        + (c.kind === 'main' ? '' : ic('more', tt(`“${name}”的菜单`, `Menu of "${name}"`), { act: 'chat-menu', cls: 'more', attrs: `data-arg="${esc(c.chat)}"` })) + `</div>`
}

function projectMenu(app, placeId, anchor) {
    const p = (app.life.places || []).find((x) => x.id === placeId)
    if (!p) return
    menu(anchor, [
        { label: tt('在此项目新建对话', 'New conversation'), icon: 'plus', run: () => app.newProjectChat(placeId) },
        ...(p.git ? [{ label: tt('新建隔离分支对话 (Worktree)', 'New worktree conversation'), icon: 'branch', run: () => app.newProjectChat(placeId, 'worktree') }] : []),
        ...(p.kind === 'ssh' ? [{ label: tt('在此主机打开其他目录…', 'Open folder on this host…'), icon: 'folderPlus', run: () => app.openSshFolder && app.openSshFolder(p) }] : []),
        '-',
        { label: tt('从项目列表移除', 'Remove project'), icon: 'trash', danger: true, run: async () => {
            const r = await agent.places(app.identity.id, { action: 'disconnect', place: placeId })
            if (!r.ok) return said(r)
            await app.refreshList()
        } },
    ], { label: p.title || placeId })
}

export function draw(app) {
    const list = $('.pg-list'); if (!list) return
    const busy = new Set(app.life.busy || [])
    let html
    if (filtering()) {
        const hdr = `<div class="pg-sec"><span>${archived ? tt('已归档', 'Archived') : tt('搜索结果', 'Search results')}</span><button type="button" class="sec-txt" data-act="chats-archived" aria-pressed="${archived}">${archived ? tt('返回', 'Back') : tt('已归档', 'Archived')}</button></div>`
        html = hdr + (found === null ? loading(tt('正在找…', 'Searching…'))
            : found.length ? found.map((c) => rowHtml(app, c, busy)).join('')
                : q ? empty(tt(`没有对话匹配“${q}”`, `No matches for "${q}"`), '')
                    : empty(tt('没有已归档的对话', 'No archived conversations'), ''))
    } else if (!app.chats.length) {
        const why = failed.get('/api/agent/chats')
        html = why ? problem(why, { title: tt('对话列表没有读出来', 'Could not load conversations'), retry: 'chats-retry' }) : loading()
    } else {
        const v = viewPrefs()
        const matchesFilter = (c) => {
            if (v.filter === 'unread') return !!(c.unread && c.chat !== app.chat)
            if (v.filter === 'busy') return !!(c.busy || busy.has(c.chat))
            if (v.filter === 'pinned') return !!c.pinned
            return true
        }
        const sortChatsList = (arr) => [...arr].sort((a, b) => {
            if (v.sortChats === 'title') return title(a).localeCompare(title(b))
            if (v.sortChats === 'created') return (b.created || b.updated || 0) - (a.created || a.updated || 0)
            return (b.updated || 0) - (a.updated || 0)
        })
        const mainRows = app.chats.filter((c) => c.kind === 'main')
        const nonMain = app.chats.filter((c) => c.kind !== 'main').filter(matchesFilter)
        // All connected local folders and SSH remote projects are first-class items
        const rawProjects = (app.life.places || []).filter((p) => p.kind === 'folder' || p.kind === 'ssh')
        const byProject = new Map(rawProjects.map((p) => [p.id, []]))
        const loosePinned = []
        const loose = []
        const pinnedFirst = (arr) => [...sortChatsList(arr.filter((c) => c.pinned)), ...sortChatsList(arr.filter((c) => !c.pinned))]
        for (const c of nonMain) {
            // Permanently hide backend-created folder/ssh place event-log rows unless directly opened
            if (c.kind === 'place' && c.place && byProject.has(c.place)) {
                if (c.chat === app.chat) byProject.get(c.place).push(c)
                continue
            }
            if (c.place && byProject.has(c.place)) byProject.get(c.place).push(c)
            else if (c.pinned) loosePinned.push(c)
            else loose.push(c)
        }
        for (const [pid, arr] of byProject.entries()) byProject.set(pid, pinnedFirst(arr))
        const pinnedLoose = sortChatsList(loosePinned)
        const restLoose = sortChatsList(loose)
        const folderPlaces = [...rawProjects].sort((a, b) => {
            if (v.sortProjects === 'name') {
                const la = (a.title || a.id).replace(/^(folder|ssh)\s*·\s*/i, '')
                const lb = (b.title || b.id).replace(/^(folder|ssh)\s*·\s*/i, '')
                return la.localeCompare(lb)
            }
            if (v.sortProjects === 'updated') {
                const ua = Math.max(0, ...(byProject.get(a.id) || []).map((c) => c.updated || 0))
                const ub = Math.max(0, ...(byProject.get(b.id) || []).map((c) => c.updated || 0))
                return ub - ua
            }
            return 0
        })
        const filterActive = hasCustomView()
        const filterTagMap = {
            unread: tt('仅未读', 'Unread'),
            busy: tt('进行中', 'Running'),
            pinned: tt('仅置顶', 'Pinned'),
        }
        const activeBits = [
            v.filter !== 'all' ? filterTagMap[v.filter] : '',
            v.groupBy === 'none' ? tt('平铺', 'Flat') : '',
            v.sortChats === 'created' ? tt('按创建', 'Created') : v.sortChats === 'title' ? tt('按名称', 'A–Z') : '',
        ].filter(Boolean)
        const filterBar = activeBits.length
            ? `<div class="pg-filter-bar"><span>${esc(activeBits.join(' · '))}</span><button type="button" data-act="chats-filter-reset">${tt('重置', 'Reset')}</button></div>`
            : ''
        const closed = closedProjects()
        const projHeader = `<div class="pg-sec"><span>${tt('项目', 'Projects')}</span>`
            + `<span class="sec-acts">${ic('filter', tt('筛选与排序', 'Filter & Sort'), { act: 'chats-filter', cls: filterActive ? 'filter-btn on' : 'filter-btn' })}${ic('server', tt('连接 SSH 远程项目', 'Connect SSH project'), { act: 'project-open-ssh' })}${ic('folderPlus', tt('打开本地文件夹', 'Open local folder'), { act: 'project-open-folder' })}</span></div>`
        let projectsHtml = ''
        let convsHtml = ''
        if (v.groupBy === 'none') {
            const visibleAll = sortChatsList(nonMain.filter((c) => !(c.kind === 'place' && c.place && byProject.has(c.place) && c.chat !== app.chat)))
            const flatPinned = visibleAll.filter((c) => c.pinned)
            const flatRest = visibleAll.filter((c) => !c.pinned)
            projectsHtml = projHeader + filterBar
            convsHtml = `<div class="pg-sec"><span>${tt('对话', 'Conversations')}</span>`
                + `<span class="sec-acts">${ic('plus', tt('新建对话', 'New conversation'), { act: 'chat-new-loose' })}</span></div>`
                + (flatPinned.length ? `<div class="pg-sub">${tt('置顶', 'Pinned')}</div>` + flatPinned.map((c) => rowHtml(app, c, busy)).join('') : '')
                + (flatRest.length ? flatRest.map((c) => rowHtml(app, c, busy)).join('') : (!flatPinned.length ? empty(tt('没有符合筛选条件的对话', 'No matching conversations'), '') : ''))
        } else {
            projectsHtml = projHeader + filterBar
                + (folderPlaces.length
                    ? folderPlaces.map((p) => {
                        const chats = byProject.get(p.id) || []
                        if (v.filter !== 'all' && !chats.length) return ''
                        const isClosed = closed.has(p.id)
                        const label = (p.title || p.id).replace(/^(folder|ssh)\s*·\s*/i, '')
                        const tip = p.kind === 'ssh' ? `SSH · ${p.target || p.host}:${p.folder || '~'}` : (p.folder || '')
                        const bodyRows = isClosed
                            ? ''
                            : chats.length
                                ? chats.map((c) => rowHtml(app, c, busy, 'in-proj')).join('')
                                : `<button type="button" class="pg-proj-none" data-act="project-new-chat" data-arg="${esc(p.id)}">${tt('暂无对话', 'No conversations yet')}</button>`
                        return `<div class="pg-proj${isClosed ? ' closed' : ''}" data-project="${esc(p.id)}">`
                            + `<div class="pg-proj-head" title="${esc(tip)}">`
                            + `<button type="button" class="proj-tog" data-act="project-toggle" data-arg="${esc(p.id)}" aria-expanded="${!isClosed}">${icon(isClosed ? 'right' : 'down', 11)}${icon(p.kind === 'ssh' ? 'server' : 'folder', 13)}<span>${esc(label)}</span></button>`
                            + `<span class="proj-acts">${ic('plus', tt(`在 ${label} 新建对话`, `New chat in ${label}`), { act: 'project-new-chat', cls: 'pa', attrs: `data-arg="${esc(p.id)}"` })}${ic('more', tt(`${label} 菜单`, `${label} menu`), { act: 'project-menu', cls: 'pa', attrs: `data-arg="${esc(p.id)}"` })}</span></div>`
                            + bodyRows
                            + `</div>`
                    }).join('')
                    : `<button type="button" class="pg-proj-empty" data-act="project-open-folder">${icon('folderPlus', 13)}<span>${tt('打开文件夹…', 'Open folder…')}</span></button>`
                    + `<button type="button" class="pg-proj-empty" data-act="project-open-ssh">${icon('server', 13)}<span>${tt('连接 SSH 项目…', 'Connect SSH…')}</span></button>`)

            convsHtml = `<div class="pg-sec"><span>${tt('对话', 'Conversations')}</span>`
                + `<span class="sec-acts">${ic('plus', tt('新建对话', 'New conversation'), { act: 'chat-new-loose' })}</span></div>`
                + (pinnedLoose.length ? `<div class="pg-sub">${tt('置顶', 'Pinned')}</div>` + pinnedLoose.map((c) => rowHtml(app, c, busy)).join('') : '')
                + (restLoose.length ? restLoose.map((c) => rowHtml(app, c, busy)).join('') : '')
        }

        html = mainRows.map((c) => rowHtml(app, c, busy, 'main-row')).join('')
            + projectsHtml
            + convsHtml
    }
    if (list._html !== html) {
        // drawn again only when something changed, and the keyboard stays on the row it was on
        const at = document.activeElement && list.contains(document.activeElement) ? document.activeElement : null
        const where = at ? [at.closest('.pg-row') && at.closest('.pg-row').dataset.chat, at.classList.contains('more')] : null
        list._html = html; list.innerHTML = html
        if (where && where[0]) { const row = $$('.pg-row', list).find((r) => r.dataset.chat === where[0]); if (row) (row.querySelector(where[1] ? '.more' : '.pg-chat') || row.querySelector('.pg-chat')).focus() }
    }
    const backBtn = $('.pg-top .nav-back'), fwdBtn = $('.pg-top .nav-fwd')
    if (backBtn) backBtn.disabled = !(app.canNavBack && app.canNavBack())
    if (fwdBtn) fwdBtn.disabled = !(app.canNavForward && app.canNavForward())
    const calBtn = $('.pg-new.cal'), custBtn = $('.pg-new.cust')
    if (calBtn) calBtn.classList.toggle('on', app.view === 'calendar' && !app.section)
    if (custBtn) custBtn.classList.toggle('on', app.view === 'customizations' && !app.section)
    $('.pg-ic.bell').classList.toggle('ping', app.approvals.length > 0)
    const me = app.identity
    $('.pg-me .pg-avatar').textContent = (me.name || me.id || '?').slice(0, 1).toUpperCase()
    $('.pg-me b').textContent = me.name || me.id
    $('.pg-me small').textContent = me.name && me.name !== me.id ? me.id : ''
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
    const go = await confirm({ title: tt(`删除“${title(c)}”？`, `Delete "${title(c)}"?`), text: tt('这个对话的记录会被删掉，找不回来。', 'The record of this chat is deleted and cannot be brought back.'), yes: tt('删除', 'Delete'), danger: true })
    if (!go) return
    const open = app.chat === chat
    if (await change(app, 'delete', chat) && open) await app.openChat('main')
}
async function archive(app, chat, away) {
    const open = app.chat === chat
    if (!(await change(app, away ? 'archive' : 'unarchive', chat))) return
    toast(away ? tt('已归档', 'Archived') : tt('已放回对话列表', 'Back in the list of chats'))
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
