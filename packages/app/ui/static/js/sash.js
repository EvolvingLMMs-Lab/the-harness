// Resizable sashes between workbench regions (left sidebar, right Overview/Work pane,
// bottom full-width terminal drawer, Settings nav, and Calendar left rail).
import { tt } from './i18n.js'
import { prefs } from './prefs.js'

const PARTS = {
    side: { axis: 'x', base: 232, min: 180, max: 440, grows: 1, of: '.pg-side', zh: '侧边栏', en: 'the sidebar' },
    panel: { axis: 'x', base: 540, min: 360, max: 1100, grows: -1, of: '.pg-panel', zh: '右侧边栏', en: 'the right side panel' },
    terminal: { axis: 'y', base: 240, min: 140, max: 620, grows: -1, of: '.pg-term-drawer', zh: '终端高度', en: 'the terminal height' },
    settings: { axis: 'x', base: 220, min: 170, max: 420, grows: 1, of: '.pg-settings nav', zh: '设置列表', en: "Settings' list" },
    calendar: { axis: 'x', base: 204, min: 170, max: 440, grows: 1, of: '.pc-left', zh: '日历左栏', en: "the calendar's left column" },
}

function activePart(s) {
    return s.dataset.sash
}

const ROOM_X = 400
const ROOM_Y = 220
const STEP = 16

export function sashHtml(part) {
    const p = PARTS[part]
    const vertical = p.axis !== 'y'
    const what = vertical
        ? tt(`拖动调整${p.zh}的宽度 · 双击恢复`, `Drag to resize ${p.en} · double-click to reset`)
        : tt(`拖动调整${p.zh} · 双击恢复`, `Drag to resize ${p.en} · double-click to reset`)
    return `<div class="sash${vertical ? '' : ' sash-y'}" data-sash="${part}" role="separator" aria-orientation="${vertical ? 'vertical' : 'horizontal'}" tabindex="0" aria-label="${escAttr(tt(p.zh, p.en))}" title="${escAttr(what)}"></div>`
}

function escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
}

const variable = (part) => (PARTS[part].axis === 'y' ? `--h-${part}` : `--w-${part}`)
function set(part, size) {
    if (size === null) document.documentElement.style.removeProperty(variable(part))
    else document.documentElement.style.setProperty(variable(part), `${size}px`)
}

function limit(part) {
    const p = PARTS[part], node = document.querySelector(p.of)
    if (p.axis === 'y') {
        const parent = node && node.parentElement ? node.parentElement.getBoundingClientRect().height : innerHeight
        return Math.max(p.min, Math.min(p.max, Math.floor(parent - ROOM_Y)))
    }
    const rect = (selector) => { const n = document.querySelector(selector); return n && n.getClientRects().length ? n.getBoundingClientRect().width : 0 }
    const others = part === 'side' ? rect('.pg-panel') : (part === 'panel' || part === 'overview') ? rect('.pg-side') : 0
    const all = part === 'settings' || part === 'calendar' ? (node && node.parentElement ? node.parentElement.getBoundingClientRect().width : innerWidth) : innerWidth
    return Math.max(p.min, Math.min(p.max, Math.floor(all - others - ROOM_X)))
}

const clamp = (part, size) => Math.round(Math.max(PARTS[part].min, Math.min(limit(part), size)))

function now(part) {
    const p = PARTS[part], node = document.querySelector(p.of)
    if (node && node.getClientRects().length) {
        const r = node.getBoundingClientRect()
        return p.axis === 'y' ? r.height : r.width
    }
    return prefs.get(`layout.${part}`, p.base)
}

function keep(part, size) {
    set(part, size)
    prefs.set(`layout.${part}`, size)
    const sashKey = part === 'overview' ? 'panel' : part
    for (const s of document.querySelectorAll(`.sash[data-sash="${sashKey}"]`)) s.setAttribute('aria-valuenow', size === null ? PARTS[part].base : size)
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
        const part = activePart(s), p = PARTS[part]
        if (!p) return
        drag = { part, s, axis: p.axis, pos: p.axis === 'y' ? e.clientY : e.clientX, from: now(part), size: null }
        s.setPointerCapture(e.pointerId)
        s.classList.add('on')
        document.body.classList.add(p.axis === 'y' ? 'sashing-y' : 'sashing')
    })
    document.addEventListener('pointermove', (e) => {
        if (!drag) return
        const cur = drag.axis === 'y' ? e.clientY : e.clientX
        drag.size = clamp(drag.part, drag.from + (cur - drag.pos) * PARTS[drag.part].grows)
        set(drag.part, drag.size)
    })
    const end = () => {
        if (!drag) return
        drag.s.classList.remove('on')
        document.body.classList.remove('sashing', 'sashing-y')
        if (drag.size !== null) keep(drag.part, drag.size)
        drag = null
    }
    document.addEventListener('pointerup', end)
    document.addEventListener('pointercancel', end)
    document.addEventListener('dblclick', (e) => {
        const s = e.target.closest && e.target.closest('.sash')
        if (s) keep(activePart(s), null)
    })
    document.addEventListener('keydown', (e) => {
        const s = e.target.classList && e.target.classList.contains('sash') ? e.target : null
        if (!s) return
        const part = activePart(s), p = PARTS[part]
        if (!p) return
        const dec = p.axis === 'y' ? 'ArrowDown' : 'ArrowLeft'
        const inc = p.axis === 'y' ? 'ArrowUp' : 'ArrowRight'
        const dir = e.key === dec ? -1 : e.key === inc ? 1 : 0
        if (dir) { e.preventDefault(); keep(part, clamp(part, now(part) + dir * STEP * (p.axis === 'y' ? 1 : p.grows))) }
        else if (e.key === 'Home') { e.preventDefault(); keep(part, p.min) }
        else if (e.key === 'End') { e.preventDefault(); keep(part, limit(part)) }
        else if (e.key === 'Enter') { e.preventDefault(); keep(part, null) }
    })
    addEventListener('resize', () => {
        if (drag) return
        for (const part of Object.keys(PARTS)) {
            const kept = prefs.get(`layout.${part}`, null)
            if (typeof kept !== 'number') continue
            const node = document.querySelector(PARTS[part].of)
            if (node && node.getClientRects().length) set(part, Math.min(kept, limit(part)))
        }
    })
}
