// A chat's record as the chat shows it: what was said, events of its place, the tree's
// reactions, actions with one of the five outcomes, what it learned, approval cards. The same
// names and symbols as the terminal (tokens.css). Model calls and queue bookkeeping are quiet.
import { esc, tt, outcome, when } from './i18n.js'

const HIDDEN = new Set(['model_request', 'model_reply', 'queued', 'wake_queued', 'turn_started', 'compacted', 'opened',
    'intention', 'action_result', 'span_start', 'span_end'])
const label = { event: ['事件', 'event'], reaction: ['反应', 'reaction'], action: ['动作', 'action'], learned: ['学会', 'learned'],
    review: ['回看', 'review'], calendar: ['日历', 'calendar'], noted: ['记住', 'noted'] }
const L = (k) => tt(label[k][0], label[k][1])

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

function eventText(r) {
    const d = r.data || {}
    if (typeof d === 'string') return d
    return d.text || d.title || d.summary || d.message_text || [r.kind, ...Object.entries(d).filter(([, v]) => typeof v !== 'object').slice(0, 3).map(([k, v]) => `${k}=${v}`)].filter(Boolean).join(' · ')
}

// The rows of a chat: [{type, html, ...}] from its records in order.
export function rows(records, ctx) {
    const out = [], open = [], approvals = new Map()
    let lastLimit = -1
    for (const r of records) {
        const ev = r.event
        if (HIDDEN.has(ev)) continue
        if (ev === 'user') {
            const via = r.channel ? ` · ${esc(r.channel)}` : ''
            out.push({ html: `<div class="pe say me"><small>${tt('你', 'you')}${via}</small>${esc(r.text)}</div>` })
        } else if (ev === 'reply') {
            out.push({ html: `<div class="pe say"><small>${esc(ctx.name)}</small>${esc(r.text)}</div>` })
        } else if (ev === 'event') {
            const d = r.data || {}
            if (d.text && (d.name || d.from)) {
                out.push({ html: `<div class="pe say"><small><span class="k event">${L('event')}</span> · ${esc(d.name || d.from)}</small>${esc(d.text)}</div>` })
            } else {
                const kind = r.kind === 'calendar' ? L('calendar') : L('event')
                out.push({ html: line('event', kind, esc(eventText(r))) })
            }
        } else if (ev === 'reaction') {
            const t = r.about || [r.node, typeof r.answer === 'string' ? r.answer : ''].filter(Boolean).join(' → ')
            out.push({ html: line('reaction', L('reaction'), esc(t)) })
        } else if (ev === 'woken') {
            const why = (r.why || []).map((w) => (typeof w === 'string' ? w : w.why || w.kind || JSON.stringify(w))).join(', ')
            out.push({ html: line('quiet', tt('叫醒', 'woken'), esc(why) + (r.summarized ? ` <span class="w">— ${tt('旧事件合成摘要', 'older events as one summary')}</span>` : ''), false, 'quiet') })
        } else if (ev === 'action') {
            const row = { verb: r.verb, html: null, call: call(r), seq: r.seq }
            open.push(row); out.push(row)
        } else if (ev === 'outcome') {
            let at = -1
            for (let i = open.length - 1; i >= 0; i--) if (open[i].verb === r.verb && !open[i].end) { at = i; break }
            if (at >= 0) { open[at].end = r.end; open[at].reason = r.reason || r.summary || ''; open[at].run = r.run; open.splice(at, 1) }
            else out.push({ verb: r.verb, call: `${r.verb || 'action'}()`, end: r.end, reason: r.reason || r.summary || '', run: r.run })
        } else if (ev === 'learned') {
            const t = [r.kind, r.name, r.evidence].filter(Boolean).join(' · ')
            out.push({ html: line('learned', r.kind === 'memory' ? L('noted') : L('learned'), esc(t)) })
        } else if (ev === 'summary') {
            out.push({ html: summaryCard(r) })
        } else if (ev === 'channel' && r.owner_code) {
            out.push({ html: `<div class="pe card"><b>${tt('绑定你自己的 QQ 号', 'Bind your own QQ account')}</b><p>${tt(`用你自己的 QQ 私聊${esc(ctx.name)}的号，发送 ${esc(r.owner_code)}。绑定后，你在 QQ 上和它的私聊就是这个主对话。`, `From your own QQ account, send ${esc(r.owner_code)} to ${esc(ctx.name)}'s account in a private chat. After that, your QQ private chat with it is this main conversation.`)}</p></div>` })
        } else if (ev === 'review') {
            out.push({ html: line('review', L('review'), esc(r.text || r.note || '')) })
        } else if (ev === 'approval') {
            const known = approvals.get(r.code)
            if (known) { Object.assign(known.data, r); continue }
            const row = { approval: true, data: { ...r } }
            approvals.set(r.code, row); out.push(row)
        } else if (ev === 'asleep' || ev === 'spending_limit') {
            if (lastLimit === out.length - 1 && lastLimit >= 0) continue
            lastLimit = out.length
            out.push({ html: limitCard(ctx) })
        } else if (ev === 'done') {
            if (r.note) out.push({ html: line('quiet', tt('完成', 'done'), esc(r.note), false, 'quiet') })
        } else if (ev === 'error') {
            out.push({ html: line('failed', tt('出错', 'error'), esc(r.error)) })
        } else if (ev === 'life') {
            if (r.state === 'started' || r.state === 'stopped') continue // the host starting and quitting: bookkeeping
            const s = { started: tt('开始运行', 'started'), stopped: tt('已停止', 'stopped'), paused: tt('已暂停', 'paused'), resumed: tt('已继续', 'resumed') }[r.state] || r.state
            out.push({ html: line('quiet', tt('生活', 'life'), esc(s), false, 'quiet') })
        } else if (ev === 'interrupted') {
            out.push({ html: line('quiet', tt('中断', 'stopped'), esc(r.reason || ''), false, 'quiet') })
        }
    }
    return out.map((row) => {
        if (row.html) return row.html
        if (row.approval) return approvalCard(row.data, ctx)
        const pending = !row.end
        const oc = pending ? `<span class="oc pending"><span class="spin"></span>${outcome('pending')}</span>` : `<span class="oc ${esc(row.end)}">${outcome(row.end)}</span>`
        const extra = row.reason ? `<span class="w"> — ${esc(row.reason)}</span>` : ''
        return `<div class="pe line"><span class="k action">${L('action')}</span><span class="t">${esc(row.call)}${extra}</span>${oc}</div>`
    })
}

function line(kind, labelText, html, pending, cls = '') {
    return `<div class="pe line ${cls}"><span class="k ${kind}">${esc(labelText)}</span><span class="t">${html}</span>${pending ? `<span class="oc pending"><span class="spin"></span>${outcome('pending')}</span>` : ''}</div>`
}

export function approvalCard(a, ctx) {
    const pending = !a.state || a.state === 'waiting'
    const done = { approved: tt('已同意', 'Allowed'), rejected: tt('已拒绝', 'Declined'), cancelled: tt('30 分钟没人批准：已取消', 'No answer in 30 minutes: cancelled'),
        elsewhere: tt('已在别处处理', 'Handled elsewhere') }[a.state] || ''
    const what = esc(a.what || a.verb || '')
    const where = [a.verb, ctx.titles && a.in_chat ? ctx.titles[a.in_chat] || a.in_chat : a.place, a.why, a.reason && a.state !== 'waiting' ? a.reason : ''].filter(Boolean).map(esc).join(' · ')
    return `<div class="pe card" data-code="${esc(a.code)}"><b>${what} <span class="code">${esc(a.code || '')}</span></b>`
        + (where ? `<p>${where}</p>` : '')
        + `<div class="na">${pending ? `<button class="pri" data-approve="${esc(a.code)}">${tt('同意', 'Allow')}</button><button data-reject="${esc(a.code)}">${tt('拒绝', 'Decline')}</button>` : `<span>${done}</span>`}</div></div>`
}

function limitCard(ctx) {
    return `<div class="pe card"><b>${tt('今天的额度用完了', "Today's limit is reached")}</b><p>${tt('正在进行的调用已做完。你的消息我照样回；别的事等 0:00 额度重置，反应照常运行，事件都记下来。',
        'The call in progress finished. I still answer you; everything else waits for the 0:00 reset, reactions keep running and events are recorded.')}</p>`
        + `<div class="na"><button class="pri" data-open-settings="usage">${tt('提高今天的额度', "Raise today's limit")}</button><button data-dismiss>${tt('知道了', 'OK')}</button></div></div>`
}

// The summary on return: what it did, learned and spent, and what waits for approval.
export function summaryCard(s) {
    const lines = String(s.text || '').split(/\r?\n/).filter((x) => x.trim())
    const items = lines.filter((x) => x.startsWith('- ')).map((x) => x.slice(2))
    const head = lines.find((x) => !x.startsWith('- '))
    return `<div class="pe card"><b>${s.since ? tt('自从 ', 'Since ') + esc(when(s.since)) : esc(head || tt('摘要', 'Summary'))}</b>`
        + (items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '')
        + `<button class="lnk" data-open-settings="learned">${tt('打开学到的东西 →', 'Open What it learned →')}</button></div>`
}
