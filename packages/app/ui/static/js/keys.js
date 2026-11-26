// The keyboard. One table holds every shortcut of the app: the key handler acts on it and the
// shortcut panel (Ctrl+/) prints it, so the panel cannot list a key that does nothing. The
// keys and what they do follow Hermes Desktop's "Keyboard & navigation" and "Windows, tabs &
// panes": Ctrl+K or Ctrl+P the command palette, Ctrl+/ the shortcuts, Ctrl+, Settings, Ctrl+N
// a new chat, Ctrl+B the left sidebar, Ctrl+J the right one, Ctrl+F find in the chat,
// Ctrl+Shift+F search the chats; Cmd on macOS.
//
// `where` says who acts on the key: 'app' entries are dispatched here to the function bound
// to their id (bind()); the others belong to the part of the page named, which handles them
// while it has the keyboard and is listed here so that the panel is complete.
import { tt } from './i18n.js'

export const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '')

export const SHORTCUTS = [
    { id: 'palette', keys: ['mod+k', 'mod+p'], where: 'app', group: 'general', zh: '命令面板', en: 'Command palette' },
    { id: 'shortcuts', keys: ['mod+/'], where: 'app', group: 'general', zh: '快捷键', en: 'Keyboard shortcuts' },
    { id: 'settings', keys: ['mod+,'], where: 'app', group: 'general', zh: '设置', en: 'Settings' },
    { id: 'new-chat', keys: ['mod+n'], where: 'app', group: 'general', zh: '新对话', en: 'New chat' },
    { id: 'sidebar', keys: ['mod+b'], where: 'app', group: 'general', zh: '收起或展开左栏', en: 'Hide or show the sidebar' },
    { id: 'tools', keys: ['mod+j'], where: 'app', group: 'general', zh: '打开或收起右侧的工具面板', en: 'Open or close the tools panel' },
    { id: 'search-chats', keys: ['mod+shift+f'], where: 'app', group: 'general', zh: '搜索对话', en: 'Search chats' },
    { id: 'escape', keys: ['escape'], where: 'app', group: 'general', zh: '关闭、取消；都没有时停下当前回合', en: 'Close or cancel; with nothing open, stop the turn' },
    { id: 'send', keys: ['enter'], where: 'composer', group: 'chat', zh: '发送（它在做事时进队列）', en: 'Send (joins the queue while it works)' },
    { id: 'newline', keys: ['shift+enter'], where: 'composer', group: 'chat', zh: '换行', en: 'New line' },
    { id: 'history', keys: ['up', 'down'], where: 'composer', group: 'chat', zh: '空输入框里调出发过的消息', en: 'Recall sent messages in an empty composer' },
    { id: 'find', keys: ['mod+f'], where: 'app', group: 'chat', zh: '在当前对话里查找', en: 'Find in this chat' },
    { id: 'find-next', keys: ['enter', 'shift+enter'], where: 'find', group: 'chat', zh: '查找时：下一个、上一个', en: 'While finding: next, previous match' },
    { id: 'approve', keys: ['1', '2'], where: 'approval', group: 'chat', zh: '批准卡上：选第几项', en: 'On an approval card: choose that option' },
    { id: 'chat-menu', keys: ['shift+f10'], where: 'list', group: 'list', zh: '对话的菜单：置顶、改名、归档、删除', en: "A chat's menu: pin, rename, archive, delete" },
    { id: 'chat-rename', keys: ['f2'], where: 'list', group: 'list', zh: '给选中的对话改名', en: 'Rename the chat' },
    { id: 'chat-delete', keys: ['delete'], where: 'list', group: 'list', zh: '删除选中的对话（先确认）', en: 'Delete the chat (asks first)' },
]
export const GROUPS = [['general', '全局', 'Everywhere'], ['chat', '对话', 'Chat'], ['list', '对话列表', 'Chat list']]

const NAMES = { enter: ['Enter', '↩'], escape: ['Esc', 'Esc'], up: ['↑', '↑'], down: ['↓', '↓'], delete: ['Delete', '⌫'] }

// "mod+shift+f" as people read it: Ctrl+Shift+F, or ⇧⌘F on macOS.
export function label(combo) {
    const parts = combo.split('+')
    const key = parts.pop()
    const name = NAMES[key] ? NAMES[key][mac ? 1 : 0] : key.length === 1 ? key.toUpperCase() : key.toUpperCase()
    if (mac) return (parts.includes('shift') ? '⇧' : '') + (parts.includes('alt') ? '⌥' : '') + (parts.includes('mod') ? '⌘' : '') + name
    return [...parts.map((p) => ({ mod: 'Ctrl', shift: 'Shift', alt: 'Alt' })[p]), name].join('+')
}
// The first key of a shortcut, for tooltips and the palette: keysOf('sidebar') → "Ctrl+B".
export function keysOf(id) {
    const s = SHORTCUTS.find((x) => x.id === id)
    return s ? label(s.keys[0]) : ''
}
export const nameOf = (s) => tt(s.zh, s.en)

const bound = new Map()
export function bind(id, run) { bound.set(id, run) }
export function run(id) { const f = bound.get(id); return f ? f() : undefined }

// What Esc does, asked in order: the first part that had something to close or cancel
// answers true and the rest are not asked (a dialog before the settings before the turn).
const escapes = []
export function onEscape(order, close) { escapes.push([order, close]); escapes.sort((a, b) => a[0] - b[0]) }

// The key of an event as the table writes it. Shift is part of it only for letters and named
// keys: "/" and "," are typed with Shift on some keyboards.
function combo(e) {
    const raw = e.key || ''
    const key = { ArrowUp: 'up', ArrowDown: 'down', Escape: 'escape', Enter: 'enter', Delete: 'delete' }[raw] || raw.toLowerCase()
    const mod = mac ? e.metaKey : e.ctrlKey
    const named = key.length > 1 || /[a-z0-9]/.test(key)
    return [mod ? 'mod' : '', e.altKey ? 'alt' : '', e.shiftKey && named ? 'shift' : '', key].filter(Boolean).join('+')
}

export function start({ blocked }) {
    document.addEventListener('keydown', (e) => {
        if (e.isComposing || e.keyCode === 229) return // an input method is composing: the key is its own
        const pressed = combo(e)
        if (pressed === 'escape') {
            for (const [, close] of escapes) if (close(e)) { e.preventDefault(); return }
            return
        }
        const found = SHORTCUTS.find((s) => s.where === 'app' && s.keys.includes(pressed))
        if (!found || !bound.has(found.id)) return
        e.preventDefault() // also keeps the browser's own Ctrl+F, Ctrl+P and Ctrl+J away
        if (blocked(found.id)) return
        bound.get(found.id)()
    })
}
