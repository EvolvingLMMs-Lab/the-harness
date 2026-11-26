// Settings › Connectors. The list is the connectors page of Claude and ChatGPT: what is
// connected, each with its state and what can be done with it, and a way to add one. Four
// kinds are listed the same way, each with add, remove and test: chat channels, MCP servers,
// external agents (ACP) and sources of skills.
//
// Channels are Hermes Desktop's Messaging set-up, with one difference that is the plan's: the
// page knows no chat service. The kinds are whatever the installed channel packages declare
// (GET /api/agent/channels → kinds), and every step of connecting an account (its fields,
// its login, its groups, binding the owner) is drawn from that declaration in the order it
// gives. With no channel package installed, the page says where channels come from.
import { esc, tt, when } from '../i18n.js'
import { get, post, failed } from '../api.js'
import { $, $$, on, dialog, closeDialog, refocus, press, confirm, said, toast, steps, row, mark, act, empty, problem } from '../ui.js'
import { icon } from '../icons.js'
import { said as words } from '../names.js'

export const identity = true
let c = null
let kinds = [] // the channel kinds the installed packages declare
const tools = new Map() // MCP server → the tools its last test listed
const looked = new Map() // skill source → what its last look found

const fail = (d, r) => { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('没有成功', 'That did not work'))}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}` }
const busy = (d, text) => { d.querySelector('.res').innerHTML = `<span class="spin"></span>${esc(text)}` }
const foot = (yes, { back = '' } = {}) => `<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${back || tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${esc(yes)}</button></div>`
// a command line as its words: quotes keep spaces together
const argv = (text) => (String(text).match(/"[^"]*"|'[^']*'|\S+/g) || []).map((w) => w.replace(/^(["'])(.*)\1$/, '$2'))
const pairs = (text, cut) => Object.fromEntries(String(text).split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => { const at = l.indexOf(cut); return at < 0 ? [l, ''] : [l.slice(0, at).trim(), l.slice(at + 1).trim()] }))

const STATE = { logged_in: ['已连接', 'connected', 'eff'], waiting_login: ['等登录', 'waiting for login', 'prop'], starting: ['正在启动', 'starting', 'prop'], unavailable: ['用不了', 'unavailable', 'failed'] }
const kindOf = (name) => kinds.find((k) => k.kind === name)

export async function draw(ctx) {
    c = ctx
    const [ch, mcp, acp, sources] = await Promise.all([ctx.get('/api/agent/channels', { identity: ctx.id }), ctx.get('/api/app/mcp'), ctx.get('/api/app/acp'), ctx.get('/api/agent/skill_sources', { identity: ctx.id })])
    kinds = (ch && ch.kinds) || []
    // ── channels ──
    let channels
    if (!ch) channels = problem(failed.get('/api/agent/channels'), { title: tt('渠道没有读出来', 'The channels could not be read'), retry: 'settings' })
    else {
        const accounts = ch.channels || []
        const pending = accounts.flatMap((a) => (a.pending || []).map((p) => ({ ...p, account: a.account, title: a.title || a.account })))
        const broken = Object.entries(ch.problems || {})
        channels = broken.map(([kind, why]) => row({ title: esc(kind), sub: esc(why), marks: mark(tt('声明读不出来', 'declaration unreadable'), 'failed') })).join('')
            + accounts.map((a) => {
                const k = kindOf(a.kind) || {}, st = STATE[a.state] || [a.state, a.state, 'prop']
                const entered = Object.keys(a.entered || {}).length
                return row({ title: esc(a.title || a.account), sub: esc([(words(a.name || k.name) || a.kind) === (a.title || a.account) ? a.account : words(a.name || k.name) || a.kind, a.identity, entered ? tt(`进了 ${entered} 个群`, `in ${entered} group${entered === 1 ? '' : 's'}`) : '',
                    k.owner ? (a.owner ? tt(`主人：${a.owner}`, `owner: ${a.owner}`) : tt('还没绑定主人', 'owner not bound yet')) : '', a.problem].filter(Boolean).join(' · ')),
                    marks: mark(tt(st[0], st[1]), st[2]),
                    actions: act(tt('测试', 'Test'), 'channel-test', a.account) + (a.state !== 'logged_in' && k.login ? act(tt('登录…', 'Log in…'), 'channel-step', a.account, { more: 'data-step="login"' }) : '')
                        + (k.groups && a.state === 'logged_in' ? act(tt('群…', 'Groups…'), 'channel-step', a.account, { more: 'data-step="groups"' }) : '')
                        + (k.owner && !a.owner && a.state === 'logged_in' ? act(tt('绑定主人…', 'Bind the owner…'), 'channel-step', a.account, { more: 'data-step="owner"' }) : '')
                        + ((k.fields || []).length ? act(tt('设置…', 'Settings…'), 'channel-settings', a.account) : '') + act(tt('移除', 'Remove'), 'channel-remove', a.account, { danger: true }) })
            }).join('')
            + pending.map((p) => row({ title: `${esc(p.name || p.user || tt('有人', 'Someone'))} <span class="code">${esc(p.code)}</span>`, sub: esc(tt(`想在“${p.title}”里和它私聊`, `wants to message it in "${p.title}"`) + (p.expires ? ` · ${tt('到', 'until')} ${when(p.expires, { day: false })}` : '')),
                marks: mark(tt('等你批准', 'waits for you'), 'prop'), actions: act(tt('批准', 'Approve'), 'channel-pair', p.account, { more: `data-code="${esc(p.code)}"` }) })).join('')
        if (!accounts.length && !broken.length) {
            channels = kinds.length ? empty(tt('还没有接上渠道', 'No channel is connected yet'), tt('接上一个聊天账号，它在那里的私聊并进主对话，放它进去的每个群是一个对话。', 'Connect a chat account: your private chat with it there joins the main conversation, and each group it is let into is a chat.'))
                : empty(tt('还没有装提供渠道的扩展包', 'No package that provides a channel is installed'), words(ch.from), `<div class="st-acts"><button type="button" class="b" data-act="settings" data-arg="packages">${tt('去扩展包…', 'Go to Packages…')}</button></div>`)
        }
        if (kinds.length) channels += `<div class="btns"><button type="button" class="b" data-act="channel-add">${icon('plus', 14)}${tt('添加渠道…', 'Add a channel…')}</button></div>`
    }
    // ── MCP servers ──
    const servers = (mcp && mcp.servers) || []
    const mcpHtml = !mcp ? problem(failed.get('/api/app/mcp'), { title: tt('MCP 服务没有读出来', 'The MCP servers could not be read'), retry: 'settings' })
        : (servers.length ? servers.map((s) => {
            const listed = tools.get(s.name)
            return row({ title: esc(s.title || s.name), sub: esc([s.title && s.title !== s.name ? s.name : '', s.target, (s.env || []).length ? tt(`环境变量 ${s.env.join('、')}`, `env ${s.env.join(', ')}`) : ''].filter(Boolean).join(' · ')),
                marks: mark(s.transport === 'http' ? tt('远程地址', 'remote') : tt('本机命令', 'local command'), 'none') + mark(s.enabled === false ? tt('关', 'off') : tt('开', 'on'), s.enabled === false ? 'off' : 'eff'),
                actions: act(tt('测试', 'Test'), 'mcp-test', s.name) + act(s.enabled === false ? tt('打开', 'Enable') : tt('关掉', 'Disable'), 'mcp-enable', s.name, { more: `data-on="${s.enabled === false ? 1 : 0}"` }) + act(tt('移除', 'Remove'), 'mcp-remove', s.name, { danger: true }),
                more: listed ? `<div class="ld"><p>${tt(`上次测试列出 ${listed.tools.length} 个工具，用了 ${listed.seconds} 秒：`, `The last test listed ${listed.tools.length} tool${listed.tools.length === 1 ? '' : 's'} in ${listed.seconds} s:`)}</p><ul class="tools">${listed.tools.map((t) => `<li><code>${esc(t.name)}</code> ${esc(t.description || '')}</li>`).join('')}</ul></div>` : '' })
        }).join('') : empty(tt('还没有接上 MCP 服务', 'No MCP server is connected yet'), tt('MCP 服务给它更多工具：一条在这台电脑上启动的命令，或者一个地址。', 'An MCP server gives it more tools: a command started on this computer, or an address.')))
        + `<div class="btns"><button type="button" class="b" data-act="mcp-add">${icon('plus', 14)}${tt('添加 MCP 服务…', 'Add an MCP server…')}</button></div>`
    // ── external agents ──
    const agents = (acp && acp.agents) || []
    const acpHtml = !acp ? problem(failed.get('/api/app/acp'), { title: tt('外部 agent 没有读出来', 'The external agents could not be read'), retry: 'settings' })
        : (agents.length ? agents.map((a) => row({ title: esc(a.name || a.id), sub: esc([a.id, a.version, a.signed_in === false ? tt(`还没登录：${a.sign_in}`, `not signed in: ${a.sign_in}`) : a.plan ? tt(`用${a.plan === 'your Claude plan' ? '你的 Claude 订阅' : a.plan === 'your ChatGPT plan' ? '你的 ChatGPT 订阅' : a.plan}`, `uses ${a.plan}`) : ''].filter(Boolean).join(' · ')),
            marks: mark({ connected: tt('已接上', 'connected'), found: tt('这台电脑上有', 'found here'), available: tt('目录里有', 'in the directory') }[a.state] || a.state, a.state === 'connected' ? 'eff' : 'prop')
                + (a.signed_in === true ? mark(tt('已登录', 'signed in'), 'eff') : a.signed_in === false ? mark(tt('没登录', 'not signed in'), 'prop') : ''),
            actions: `<button type="button" class="lb" data-act="acp-test" data-arg="${esc(a.id)}" data-tip="${tt('让它答一个词；会用到你在这个工具里的订阅额度', 'Asks it for one word; this uses your plan in that tool')}">${tt('测试', 'Test')}</button>`
                + (a.source === 'found' ? '' : act(tt('移除', 'Remove'), 'acp-remove', a.id, { danger: true })) })).join('')
            : empty(tt('还没有外部 agent', 'No external agent yet'), tt('已经登录的 agent 命令行工具（说 ACP 的）可以直接当模型用，用的是你自己的订阅。', 'An agent command-line tool signed in here (one that speaks ACP) can be the model, under your own plan.')))
        + `<div class="btns"><button type="button" class="b" data-act="acp-add">${icon('plus', 14)}${tt('添加外部 agent…', 'Add an external agent…')}</button></div>`
    // ── skill sources ──
    const list = (sources && sources.sources) || []
    const srcHtml = !sources ? problem(failed.get('/api/agent/skill_sources'), { title: tt('技能来源没有读出来', 'The skill sources could not be read'), retry: 'settings' })
        : (list.length ? list.map((s) => row({ title: esc(s.from), sub: esc([{ path: tt('这台电脑上的文件夹', 'a folder on this computer'), git: tt('一个仓库', 'a repository'), url: tt('一个地址', 'an address') }[s.kind] || s.kind,
            tt(`${(s.skills || []).length} 个技能：`, `${(s.skills || []).length} skill${(s.skills || []).length === 1 ? '' : 's'}: `) + (s.skills || []).map((k) => k.name + (k.there === false ? tt('（已删）', ' (removed)') : '')).join(tt('、', ', ')),
            s.checked ? tt(`上次读 ${when(s.checked)}`, `last read ${when(s.checked)}`) : ''].filter(Boolean).join(' · ')),
            actions: act(tt('测试', 'Test'), 'source-test', s.id) + act(tt('更新', 'Update'), 'source-update', s.id) + act(tt('移除…', 'Remove…'), 'source-remove', s.id, { danger: true }),
            more: looked.get(s.id) ? `<div class="ld"><p>${tt('现在那里有：', 'It holds now:')}</p><ul class="tools">${looked.get(s.id).map((k) => `<li><code>${esc(k.name)}</code> ${esc(k.description || '')}</li>`).join('')}</ul></div>` : '' })).join('')
            : empty(tt('还没有技能来源', 'No skill source yet'), tt('别人写的技能（带 SKILL.md 的文件夹）可以从一个文件夹、一个仓库或一个地址拿进来；拿进来的先是"提议"。', 'Skills others wrote (folders with a SKILL.md) can be taken from a folder, a repository or an address; they come in as "proposed".')))
        + `<div class="btns"><button type="button" class="b" data-act="source-add">${icon('plus', 14)}${tt('添加技能来源…', 'Add a skill source…')}</button></div>`
    return `<p>${tt('它和外面接在一起的地方：聊天渠道、给它更多工具的 MCP 服务、能当模型用的外部 agent，以及技能的来源。', 'Where it is joined to the outside: chat channels, MCP servers that give it more tools, external agents that can be its model, and sources of skills.')}</p>`
        + `<div class="lg">${tt('渠道', 'Channels')}</div>${channels}`
        + `<div class="lg">${tt('MCP 服务', 'MCP servers')}${c.many ? `<span class="tag">${tt('所有身份', 'every identity')}</span>` : ''}</div>${mcpHtml}`
        + `<div class="lg">${tt('外部 agent（ACP）', 'External agents (ACP)')}${c.many ? `<span class="tag">${tt('所有身份', 'every identity')}</span>` : ''}</div>${acpHtml}`
        + `<div class="lg">${tt('技能来源', 'Skill sources')}</div>${srcHtml}`
}

// ── channels: every step drawn from the kind's declaration ──
const STEP = { kind: ['渠道', 'Channel'], policies: ['身份和设置', 'Identity and settings'], login: ['登录', 'Log in'], groups: ['群', 'Groups'], owner: ['主人', 'Owner'] }
const channel = (body) => post('/api/agent/channels', body)
// one declared field as a control
function field(f, value) {
    const v = value !== undefined ? value : f.default
    const label = esc(words(f.label) || f.id), help = words(f.help)
    let control
    if (f.kind === 'choice') control = `<select class="field" data-f="${esc(f.id)}">${(f.choices || []).map((o) => `<option value="${esc(o.value)}"${String(o.value) === String(v) ? ' selected' : ''}>${esc(words(o) || o.value)}</option>`).join('')}</select>`
    else if (f.kind === 'bool') return `<label class="check"><input type="checkbox" data-f="${esc(f.id)}"${v ? ' checked' : ''}><span>${label}${help ? `<small>${esc(help)}</small>` : ''}</span></label>`
    else control = `<input class="field" data-f="${esc(f.id)}" ${f.kind === 'secret' ? 'type="password" autocomplete="off"' : 'type="text" spellcheck="false"'} value="${f.kind === 'secret' ? '' : esc(v ?? '')}"${f.required ? ' required' : ''}>`
    return `<label><span>${label}${f.required ? ' *' : ''}</span>${control}</label>${help ? `<p class="note fh">${esc(help)}</p>` : ''}`
}
function values(d, fields) {
    const out = {}
    for (const f of fields) {
        const node = d.querySelector(`[data-f="${f.id}"]`)
        if (!node) continue
        const v = f.kind === 'bool' ? node.checked : node.value
        if (f.kind === 'secret' && !v) continue // nothing typed: the one that is kept stays
        out[f.id] = v
    }
    return out
}

// The flow of connecting an account: the kind's own steps, in its order. `from`: the step to
// start at for an account that exists already.
async function connect({ kind = null, account = null, from = null, who = c.id } = {}) {
    const k = kind && kindOf(kind)
    const order = k ? k.steps : []
    const names = (at) => steps([...(account || kinds.length === 1 ? [] : ['kind']), ...order].map((s) => tt(STEP[s][0], STEP[s][1])), at + (account || kinds.length === 1 ? 0 : 1))
    const next = (step) => { const at = order.indexOf(step); return at >= 0 && at + 1 < order.length ? order[at + 1] : null }
    const done = () => { closeDialog(); c.app.refresh(); c.reload() }
    const go = (step) => (step ? connect({ kind, account, from: step, who }) : done())
    // 0. which channel, of those the installed packages declare
    if (!k) {
        const d = dialog(`${steps(['kind', 'policies'].map((s) => tt(STEP[s][0], STEP[s][1])).concat('…'), 0)}<h5>${tt('接上哪个渠道？', 'Which channel?')}</h5>
<div role="radiogroup" aria-label="${tt('渠道', 'Channel')}">${kinds.map((x, i) => `<button type="button" class="opt${i === 0 ? ' on' : ''}" role="radio" aria-checked="${i === 0}" data-kind="${esc(x.kind)}"><b>${esc(words(x.name) || x.kind)}</b><small>${esc(words(x.about))} · ${tt('来自扩展包', 'from the package')} ${esc(x.package)}</small></button>`).join('')}</div>` + foot(tt('下一步', 'Next')))
        let chosen = kinds[0].kind
        $$('[data-kind]', d).forEach((b) => { b.onclick = () => { chosen = b.dataset.kind; $$('[data-kind]', d).forEach((x) => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b) }) }; b.ondblclick = () => connect({ kind: chosen }) })
        d.querySelector('[data-no]').onclick = closeDialog
        d.querySelector('[data-default]').onclick = () => connect({ kind: chosen })
        return
    }
    const step = from || order[0]
    const at = order.indexOf(step)
    const title = esc(words(k.name) || k.kind)
    if (step === 'policies') {
        // 1. whose it is, and what the kind asks for
        const d = dialog(`${names(at)}<h5>${tt('添加渠道', 'Add a channel')} · ${title}</h5>
<label><span>${tt('归属身份', 'Identity')}</span><select class="field" data-who>${c.app.identities.map((i) => `<option value="${esc(i.id)}"${i.id === who ? ' selected' : ''}>${esc(i.name || i.id)} (${esc(i.id)})</option>`).join('')}</select></label>
${(k.fields || []).map((f) => field(f)).join('')}` + foot(tt('添加', 'Add')))
        d.querySelector('[data-no]').onclick = closeDialog
        press(d.querySelector('[data-default]'), async () => {
            const owner = d.querySelector('[data-who]').value
            busy(d, tt('正在添加，并启动它…', 'adding it and starting it…'))
            const r = await channel({ identity: owner, action: 'add', kind: k.kind, values: values(d, k.fields || []) })
            if (!r.ok) return fail(d, r)
            return connect({ kind, account: r.data.account, from: next('policies'), who: owner })
        })
        return
    }
    if (!step) return done()
    if (step === 'login') {
        // 2. the account logs in, in whatever way its kind says; the page watches until it has
        const d = dialog(`${names(at)}<h5>${tt('登录', 'Log in')} · ${title}</h5><div data-login><span class="spin"></span>${tt('正在等它启动…', 'waiting for it to start…')}</div>` + foot(tt('下一步', 'Next'), { back: tt('以后再登录', 'Log in later') }))
        const nextButton = d.querySelector('[data-default]')
        nextButton.disabled = true
        d.querySelector('[data-no]').onclick = done
        nextButton.onclick = () => go(next('login'))
        const box = d.querySelector('[data-login]')
        while (d.isConnected) {
            const got = await get('/api/agent/channels', { identity: who, account })
            if (!d.isConnected) return
            const row = got && (got.channels || []).find((x) => x.account === account)
            if (!got) box.innerHTML = problem(failed.get('/api/agent/channels'))
            else if (!row) { box.innerHTML = problem({ error: tt('这个账号不在了。', 'This account is gone.') }); return }
            else if (row.state === 'logged_in') {
                box.innerHTML = `<p class="c-done">✓ ${tt('已登录', 'It is logged in')}</p>`
                nextButton.disabled = false
                if (!next('login')) nextButton.textContent = tt('完成', 'Done')
                nextButton.focus()
                return
            } else if (row.state === 'unavailable') { box.innerHTML = problem({ error: row.problem || tt('提供它的扩展包不在了。', 'The package that provides it is gone.') }); return }
            else {
                const login = row.login || {}
                const html = `<p>${esc(words(login.text) || words((k.login || {}).text) || tt('等它登录…', 'Waiting for it to log in…'))}</p>`
                    + (login.qr ? `<img class="qr" alt="${tt('登录用的二维码', 'The code to scan to log in')}" src="${esc(login.qr)}">` : '')
                    + (login.url ? `<p><a href="${esc(login.url)}" target="_blank" rel="noopener noreferrer">${esc(login.url)}</a></p>` : '')
                    + (login.now ? `<p class="note">${esc(login.now)}</p>` : '')
                    + `<p class="note"><span class="spin"></span>${row.state === 'starting' ? tt('正在启动…', 'starting…') : tt('等登录…', 'waiting for the login…')}</p>`
                if (box._html !== html) { box._html = html; box.innerHTML = html }
            }
            await new Promise((ok) => setTimeout(ok, 1500))
        }
        return
    }
    if (step === 'groups') {
        // 3. which groups it may enter (none by default), and when it is woken in them
        const d = dialog(`${names(at)}<h5>${tt('放它进哪些群？', 'Which groups may it enter?')} · ${title}</h5><div data-groups><span class="spin"></span>${tt('正在读群的列表…', 'reading the groups…')}</div>` + foot(next('groups') ? tt('下一步', 'Next') : tt('完成', 'Done'), { back: tt('跳过', 'Skip') }))
        d.querySelector('[data-no]').onclick = () => go(next('groups'))
        const got = await get('/api/agent/channels', { identity: who, account })
        if (!d.isConnected) return
        const row = got && (got.channels || []).find((x) => x.account === account)
        const box = d.querySelector('[data-groups]')
        const groups = row && row.groups
        if (!got) box.innerHTML = problem(failed.get('/api/agent/channels'))
        else if (!groups) box.innerHTML = empty(tt('它还没登录，读不到群', 'It is not logged in yet, so its groups cannot be read'))
        else if (!groups.length) box.innerHTML = empty(tt('这个账号不在任何群里', 'This account is in no group'))
        else {
            const modes = (k.groups || {}).modes || []
            box.innerHTML = `<p class="note">${tt(`这个账号在 ${groups.length} 个群里，默认一个都不进。勾上的每个群是列表里的一个对话。`, `This account is in ${groups.length} group${groups.length === 1 ? '' : 's'} and enters none by default. Each ticked group becomes a chat in the list.`)}</p>`
                + `<div class="checks col">${groups.map((g) => `<label class="check"><input type="checkbox" data-g="${esc(g.id)}"${g.entered ? ' checked' : ''}><span>${esc(g.name || g.id)}</span></label>`).join('')}</div>`
                + (modes.length ? `<label><span>${tt('什么时候叫醒它', 'When it is woken')}</span><select class="field" data-mode>${modes.map((m) => `<option value="${esc(m.value)}">${esc(words(m) || m.value)}</option>`).join('')}</select></label>` : '')
            refocus(d)
        }
        press(d.querySelector('[data-default]'), async () => {
            if (!groups || !groups.length) return go(next('groups'))
            const mode = d.querySelector('[data-mode]')
            const r = await channel({ identity: who, action: 'groups', account, groups: $$('[data-g]', d).filter((x) => x.checked).map((x) => x.dataset.g), ...(mode ? { mode: mode.value } : {}) })
            if (!r.ok) return fail(d, r)
            return go(next('groups'))
        })
        return
    }
    if (step === 'owner') {
        // 4. binding the owner's own account there with a one-time code
        const d = dialog(`${names(at)}<h5>${tt('绑定你自己', 'Bind yourself as the owner')} · ${title}</h5><div data-owner><span class="spin"></span>${tt('正在要一个一次性的码…', 'asking for a one-time code…')}</div>` + foot(tt('完成', 'Done'), { back: tt('以后再绑定', 'Bind later') }))
        d.querySelector('[data-no]').onclick = done
        d.querySelector('[data-default]').onclick = done
        const r = await channel({ identity: who, action: 'owner_code', account })
        if (!d.isConnected) return
        const box = d.querySelector('[data-owner]')
        if (!r.ok) { box.innerHTML = problem(r, { title: tt('没要到码', 'No code was given') }); return }
        const result = r.data.result || {}
        box.innerHTML = `<p>${esc(words(result.text) || words((k.owner || {}).text))}</p><p class="bigcode">${esc(result.code || '')}</p>`
            + (result.expires ? `<p class="note">${tt(`到 ${when(result.expires, { day: false })} 有效。`, `Good until ${when(result.expires, { day: false })}.`)}</p>` : '')
            + `<p class="note" data-bound><span class="spin"></span>${tt('等这个码到…', 'waiting for the code to arrive…')}</p>`
        while (d.isConnected) {
            await new Promise((ok) => setTimeout(ok, 1500))
            const got = await get('/api/agent/channels', { identity: who, account })
            const row = got && (got.channels || []).find((x) => x.account === account)
            if (d.isConnected && row && row.owner) { d.querySelector('[data-bound]').innerHTML = `<span class="c-done">✓ ${tt(`已绑定：${row.owner}。你在那里和它的私聊就是主对话。`, `Bound: ${row.owner}. Your private chat with it there is the main conversation.`)}</span>`; return }
        }
    }
}

// An account's own settings: the fields its kind declares, with what it has now.
async function channelSettings(account) {
    const got = await get('/api/agent/channels', { identity: c.id, account })
    const a = got && (got.channels || []).find((x) => x.account === account)
    if (!a) return said(failed.get('/api/agent/channels') || { error: tt('这个账号不在了。', 'This account is gone.') })
    const k = kindOf(a.kind) || { fields: [] }
    const d = dialog(`<h5>${esc([...new Set([a.title || a.account, words(k.name) || a.kind])].join(' · '))}</h5>${(k.fields || []).map((f) => field(f, (a.values || {})[f.id])).join('')}
<p class="note">${tt('保存后这个账号会重新启动。密钥留空就保留现在的。', 'Saving restarts the account. A secret left empty keeps the one it has.')}</p>` + foot(tt('保存', 'Save')))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await channel({ identity: c.id, action: 'set', account, values: values(d, k.fields || []) })
        if (!r.ok) return fail(d, r)
        closeDialog(); toast(tt('已保存', 'Saved')); c.reload()
    })
}

// ── MCP servers ──
function mcpAdd() {
    const d = dialog(`<h5>${tt('添加 MCP 服务', 'Add an MCP server')}</h5>
<label><span>${tt('名字', 'Name')}</span><input class="field" data-name spellcheck="false" placeholder="units" pattern="[a-z0-9-]+"></label>
<div role="radiogroup" aria-label="${tt('怎么连', 'How it is reached')}" class="seg wide"><button type="button" role="radio" aria-checked="true" data-way="command">${tt('这台电脑上的一条命令', 'A command on this computer')}</button><button type="button" role="radio" aria-checked="false" data-way="url">${tt('一个地址', 'An address')}</button></div>
<div data-command><label><span>${tt('命令', 'Command')}</span><input class="field" data-line spellcheck="false" placeholder="npx -y @modelcontextprotocol/server-everything"></label>
<label><span>${tt('环境变量', 'Environment')}</span><textarea class="field" data-env rows="2" spellcheck="false" placeholder="KEY=value"></textarea></label></div>
<div data-url hidden><label><span>${tt('地址', 'Address')}</span><input class="field" data-address spellcheck="false" placeholder="https://example.com/mcp"></label>
<label><span>${tt('请求头', 'Headers')}</span><textarea class="field" data-headers rows="2" spellcheck="false" placeholder="Authorization: Bearer …"></textarea></label></div>
<p class="note">${tt('名字只能用小写字母、数字和连字符。环境变量和请求头的值存进凭据文件，页面不再显示。添加后会连上去列一次工具。', 'The name takes lowercase letters, digits and hyphens. Values of the environment and of headers are kept with the credentials and not shown again. After adding, it is connected once to list its tools.')}</p>` + foot(tt('添加并测试', 'Add and test')))
    let way = 'command'
    $$('[data-way]', d).forEach((b) => { b.onclick = () => { way = b.dataset.way; $$('[data-way]', d).forEach((x) => x.setAttribute('aria-checked', x === b)); d.querySelector('[data-command]').hidden = way !== 'command'; d.querySelector('[data-url]').hidden = way !== 'url' } })
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const name = d.querySelector('[data-name]').value.trim()
        const words_ = argv(d.querySelector('[data-line]').value)
        const body = way === 'command' ? { command: words_[0], args: words_.slice(1), env: pairs(d.querySelector('[data-env]').value, '=') } : { url: d.querySelector('[data-address]').value.trim(), headers: pairs(d.querySelector('[data-headers]').value, ':') }
        busy(d, tt('正在添加…', 'adding…'))
        const r = await post('/api/app/mcp', { action: 'add', name, ...body })
        if (!r.ok) return fail(d, r)
        busy(d, tt('已添加，正在连上去列工具…', 'added; connecting to list its tools…'))
        const t = await post('/api/app/mcp', { action: 'test', name })
        if (!t.ok) { fail(d, { error: tt('已添加，但没连上：', 'It was added, but did not connect: ') + (t.error || ''), fix: t.fix }); d.querySelector('[data-default]').hidden = true; d.querySelector('[data-no]').textContent = tt('关闭', 'Close'); d.querySelector('[data-no]').onclick = () => { closeDialog(); c.reload() }; return }
        tools.set(name, t.data.result)
        closeDialog(); toast(tt(`已接上 ${name}：${t.data.result.tools.length} 个工具`, `${name} is connected: ${t.data.result.tools.length} tool${t.data.result.tools.length === 1 ? '' : 's'}`)); c.reload()
    })
}

// ── external agents ──
async function acpAdd() {
    const d = dialog(`<h5>${tt('添加外部 agent', 'Add an external agent')}</h5>
<div role="radiogroup" aria-label="${tt('从哪里来', 'Where it comes from')}" class="seg wide"><button type="button" role="radio" aria-checked="true" data-way="registry">${tt('从 ACP 公开目录里选', 'From the ACP directory')}</button><button type="button" role="radio" aria-checked="false" data-way="custom">${tt('自己填启动命令', 'A command of my own')}</button></div>
<div data-registry><div data-list><span class="spin"></span>${tt('正在读公开目录…', 'reading the directory…')}</div></div>
<div data-custom hidden><label><span>${tt('名字', 'Name')}</span><input class="field" data-name spellcheck="false"></label>
<label><span>${tt('启动命令', 'Command')}</span><input class="field" data-line spellcheck="false" placeholder="my-agent --acp"></label>
<label><span>${tt('环境变量名', 'Environment names')}</span><input class="field" data-env spellcheck="false" placeholder="MY_AGENT_HOME"></label>
<p class="note fh">${tt('允许传给它的环境变量的名字，用空格隔开；值来自后台自己的环境。', "The names of environment variables it may be given, separated by spaces; their values are the host's own.")}</p></div>
<p class="note">${tt('接上的是已经装在这台电脑上、由你自己登录的工具：这里不读取、不保存它的登录。', 'What is connected is a tool installed on this computer that you signed in to yourself: its sign-in is neither read nor kept here.')}</p>` + foot(tt('添加', 'Add')))
    let way = 'registry', chosen = null
    $$('[data-way]', d).forEach((b) => { b.onclick = () => { way = b.dataset.way; $$('[data-way]', d).forEach((x) => x.setAttribute('aria-checked', x === b)); d.querySelector('[data-registry]').hidden = way !== 'registry'; d.querySelector('[data-custom]').hidden = way !== 'custom' } })
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const body = way === 'registry' ? { name: chosen } : { name: d.querySelector('[data-name]').value.trim(), argv: argv(d.querySelector('[data-line]').value), env: argv(d.querySelector('[data-env]').value) }
        if (!body.name) return fail(d, { error: way === 'registry' ? tt('先从目录里选一个。', 'Choose one from the directory first.') : tt('先给它一个名字。', 'Give it a name first.') })
        busy(d, tt('正在接上（第一次要装它的适配器）…', 'connecting (its adapter installs the first time)…'))
        const r = await post('/api/app/acp', { action: 'add', ...body })
        if (!r.ok) return fail(d, r)
        closeDialog(); toast(tt('已添加', 'Added')); c.reload()
    })
    const got = await get('/api/app/acp', { registry: 1 })
    if (!d.isConnected) return
    const box = d.querySelector('[data-list]')
    const rows = ((got && got.agents) || []).filter((a) => a.state === 'available')
    if (!got) box.innerHTML = problem(failed.get('/api/app/acp'), { title: tt('公开目录没有读出来', 'The directory could not be read') })
    else if (!rows.length) box.innerHTML = empty(tt('目录里没有还没接上的 agent', 'The directory has no agent that is not connected yet'))
    else {
        box.innerHTML = `<input class="field" data-find placeholder="${tt('找一个 agent', 'Find an agent')}" aria-label="${tt('找一个 agent', 'Find an agent')}"><div class="picks" role="radiogroup">${rows.map((a) => `<button type="button" class="opt" role="radio" aria-checked="false" data-id="${esc(a.id)}"><b>${esc(a.name || a.id)}</b><small>${esc([a.id, a.version].filter(Boolean).join(' · '))}</small></button>`).join('')}</div>`
        $$('[data-id]', box).forEach((b) => { b.onclick = () => { chosen = b.dataset.id; $$('[data-id]', box).forEach((x) => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b) }) } })
        box.querySelector('[data-find]').oninput = (e) => { const q = e.target.value.toLowerCase(); $$('[data-id]', box).forEach((b) => { b.hidden = !!q && !b.textContent.toLowerCase().includes(q) }) }
    }
}

// ── skill sources ──
function sourceAdd() {
    const d = dialog(`<h5>${tt('添加技能来源', 'Add a skill source')}</h5>
<label><span>${tt('来源', 'Source')}</span><input class="field" data-from spellcheck="false" placeholder="github:OWNER/REPO"></label>
<p class="note">${tt('这台电脑上的一个文件夹或一个 SKILL.md；一个仓库（github:OWNER/REPO[#文件夹]、git 地址）；一个压缩包或 SKILL.md 的地址。拿进来的技能先是"提议"，它带的程序要在这里自测通过才用。', 'A folder or a SKILL.md on this computer; a repository (github:OWNER/REPO[#FOLDER], a git address); the address of an archive or of a SKILL.md. Skills come in as "proposed", and a program one brings is used only once it passed its own test here.')}</p>
<div data-found></div>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn quiet" data-look>${tt('先看看', 'Look first')}</button><button type="button" class="btn" data-default>${tt('添加', 'Add')}</button></div>`)
    const from = () => d.querySelector('[data-from]').value.trim()
    const need = () => { if (from()) return false; fail(d, { error: tt('先填来源。', 'Give the source first.') }); return true }
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-look]'), async () => {
        if (need()) return
        busy(d, tt('正在读（仓库可能要几十秒）…', 'reading it (a repository can take a while)…'))
        const r = await post('/api/agent/skill_sources', { identity: c.id, action: 'test', from: from() })
        if (!r.ok) return fail(d, r)
        const found = (r.data.result || {}).skills || []
        d.querySelector('.res').innerHTML = `<span class="c-done">✓ ${tt(`读到 ${found.length} 个技能`, `${found.length} skill${found.length === 1 ? '' : 's'} found`)}</span>`
        d.querySelector('[data-found]').innerHTML = `<ul class="tools">${found.map((k) => `<li><code>${esc(k.name)}</code> ${esc(k.description || '')}${k.program ? ` · ${tt('带程序', 'has a program')}` : ''}</li>`).join('')}</ul>`
    })
    press(d.querySelector('[data-default]'), async () => {
        if (need()) return
        busy(d, tt('正在拿进来…', 'taking them in…'))
        const r = await post('/api/agent/skill_sources', { identity: c.id, action: 'add', from: from() })
        if (!r.ok) return fail(d, r)
        const result = r.data.result || {}
        closeDialog()
        toast(tt(`拿进来 ${(result.added || []).length} 个技能${(result.skipped || []).length ? `，${result.skipped.length} 个同名的没动` : ''}`, `${(result.added || []).length} skill${(result.added || []).length === 1 ? '' : 's'} taken in${(result.skipped || []).length ? `, ${result.skipped.length} of the same name left as they were` : ''}`))
        c.reload()
    })
}
function sourceRemove(id) {
    const d = dialog(`<h5>${tt('移除这个技能来源？', 'Remove this skill source?')}</h5><p class="say">${tt('以后不再从它那里拿技能。', 'Skills are no longer taken from it.')}</p>
<label class="check"><input type="checkbox" data-keep><span>${tt('留下它已经带来的技能', 'Keep the skills it already brought')}</span></label>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no autofocus>${tt('取消', 'Cancel')}</button><button type="button" class="btn danger" data-default>${tt('移除', 'Remove')}</button></div>`)
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await post('/api/agent/skill_sources', { identity: c.id, action: 'remove', id, keep: d.querySelector('[data-keep]').checked })
        if (!r.ok) return fail(d, r)
        closeDialog(); looked.delete(id); c.reload()
    })
}

export function actions() {
    on('channel-add', () => connect(kinds.length === 1 ? { kind: kinds[0].kind } : {}))
    on('channel-step', async (n) => {
        const got = await get('/api/agent/channels', { identity: c.id })
        const a = got && (got.channels || []).find((x) => x.account === n.dataset.arg)
        if (!a) return said(failed.get('/api/agent/channels') || { error: tt('这个账号不在了。', 'This account is gone.') })
        return connect({ kind: a.kind, account: a.account, from: n.dataset.step, who: a.identity || c.id })
    })
    on('channel-settings', (n) => channelSettings(n.dataset.arg))
    on('channel-test', async (n) => {
        const r = await channel({ identity: c.id, action: 'test', account: n.dataset.arg })
        if (!r.ok) return said(r, tt('测试没通过', 'The test failed'))
        const result = r.data.result || {}
        toast(tt(`${n.dataset.arg} 连着${result.groups !== undefined && result.groups !== null ? `，在 ${Array.isArray(result.groups) ? result.groups.length : result.groups} 个群里` : ''}${result.owner ? `，主人是 ${result.owner}` : ''}`, `${n.dataset.arg} is connected${result.groups !== undefined && result.groups !== null ? `, in ${Array.isArray(result.groups) ? result.groups.length : result.groups} groups` : ''}${result.owner ? `, owner ${result.owner}` : ''}`))
    })
    on('channel-remove', async (n) => {
        if (!(await confirm({ title: tt(`移除渠道账号 ${n.dataset.arg}？`, `Remove the channel account ${n.dataset.arg}?`), text: tt('它不再在那里收发消息；已有的对话和记录留着。', 'It no longer receives or sends there; the chats and their records stay.'), yes: tt('移除', 'Remove'), danger: true }))) return
        const r = await channel({ identity: c.id, action: 'remove', account: n.dataset.arg })
        if (!r.ok) return said(r)
        await c.app.refresh(); return c.reload()
    })
    on('channel-pair', async (n) => {
        const r = await channel({ identity: c.id, action: 'pair', account: n.dataset.arg, code: n.dataset.code })
        if (!r.ok) return said(r)
        toast(tt('已批准', 'Approved')); return c.reload()
    })
    on('mcp-add', mcpAdd)
    on('mcp-test', async (n) => {
        const r = await post('/api/app/mcp', { action: 'test', name: n.dataset.arg })
        if (!r.ok) { tools.delete(n.dataset.arg); return said(r, tt('没连上', 'It did not connect')) }
        tools.set(n.dataset.arg, r.data.result)
        toast(tt(`连上了，${r.data.result.tools.length} 个工具，${r.data.result.seconds} 秒`, `Connected: ${r.data.result.tools.length} tool${r.data.result.tools.length === 1 ? '' : 's'} in ${r.data.result.seconds} s`))
        return c.reload()
    })
    on('mcp-enable', async (n) => {
        const r = await post('/api/app/mcp', { action: n.dataset.on === '1' ? 'enable' : 'disable', name: n.dataset.arg })
        if (!r.ok) return said(r)
        return c.reload()
    })
    on('mcp-remove', async (n) => {
        if (!(await confirm({ title: tt(`移除 MCP 服务 ${n.dataset.arg}？`, `Remove the MCP server ${n.dataset.arg}?`), text: tt('它的工具不再可用；存下的密钥一起去掉。', 'Its tools are no longer available; the secrets kept for it go too.'), yes: tt('移除', 'Remove'), danger: true }))) return
        const r = await post('/api/app/mcp', { action: 'remove', name: n.dataset.arg })
        if (!r.ok) return said(r)
        tools.delete(n.dataset.arg); return c.reload()
    })
    on('acp-add', acpAdd)
    on('acp-test', async (n) => {
        const r = await post('/api/app/acp', { action: 'test', id: n.dataset.arg })
        if (!r.ok) return said(r, tt('它没有回答', 'It did not answer'))
        toast(tt(`它回答了（${r.data.result.seconds} 秒）：${r.data.result.reply}`, `It answered (${r.data.result.seconds} s): ${r.data.result.reply}`))
        return c.reload()
    })
    on('acp-remove', async (n) => {
        if (!(await confirm({ title: tt(`移除外部 agent ${n.dataset.arg}？`, `Remove the external agent ${n.dataset.arg}?`), text: tt('用它当模型的条目不再能用。它自己和它的登录不动。', 'Model entries that use it stop working. The tool itself and its sign-in are not touched.'), yes: tt('移除', 'Remove'), danger: true }))) return
        const r = await post('/api/app/acp', { action: 'remove', id: n.dataset.arg })
        if (!r.ok) return said(r)
        return c.reload()
    })
    on('source-add', sourceAdd)
    on('source-test', async (n) => {
        const r = await post('/api/agent/skill_sources', { identity: c.id, action: 'test', id: n.dataset.arg })
        if (!r.ok) return said(r, tt('没读到', 'It could not be read'))
        looked.set(n.dataset.arg, (r.data.result || {}).skills || [])
        toast(tt(`读到 ${looked.get(n.dataset.arg).length} 个技能`, `${looked.get(n.dataset.arg).length} skill${looked.get(n.dataset.arg).length === 1 ? '' : 's'} read`))
        return c.reload()
    })
    on('source-update', async (n) => {
        const r = await post('/api/agent/skill_sources', { identity: c.id, action: 'update', id: n.dataset.arg })
        if (!r.ok) return said(r, tt('没更新成', 'It was not updated'))
        const fresh = Object.values(((r.data.result || {}).updated) || {}).flat()
        toast(fresh.length ? tt(`新拿进来：${fresh.join('、')}`, `Newly taken in: ${fresh.join(', ')}`) : tt('没有新的技能', 'No new skills'))
        return c.reload()
    })
    on('source-remove', (n) => sourceRemove(n.dataset.arg))
}
