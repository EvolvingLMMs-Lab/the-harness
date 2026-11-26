// Small pieces every screen uses: elements, the dialog layer, toasts, the rail's tips.
import { esc } from './i18n.js'

export const $ = (s, root = document) => root.querySelector(s)
export const $$ = (s, root = document) => [...root.querySelectorAll(s)]
export function el(tag, cls, html) {
    const d = document.createElement(tag)
    if (cls) d.className = cls
    if (html !== undefined) d.innerHTML = html
    return d
}

export function dialog(html, { onClose } = {}) {
    const layer = $('.pg-layer')
    layer.innerHTML = `<div class="dlg" role="dialog" aria-modal="true">${html}</div>`
    layer.classList.add('open')
    const d = layer.firstElementChild
    layer.onclick = (e) => { if (e.target === layer) closeDialog() }
    layer._onClose = onClose
    const first = d.querySelector('input, textarea, select, button.btn')
    if (first) setTimeout(() => first.focus(), 30)
    return d
}
export function closeDialog() {
    const layer = $('.pg-layer')
    if (!layer.classList.contains('open')) return false
    layer.classList.remove('open'); layer.innerHTML = ''
    if (layer._onClose) { const f = layer._onClose; layer._onClose = null; f() }
    return true
}
export function steps(names, n) {
    return `<div class="steps">${names.map((s, i) => `<span class="${i === n ? 'on' : i < n ? 'done' : ''}">${i + 1} ${esc(s)}</span>`).join('')}</div>`
}

export function toast(text) {
    const t = el('div', 'toast', esc(text)); document.body.append(t); setTimeout(() => t.remove(), 3300)
}

export function tip(target, text) {
    const r = target.getBoundingClientRect(), t = el('div', 'tip', esc(text))
    document.body.append(t)
    t.style.left = Math.max(4, r.left - t.offsetWidth - 8) + 'px'; t.style.top = (r.top + 4) + 'px'
    return t
}
export function tips(root) {
    root.addEventListener('mouseover', (e) => {
        const b = e.target.closest('[data-tip]'); if (!b || b._tip) return
        b._tip = tip(b, b.dataset.tip)
        b.addEventListener('mouseleave', () => { b._tip && b._tip.remove(); b._tip = null }, { once: true })
    })
}

// a two-state switch
export function toggle(on, label = '') { return `<button class="tog${on ? ' on' : ''}" role="switch" aria-checked="${on ? 'true' : 'false'}" aria-label="${esc(label)}"></button>` }
