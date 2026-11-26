// The window's title bar, when the page is in the desktop shell (it draws no native one): the
// top rows (data-tauri-drag-region) move the window and a double click maximizes or restores
// it; minimize, maximize/restore and close sit at the right end, sized like the system's own
// caption buttons. Close hides the window to the tray, as the shell does with any close.
// macOS keeps its own traffic lights at the top left. In a plain browser: nothing.
import { tt } from './i18n.js'

const shell = window.__TAURI_INTERNALS__
const call = (command) => shell.invoke('plugin:window|' + command)

const GLYPH = {
    min: '<path d="M0 5.5h10"/>',
    max: '<path d="M.5 .5h9v9h-9z"/>',
    restore: '<path d="M.5 2.5h7v7h-7z M2.5 2.5v-2h7v7h-2"/>',
    close: '<path d="M.5 .5l9 9M9.5 .5l-9 9"/>',
}
const svg = (name) => `<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">${GLYPH[name]}</svg>`

export function start() {
    if (!shell) return
    const mac = /Mac/.test(navigator.platform || navigator.userAgent)
    document.documentElement.classList.add('shell', mac ? 'mac' : 'own-caption')
    for (const row of document.querySelectorAll('.pg-top, .pg-bar')) row.dataset.tauriDragRegion = 'deep'
    if (mac) return
    const bar = document.createElement('div')
    bar.className = 'pg-win'
    bar.innerHTML = `<button data-win="minimize" aria-label="${tt('最小化', 'Minimize')}">${svg('min')}</button>`
        + `<button data-win="toggle_maximize" aria-label="${tt('最大化', 'Maximize')}">${svg('max')}</button>`
        + `<button data-win="close" class="close" aria-label="${tt('关闭', 'Close')}">${svg('close')}</button>`
    document.body.append(bar)
    bar.addEventListener('click', (e) => { const b = e.target.closest('[data-win]'); if (b) call(b.dataset.win) })
    const max = bar.querySelector('[data-win="toggle_maximize"]')
    const state = async () => {
        const on = await call('is_maximized').catch(() => false)
        max.innerHTML = svg(on ? 'restore' : 'max')
        max.setAttribute('aria-label', on ? tt('还原', 'Restore') : tt('最大化', 'Maximize'))
        document.documentElement.classList.toggle('maximized', !!on)
    }
    addEventListener('resize', state)
    state()
}
