// Single 24px environment footer row directly under the composer:
//   Left: Project / Branch selector (`.pick.where` updated by composer.draw) + active git branch
//   Right: Clickable Context % (click to compact) + Today's spend (when > 0)
import { esc, tt, usd } from './i18n.js'
import { post } from './api.js'
import { $, menu, said } from './ui.js'
import { icon } from './icons.js'
import { choicesOf } from './names.js'

export const frameHtml = () => `<div class="pg-status" aria-label="${tt('工作区与状态', 'Workspace and status')}">`
    + `<button type="button" class="pick where" data-act="where-pick" data-tip="${tt('工作项目', 'Project')}"></button>`
    + `<span class="pg-status-meta" role="status"></span></div>`

const count = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n))

export function draw(app) {
    const bar = $('.pg-status'), meta = $('.pg-status-meta')
    if (!bar || !meta) return
    let read = app.context[app.chat] && app.context[app.chat].input_tokens ? app.context[app.chat] : null
    const recs = app.records[app.chat] || []
    for (let i = recs.length - 1; i >= 0 && !read; i--) if (recs[i].event === 'model_reply' && recs[i].usage && recs[i].usage.input_tokens) read = recs[i].usage
    const full = read && read.window ? Math.min(100, Math.round((read.input_tokens / read.window) * 100)) : null
    const row = app.row()
    const ws = (app.workspaceStats && app.workspaceStats[app.chat]) || {}
    const branch = row.branch || ws.branch || ''
    const day = app.usage.today || {}
    const spent = Number(day.cost_usd) || 0
    const showSpend = spent > 0

    const leftParts = []
    if (branch) {
        leftParts.push(`<span class="sb sb-branch" data-tip="${esc(ws.folder || row.folder || branch)}">${icon('branch', 12)}<span>${esc(branch)}</span></span>`)
    }
    const rightParts = []
    if (read) {
        const tip = tt(
            `上下文 ${read.input_tokens.toLocaleString()}${read.window ? ' / ' + read.window.toLocaleString() : ''} · 点击压缩`,
            `Context ${read.input_tokens.toLocaleString()}${read.window ? ' / ' + read.window.toLocaleString() : ''} · Click to compact`,
        )
        const lbl = full !== null ? tt(`上下文 ${full}%`, `Context ${full}%`) : tt(`上下文 ${count(read.input_tokens)}`, `Context ${count(read.input_tokens)}`)
        rightParts.push(`<button type="button" class="sb${full !== null && full >= 80 ? ' warn' : ''}" data-act="ctx-compact" data-tip="${esc(tip)}">${icon('context', 12)}<span>${esc(lbl)}</span></button>`)
    }
    if (showSpend) {
        rightParts.push(`<button type="button" class="sb" data-act="settings" data-arg="usage" data-tip="${esc(tt('今日用量', "Today's usage"))}"><span>${usd(spent)}${day.daily_budget ? ` / ${usd(day.daily_budget)}` : ''}</span></button>`)
    }
    const html = `${leftParts.join('')}<span class="grow"></span>${rightParts.join('')}`
    if (meta._html !== html) { meta._html = html; meta.innerHTML = html }
}

export function approvalsMenu(app, anchor) {
    const spec = ((app.schema || {}).approvals || {}).ask || {}
    const now = (app.values.approvals || {}).ask
    menu(anchor, [{ head: tt('哪些事先问你 · 所有对话', 'What it asks first · every chat') },
        ...(choicesOf(spec) || [{ value: now, label: String(now) }]).map(({ value: v, label }) => ({ label, checked: v === now, run: async () => {
            const r = await post('/api/app/settings', { approvals: { ask: v } })
            if (!r.ok) return said(r)
            app.applied('approvals', 'ask', v)
        } })),
        '-', { label: tt('权限与限额…', 'Permissions and limits…'), icon: 'settings', run: () => app.openSettings('permissions') }], { side: 'top' })
}
