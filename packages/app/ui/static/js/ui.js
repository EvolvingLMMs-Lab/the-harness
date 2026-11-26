// The layer every screen shares. A screen is built from these and nothing of its own kind:
//
//   states     loading(), empty(), problem(): with the screen's normal drawing, the four states
//              each screen has. problem() is the error card: what went wrong, what to do, where
//              the log is, and a way to try again.
//   actions    on(name, run) and data-act="name" on a button: one click handler for the whole
//              page. A handler that returns a promise locks its button until it settles, so a
//              click answers at once (the button shows it is working) and cannot fire twice.
//   buttons    ic(): an icon button always has a name and a tooltip (with its shortcut).
//   dialogs    dialog(), confirm(), ask(): the keyboard stays inside, Enter is the main button,
//              Esc cancels, and the focus goes back to where it was.
//   menus      menu(): a popup list for the arrow keys, Enter and Esc as well as the mouse.
//   feedback   toast() (with one action, as in "Saved" and Undo) and said() for a failure's reason and fix, flash() beside a control
//              that was just saved, copy().
import { esc, tt } from './i18n.js'
import { icon } from './icons.js'

export const $ = (s, root = document) => root.querySelector(s)
export const $$ = (s, root = document) => [...root.querySelectorAll(s)]
export function el(tag, cls, html) {
    const d = document.createElement(tag)
    if (cls) d.className = cls
    if (html !== undefined) d.innerHTML = html
    return d
}

// ── states ──
export const loading = (text) => `<div class="st st-load" role="status"><span class="spin"></span>${esc(text || tt('正在加载…', 'Loading…'))}</div>`
export const empty = (title, text = '', more = '') => `<div class="st st-empty"><b>${esc(title)}</b>${text ? `<span>${esc(text)}</span>` : ''}${more}</div>`
// p: what api.js keeps of a failure ({error, fix, log}); retry: the action a click runs again.
export function problem(p, { title, retry, more = '' } = {}) {
    const said = p || {}
    return `<div class="st st-problem" role="alert"><b>${icon('alert')}<span>${esc(title || tt('这一块没有加载出来', 'This part did not load'))}</span></b>`
        + `<span class="why">${esc(said.error || tt('后台没有说明原因。', 'The host gave no reason.'))}</span>`
        + (said.fix ? `<span class="fix">${esc(said.fix)}</span>` : '')
        + (said.log ? `<small>${esc(tt('日志：', 'Log: '))}${esc(said.log)}</small>` : '')
        + (retry || more ? `<div class="st-acts">${retry ? `<button type="button" class="b" data-act="${esc(retry)}">${icon('retry')}${esc(tt('重试', 'Try again'))}</button>` : ''}${more}</div>` : '')
        + `</div>`
}

// ── actions ──
const actions = new Map()
export function on(name, run) { actions.set(name, run) }
// While `promise` runs the control shows it and takes no more clicks.
export function lock(node, promise) {
    if (!node || !promise || typeof promise.then !== 'function') return promise
    node.setAttribute('aria-busy', 'true')
    const release = () => node.removeAttribute('aria-busy')
    promise.then(release, release)
    return promise
}
const locked = (node) => node.getAttribute('aria-busy') === 'true' || node.disabled || node.getAttribute('aria-disabled') === 'true'
export function wireActions(root) {
    root.addEventListener('click', (e) => {
        const node = e.target.closest('[data-act]')
        if (!node || !root.contains(node)) return
        const run = actions.get(node.dataset.act)
        if (!run) return
        e.preventDefault()
        if (locked(node)) return
        lock(node, run(node, e))
    })
}
// For a control wired by hand (inside a dialog): press(button, async () => …).
export function press(node, run) {
    if (!node) return
    node.addEventListener('click', (e) => { e.preventDefault(); if (!locked(node)) lock(node, run(e)) })
}

// ── buttons ──
export function ic(name, text, { act: action, keys = '', cls = '', attrs = '' } = {}) {
    return `<button type="button" class="pg-ic${cls ? ' ' + cls : ''}"${action ? ` data-act="${esc(action)}"` : ''} aria-label="${esc(text)}" data-tip="${esc(text)}"${keys ? ` data-keys="${esc(keys)}"` : ''}${attrs ? ' ' + attrs : ''}>${icon(name)}</button>`
}
// a two-state switch
export function toggle(on, label = '') { return `<button type="button" class="tog${on ? ' on' : ''}" role="switch" aria-checked="${on ? 'true' : 'false'}" aria-label="${esc(label)}"></button>` }
export function steps(names, n) {
    return `<div class="steps">${names.map((s, i) => `<span class="${i === n ? 'on' : i < n ? 'done' : ''}">${i + 1} ${esc(s)}</span>`).join('')}</div>`
}

// ── tooltips: any element with data-tip, under the pointer after a moment or under the
// keyboard's focus at once; the shortcut (data-keys) beside the name ──
let tipNode = null, tipFor = null, tipTimer = null
function showTip(target) {
    hideTip()
    const text = target.dataset.tip
    if (!text || !document.contains(target)) return
    tipFor = target
    tipNode = el('div', 'tip', esc(text) + (target.dataset.keys ? `<kbd>${esc(target.dataset.keys)}</kbd>` : ''))
    tipNode.setAttribute('role', 'tooltip')
    document.body.append(tipNode)
    const r = target.getBoundingClientRect(), w = tipNode.offsetWidth, h = tipNode.offsetHeight
    const below = r.bottom + 6 + h <= innerHeight
    tipNode.style.left = Math.max(4, Math.min(innerWidth - w - 4, r.left + r.width / 2 - w / 2)) + 'px'
    tipNode.style.top = (below ? r.bottom + 6 : Math.max(4, r.top - h - 6)) + 'px'
}
function hideTip() {
    clearTimeout(tipTimer)
    if (tipNode) tipNode.remove()
    tipNode = null; tipFor = null
}
export function tips(root) {
    root.addEventListener('mouseover', (e) => {
        const b = e.target.closest('[data-tip]')
        if (!b || b === tipFor) return
        clearTimeout(tipTimer)
        tipTimer = setTimeout(() => showTip(b), 450)
    })
    root.addEventListener('mouseout', (e) => {
        const b = e.target.closest('[data-tip]')
        if (b && !b.contains(e.relatedTarget)) hideTip()
    })
    root.addEventListener('focusin', (e) => {
        const b = e.target.closest('[data-tip]')
        if (b && b.matches(':focus-visible')) showTip(b)
    })
    root.addEventListener('focusout', hideTip)
    root.addEventListener('mousedown', hideTip, true)
    root.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideTip() }, true)
    addEventListener('scroll', hideTip, true)
}

// ── dialogs ──
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
const reachable = (root) => $$(FOCUSABLE, root).filter((n) => !n.disabled && n.type !== 'hidden' && n.offsetParent !== null)
const mainButton = (d) => d.querySelector('.btn[data-default]:not([disabled])') || $$('.btn:not(.quiet):not([disabled])', d).pop()
let returnTo = null

// Put the keyboard where a dialog (or its new step) begins: its first field, else its main button.
export function refocus(d) {
    const first = d.querySelector('[autofocus]') || $$('input:not([type=hidden]):not([type=checkbox]), textarea, select', d).find((n) => !n.disabled && n.offsetParent !== null)
        || mainButton(d) || d
    first.focus()
}

export function dialog(html, { onClose, label } = {}) {
    const layer = $('.pg-layer')
    if (!layer.classList.contains('open')) returnTo = document.activeElement
    else if (layer._onClose) { const f = layer._onClose; layer._onClose = null; f() }
    layer.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" tabindex="-1">${html}</div>`
    layer.classList.add('open')
    const d = layer.firstElementChild
    const h = d.querySelector('h5')
    if (h) { h.id = 'dlg-title'; d.setAttribute('aria-labelledby', 'dlg-title') } else if (label) d.setAttribute('aria-label', label)
    layer._onClose = onClose
    refocus(d)
    return d
}
export const dialogOpen = () => $('.pg-layer').classList.contains('open')
export function closeDialog() {
    const layer = $('.pg-layer')
    if (!layer.classList.contains('open')) return false
    layer.classList.remove('open'); layer.innerHTML = ''
    if (layer._onClose) { const f = layer._onClose; layer._onClose = null; f() }
    if (returnTo && document.contains(returnTo)) returnTo.focus()
    returnTo = null
    return true
}
// The dialog layer's own keys and clicks, wired once with the frame.
export function wireDialogs() {
    const layer = $('.pg-layer')
    let downOnScrim = false
    layer.addEventListener('mousedown', (e) => { downOnScrim = e.target === layer })
    layer.addEventListener('click', (e) => { if (e.target === layer && downOnScrim) closeDialog() })
    layer.addEventListener('keydown', (e) => {
        const d = layer.firstElementChild
        if (!d || e.isComposing) return
        if (e.key === 'Tab') {
            const all = reachable(d)
            if (!all.length) { e.preventDefault(); return }
            const first = all[0], last = all[all.length - 1]
            if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus() }
            else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
            return
        }
        if (e.key !== 'Enter' || e.shiftKey) return
        const t = e.target, tag = t.tagName
        const field = (tag === 'INPUT' && !['button', 'submit', 'file'].includes(t.type)) || tag === 'SELECT'
            || (tag === 'TEXTAREA' && (e.ctrlKey || e.metaKey))
        if (!field) return
        const main = mainButton(d)
        if (main) { e.preventDefault(); main.click() }
    })
    // a dialog whose content was replaced keeps the keyboard
    document.addEventListener('focusin', (e) => {
        const d = layer.firstElementChild
        if (layer.classList.contains('open') && d && !layer.contains(e.target) && !e.target.closest('.menu, .tip')) refocus(d)
    })
}

// "Are you sure": true for yes. What cannot be undone starts on Cancel.
export function confirm({ title, text = '', yes, no, danger = false }) {
    return new Promise((done) => {
        let answer = false
        const d = dialog(`<h5>${esc(title)}</h5>${text ? `<p class="say">${esc(text)}</p>` : ''}`
            + `<div class="row"><span class="res"></span><button type="button" class="btn quiet" data-no${danger ? ' autofocus' : ''}>${esc(no || tt('取消', 'Cancel'))}</button>`
            + `<button type="button" class="btn${danger ? ' danger' : ''}" data-yes data-default${danger ? '' : ' autofocus'}>${esc(yes || tt('确定', 'OK'))}</button></div>`,
        { onClose: () => done(answer) })
        d.querySelector('[data-no]').onclick = closeDialog
        d.querySelector('[data-yes]').onclick = () => { answer = true; closeDialog() }
    })
}
// One line of text: the text, or null when cancelled.
export function ask({ title, label = '', value = '', yes, note = '', placeholder = '' }) {
    return new Promise((done) => {
        let answer = null
        const d = dialog(`<h5>${esc(title)}</h5><label><span>${esc(label)}</span><input class="field" value="${esc(value)}" placeholder="${esc(placeholder)}"></label>`
            + (note ? `<p class="note">${esc(note)}</p>` : '')
            + `<div class="row"><span class="res"></span><button type="button" class="btn quiet" data-no>${esc(tt('取消', 'Cancel'))}</button><button type="button" class="btn" data-yes data-default>${esc(yes || tt('保存', 'Save'))}</button></div>`,
        { onClose: () => done(answer) })
        const input = d.querySelector('input')
        input.select()
        d.querySelector('[data-no]').onclick = closeDialog
        d.querySelector('[data-yes]').onclick = () => { answer = input.value.trim(); closeDialog() }
    })
}

// ── menus ──
// items: {label, sub, icon, keys, right, checked, danger, disabled, run} | {head: text} | '-'.
// `filter`: a placeholder; the menu then starts with a field that narrows the items as you type.
let openMenu = null
export function closeMenu(refocusAnchor = false) {
    if (!openMenu) return false
    const { node, anchor, off, onClose } = openMenu
    openMenu = null
    off(); node.remove()
    if (anchor) anchor.setAttribute('aria-expanded', 'false')
    if (refocusAnchor && anchor && document.contains(anchor)) anchor.focus()
    if (onClose) onClose()
    return true
}
export const menuOpen = () => !!openMenu
export function menu(anchor, items, { side = 'bottom', align = 'start', filter = '', label = '', onClose, point } = {}) {
    if (openMenu && openMenu.anchor === anchor) { closeMenu(true); return null }
    closeMenu()
    const node = el('div', 'menu')
    node.setAttribute('role', 'menu')
    if (label) node.setAttribute('aria-label', label)
    const rows = items.filter(Boolean)
    const row = (it, i) => {
        if (it === '-') return '<hr>'
        if (it.head !== undefined) return `<div class="mh">${esc(it.head)}</div>`
        const role = it.checked === undefined ? 'menuitem' : 'menuitemradio'
        return `<button type="button" role="${role}"${it.checked === undefined ? '' : ` aria-checked="${it.checked ? 'true' : 'false'}"`} tabindex="-1" data-i="${i}" class="mi${it.danger ? ' danger' : ''}"${it.disabled ? ' disabled' : ''}>`
            + `<span class="mk">${it.checked ? icon('check', 14) : it.icon ? icon(it.icon, 14) : ''}</span><span class="ml"><b>${esc(it.label)}</b>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}</span>`
            + (it.right ? `<span class="mr">${esc(it.right)}</span>` : '') + (it.keys ? `<kbd>${esc(it.keys)}</kbd>` : '') + `</button>`
    }
    node.innerHTML = (filter ? `<input class="mf" type="text" placeholder="${esc(filter)}" aria-label="${esc(filter)}">` : '') + `<div class="ms">${rows.map(row).join('')}</div>`
    document.body.append(node)
    // where: under (or above) the anchor, inside the window
    const r = point ? { left: point.x, right: point.x, top: point.y, bottom: point.y } : anchor.getBoundingClientRect()
    const w = node.offsetWidth, h = node.offsetHeight
    let left = align === 'end' ? r.right - w : r.left
    left = Math.max(6, Math.min(innerWidth - w - 6, left))
    const below = side === 'bottom' ? r.bottom + 4 + h <= innerHeight || r.top < innerHeight / 2 : r.top - 4 - h < 0
    node.style.left = left + 'px'
    if (below) { node.style.top = (r.bottom + 4) + 'px'; node.style.maxHeight = Math.max(120, innerHeight - r.bottom - 12) + 'px' }
    else { node.style.bottom = (innerHeight - r.top + 4) + 'px'; node.style.maxHeight = Math.max(120, r.top - 12) + 'px' }
    const shown = () => $$('.mi:not([disabled])', node).filter((b) => !b.hidden)
    const move = (step, from = document.activeElement) => {
        const all = shown(); if (!all.length) return
        const at = all.indexOf(from)
        all[at < 0 ? (step > 0 ? 0 : all.length - 1) : (at + step + all.length) % all.length].focus()
    }
    const choose = (b) => { const it = rows[+b.dataset.i]; closeMenu(true); if (it && it.run) it.run() }
    node.addEventListener('click', (e) => { const b = e.target.closest('.mi'); if (b && !b.disabled) choose(b) })
    node.addEventListener('mousemove', (e) => { const b = e.target.closest('.mi'); if (b && !b.disabled && document.activeElement !== b && document.activeElement.tagName !== 'INPUT') b.focus() })
    const field = node.querySelector('.mf')
    node.addEventListener('keydown', (e) => {
        if (e.isComposing) return
        if (e.key === 'ArrowDown') { e.preventDefault(); move(1) }
        else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
        else if (e.key === 'Home' && e.target !== field) { e.preventDefault(); move(1, null) }
        else if (e.key === 'End' && e.target !== field) { e.preventDefault(); move(-1, null) }
        else if (e.key === 'Tab') { e.preventDefault(); closeMenu(true) }
        else if (e.key === 'Enter' && e.target === field) { e.preventDefault(); const first = shown()[0]; if (first) choose(first) }
        else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.target !== field) {
            // a letter: into the filter when there is one, else to the next item that starts with it
            if (field) { if (e.key !== ' ') field.focus(); return }
            const next = shown().find((b) => b.querySelector('b').textContent.trim().toLowerCase().startsWith(e.key.toLowerCase()) && b !== document.activeElement)
            if (next) next.focus()
        }
    })
    if (field) field.addEventListener('input', () => {
        const q = field.value.trim().toLowerCase()
        $$('.mi', node).forEach((b) => { b.hidden = !!q && !b.textContent.toLowerCase().includes(q) })
        // a heading with nothing left under it goes too
        $$('.mh', node).forEach((head) => { let n = head.nextElementSibling, any = false; while (n && !n.matches('.mh')) { if (n.matches('.mi') && !n.hidden) any = true; n = n.nextElementSibling } head.hidden = !any })
    })
    const outside = (e) => { if (!node.contains(e.target) && !(anchor && anchor.contains(e.target))) closeMenu() }
    const gone = () => closeMenu()
    document.addEventListener('mousedown', outside, true)
    addEventListener('resize', gone); addEventListener('blur', gone)
    if (anchor) { anchor.setAttribute('aria-haspopup', 'menu'); anchor.setAttribute('aria-expanded', 'true') }
    openMenu = { node, anchor, onClose, off: () => { document.removeEventListener('mousedown', outside, true); removeEventListener('resize', gone); removeEventListener('blur', gone) } }
    if (field) field.focus()
    else (node.querySelector('.mi[aria-checked="true"]:not([disabled])') || shown()[0] || node).focus()
    return node
}

// ── feedback ──
function toasts() {
    let box = $('.toasts')
    if (!box) { box = el('div', 'toasts'); box.setAttribute('aria-live', 'polite'); document.body.append(box) }
    return box
}
// `action`: {label, keys, run}: one thing to do about what was just said ("Saved" with Undo). Such a
// toast stays longer, and a newer one with an action takes the place of the one before.
export function toast(text, { error = false, fix = '', action = null } = {}) {
    if (!text) return
    const t = el('div', 'toast' + (error ? ' error' : '') + (action ? ' has-act' : ''), `<span>${esc(text)}</span>${fix ? `<small>${esc(fix)}</small>` : ''}`)
    if (error) t.setAttribute('role', 'alert')
    if (action) {
        $$('.toast.has-act').forEach((old) => old.remove())
        const b = el('button', 'ta', esc(action.label) + (action.keys ? `<kbd>${esc(action.keys)}</kbd>` : ''))
        b.type = 'button'
        b.onclick = () => { t.remove(); action.run() }
        t.append(b)
    }
    toasts().append(t)
    setTimeout(() => t.remove(), error ? 7000 : action ? 8000 : 3200)
}
// A failed request (api.js post()) as a toast: the reason, and what to do about it.
export function said(r, fallback = '') {
    toast((r && r.error) || fallback || tt('没有成功', 'That did not work'), { error: true, fix: (r && r.fix) || '' })
}
// Beside a control that was just changed: "Saved", or why it was not.
export function flash(holder, text, { error = false, fix = '' } = {}) {
    if (!holder) return
    const old = holder.querySelector(':scope > .flash')
    if (old) old.remove()
    const n = el('span', 'flash' + (error ? ' error' : ''), esc(text) + (fix ? `<small>${esc(fix)}</small>` : ''))
    n.setAttribute('role', error ? 'alert' : 'status')
    holder.append(n)
    if (!error) setTimeout(() => n.remove(), 2400)
}
export async function copy(text, what = '') {
    try {
        await navigator.clipboard.writeText(text)
    } catch {
        // no clipboard permission (a plain http page elsewhere than this computer): the old way
        const area = el('textarea'); area.value = text; area.style.position = 'fixed'; area.style.opacity = '0'
        document.body.append(area); area.select()
        let ok = false
        try { ok = document.execCommand('copy') } catch { ok = false }
        area.remove()
        if (!ok) { toast(tt('没能复制到剪贴板', 'Could not copy to the clipboard'), { error: true }); return false }
    }
    toast(what || tt('已复制', 'Copied'))
    return true
}

// ── lists: a row is what it is (a title and a line under it), its marks, and what can be done with it ──
export function row({ title, sub = '', marks = '', actions = '', cls = '', attrs = '', more = '' }) {
    return `<div class="li${cls ? ' ' + cls : ''}"${attrs ? ' ' + attrs : ''}><div class="lm"><b>${title}</b>${sub ? `<small>${sub}</small>` : ''}</div>`
        + `${marks ? `<div class="lk">${marks}</div>` : ''}${actions ? `<div class="la">${actions}</div>` : ''}${more}</div>`
}
export const mark = (text, kind = 'none') => `<span class="ev ev-${kind}">${esc(text)}</span>`
// a small button of a row; `more`: further data- attributes
export function act(label, action, arg = '', { danger = false, glyph = '', more = '' } = {}) {
    return `<button type="button" class="lb${danger ? ' danger' : ''}" data-act="${esc(action)}" data-arg="${esc(arg)}"${more ? ' ' + more : ''}>${glyph ? icon(glyph, 14) : ''}${esc(label)}</button>`
}
