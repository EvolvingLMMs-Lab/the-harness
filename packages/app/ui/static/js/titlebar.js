// Dedicated Row-1 global desktop titlebar (Microsoft Windows Fluent UI HIG & Tauri standard).
// Rendered strictly as Row 1 of `.app` (height: 32px) ONLY inside the Tauri desktop shell so
// content views (Chat, Overview, Calendar, Customizations, Settings) live cleanly in Row 2
// (`.app-body`) and can never collide with window caption controls (`— □ ×`).
// Plain browser sessions render nothing (0px height).
import { tt } from './i18n.js'
import { menu } from './ui.js'
import * as keys from './keys.js'

const getShell = () => window.__TAURI_INTERNALS__ || null
const call = (command) => {
    const sh = getShell()
    return sh ? sh.invoke('plugin:window|' + command) : Promise.resolve(false)
}

const GLYPH = {
    min: '<path d="M0 5.5h10"/>',
    max: '<path d="M.5 .5h9v9h-9z"/>',
    restore: '<path d="M.5 2.5h7v7h-7z M2.5 2.5v-2h7v7h-2"/>',
    close: '<path d="M.5 .5l9 9M9.5 .5l-9 9"/>',
}
const svg = (name) => `<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">${GLYPH[name]}</svg>`

let resizeHandler = null

export function frameHtml() {
    if (!getShell()) return ''
    const mac = /Mac/.test(navigator.platform || navigator.userAgent || '')
    if (mac) {
        return `<header class="pg-titlebar is-mac" data-tauri-drag-region="deep">`
            + `<span class="tb-mac-inset" aria-hidden="true"></span>`
            + `<span class="tb-brand" data-tauri-drag-region>The Harness</span>`
            + `<span class="tb-drag" data-tauri-drag-region></span>`
            + `</header>`
    }
    return `<header class="pg-titlebar" data-tauri-drag-region="deep">`
        + `<div class="tb-left">`
        + `<span class="tb-brand" data-tauri-drag-region>The Harness</span>`
        + `<button type="button" class="tb-menu" data-tb-menu="file">${tt('文件', 'File')}</button>`
        + `<button type="button" class="tb-menu" data-tb-menu="view">${tt('视图', 'View')}</button>`
        + `<button type="button" class="tb-menu" data-tb-menu="window">${tt('窗口', 'Window')}</button>`
        + `</div>`
        + `<div class="tb-drag" data-tauri-drag-region></div>`
        + `<div class="tb-win">`
        + `<button type="button" data-win="minimize" aria-label="${tt('最小化', 'Minimize')}">${svg('min')}</button>`
        + `<button type="button" data-win="toggle_maximize" aria-label="${tt('最大化', 'Maximize')}">${svg('max')}</button>`
        + `<button type="button" data-win="close" class="close" aria-label="${tt('关闭', 'Close')}">${svg('close')}</button>`
        + `</div>`
        + `</header>`
}

function openTitleMenu(app, kind, anchor) {
    if (kind === 'file') {
        menu(anchor, [
            { label: tt('新对话', 'New Conversation'), icon: 'plus', keys: keys.keysOf('new-chat'), run: () => app && app.newChat && app.newChat() },
            { label: tt('打开本地文件夹…', 'Open Folder…'), icon: 'folderPlus', run: () => { const b = document.querySelector('[data-act="project-open-folder"]'); if (b) b.click() } },
            { label: tt('连接 SSH 项目…', 'Connect SSH Project…'), icon: 'server', run: () => { const b = document.querySelector('[data-act="project-open-ssh"]'); if (b) b.click() } },
            '-',
            { label: tt('设置', 'Settings'), icon: 'settings', keys: keys.keysOf('settings'), run: () => app && app.openSettings && app.openSettings('general') },
        ], { align: 'start', label: tt('文件', 'File') })
        return
    }
    if (kind === 'view') {
        menu(anchor, [
            { label: tt('命令面板', 'Command Palette'), icon: 'command', keys: keys.keysOf('palette'), run: () => keys.run('palette') },
            { label: tt('快捷键', 'Keyboard Shortcuts'), icon: 'keyboard', keys: keys.keysOf('shortcuts'), run: () => keys.run('shortcuts') },
            '-',
            { label: tt('切换左侧栏', 'Toggle Sidebar'), icon: 'sidebar', keys: keys.keysOf('sidebar'), run: () => keys.run('sidebar') },
            { label: tt('切换概览面板', 'Toggle Overview'), icon: 'overview', keys: keys.keysOf('tools'), run: () => keys.run('tools') },
            { label: tt('切换底部终端', 'Toggle Terminal'), icon: 'terminal', keys: keys.keysOf('terminal'), run: () => keys.run('terminal') },
            '-',
            { label: tt('日历', 'Calendar'), icon: 'calendar', run: () => { const b = document.querySelector('[data-act="calendar"]'); if (b) b.click() } },
            { label: tt('自定义中心', 'Customizations'), icon: 'sliders', run: () => app && app.openCustomizations && app.openCustomizations() },
        ], { align: 'start', label: tt('视图', 'View') })
        return
    }
    if (kind === 'window') {
        menu(anchor, [
            { label: tt('上一个对话', 'Back'), icon: 'arrowLeft', keys: keys.keysOf('nav-back'), run: () => keys.run('nav-back') },
            { label: tt('下一个对话', 'Forward'), icon: 'arrowRight', keys: keys.keysOf('nav-forward'), run: () => keys.run('nav-forward') },
            '-',
            { label: tt('最小化', 'Minimize'), run: () => call('minimize') },
            { label: tt('最大化 / 还原', 'Maximize / Restore'), run: () => call('toggle_maximize') },
            { label: tt('重新加载界面', 'Reload Window'), icon: 'retry', run: () => location.reload() },
            '-',
            { label: tt('关闭到托盘', 'Close to Tray'), run: () => call('close') },
        ], { align: 'start', label: tt('窗口', 'Window') })
    }
}

export function start(app) {
    // Clean up any legacy fixed caption element if present
    for (const stale of document.querySelectorAll('body > .pg-win')) stale.remove()
    if (resizeHandler) {
        removeEventListener('resize', resizeHandler)
        resizeHandler = null
    }
    if (!getShell()) {
        document.documentElement.classList.remove('shell', 'mac', 'own-caption')
        return
    }
    const mac = /Mac/.test(navigator.platform || navigator.userAgent || '')
    document.documentElement.classList.add('shell', mac ? 'mac' : 'own-caption')
    const bar = document.querySelector('.pg-titlebar')
    if (!bar || mac) return
    bar.onclick = (e) => {
        const w = e.target.closest('[data-win]')
        if (w) { call(w.dataset.win); return }
        const m = e.target.closest('[data-tb-menu]')
        if (m) openTitleMenu(app, m.dataset.tbMenu, m)
    }
    const maxBtn = bar.querySelector('[data-win="toggle_maximize"]')
    const syncState = async () => {
        if (!maxBtn || !maxBtn.isConnected) return
        const on = await call('is_maximized').catch(() => false)
        maxBtn.innerHTML = svg(on ? 'restore' : 'max')
        maxBtn.setAttribute('aria-label', on ? tt('还原', 'Restore') : tt('最大化', 'Maximize'))
        document.documentElement.classList.toggle('maximized', !!on)
    }
    resizeHandler = syncState
    addEventListener('resize', resizeHandler)
    syncState()
}
