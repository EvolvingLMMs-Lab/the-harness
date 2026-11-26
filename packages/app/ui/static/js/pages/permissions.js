// Settings › Permissions and limits, after Hermes Desktop's Safety and Claude Code's
// /permissions: what waits for the owner's approval, what an identity may spend a day, and
// how much it does on its own.
import { esc, tt, when } from '../i18n.js'
import { post } from '../api.js'
import { on, toggle, flash, row, act, lock } from '../ui.js'

export const identity = true

export async function draw(ctx) {
    const [pending, life] = await Promise.all([ctx.get('/api/agent/approvals', { identity: ctx.id }), ctx.get('/api/agent/life', { identity: ctx.id })])
    const waiting = (pending && pending.pending) || []
    const paused = !!(life && life.paused)
    return `<p>${tt('只有两种人：主人和其他人。其他人只能请它做所在对话里的事，不能让它动你的电脑、文件和账号，也不能替你批准。付款永远要你批准，登录永远由你来。',
        'Two kinds of people: the owner and everyone else. Everyone else can ask it only for things within their chat; they cannot have it touch your computer, files or accounts, or approve for you. Payment always needs your approval; logging in is always yours.')}</p>`
        + (waiting.length ? `<div class="lg">${tt('等你批准', 'Waiting for you')}</div>` + waiting.map((a) => row({ title: `${esc(a.what || a.verb)} <span class="code">${esc(a.code)}</span>`,
            sub: esc([a.place, a.expires ? tt(`到 ${when(a.expires, { day: false })}`, `until ${when(a.expires, { day: false })}`) : ''].filter(Boolean).join(' · ')),
            actions: ctx.id === ctx.app.identity.id ? act(tt('去回答', 'Answer it'), 'permissions-chat', a.chat || 'main') : '' })).join('') : '')
        + `<div class="lg">${tt('批准', 'Approvals')}</div>` + ctx.setting('approvals.ask') + ctx.setting('approvals.programs') + ctx.setting('approvals.timeout_minutes') + ctx.setting('approvals.rules')
        + `<div class="lg">${tt('额度', 'Limits')}</div>` + ctx.setting('agent.daily_budget') + ctx.setting('agent.reserve') + ctx.setting('agent.daily_calls')
        + ctx.setting('limits.max_steps') + ctx.setting('limits.max_minutes')
        + ctx.group(tt('子 agent 和并行', 'Sub-agents and work side by side'), ['session.agents', 'limits.agent_depth', 'workspace.workers'])
        + `<div class="lg">${tt('它自己做', 'On its own')}</div>`
        + `<div class="sr" data-life><div><b>${tt('暂停', 'Paused')}</b><small>${tt('暂停时不叫醒模型、不做动作；渠道照常连着、事件照常记下，继续后再处理。', 'While paused the model is not woken and no actions run; channels stay connected and events are recorded, handled after resuming.')}</small></div><div class="ctl">${toggle(paused, tt('暂停', 'Paused'))}</div></div>`
        + ctx.setting('agent.proactive') + ctx.setting('agent.stale_hours')
        + `<p>${tt('每个环境自己的主动程度在"电脑"里设。', 'How much it does on its own in each place is set under Computer.')}</p>`
}

export function wire(ctx, pane) {
    const t = pane.querySelector('[data-life] .tog')
    t.onclick = () => {
        if (t.getAttribute('aria-busy') === 'true') return
        const pause = !t.classList.contains('on')
        lock(t, post(pause ? '/api/agent/pause' : '/api/agent/resume', { identity: ctx.id }).then((r) => {
            if (!r.ok) return flash(t.parentElement, r.error || tt('没改成', 'Not changed'), { error: true, fix: r.fix || '' })
            t.classList.toggle('on', !!r.data.paused); t.setAttribute('aria-checked', r.data.paused ? 'true' : 'false')
            flash(t.parentElement, tt('已保存', 'Saved'))
            ctx.app.refresh()
        }))
    }
}

export function actions(app) {
    on('permissions-chat', async (n) => { await app.openChat(n.dataset.arg) })
}
