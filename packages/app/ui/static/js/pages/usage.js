// Settings › Usage, after OpenRouter's activity page: a time range at the top, the totals of
// the stretch, a chart by day for what was spent and one for the calls, then where it went (by
// chat, by what else it was for, by model). Under it, today's limit of the identity, which is
// the plan's own, with "Raise today's limit".
//
// Calls under the owner's own plan are counted as calls: they cost nothing here, and the
// agent's list price for them is shown beside them as a list price, never added to what was
// spent. A stretch without a single call is an ordinary empty state, not a chart of zeros.
import { esc, tt } from '../i18n.js'
import { post, failed } from '../api.js'
import { on, dialog, closeDialog, press, toast, empty, problem } from '../ui.js'
import { prefs } from '../prefs.js'

export const identity = true
let c = null
const RANGES = [['today', '今天', 'Today'], ['week', '最近 7 天', 'Last 7 days'], ['month', '最近 30 天', 'Last 30 days']]
// Bars are at most this thick; the rest of a day's slot is air.
const BAR = 24

// Money as read on a bill: cents, and what is less than a cent to four places.
export const money = (v) => { const n = Number(v) || 0; return n > 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}` }
const took = (s) => { const n = Number(s) || 0; return n < 60 ? tt(`${n.toFixed(1)} 秒`, `${n.toFixed(1)} s`) : tt(`${Math.floor(n / 60)} 分 ${Math.round(n % 60)} 秒`, `${Math.floor(n / 60)} min ${Math.round(n % 60)} s`) }
const day = (text) => { const d = new Date(`${text}T12:00:00`); return tt(`${d.getMonth() + 1}月${d.getDate()}日`, d.toLocaleDateString('en', { month: 'short', day: 'numeric' })) }
const calls = (n) => tt(`${n} 次调用`, `${n} call${n === 1 ? '' : 's'}`)
// what a row cost: dollars, or for calls under a plan that they were under it, with the list price as such
function cost(r) {
    if (r.cost_usd > 0) return money(r.cost_usd) + (r.plan_usd > 0 ? `<small>${tt('另有订阅下的调用，标价', 'plus calls under your plan, list price')} ${money(r.plan_usd)}</small>` : '')
    if (r.plan_usd > 0) return `${tt('订阅内', 'under your plan')}<small>${tt('标价', 'list price')} ${money(r.plan_usd)}</small>`
    return r.calls ? tt('没有价格', 'no price') : money(0)
}

// A chart by day: one column a day, each a stack of its series, growing from one baseline.
// series: [{key, label, cls}]; a column answers the pointer and the keyboard with its values.
function chart(title, days, series, format) {
    const top = Math.max(...days.map((d) => series.reduce((a, s) => a + (d[s.key] || 0), 0)), 0)
    if (!top) return ''
    const few = days.length <= 10
    const columns = days.map((d) => {
        const said = series.filter((s) => d[s.key]).map((s) => `${series.length > 1 ? s.label + ' ' : ''}${format(d[s.key])}`).join(' · ') || format(0)
        const stack = series.map((s) => (d[s.key] ? `<i class="${s.cls}" style="height:${((d[s.key] / top) * 100).toFixed(2)}%"></i>` : '')).join('')
        return `<button type="button" class="col" data-tip="${esc(`${day(d.date)} · ${said}`)}" aria-label="${esc(`${day(d.date)}: ${said}`)}"><span class="stack">${stack}</span></button>`
    }).join('')
    const marks = few ? days.map((d) => `<span>${esc(day(d.date))}</span>`).join('')
        : [0, Math.floor((days.length - 1) / 2), days.length - 1].map((i) => `<span>${esc(day(days[i].date))}</span>`).join('')
    return `<figure class="chart"><figcaption><b>${esc(title)}</b>${series.length > 1 ? `<span class="legend">${series.map((s) => `<span><i class="${s.cls}"></i>${esc(s.label)}</span>`).join('')}</span>` : ''}</figcaption>`
        + `<div class="plot" style="--n:${days.length};--bar:${BAR}px"><span class="top">${esc(format(top))}</span>${columns}</div><div class="axis${few ? ' each' : ''}" style="--n:${days.length}">${marks}</div></figure>`
}

function table(heads, rows) {
    return `<div class="tblw"><table class="ut"><thead><tr>${heads.map((h, i) => `<th${i ? ' class="num"' : ''}>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
}

export async function draw(ctx) {
    c = ctx
    const range = prefs.get('usage.range', 'week')
    const u = await ctx.get('/api/agent/usage', { identity: ctx.id, range })
    if (!u) return problem(failed.get('/api/agent/usage'), { title: tt('用量没有读出来', 'The usage could not be read'), retry: 'settings' })
    const picker = `<div class="seg" role="radiogroup" aria-label="${tt('时间范围', 'Time range')}">${RANGES.map(([id, zh, en]) => `<button type="button" role="radio" aria-checked="${id === range}" data-act="usage-range" data-arg="${id}">${tt(zh, en)}</button>`).join('')}</div>`
    const n = u.calls || { total: 0, priced: 0, plan: 0, unpriced: 0 }
    const days = u.days || []
    let body
    if (!n.total && !days.length) {
        body = empty(tt('这段时间没有模型调用', 'No model calls in this stretch'), '')
    } else {
        const parts = [n.priced ? tt(`${n.priced} 次有价格`, `${n.priced} priced`) : '', n.plan ? tt(`${n.plan} 次在你的订阅下`, `${n.plan} under your plan`) : '', n.unpriced ? tt(`${n.unpriced} 次没有价格`, `${n.unpriced} without a price`) : ''].filter(Boolean).join(' · ')
        const title = (r) => (r.chat === 'main' ? tt('主对话', 'Main conversation') : r.title || r.chat) + (r.there === false ? tt('（已删除）', ' (deleted)') : '')
        const KIND = { task: tt('任务', 'Task'), learning: tt('后台回看和 dreaming', 'Review and dreaming') }
        const BASIS = { reported: tt('提供商报的价', 'reported by the provider'), estimated: tt('按价格表估的', 'estimated from the price list'), local: tt('本机模型', 'a model on this computer'),
            plan: tt('你的订阅', 'your own plan'), unpriced: tt('没有价格', 'no price') }
        const line = (cells) => `<tr>${cells.map((x, i) => `<td${i ? ' class="num"' : ''}>${x}</td>`).join('')}</tr>`
        body = `<div class="totals"><div><b>${money(u.cost_usd)}</b><span>${tt('花费', 'Spent')}</span></div><div><b>${n.total}</b><span>${tt('模型调用', 'Model calls')}${parts ? ` · ${esc(parts)}` : ''}</span></div>`
            + `<div><b>${esc(took(u.seconds))}</b><span>${tt('模型用时', 'Model time')}</span></div>`
            + (u.plan_usd > 0 ? `<div><b>${money(u.plan_usd)}</b><span>${tt('订阅下的调用按标价折算（没有收这笔钱）', 'List price of the calls under your plan (not charged)')}</span></div>` : '') + `</div>`
            + (days.length > 1 ? `<div class="charts">${chart(tt('每天的花费', 'Spent by day'), days, [{ key: 'cost_usd', label: tt('花费', 'Spent'), cls: 's1' }], money)}`
                + chart(tt('每天的调用', 'Calls by day'), days, [{ key: 'priced_calls', label: tt('有价格', 'Priced'), cls: 's1' }, { key: 'unpriced_calls', label: tt('没有价格', 'No price'), cls: 's2' }, { key: 'plan_calls', label: tt('订阅下', 'Under your plan'), cls: 's3' }], (v) => String(v)) + `</div>` : '')
            + `<div class="lg">${tt('按对话', 'By chat')}</div>` + ((u.by_chat || []).length ? table([tt('对话', 'Chat'), tt('调用', 'Calls'), tt('用时', 'Time'), tt('花费', 'Cost')],
                u.by_chat.map((r) => line([esc(title(r)), r.calls, esc(took(r.seconds)), cost(r)]))) : `<p>${tt('这段时间对话里没有调用模型。', 'No chat called the model in this stretch.')}</p>`)
            + `<div class="lg">${tt('按事', 'By kind')}</div>` + ((u.by_task || []).length ? table([tt('做的事', 'What it was for'), tt('调用', 'Calls'), tt('用时', 'Time'), tt('花费', 'Cost')],
                u.by_task.map((r) => line([`${esc(KIND[r.kind] || r.kind)}${r.title ? `<small>${esc(r.title)}</small>` : ''}`, r.calls, esc(took(r.seconds)), cost(r)]))) : `<p>${tt('这段时间没有任务，也没有后台回看。', 'No tasks and no review in the background in this stretch.')}</p>`)
            + ((u.by_model || []).length ? `<div class="lg">${tt('按模型', 'By model')}</div>` + table([tt('模型', 'Model'), tt('调用', 'Calls'), tt('花费', 'Cost')],
                u.by_model.map((r) => line([`${esc(r.model)}<small>${esc(BASIS[r.basis] || r.basis || '')}</small>`, r.calls, cost(r)]))) : '')
    }
    const d = u.today || {}
    const budget = d.daily_budget || 0, spent = d.cost_usd || 0, callsCap = d.daily_calls || 0
    const callsNote = callsCap > 0
        ? `${tt('没有价格的调用', 'calls without a price')} ${d.unpriced_calls || 0} / ${callsCap}`
        : `${tt('没有价格的调用', 'calls without a price')} ${d.unpriced_calls || 0}（${tt('未设上限', 'no limit')}）`
    const limitSection = budget > 0
        ? `<div class="meter" role="img" aria-label="${esc(tt(`今天花了 ${money(spent)}，额度 ${money(budget)}`, `${money(spent)} spent today of ${money(budget)}`))}"><i style="width:${Math.min(100, (spent / budget) * 100)}%"></i></div>`
            + `<p>${tt('今天', 'Today')} ${money(spent)} / ${money(budget)} · ${tt('还剩', 'left')} ${money(d.left_usd ?? Math.max(0, budget - spent))} · ${tt('给你留', 'kept for you')} ${money(d.reserve)}`
            + ` · ${callsNote}${d.raised ? ' · ' + tt('今天已提高过', 'raised today') : ''}</p>`
            + `<div class="btns"><button type="button" class="b" data-act="usage-raise" data-arg="${esc(budget)}">${tt('提高今天的额度…', "Raise today's limit…")}</button><button type="button" class="b" data-act="settings" data-arg="permissions">${tt('改每日额度…', 'Change the daily limit…')}</button></div>`
        : `<p>${tt('今天', 'Today')} ${money(spent)} · ${tt('未设每日额度上限', 'No daily limit set')} · ${callsNote}</p>`
            + `<div class="btns"><button type="button" class="b" data-act="settings" data-arg="permissions">${tt('设置每日额度…', 'Set a daily limit…')}</button></div>`
    return `<div class="uhead"><p>${esc(day(u.start))}${u.end && u.end !== u.start ? ` – ${esc(day(u.end))}` : ''}</p>${picker}</div>` + body
        + `<div class="lg">${tt('今天的额度', "Today's limit")}</div>` + limitSection
}

function raise(budget) {
    const d = dialog(`<h5>${tt('提高今天的额度', "Raise today's limit")}</h5><label><span>${tt('今天的额度（美元）', "Today's limit (US$)")}</span><input class="field" type="number" step="0.5" min="0" value="${(Number(budget) || 2) + 1}"></label>`
        + `<p class="note">${tt('只改今天', 'Today only')}</p>`
        + `<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('提高', 'Raise')}</button></div>`)
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await post('/api/agent/usage', { identity: c.id, raise_today: parseFloat(d.querySelector('input').value) })
        if (!r.ok) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog(); toast(tt('今天的额度已提高', "Today's limit is raised"))
        c.app.refresh(); c.reload()
    })
}

export function actions() {
    on('usage-range', (n) => { prefs.set('usage.range', n.dataset.arg); return c.reload() })
    on('usage-raise', (n) => raise(n.dataset.arg))
}
