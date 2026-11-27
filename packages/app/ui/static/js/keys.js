// The keyboard. One table holds every shortcut of the app: the key handler acts on it and the
// shortcut panel (Ctrl+/) prints it, so the panel cannot list a key that does nothing. The
// keys and what they do follow Hermes Desktop's "Keyboard & navigation" and "Windows, tabs &
// panes": Ctrl+K or Ctrl+P the command palette, Ctrl+/ the shortcuts, Ctrl+, Settings, Ctrl+N
// a new chat, Ctrl+B the left sidebar, Ctrl+J the right one, Ctrl+F find in the chat,
// Ctrl+Shift+F search the chats; Cmd on macOS. The calendar's keys are those of "Use keyboard
// shortcuts in Google Calendar" (single letters, while the calendar is in view).
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
    { id: 'tools', keys: ['mod+j', 'mod+alt+o'], where: 'app', group: 'general', zh: '打开或收起概览面板', en: 'Toggle Overview panel' },
    { id: 'terminal', keys: ['mod+`'], where: 'app', group: 'chat', zh: '打开或收起底部终端', en: 'Toggle bottom terminal' },
    { id: 'nav-back', keys: ['alt+left'], where: 'app', group: 'general', zh: '返回上一个对话', en: 'Previous conversation' },
    { id: 'nav-forward', keys: ['alt+right'], where: 'app', group: 'general', zh: '前进到下一个对话', en: 'Next conversation' },
    { id: 'search-chats', keys: ['mod+shift+f'], where: 'app', group: 'general', zh: '搜索对话', en: 'Search chats' },
    { id: 'escape', keys: ['escape'], where: 'app', group: 'general', zh: '关闭、取消；都没有时停下当前回合', en: 'Close or cancel; with nothing open, stop the turn' },
    { id: 'send', keys: ['enter'], where: 'composer', group: 'chat', zh: '发送（它在做事时进队列）', en: 'Send (joins the queue while it works)' },
    { id: 'newline', keys: ['shift+enter'], where: 'composer', group: 'chat', zh: '换行', en: 'New line' },
    { id: 'history', keys: ['up', 'down'], where: 'composer', group: 'chat', zh: '空输入框里调出发过的消息', en: 'Recall sent messages in an empty composer' },
    { id: 'find', keys: ['mod+f'], where: 'app', group: 'chat', zh: '在当前对话里查找', en: 'Find in this chat' },
    { id: 'find-next', keys: ['enter', 'shift+enter'], where: 'find', group: 'chat', zh: '查找时：下一个、上一个', en: 'While finding: next, previous match' },
    { id: 'approve', keys: ['1', '2', '3'], where: 'approval', group: 'chat', zh: '批准卡上：选第几项', en: 'On an approval card: choose that option' },
    { id: 'chat-menu', keys: ['shift+f10'], where: 'list', group: 'list', zh: '对话的菜单：置顶、改名、归档、删除', en: "A chat's menu: pin, rename, archive, delete" },
    { id: 'chat-rename', keys: ['f2'], where: 'list', group: 'list', zh: '给选中的对话改名', en: 'Rename the chat' },
    { id: 'chat-delete', keys: ['delete'], where: 'list', group: 'list', zh: '删除选中的对话（先确认）', en: 'Delete the chat (asks first)' },
    { id: 'cal-day', keys: ['d', '1'], where: 'calendar', group: 'calendar', zh: '日视图', en: 'Day view' },
    { id: 'cal-week', keys: ['w', '2'], where: 'calendar', group: 'calendar', zh: '周视图', en: 'Week view' },
    { id: 'cal-month', keys: ['m', '3'], where: 'calendar', group: 'calendar', zh: '月视图', en: 'Month view' },
    { id: 'cal-year', keys: ['y'], where: 'calendar', group: 'calendar', zh: '年视图', en: 'Year view' },
    { id: 'cal-schedule', keys: ['a'], where: 'calendar', group: 'calendar', zh: '日程视图', en: 'Schedule view' },
    { id: 'cal-today', keys: ['t'], where: 'calendar', group: 'calendar', zh: '回到今天', en: 'Go to today' },
    { id: 'cal-next', keys: ['j', 'n'], where: 'calendar', group: 'calendar', zh: '下一段（下一天、周、月、年）', en: 'Next period (day, week, month, year)' },
    { id: 'cal-previous', keys: ['k', 'p'], where: 'calendar', group: 'calendar', zh: '上一段', en: 'Previous period' },
    { id: 'cal-go', keys: ['g'], where: 'calendar', group: 'calendar', zh: '去某一天', en: 'Go to a date' },
    { id: 'cal-create', keys: ['c'], where: 'calendar', group: 'calendar', zh: '新建一件事', en: 'Create an entry' },
    { id: 'cal-open', keys: ['enter'], where: 'calendar', group: 'calendar', zh: '选中的事：看它的卡片', en: 'The entry in focus: its card' },
    { id: 'cal-edit', keys: ['e'], where: 'calendar', group: 'calendar', zh: '编辑选中的事', en: 'Edit the entry in focus' },
    { id: 'cal-delete', keys: ['delete', 'backspace'], where: 'calendar', group: 'calendar', zh: '删除选中的事（可撤销）', en: 'Delete the entry in focus (can be undone)' },
    { id: 'cal-undo', keys: ['z'], where: 'calendar', group: 'calendar', zh: '撤销刚才的改动', en: 'Undo the last change' },
    { id: 'cal-search', keys: ['/'], where: 'calendar', group: 'calendar', zh: '搜索日历', en: 'Search the calendar' },
    { id: 'cal-refresh', keys: ['r'], where: 'calendar', group: 'calendar', zh: '重新读一遍', en: 'Refresh' },
]
export const GROUPS = [['general', '全局', 'Everywhere'], ['chat', '对话', 'Chat'], ['list', '对话列表', 'Chat list'], ['calendar', '日历', 'Calendar']]

const NAMES = { enter: ['Enter', '↩'], escape: ['Esc', 'Esc'], up: ['↑', '↑'], down: ['↓', '↓'], left: ['←', '←'], right: ['→', '→'], delete: ['Delete', '⌦'], backspace: ['Backspace', '⌫'], '`': ['`', '`'] }

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
    const key = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Escape: 'escape', Enter: 'enter', Delete: 'delete' }[raw] || raw.toLowerCase()
    const mod = mac ? e.metaKey : e.ctrlKey
    const named = key.length > 1 || /[a-z0-9]/.test(key)
    return [mod ? 'mod' : '', e.altKey ? 'alt' : '', e.shiftKey && named ? 'shift' : '', key].filter(Boolean).join('+')
}

// The shortcut of one part of the page that a key event means, if any: that part acts on it
// (the calendar does, for where: 'calendar').
export const meant = (e, where) => SHORTCUTS.find((s) => s.where === where && s.keys.includes(combo(e))) || null

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
