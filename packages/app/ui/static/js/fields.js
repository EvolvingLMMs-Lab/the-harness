// A setting as every settings page draws it: a row with what the setting is and its control
// by kind, and what happens when the control changes: the value is saved at once, "Saved"
// shows beside it, and when the host refuses, its reason and fix show there and the control
// goes back to the value the host still has. Titles, descriptions and the names of choices
// are the host's (names.js).
import { esc, tt } from './i18n.js'
import { $$, toggle, lock, flash } from './ui.js'
import { settingTitle, settingAbout, choicesOf } from './names.js'
import { count } from './rules.js'

// name: "section.key"; spec: the host's description of it; `only`: the values a page offers
// of a choice; `tag`: a word beside the title (whom the setting is for); `long`: a text of
// several lines.
// `choices`: [{value, label}] where the page knows what can be chosen (the models of a list).
export function settingRow({ name, spec = {}, value, title, about, only, choices, tag = '', long = false }) {
    const type = spec.type || spec.kind || (typeof value === 'boolean' ? 'bool' : typeof value === 'number' ? 'float' : value === undefined ? '' : 'text')
    if (!type) return '' // a setting this host does not have
    const label = settingTitle(name, spec, title)
    const id = `sr-${name}`.replace(/[^A-Za-z0-9_-]/g, '-')
    const offered = choices || choicesOf(spec, only)
    const range = (type === 'int' || type === 'float') && Array.isArray(spec.bounds) ? spec.bounds : []
    const limit = (attribute, v) => (v !== undefined && v !== null ? ` ${attribute}="${esc(v)}"` : '')
    let control
    if (type === 'bool') control = toggle(!!value, label)
    else if (offered) {
        const all = value === undefined || value === null || offered.some((c) => String(c.value) === String(value)) ? offered : [{ value, label: String(value) }, ...offered]
        control = `<select aria-labelledby="${id}">${all.map((c) => `<option value="${esc(c.value)}"${String(c.value) === String(value) ? ' selected' : ''}>${esc(c.label)}</option>`).join('')}</select>`
    } else if (type === 'int' || type === 'float') {
        control = `<input type="number" aria-labelledby="${id}" step="${type === 'int' ? 1 : 'any'}"${limit('min', range[0])}${limit('max', range[1])} value="${esc(value)}">`
    } else if (type === 'rules') control = `<span class="ro" data-count>${esc(count((value || []).length))}</span><button type="button" class="b" data-rules aria-describedby="${id}">${tt('编辑…', 'Edit…')}</button>`
    else if (Array.isArray(value)) control = `<span class="ro">${esc(value.join(', '))}</span>`
    else if (long) control = `<textarea rows="3" aria-labelledby="${id}">${esc(value ?? '')}</textarea>`
    else control = `<input type="text" aria-labelledby="${id}" value="${esc(value ?? '')}">`
    return `<div class="sr${long ? ' long' : ''}" data-name="${esc(name)}" data-type="${esc(type)}">`
        + `<div><b id="${id}">${esc(label)}${tag ? `<span class="tag">${esc(tag)}</span>` : ''}</b><small>${esc(settingAbout(spec, about))}</small></div><div class="ctl">${control}</div></div>`
}

// save(name, value) → the result of the request ({ok} or {ok: false, error, fix});
// rules(name, told) opens the editor of a list of rules and tells `told` the list after each change.
export function wireSettings(pane, save, rules) {
    $$('.sr[data-name]', pane).forEach((row) => {
        const { name, type } = row.dataset
        const holder = row.querySelector('.ctl')
        const done = (r) => {
            if (r && r.ok) flash(holder, tt('已保存', 'Saved'))
            else flash(holder, (r && r.error) || tt('没存上', 'Not saved'), { error: true, fix: (r && r.fix) || '' })
            return !!(r && r.ok)
        }
        const edit = row.querySelector('[data-rules]')
        if (edit) edit.onclick = () => rules(name, (list) => { row.querySelector('[data-count]').textContent = count(list.length) })
        const t = row.querySelector('.tog')
        if (t) {
            t.onclick = () => {
                if (t.getAttribute('aria-busy') === 'true') return
                const want = !t.classList.contains('on')
                lock(t, save(name, want).then((r) => { if (done(r)) { t.classList.toggle('on', want); t.setAttribute('aria-checked', want ? 'true' : 'false') } }))
            }
        }
        const i = row.querySelector('select, input, textarea')
        if (!i) return
        i.dataset.was = i.value
        i.onchange = () => {
            let v = i.value
            if (type === 'int' || type === 'float') {
                v = type === 'int' ? parseInt(i.value, 10) : parseFloat(i.value)
                if (Number.isNaN(v)) { i.value = i.dataset.was; done({ ok: false, error: tt('这里要填一个数。', 'This takes a number.') }); return }
            }
            lock(i, save(name, v).then((r) => { if (done(r)) i.dataset.was = i.value; else i.value = i.dataset.was }))
        }
    })
}
