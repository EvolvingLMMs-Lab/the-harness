// The bar along the bottom of the chat, after Hermes Desktop's "Status bar": the chat's live
// state and quick controls without opening Settings. What waits for approval (a menu that
// changes it), how much the last model call read (the context in use), where the chat works,
// its model (the same picker as the composer's) and, as the plan puts it here, today's
// spending of the daily limit.
import { esc, tt, usd } from './i18n.js'
import { post } from './api.js'
import { $, menu, said } from './ui.js'
import { icon } from './icons.js'
import { choiceLabel, settingTitle } from './names.js'
import { modelOf } from './composer.js'

export const frameHtml = () => `<div class="pg-status" role="status" aria-label="${tt('这个对话的状态', "This chat's state")}"></div>`

const count = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n))

export function draw(app) {
    const bar = $('.pg-status'); if (!bar) return
    const approvals = (app.values.approvals || {}).ask
    const spec = ((app.schema || {}).approvals || {}).ask || {}
    // the context in use: what the last model call of this chat read
    let read = null
    const recs = app.records[app.chat] || []
    for (let i = recs.length - 1; i >= 0 && !read; i--) if (recs[i].event === 'model_reply' && recs[i].usage && recs[i].usage.input_tokens) read = recs[i].usage
    const row = app.row()
    const meta = app.meta[app.chat] || {}
    const place = (app.life.places || []).find((p) => p.id === (meta.place || row.place))
    const model = modelOf(app), day = app.usage.today || {}
    const html = (approvals ? `<button type="button" class="sb" data-act="approvals-level" data-tip="${esc(settingTitle('approvals', 'ask', spec))}">${icon('shield', 13)}<span>${esc(tt('先问你：', 'Asks first: '))}${esc(choiceLabel('approvals', 'ask', approvals, spec))}</span></button>` : '')
        + (read ? `<span class="sb" tabindex="0" data-tip="${esc(tt(`上一次模型调用读了 ${read.input_tokens} 个 token${read.cached_tokens ? `，其中 ${read.cached_tokens} 个来自缓存` : ''}`, `The last model call read ${read.input_tokens} tokens${read.cached_tokens ? `, ${read.cached_tokens} of them from the cache` : ''}`))}">${icon('context', 13)}<span>${esc(tt(`上下文 ${count(read.input_tokens)}`, `Context ${count(read.input_tokens)}`))}</span></span>` : '')
        + `<span class="grow"></span>`
        + (place ? `<span class="sb" tabindex="0" data-tip="${esc(tt('这个对话在哪里做事', 'Where this chat works'))}">${icon('folder', 13)}<span>${esc(place.title || place.id)}</span></span>` : '')
        + (model.name ? `<button type="button" class="sb${model.usable ? '' : ' warn'}" data-act="model-pick" data-tip="${esc(tt('这个对话用的模型', "This chat's model"))}">${icon('model', 13)}<span>${esc(model.name)}</span></button>` : '')
        + `<button type="button" class="sb" data-act="settings" data-arg="usage" data-tip="${esc(tt('今天花的 / 每日额度', 'Spent today / the daily limit'))}"><span>${usd(day.cost_usd)}${day.daily_budget ? ` / ${usd(day.daily_budget)}` : ''} ${esc(tt('今天', 'today'))}</span></button>`
    if (bar._html === html) return
    bar._html = html; bar.innerHTML = html
}

// What waits for the owner's approval, changed from the bar (it is the setting approvals.ask,
// the same for every chat).
export function approvalsMenu(app, anchor) {
    const spec = ((app.schema || {}).approvals || {}).ask || {}
    const now = (app.values.approvals || {}).ask
    menu(anchor, [{ head: tt('哪些事先问你 · 所有对话', 'What it asks first · every chat') },
        ...(spec.bounds || [now]).map((v) => ({ label: choiceLabel('approvals', 'ask', v, spec), checked: v === now, run: async () => {
            const r = await post('/api/app/settings', { approvals: { ask: v } })
            if (!r.ok) return said(r)
            app.applied('approvals', 'ask', v)
        } })),
        '-', { label: tt('权限与限额…', 'Permissions and limits…'), icon: 'settings', run: () => app.openSettings('permissions') }], { side: 'top' })
}
