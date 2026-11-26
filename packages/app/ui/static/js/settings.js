// Settings: General, Model, Usage, Permissions and limits, Packages, What it learned,
// Connectors, Computer, Personalization, Data, About. Global settings are the core's
// (/api/app/settings); an identity's own (agent.*, learning.*, spaces.<place>.proactive) are the
// agent package's (/api/agent/settings), shown for the identity in use.
import { esc, tt, sectionName, SECTIONS, evidence, usd, when } from './i18n.js'
import { get as fetchJson, post, failed } from './api.js'
import { $, $$, dialog, closeDialog, steps, toggle, toast, loading, problem } from './ui.js'
import { settingRow, wireSettings } from './fields.js'
import { modelDialog } from './onboarding.js'
import * as update from './update.js'

// What a page reads is kept: a page draws at once from what it read last time, the reads run
// again in the background, and the page draws again only when something changed. Nothing on
// a Settings page waits for the network or a subprocess after the first visit.
const STORE = 'harness.settings.seen'
const seen = new Map((() => { try { return JSON.parse(localStorage.getItem(STORE) || '[]') } catch { return [] } })())
const keep = () => { try { localStorage.setItem(STORE, JSON.stringify([...seen].slice(-60))) } catch { /* full or off */ } }
let fresh = null // the reads of this drawing that were already fresh
function get(path, params) {
    const key = path + JSON.stringify(params || {})
    const reading = fetchJson(path, params).then((value) => {
        const before = seen.get(key)
        if (value === null && before !== undefined && before !== null) return before // no answer now: what it said last
        seen.set(key, value)
        keep()
        if (before !== undefined && JSON.stringify(before) !== JSON.stringify(value) && redraw) redraw()
        return value
    })
    if (seen.has(key) && !(fresh && fresh.has(key))) return Promise.resolve(seen.get(key))
    if (fresh) fresh.add(key)
    return reading
}
let redraw = null

let core = { values: {}, schema: {} }
let own = null // the identity's settings, when the host has them
let treePath = []

async function load(app) {
    core = (await get('/api/app/settings')) || { values: {}, schema: {} }
    if (!Object.keys(core.schema || {}).length) seen.delete('/api/app/settings{}') // not read: ask again next time
    own = await get('/api/agent/settings', { identity: app.identity.id })
}
const ownValue = (key) => {
    if (!own) return undefined
    const flat = own.values || own
    if (key in flat) return flat[key]
    const [s, k] = key.split('.')
    return flat[s] && typeof flat[s] === 'object' ? flat[s][k] : undefined
}
const value = (section, key) => {
    const mine = ownValue(`${section}.${key}`)
    if (mine !== undefined) return mine
    const v = (core.values[section] || {})[key]
    return v !== undefined ? v : ((core.schema[section] || {})[key] || {}).default
}

// Save one setting: the identity's own through the agent package ({section, key, value}; a
// place's "acting on its own" is spaces.<place>), the others through the core. The answer is
// the request's ({ok} or {ok: false, error, fix}); fields.js shows it beside the control.
async function change(app, section, key, v, perIdentity) {
    const r = perIdentity
        ? await post('/api/agent/settings', { identity: app.identity.id, section, key: section === 'spaces' ? key.split('.')[0] : key, value: v })
        : await post('/api/app/settings', { [section]: { [key]: v } })
    if (!r.ok) return r
    if (perIdentity) own = r.data || own
    else if (r.data && r.data.values) core.values = r.data.values
    if (app.applied) app.applied(section, key, v)
    return r
}

// one setting as a row (fields.js): what it is, and its control by kind
function setting(section, key, { title, perIdentity = false, choices, about } = {}) {
    return settingRow({ section, key, spec: (core.schema[section] || {})[key] || {}, value: value(section, key), title, about, choices, perIdentity })
}

export async function open(app, id, again = false) {
    app.section = id
    const s = $('.pg-settings')
    // the keyboard stays on the list of pages while it moves through them
    const inNav = !s.classList.contains('open') || s.querySelector('nav').contains(document.activeElement)
    s.querySelector('nav').innerHTML = `<div class="nt" data-tauri-drag-region="deep">${tt('设置', 'Settings')}</div>`
        + SECTIONS.map(([sid, zh, en]) => `<button type="button" data-act="settings" data-arg="${sid}" class="${sid === id ? 'on' : ''}"${sid === id ? ' aria-current="page"' : ''}>${tt(zh, en)}</button>`).join('')
    const pane = s.querySelector('.pane')
    const head = `<div class="lt" data-tauri-drag-region="deep"><h2>${esc(sectionName(id))}</h2><button type="button" class="x" data-act="settings-close" data-tip="${tt('关闭设置', 'Close Settings')}" data-keys="Esc">${tt('关闭', 'Close')}</button></div>`
    if (!s.classList.contains('open') || pane.dataset.section !== id) { pane.innerHTML = head + loading(); pane.scrollTop = 0 }
    pane.dataset.section = id
    s.classList.add('open')
    if (inNav && !again) s.querySelector('nav button.on').focus({ preventScroll: true })
    // A second drawing (something changed in the background) uses what was just read.
    fresh = again ? new Set(seen.keys()) : null
    redraw = again ? null : () => { if (app.section === id && !document.querySelector('.pg-settings .pane :focus')) open(app, id, true) }
    await load(app)
    if (app.section !== id) return
    let html
    if (!core.schema || !Object.keys(core.schema).length) {
        // the settings themselves were not read: the reason, and a way to try again
        html = problem(failed.get('/api/app/settings') || {}, { title: tt('设置没有读出来', 'The settings could not be read'), retry: 'settings' })
    } else {
        try { html = await PAGES[id](app) } catch (error) {
            html = problem({ error: String((error && error.message) || error) }, { title: tt('这一页没有画出来', 'This page could not be drawn'), retry: 'settings' })
        }
    }
    if (app.section !== id) return
    pane.innerHTML = head + html
    wireSettings(pane, (section, key, v, perIdentity) => change(app, section, key, v, perIdentity))
    if (AFTER[id] && !pane.querySelector('.st-problem')) AFTER[id](app, pane)
}
export function closeSettings(app) {
    const s = $('.pg-settings'), was = s.classList.contains('open')
    app.section = null; s.classList.remove('open')
    if (was && (s.contains(document.activeElement) || document.activeElement === document.body)) { const back = $('.pg-foot .set'); if (back) back.focus() }
}

const PAGES = {
    async general(app) {
        return `<p>${tt('它是常驻在这台电脑上的服务：关掉窗口它也照常工作，托盘里能暂停或退出。', 'It is a resident service on this computer: it keeps working with the window closed; the tray pauses or quits it.')}</p>`
            + `<div class="sr" data-life><div><b>${tt('暂停', 'Paused')}</b><small>${tt('暂停时不叫醒模型、不做动作；渠道照常连着、事件照常记下，继续后再处理。', 'While paused the model is not woken and no actions run; channels stay connected and events are recorded, handled after resuming.')}</small></div><div class="ctl">${toggle(!!app.life.paused)}</div></div>`
            + (ownValue('agent.autostart') !== undefined ? setting('agent', 'autostart')
                : `<div class="sr"><div><b>${tt('开机时启动', 'Start at login')}</b><small>${tt('系统里的登录项是唯一的依据。', 'The login item in the system is the only truth.')}</small></div><div class="ctl"><span class="ro">harness host install</span></div></div>`)
            + setting('general', 'language') + setting('general', 'theme') + setting('general', 'notifications')
            + `<p>${tt('系统通知只用于要你决定或知道的事：批准请求、额度用完、失败或不确定的动作、渠道登录过期。', 'System notifications are only for what you must decide or know: approval requests, the limit reached, actions that failed or ended unknown, an expired channel login.')}</p>`
    },
    async model(app) {
        const status = (await get('/api/app')) || {}
        const llm = status.llm || {}, list = ((await get('/api/app/models')) || {}).models || []
        return `<p>${tt('这个身份用的模型。换模型后人设、记忆、技能和反应都不变；在一个对话里用 /model 只换那个对话。', "This identity's model. Changing it keeps persona, memory, skills and reactions; /model in a chat changes that chat only.")}</p>`
            + `<div class="lg">${tt('现在', 'Now')}</div><div class="lr"><span class="n">${esc(llm.provider || '—')} · ${esc(llm.model || '—')}</span><span class="ev ${llm.ready ? 'ev-eff' : 'ev-prop'}">${llm.ready ? tt('可用', 'ready') : tt('没准备好', 'not ready')}</span><span class="u"></span><span class="s">${esc(llm.key_env || '')}${llm.key && llm.key.set ? ' ✓' : ''}</span><span class="undo"><button data-change-model>${tt('换', 'change')}</button></span></div>`
            + (list.length ? `<div class="lg">${tt('模型列表', 'Models')}</div>` + list.map((m) => `<div class="lr"><span class="n">${esc(m.name || m.model || m.id)}</span><span class="ev ${m.enabled === false ? 'ev-off' : 'ev-own'}">${m.enabled === false ? tt('关', 'off') : tt('开', 'on')}</span><span class="u"></span><span class="s">${esc(m.provider || '')}</span></div>`).join('') : '')
            + setting('model', 'reasoning_effort')
            + `<p>${tt('用 OpenRouter 的话，也可以在 key 上设一个每天重置的额度。', 'With OpenRouter you can also set a limit with a daily reset on the key itself.')}</p>`
    },
    async usage(app) {
        const u = (await get('/api/agent/usage', { identity: app.identity.id, week: 1 })) || {}
        const d = u.today || {}, budget = d.daily_budget || value('agent', 'daily_budget') || 2
        const by = Object.values(d.by_source || {})
        const chats = new Map(app.chats.map((c) => [c.chat, c.title]))
        const byChat = {}
        by.filter((s) => s.kind === 'chat' || s.kind === 'task').forEach((s) => { const n = s.id === 'main' ? tt('主对话', 'Main conversation') : chats.get(s.id) || s.title || s.id; byChat[n] = (byChat[n] || 0) + (s.cost_usd || 0) })
        const KIND = { chat: tt('回答和动作', 'answers and actions'), task: tt('任务', 'tasks'), learning: tt('后台回看和 dreaming', 'review and dreaming') }
        const kinds = {}
        by.forEach((s) => { const k = KIND[s.kind] || s.kind || tt('其他', 'other'); kinds[k] = (kinds[k] || 0) + (s.cost_usd || 0) })
        const rows = (list) => { const top = Math.max(0.0001, ...list.map((x) => x[1])); return list.sort((a, b) => b[1] - a[1]).map(([n, v]) => `<div class="urow"><span>${esc(n)}</span><span class="b"><i style="width:${(v / top) * 100}%"></i></span><span>${usd(v)}</span></div>`).join('') }
        return `<p>${tt('今天', 'Today')} ${usd(d.cost_usd)} / ${usd(budget)} · ${tt('每日额度按身份算，0:00 重置；OpenRouter 报告的花费，其他按价格表估算', 'the daily limit is per identity and resets at 0:00; OpenRouter reports cost, other providers are estimated')}</p>`
            + `<div class="ubar"><i style="width:${Math.min(100, ((d.cost_usd || 0) / budget) * 100)}%"></i></div>`
            + `<p>${tt('给你留', 'kept for you')} ${usd(d.reserve ?? value('agent', 'reserve'))} · ${tt('没有价格的调用', 'calls without a price')} ${d.unpriced_calls || 0} / ${d.daily_calls ?? value('agent', 'daily_calls')}${d.raised ? ' · ' + tt('今天已提高', 'raised today') : ''}</p>`
            + `<div class="lg">${tt('按对话', 'By chat')}</div>${Object.keys(byChat).length ? rows(Object.entries(byChat)) : `<p>${tt('今天还没有花费。', 'Nothing spent today yet.')}</p>`}`
            + `<div class="lg">${tt('按事', 'By kind')}</div>${Object.keys(kinds).length ? rows(Object.entries(kinds)) : `<p>—</p>`}`
            + (u.week ? `<div class="lg">${tt('这一周', 'This week')}</div>${rows(u.week.slice().reverse().map((x) => [x.date, x.cost_usd || 0]))}` : '')
            + `<div class="btns"><button class="b" data-raise>${tt('提高今天的额度…', "Raise today's limit…")}</button></div>`
    },
    async permissions(app) {
        const pend = ((await get('/api/agent/approvals', { identity: app.identity.id })) || {}).pending || []
        const places = app.life.places || []
        return `<p>${tt('只有两种人：主人和其他人。其他人只能请它做所在对话里的事，不能让它动你的电脑、文件和账号，也不能替你批准。付款永远要你批准，登录永远由你来。',
            'Two kinds of people: the owner and everyone else. Everyone else can ask it only for things within their chat; they cannot have it touch your computer, files or accounts, or approve for you. Payment always needs your approval; logging in is always yours.')}</p>`
            + (pend.length ? `<div class="lg">${tt('等你批准', 'Waiting for you')}</div>` + pend.map((a) => `<div class="lr"><span class="n">${esc(a.what || a.verb)} <span class="code">${esc(a.code)}</span></span><span class="ev ev-prop">${esc(a.place || '')}</span><span class="u"></span><span class="s">${when(a.expires)}</span></div>`).join('') : '')
            + `<div class="lg">${tt('批准', 'Approvals')}</div>` + setting('approvals', 'ask') + setting('approvals', 'programs') + setting('approvals', 'timeout_minutes')
            + `<div class="lg">${tt('额度', 'Limits')}</div>` + setting('agent', 'daily_budget', { perIdentity: true })
            + setting('agent', 'reserve', { perIdentity: true }) + setting('agent', 'daily_calls', { perIdentity: true })
            + setting('limits', 'max_steps') + setting('limits', 'max_minutes')
            + `<div class="lg">${tt('它自己做', 'On its own')}</div>` + setting('agent', 'proactive', { perIdentity: true })
            + places.map((p) => setting('spaces', `${p.id}.proactive`, { title: `${p.title || p.id} · ${p.kind}`, perIdentity: true, choices: ['off', 'learn', 'do'] })).join('')
    },
    async packages(app) {
        const st = (await get('/api/app/packages')) || {}
        const rows = st.packages || []
        return `<p>${tt('扩展包在第一次用到时自动安装。', 'Packages install on first use.')}</p>` + setting('packages', 'auto_install')
            + `<div class="lg">${tt('已安装', 'Installed')}</div>` + (rows.length ? rows.map((p) => `<div class="lr"><span class="n">${esc(p.name)} <span class="w" style="color:var(--ar-dim)">${esc(p.summary || (p.shown || {}).summary || '')}</span></span><span class="ev ${p.enabled === false ? 'ev-off' : 'ev-eff'}">${p.enabled === false ? tt('关', 'off') : tt('开', 'on')}</span><span class="u">${esc(p.version || '')}</span><span class="s"></span><span class="undo"><button data-pkg="${esc(p.name)}" data-on="${p.enabled === false ? 1 : 0}">${p.enabled === false ? tt('打开', 'enable') : tt('关掉', 'disable')}</button></span></div>`).join('') : `<p>${tt('还没有装扩展包。', 'No packages installed yet.')}</p>`)
    },
    async learned(app) {
        const got = await get('/api/agent/learned', { identity: app.identity.id })
        const skills = (got && got.skills) || []
        const raw = (got && got.memory) || []
        const memory = Array.isArray(raw) ? raw : Object.entries(raw).map(([key, v]) => ({ key, ...v }))
        const shared = (got && got.shared_libraries) || []
        return `<p>${tt('它学到的东西：每一项的证据、用过几次、从哪段经历来。新学的立刻生效，可以撤销。', 'What it learned: each item with its evidence, how often it was used, and the experience it came from. New learning takes effect at once and can be undone.')}</p>`
            + setting('learning', 'mode', { perIdentity: true, about: tt('学了马上生效（可撤销）、先等你看过、只用不学，或者不学也不加载学到的。', 'Whether what it learns takes effect at once (it can be undone), waits for you first, is only used and not added to, or is neither learned nor loaded.') })
            + `<div class="lg">${tt('技能', 'Skills')}</div>` + (skills.length ? skills.map((s, i) => skillRow(s, i, app)).join('') : `<p>${tt('还没有学会技能。', 'No skills learned yet.')}</p>`)
            + `<div class="lg" data-tree-head>${tt('反射树', 'Tree of reactions')}</div><div class="tvw"></div>`
            + `<div class="lg">${tt('记忆', 'Memory')}</div>` + (memory.length ? memory.map((m) => memoryRow(m, app)).join('') : await memoryFallback(app))
            + (shared.length ? `<div class="lg">${tt('共享库 · 只读', 'Shared libraries · read only')}</div>` + shared.map((l) => `<div class="lr"><span class="n">${esc(l.name || l)}</span><span class="ev ev-none">—</span><span class="u"></span><span class="s">${esc(l.enabled ? tt('已启用', 'enabled') : '')}</span></div>`).join('') : '')
    },
    async connectors(app) {
        const connectors = core.values.connectors || []
        const channels = ((await get('/api/agent/channels', { identity: app.identity.id })) || {}).channels || []
        const pending = channels.flatMap((c) => (c.pending || []).map((p) => ({ ...p, account: c.account })))
        return `<p>${tt('渠道、MCP 服务和技能来源。', 'Channels, MCP servers and skill sources.')}</p>`
            + (channels.length ? `<div class="lg">${tt('渠道', 'Channels')}</div>` : '') + channels.map((c) => `<div class="lr"><span class="n">${esc(c.title || c.account)} <span style="color:var(--ar-dim);font:400 12px var(--ar-mono)">${esc(c.account)} · ${tt('私聊', 'strangers')} ${esc(c.dm || '')} · ${tt('进了', 'in')} ${Object.keys(c.entered || {}).length} ${tt('个群', 'groups')}${c.owner ? '' : ' · ' + tt('还没绑定主人', 'owner not bound')}</span></span><span class="ev ${c.online ? 'ev-eff' : 'ev-prop'}">${c.online ? tt('已连接', 'connected') : tt('等登录', 'waiting login')}</span><span class="u"></span><span class="s">${c.online && !c.owner ? `<button class="go" data-owner-code="${esc(c.account)}">${tt('绑定主人', 'bind owner')}</button>` : esc(app.identity.name)}</span><span class="undo"><button data-remove-channel="${esc(c.account)}">${tt('移除', 'remove')}</button></span></div>`).join('')
            + (pending.length ? `<div class="lg">${tt('等你批准的配对', 'Pairing requests')}</div>` + pending.map((p) => `<div class="lr"><span class="n">${esc(p.name || p.user || p.from || '')} <span class="code">${esc(p.code)}</span></span><span class="ev ev-prop">${esc(p.account)}</span><span class="u"></span><span class="s"></span><span class="undo"><button data-pair="${esc(p.code)}" data-account="${esc(p.account)}">${tt('批准', 'approve')}</button></span></div>`).join('') : '')
            + (connectors.length ? `<div class="lg">MCP</div>` : '')
            + connectors.map((c) => `<div class="lr"><span class="n">${esc(c.name || c.id || c.url)}</span><span class="ev ${c.enabled === false ? 'ev-off' : 'ev-eff'}">${c.enabled === false ? tt('关', 'off') : tt('已连接', 'connected')}</span><span class="u"></span><span class="s">MCP</span></div>`).join('')
            + `<button class="addc" data-add-channel>＋ ${tt('添加渠道', 'Add a channel')}</button>`
    },
    async computer(app) {
        const places = app.life.places || []
        const mine = places.filter((p) => ['desktop', 'browser', 'folder'].includes(p.kind))
        return `<p>${tt('它在这台电脑上能用的地方：项目文件夹、浏览器和桌面。每个地方可以单独设：不主动、只学习、学习也做事。', 'Where it works on this computer: project folders, the browser and the desktop. Each can be set on its own: not on its own, learning only, or learning and doing.')}</p>`
            + (mine.length ? mine.map((p) => `<div class="lr"><span class="n">${esc(p.title || p.id)}</span><span class="ev ${p.online ? 'ev-eff' : 'ev-prop'}">${esc(p.kind)}</span><span class="u"></span><span class="s">${p.single_body ? tt('一次只给一个对话', 'one chat at a time') : ''}</span><span class="undo"><button data-disconnect="${esc(p.id)}">${tt('断开', 'remove')}</button></span></div>`).join('') : `<p>${tt('还没有接上。', 'Nothing connected yet.')}</p>`)
            + `<div class="btns"><button class="b" data-connect="folder">＋ ${tt('项目文件夹', 'Project folder')}</button><button class="b" data-connect="browser">＋ ${tt('浏览器', 'Browser')}</button><button class="b" data-connect="desktop">＋ ${tt('桌面', 'Desktop')}</button></div>`
            + `<div class="lg">${tt('安全层的固定规则', 'The safety layer’s fixed rules')}</div><p>${tt('你在用桌面时，它的输入被拒绝；发送、发布、付款、删除、登录和不可撤销的步骤要你批准；超出权限的被拒绝；它自己发起的事比你交代的事低一级权限。被拒绝之后怎么做由它判断。',
                'While you use the desktop its input is refused; sending, publishing, paying, deleting, logging in and irreversible steps pass only with your approval; anything beyond its authority is refused; work it starts itself has one level less authority than work you ask for. What to do after a refusal is its own judgement.')}</p>`
            + setting('physical', 'level') + setting('physical', 'idle_seconds')
    },
    async personalization(app) {
        const p = (await get('/api/app/persona', { identity: app.identity.id })) || { files: [] }
        return `<p>${esc(p.folder || `agents/${app.identity.id}/`)} · ${tt('人设和记忆是可以打开编辑的 Markdown 文件；也可以直接告诉它。', 'Persona and memory are Markdown files you can edit, or just tell it.')}</p>`
            + `<div class="sr"><div><b>${tt('显示名', 'Display name')}</b><small>${tt('随时能改；id 不变', 'changes any time; the id stays')} · ${esc(app.identity.id)}</small></div><div class="ctl"><input type="text" data-rename value="${esc(app.identity.name)}"></div></div>`
            + p.files.map((f) => `<div class="file" data-file="${esc(f.name)}"><div class="fn">${esc(f.name)}<button data-edit>${tt('编辑', 'edit')}</button></div><pre>${esc(f.text || tt('（空）', '(empty)'))}</pre></div>`).join('')
    },
    async data(app) {
        return `<p>agents/${esc(app.identity.id)}/ · ${esc(app.identity.name)}</p><div class="btns"><button class="b" data-share>${tt('分享…', 'Share…')}</button><button class="b" data-card>${tt('导出角色卡', 'Export a character card')}</button><button class="b" data-backup>${tt('备份…', 'Back up…')}</button><button class="b" data-restore>${tt('恢复…', 'Restore…')}</button><button class="b" data-retire>${tt('在这台电脑上停用…', 'Retire here…')}</button></div>`
            + ((keep) => (keep ? `<div class="lg">${tt('保留', 'Keeping')}</div>` + keep : ''))(setting('agent', 'keep_days', { perIdentity: true }))
    },
    async about(app) {
        const a = (await get('/api/app/about', { identity: app.identity.id })) || {}
        return `<div class="lr"><span class="n">The Harness</span><span class="ev ev-none"></span><span class="u"></span><span class="s">${esc(a.version || '')}</span></div>`
            + `<div class="lr"><span class="n">${tt('身份', 'Identity')} · ${esc(a.name || app.identity.name)}</span><span class="ev ev-none"></span><span class="u"></span><span class="s">${esc(a.identity || app.identity.id)}</span></div>`
            + `<div class="lr"><span class="n">${tt('文件夹', 'Folder')}</span><span class="ev ev-none"></span><span class="u"></span><span class="s">${esc(a.folder || '')}</span></div>`
            + `<div class="lr"><span class="n">${tt('密钥指纹', 'Key fingerprint')}</span><span class="ev ev-none"></span><span class="u"></span><span class="s" title="${esc(a.fingerprint || '')}">${esc(a.fingerprint || '—')}</span></div>`
            + `<p>${tt('私钥只在这台电脑上，永远不进分享。', 'The private key stays on this computer and never goes into a share.')}</p>`
            + await update.about(app, setting)
    },
}

function skillRow(s, i, app) {
    const e = evidence(s.evidence)
    const src = { ...(s.source || {}) }
    if (src.chat && !src.title) src.title = ((app.chats.find((c) => c.chat === src.chat) || {}).kind === 'main' ? tt('主对话', 'main') : (app.chats.find((c) => c.chat === src.chat) || {}).title)
    return `<div class="lr click${s.archived ? ' undone' : ''}" data-skill="${i}"><span class="n">${esc(s.description || s.name)}</span><span class="ev ev-${e.cls}">${esc(e.text)}</span><span class="u">${s.uses ?? 0} ${tt('次', s.uses === 1 ? 'use' : 'uses')}</span><span class="s">${esc(src.title || src.chat || '')}${src.time ? ' · ' + when(src.time) : ''}</span><span class="undo">${s.archived ? tt('已归档', 'archived') : ''}</span></div>`
}
function memoryRow(m, app) {
    const e = evidence(m.scope || 'private'), title = (app.chats.find((c) => c.chat === m.chat) || {}).title
    return `<div class="lr"><span class="n">${esc(m.text || m.key)}</span><span class="ev ev-${e.cls}">${esc(e.text)}</span><span class="u"></span><span class="s">${esc(title || m.source || '')}${m.updated ? ' · ' + when(m.updated) : ''}</span>${m.key ? `<span class="undo"><button data-forget="${esc(m.key)}">${tt('忘掉', 'forget')}</button></span>` : ''}</div>`
}
async function memoryFallback(app) {
    const m = await get('/api/agent/memory', { identity: app.identity.id })
    const raw = m ? (Array.isArray(m) ? m : m.entries || m.items || m.memory || {}) : []
    const items = Array.isArray(raw) ? raw : Object.entries(raw).map(([key, v]) => (typeof v === 'string' ? { key, text: v } : { key, ...v }))
    return items.length ? items.map((x) => memoryRow(typeof x === 'string' ? { text: x } : x, app)).join('') : `<p>${tt('还没有记忆。', 'Nothing remembered yet.')}</p>`
}

// the tree of reactions, one level at a time like a file manager: the path on top, this
// level's nodes in order; a node with nodes under it opens as the new root
async function drawTree(app, pane) {
    const host = pane.querySelector('.tvw'); if (!host) return
    const t = await get('/api/agent/tree', { identity: app.identity.id, path: treePath.join('/') })
    if (!t) { host.innerHTML = `<p>${tt('反射树还没在这台 host 上运行。', 'The tree of reactions does not run in this host yet.')}</p>`; return }
    const path = t.path || treePath, nodes = t.nodes || []
    const crumbs = [tt('根', 'root'), ...path]
    const total = nodes.reduce((a, n) => a + 1 + (n.children || 0), 0)
    const head = pane.querySelector('[data-tree-head]')
    if (head) head.textContent = tt(`反射树 · 这一层 ${nodes.length} 个，共 ${total} 个节点 · 从上往下判断，上面的先；点开一支就进到它下面`, `Tree of reactions · ${total} nodes here · judged top down, the upper first; open a branch to go inside it`)
    const lit = nodes.some((n) => n.lit)
    host.innerHTML = `<div class="tv"><div class="crumbs">${crumbs.map((c, i) => `<button class="bc${i === crumbs.length - 1 ? ' on' : ''}${lit && i === crumbs.length - 1 ? ' lit' : ''}" data-up="${i}">${esc(c)}</button>`).join('<i>›</i>')}</div>`
        + nodes.map((n, i) => {
            const label = n.about || [n.when, n.do].filter(Boolean).join(' → ') || n.name
            if (n.children) return `<div class="lr rx dir click${n.lit ? ' lit' : ''}" data-open="${esc(n.name)}"><span class="n"><span class="ord">${i + 1}</span><span class="fd">▸</span>${esc(label)}</span><span class="ev ev-none">${tt(`${n.children} 个节点`, `${n.children} nodes`)}</span><span class="u"></span><span class="s"></span><span class="go">›</span></div>`
            const e = evidence(n.source === 'builtin' ? 'builtin' : n.source === 'owner' ? 'owner' : n.evidence)
            const act = n.source === 'builtin' ? (n.enabled === false ? tt('启用', 'enable') : tt('停用', 'disable')) : n.source === 'owner' ? tt('撤销', 'undo') : tt('停用', 'disable')
            return `<div class="lr rx${n.enabled === false ? ' off' : ''}${n.lit ? ' lit' : ''}" data-node="${esc(n.name)}"><span class="n"><span class="ord">${i + 1}</span>${esc(label)}</span><span class="ev ev-${e.cls}">${esc(e.text)}</span><span class="u">${n.uses ?? ''}</span><span class="s"></span><span class="undo"><button data-node-act="${n.source === 'builtin' || n.source !== 'owner' ? (n.enabled === false ? 'enable' : 'disable') : 'remove'}">${act}</button></span></div>`
        }).join('') + (nodes.length ? '' : `<p>${tt('这一层是空的。', 'This level is empty.')}</p>`) + '</div>'
    host.onclick = async (e) => {
        const up = e.target.closest('[data-up]'); if (up) { treePath = treePath.slice(0, +up.dataset.up); return drawTree(app, pane) }
        const act = e.target.closest('[data-node-act]')
        if (act) { const name = act.closest('[data-node]').dataset.node; await post('/api/agent/tree', { identity: app.identity.id, action: act.dataset.nodeAct, path: [...treePath, name].join('/') }); return drawTree(app, pane) }
        const dir = e.target.closest('[data-open]'); if (dir) { treePath = [...treePath, dir.dataset.open]; return drawTree(app, pane) }
    }
}

const AFTER = {
    general(app, pane) {
        const t = pane.querySelector('[data-life] .tog')
        t.onclick = async () => { const r = await post(app.life.paused ? '/api/agent/resume' : '/api/agent/pause', { identity: app.identity.id }); if (r.ok) { app.life = r.data; t.classList.toggle('on', !!r.data.paused); app.refresh() } }
    },
    model(app, pane) { pane.querySelector('[data-change-model]').onclick = () => modelDialog(app, { after: () => open(app, 'model') }) },
    usage(app, pane) {
        pane.querySelector('[data-raise]').onclick = () => {
            const d = dialog(`<h5>${tt('提高今天的额度', "Raise today's limit")}</h5><label><span>${tt('今天的额度', "Today's limit")}</span><input class="field" type="number" step="0.5" min="0" value="${(value('agent', 'daily_budget') || 2) + 1}"></label><p class="note">${tt('只改今天；明天恢复设置里的额度。', 'Today only; tomorrow it is the setting again.')}</p><div class="row"><span class="res"></span><button class="btn">${tt('提高', 'Raise')}</button></div>`)
            d.querySelector('.btn').onclick = async () => {
                const r = await post('/api/agent/usage', { identity: app.identity.id, raise_today: parseFloat(d.querySelector('input').value) })
                d.querySelector('.res').innerHTML = r.ok ? `<span class="c-done">✓ ${tt('已提高', 'raised')}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
                if (r.ok) setTimeout(() => { closeDialog(); open(app, 'usage') }, 600)
            }
        }
    },
    packages(app, pane) {
        $$('[data-pkg]', pane).forEach((b) => { b.onclick = async () => { await post('/api/app/packages/enable', { name: b.dataset.pkg, on: b.dataset.on === '1' }); open(app, 'packages') } })
    },
    async learned(app, pane) {
        treePath = []
        drawTree(app, pane)
        $$('[data-forget]', pane).forEach((b) => { b.onclick = async () => { const r = await post('/api/agent/learned', { identity: app.identity.id, action: 'forget', name: b.dataset.forget }); if (r.ok) b.closest('.lr').classList.add('undone') } })
        const got = await get('/api/agent/learned', { identity: app.identity.id })
        const skills = (got && got.skills) || []
        $$('[data-skill]', pane).forEach((row) => {
            row.onclick = async (e) => {
                if (e.target.closest('.sk')) return
                const open2 = row.querySelector('.sk'); if (open2) { open2.remove(); row.classList.remove('open', 'sel'); return }
                const s = skills[+row.dataset.skill], src = { ...(s.source || {}) }
                if (src.chat && !src.title) src.title = (app.chats.find((c) => c.chat === src.chat) || {}).title
                const hist = (s.history || []).map((h) => (typeof h === 'string' ? h : `${evidence(h.evidence || h.to).text} ${when(h.time)}`)).join(' → ')
                row.classList.add('open', 'sel')
                const sk = document.createElement('div'); sk.className = 'sk'
                sk.innerHTML = `<div class="src" data-jump="${esc(src.chat || '')}">${tt('来源：', 'Source: ')}${esc(src.title || src.chat || '—')}${src.time ? ' · ' + when(src.time) : ''}${src.expired ? ' · ' + tt('原始记录已过期', 'expired') : ' · ' + tt('打开那次对话 →', 'open that chat →')}</div>`
                    + (hist ? `<div class="hist">${esc(hist)} · ${tt('用满 5 次、至少 80% 完成后升级为实际有效', 'effective after 5 uses with at least 80% done')}</div>` : '')
                    + (s.file ? `<div>${esc(s.file)}${s.instructions_only ? ' · ' + tt('只有说明，没有程序', 'instructions only, no program') : ''}</div>` : '')
                    + `<div class="acts">${s.waiting ? `<button data-act="approve">${tt('批准使用', 'approve')}</button>` : ''}${s.archived || s.loaded === false ? `<button data-act="restore">${tt('恢复', 'restore')}</button>` : `<button data-act="undo">${tt('撤销到上一版', 'undo to the previous version')}</button>`}<button data-act="diff">${tt('改动', 'diff')}</button><button data-act="delete">${tt('删除', 'delete')}</button></div><pre class="change" hidden></pre>`
                row.append(sk)
                const files = await get('/api/app/skill', { identity: app.identity.id, name: s.name })
                const program = files && (files.files || []).find((f) => f.name.endsWith('.py') && !f.name.startsWith('test'))
                if (program) sk.querySelector('.acts').insertAdjacentHTML('beforebegin', `<pre>${program.text.trimEnd().split(/\r?\n/).map((l) => `<span class="add">+ ${esc(l)}</span>`).join('\n')}</pre>`)
                sk.querySelector('[data-jump]').onclick = () => { if (src.chat) { closeSettings(app); app.openChat(src.chat) } }
                sk.querySelectorAll('[data-act]').forEach((b) => {
                    b.onclick = async () => {
                        const r = await post('/api/agent/learned', { identity: app.identity.id, action: b.dataset.act, name: s.name })
                        if (!r.ok) return toast(r.error || '')
                        if (b.dataset.act === 'diff') {
                            const pre = sk.querySelector('.change'), text = (r.data.result || r.data).diff || ''
                            pre.hidden = false
                            pre.innerHTML = text ? text.split(/\r?\n/).map((l) => `<span class="${l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : ''}">${esc(l)}</span>`).join('\n') : esc(tt('没有上一版', 'no earlier version'))
                            return
                        }
                        if (b.dataset.act === 'delete') { row.classList.add('undone'); row.querySelector('.undo').textContent = tt('已删除', 'deleted'); sk.remove(); return }
                        const undone = b.dataset.act === 'undo'
                        row.classList.toggle('undone', undone)
                        row.querySelector('.undo').textContent = undone ? tt('已撤销，不再加载', 'undone; no longer loaded') : b.dataset.act === 'restore' ? tt('已恢复', 'restored') : tt('已批准', 'approved')
                    }
                })
            }
        })
    },
    connectors(app, pane) {
        pane.querySelector('[data-add-channel]').onclick = () => channelDialog(app)
        const act = async (body) => { const r = await post('/api/agent/channels', { identity: app.identity.id, ...body }); if (!r.ok) toast(r.error); await app.refresh(); open(app, 'connectors'); return r }
        $$('[data-remove-channel]', pane).forEach((b) => { b.onclick = () => act({ action: 'remove', account: b.dataset.removeChannel }) })
        $$('[data-pair]', pane).forEach((b) => { b.onclick = () => act({ action: 'pair', account: b.dataset.account, code: b.dataset.pair }) })
        $$('[data-owner-code]', pane).forEach((b) => { b.onclick = async () => { const r = await act({ action: 'owner_code', account: b.dataset.ownerCode }); if (r.ok) { closeSettings(app); app.openChat('main') } } })
    },
    computer(app, pane) {
        $$('[data-disconnect]', pane).forEach((b) => { b.onclick = async () => { await post('/api/agent/places', { identity: app.identity.id, action: 'disconnect', place: b.dataset.disconnect }); await app.refresh(); open(app, 'computer') } })
        $$('[data-connect]', pane).forEach((b) => { b.onclick = () => connectDialog(app, b.dataset.connect) })
    },
    personalization(app, pane) {
        const name = pane.querySelector('[data-rename]')
        name.onchange = async () => { const r = await post('/api/agent/identity', { action: 'rename', id: app.identity.id, name: name.value }); if (r.ok) { toast(tt('已改名', 'Renamed')); app.refresh() } }
        $$('[data-file]', pane).forEach((box) => {
            box.querySelector('[data-edit]').onclick = async (e) => {
                const pre = box.querySelector('pre'), area = box.querySelector('textarea')
                if (pre) { const t = document.createElement('textarea'); t.value = pre.textContent === tt('（空）', '(empty)') ? '' : pre.textContent; pre.replaceWith(t); e.target.textContent = tt('保存', 'save'); t.focus(); return }
                const r = await post('/api/app/persona', { identity: app.identity.id, file: box.dataset.file, text: area.value })
                if (r.ok) { const p = document.createElement('pre'); p.textContent = area.value || tt('（空）', '(empty)'); area.replaceWith(p); e.target.textContent = tt('编辑', 'edit'); toast(tt('已保存', 'Saved')) }
            }
        })
    },
    data(app, pane) {
        pane.querySelector('[data-share]').onclick = () => shareDialog(app)
        pane.querySelector('[data-backup]').onclick = () => backupDialog(app)
        pane.querySelector('[data-card]').onclick = () => cardDialog(app)
        pane.querySelector('[data-restore]').onclick = () => restoreDialog()
        pane.querySelector('[data-retire]').onclick = () => retireDialog(app)
    },
}

// Taking it along (the agent package's /api/agent/take): sharing after a preview of every text
// that becomes public, a character card, an encrypted backup, and retiring it here after a move.
async function saveTo(app, name) {
    const a = (await get('/api/app/about', { identity: app.identity.id })) || {}
    return a.save_to ? `${a.save_to}/${name}` : name
}

function shareDialog(app) {
    const fixed = [tt('人设', 'Persona'), tt('头像', 'Avatar'), tt('技能', 'Skills'), tt('反应', 'Reactions')]
    const d = dialog(`<h5>${tt('分享', 'Share')} ${esc(app.identity.name)}</h5><div class="checks">${fixed.map((n) => `<span class="ck on fixed">${n}</span>`).join('')}<button class="ck" data-memory>${tt('记忆', 'Memory')}</button></div>
<div class="pv"><b>${tt('将公开的内容', 'What will be public')}</b><div data-preview style="display:flex;flex-direction:column;gap:4px"><span class="spin"></span></div></div>
<p class="note">${tt('私钥和凭据永远不带。领养的人得到一个新身份和新密钥。', 'The private key and credentials never go. Whoever adopts it gets a new identity and a new key.')}</p>
<label><span>${tt('发到', 'Send to')}</span><input class="field" value="github:you/${esc(app.identity.id)}-agent"></label><div class="row"><span class="res"></span><button class="btn">${tt('分享', 'Share')}</button></div>`)
    const memory = () => d.querySelector('[data-memory]').classList.contains('on')
    const preview = async () => {
        const r = await post('/api/agent/take', { identity: app.identity.id, action: 'share', preview: true, with_memory: memory() })
        const p = r.ok ? r.data : null
        d.querySelector('[data-preview]').innerHTML = !p ? `<span class="c-failed">✕ ${esc(r.error)}</span>`
            : [p.texts.map((t) => esc(t.file.split('/').slice(2).join('/'))).join(' · '),
                tt(`技能 ${(p.skills || []).length} 项 · 反应 ${(p.reactions || []).length} 项`, `${(p.skills || []).length} skills · ${(p.reactions || []).length} reactions`)
                    + (Object.keys(p.replaced || {}).length ? tt('（群名换成占位符）', ' (group names replaced with placeholders)') : ''),
                (p.other_files || []).length ? esc(p.other_files.map((f) => f.split('/').slice(2).join('/')).join(' · ')) : '',
                (p.left_out || []).length ? `${tt('不带：', 'left here: ')}${esc(p.left_out.join(', '))}` : ''].filter(Boolean).map((x) => `<span>${x}</span>`).join('')
    }
    d.querySelector('[data-memory]').onclick = (e) => { e.target.classList.toggle('on'); preview() }
    preview()
    d.querySelector('.btn').onclick = async () => {
        const res = d.querySelector('.res'); res.innerHTML = `<span class="spin"></span>`
        const r = await post('/api/agent/take', { identity: app.identity.id, action: 'share', to: d.querySelector('input').value, with_memory: memory() })
        res.innerHTML = r.ok ? `<span class="c-done">✓ ${esc(r.data.sent || r.data.link || tt('已发出', 'sent'))}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
    }
}

async function cardDialog(app) {
    const d = dialog(`<h5>${tt('导出角色卡', 'Export a character card')}</h5><p class="note">${tt('只带名字、人设和头像（Character Card V3）。', 'Only the name, persona and avatar (Character Card V3).')}</p>
<label><span>${tt('存到', 'Save to')}</span><input class="field" value="${esc(await saveTo(app, `${app.identity.id}.card.png`))}"></label><div class="row"><span class="res"></span><button class="btn">${tt('导出', 'Export')}</button></div>`)
    d.querySelector('.btn').onclick = async () => {
        const r = await post('/api/agent/take', { identity: app.identity.id, action: 'card', path: d.querySelector('input').value })
        d.querySelector('.res').innerHTML = r.ok ? `<span class="c-done">✓ ${esc(r.data.sent || tt('已导出', 'exported'))}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
    }
}

async function backupDialog(app) {
    const d = dialog(`<h5>${tt('备份', 'Back up')} ${esc(app.identity.name)}</h5><p class="note warn">${tt('备份含私钥、记忆和这个身份的渠道凭据，用口令加密。', "The backup holds the private key, memory and this identity's channel credentials, encrypted with a passphrase.")}</p>
<label><span>${tt('口令', 'Passphrase')}</span><input class="field" data-pass type="password" autocomplete="new-password"></label>
<label><span>${tt('存到', 'Save to')}</span><input class="field" data-path value="${esc(await saveTo(app, `${app.identity.id}.harness-backup`))}"></label><div class="checks"><button class="ck" data-keys>${tt('带上模型 key', 'Include model keys')}</button></div>
<div class="row"><span class="res"></span><button class="btn">${tt('保存', 'Save')}</button></div>`)
    d.querySelector('[data-keys]').onclick = (e) => e.target.classList.toggle('on')
    d.querySelector('.btn').onclick = async () => {
        const pass = d.querySelector('[data-pass]').value
        if (!pass) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${tt('先填口令', 'a passphrase first')}</span>`; return }
        const r = await post('/api/agent/take', { identity: app.identity.id, action: 'backup', path: d.querySelector('[data-path]').value, passphrase: pass,
            with_keys: d.querySelector('[data-keys]').classList.contains('on') })
        d.querySelector('.res').innerHTML = r.ok ? `<span class="c-done">✓ ${tt('已保存 · 在新电脑上恢复后重新登录渠道', 'saved · after restoring on the new computer, log in to channels again')}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
    }
}

function restoreDialog() {
    const d = dialog(`<h5>${tt('恢复', 'Restore')}</h5><p class="note">${tt('恢复要输入口令，在新电脑的终端里运行；之后重新登录渠道，旧电脑上的连接会掉线，再在旧电脑上运行 retire。', 'Restoring asks for the passphrase in a terminal on the new computer; then log in to channels again (the old computer drops off) and run retire on the old one.')}</p>
<pre class="cmd">harness agent restore FILE</pre><div class="row"><span></span><button class="btn">${tt('关闭', 'Close')}</button></div>`)
    d.querySelector('.btn').onclick = closeDialog
}

function retireDialog(app) {
    const d = dialog(`<h5>${tt('在这台电脑上停用', 'Retire on this computer')} · ${esc(app.identity.name)}</h5><p class="note warn">${tt('搬到另一台电脑并在那里恢复之后再做：这台电脑不再运行它，打开时会提示它已搬走。', 'Do this after it was restored on another computer: this computer no longer runs it, and opening it here says it has moved.')}</p>
<div class="row"><span class="res"></span><button class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button class="btn">${tt('停用', 'Retire')}</button></div>`)
    d.querySelector('[data-no]').onclick = closeDialog
    d.querySelector('.btn:not(.quiet)').onclick = async () => {
        const r = await post('/api/agent/take', { identity: app.identity.id, action: 'retire' })
        d.querySelector('.res').innerHTML = r.ok ? `<span class="c-done">✓ ${tt('已停用', 'retired')}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
    }
}

function connectDialog(app, kind) {
    const name = { folder: tt('项目文件夹', 'Project folder'), browser: tt('浏览器', 'Browser'), desktop: tt('桌面', 'Desktop') }[kind]
    const d = dialog(`<h5>${tt('接上', 'Connect')} · ${esc(name)}</h5>${kind === 'folder' ? `<label><span>${tt('文件夹', 'Folder')}</span><input class="field" placeholder="~/code/project"></label>` : ''}
<label><span>${tt('名字', 'Title')}</span><input class="field" data-title value="${esc(name)}"></label><p class="note">${tt('每个环境是列表里的一个对话；那里的事件、反应和动作都记在那个对话里。', 'Each place is a chat in the list; its events, reactions and actions are recorded there.')}</p>
<div class="row"><span class="res"></span><button class="btn">${tt('接上', 'Connect')}</button></div>`)
    d.querySelector('.btn').onclick = async () => {
        const title = d.querySelector('[data-title]').value
        const body = { identity: app.identity.id, action: 'connect', kind, id: `${kind}-${Date.now().toString(36)}`, title, ...(kind === 'folder' ? { folder: d.querySelector('input').value } : {}) }
        const r = await post('/api/agent/places', body)
        d.querySelector('.res').innerHTML = r.ok ? `<span class="c-done">✓ ${tt('已接上', 'connected')}</span>` : `<span class="c-failed">✕ ${esc(r.error)}</span>`
        if (r.ok) { await app.refresh(); setTimeout(() => { closeDialog(); open(app, 'computer') }, 500) }
    }
}

// Add a channel, in the order OpenClaw and Hermes use: identity and policies, log in, groups;
// then binding the owner with a one-time code, shown in the main conversation.
function channelDialog(app) {
    const names = [tt('身份和策略', 'Identity and policy'), tt('扫码', 'Scan'), tt('群', 'Groups')]
    const ids = app.identities
    const d = dialog(`${steps(names, 0)}<h5>${tt('添加渠道 · QQ（OneBot）', 'Add a channel · QQ (OneBot)')}</h5>
<label><span>${tt('归属身份', 'Identity')}</span><select class="field" data-id>${ids.map((i) => `<option value="${esc(i.id)}"${i.id === app.identity.id ? ' selected' : ''}>${esc(i.name)} (${esc(i.id)})</option>`).join('')}</select></label>
<label><span>${tt('陌生人私聊', 'Strangers')}</span><select class="field" data-dm><option value="pairing">${tt('配对', 'pairing')}</option><option value="allowlist">${tt('名单', 'allowlist')}</option><option value="open">${tt('开放', 'open')}</option><option value="off">${tt('关', 'off')}</option></select></label>
<label><span>${tt('群', 'Groups')}</span><select class="field" data-groups><option value="mention">${tt('点名才醒', 'when named')}</option><option value="all">${tt('每条', 'every message')}</option></select></label>
<p class="note">${tt('第一次用到时会安装 OneBot 渠道包。', 'The OneBot channel package installs on first use.')}</p>
<div class="row"><span class="res"></span><button class="btn">${tt('下一步', 'Next')}</button></div>`)
    d.querySelector('.btn').onclick = async () => {
        const body = { action: 'add', kind: 'qq', identity: d.querySelector('[data-id]').value, dm: d.querySelector('[data-dm]').value, groups: d.querySelector('[data-groups]').value }
        d.querySelector('.res').innerHTML = `<span class="spin"></span>`
        const r = await post('/api/agent/channels', body)
        if (!r.ok) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
        scan(app, d, names, body, r.data || {})
    }
}
async function scan(app, d, names, body, state) {
    d.innerHTML = `${steps(names, 1)}<div style="display:flex;gap:16px;align-items:center">${state.qr ? `<img alt="" src="${esc(state.qr)}" style="width:130px;height:130px">` : ''}<p class="note">${tt('用要给它用的 QQ 号扫码登录。建议用单独的号。', 'Scan with the QQ account it will use. A separate account is recommended.')}${state.qr ? '' : ` ${tt('二维码在 OneBot 实现的窗口里', 'The QR code is in the OneBot implementation')}${state.onebot ? ` (${esc(state.onebot)})` : ''}.`}</p></div><div class="row"><span class="res"><span class="spin"></span>${tt('等待扫码…', 'waiting for the scan…')}</span></div>`
    for (let i = 0; i < 300 && $('.pg-layer').contains(d); i++) {
        const s = await get('/api/agent/channels', { identity: body.identity, account: state.account })
        const row = s && (s.channels || []).find((c) => c.account === state.account)
        if (row && row.online && row.groups) return groups(app, d, names, body, row)
        await new Promise((r) => setTimeout(r, 2000))
    }
}
function groups(app, d, names, body, row) {
    d.innerHTML = `${steps(names, 2)}<h5>${tt('进哪些群？', 'Which groups?')}</h5><p class="note">${tt(`这个号在 ${row.groups.length} 个群里，默认一个都不进。每个勾选的群是列表里的一个对话。`, `This account is in ${row.groups.length} groups and joins none by default. Each ticked group becomes a chat in the list.`)}</p>
<div class="checks col">${row.groups.map((g) => `<button class="ck${g.entered ? ' on' : ''}" data-g="${esc(g.id)}">${esc(g.name || g.id)}</button>`).join('')}</div><div class="row"><span class="res"></span><button class="btn">${tt('完成', 'Done')}</button></div>`
    $$('[data-g]', d).forEach((b) => { b.onclick = () => b.classList.toggle('on') })
    d.querySelector('.btn').onclick = async () => {
        const res = d.querySelector('.res'); res.innerHTML = `<span class="spin"></span>`
        const r = await post('/api/agent/channels', { action: 'groups', identity: body.identity, account: row.account, groups: $$('[data-g].on', d).map((b) => b.dataset.g), mode: body.groups })
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
        if (!row.owner) await post('/api/agent/channels', { action: 'owner_code', identity: body.identity, account: row.account })
        closeDialog(); closeSettings(app); app.openChat('main')
    }
}
