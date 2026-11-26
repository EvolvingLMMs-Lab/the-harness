// The bar along the bottom of the chat, after Hermes Desktop's "Status bar": the chat's live
// state and quick controls without opening Settings. What waits for approval (a menu that
// changes it), how much the last model call read (the context in use), where the chat works,
// its model (the same picker as the composer's) and, as the plan puts it here, today's
// spending of the daily limit.
import { esc, tt, usd } from './i18n.js'
import { post } from './api.js'
import { $, menu, said } from './ui.js'
import { icon } from './icons.js'
import { choiceLabel, choicesOf, settingTitle } from './names.js'
import { modelOf } from './composer.js'

export const frameHtml = () => `<div class="pg-status" role="status" aria-label="${tt('这个对话的状态', "This chat's state")}"></div>`

const count = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n))

export function draw(app) {
    const bar = $('.pg-status'); if (!bar) return
    // the context in use: what the last model call of this chat read, of what the model can read at once
    let read = app.context[app.chat] && app.context[app.chat].input_tokens ? app.context[app.chat] : null
    const recs = app.records[app.chat] || []
    for (let i = recs.length - 1; i >= 0 && !read; i--) if (recs[i].event === 'model_reply' && recs[i].usage && recs[i].usage.input_tokens) read = recs[i].usage
    const full = read && read.window ? Math.min(100, Math.round((read.input_tokens / read.window) * 100)) : null
    const row = app.row()
    const day = app.usage.today || {}
    const spent = Number(day.cost_usd) || 0
    const showSpend = spent > 0 || (day.daily_budget && day.plan_usd === undefined && spent > 0)
    const parts = []
    if (read) {
        parts.push(`<span class="sb" tabindex="0" data-tip="${esc(tt(`上下文 ${read.input_tokens}${read.window ? ' / ' + read.window : ''}`,
            `Context ${read.input_tokens}${read.window ? ' / ' + read.window : ''}`))}">${icon('context', 13)}<span>${esc(full !== null ? tt(`上下文 ${full}%`, `Context ${full}%`) : tt(`上下文 ${count(read.input_tokens)}`, `Context ${count(read.input_tokens)}`))}</span></span>`)
    }
    if (row.branch) {
        parts.push(`<span class="sb" tabindex="0" data-tip="${esc(row.folder || row.branch)}">${icon('branch', 13)}<span>${esc(row.branch)}</span></span>`)
    }
    if (showSpend) {
        parts.push(`<span class="grow"></span><button type="button" class="sb" data-act="settings" data-arg="usage" data-tip="${esc(tt('用量', 'Usage'))}"><span>${usd(spent)}${day.daily_budget ? ` / ${usd(day.daily_budget)}` : ''}</span></button>`)
    }
    const html = parts.join('')
    bar.hidden = !html
    if (bar._html === html) return
    bar._html = html; bar.innerHTML = html
}

// What waits for the owner's approval, changed from the bar (it is the setting approvals.ask,
// the same for every chat).
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
