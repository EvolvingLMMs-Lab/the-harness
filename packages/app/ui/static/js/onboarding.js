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

const NAMES = () => [tt('模型', 'Model'), tt('身份', 'Identity'), tt('偏好', 'Preferences'), tt('开始', 'Start')]
const SOUL_PRESETS = () => [
    [tt('简洁高效', 'Concise & direct'), tt('回答直接清晰，少说废话，直接给结论与可执行方案。', 'Be direct, concise, and action-oriented; lead with clear answers.')],
    [tt('严谨工程师', 'Rigorous engineer'), tt('注重代码质量、边界条件与测试验证，修改前先理清根因。', 'Prioritize code quality, edge cases, root-cause analysis, and verification.')],
    [tt('研究分析', 'Research & analysis'), tt('善于系统调研、对比权衡并给出有据可查的结论。', 'Investigate systematically, weigh trade-offs, and back conclusions with evidence.')],
    [tt('温暖伙伴', 'Warm & thoughtful'), tt('语气友好自然，主动关注细节并体贴地协助推进工作。', 'Be warm, approachable, and proactively attentive to context and details.')],
]
const WAIT = (ms) => new Promise((done) => setTimeout(done, ms))
const KIND = { hermes: 'Hermes', openclaw: 'OpenClaw' }

// An agent as a source of the model: whether it can be tried as it is, and what is said of it
// (signed in and under whose plan, or how to sign in, or how to get it).
// (one that needs no command line here installs its adapter when chosen, and is signed in to through it)
export const agentUsable = (a) => (a.installed !== false ? a.signed_in !== false : !!a.standalone)
export function agentNote(a) {
    // its state, and nothing else: what to do about it is said when it is chosen and fails
    if (a.installed === false) return a.standalone ? tt('可安装', 'can be installed') : tt('未安装', 'not installed')
    if (a.signed_in === false) return tt('未登录', 'not signed in')
    return a.signed_in === true ? tt('已登录', 'signed in') : tt('已安装', 'installed')
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
        said.innerHTML = `<span class="spin"></span>${tt('在打开的页面里完成登录…', 'Finish signing in on the page it opens…')}`
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
    const agent = (a) => {
        const meta = models.providerDisplay(a.provider, a.name)
        return { provider: a.provider, model: a.model || 'default', name: a.name, title: meta.title, note: agentNote(a) }
    }
    const ready = (f.agents || []).filter(agentUsable).map(agent), rest = (f.agents || []).filter((a) => !agentUsable(a)).map(agent)
    const keys = (f.keys || []).map((k) => {
        const meta = models.providerDisplay(k.provider, k.name)
        return {
            provider: k.provider, model: k.model || '', ask: !k.model, title: `${meta.vendor}${k.model ? ' · ' + modelName(k.model) : ''}`,
            note: k.kept ? 'API Key' : `API Key · ${k.key_env}`,
        }
    })
    const local = (f.local || []).slice(0, 3).map((m) => ({ provider: m.provider, model: m.model, title: `Ollama · ${m.model}`, note: tt('本地', 'Local') }))
    // what can be tried as it is comes first; then the agents that are not here or not signed in, each with how to get it
    const usable = ready.length + keys.length + local.length
    const all = [...ready, ...keys, ...local, ...rest,
        { more: true, title: tt('更多 ACP 代理…', 'More ACP agents…'), note: '' },
        { fresh: true, title: tt('使用 API Key / 自定义接口…', 'Use API Key / Custom endpoint…'), note: '' }]
    return { all, start: usable ? 0 : all.length - 1 }
}

export async function modelDialog(app, { first = false, after } = {}) {
    const f = (await found()) || { agents: [], keys: [], local: [], elsewhere: [], providers: [] }
    const providers = f.providers || []
    const { all: opts, start } = options(f)
    const question = tt('模型来源', 'Model source')
    const d = dialog(`${first ? steps(NAMES(), 0) : ''}<h5>${question}</h5>
<div role="radiogroup" aria-label="${esc(question)}">${opts.map((o, i) => `<button type="button" class="opt${i === start ? ' on' : ''}" role="radio" aria-checked="${i === start}" tabindex="${i === start ? 0 : -1}"${i === start ? ' autofocus' : ''} data-i="${i}"><b>${esc(o.title)}</b>${o.note ? `<small>${esc(o.note)}</small>` : ''}</button>`).join('')}</div>
<div class="opt-extra"></div>
<div class="kept" hidden></div>

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
        const effortRow = (m) => ((m.efforts || []).length ? `<label><span>${tt('思考强度', 'Reasoning effort')}</span><select data-ke aria-label="${tt('思考强度', 'Reasoning effort')}">${['default', ...m.efforts].map((e) => `<option value="${e === 'default' ? '' : esc(e)}">${esc(models.effortLabel(e))}</option>`).join('')}</select></label>` : `<label><span>${tt('思考强度', 'Reasoning effort')}</span><small>—</small></label>`)
        const drawKept = (m, list) => {
            keptBox.hidden = false
            d.classList.add('is-kept')
            keptBox.innerHTML = `<div class="kh"><span>${esc(source)}</span><button type="button" data-other>${tt('换一个来源', 'Another source')}</button></div>
<label><span>${tt('模型', 'Model')}</span>${list ? `<select data-km aria-label="${tt('模型', 'Model')}">${list.map((x) => `<option value="${esc(x.id)}"${x.id === m.model ? ' selected' : ''}>${esc(x.name || x.id)}</option>`).join('')}</select>` : `<b>${esc(models.modelLabel(m))}</b>`}</label>
${effortRow(m)}
`
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
                : o.more ? `<div class="opt on"><select data-a aria-label="${tt('ACP 目录里的 agent', 'An agent of the ACP Registry')}"><option value="">${tt('正在读取目录…', 'reading the registry…')}</option></select></div>` : ''
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
        if (btn.dataset.next) { if (first) return identityStep(app, d, f); closeDialog(); if (app.modelHint) app.modelHint(); return after && after() }
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

export function identityStep(app, d, f) {
    const curId = (app.identity && app.identity.id) || 'default'
    const curName = (app.identity && app.identity.name) || ''
    const initialName = curName && curName !== 'default' ? curName : ''
    const presets = SOUL_PRESETS()
    d.innerHTML = `${steps(NAMES(), 1)}<h5 id="dlg-title">${tt('认识你的助手', 'Name your assistant')}</h5>
<p class="say">${tt('给它起一个名字，选一种相处风格；之后随时可在左下角身份菜单修改。', 'Give your assistant a name and optional style; you can change this anytime from the identity menu.')}</p>
<label><span>${tt('助手名称', 'Display name')}</span><input class="field" data-ob-name autofocus value="${esc(initialName)}" placeholder="${tt('例如：Jarvis、小安、Aria', 'e.g. Jarvis, Aria, Nova')}"></label>
<label><span>${tt('身份 ID', 'Identity ID')}</span><input class="field" data-ob-id pattern="[A-Za-z0-9][A-Za-z0-9_-]*" value="" placeholder="${esc(curId === 'default' ? tt('自动生成（留空保留 default）', 'Auto-generated (blank keeps default)') : curId)}"></label>
<div class="presets" role="group" aria-label="${tt('风格预设', 'Style presets')}">${presets.map(([label, desc], i) => `<button type="button" class="preset" data-preset="${i}" title="${esc(desc)}">${esc(label)}</button>`).join('')}</div>
<label><span>${tt('人设风格', 'Persona')}</span><input class="field" data-ob-soul placeholder="${tt('选填，写入 SOUL.md（例如：简洁直接、中文回复）', 'Optional, saved to SOUL.md (e.g. concise, rigorous)')}"></label>
<label><span>${tt('关于你', 'About you')}</span><input class="field" data-ob-user placeholder="${tt('选填，写入 USER.md（例如：你的称呼、常用技术栈）', 'Optional, saved to USER.md (e.g. your name, role, stack)')}"></label>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-skip>${tt('跳过', 'Skip')}</button><button type="button" class="btn" data-save data-default>${tt('继续', 'Continue')}</button></div>`
    const nameEl = d.querySelector('[data-ob-name]')
    const idEl = d.querySelector('[data-ob-id]')
    const soulEl = d.querySelector('[data-ob-soul]')
    const userEl = d.querySelector('[data-ob-user]')
    const res = d.querySelector('.res')
    nameEl.oninput = () => {
        if (idEl.dataset.touched || curId !== 'default') return
        const slug = nameEl.value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
        idEl.value = /^[a-z0-9]/.test(slug) ? slug.slice(0, 48) : ''
    }
    idEl.oninput = () => { idEl.dataset.touched = '1' }
    $$('[data-preset]', d).forEach((b) => {
        b.onclick = () => {
            const on = b.classList.toggle('on')
            $$('[data-preset]', d).forEach((x) => { if (x !== b) x.classList.remove('on') })
            soulEl.value = on ? presets[+b.dataset.preset][1] : ''
        }
    })
    d.querySelector('[data-skip]').onclick = () => preferencesStep(app, d, f)
    press(d.querySelector('[data-save]'), async () => {
        const display = nameEl.value.trim()
        const newId = idEl.value.trim()
        const soul = soulEl.value.trim()
        const user = userEl.value.trim()
        if (newId && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(newId)) {
            res.innerHTML = `<span class="c-failed">✕ ${tt('ID 只能以英文字母或数字开头，含字母、数字、下划线或连字符', 'ID must start with a letter or digit and use only letters, digits, _ or -')}</span>`
            idEl.focus()
            return
        }
        if (display || newId || soul || user) {
            res.innerHTML = `<span class="spin"></span>${tt('正在保存身份…', 'saving identity…')}`
            const r = await post('/api/agent/identity', {
                action: 'setup', id: curId,
                ...(newId && newId !== curId ? { new_id: newId } : {}),
                ...(display ? { name: display } : {}),
                ...(soul ? { soul } : {}),
                ...(user ? { user } : {}),
            })
            if (!r.ok) {
                res.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('保存失败', 'Could not save'))}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`
                return
            }
            if (newId && newId !== curId && app.switchIdentity) await app.switchIdentity(newId)
            else if (app.reloadIdentities) await app.reloadIdentities()
        }
        preferencesStep(app, d, f)
    })
    refocus(d)
}

export function preferencesStep(app, d, f) {
    const id = (app.identity && app.identity.id) || 'default'
    d.innerHTML = `${steps(NAMES(), 2)}<h5 id="dlg-title">${tt('使用偏好', 'Preferences')}</h5>
<label><span>${tt('每日额度（美元）', 'Daily limit (US$)')}</span><input class="field" type="number" min="0" max="10000" step="0.5" data-pref-budget placeholder="${tt('0 = 不设上限', '0 = no limit')}"></label>
<label><span>${tt('无价调用每日上限', 'Daily unpriced calls')}</span><input class="field" type="number" min="0" max="1000000" step="10" data-pref-calls placeholder="${tt('0 = 不设上限', '0 = no limit')}"></label>
<label><span>${tt('留给你的部分（美元）', 'Reserved for you (US$)')}</span><input class="field" type="number" min="0" max="10000" step="0.5" data-pref-reserve placeholder="${tt('0 = 不预留', '0 = none')}"></label>
<label><span>${tt('自主运行', 'Acting on its own')}</span><select class="field" data-pref-proactive>
  <option value="off" selected>${tt('关：有事找它才醒', 'Off: only when called')}</option>
  <option value="learn_only">${tt('只为学习', 'Only to learn')}</option>
  <option value="on">${tt('打开', 'On')}</option>
</select></label>
<label><span>${tt('原始记录保留天数', 'Keep raw records (days)')}</span><input class="field" type="number" min="0" max="3650" step="1" data-pref-keep placeholder="${tt('0 = 一直保留', '0 = keep forever')}"></label>
<label class="check"><input type="checkbox" data-pref-autostart${f.background === true ? ' checked' : ''}><span>${tt('开机后继续工作', 'Keep working after restart')}</span></label>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-skip>${tt('跳过', 'Skip')}</button><button type="button" class="btn" data-save data-default>${tt('继续', 'Continue')}</button></div>`
    const res = d.querySelector('.res')
    d.querySelector('[data-skip]').onclick = () => ready(app, d, f)
    press(d.querySelector('[data-save]'), async () => {
        const num = (sel, parser) => {
            const raw = d.querySelector(sel).value.trim()
            if (raw === '') return null
            const val = parser(raw)
            return Number.isFinite(val) && val >= 0 ? val : NaN
        }
        const budget = num('[data-pref-budget]', parseFloat)
        const calls = num('[data-pref-calls]', (s) => parseInt(s, 10))
        const reserve = num('[data-pref-reserve]', parseFloat)
        const keep = num('[data-pref-keep]', (s) => parseInt(s, 10))
        if ([budget, calls, reserve, keep].some((v) => Number.isNaN(v))) {
            res.innerHTML = `<span class="c-failed">✕ ${tt('请输入 0 或正数', 'Enter 0 or a positive number')}</span>`
            return
        }
        const proactive = d.querySelector('[data-pref-proactive]').value
        const autostart = d.querySelector('[data-pref-autostart]').checked
        res.innerHTML = `<span class="spin"></span>${tt('正在保存偏好…', 'saving preferences…')}`
        const perId = [
            ...(budget !== null ? [['agent.daily_budget', budget]] : []),
            ...(calls !== null ? [['agent.daily_calls', calls]] : []),
            ...(reserve !== null ? [['agent.reserve', reserve]] : []),
            ...(proactive !== 'off' ? [['agent.proactive', proactive]] : []),
            ...(keep !== null ? [['agent.keep_days', keep]] : []),
        ]
        for (const [key, value] of perId) {
            const r = await post('/api/agent/settings', { identity: id, key, value })
            if (!r.ok) {
                res.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('保存失败', 'Could not save'))}</span>`
                return
            }
        }
        if (autostart !== (f.background === true)) {
            const r = await post('/api/app/settings', { agent: { autostart } })
            if (!r.ok) {
                res.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('保存失败', 'Could not save'))}</span>`
                return
            }
        }
        ready(app, d, { ...f, background: autostart })
    })
    refocus(d)
}

function ready(app, d, f) {
    const who = (app.identity && app.identity.name && app.identity.name !== 'default') ? app.identity.name : ''
    const title = who ? tt(`${who} 已准备就绪`, `${who} is ready`) : tt('准备好了', 'Ready')
    d.innerHTML = `${steps(NAMES(), 3)}<h5 id="dlg-title">${esc(title)}</h5>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn" data-default>${tt('开始聊天', 'Start chatting')}</button></div>`
    const finish = async () => {
        await post('/api/app/onboarded', {})
        closeDialog(); if (app.modelHint) app.modelHint()
        await app.openChat('main')
        if (app.focusComposer) app.focusComposer()
    }
    press(d.querySelector('.btn'), finish)
    refocus(d)
}

// Bringing an OpenClaw or Hermes agent over, or adopting a shared one (a link, a file or a
// character card): persona, memory and skills come; channel tokens and keys never do.
export async function importDialog(app) {
    const here = ((await get('/api/app/elsewhere')) || {}).found || []
    const d = dialog(`<h5>${tt('从 OpenClaw 或 Hermes 导入', 'Import from OpenClaw or Hermes')}</h5>
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
