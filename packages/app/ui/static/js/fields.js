// A setting as every settings page draws it: a row with what the setting is and its control
// by kind, and what happens when the control changes: the value is saved at once, "Saved"
// shows beside it, and when the host refuses, its reason and fix show there and the control
// goes back to the value the host still has. The names come from names.js.
import { esc, tt } from './i18n.js'
import { $$, toggle, lock, flash } from './ui.js'
import { settingTitle, settingAbout, choiceLabel } from './names.js'

// spec: the host's description of the setting ({kind, default, bounds, about, ...});
// choices: the values to offer when the page narrows them (else the description's).
export function settingRow({ section, key, spec = {}, value, title, about, choices, perIdentity = false }) {
    if (value === undefined && !spec.kind) return '' // a setting this host does not have
    const name = settingTitle(section, key, spec, title)
    const id = `sr-${section}-${key}`.replace(/[^A-Za-z0-9_-]/g, '-')
    const offered = choices || spec.choices || (spec.kind === 'choice' && Array.isArray(spec.bounds) ? spec.bounds : null)
    const kind = spec.kind || typeof value
    const range = (kind === 'int' || kind === 'float') && Array.isArray(spec.bounds) ? spec.bounds : []
    const limit = (name, v) => (v !== undefined && v !== null ? ` ${name}="${esc(v)}"` : '')
    let control
    if (kind === 'bool' || typeof value === 'boolean') control = toggle(!!value, name)
    else if (offered) {
        const all = value === undefined || offered.map(String).includes(String(value)) ? offered : [value, ...offered]
        control = `<select aria-labelledby="${id}">${all.map((c) => `<option value="${esc(c)}"${String(c) === String(value) ? ' selected' : ''}>${esc(choiceLabel(section, key, c, spec))}</option>`).join('')}</select>`
    } else if (kind === 'int' || kind === 'float' || typeof value === 'number') {
        control = `<input type="number" aria-labelledby="${id}" step="${kind === 'int' ? 1 : 'any'}"${limit('min', range[0])}${limit('max', range[1])} value="${esc(value)}">`
    } else if (kind === 'rules' || Array.isArray(value)) control = `<span class="ro">${(value || []).length} ${tt('条规则', 'rules')}</span>`
    else control = `<input type="text" aria-labelledby="${id}" value="${esc(value ?? '')}">`
    return `<div class="sr" data-s="${esc(section)}" data-k="${esc(key)}" data-own="${perIdentity ? 1 : 0}" data-kind="${esc(kind)}">`
        + `<div><b id="${id}">${esc(name)}</b><small>${esc(settingAbout(section, key, spec, about))}</small></div><div class="ctl">${control}</div></div>`
}

// save(section, key, value, perIdentity) → the result of the request ({ok} or {ok: false, error, fix}).
export function wireSettings(pane, save) {
    $$('.sr[data-s]', pane).forEach((row) => {
        const { s, k, own, kind } = row.dataset
        const holder = row.querySelector('.ctl')
        const done = (r) => {
            if (r && r.ok) flash(holder, tt('已保存', 'Saved'))
            else flash(holder, (r && r.error) || tt('没存上', 'Not saved'), { error: true, fix: (r && r.fix) || '' })
            return !!(r && r.ok)
        }
        const t = row.querySelector('.tog')
        if (t) {
            t.onclick = () => {
                if (t.getAttribute('aria-busy') === 'true') return
                const want = !t.classList.contains('on')
                lock(t, save(s, k, want, own === '1').then((r) => { if (done(r)) { t.classList.toggle('on', want); t.setAttribute('aria-checked', want ? 'true' : 'false') } }))
            }
        }
        const i = row.querySelector('select, input')
        if (!i) return
        i.dataset.was = i.value
        i.onchange = () => {
            let v = i.value
            if (kind === 'int' || kind === 'float' || i.type === 'number') {
                v = kind === 'int' ? parseInt(i.value, 10) : parseFloat(i.value)
                if (Number.isNaN(v)) { i.value = i.dataset.was; done({ ok: false, error: tt('这里要填一个数。', 'This takes a number.') }); return }
            }
            lock(i, save(s, k, v, own === '1').then((r) => { if (done(r)) i.dataset.was = i.value; else i.value = i.dataset.was }))
        }
    })
}
