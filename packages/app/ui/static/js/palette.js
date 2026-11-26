// The command palette (Ctrl+K or Ctrl+P) and the shortcut panel (Ctrl+/), after Hermes Desktop's
// "Keyboard & navigation": the palette jumps to actions and places from the keyboard (any
// page or settings section, a chat by its title, the model, the theme); the panel lists the
// shortcuts, from the same table the key handler acts on (keys.js).
import { esc, tt } from './i18n.js'
import { $, $$, el, dialog, closeDialog } from './ui.js'
import { icon } from './icons.js'
import { SHORTCUTS, GROUPS, label, nameOf, mac } from './keys.js'

// Rows drawn at once; typing narrows a longer list.
const ROWS = 60

let box = null, all = [], shown = [], at = 0, returnTo = null

export const paletteOpen = () => !!box
export function closePalette() {
    if (!box) return false
    box.remove(); box = null
    if (returnTo && document.contains(returnTo)) returnTo.focus()
    returnTo = null
    return true
}

// How well a command answers what was typed: every word must be in its title or group; a
// title that starts with the text comes first, then a title that contains it.
function rank(command, words, whole) {
    const title = command.title.toLowerCase(), hay = `${title} ${(command.group || '').toLowerCase()} ${(command.also || '').toLowerCase()}`
    if (!words.every((w) => hay.includes(w))) return -1
    return title.startsWith(whole) ? 0 : title.includes(whole) ? 1 : 2
}

function draw() {
    const input = box.querySelector('input'), list = box.querySelector('.pal-list')
    const whole = input.value.trim().toLowerCase(), words = whole.split(/\s+/).filter(Boolean)
    shown = all.map((c, i) => [rank(c, words, whole), i, c]).filter((r) => r[0] >= 0).sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, ROWS).map((r) => r[2])
    at = Math.min(at, Math.max(0, shown.length - 1))
    list.innerHTML = shown.length ? shown.map((c, i) => `<div class="po${i === at ? ' on' : ''}" role="option" id="pal-${i}" aria-selected="${i === at}" data-i="${i}">`
        + `<span class="pi">${c.icon ? icon(c.icon, 14) : ''}</span><span class="pt">${esc(c.title)}</span>${c.group ? `<span class="pg">${esc(c.group)}</span>` : ''}${c.keys ? `<kbd>${esc(c.keys)}</kbd>` : ''}</div>`).join('')
        : `<div class="pal-none">${esc(tt('没有匹配的命令或对话。', 'No command or chat matches.'))}</div>`
    input.setAttribute('aria-activedescendant', shown.length ? `pal-${at}` : '')
    const on = list.querySelector('.po.on')
    if (on) on.scrollIntoView({ block: 'nearest' })
}

function choose(i) {
    const command = shown[i]
    if (!command) return
    closePalette()
    command.run()
}

// commands: [{title, group, keys, icon, also, run}], in the order to show them with nothing typed.
export function openPalette(commands) {
    if (box) { closePalette(); return }
    returnTo = document.activeElement
    all = commands; at = 0
    const name = tt('命令面板', 'Command palette')
    box = el('div', 'pal-layer', `<div class="pal" role="dialog" aria-modal="true" aria-label="${esc(name)}">`
        + `<div class="pal-in">${icon('search')}<input type="text" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-autocomplete="list" autocomplete="off" spellcheck="false" placeholder="${esc(tt('输入命令、对话的标题或设置页', 'Type a command, a chat title or a settings page'))}"></div>`
        + `<div class="pal-list" id="pal-list" role="listbox" aria-label="${esc(name)}"></div>`
        + `<div class="pal-foot"><kbd>↑</kbd><kbd>↓</kbd> ${esc(tt('移动', 'move'))} · <kbd>${label('enter')}</kbd> ${esc(tt('执行', 'run'))} · <kbd>Esc</kbd> ${esc(tt('关闭', 'close'))}</div></div>`)
    $('.app').append(box)
    const input = box.querySelector('input')
    input.addEventListener('input', () => { at = 0; draw() })
    box.addEventListener('keydown', (e) => {
        if (e.isComposing || e.keyCode === 229) return
        if (e.key === 'ArrowDown') { e.preventDefault(); at = shown.length ? (at + 1) % shown.length : 0; draw() }
        else if (e.key === 'ArrowUp') { e.preventDefault(); at = shown.length ? (at - 1 + shown.length) % shown.length : 0; draw() }
        else if (e.key === 'Home' && e.ctrlKey) { e.preventDefault(); at = 0; draw() }
        else if (e.key === 'End' && e.ctrlKey) { e.preventDefault(); at = Math.max(0, shown.length - 1); draw() }
        else if (e.key === 'Enter') { e.preventDefault(); choose(at) }
        else if (e.key === 'Tab') e.preventDefault() // the keyboard stays in the palette
    })
    box.addEventListener('mousedown', (e) => { if (e.target === box) closePalette() })
    box.querySelector('.pal-list').addEventListener('mousemove', (e) => {
        const row = e.target.closest('.po')
        if (row && +row.dataset.i !== at) { at = +row.dataset.i; $$('.po', box).forEach((r, i) => { r.classList.toggle('on', i === at); r.setAttribute('aria-selected', i === at) }) }
    })
    box.querySelector('.pal-list').addEventListener('click', (e) => { const row = e.target.closest('.po'); if (row) choose(+row.dataset.i) })
    draw()
    input.focus()
}

export function openShortcuts() {
    const keys = (s) => s.keys.map((k) => `<kbd>${esc(label(k))}</kbd>`).join(' ')
    const d = dialog(`<h5>${esc(tt('快捷键', 'Keyboard shortcuts'))}</h5>`
        + GROUPS.map(([id, zh, en]) => `<div class="kg">${esc(tt(zh, en))}</div><div class="keys">`
            + SHORTCUTS.filter((s) => s.group === id).map((s) => `<div class="kr"><span>${esc(nameOf(s))}</span><span class="kk">${keys(s)}</span></div>`).join('') + `</div>`).join('')
        + `<p class="note">${esc(mac ? tt('在浏览器标签页里打开时，浏览器会自己留着其中几个键（⌘N、⌘P）；在桌面应用里都有效。', 'Opened in a browser tab, the browser keeps a few of these for itself (⌘N, ⌘P); in the desktop app they all work.')
            : tt('在浏览器标签页里打开时，浏览器会自己留着其中几个键（Ctrl+N、Ctrl+P）；在桌面应用里都有效。', 'Opened in a browser tab, the browser keeps a few of these for itself (Ctrl+N, Ctrl+P); in the desktop app they all work.'))}</p>`
        + `<div class="row"><span class="res"></span><button type="button" class="btn" data-default>${esc(tt('关闭', 'Close'))}</button></div>`)
    d.classList.add('wide')
    d.querySelector('.btn').onclick = closeDialog
}
