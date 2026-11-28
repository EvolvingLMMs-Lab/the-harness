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

export const isAgent = (m) => String((typeof m === 'string' ? m : (m && m.provider)) || '').startsWith('acp:')

// Canonical provider taxonomy: uniform Vendor + Connection method (OpenCode / T3 / Hermes standard).
const PROVIDER_META = {
    'acp:claude-acp': { vendor: 'Anthropic', via: 'Claude Code', kind: 'plan' },
    'acp:codex-acp': { vendor: 'OpenAI', via: 'Codex CLI', kind: 'plan' },
    'acp:cursor': { vendor: 'Cursor', via: 'Cursor', kind: 'plan' },
    'acp:antigravity': { vendor: 'Google', via: 'Antigravity CLI', kind: 'plan' },
    'acp:custom/antigravity': { vendor: 'Google', via: 'Antigravity CLI', kind: 'plan' },
    'acp:gemini': { vendor: 'Google', via: 'Gemini CLI', kind: 'plan' },
    'acp:grok-build': { vendor: 'xAI', via: 'Grok CLI', kind: 'plan' },
    anthropic: { vendor: 'Anthropic', via: 'API Key', kind: 'key' },
    openai: { vendor: 'OpenAI', via: 'API Key', kind: 'key' },
    gemini: { vendor: 'Google', via: 'API Key', kind: 'key' },
    xai: { vendor: 'xAI', via: 'API Key', kind: 'key' },
    openrouter: { vendor: 'OpenRouter', via: 'API Key', kind: 'key' },
    deepseek: { vendor: 'DeepSeek', via: 'API Key', kind: 'key' },
    dashscope: { vendor: 'Qwen', via: 'API Key', kind: 'key' },
    zhipu: { vendor: 'Zhipu', via: 'API Key', kind: 'key' },
    moonshot: { vendor: 'Moonshot', via: 'API Key', kind: 'key' },
    ollama: { vendor: 'Ollama', via: null, kind: 'local' },
    custom: { vendor: 'Custom', via: null, kind: 'custom' },
}

export function providerDisplay(provider, fallbackSource = '') {
    const id = String(provider || '')
    const hit = PROVIDER_META[id]
    if (hit) {
        const via = hit.via || (hit.kind === 'local' ? tt('本地', 'Local') : hit.kind === 'custom' ? tt('自定义接口', 'Custom API') : 'API Key')
        return { id, vendor: hit.vendor, via, kind: hit.kind, title: `${hit.vendor} · ${via}` }
    }
    if (isAgent(id)) {
        const raw = fallbackSource || id.slice(4)
        return { id, vendor: raw, via: 'ACP', kind: 'plan', title: raw }
    }
    const vendor = fallbackSource || id
    return { id, vendor, via: 'API Key', kind: 'key', title: vendor }
}

const isUnresolvedDefault = (m) => {
    const name = String((m && (m.model_name || m.name)) || '').trim()
    return isAgent(m) && (!m.model || m.model === 'default')
        && (!name || ['its own default', 'Default', 'default', m.source, providerDisplay(m.provider, m.source).via].includes(name))
}

// The model by its own clean name (never "默认 · 默认 (Claude Code)").
// `inGroup`: inside a provider group whose header already shows Vendor + via.
export function modelLabel(m, { inGroup = false } = {}) {
    if (!m) return ''
    if (isUnresolvedDefault(m)) {
        if (inGroup) return tt('默认模型', 'Default model')
        const meta = providerDisplay(m.provider, m.source)
        return meta.via || meta.vendor
    }
    const name = m.model_name || m.name || ''
    return name && name !== m.model ? name : modelName(m.model) || name
}
export const sourceLabel = (m) => {
    if (!m) return ''
    const meta = providerDisplay(m.provider, m.source)
    return meta.kind === 'plan' ? `${meta.vendor} · ${meta.via}` : meta.vendor
}
// What a source is, in a few words, for the heading over its models.
export function sourceKind(m, found) {
    if (isAgent(m)) return tt('订阅', 'plan')
    if (m && m.provider === 'ollama') return tt('本地', 'local')
    if (((found || {}).local || []).some((l) => l.provider === m.provider)) return tt('本地', 'local')
    return 'API Key'
}
export const EFFORT_ZH = { minimal: '最少', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高', ultra: '极高', none: '关闭', default: '自动' }
export const EFFORT_EN = { minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max', ultra: 'Ultra', none: 'None', default: 'Auto' }
export const effortLabel = (level, modelEntry = null) => {
    const custom = modelEntry && modelEntry.effort_labels && modelEntry.effort_labels[level]
    if (custom) return tt(EFFORT_ZH[level] || custom, custom)
    return tt(EFFORT_ZH[level] || level, EFFORT_EN[level] || level)
}

const OFF_VALUES = new Set(['false', 'off', '0', 'disabled', 'none'])
export function toggleSpec(opt) {
    const list = (opt && Array.isArray(opt.options)) ? opt.options : []
    if (list.length !== 2) return null
    const off = list.find((o) => OFF_VALUES.has(String(o.value || '').toLowerCase()))
    const on = list.find((o) => o !== off)
    return off && on ? { off, on } : null
}
export function optionName(opt) {
    if (!opt) return ''
    const id = String(opt.id || '').toLowerCase()
    if (id === 'fast') return tt('快速模式', 'Fast')
    if (id === 'context') return tt('上下文窗口', 'Context')
    if (id === 'thinking') return tt('深度思考', 'Thinking')
    return String(opt.name || opt.id || '').replace(/[\u200B-\u200D\uFEFF]/g, '').trim()
}
export function optionValueLabel(opt, value) {
    const list = (opt && Array.isArray(opt.options)) ? opt.options : []
    const hit = list.find((o) => o.value === value)
    const raw = String((hit && hit.name) || value || '').replace(/[\u200B-\u200D\uFEFF]/g, '').trim()
    return raw || String(value || '')
}

// The entries of the list by source, in the order the sources first appear.
export function bySource(models) {
    const groups = []
    for (const m of models) {
        let g = groups.find((x) => x.provider === m.provider)
        if (!g) {
            const meta = providerDisplay(m.provider, m.source)
            groups.push(g = { provider: m.provider, source: meta.vendor, via: meta.via, kind: meta.kind, label: meta.title, models: [] })
        }
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
export async function use(provider, model, { name = '', fast = false } = {}) {
    const r = await post('/api/app/models', { action: 'use', provider, model, ...(name ? { name } : {}), ...(fast ? { fast: true } : {}) })
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
    if (!rows.length) { box.innerHTML = empty(tt(`${source} 没有列出可选的模型`, `${source} lists no models to choose from`)); return }
    const at = current || got.current || ''
    let chosen = rows.some((m) => m.id === at) ? at : null
    box.innerHTML = (rows.length > 8 ? `<input class="field" data-find placeholder="${tt('找一个模型', 'Find a model')}" aria-label="${tt('找一个模型', 'Find a model')}">` : '')
        + `<div class="picks" role="radiogroup" aria-label="${esc(source)}">${rows.map((m) => `<button type="button" class="opt${m.id === chosen ? ' on' : ''}" role="radio" aria-checked="${m.id === chosen}" data-id="${esc(m.id)}"><b>${esc(m.name || modelName(m.id))}${m.id === got.current ? ` <em>${tt('当前', 'current')}</em>` : ''}</b><small>${esc(m.description || m.id)}</small></button>`).join('')}</div>`
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
