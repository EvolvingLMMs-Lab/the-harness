// A setting that is a list of rules (kind "rules"): each rule gives a level to what its
// fields name, and it wins over the level set beside it. The editor is drawn from the host's
// description of the setting and knows no particular one:
//
//     fields       {name: "text" | "id" | [choices]}: what a rule may name
//     fields_when  {level: {name: kind}}: what a rule of that level takes besides
//     example      one rule, shown as the hint in the fields
//
// The levels are the choices of the setting of the same section that the example's level is
// one of. A rule is added or removed at once: the whole list is saved, and what the host
// refuses stays as it was, with its reason.
import { esc, tt } from './i18n.js'
import { $$, dialog, closeDialog, press, empty } from './ui.js'
import { choicesOf, settingTitle, settingAbout, readable } from './names.js'

export const count = (n) => tt(`${n} 条规则`, `${n} rule${n === 1 ? '' : 's'}`)

function levelsOf(ctx, name) {
    const section = name.split('.')[0], want = (ctx.spec(name).example || {}).level
    for (const key of Object.keys((ctx.core().schema || {})[section] || {})) {
        const spec = ctx.spec(`${section}.${key}`), choices = (spec.type || spec.kind) === 'choice' ? choicesOf(spec) : null
        if (choices && (want === undefined || choices.some((c) => c.value === want))) return choices
    }
    return null
}

// `changed(rules)`: told the list after each change, to show how many there are.
export function rulesDialog(ctx, name, changed) {
    const spec = ctx.spec(name), levels = levelsOf(ctx, name)
    const fields = spec.fields || {}, when = spec.fields_when || {}, example = spec.example || {}
    let rules = [...(ctx.value(name) || [])]
    const level = (v) => ((levels || []).find((c) => c.value === v) || { label: String(v) }).label
    const field = (key, kind, only = '') => `<label${only ? ` data-when="${esc(only)}" hidden` : ''}><span>${esc(readable(key))}</span>`
        + (Array.isArray(kind) ? `<select class="field" data-f="${esc(key)}"><option value=""></option>${kind.map((v) => `<option value="${esc(v)}">${esc(readable(v))}</option>`).join('')}</select>`
            : `<input class="field" data-f="${esc(key)}" data-kind="${esc(kind)}" ${kind === 'int' || kind === 'float' ? 'type="number" step="any"' : 'spellcheck="false"'} placeholder="${esc(example[key] ?? '')}">`) + `</label>`
    const d = dialog(`<h5>${esc(settingTitle(name, spec))}</h5><p class="note">${esc(settingAbout(spec))}</p><div class="rl" data-list></div>
<div class="lg">${tt('加一条规则', 'Add a rule')}</div>
<label><span>${tt('档位', 'Level')}</span>${levels ? `<select class="field" data-level>${levels.map((c) => `<option value="${esc(c.value)}"${c.value === example.level ? ' selected' : ''}>${esc(c.label)}</option>`).join('')}</select>` : `<input class="field" data-level spellcheck="false" placeholder="${esc(example.level ?? '')}">`}</label>
${Object.entries(fields).map(([key, kind]) => field(key, kind)).join('')}${Object.entries(when).map(([lv, more]) => Object.entries(more).map(([key, kind]) => field(key, kind, lv)).join('')).join('')}
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('关闭', 'Close')}</button><button type="button" class="btn" data-default>${tt('添加', 'Add')}</button></div>`)
    d.classList.add('wide')
    const res = d.querySelector('.res'), pick = d.querySelector('[data-level]')
    const list = () => {
        d.querySelector('[data-list]').innerHTML = rules.length ? rules.map((r, i) => `<div class="li"><div class="lm"><b>${esc(level(r.level))}</b><small>${esc(Object.entries(r).filter(([k]) => k !== 'level').map(([k, v]) => `${readable(k).toLowerCase()}: ${v}`).join(' · '))}</small></div>`
            + `<div class="la"><button type="button" class="b" data-remove="${i}">${tt('移除', 'Remove')}</button></div></div>`).join('') : empty(tt('还没有规则', 'No rules yet'))
        $$('[data-remove]', d).forEach((b) => press(b, () => save(rules.filter((_, i) => i !== +b.dataset.remove))))
    }
    const fit = () => $$('[data-when]', d).forEach((n) => { n.hidden = n.dataset.when !== pick.value })
    async function save(next) {
        res.innerHTML = `<span class="spin"></span>`
        const r = await ctx.save(name, next)
        if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('没存上', 'Not saved'))}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return false }
        rules = [...(ctx.value(name) || next)]
        res.innerHTML = `<span class="c-done">✓ ${tt('已保存', 'Saved')}</span>`
        list(); changed(rules)
        return true
    }
    pick.onchange = fit
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const rule = { level: pick.value.trim() }
        for (const input of $$('[data-f]', d)) {
            if (input.closest('[hidden]') || input.value.trim() === '') continue
            const kind = input.dataset.kind
            rule[input.dataset.f] = kind === 'int' || kind === 'float' ? Number(input.value) : input.value.trim()
        }
        if (Object.keys(rule).length < 2 && Object.keys(fields).length) { res.innerHTML = `<span class="c-failed">✕ ${tt('先填这条规则管的是什么。', 'Say first what this rule is about.')}</span>`; return }
        if (await save([...rules, rule])) $$('[data-f]', d).forEach((input) => { input.value = '' })
    })
    list(); fit()
}
