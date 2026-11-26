// The tools rail on the right and the side panel its views open in, as tabs: Context,
// Terminal, Browser, Files and Changes of the chat that is shown.
import { esc, tt, when, usd } from './i18n.js'
import { get } from './api.js'
import { $, $$ } from './ui.js'

export const RAIL = [['context', '☰', '上下文', 'Context'], ['terminal', '>_', '终端', 'Terminal'], ['browser', '◎', '浏览器', 'Browser'],
    ['files', '▢', '文件', 'Files'], ['changes', '±', '改动', 'Changes']]
const name = (id) => { const r = RAIL.find((x) => x[0] === id); return tt(r[2], r[3]) }

const tabs = new Map() // chat -> {open: [ids], on: id}

export function railHtml() {
    return RAIL.map(([id, g]) => `<button class="pg-ic" data-r="${id}" data-tip="${esc(name(id))}" aria-label="${esc(name(id))}">${g}</button>`).join('')
}

export function open(app, id) {
    const t = tabs.get(app.chat) || { open: [], on: null }
    if (!t.open.includes(id)) t.open.push(id)
    t.on = id; tabs.set(app.chat, t); render(app)
}
export function close(app, id) {
    const t = tabs.get(app.chat); if (!t) return
    t.open = t.open.filter((x) => x !== id); if (t.on === id) t.on = t.open[t.open.length - 1] || null
    render(app)
}

export async function render(app) {
    const panel = $('.pg-panel'), t = tabs.get(app.chat)
    const on = t && t.on
    panel.classList.toggle('open', !!on)
    $$('.pg-rail .pg-ic').forEach((b) => b.classList.toggle('on', b.dataset.r === on))
    if (!on) { panel.querySelector('.pg-tabs').innerHTML = ''; panel.querySelector('.pg-pane').innerHTML = ''; return }
    panel.querySelector('.pg-tabs').innerHTML = t.open.map((id) => `<div class="pg-tab${id === on ? ' on' : ''}" data-tab="${id}">${RAIL.find((x) => x[0] === id)[1]} ${esc(name(id))}<button class="x" data-close="${id}" aria-label="${tt('关闭', 'Close')}">×</button></div>`).join('')
    const pane = panel.querySelector('.pg-pane')
    const chat = app.chat
    const html = await VIEWS[on](app)
    if (app.chat === chat && (tabs.get(chat) || {}).on === on) pane.innerHTML = `<div class="pg-view">${html}</div>`
}

function runs(app) {
    return (app.records[app.chat] || []).filter((r) => r.run && (r.event === 'outcome' || r.event === 'action')).map((r) => r.run)
}

const VIEWS = {
    async context(app) {
        const meta = app.meta[app.chat] || {}, row = app.chats.find((c) => c.chat === app.chat) || {}
        const place = (app.life.places || []).find((p) => p.id === (meta.place || row.place))
        const owner = ['main', 'new'].includes(meta.kind || row.kind) || (place && ['folder', 'browser', 'desktop'].includes(place.kind))
        const spent = Object.values((app.usage.today || {}).by_source || {}).filter((s) => s.id === app.chat).reduce((a, s) => a + (s.cost_usd || 0), 0)
        return `<div class="vt">${tt('这个对话', 'This chat')}</div><div class="kv">`
            + `<b>${tt('种类', 'kind')}</b><span>${esc(meta.kind || row.kind || '')}</span>`
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
        if (!run) return `<div class="none">${tt('这个对话还没有跑过任务。', 'No task has run in this chat yet.')}</div>`
        const row = await get('/api/sessions/show', { id: run, lines: 80 })
        const lines = row && row.agents ? row.agents.flatMap((a) => a.lines || []) : []
        return `<div class="vt">${esc(run)}</div><div class="term">${lines.length ? esc(lines.join('\n')) : tt('没有输出', 'no output')}</div>`
    },
    async browser(app) {
        const run = runs(app).slice(-1)[0]
        const browser = (app.life.places || []).find((p) => p.kind === 'browser')
        if (!run) return `<div class="none">${browser ? esc(browser.title || browser.id) + ' · ' : ''}${tt('这个对话还没有浏览器画面。', 'No browser view in this chat yet.')}</div>`
        return `<div class="vt">${esc(run)}</div><div class="frame"><img class="shot" alt="" src="/api/app/screen?run=${encodeURIComponent(run)}&t=${Date.now()}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'none',textContent:'${tt('现在没有画面', 'no view now')}'}))"></div>`
    },
    async files(app) {
        const found = await get('/api/app/place', { identity: app.identity.id, chat: app.chat })
        if (!found || !found.folder) return `<div class="none">${tt('这个对话没有接着文件夹。', 'This chat works in no folder.')}</div>`
        return `<div class="vt">${esc(found.folder)}/</div>` + found.files.map((f) => `<div class="fl"><span>${f.dir ? '▸' : ' '} ${esc(f.name)}</span><span>${f.dir ? '' : when(f.modified)}</span></div>`).join('')
    },
    async changes(app) {
        const found = await get('/api/app/place', { identity: app.identity.id, chat: app.chat })
        if (!found || !found.folder) return `<div class="none">${tt('这个对话没有接着文件夹。', 'This chat works in no folder.')}</div>`
        if (!found.diff) return `<div class="none">${esc(found.folder)} · ${tt('没有改动', 'no changes')}</div>`
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
