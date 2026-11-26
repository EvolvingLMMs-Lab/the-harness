// The tools rail on the right and the side panel its views open in, as tabs: Context,
// Terminal, Browser, Files and Changes of the chat that is shown. Ctrl+J opens or closes the
// panel (Hermes Desktop: "Cmd/Ctrl+J the right one"); the rail itself is the plan's design.
import { esc, tt, when, usd } from './i18n.js'
import { get, failed } from './api.js'
import { $, $$, ic, loading, empty, problem } from './ui.js'
import { icon } from './icons.js'
import { keysOf } from './keys.js'
import { prefs } from './prefs.js'

export const RAIL = [['context', '上下文', 'Context'], ['terminal', '终端', 'Terminal'], ['browser', '浏览器', 'Browser'],
    ['files', '文件', 'Files'], ['changes', '改动', 'Changes']]
export const toolName = (id) => { const r = RAIL.find((x) => x[0] === id); return r ? tt(r[1], r[2]) : id }

const tabs = new Map() // chat -> {open: [ids], on: id | null}

export function railHtml() {
    return RAIL.map(([id]) => ic(id, toolName(id), { act: 'tool', attrs: `data-arg="${id}" aria-pressed="false"` })).join('')
}

export function open(app, id) {
    const t = tabs.get(app.chat) || { open: [], on: null }
    if (!t.open.includes(id)) t.open.push(id)
    t.on = id; tabs.set(app.chat, t); prefs.set('tools.last', id); render(app)
}
export function close(app, id) {
    const t = tabs.get(app.chat); if (!t) return
    t.open = t.open.filter((x) => x !== id); if (t.on === id) t.on = t.open[t.open.length - 1] || null
    render(app)
}
// Ctrl+J: the panel away with its tabs kept, or back on the tool used last.
export function toggle(app) {
    const t = tabs.get(app.chat)
    if (t && t.on) { t.on = null; render(app); return }
    const last = prefs.get('tools.last', 'context')
    open(app, t && t.open.includes(last) ? last : (t && t.open[t.open.length - 1]) || (RAIL.some((r) => r[0] === last) ? last : 'context'))
}

export async function render(app) {
    const panel = $('.pg-panel'), t = tabs.get(app.chat)
    const shown = t && t.on
    panel.classList.toggle('open', !!shown)
    $$('.pg-rail .pg-ic').forEach((b) => { b.classList.toggle('on', b.dataset.arg === shown); b.setAttribute('aria-pressed', b.dataset.arg === shown ? 'true' : 'false') })
    const strip = panel.querySelector('.pg-tabs'), pane = panel.querySelector('.pg-pane')
    if (!shown) { strip.innerHTML = ''; pane.innerHTML = ''; return }
    strip.innerHTML = t.open.map((id) => `<div class="pg-tab${id === shown ? ' on' : ''}"><button type="button" role="tab" aria-selected="${id === shown}" data-act="tool-tab" data-arg="${id}">${icon(id, 14)}<span>${esc(toolName(id))}</span></button>`
        + `<button type="button" class="x" data-act="tool-close" data-arg="${id}" aria-label="${esc(tt(`关闭${toolName(id)}`, `Close ${toolName(id)}`))}">${icon('close', 12)}</button></div>`).join('')
        + `<span class="pg-tabs-end">${ic('right', tt('收起工具面板', 'Close the tools panel'), { act: 'tools-toggle', keys: keysOf('tools') })}</span>`
    const chat = app.chat
    if (pane.dataset.view !== `${chat}/${shown}`) pane.innerHTML = `<div class="pg-view">${loading()}</div>`
    pane.dataset.view = `${chat}/${shown}`
    const html = await VIEWS[shown](app)
    if (app.chat !== chat || (tabs.get(chat) || {}).on !== shown) return
    pane.innerHTML = `<div class="pg-view">${html}</div>`
    for (const img of pane.querySelectorAll('img.shot')) img.onerror = () => { img.closest('.frame').outerHTML = empty(tt('现在没有画面', 'No view now')) }
}

function runs(app) {
    return (app.records[app.chat] || []).filter((r) => r.run && (r.event === 'outcome' || r.event === 'action')).map((r) => r.run)
}
// what a view shows when its request failed: the reason, the fix, and Try again
const broke = (path) => problem(failed.get(path), { retry: 'tool-retry' })
const KINDS = { main: ['主对话', 'main conversation'], place: ['一个环境的对话', "a place's chat"], new: ['新对话', 'new chat'], earlier: ['早先版本的对话（只读）', 'from an earlier version (read only)'] }

const VIEWS = {
    async context(app) {
        const meta = app.meta[app.chat] || {}, row = app.chats.find((c) => c.chat === app.chat) || {}
        const place = (app.life.places || []).find((p) => p.id === (meta.place || row.place))
        const owner = ['main', 'new'].includes(meta.kind || row.kind) || (place && ['folder', 'browser', 'desktop'].includes(place.kind))
        const spent = Object.values((app.usage.today || {}).by_source || {}).filter((s) => s.id === app.chat).reduce((a, s) => a + (s.cost_usd || 0), 0)
        const kind = KINDS[meta.kind || row.kind]
        return `<div class="vt">${tt('这个对话', 'This chat')}</div><div class="kv">`
            + `<b>${tt('种类', 'kind')}</b><span>${esc(kind ? tt(kind[0], kind[1]) : meta.kind || row.kind || '')}</span>`
            + (place ? `<b>${tt('环境', 'place')}</b><span>${esc(place.title || place.id)} · ${esc(place.kind)}${place.online === false ? ' · ' + tt('离线', 'offline') : ''}</span>` : '')
            + (meta.thing ? `<b>${tt('在里面', 'inside')}</b><span>${esc(meta.thing)}</span>` : '')
            + `<b>${tt('模型', 'model')}</b><span>${esc(app.model || '')}</span>`
            + `<b>${tt('今天花费', 'spent today')}</b><span>${usd(spent)}</span></div>`
            + `<div class="vt">${tt('每回合读入', 'Read every turn')}</div><div class="kv"><b>${tt('人设', 'persona')}</b><span>SOUL.md · IDENTITY.md · USER.md</span>`
            + `<b>${tt('记忆', 'memory')}</b><span>${owner ? tt('私人的和本对话的', 'private and this chat') : tt('只有本对话的（这里不是主人自己的地方）', "this chat only (not one of the owner's own places)")}</span>`
            + `<b>${tt('技能', 'skills')}</b><span>${tt('名字和一句话说明；用到时读全文', 'names and one-line descriptions; the full text when used')}</span></div>`
    },
    async terminal(app) {
        const run = runs(app).slice(-1)[0]
        if (!run) return empty(tt('这个对话还没有跑过任务', 'No task has run in this chat yet'), tt('它在这里开始一个任务后，任务的输出会出现在这里。', "Once it starts a task here, the task's output shows up in this tab."))
        const row = await get('/api/sessions/show', { id: run, lines: 80 })
        if (!row) return broke('/api/sessions/show')
        const lines = row.agents ? row.agents.flatMap((a) => a.lines || []) : []
        return `<div class="vt">${esc(run)}</div>` + (lines.length ? `<div class="term">${esc(lines.join('\n'))}</div>` : empty(tt('这个任务没有输出', 'This task printed nothing')))
    },
    async browser(app) {
        const run = runs(app).slice(-1)[0]
        const browser = (app.life.places || []).find((p) => p.kind === 'browser')
        if (!run) return empty(tt('这个对话还没有浏览器画面', 'No browser view in this chat yet'), browser ? browser.title || browser.id : tt('它在这里用浏览器做事时，画面会出现在这里。', 'When it works in a browser here, the view shows up in this tab.'))
        return `<div class="vt">${esc(run)}</div><div class="frame"><img class="shot" alt="${esc(tt('浏览器画面', 'The browser view'))}" src="/api/app/screen?run=${encodeURIComponent(run)}&t=${Date.now()}"></div>`
    },
    async files(app) {
        const found = await get('/api/app/place', { identity: app.identity.id, chat: app.chat })
        if (!found) return broke('/api/app/place')
        if (!found.folder) return empty(tt('这个对话没有接着文件夹', 'This chat works in no folder'), tt('在 设置 › 电脑 里接上一个项目文件夹。', 'Connect a project folder in Settings › Computer.'))
        if (!found.files.length) return `<div class="vt">${esc(found.folder)}/</div>` + empty(tt('这个文件夹是空的', 'This folder is empty'))
        return `<div class="vt">${esc(found.folder)}/</div>` + found.files.map((f) => `<div class="fl"><span>${icon(f.dir ? 'folder' : 'file', 14)}${esc(f.name)}</span><span>${f.dir ? '' : when(f.modified)}</span></div>`).join('')
    },
    async changes(app) {
        const found = await get('/api/app/place', { identity: app.identity.id, chat: app.chat })
        if (!found) return broke('/api/app/place')
        if (!found.folder) return empty(tt('这个对话没有接着文件夹', 'This chat works in no folder'), tt('在 设置 › 电脑 里接上一个项目文件夹。', 'Connect a project folder in Settings › Computer.'))
        if (!found.diff) return `<div class="vt">${esc(found.folder)}/</div>` + empty(tt('没有改动', 'No changes'))
        return `<div class="pg-diff">${diffHtml(found.diff)}</div>`
    },
}

// git diff as the prototype's Changes tab: a file, then its lines with line numbers
export function diffHtml(text) {
    let html = '', left = 0, right = 0
    for (const raw of text.split('\n')) {
        if (raw.startsWith('diff --git')) { html += `<div class="df">${esc(raw.split(' b/').pop())}</div>`; continue }
        if (raw.startsWith('index ') || raw.startsWith('--- ') || raw.startsWith('+++ ') || raw.startsWith('new file') || raw.startsWith('deleted file')) continue
        const h = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/)
        if (h) { left = +h[1]; right = +h[2]; continue }
        if (raw.startsWith('-')) html += `<div class="dl del"><span class="ln">${left++}</span>- ${esc(raw.slice(1))}</div>`
        else if (raw.startsWith('+')) html += `<div class="dl add"><span class="ln">${right++}</span>+ ${esc(raw.slice(1))}</div>`
        else if (raw.startsWith(' ')) { html += `<div class="dl"><span class="ln">${right}</span>  ${esc(raw.slice(1))}</div>`; left++; right++ }
    }
    return html
}
