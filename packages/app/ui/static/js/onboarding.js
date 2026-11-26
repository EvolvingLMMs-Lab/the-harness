// The first run, the same steps as in a terminal (the host's onboarding: /api/app/found,
// /api/app/onboard, /api/app/onboarded), laid over the window as Hermes Desktop's first run
// is: a few seconds to the first message, and "choose later" to look around first. Step one
// lists what can be the model: an agent signed in here (Claude Code, Codex, Gemini CLI, Grok:
// it runs under the owner's own plan, no key; one that is not on this computer is listed with
// how to get it, and the rest of the ACP Registry is one row further), a provider's key found
// here, a local model, or a key typed now. The one chosen is asked for one word and kept only
// when it answers. Step
// two says it stays on and opens the chat, where it asks for its own name and manner. "Later"
// leaves it for now; the composer then says that a model is still to be chosen.
import { esc, tt, modelName } from './i18n.js'
import { get, post } from './api.js'
import { $$, dialog, closeDialog, refocus, press, steps } from './ui.js'
import * as models from './models.js'

const NAMES = () => [tt('来源和模型', 'Source and model'), tt('开始', 'Start')]
const WAIT = (ms) => new Promise((done) => setTimeout(done, ms))
const KIND = { hermes: 'Hermes', openclaw: 'OpenClaw' }
const PLAN_ZH = { 'your Claude plan': '你的 Claude 订阅', 'your ChatGPT plan': '你的 ChatGPT 订阅', 'your Google account': '你的 Google 账号', 'your Grok plan': '你的 Grok 订阅' }
const SIGN_ZH = { 'acp:claude-acp': '运行 claude 并登录（/login）', 'acp:codex-acp': '运行 codex login', 'acp:gemini': '运行 gemini 并用 Google 账号登录', 'acp:grok-build': '运行 grok 并登录' }

// An agent as a source of the model: whether it can be tried as it is, and what is said of it
// (signed in and under whose plan, or how to sign in, or how to get it).
// (one that needs no command line here installs its adapter when chosen, and is signed in to through it)
export const agentUsable = (a) => (a.installed !== false ? a.signed_in !== false : !!a.standalone)
export function agentNote(a) {
    const zh = SIGN_ZH[a.provider] || a.sign_in
    if (a.installed === false && a.standalone) return tt(`选中后自动装好，然后在这里登录 · 用${PLAN_ZH[a.plan] || '它自己的登录'}，不用 key`, `installs when you choose it, then you sign in here · uses ${a.plan || 'its own sign-in'}, no key needed`)
    if (a.installed === false) return tt(`没装 · ${a.install}，然后${zh}`, `not installed · ${a.install}, then ${a.sign_in}`)
    if (a.signed_in === false) return tt(`还没登录 · ${zh}`, `not signed in · ${a.sign_in}`)
    const plan = tt(`用${PLAN_ZH[a.plan] || '它自己的登录'}，不用 key`, `uses ${a.plan || 'its own sign-in'}, no key needed`)
    return a.signed_in === true ? tt(`已登录 · ${plan}`, `signed in · ${plan}`) : tt(`已安装 · ${plan}`, `installed · ${plan}`)
}

// An agent answered "not signed in" and offers to be signed in to through it (the answer's
// `sign_in`: [{id, name, description}], as Zed shows an agent's authentication methods): a
// button for each way under the failure. The agent opens a page in the browser; when its user
// is through, `again` tries the source once more.
export function signInOffer(holder, provider, ways, again) {
    if (!ways || !ways.length) return
    const box = document.createElement('div')
    box.className = 'signin'
    box.innerHTML = `<span>${tt('在这里登录：', 'Sign in here:')}</span>` + ways.map((w, i) => `<button type="button" class="btn quiet" data-way="${i}" title="${esc(w.description || '')}">${esc(w.name)}</button>`).join('') + `<small role="status"></small>`
    holder.append(box)
    const said = box.querySelector('small')
    box.querySelectorAll('[data-way]').forEach((b) => { b.onclick = async () => {
        box.querySelectorAll('button').forEach((x) => { x.disabled = true })
        said.innerHTML = `<span class="spin"></span>${tt('它会打开一个登录页面：在那里完成登录，这里会接着试…', 'It opens a sign-in page: finish there, and this goes on by itself…')}`
        const r = await post('/api/app/acp', { action: 'sign_in', id: provider, method: ways[Number(b.dataset.way)].id })
        if (!r.ok) { box.querySelectorAll('button').forEach((x) => { x.disabled = false }); said.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('没登录上', 'the sign-in did not go through'))}</span>${r.fix ? ` ${esc(r.fix)}` : ''}`; return }
        said.innerHTML = `<span class="c-done">✓ ${tt('已登录', 'signed in')}</span>`
        again()
    } })
}

// What the host found; asked again for a few seconds while it does not answer yet (a host
// that is still starting must not look like "nothing to set up").
export async function found() {
    for (let i = 0; i < 12; i++) {
        const f = await get('/api/app/found')
        if (f) return f
        await WAIT(500)
    }
    return null
}

export async function needed() {
    const f = await found()
    return !!f && !!f.needed
}

function options(f) {
    const agent = (a) => ({ provider: a.provider, model: a.model || 'default', name: a.name, title: a.name, note: agentNote(a) })
    const ready = (f.agents || []).filter(agentUsable).map(agent), rest = (f.agents || []).filter((a) => !agentUsable(a)).map(agent)
    const keys = (f.keys || []).map((k) => ({
        provider: k.provider, model: k.model || '', ask: !k.model, title: `${k.name}${k.model ? ' · ' + modelName(k.model) : ''}`,
        note: k.kept ? tt('凭据文件里有 key', 'key in the credentials file') : tt(`在环境变量里找到了 key（${k.key_env}）`, `key found in the environment (${k.key_env})`),
    }))
    const local = (f.local || []).slice(0, 3).map((m) => ({ provider: m.provider, model: m.model, title: `${tt('本机', 'This computer')} · ${m.model}`, note: tt('本机上的模型，不用 key', 'a model on this computer, no key needed') }))
    // what can be tried as it is comes first; then the agents that are not here or not signed in, each with how to get it
    const usable = ready.length + keys.length + local.length
    const all = [...ready, ...keys, ...local, ...rest,
        { more: true, title: tt('更多 agent…', 'More agents…'), note: tt('GitHub Copilot、Cursor、Qwen Code、OpenCode 等，来自 ACP 的公开目录', 'GitHub Copilot, Cursor, Qwen Code, OpenCode and the others of the ACP Registry') },
        { fresh: true, title: tt('填一个 key…', 'Enter a key…'), note: tt('OpenRouter、OpenAI、Anthropic、Gemini 等，或你自己的接口', 'OpenRouter, OpenAI, Anthropic, Gemini and others, or an endpoint of your own') }]
    return { all, start: usable ? 0 : all.length - 1 }
}

export async function modelDialog(app, { first = false, after } = {}) {
    const f = (await found()) || { agents: [], keys: [], local: [], elsewhere: [], providers: [] }
    const providers = f.providers || []
    const { all: opts, start } = options(f)
    const question = tt('它的模型从哪里来？', 'Where does its model come from?')
    const d = dialog(`${first ? steps(NAMES(), 0) : ''}<h5>${first ? tt('欢迎使用 The Harness', 'Welcome to The Harness') : question}</h5>
${first ? `<p class="say">${tt('先选模型的来源：你的订阅、一个 key，或这台电脑上的模型。选中的那个会被问一个词，答得出来才保存；然后选用它的哪个模型。', 'First choose where its model comes from: a plan of yours, a key, or a model on this computer. The one you choose is asked for one word and kept only when it answers; then you choose which of its models.')}</p>` : ''}
<div role="radiogroup" aria-label="${esc(question)}">${opts.map((o, i) => `<button type="button" class="opt${i === start ? ' on' : ''}" role="radio" aria-checked="${i === start}" tabindex="${i === start ? 0 : -1}"${i === start ? ' autofocus' : ''} data-i="${i}"><b>${esc(o.title)}</b>${o.note ? `<small>${esc(o.note)}</small>` : ''}</button>`).join('')}</div>
<div class="opt-extra"></div>
<div class="kept" hidden></div>
<p class="note">${tt('这台电脑上已登录的 agent 用你自己的订阅，不用 key。', 'An agent signed in on this computer runs under your own plan, without a key.')}</p>
${first && (f.elsewhere || []).length ? `<button type="button" class="imp" data-import>${tt(`在本机发现一个 ${KIND[f.elsewhere[0]] || f.elsewhere[0]} 身份 · 把它接过来`, `A ${KIND[f.elsewhere[0]] || f.elsewhere[0]} agent is on this computer · bring it over`)}</button>` : ''}
<div class="row"><span class="res" role="status"></span>${first ? `<button type="button" class="btn quiet" data-later>${tt('稍后再选模型', 'Choose a model later')}</button>` : `<button type="button" class="btn quiet" data-cancel>${tt('取消', 'Cancel')}</button>`}<button type="button" class="btn" data-try data-default>${tt('试一下', 'Try it')}</button></div>`)
    let chosen = start, directory = null
    const extra = d.querySelector('.opt-extra')
    const btn = d.querySelector('[data-try]'), res = d.querySelector('.res'), later = d.querySelector('[data-later]'), cancel = d.querySelector('[data-cancel]')
    const keptBox = d.querySelector('.kept')
    const reset = () => { delete btn.dataset.next; btn.textContent = tt('试一下', 'Try it'); res.innerHTML = ''; keptBox.hidden = true; keptBox.innerHTML = ''; d.classList.remove('is-kept') }
    // The source answered and one of its models is kept: which model, and how hard it thinks.
    // The source is the heading; the model and the effort are choices under it, as everywhere.
    const kept = async (entry) => {
        const source = entry.source || models.sourceLabel(entry), agent = models.isAgent(entry)
        const effortRow = (m) => ((m.efforts || []).length ? `<label><span>${tt('思考强度', 'Reasoning effort')}</span><select data-ke aria-label="${tt('思考强度', 'Reasoning effort')}">${['default', ...m.efforts].map((e) => `<option value="${e === 'default' ? '' : esc(e)}">${esc(models.effortLabel(e))}</option>`).join('')}</select></label>` : `<label><span>${tt('思考强度', 'Reasoning effort')}</span><small>${tt('这个模型没有可调的档位', 'this model has no levels to choose')}</small></label>`)
        const drawKept = (m, list) => {
            keptBox.hidden = false
            d.classList.add('is-kept')
            keptBox.innerHTML = `<div class="kh"><span>${tt(`来源：${source}`, `Source: ${source}`)}</span><button type="button" data-other>${tt('换一个来源', 'Another source')}</button></div>
<label><span>${tt('模型', 'Model')}</span>${list ? `<select data-km aria-label="${tt('模型', 'Model')}">${list.map((x) => `<option value="${esc(x.id)}"${x.id === m.model ? ' selected' : ''}>${esc(x.name || x.id)}${x.description ? ` — ${esc(x.description)}` : ''}</option>`).join('')}</select>` : `<b>${esc(models.modelLabel(m))}</b>`}</label>
${effortRow(m)}
<small>${tt('以后在输入框旁边或 设置 › 模型 里都能换。', 'Both can be changed later beside the composer or in Settings › Model.')}</small>`
            const km = keptBox.querySelector('[data-km]'), ke = keptBox.querySelector('[data-ke]')
            keptBox.querySelector('[data-other]').onclick = () => { reset(); radios[chosen].focus() }
            if (ke) ke.onchange = () => post('/api/app/settings', { model: { reasoning_effort: ke.value || 'default' } })
            if (km) km.onchange = async () => {
                // another model of the same source: asked for one word too, then it is the default
                const was = m.model
                km.disabled = true
                res.innerHTML = `<span class="spin"></span>${tt('换成它，先问它一个词…', 'switching: asking it for one word first…')}`
                const r = await post('/api/app/onboard', { provider: m.provider, model: km.value })
                if (r.ok && r.data && r.data.ok) {
                    res.innerHTML = `<span class="c-done">✓ ${tt(`${models.modelLabel(r.data)} 通了 · ${r.data.seconds} 秒 · 已保存`, `${models.modelLabel(r.data)} answered · ${r.data.seconds} s · saved`)}</span>`
                    await post('/api/app/settings', { model: { reasoning_effort: 'default' } })
                    drawKept(r.data, list)
                } else {
                    km.value = was; km.disabled = false
                    res.innerHTML = `<span class="c-failed">✕ ${esc((r.data && (r.data.detail || r.data.error)) || r.error || tt('没通', 'it did not answer'))}</span>${(r.data && r.data.fix) || r.fix ? `<small class="fix">${esc((r.data && r.data.fix) || r.fix)}</small>` : ''}`
                }
            }
        }
        drawKept(entry, null)
        if (!agent) return
        // an agent declares a handful of models: the one it is set to was kept; the others are a choice away
        const got = await models.offered(entry.provider)
        if (d.isConnected && got && (got.models || []).length > 1 && keptBox.querySelector('b')) drawKept(entry, got.models)
    }
    const showExtra = () => {
        const o = opts[chosen]
        extra.innerHTML = o.fresh ? `<div class="opt on"><select data-p aria-label="${tt('提供商', 'Provider')}">${providers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select><input data-m aria-label="${tt('模型 id', 'model id')}" placeholder="${tt('模型 id', 'model id')}" value="deepseek/deepseek-v4.1-flash"><input data-u aria-label="${tt('接口地址', 'base URL of the endpoint')}" placeholder="${tt('接口地址（http…）', 'base URL of the endpoint (http…)')}" hidden><input data-k type="password" autocomplete="off" aria-label="key" placeholder="${tt('key（本机模型不用填）', 'key (none for a local model)')}"></div>`
            : o.ask ? `<div class="opt on"><input data-m aria-label="${tt('模型 id', 'model id')}" placeholder="${tt('模型 id', 'model id')}" value=""></div>`
                : o.more ? `<div class="opt on"><select data-a aria-label="${tt('ACP 目录里的 agent', 'An agent of the ACP Registry')}"><option value="">${tt('正在读取目录…', 'reading the registry…')}</option></select><small>${tt('选中的那个，它的适配器会为 The Harness 装好；它用自己的登录回答。', 'The adapter of the one you choose is installed for The Harness; it answers under its own sign-in.')}</small></div>` : ''
        if (o.more) fill()
        const pick = extra.querySelector('[data-p]')
        if (pick) pick.onchange = () => {
            const p = providers.find((x) => x.id === pick.value) || {}
            extra.querySelector('[data-u]').hidden = !!p.base_url || p.id === 'openrouter'
            extra.querySelector('[data-m]').value = p.id === 'openrouter' ? 'deepseek/deepseek-v4.1-flash' : ''
            reset()
        }
    }
    // the rest of the ACP Registry, read once (it takes the network the first time)
    const fill = async () => {
        if (!directory) directory = get('/api/app/acp', { registry: 1 }).then((got) => got && (got.agents || []).filter((a) => a.state === 'available' && a.runs_here !== false && !(f.agents || []).some((x) => x.provider === a.id)))
        const rows = await directory, pick = extra.querySelector('[data-a]')
        if (!pick) return
        if (!rows) { directory = null; pick.innerHTML = `<option value="">${tt('目录没有读出来；再选一次这一项重试', 'the registry could not be read; choose this row again to retry')}</option>`; return }
        pick.innerHTML = `<option value="">${tt('选一个 agent', 'Choose an agent')}</option>` + rows.map((a) => `<option value="${esc(a.id)}">${esc(a.name || a.id)}</option>`).join('')
        pick.onchange = reset
    }
    // one of them is chosen, as radio buttons are: a click or the arrow keys move the choice
    const radios = $$('.opt[data-i]', d)
    const choose = (i, focus = false) => {
        chosen = i
        radios.forEach((x, n) => { x.classList.toggle('on', n === i); x.setAttribute('aria-checked', n === i); x.tabIndex = n === i ? 0 : -1 })
        if (focus) radios[i].focus()
        showExtra(); reset()
    }
    radios.forEach((b, i) => {
        b.onclick = () => choose(i)
        b.onkeydown = (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); choose((i + 1) % radios.length, true) }
            else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); choose((i - 1 + radios.length) % radios.length, true) }
            else if (e.key === 'Enter') { e.preventDefault(); btn.click() } // Enter tries the chosen one
        }
    })
    showExtra()
    refocus(d)
    if (d.querySelector('[data-import]')) d.querySelector('[data-import]').onclick = () => importDialog(app)
    if (later) later.onclick = () => { closeDialog(); if (app.modelHint) app.modelHint() }
    if (cancel) cancel.onclick = closeDialog
    press(btn, async () => {
        if (btn.dataset.next) { if (first) return ready(app, d, f); closeDialog(); if (app.modelHint) app.modelHint(); return after && after() }
        const o = opts[chosen]
        const body = { provider: o.provider, model: o.model, ...(o.name ? { name: o.name } : {}) }
        if (o.more) {
            const pick = d.querySelector('[data-a]')
            if (!pick || !pick.value) { res.innerHTML = `<span class="c-failed">✕ ${tt('先从目录里选一个 agent。', 'Choose an agent of the registry first.')}</span>`; return }
            body.provider = pick.value; body.model = 'default'; body.name = pick.selectedOptions[0].textContent
        } else if (o.fresh) {
            body.provider = d.querySelector('[data-p]').value; body.model = d.querySelector('[data-m]').value
            body.key = d.querySelector('[data-k]').value; body.base_url = d.querySelector('[data-u]').value || null
        } else if (o.ask) body.model = d.querySelector('[data-m]').value || o.model
        res.innerHTML = `<span class="spin"></span>${tt('正在试一次调用…', 'making one call…')}`
        const r = await post('/api/app/onboard', body)
        if (r.ok && r.data && r.data.ok) {
            res.innerHTML = `<span class="c-done">✓ ${tt(`${r.data.source || ''} 通了 · ${r.data.seconds} 秒 · 已保存`, `${r.data.source || 'it'} answered · ${r.data.seconds} s · saved`)}</span>`
            btn.textContent = tt('继续', 'Continue'); btn.dataset.next = '1'
            btn.focus()
            kept(r.data)
        } else {
            const why = (r.data && (r.data.detail || r.data.error)) || r.error || tt('没通', 'it did not answer')
            const fix = (r.data && r.data.fix) || r.fix || ''
            res.innerHTML = `<span class="c-failed">✕ ${esc(why)}</span>${fix ? `<small class="fix">${esc(fix)}</small>` : ''}`
            // not signed in, and it can be signed in to from here: its own ways, then tried again
            signInOffer(res, body.provider, r.data && r.data.sign_in, () => btn.click())
        }
    })
    return d
}

export const STARTERS = () => [tt('你能在这台电脑上做什么？', 'What can you do on this computer?'), tt('看看这个文件夹里有什么', 'Look at this folder and tell me what is in it'), tt('每天早上给我一个当天的摘要', 'Give me a summary of the day every morning')]

function ready(app, d, f) {
    // Whether it starts at login is the system's login item: the installer asked already,
    // so only a page opened without the desktop app (harness app) asks here, on by default.
    const ask = f.background === false && !window.__TAURI_INTERNALS__
    d.innerHTML = `${steps(NAMES(), 1)}<h5 id="dlg-title">${tt('准备好了', 'Ready')}</h5>
<p class="note">${ask ? tt('它可以一直在：关掉窗口照常工作，开机后接着做。', 'It can stay on: it goes on working with the window closed, and after the computer starts.')
        : tt('它会一直在：关掉窗口照常工作，开机后接着做；设置的"通用"里能改。', 'It stays on: it goes on working with the window closed and after the computer starts; Settings › General changes it.')}</p>
${ask ? `<label class="check"><input type="checkbox" data-bg checked><span>${tt('开机后继续工作', 'Keep working after the computer starts')}</span></label>` : ''}
<p class="note">${tt('第一次聊天时它会问你怎么称呼它。直接说要做的事就行，比如：', 'In the first chat it asks what to call it. Just say what you want done, for example:')}</p>
<div class="starters">${STARTERS().map((s) => `<button type="button" class="opt" data-say="${esc(s)}">${esc(s)}</button>`).join('')}</div>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn" data-default>${tt('开始聊天', 'Start chatting')}</button></div>`
    const finish = async (text) => {
        const box = d.querySelector('[data-bg]')
        await post('/api/app/onboarded', box ? { background: box.checked } : {})
        closeDialog(); if (app.modelHint) app.modelHint()
        await app.openChat('main')
        if (text && app.say) app.say(text)
        else if (app.focusComposer) app.focusComposer()
    }
    press(d.querySelector('.btn'), () => finish(''))
    $$('[data-say]', d).forEach((b) => press(b, () => finish(b.dataset.say)))
    refocus(d)
}

// Bringing an OpenClaw or Hermes agent over, or adopting a shared one (a link, a file or a
// character card): persona, memory and skills come; channel tokens and keys never do.
export async function importDialog(app) {
    const here = ((await get('/api/app/elsewhere')) || {}).found || []
    const d = dialog(`<h5>${tt('从 OpenClaw 或 Hermes 导入', 'Import from OpenClaw or Hermes')}</h5><p class="note">${tt('带过来人设、记忆和技能，不带渠道 token，免得一个 token 同时被两个 agent 用；导入后建议停掉原来的 agent。技能回到"提议"，要在这里自测通过；反应先停用。',
        'Brings persona, memory and skills but not channel tokens, so one token is never used by two agents at once; afterwards stop the original agent. Skills go back to "proposed" and must pass their own test here; reactions start disabled.')}</p>
${here.map((f) => `<button type="button" class="opt" data-kind="${esc(f.kind)}"><b>${esc(KIND[f.kind] || f.kind)}</b><small>${esc(f.folder)}</small></button>`).join('') || `<p class="note">${tt('这台电脑上没有找到 OpenClaw 或 Hermes。', 'No OpenClaw or Hermes agent on this computer.')}</p>`}
<label><span>${tt('或者领养', 'Or adopt')}</span><input class="field" placeholder="${tt('分享链接、文件或角色卡', 'a share link, a file or a character card')}"></label>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('关闭', 'Close')}</button><button type="button" class="btn" data-default>${tt('导入', 'Import')}</button></div>`)
    let kind = here.length ? here[0].kind : null
    $$('[data-kind]', d).forEach((b, i) => { b.classList.toggle('on', i === 0); b.onclick = () => { kind = b.dataset.kind; $$('[data-kind]', d).forEach((x) => x.classList.toggle('on', x === b)) } })
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const source = d.querySelector('input').value.trim(), res = d.querySelector('.res')
        res.innerHTML = '<span class="spin"></span>'
        const r = source ? await post('/api/agent/take', { action: 'adopt', source }) : kind ? await post('/api/app/elsewhere', { kind }) : { ok: false, error: tt('选一个，或填一个来源', 'choose one, or give a source') }
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        const made = r.data.identity || r.data.id
        res.innerHTML = `<span class="c-done">✓ ${tt('新身份', 'new identity')} ${esc(made || '')}</span>`
        if (app && app.refresh) app.refresh()
    })
}

export async function start(app) {
    if (await needed()) await modelDialog(app, { first: true })
    else if (app.modelHint) app.modelHint()
}
