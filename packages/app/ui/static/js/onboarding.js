// The first time, as `hermes setup` and `openclaw onboard` do it: step one finds the keys on
// this computer, makes one test call and saves only a working key (to the credentials file);
// step two says it stays on (the installer chose that) and opens the chat, where it asks for
// its own name and manner, as OpenClaw's first conversation does.
import { esc, tt, modelName } from './i18n.js'
import { get, post } from './api.js'
import { $$, dialog, closeDialog, steps } from './ui.js'

const NAMES = () => [tt('模型', 'Model'), tt('开始', 'Start')]

export async function needed() {
    const status = await get('/api/app')
    return !!status && status.llm && !status.llm.ready
}

export async function modelDialog(app, { first = false, after } = {}) {
    const found = (await get('/api/app/found')) || { keys: [], ollama: [], bring_over: [] }
    const status = (await get('/api/app')) || {}
    const providers = status.providers || []
    const opts = [
        ...found.keys.map((k) => ({ provider: k.provider, model: k.model || '', title: `${k.name}${k.model ? ' · ' + modelName(k.model) : ''}`, note: k.saved ? tt('凭据文件里有 key', 'key in the credentials file') : tt('在环境变量里找到了 key', 'key found in the environment'), ask: !k.model })),
        ...found.ollama.slice(0, 2).map((m) => ({ provider: 'ollama', model: m, title: `${tt('本机 Ollama', 'Local Ollama')} · ${m}`, note: tt('在本机找到', 'found on this computer') })),
        { provider: '', model: '', title: tt('填一个新的 key…', 'Enter a new key…'), fresh: true },
    ]
    const d = dialog(`${first ? steps(NAMES(), 0) : ''}<h5>${tt('用哪个模型？', 'Which model?')}</h5>
${opts.map((o, i) => `<button class="opt${i === 0 ? ' on' : ''}" data-i="${i}"><b>${esc(o.title)}</b>${o.note ? `<small>${esc(o.note)}</small>` : ''}</button>`).join('')}
<div class="opt-extra"></div>
${first && found.bring_over.length ? `<button class="imp" data-import>${tt(`在本机发现一个 ${KIND[found.bring_over[0]] || found.bring_over[0]} 身份 · 把它接过来`, `A ${KIND[found.bring_over[0]] || found.bring_over[0]} agent is on this computer · bring it over`)}</button>` : ''}
<div class="row"><span class="res"></span><button class="btn">${tt('试一下', 'Try it')}</button></div>`)
    let chosen = 0
    const extra = d.querySelector('.opt-extra')
    const showExtra = () => {
        const o = opts[chosen]
        extra.innerHTML = o.fresh ? `<div class="opt on"><select data-p>${providers.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select><input data-m placeholder="${tt('模型 id', 'model id')}" value="deepseek/deepseek-v4.1-flash"><input data-k type="password" autocomplete="off" placeholder="${tt('key（本机模型不用填）', 'key (none for a local model)')}"></div>`
            : o.ask ? `<div class="opt on"><input data-m placeholder="${tt('模型 id', 'model id')}" value=""></div>` : ''
    }
    $$('.opt[data-i]', d).forEach((b) => { b.onclick = () => { chosen = +b.dataset.i; $$('.opt[data-i]', d).forEach((x) => x.classList.toggle('on', x === b)); showExtra() } })
    showExtra()
    if (d.querySelector('[data-import]')) d.querySelector('[data-import]').onclick = () => importDialog(app)
    const btn = d.querySelector('.btn'), res = d.querySelector('.res')
    btn.onclick = async () => {
        if (btn.dataset.next) { if (first) return ready(app, d); closeDialog(); return after && after() }
        const o = opts[chosen]
        const body = { provider: o.provider, model: o.model }
        if (o.fresh) { body.provider = d.querySelector('[data-p]').value; body.model = d.querySelector('[data-m]').value; body.key = d.querySelector('[data-k]').value }
        else if (o.ask) body.model = d.querySelector('[data-m]').value || o.model
        btn.disabled = true
        res.innerHTML = `<span class="spin"></span>${tt('正在试一次调用…', 'making one call…')}`
        const r = await post('/api/app/onboard', body)
        btn.disabled = false
        if (r.ok && r.data && r.data.ok) {
            res.innerHTML = `<span class="c-done">✓ ${tt(`通了 · ${r.data.seconds} 秒 · 已存进凭据`, `works · ${r.data.seconds} s · saved to credentials`)}</span>`
            btn.textContent = tt('继续', 'Continue'); btn.dataset.next = '1'
        } else res.innerHTML = `<span class="c-failed">✕ ${esc((r.data && (r.data.detail || r.data.error)) || r.error || tt('没通', 'it did not answer'))}</span>`
    }
    return d
}

function ready(app, d) {
    d.innerHTML = `${steps(NAMES(), 1)}<h5>${tt('准备好了', 'Ready')}</h5>
<p class="note">${tt('它会一直在：开机后继续生活，设置的"通用"里能改。每天的模型花费上限是 $2；用 OpenRouter 的话，也可以在 key 上设一个额度。', 'It stays on: it keeps living after the computer starts, and Settings › General changes it. Model spending is capped at $2 a day; with OpenRouter you can also set a limit on the key itself.')}</p>
<div class="row"><span class="res"></span><button class="btn">${tt('开始聊天', 'Start chatting')}</button></div>`
    d.querySelector('.btn').onclick = () => { closeDialog(); app.openChat('main') }
}

const KIND = { hermes: 'Hermes', openclaw: 'OpenClaw' }

// Bringing an OpenClaw or Hermes agent over, or adopting a shared one (a link, a file or a
// character card): persona, memory and skills come; channel tokens and keys never do.
export async function importDialog(app) {
    const found = ((await get('/api/app/elsewhere')) || {}).found || []
    const d = dialog(`<h5>${tt('从 OpenClaw 或 Hermes 导入', 'Import from OpenClaw or Hermes')}</h5><p class="note">${tt('带过来人设、记忆和技能，不带渠道 token，免得一个 token 同时被两个 agent 用；导入后建议停掉原来的 agent。技能回到"提议"，要在这里自测通过；反应先停用。',
        'Brings persona, memory and skills but not channel tokens, so one token is never used by two agents at once; afterwards stop the original agent. Skills go back to "proposed" and must pass their own test here; reactions start disabled.')}</p>
${found.map((f) => `<button class="opt" data-kind="${esc(f.kind)}"><b>${esc(KIND[f.kind] || f.kind)}</b><small>${esc(f.folder)}</small></button>`).join('') || `<p class="note">${tt('这台电脑上没有找到 OpenClaw 或 Hermes。', 'No OpenClaw or Hermes agent on this computer.')}</p>`}
<label><span>${tt('或者领养', 'Or adopt')}</span><input class="field" placeholder="${tt('分享链接、文件或角色卡', 'a share link, a file or a character card')}"></label>
<div class="row"><span class="res"></span><button class="btn">${tt('导入', 'Import')}</button></div>`)
    let kind = found.length ? found[0].kind : null
    $$('[data-kind]', d).forEach((b, i) => { b.classList.toggle('on', i === 0); b.onclick = () => { kind = b.dataset.kind; $$('[data-kind]', d).forEach((x) => x.classList.toggle('on', x === b)) } })
    d.querySelector('.btn').onclick = async () => {
        const source = d.querySelector('input').value.trim(), res = d.querySelector('.res')
        res.innerHTML = '<span class="spin"></span>'
        const r = source ? await post('/api/agent/take', { action: 'adopt', source }) : kind ? await post('/api/app/elsewhere', { kind }) : { ok: false, error: tt('选一个，或填一个来源', 'choose one, or give a source') }
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
        const made = r.data.identity || r.data.id
        res.innerHTML = `<span class="c-done">✓ ${tt('新身份', 'new identity')} ${esc(made || '')}</span>`
        if (app && app.refresh) app.refresh()
    }
}

export async function start(app) {
    if (await needed()) await modelDialog(app, { first: true })
}
