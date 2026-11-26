// The left column: New chat, Calendar, the chats, Settings and the identity at the bottom.
import { esc, tt, when, usd } from './i18n.js'
import { $, ic, on } from './ui.js'
import { icon } from './icons.js'
import * as keys from './keys.js'

let find = '' // what the search field holds

export const title = (c) => (c.kind === 'main' ? tt('主对话', 'Main conversation') : c.title || c.chat)

export function frameHtml() {
    return `<aside class="pg-side" aria-label="${tt('对话', 'Chats')}">
  <div class="pg-top"><span class="pg-mode">The Harness</span>${ic('bell', tt('等你批准', 'Waiting for you'), { act: 'approvals-next', cls: 'bell' })}${ic('search', tt('搜索对话', 'Search chats'), { act: 'chats-search', keys: keys.keysOf('search-chats') })}${ic('sidebar', tt('收起左栏', 'Hide the sidebar'), { act: 'side-toggle', keys: keys.keysOf('sidebar') })}</div>
  <button type="button" class="pg-new" data-act="chat-new" data-tip="${tt('新对话', 'New chat')}" data-keys="${keys.keysOf('new-chat')}">${icon('edit')}<span>${tt('新对话', 'New chat')}</span></button>
  <button type="button" class="pg-new cal" data-act="calendar">${icon('calendar')}<span>${tt('日历', 'Calendar')}</span></button>
  <input class="pg-find" type="search" placeholder="${tt('搜索对话', 'Search chats')}" aria-label="${tt('搜索对话', 'Search chats')}">
  <div class="pg-lhead"><span>${tt('对话', 'Chats')}</span><span></span></div>
  <nav class="pg-list" aria-label="${tt('对话', 'Chats')}"></nav>
  <div class="pg-foot"><div class="pg-upd" hidden></div><button type="button" class="set" data-act="settings" data-tip="${tt('设置', 'Settings')}" data-keys="${keys.keysOf('settings')}">${icon('settings')}<span>${tt('设置', 'Settings')}</span></button>
    <button type="button" class="pg-me" data-act="identity-menu" aria-label="${tt('切换身份', 'Switch identity')}"><div class="pg-avatar"></div><div><b></b><small></small></div></button></div>
</aside>`
}

export function mount(app) {
    $('.pg-find').oninput = (e) => { find = e.target.value; draw(app) }
}
export function actions(app) {
    on('chats-search', () => { const f = $('.pg-find'); if (f.classList.contains('on') && !f.value) { f.classList.remove('on'); return } search(app) })
}
// what the list asks the host for
export const query = () => ({})
// the palette's entries for the chat that is open
export const commands = () => []

export function draw(app) {
    const list = $('.pg-list'), q = find.toLowerCase()
    const busy = new Set(app.life.busy || [])
    list.innerHTML = app.chats.filter((c) => !q || (c.title || '').toLowerCase().includes(q)).map((c) => {
        const waiting = c.waiting === 'desktop' ? tt('等桌面', 'waiting for desktop') : c.waiting === 'approval' ? tt('等你批准', 'waits for you') : ''
        const shown = app.view === 'chat' && c.chat === app.chat
        return `<button type="button" class="pg-chat${shown ? ' on' : ''}${c.unread && !shown ? ' unread' : ''}${c.busy || busy.has(c.chat) ? ' busy' : ''}${waiting ? ' waiting' : ''}${c.kind === 'earlier' ? ' earlier' : ''}" data-act="chat-open" data-arg="${esc(c.chat)}"${shown ? ' aria-current="page"' : ''}>`
            + `<b>${esc(title(c))}</b><small>${esc(waiting || when(c.updated))}</small><span class="dot"></span></button>`
    }).join('')
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
    f.value = ''; find = ''; f.classList.remove('on')
    draw(app)
    return true
}
