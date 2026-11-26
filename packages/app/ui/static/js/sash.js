// The edges between the parts of the window: dragged to make a part wider or narrower, as the
// sashes of VS Code and the sidebars of Claude's and Codex's desktop apps are. Every part that
// has a width of its own has one: the chat list, the tools panel, the Settings page's list and
// the calendar's left column.
//
//   drag            the part follows the pointer, between its narrowest and what the window has
//                   room for (the chat always keeps room to read and type)
//   double-click    back to the width it comes with
//   keyboard        the edge takes the focus (Tab): Left and Right move it, Home and End go to
//                   its narrowest and widest, Enter puts it back
//
// A width is this window's own on this computer (prefs.js: layout.<part>), kept as a CSS variable
// the stylesheet reads (--w-<part>), so a page that loads again opens as it was left.
import { tt } from './i18n.js'
import { prefs } from './prefs.js'

// grows: +1 when dragging right widens the part (its edge is on its right), -1 when dragging left does.
const PARTS = {
    side: { base: 240, min: 180, max: 520, grows: 1, of: '.pg-side', zh: '对话列表', en: 'the chat list' },
    panel: { base: 430, min: 300, max: 1100, grows: -1, of: '.pg-panel', zh: '工具面板', en: 'the tools panel' },
    settings: { base: 220, min: 170, max: 420, grows: 1, of: '.pg-settings nav', zh: '设置的列表', en: "Settings' list" },
    calendar: { base: 196, min: 170, max: 440, grows: 1, of: '.pc-left', zh: '日历的左栏', en: "the calendar's left column" },
}
// What the middle of the window keeps, whatever is dragged.
const ROOM = 400
const STEP = 16

export function sashHtml(part) {
    const p = PARTS[part]
    const what = tt(`拖动调整${p.zh}的宽度 · 双击恢复`, `Drag to resize ${p.en} · double-click to reset`)
    return `<div class="sash" data-sash="${part}" role="separator" aria-orientation="vertical" tabindex="0" aria-label="${tt(`${p.zh}的宽度`, `Width of ${p.en}`)}" title="${what}"></div>`
}

const variable = (part) => `--w-${part}`
function set(part, width) {
    if (width === null) document.documentElement.style.removeProperty(variable(part))
    else document.documentElement.style.setProperty(variable(part), `${width}px`)
}
// The widest a part may be now: its own limit, and what the window has left beside the others.
function widest(part) {
    const p = PARTS[part], node = document.querySelector(p.of)
    const rect = (selector) => { const n = document.querySelector(selector); return n && n.getClientRects().length ? n.getBoundingClientRect().width : 0 }
    const others = part === 'side' ? rect('.pg-panel') + rect('.pg-rail') : part === 'panel' ? rect('.pg-side') + rect('.pg-rail') : 0
    const all = part === 'settings' || part === 'calendar' ? (node && node.parentElement ? node.parentElement.getBoundingClientRect().width : innerWidth) : innerWidth
    return Math.max(p.min, Math.min(p.max, Math.floor(all - others - ROOM)))
}
const clamp = (part, width) => Math.round(Math.max(PARTS[part].min, Math.min(widest(part), width)))
function now(part) {
    const node = document.querySelector(PARTS[part].of)
    return node && node.getClientRects().length ? node.getBoundingClientRect().width : prefs.get(`layout.${part}`, PARTS[part].base)
}
function keep(part, width) {
    set(part, width)
    prefs.set(`layout.${part}`, width)
    for (const s of document.querySelectorAll(`.sash[data-sash="${part}"]`)) s.setAttribute('aria-valuenow', width === null ? PARTS[part].base : width)
    // what lays itself out by the window's size (the calendar's grid, the timeline) follows
    dispatchEvent(new Event('resize'))
}

export function start() {
    for (const part of Object.keys(PARTS)) {
        const kept = prefs.get(`layout.${part}`, null)
        if (typeof kept === 'number' && kept >= PARTS[part].min) set(part, Math.min(kept, PARTS[part].max))
    }
    let drag = null
    document.addEventListener('pointerdown', (e) => {
        const s = e.target.closest && e.target.closest('.sash')
        if (!s || e.button !== 0) return
        e.preventDefault()
        const part = s.dataset.sash
        drag = { part, s, x: e.clientX, from: now(part), width: null }
        s.setPointerCapture(e.pointerId)
        s.classList.add('on')
        document.body.classList.add('sashing')
    })
    document.addEventListener('pointermove', (e) => {
        if (!drag) return
        drag.width = clamp(drag.part, drag.from + (e.clientX - drag.x) * PARTS[drag.part].grows)
        set(drag.part, drag.width)
    })
    const end = () => {
        if (!drag) return
        drag.s.classList.remove('on')
        document.body.classList.remove('sashing')
        if (drag.width !== null) keep(drag.part, drag.width)
        drag = null
    }
    document.addEventListener('pointerup', end)
    document.addEventListener('pointercancel', end)
    document.addEventListener('dblclick', (e) => {
        const s = e.target.closest && e.target.closest('.sash')
        if (s) keep(s.dataset.sash, null)
    })
    document.addEventListener('keydown', (e) => {
        const s = e.target.classList && e.target.classList.contains('sash') ? e.target : null
        if (!s) return
        const part = s.dataset.sash, p = PARTS[part]
        const to = { ArrowLeft: now(part) - STEP * p.grows, ArrowRight: now(part) + STEP * p.grows, Home: p.min, End: widest(part) }[e.key]
        if (to !== undefined) { e.preventDefault(); keep(part, clamp(part, to)) }
        else if (e.key === 'Enter') { e.preventDefault(); keep(part, null) }
    })
    // a window made narrower keeps the middle readable: a kept width gives way
    addEventListener('resize', () => {
        if (drag) return
        for (const part of Object.keys(PARTS)) {
            const kept = prefs.get(`layout.${part}`, null)
            if (typeof kept !== 'number') continue
            const node = document.querySelector(PARTS[part].of)
            if (node && node.getClientRects().length) set(part, Math.min(kept, widest(part)))
        }
    })
}
