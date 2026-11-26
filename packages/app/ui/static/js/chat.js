// A chat's record as the chat shows it. What was said is Hermes Desktop's "Chat": replies as
// Markdown, tool activity live and then one structured summary that opens, thinking that can be
// hidden, an error card when a turn fails ("Failed turns": the reason, Retry, Switch model,
// Open logs, Copy error). The approval card asks as Claude Code's permission prompt does
// ("Do you want to proceed?", 1. Yes, 2. No, and tell it what to do differently (esc)); where
// it sits, in the chat, is the plan's. The rows of the plan's own records (events of a place,
// the tree's reactions, what it learned, the five outcomes with their colours and symbols)
// keep their names and marks, the same as in the terminal (tokens.css). Model calls and queue
// bookkeeping are quiet.
import { esc, tt, outcome, when } from './i18n.js'
import { icon } from './icons.js'
import { markdown } from './markdown.js'

const HIDDEN = new Set(['model_request', 'model_reply', 'queued', 'wake_queued', 'turn_started', 'compacted', 'opened',
    'intention', 'span_start', 'span_end', 'approval_answer', 'deferred', 'awake', 'dreamed', 'model_cancelled', 'queue'])
const label = { event: ['事件', 'event'], reaction: ['反应', 'reaction'], action: ['动作', 'action'], learned: ['学会', 'learned'],
    review: ['回看', 'review'], calendar: ['日历', 'calendar'], noted: ['记住', 'noted'] }
const L = (k) => tt(label[k][0], label[k][1])
// Characters of an action's arguments or result shown when it is opened.
const DETAIL = 4000
// the worst outcome first: what a group of actions shows as a whole
const WORST = ['failed', 'refused', 'unknown', 'cancelled', 'done']

function args(a) {
    if (a === undefined || a === null) return ''
    if (typeof a === 'string') return JSON.stringify(a)
    const v = Object.values(a)
    if (v.length === 1 && typeof v[0] !== 'object') return JSON.stringify(v[0])
    return v.length ? JSON.stringify(a) : ''
}
// an action as a call: group.say("…"), files.read("~/Pictures"), task(goal)
export function call(r) {
    if (r.verb === 'task') return `task(${JSON.stringify(r.goal || (r.args || {}).goal || '')})`
    const a = args(r.args)
    const obj = r.object && typeof r.object !== 'object' ? String(r.object) : ''
    return `${r.verb || 'action'}(${a || (obj ? JSON.stringify(obj) : '')})`
}
const pretty = (value) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    return text.length > DETAIL ? text.slice(0, DETAIL) + '\n…' : text
}
const clock = (time) => { const d = new Date(time * 1000); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` }
const seconds = (s) => (s < 60 ? tt(`${Math.max(1, Math.round(s))} 秒`, `${Math.max(1, Math.round(s))} s`) : tt(`${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`, `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`))

function eventText(r) {
    const d = r.data || {}
    if (typeof d === 'string') return d
    return d.text || d.title || d.summary || d.message_text || [r.kind, ...Object.entries(d).filter(([, v]) => typeof v !== 'object').slice(0, 3).map(([k, v]) => `${k}=${v}`)].filter(Boolean).join(' · ')
}

// The reason of a failure without the name of the exception that carried it.
export const plainError = (text) => String(text || '').replace(/^[A-Za-z_][\w.]*(Error|Exception|Refused|Limit):\s*/, '')

// The rows of a chat, as HTML, from its records in order.
// ctx: {name, titles, thinking (show thinking), busy (a turn is running in this chat)}
export function rows(records, ctx) {
    const out = [], approvals = new Map()
    let group = null // the run of actions being gathered
    let lastLimit = -1
    const push = (row) => { group = null; out.push(row) }
    for (const r of records) {
        const ev = r.event
        if (HIDDEN.has(ev)) continue
        if (ev === 'action') {
            if (!group) { group = { actions: [] }; out.push(group) }
            group.actions.push({ verb: r.verb, call: call(r), args: r.verb === 'task' ? { goal: r.goal, ...(r.send ? { send: r.send } : {}) } : r.args, object: r.object, start: r.time })
        } else if (ev === 'outcome') {
            const open = group && [...group.actions].reverse().find((a) => a.verb === r.verb && !a.end)
            const done = { end: r.end || 'unknown', reason: r.reason || r.summary || '', run: r.run, stop: r.time, ...(r.result !== undefined ? { result: r.result } : {}) }
            if (open) Object.assign(open, done)
            else {
                // an outcome whose action was said elsewhere (a task that ended later, a skill the tree ran)
                if (!group) { group = { actions: [] }; out.push(group) }
                group.actions.push({ verb: r.verb, call: `${r.verb || 'action'}()`, start: r.time, ...done })
            }
        } else if (ev === 'action_result') {
            const last = group && group.actions[group.actions.length - 1]
            if (last && last.result === undefined) last.result = r.result
        } else if (ev === 'user') {
            const via = r.channel ? ` · ${esc(r.channel)}` : ''
            const files = (r.files || []).map((f) => `<span class="att">${icon('file', 12)}${esc(typeof f === 'string' ? f : f.name || '')}</span>`).join('')
            push({ html: `<div class="pe say me" data-seq="${r.seq}"><small>${tt('你', 'you')}${via}</small><div class="tx">${esc(r.text)}</div>${files ? `<div class="atts">${files}</div>` : ''}</div>` })
        } else if (ev === 'reply') {
            push({ html: `<div class="pe say" data-seq="${r.seq}"><small>${esc(ctx.name)}</small>${thought(r.reasoning, ctx)}<div class="md">${markdown(r.text)}</div></div>` })
        } else if (ev === 'event') {
            const d = r.data || {}
            if (d.text && (d.name || d.from)) {
                push({ html: `<div class="pe say"><small><span class="k event">${L('event')}</span> · ${esc(d.name || d.from)}</small><div class="tx">${esc(d.text)}</div></div>` })
            } else {
                const kind = r.kind === 'calendar' ? L('calendar') : L('event')
                push({ html: line('event', kind, esc(eventText(r))) })
            }
        } else if (ev === 'calendar') {
            const e = r.entry || {}
            push({ html: line('event', L('calendar'), esc([e.title, e.at ? when(e.at) : ''].filter(Boolean).join(' · '))) })
        } else if (ev === 'reaction') {
            const t = r.about || [r.node, typeof r.answer === 'string' ? r.answer : ''].filter(Boolean).join(' → ')
            push({ html: line('reaction', L('reaction'), esc(t)) })
        } else if (ev === 'woken') {
            const why = (r.why || []).map((w) => (typeof w === 'string' ? w : w.why || w.kind || JSON.stringify(w))).join(', ')
            push({ html: line('quiet', tt('叫醒', 'woken'), esc(why) + (r.summarized ? ` <span class="w">— ${tt('旧事件合成摘要', 'older events as one summary')}</span>` : ''), 'quiet') })
        } else if (ev === 'learned') {
            const t = [r.kind, r.name, r.evidence].filter(Boolean).join(' · ')
            push({ html: line('learned', r.kind === 'memory' ? L('noted') : L('learned'), esc(t)) })
        } else if (ev === 'summary') {
            push({ html: summaryCard(r) })
        } else if (ev === 'channel' && r.owner_code) {
            // binding the owner in a channel: the words are the channel package's own (text: {en, zh})
            const how = (r.text && (typeof r.text === 'object' ? tt(r.text.zh || r.text.en, r.text.en || r.text.zh) : r.text))
                || tt(`用你自己的账号私聊${ctx.name}在这个渠道里的账号，发送下面的码。绑定后，你在那里和它的私聊就是这个主对话。`, `From your own account, send the code below to ${ctx.name}'s account on that channel in a private chat. After that, your private chat with it there is this main conversation.`)
            push({ html: `<div class="pe card"><div class="ah"><b>${tt('在这个渠道里绑定你自己', 'Bind yourself as the owner in this channel')}</b><span class="code">${esc(r.owner_code)}</span></div><p>${esc(how)}</p>`
                + (r.expires ? `<small class="exp">${tt(`这个码到 ${clock(r.expires)} 有效。`, `The code is good until ${clock(r.expires)}.`)}</small>` : '') + `</div>` })
        } else if (ev === 'channel' && r.pairing) {
            // someone the agent does not know wrote to it: the owner lets them in, or lets the code run out
            const who = r.pairing.name || r.pairing.user || tt('有人', 'Someone')
            push({ html: `<div class="pe card"><div class="ah"><b>${tt(`${esc(who)} 想和${esc(ctx.name)}私聊`, `${esc(who)} wants to message ${esc(ctx.name)}`)}</b><span class="code">${esc(r.pairing.code || '')}</span></div>`
                + `<p>${tt('批准之前，对方的消息不保存。不批准的话什么都不用做，码过期就作废。', 'Until you approve, their messages are not kept. To refuse, do nothing: the code runs out.')}${r.pairing.expires ? ' ' + tt(`到 ${clock(r.pairing.expires)} 有效。`, `It is good until ${clock(r.pairing.expires)}.`) : ''}</p>`
                + `<div class="na"><button type="button" class="pri" data-act="pair" data-arg="${esc(r.account || '')}" data-code="${esc(r.pairing.code || '')}">${tt('批准', 'Approve')}</button><button type="button" data-act="settings" data-arg="connectors">${tt('连接器…', 'Connectors…')}</button></div></div>` })
        } else if (ev === 'review') {
            push({ html: line('review', L('review'), esc(r.text || r.note || '')) })
        } else if (ev === 'approval') {
            const known = approvals.get(r.code)
            if (known) { Object.assign(known.data, r); continue }
            const row = { approval: true, data: { ...r } }
            approvals.set(r.code, row); push(row)
        } else if (ev === 'asleep' || ev === 'spending_limit') {
            if (lastLimit === out.length - 1 && lastLimit >= 0) continue
            lastLimit = out.length
            push({ html: limitCard(r.fix) })
        } else if (ev === 'done') {
            if (r.note) push({ html: line('quiet', tt('完成', 'done'), esc(r.note), 'quiet') })
        } else if (ev === 'error') {
            // a turn that failed gets the card; a failure of work in the background is one line
            if (r.job) push({ failed: r })
            else push({ html: line('failed', tt('出错', 'error'), esc(plainError(r.error))) })
        } else if (ev === 'life') {
            if (r.state === 'started' || r.state === 'stopped') continue // the host starting and quitting: bookkeeping
            const s = { paused: tt('已暂停', 'paused'), resumed: tt('已继续', 'resumed'), 'own paused': tt('不再自己做事', 'no longer acts on its own'), 'own resumed': tt('又自己做事了', 'acts on its own again') }[r.state] || r.state
            push({ html: line('quiet', tt('状态', 'state'), esc(s), 'quiet') })
        } else if (ev === 'interrupted') {
            // what it had written when it was stopped stays on the screen
            if (r.text) push({ html: `<div class="pe say cut" data-seq="${r.seq}"><small>${esc(ctx.name)} · ${tt('写到这里被停下', 'stopped while writing this')}</small><div class="md">${markdown(r.text)}</div></div>` })
            push({ html: line('quiet', tt('已停下', 'stopped'), esc(r.reason || tt('这一回合被停下了；做完的部分保留。', 'This turn was stopped; what was done is kept.')), 'quiet') })
        }
    }
    const last = out[out.length - 1]
    return out.map((row) => {
        if (row.html) return row.html
        if (row.approval) return approvalCard(row.data, ctx)
        if (row.failed) return failedCard(row.failed)
        return activity(row.actions, ctx.busy && row === last)
    })
}

function line(kind, labelText, html, cls = '') {
    return `<div class="pe line ${cls}"><span class="k ${kind}">${esc(labelText)}</span><span class="t">${html}</span></div>`
}

// Thinking that came with a reply, closed until it is opened (and not there at all when
// thinking is hidden in Settings).
function thought(text, ctx) {
    if (!text || !ctx.thinking) return ''
    return `<details class="thinking"><summary>${icon('right', 12)}${esc(tt('想过的', 'Thinking'))}</summary><div class="tx">${esc(text)}</div></details>`
}

const badge = (end) => (end ? `<span class="oc ${esc(end)}">${outcome(end)}</span>` : `<span class="oc pending"><span class="spin"></span>${outcome('pending')}</span>`)

// One action, opening to what it was given and what came back.
function action(a) {
    const given = a.args && typeof a.args === 'object' && Object.keys(a.args).length ? a.args : a.object
    const body = [
        given !== undefined && given !== null && given !== '' ? `<div class="dk">${esc(tt('给它的', 'given'))}</div><pre>${esc(pretty(given))}</pre>` : '',
        a.reason ? `<div class="dk">${esc(tt('结果', 'outcome'))}</div><pre>${esc(pretty(a.reason))}</pre>` : '',
        a.result !== undefined && a.result !== null ? `<div class="dk">${esc(tt('返回的', 'returned'))}</div><pre>${esc(pretty(a.result))}</pre>` : '',
        a.run ? `<div class="dk">${esc(tt('任务', 'task'))}</div><pre>${esc(a.run)}</pre>` : '',
    ].join('')
    const took = a.end && a.stop && a.start ? `<span class="tk">${seconds(a.stop - a.start)}</span>` : ''
    const head = `<span class="k action">${L('action')}</span><span class="t">${esc(a.call)}</span>${took}${badge(a.end)}`
    return body ? `<details class="act"><summary>${head}</summary><div class="ad">${body}</div></details>` : `<div class="act"><div class="sum">${head}</div></div>`
}

// A run of actions. While the turn is at work on it, each action shows as it happens; once it
// is over, one line says how it went (how many, how they ended, how long) and opens to the list.
function activity(actions, live) {
    if (actions.length === 1) return `<div class="pe acts one">${action(actions[0])}</div>`
    const list = actions.map(action).join('')
    if (live) return `<div class="pe acts">${list}</div>`
    const counts = {}
    for (const a of actions) counts[a.end || 'pending'] = (counts[a.end || 'pending'] || 0) + 1
    const said = [...WORST, 'pending'].filter((end) => counts[end]).map((end) => `${counts[end]} ${outcome(end)}`).join(' · ')
    const worst = counts.pending ? null : WORST.find((end) => counts[end])
    const first = actions[0].start, lastStop = Math.max(...actions.map((a) => a.stop || 0))
    const took = first && lastStop > first ? ` · ${seconds(lastStop - first)}` : ''
    return `<details class="pe acts sumup"><summary><span class="k action">${L('action')}</span><span class="t">${tt(`${actions.length} 个动作`, `${actions.length} actions`)} · ${esc(said)}${took}</span>${badge(worst)}</summary><div class="al">${list}</div></details>`
}

// The approval request, asked as Claude Code asks for a permission.
export function approvalCard(a, ctx) {
    const pending = !a.state || a.state === 'waiting'
    const code = esc(a.code || '')
    const where = [a.verb, ctx.titles && a.in_chat ? ctx.titles[a.in_chat] || a.in_chat : a.place, a.why].filter(Boolean).map(esc).join(' · ')
    const head = `<div class="ah"><b>${esc(a.what || a.verb || tt('要你批准', 'Needs your approval'))}</b><span class="code">${code}</span></div>` + (where ? `<p>${where}</p>` : '')
    if (!pending) {
        const done = { approved: ['done', tt('已同意', 'Allowed')], rejected: ['refused', tt('已拒绝', 'Declined')], cancelled: ['cancelled', tt('没人批准，已取消', 'Nobody answered: cancelled')],
            elsewhere: ['unknown', tt('已在别处处理', 'Handled elsewhere')] }[a.state] || ['unknown', a.state]
        const why = a.reason && !['approved', 'rejected'].includes(a.reason) ? ` — ${esc(a.reason)}` : ''
        return `<div class="pe card ask" data-code="${code}">${head}<div class="na"><span class="oc ${done[0]}">${esc(done[1])}</span><span class="w">${why}</span></div></div>`
    }
    return `<div class="pe card ask waiting" data-code="${code}" role="group" aria-label="${esc(tt(`批准请求 ${a.code}`, `Approval request ${a.code}`))}">${head}`
        + `<p class="aq">${tt('要继续吗？', 'Do you want to proceed?')}</p>`
        + `<div class="opts"><button type="button" class="ao" data-act="approve" data-arg="${code}"><kbd>1</kbd><span>${tt('是', 'Yes')}</span></button>`
        + `<button type="button" class="ao" data-act="decline-why" data-arg="${code}"><kbd>2</kbd><span>${tt(`否，并告诉${esc(ctx.name)}换个做法`, `No, and tell ${esc(ctx.name)} what to do differently`)}</span><kbd>Esc</kbd></button></div>`
        + `<div class="why" hidden><input type="text" aria-label="${tt('换个什么做法', 'What to do differently')}" placeholder="${tt('告诉它换个什么做法（可以不填）', 'What should it do instead? (optional)')}"><button type="button" class="b" data-act="decline" data-arg="${code}">${tt('拒绝', 'Decline')}</button></div>`
        + (a.expires ? `<small class="exp">${tt(`到 ${clock(a.expires)} 没人回答就算取消，不会当成完成。`, `Unanswered by ${clock(a.expires)} it is cancelled, never taken as done.`)}</small>` : '')
        + `</div>`
}

// A turn that failed: what went wrong, what to do, and the ways on from here.
function failedCard(r) {
    const act = (name, glyph, zh, en) => `<button type="button" data-act="${name}" data-arg="${r.seq}">${icon(glyph, 14)}${tt(zh, en)}</button>`
    return `<div class="pe card fail" role="group" aria-label="${tt('这一回合失败了', 'This turn failed')}"><div class="ah"><b>${icon('alert')}<span>${tt('这一回合失败了', 'This turn failed')}</span></b>${r.code ? `<span class="code">${esc(r.code)}</span>` : ''}</div>`
        + `<p class="why">${esc(plainError(r.error) || tt('后台没有说明原因。', 'The host gave no reason.'))}</p>`
        + (r.fix ? `<p class="fix">${esc(r.fix)}</p>` : '')
        + `<div class="na">${act('turn-retry', 'retry', '重试', 'Retry')}${act('turn-model', 'model', '换模型', 'Switch model')}${act('turn-logs', 'log', '打开日志', 'Open logs')}${act('turn-copy', 'copy', '复制错误', 'Copy error')}</div></div>`
}

function limitCard(fix) {
    return `<div class="pe card"><div class="ah"><b>${tt('今天的额度用完了', "Today's limit is reached")}</b></div><p>${tt('正在进行的调用已做完。你的消息我照样回；别的事等 0:00 额度重置，反应照常运行，事件都记下来。',
        'The call in progress finished. I still answer you; everything else waits for the 0:00 reset, reactions keep running and events are recorded.')}</p>${fix ? `<p>${esc(fix)}</p>` : ''}`
        + `<div class="na"><button type="button" class="pri" data-act="settings" data-arg="usage">${tt('提高今天的额度', "Raise today's limit")}</button><button type="button" data-act="card-dismiss">${tt('知道了', 'OK')}</button></div></div>`
}

// The summary on return: what it did, learned and spent, and what waits for approval.
export function summaryCard(s) {
    const lines = String(s.text || '').split(/\r?\n/).filter((x) => x.trim())
    const items = lines.filter((x) => x.startsWith('- ')).map((x) => x.slice(2))
    const head = lines.find((x) => !x.startsWith('- '))
    return `<div class="pe card"><div class="ah"><b>${s.since ? tt('自从 ', 'Since ') + esc(when(s.since)) : esc(head || tt('摘要', 'Summary'))}</b></div>`
        + (items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '')
        + `<button type="button" class="lnk" data-act="settings" data-arg="learned">${tt('打开学到的东西 →', 'Open What it learned →')}</button></div>`
}

// The reply being written (the contract's `live`): its text so far as Markdown, its thinking
// above it while thinking is shown, or only that it is thinking.
export function liveRow(live, ctx, now = Date.now() / 1000) {
    const waited = live.since ? Math.max(0, now - live.since) : 0
    const dots = `<span class="dots"><b></b><b></b><b></b></span>`
    const thinking = live.reasoning && ctx.thinking
        ? `<details class="thinking" open><summary>${icon('right', 12)}${esc(tt('正在想', 'Thinking'))}${live.text ? '' : dots}</summary><div class="tx">${esc(live.reasoning)}</div></details>` : ''
    if (!live.text) {
        return thinking ? `<div class="pe say live"><small>${esc(ctx.name)}</small>${thinking}</div>`
            : `<div class="pe think" role="status">${tt('思考中', 'Thinking')}${dots}${waited >= 3 ? `<span class="tk">${seconds(waited)}</span>` : ''}</div>`
    }
    return `<div class="pe say live"><small>${esc(ctx.name)}</small>${thinking}<div class="md">${markdown(live.text)}</div></div>`
}
export const working = () => `<div class="pe think" role="status">${tt('工作中', 'Working')}<span class="dots"><b></b><b></b><b></b></span></div>`
