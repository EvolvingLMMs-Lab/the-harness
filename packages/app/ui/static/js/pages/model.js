// Settings › Model, after Hermes Desktop's Providers and Model ("Choosing a model", "Settings
// & onboarding") and Claude Code's /model: three things kept apart. The source is whose account
// pays (an agent signed in here: the owner's own plan; a provider's key; this computer). The
// model is one of those the source offers, and every source lists all of its own. The reasoning
// effort is one of the levels the chosen model has, so its choices change with the model.
// The main model takes effect with Apply; the saved models are listed under their sources with
// their switches; adding a source has Test, which makes one real call and says what came of it.
// A switch while the identity is at work is asked about first.
import { esc, tt, modelName } from '../i18n.js'
import { post, failed } from '../api.js'
import { $, $$, on, dialog, closeDialog, press, confirm, said, toast, row, mark, act, empty, problem } from '../ui.js'
import { icon } from '../icons.js'
import { agentNote, agentUsable, signInOffer } from '../onboarding.js'
import * as models from '../models.js'

export const identity = true
let c = null
let found = null, status = null, list = []

const isAgent = models.isAgent
// A model by its own name; its source is the heading it stands under.
const shown = (m) => models.modelLabel(m)
const provider = (id) => ((status && status.providers) || []).find((p) => p.id === id)
const has = (p) => list.some((x) => x.provider === p)
// an entry picked in "more models" before the page was drawn again: the draft the select opens on
let draft = null

export async function draw(ctx) {
    c = ctx
    const [s, got, f] = await Promise.all([ctx.get('/api/app'), ctx.get('/api/app/models'), ctx.get('/api/app/found')])
    if (!got) return problem(failed.get('/api/app/models'), { title: tt('模型列表没有读出来', 'The models could not be read'), retry: 'settings' })
    status = s || {}; list = got.models || []; found = f || { agents: [], keys: [], local: [] }
    const llm = status.llm || {}
    const usable = list.filter((m) => m.enabled !== false)
    const groups = models.bySource(usable)
    const mine = ctx.value('agent.model') || ''
    const option = (m, chosen) => `<option value="${esc(m.id)}"${chosen ? ' selected' : ''}>${esc(shown(m))}</option>`
    // the models under their sources; each source's last row opens every other model it offers
    const grouped = (chosen, more) => groups.map((g) => `<optgroup label="${esc(`${g.source} · ${models.sourceKind(g.models[0], found)}`)}">${g.models.map((m) => option(m, m.id === chosen)).join('')}${more ? `<option value="more:${esc(g.provider)}">${esc(tt(`${g.source} 的其它模型…`, `More models of ${g.source}…`))}</option>` : ''}</optgroup>`).join('')
    const pick = draft && usable.some((m) => m.id === draft) ? draft : llm.id
    const state = llm.ready === false ? mark(tt('还不能用', 'not usable yet'), 'prop') : llm.model ? mark(tt('可用', 'ready'), 'eff') : ''
    const main = `<div class="lg">${tt('主模型', 'Main model')}</div>`
        + (usable.length ? `<div class="apply" data-main>`
            + `<div class="sr"><div><b id="mm-default">${tt('默认模型', 'Default model')}</b><small>${tt('新对话、它自己做的事和后台回看都从它开始；每个身份可以另选自己的。模型列在它的来源下面。', 'What new chats, its own work and reviews in the background start from; an identity may choose its own. A model is listed under the source it comes from.')} ${state}</small></div><div class="ctl"><select aria-labelledby="mm-default" data-default-model data-was="${esc(llm.id || '')}">${llm.id && !usable.some((m) => m.id === llm.id) ? `<option value="" selected>${esc(shown(llm) || tt('没有选', 'none chosen'))}</option>` : ''}${grouped(pick, true)}</select></div></div>`
            + `<div class="sr"><div><b id="mm-effort">${tt('思考强度', 'Reasoning effort')}</b><small data-effort-note></small></div><div class="ctl"><select aria-labelledby="mm-effort" data-default-effort data-was="${esc(ctx.value('model.reasoning_effort') || 'default')}"></select></div></div>`
            + `<div class="sr"><div><b id="mm-own">${tt(`“${ctx.name}”用的模型`, `Model of "${ctx.name}"`)}</b><small>${tt('这个身份自己用哪个；不选就跟默认模型。对话里的选择器只换那一个对话。', "What this identity uses; with nothing chosen it follows the default. The picker in a chat changes that chat only.")}</small></div><div class="ctl"><select aria-labelledby="mm-own" data-own-model data-was="${esc(mine)}"><option value="">${tt('跟默认模型', 'The default model')}</option>${grouped(mine, false)}</select></div></div>`
            + `<div class="applyrow"><span class="res" role="status"></span><button type="button" class="b quiet" data-act="model-reset" hidden>${tt('取消', 'Cancel')}</button><button type="button" class="b pri" data-act="model-apply" disabled>${tt('应用', 'Apply')}</button></div></div>`
            : empty(tt('还没有可用的模型', 'No model is set up yet'), tt('从下面的来源里加一个，或者自己填一个。', 'Add one of the sources below, or enter one yourself.')))
        + ctx.setting('model.max_output_tokens') + ctx.setting('model.checker') + ctx.setting('model.vision')
    // every model that is kept, under its source
    const kind = (m) => mark(models.sourceKind(m, found), isAgent(m) ? 'eff' : 'none')
    const all = models.bySource(list)
    const saved = all.map((g) => `<div class="lg">${esc(g.source)} ${kind(g.models[0])}</div>`
        + g.models.map((m) => row({ title: esc(shown(m)), sub: esc([m.model && m.model !== 'default' ? m.model : '', (m.efforts || []).length ? tt(`思考强度：${m.efforts.map(models.effortLabel).join('、')}`, `effort: ${m.efforts.map(models.effortLabel).join(', ')}`) : tt('思考强度不可调', 'no effort levels')].filter(Boolean).join(' · ')),
            marks: (m.id === llm.id ? mark(tt('默认', 'default'), 'own') : '') + (m.enabled === false ? mark(tt('已停用', 'off'), 'off') : ''),
            actions: act(m.enabled === false ? tt('启用', 'Enable') : tt('停用', 'Disable'), 'model-enable', m.id, { more: `data-on="${m.enabled === false ? 1 : 0}"` })
                + act(tt('移除', 'Remove'), 'model-remove', m.id, { danger: true }) })).join('')
        + `<div class="btns"><button type="button" class="b" data-act="model-more" data-arg="${esc(g.provider)}" data-source="${esc(g.source)}">${icon('plus', 14)}${esc(tt(`${g.source} 的其它模型…`, `More models of ${g.source}…`))}</button></div>`).join('')
        || `<div class="lg">${tt('模型', 'Models')}</div>` + empty(tt('还没有保存任何模型', 'No model is kept yet'))
    const source = (title, sub, p, m, note) => row({ title: esc(title), sub: esc(sub), marks: note || '',
        actions: act(tt('添加…', 'Add…'), 'model-add', '', { more: `data-provider="${esc(p)}" data-model="${esc(m || '')}"` }) })
    const agentMark = (a) => a.installed === false && a.standalone ? mark(tt('选中后安装', 'installs when chosen'), 'none') : a.installed === false ? mark(tt('没装', 'not installed'), 'off') : a.signed_in === true ? mark(tt('已登录', 'signed in'), 'eff') : a.signed_in === false ? mark(tt('没登录', 'not signed in'), 'prop') : ''
    // sources found on this computer with no model in the list yet
    const agents = (found.agents || []).filter((a) => (a.installed !== false || a.standalone) && !has(a.provider)).map((a) => source(a.name, agentNote(a), a.provider, a.model || 'default', agentMark(a)))
    const keys = (found.keys || []).filter((k) => !has(k.provider)).map((k) => source(k.name, k.kept ? tt('key 在凭据文件里', 'its key is in the credentials file') : tt(`key 在环境变量 ${k.key_env} 里；后台开机自启时读不到它，添加后会存进凭据文件`, `its key is in the environment (${k.key_env}); a host started at login does not see that, so adding it keeps the key in the credentials file`), k.provider, k.model, mark('key', 'none')))
    const local = (found.local || []).filter((l) => !has(l.provider)).map((l) => source(l.model, tt('这台电脑上的模型，不用 key', 'a model on this computer, no key needed'), l.provider, l.model, ''))
    const here = [...agents, ...keys, ...local].length ? `<div class="lg">${tt('在这台电脑上找到，还没设好的来源', 'Sources found on this computer, not set up yet')}</div>` + [...agents, ...keys, ...local].join('') : ''
    // the agents people use most that are not on this computer, each with how to get it, and the way to the rest
    const absent = (found.agents || []).filter((a) => a.installed === false && !a.standalone).map((a) => row({ title: esc(a.name), sub: esc(agentNote(a)), marks: agentMark(a), actions: '' }))
    const others = `<div class="lg">${tt('更多来源', 'More sources')}</div>` + absent.join('')
        + row({ title: tt('ACP 公开目录里的其它 agent', 'The other agents of the ACP Registry'), sub: tt('GitHub Copilot、Cursor、Qwen Code、OpenCode 等；在 连接器 › 外部 agent 里添加后会列在上面。', 'GitHub Copilot, Cursor, Qwen Code, OpenCode and others; one added under Connectors › External agents is listed above.'), marks: '',
            actions: act(tt('打开连接器…', 'Open Connectors…'), 'model-connectors', '') })
        + `<div class="btns"><button type="button" class="b" data-act="model-add">${icon('plus', 14)}${tt('添加来源…', 'Add a source…')}</button></div>`
    return `<p>${tt('三样东西分开：来源是谁的账号（这台电脑上已登录的 agent 用你自己的订阅，提供商用 key，或本机模型）；模型是这个来源提供的某一个；思考强度是这个模型自己有的档位。', 'Three things are kept apart: the source is whose account it runs under (an agent signed in on this computer runs under your own plan, a provider under its key, or a model on this computer); the model is one of those that source offers; the reasoning effort is one of the levels that model has.')}</p>` + main + saved + here + others
}

export function wire(ctx, pane) {
    const box = pane.querySelector('[data-main]')
    if (!box) return
    const selects = $$('select', box), apply = box.querySelector('[data-act="model-apply"]'), reset = box.querySelector('[data-act="model-reset"]'), res = box.querySelector('.res')
    const base = box.querySelector('[data-default-model]'), effort = box.querySelector('[data-default-effort]'), note = box.querySelector('[data-effort-note]')
    // the effort's choices are the levels of the model chosen above it
    const levels = () => {
        const m = list.find((x) => x.id === base.value) || {}, has = (m.efforts || []).length > 0
        const keep = has && m.efforts.includes(effort.value || effort.dataset.was) ? (effort.value || effort.dataset.was) : 'default'
        effort.innerHTML = ['default', ...(m.efforts || [])].map((e) => `<option value="${esc(e)}"${e === keep ? ' selected' : ''}>${esc(models.effortLabel(e))}</option>`).join('')
        effort.disabled = !has
        note.textContent = !m.id ? '' : has ? tt(`${shown(m)} 有这几档；每次回答前想多深：越深越慢、越贵。`, `The levels ${shown(m)} has: how hard it thinks before each answer; deeper is slower and costs more.`) : tt(`${shown(m)} 没有可调的档位。`, `${shown(m)} has no levels to choose.`)
    }
    const drafted = () => {
        const changed = selects.some((x) => x.value !== x.dataset.was)
        apply.disabled = !changed; reset.hidden = !changed
        res.textContent = changed ? tt('还没应用', 'Not applied yet') : ''
    }
    let before = base.value
    for (const s of selects) s.onchange = () => {
        if (s === base && base.value.startsWith('more:')) {
            // every other model of that source: the one picked is kept in the list and becomes the draft
            const p = base.value.slice(5), g = models.bySource(list).find((x) => x.provider === p)
            base.value = before
            return models.more(p, g ? g.source : p, { then: (kept) => { draft = kept.id; c.reload() } })
        }
        if (s === base) { before = base.value; levels() }
        drafted()
    }
    levels()
    // a model picked in "more models" a moment ago is the draft
    if (draft) { draft = null; drafted() }
}

async function apply() {
    const box = $('.pg-settings [data-main]'), res = box.querySelector('.res')
    const base = box.querySelector('[data-default-model]'), own = box.querySelector('[data-own-model]')
    const busy = ((await c.get('/api/agent/life', { identity: c.id })) || {}).busy || []
    if (busy.length) {
        const go = await confirm({ title: tt('它正在做事，现在换模型？', 'It is at work. Switch the model now?'),
            text: tt(`${busy.length} 个对话里的回合正在进行；它们从下一次调用模型起用新模型，整个对话会被重新读一遍。`, `A turn is running in ${busy.length} chat${busy.length === 1 ? '' : 's'}; from their next model call they use the new model, which reads each conversation again.`),
            yes: tt('仍然切换', 'Switch anyway'), no: tt('保留现在的模型', 'Keep current model') })
        if (!go) return
    }
    if (base.value !== base.dataset.was) {
        const m = list.find((x) => x.id === base.value)
        res.innerHTML = `<span class="spin"></span>${tt('先问它一个词…', 'asking it for one word first…')}`
        const r = await post('/api/app/onboard', { provider: m.provider, model: m.model, base_url: m.base_url || null })
        if (!(r.ok && r.data && r.data.ok)) {
            const why = (r.data && (r.data.detail || r.data.error)) || r.error || tt('它没有回答', 'it did not answer')
            res.innerHTML = `<span class="c-failed">✕ ${esc(why)}</span><small class="fix">${esc((r.data && r.data.fix) || r.fix || '')}</small>`
            return
        }
    }
    if (own.value !== own.dataset.was) {
        const r = await c.save('agent.model', own.value)
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span><small class="fix">${esc(r.fix || '')}</small>`; return }
    }
    const effort = box.querySelector('[data-default-effort]')
    if (effort.value !== effort.dataset.was) {
        const r = await c.save('model.reasoning_effort', effort.value)
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span><small class="fix">${esc(r.fix || '')}</small>`; return }
    }
    toast(tt('已应用', 'Applied'))
    await c.app.modelHint()
    return c.reload()
}

// Add a source: what it is, Test (one real call), Apply (it becomes the default model).
async function add(given = {}) {
    const providers = (status.providers || [])
    const agents = (found.agents || []).filter((a) => a.installed !== false || a.standalone)
    const d = dialog(`<h5>${tt('添加来源', 'Add a source')}</h5>
<label><span>${tt('来源', 'Source')}</span><select class="field" data-p>${agents.length ? `<optgroup label="${tt('这台电脑上已登录的 agent', 'Agents signed in on this computer')}">${agents.map((a) => `<option value="${esc(a.provider)}">${esc(a.name)}</option>`).join('')}</optgroup>` : ''}<optgroup label="${tt('提供商（用 key）', 'Providers (with a key)')}">${providers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</optgroup></select></label>
<label><span>${tt('模型', 'Model')}</span><input class="field" data-m list="model-ids" autocomplete="off" spellcheck="false"><datalist id="model-ids"></datalist></label>
<label data-url-row><span>${tt('接口地址', 'Base URL')}</span><input class="field" data-u placeholder="http://…/v1" spellcheck="false"></label>
<label data-key-row><span>key</span><input class="field" data-k type="password" autocomplete="off"></label>
<p class="note" data-note></p>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn quiet" data-test>${tt('测试', 'Test')}</button><button type="button" class="btn" data-default>${tt('应用', 'Apply')}</button></div>`)
    const p = d.querySelector('[data-p]'), m = d.querySelector('[data-m]'), u = d.querySelector('[data-u]'), k = d.querySelector('[data-k]'), res = d.querySelector('.res'), note = d.querySelector('[data-note]')
    const fit = async () => {
        const agent = p.value.startsWith('acp:'), spec = provider(p.value) || {}
        d.querySelector('[data-url-row]').hidden = agent || (!!spec.base_url && p.value !== 'ollama') || p.value === 'openrouter'
        d.querySelector('[data-key-row]').hidden = agent || !spec.key_env
        const kept = (found.keys || []).find((x) => x.provider === p.value)
        k.placeholder = kept ? tt(`已经有一个（${kept.kept ? '凭据文件' : kept.key_env}）；留空就用它`, `one is known already (${kept.kept ? 'the credentials file' : kept.key_env}); leave empty to use it`) : (spec.key_env ? tt('存进这台电脑的凭据文件', "kept in this computer's credentials file") : '')
        u.placeholder = spec.base_url || 'http://…/v1'
        note.textContent = agent ? tt('走这个工具自己的登录：不读取、不保存你的订阅凭据。它不能指定的事（比如具体模型或思考强度）以它声明的为准。', "It runs under this tool's own sign-in: your plan's credentials are neither read nor kept. What it cannot be told (a particular model, an effort) is as it declares.")
            : spec.note || ''
        res.innerHTML = ''
        // what a provider offers, to pick from; an agent says its own models once it is connected
        const asked = p.value
        const got = agent ? null : await c.get('/api/app/models/catalog', { provider: asked })
        if (d.isConnected && got && p.value === asked) d.querySelector('datalist').innerHTML = (got.models || []).slice(0, 400).map((x) => `<option value="${esc(x.id)}">${esc(x.name || '')}</option>`).join('')
    }
    if (given.provider && [...p.options].some((o) => o.value === given.provider)) p.value = given.provider
    m.value = given.model && given.model !== 'default' ? given.model : p.value.startsWith('acp:') ? 'default' : ''
    p.onchange = () => { m.value = p.value.startsWith('acp:') ? 'default' : ''; fit() }
    fit()
    const body = () => ({ provider: p.value, model: m.value.trim() || (p.value.startsWith('acp:') ? 'default' : ''), base_url: u.value.trim() || null, ...(k.value ? { key: k.value } : {}) })
    const answer = (r, kept, again) => {
        const ok = r.ok && r.data && r.data.ok !== false
        if (ok) res.innerHTML = `<span class="c-done">✓ ${tt(`它回答了${r.data.seconds !== undefined ? ` · ${r.data.seconds} 秒` : ''}${kept ? ' · 已设为默认' : ''}`, `it answered${r.data.seconds !== undefined ? ` · ${r.data.seconds} s` : ''}${kept ? ' · it is the default now' : ''}`)}</span>`
        else res.innerHTML = `<span class="c-failed">✕ ${esc((r.data && (r.data.detail || r.data.error)) || r.error || tt('它没有回答', 'it did not answer'))}</span><small class="fix">${esc((r.data && r.data.fix) || r.fix || '')}</small>`
        // not signed in, and it can be signed in to from here: its own ways, then the same step again
        if (!ok) signInOffer(res, p.value, r.data && r.data.sign_in, again)
        return ok
    }
    const missing = () => { if (body().model) return false; res.innerHTML = `<span class="c-failed">✕ ${tt('先填模型的 id。', 'Give the model id first.')}</span>`; m.focus(); return true }
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-test]'), async () => {
        if (missing()) return
        res.innerHTML = `<span class="spin"></span>${tt('正在试一次调用…', 'making one call…')}`
        answer(await post('/api/app/model/test', body()), false, () => d.querySelector('[data-test]').click()) // one real call; nothing is kept
    })
    press(d.querySelector('[data-default]'), async () => {
        if (missing()) return
        res.innerHTML = `<span class="spin"></span>${tt('先问它一个词，答得出来才保存…', 'asking it for one word; it is kept only when it answers…')}`
        if (!answer(await post('/api/app/onboard', body()), true, () => d.querySelector('[data-default]').click())) return
        await c.app.modelHint()
        setTimeout(() => { if (d.isConnected) closeDialog(); c.reload() }, 700)
    })
}

export function actions() {
    on('model-apply', apply)
    on('model-reset', () => c.reload())
    on('model-connectors', () => c.app.openSettings('connectors'))
    on('model-more', (n) => models.more(n.dataset.arg, n.dataset.source, { then: () => c.reload() }))
    on('model-add', (n) => add({ provider: n.dataset.provider, model: n.dataset.model }))
    on('model-enable', async (n) => {
        const r = await post('/api/app/models', { action: 'enable', id: n.dataset.arg, enabled: n.dataset.on === '1' })
        if (!r.ok) return said(r)
        await c.app.modelHint(); return c.reload()
    })
    on('model-remove', async (n) => {
        const m = list.find((x) => x.id === n.dataset.arg)
        if (!(await confirm({ title: tt(`从列表里移除“${shown(m)}”？`, `Remove "${shown(m)}" from the list?`), text: tt('用着它的对话回到默认模型。它的 key 留在凭据文件里。', 'Chats that use it go back to the default model. Its key stays in the credentials file.'), yes: tt('移除', 'Remove'), danger: true }))) return
        const r = await post('/api/app/models', { action: 'remove', id: n.dataset.arg })
        if (!r.ok) return said(r)
        await c.app.modelHint(); return c.reload()
    })
}
export const addModel = add
