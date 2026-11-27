// The transcript of the chat that is open, after Hermes Desktop's "Chat":
//   - the reply being written grows in place; only rows that changed are drawn again;
//   - reading-position memory: coming back to a chat restores how far from the bottom it was
//     left (kept in this window's storage, prefs.js); a chat left at the bottom keeps following
//     new output, and "Jump to latest" returns to the live edge;
//   - find in the chat (Ctrl+F): a bar that searches the transcript as it is drawn, Enter and
//     Shift+Enter step through the matches, Esc closes it;
//   - an approval that starts waiting takes the keyboard when nothing is being typed, as a
//     permission prompt does: 1 and 2 choose, Esc declines.
import { esc, tt } from './i18n.js'
import { $, ic, loading, problem } from './ui.js'
import { icon } from './icons.js'
import { perChat, prefs } from './prefs.js'
import { rows, liveRow, working } from './chat.js'
import { STARTERS } from './onboarding.js'
import * as timeline from './timeline.js'
import { label } from './keys.js'

// Pixels from the bottom within which the chat counts as "at the latest".
const NEAR = 48
const positions = perChat('scroll')

let follow = true // at the live edge: new output stays in view
let unseen = false // something arrived below while an earlier part is being read
let restore = null // the saved distance from the bottom, until the chat's first rows are in
let waiting = new Set() // approval codes already seen waiting in this chat
let saving = null
let drawnAt = 0 // records the timeline was last drawn for

const distance = (feed) => feed.scrollHeight - feed.scrollTop - feed.clientHeight

export function frameHtml() {
    return `<div class="pg-thread"><div class="pg-feed" tabindex="-1" role="region" aria-label="${tt('对话记录', 'Transcript')}">${loading()}</div>`
        + `<button type="button" class="pg-latest" data-act="latest" hidden>${icon('latest', 14)}<span></span></button>`
        + `<div class="pg-findbar" role="search" hidden><input type="text" autocomplete="off" spellcheck="false" placeholder="${tt('在这个对话里查找', 'Find in this chat')}" aria-label="${tt('在这个对话里查找', 'Find in this chat')}"><span class="n" aria-live="polite"></span>`
        + ic('up', tt('上一个', 'Previous match'), { act: 'find-prev', keys: label('shift+enter') }) + ic('down', tt('下一个', 'Next match'), { act: 'find-next', keys: label('enter') })
        + ic('close', tt('关闭查找', 'Close find'), { act: 'find-close', keys: 'Esc' }) + `</div></div>`
}

export function mount(app) {
    const feed = $('.pg-feed')
    feed.addEventListener('scroll', () => {
        follow = distance(feed) < NEAR
        if (follow) unseen = false
        latest()
        clearTimeout(saving)
        saving = setTimeout(() => { if (feed.dataset.chat === key(app)) positions.set(app, follow ? null : Math.round(distance(feed))) }, 200)
    }, { passive: true })
    // an approval card under the keyboard: 1 and 2 choose; Enter in its reason field declines with it
    feed.addEventListener('keydown', (e) => {
        const card = e.target.closest && e.target.closest('.card.ask.waiting')
        if (!card || e.isComposing || e.keyCode === 229 || e.ctrlKey || e.metaKey || e.altKey) return
        if (e.target.tagName === 'INPUT') { if (e.key === 'Enter') { e.preventDefault(); card.querySelector('[data-act="decline"]').click() } return }
        const option = { 1: 0, 2: 1, 3: 2 }[e.key]
        if (option !== undefined) { const btns = card.querySelectorAll('.ao'); if (btns[option]) { e.preventDefault(); btns[option].click() } }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const all = [...card.querySelectorAll('.ao')]; all[(all.indexOf(document.activeElement) + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length].focus() }
    })
    const field = $('.pg-findbar input')
    field.addEventListener('input', () => { at = -1; refind() })
    field.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return
        e.preventDefault(); step(e.shiftKey ? -1 : 1)
    })
}

const key = (app) => `${app.identity.id}/${app.chat}`

function emptyState(app) {
    const row = app.row()
    if (row.kind === 'earlier') return `<div class="pg-empty">${tt('这是早先版本留下的对话，只能看。', 'A conversation of an earlier version: it can be read only.')}</div>`
    // An empty chat says how to begin: things to say, one click away.
    return `<div class="pg-empty start"><b>${tt('说说你想让它做什么', 'Say what you want done')}</b><span>${''}</span>`
        + STARTERS().map((s) => `<button type="button" class="starter" data-act="starter" data-arg="${esc(s)}">${esc(s)}</button>`).join('') + `</div>`
}

// Draw the open chat from what the app holds of it (records, the live reply, whether a turn runs).
export function draw(app) {
    const feed = $('.pg-feed'), chat = app.chat
    const first = feed.dataset.chat !== key(app)
    if (first) {
        feed.innerHTML = ''; feed._rows = []; feed.dataset.chat = key(app)
        restore = positions.get(app); follow = !restore; unseen = false; waiting = new Set(); drawnAt = -1
    }
    const recs = app.records[chat] || []
    const busy = app.busy(chat)
    const ctx = { name: app.identity.name, titles: app.titles(), thinking: prefs.get('thinking.show', true), busy }
    let html
    if (!app.loaded[chat]) {
        html = [app.problems[chat] ? problem(app.problems[chat], { title: tt('这个对话没有加载出来', 'This chat did not load'), retry: 'refresh' }) : loading()]
    } else {
        html = rows(recs, ctx)
        const live = app.live[chat]
        if (live) html.push(liveRow(live, ctx))
        // at work with nothing of it to show yet; an action in progress or a request waiting for the owner says so itself
        else if (busy && !/class="oc pending"|card ask waiting/.test(html[html.length - 1] || '')) html.push(working())
        if (!html.length) html.push(emptyState(app))
    }
    // only rows that are new or changed are drawn again; the others stay as they are
    const old = feed._rows
    let k = 0
    while (k < old.length && k < html.length && old[k] === html[k]) k++
    if (k < old.length || k < html.length) {
        // a row that takes the place of the reply being written does not rise in again
        const still = /class="pe (say live|think)"/.test(old[k] || '')
        const grew = html.length > old.length || k < html.length
        while (feed.children.length > k) feed.lastElementChild.remove()
        feed.insertAdjacentHTML('beforeend', html.slice(k).join(''))
        if (still && feed.children[k]) feed.children[k].classList.add('still')
        feed._rows = html
        if (!first && !follow && grew) unseen = true
        if (findOpen()) refind()
    }
    if (restore !== null && app.loaded[chat]) {
        feed.scrollTop = feed.scrollHeight - feed.clientHeight - restore
        restore = null; follow = distance(feed) < NEAR
    } else if (follow) feed.scrollTop = feed.scrollHeight
    latest()
    // thinking that is being written is read at its end
    const thought = feed.querySelector('.pe.live .thinking[open] .tx')
    if (thought) thought.scrollTop = thought.scrollHeight
    approvalFocus(feed)
    const tl = $('.tl')
    if (app.showTimeline && drawnAt !== recs.length) { drawnAt = recs.length; timeline.draw(tl, recs) }
}

// The timeline was switched on, or its chat's tasks moved on: draw it now.
export function drawTimeline(app) { drawnAt = (app.records[app.chat] || []).length; timeline.draw($('.tl'), app.records[app.chat] || []) }

function latest() {
    const b = $('.pg-latest'), feed = $('.pg-feed')
    if (!b) return
    const away = !follow && distance(feed) >= NEAR
    b.hidden = !away
    b.classList.toggle('new', unseen)
    b.querySelector('span').textContent = unseen ? tt('下面有新内容', 'New below') : tt('回到最新', 'Jump to latest')
}
export function toLatest() {
    const feed = $('.pg-feed')
    feed.scrollTop = feed.scrollHeight
    follow = true; unseen = false
    latest()
}

// A request that has just started waiting takes the keyboard, unless something is being typed.
function approvalFocus(feed) {
    for (const card of feed.querySelectorAll('.card.ask.waiting')) {
        const code = card.dataset.code
        if (waiting.has(code)) continue
        waiting.add(code)
        const active = document.activeElement
        const idle = !active || active === document.body || active === feed || (active.matches('.pg-compose textarea') && !active.value)
        if (idle && !document.querySelector('.pg-layer.open, .menu, .pal-layer')) card.querySelector('.ao').focus({ preventScroll: !follow })
    }
}
// "No, and tell it what to do differently": the line to say it in.
export function declineWhy(node) {
    const card = node.closest('.card.ask'), why = card.querySelector('.why')
    why.hidden = false
    why.querySelector('input').focus()
}
// Esc on an approval card: out of the reason line, else the request is declined (Claude Code's "(esc)").
export function escapeCard(decline) {
    const card = document.activeElement && document.activeElement.closest ? document.activeElement.closest('.card.ask.waiting') : null
    if (!card) return false
    const why = card.querySelector('.why')
    if (!why.hidden) { why.hidden = true; card.querySelectorAll('.ao')[1].focus(); return true }
    decline(card.dataset.code)
    return true
}
export const reasonOf = (node) => { const input = node.closest('.card.ask').querySelector('.why input'); return input ? input.value.trim() : '' }

// ── find in the chat ──
let ranges = [], at = -1
const findOpen = () => { const bar = $('.pg-findbar'); return !!bar && !bar.hidden }
const shownNode = (node) => (node.checkVisibility ? node.checkVisibility() : node.offsetParent !== null)
const marks = () => (typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined' ? CSS.highlights : null)

export function openFind() {
    const bar = $('.pg-findbar'), field = bar.querySelector('input')
    bar.hidden = false
    field.focus(); field.select()
    at = -1; refind()
}
export function closeFind() {
    if (!findOpen()) return false
    $('.pg-findbar').hidden = true
    ranges = []; at = -1
    if (marks()) { marks().delete('find'); marks().delete('find-now') } else getSelection().removeAllRanges()
    $('.pg-compose textarea').focus()
    return true
}
// Every place the text occurs in what the transcript shows now (case does not matter).
function refind() {
    const feed = $('.pg-feed'), bar = $('.pg-findbar'), needle = bar.querySelector('input').value.toLowerCase()
    ranges = []
    if (needle) {
        const walker = document.createTreeWalker(feed, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            const text = node.data.toLowerCase()
            let from = text.indexOf(needle)
            if (from < 0 || !node.parentElement || !shownNode(node.parentElement)) continue
            for (; from >= 0; from = text.indexOf(needle, from + needle.length)) {
                const range = document.createRange()
                range.setStart(node, from); range.setEnd(node, from + needle.length)
                ranges.push(range)
            }
        }
    }
    if (!ranges.length) at = -1
    else if (at < 0 || at >= ranges.length) {
        // start with the first match in view, as a page's own find does
        const top = feed.getBoundingClientRect().top
        at = Math.max(0, ranges.findIndex((r) => r.getBoundingClientRect().bottom >= top))
    }
    paint(needle)
}
function paint(needle) {
    const bar = $('.pg-findbar'), feed = $('.pg-feed')
    bar.querySelector('.n').textContent = !needle ? '' : ranges.length ? `${at + 1} / ${ranges.length}` : tt('没有找到', 'No matches')
    bar.classList.toggle('none', !!needle && !ranges.length)
    const now = at >= 0 ? ranges[at] : null
    if (marks()) {
        marks().set('find', new Highlight(...ranges.filter((r) => r !== now)))
        if (now) marks().set('find-now', new Highlight(now)); else marks().delete('find-now')
    } else if (now) { const sel = getSelection(); sel.removeAllRanges(); sel.addRange(now) }
    if (!now) return
    const box = now.getBoundingClientRect(), view = feed.getBoundingClientRect()
    if (box.top < view.top + 8 || box.bottom > view.bottom - 8) feed.scrollTop += box.top - view.top - feed.clientHeight / 2
}
export function step(by) {
    if (!findOpen() || !ranges.length) return
    at = (at + by + ranges.length) % ranges.length
    paint($('.pg-findbar input').value)
}
