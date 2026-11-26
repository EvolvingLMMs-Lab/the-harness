// A model, the source it comes from, and its effort levels: three things the page never mixes
// up, as Claude Code's /model and Zed's model selector keep them apart. The source is whose
// account pays (an agent signed in on this computer, a provider's key, this computer); the
// model is one of those the source offers; the effort is one of the levels that model has.
// A source is never shown as a model.
//
// The host says each entry's `source` and `model_name` (/api/app/models), what a source
// offers (/api/app/models/catalog: an agent declares its models through ACP, a provider
// lists its catalog), and keeps a model of a source when it is picked (action "use").
import { esc, tt, modelName } from './i18n.js'
import { get, post, failed } from './api.js'
import { $$, dialog, closeDialog, radios, empty, problem, loading } from './ui.js'

export const isAgent = (m) => String((m && m.provider) || '').startsWith('acp:')

// The model by its own name. An agent's "default" is the model the agent itself is set to.
export function modelLabel(m) {
    if (!m) return ''
    const name = m.model_name || m.name || ''
    if (isAgent(m) && (!m.model || m.model === 'default') && (!name || name === 'its own default' || name === 'default' || name === m.source)) return tt('它自己设的模型', 'its own default')
    // a provider's model kept under its bare id reads as its name
    return name && name !== m.model ? name : modelName(m.model) || name
}
export const sourceLabel = (m) => (m && (m.source || (isAgent(m) ? m.provider.slice(4) : m.provider))) || ''
// What a source is, in a few words, for the heading over its models.
export function sourceKind(m, found) {
    if (isAgent(m)) return tt('你的订阅', 'your own plan')
    if (((found || {}).local || []).some((l) => l.provider === m.provider)) return tt('这台电脑上', 'on this computer')
    return 'key'
}
export const EFFORT_ZH = { minimal: '最少', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高', ultra: '极高', none: '不思考', default: '模型默认' }
export const EFFORT_EN = { minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max', ultra: 'Ultra', none: 'None', default: "Model's default" }
export const effortLabel = (level) => tt(EFFORT_ZH[level] || level, EFFORT_EN[level] || level)

// The entries of the list by source, in the order the sources first appear.
export function bySource(models) {
    const groups = []
    for (const m of models) {
        let g = groups.find((x) => x.provider === m.provider)
        if (!g) groups.push(g = { provider: m.provider, source: sourceLabel(m), models: [] })
        g.models.push(m)
    }
    return groups
}

// What a source offers, asked once a session for each source (an agent is started for it).
const asked = new Map()
export function offered(provider, model = '') {
    const key = `${provider}\n${model}`
    if (!asked.has(key)) asked.set(key, get('/api/app/models/catalog', { provider, ...(model ? { model } : {}) }).then((got) => { if (!got) asked.delete(key); return got }))
    return asked.get(key)
}
// Keep a model of a source in the list (as its source describes it) and give its entry.
export async function use(provider, model) {
    const r = await post('/api/app/models', { action: 'use', provider, model })
    return r.ok && r.data ? r.data : { error: r.error, fix: r.fix }
}

// Every model a source offers, to pick one: the dialog behind "More models of ...". `then(entry,
// models)` gets the entry the pick was kept as.
export async function more(provider, source, { current = '', then, title } = {}) {
    const d = dialog(`<h5>${esc(title || tt(`${source} 的模型`, `Models of ${source}`))}</h5>
<div data-list>${loading(tt(`正在问 ${source} 有哪些模型…`, `Asking ${source} for its models…`))}</div>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default disabled>${tt('用这个', 'Use it')}</button></div>`)
    d.querySelector('[data-no]').onclick = closeDialog
    const box = d.querySelector('[data-list]'), ok = d.querySelector('[data-default]'), res = d.querySelector('.res')
    const got = await offered(provider)
    if (!d.isConnected) return
    const rows = (got && got.models) || []
    if (!got) { box.innerHTML = problem(failed.get('/api/app/models/catalog'), { title: tt(`${source} 没有答上来`, `${source} did not answer`) }); return }
    if (!rows.length) { box.innerHTML = empty(tt(`${source} 没有列出可选的模型`, `${source} lists no models to choose from`), tt('它只用自己设的那个。', 'It uses the one it is set to.')); return }
    const at = current || got.current || ''
    let chosen = rows.some((m) => m.id === at) ? at : null
    box.innerHTML = (rows.length > 8 ? `<input class="field" data-find placeholder="${tt('找一个模型', 'Find a model')}" aria-label="${tt('找一个模型', 'Find a model')}">` : '')
        + `<div class="picks" role="radiogroup" aria-label="${esc(source)}">${rows.map((m) => `<button type="button" class="opt${m.id === chosen ? ' on' : ''}" role="radio" aria-checked="${m.id === chosen}" data-id="${esc(m.id)}"><b>${esc(m.name || modelName(m.id))}${m.id === got.current ? ` <em>${tt(`${source} 现在设的`, `what ${source} is set to`)}</em>` : ''}</b><small>${esc(m.description || m.id)}</small></button>`).join('')}</div>`
    ok.disabled = !chosen
    const group = radios(box.querySelector('.picks'), (b) => { chosen = b.dataset.id; ok.disabled = false }, { enter: true })
    const find = box.querySelector('[data-find]')
    if (find) {
        find.oninput = () => { const q = find.value.toLowerCase(); $$('[data-id]', box).forEach((b) => { b.hidden = !!q && !b.textContent.toLowerCase().includes(q) }); group.stops() }
        find.onkeydown = (e) => { if (e.key === 'ArrowDown' && group.first()) { e.preventDefault(); group.first().click(); group.first().focus() } }
        find.focus()
    } else (box.querySelector('.opt.on') || box.querySelector('.opt')).focus()
    ok.onclick = async () => {
        if (!chosen) return
        ok.disabled = true
        res.innerHTML = `<span class="spin"></span>${tt('正在记下它和它的思考档位…', 'keeping it with its effort levels…')}`
        const kept = await use(provider, chosen)
        if (!kept.entry) { ok.disabled = false; res.innerHTML = `<span class="c-failed">✕ ${esc(kept.error || tt('没记下', 'it was not kept'))}</span>${kept.fix ? `<small class="fix">${esc(kept.fix)}</small>` : ''}`; return }
        closeDialog()
        if (then) then(kept.entry, kept.models || [])
    }
}
