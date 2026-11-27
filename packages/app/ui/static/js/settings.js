// Settings, after Hermes Desktop's "Settings & onboarding": a list of pages on the left, the
// page on the right, over the whole window. This file is the frame every page shares; the
// pages are in pages/.
//
//   - A page draws from what it read last time and reads again in the background; it is drawn
//     again only when something changed. The first visit shows that it is loading; a read
//     that fails shows the reason, the fix and Try again.
//   - "Applies to" ("Per-profile settings: the Applies to scope"): with two or more identities,
//     a page that holds an identity's own things has a row of the identities at its top. It
//     follows the identity in use until another is picked, keeps the pick from page to page,
//     and goes back to the identity in use when that one changes.
//   - A setting has one name, section.key. One an identity may have its own value of
//     (scope: identity) is read and written for the identity picked (/api/agent/settings);
//     the others are the computer's (/api/app/settings). A write that the host refuses is
//     never tried as the other kind.
//   - The host says of each setting whether a person is shown it (`shown: false`: never) and
//     whether it is a tuning few need (`advanced: true`): those of a page are gathered under
//     one closed "Advanced" group at its end. The pages keep no list of either.
import { esc, tt, sectionName, SECTIONS } from './i18n.js'
import { get as fetchJson, post, failed } from './api.js'
import { $, $$, on, loading, problem, dialogOpen, menuOpen } from './ui.js'
import { icon } from './icons.js'
import { settingRow, wireSettings } from './fields.js'
import { rulesDialog } from './rules.js'
import { prefs } from './prefs.js'
import * as general from './pages/general.js'
import * as model from './pages/model.js'
import * as usage from './pages/usage.js'
import * as permissions from './pages/permissions.js'
import * as packages from './pages/packages.js'
import * as learned from './pages/learned.js'
import * as connectors from './pages/connectors.js'
import * as computer from './pages/computer.js'
import * as personalization from './pages/personalization.js'
import * as data from './pages/data.js'
import * as about from './pages/about.js'

const PAGES = { general, model, usage, permissions, packages, learned, connectors, computer, personalization, data, about }

// What the pages read, by request; kept while the window is open.
const seen = new Map()
let fresh = new Set() // the reads this drawing already made
let changed = null // called when a read in the background brought something new
function read(path, params) {
    const key = path + JSON.stringify(params || {})
    if (seen.has(key) && fresh.has(key)) return Promise.resolve(seen.get(key))
    fresh.add(key)
    const reading = fetchJson(path, params).then((value) => {
        const before = seen.get(key)
        if (value === null && before !== undefined && before !== null) return before // no answer now: what it said last
        seen.set(key, value)
        if (before !== undefined && JSON.stringify(before) !== JSON.stringify(value) && changed) changed()
        return value
    })
    return seen.has(key) ? Promise.resolve(seen.get(key)) : reading
}

let core = { values: {}, schema: {} } // the computer's settings
let own = null // the picked identity's own
let target = null // the identity the pages apply to, when it is not the one in use
let ctx = null
// where the sidebar's Settings entry was when the page was opened: the way back stands there
let entryAt = null

// The names of a place's "acting on its own" (spaces.<place>.proactive has no description of its own).
const PLACE = { type: 'choice', scope: 'identity', choices: [{ value: 'off', en: 'Not on its own', zh: '不主动' }, { value: 'learn', en: 'Learning only', zh: '只学习' }, { value: 'do', en: 'Learning and doing', zh: '学习也做事' }] }

function context(app, id) {
    const who = app.identities.find((i) => i.id === (target || app.identity.id)) || { id: app.identity.id, name: app.identity.name }
    const split = (name) => { const at = name.indexOf('.'); return [name.slice(0, at), name.slice(at + 1)] }
    const spec = (name) => {
        const [section, key] = split(name)
        if (section === 'spaces') return PLACE
        return (own && own.schema && own.schema[name]) || (core.schema[section] || {})[key] || {}
    }
    const mine = (name) => spec(name).scope === 'identity'
    const value = (name) => {
        const [section, key] = split(name)
        if (section === 'spaces') return ((own || {}).spaces || {})[key.replace(/\.proactive$/, '')]
        if (mine(name) && own && own.values && name in own.values) return own.values[name]
        const v = (core.values[section] || {})[key]
        return v !== undefined ? v : spec(name).default
    }
    const c = {
        app, section: id, id: who.id, name: who.name || who.id, many: app.identities.length > 1, pane: $('.pg-settings .pane'),
        get: read, spec, value, core: () => core, own: () => own,
        // One setting as a row; on a page of an identity, a setting of the whole computer says so.
        // One the host does not show is no row at all; an advanced one goes to the page's
        // "Advanced" group instead of where it was asked for.
        setting(name, options = {}) {
            const s = spec(name)
            if (s.shown === false) return ''
            const html = settingRow({ name, spec: s, value: value(name), ...options,
                tag: options.tag ?? (c.many && PAGES[id].identity && !mine(name) ? tt('所有身份', 'every identity') : '') })
            if (!s.advanced) return html
            c.advanced.push(html)
            return ''
        },
        // A titled group of settings; no title when none of them is drawn here.
        group(title, names) {
            const rows = names.map((name) => c.setting(name)).join('')
            return rows ? `<div class="lg">${esc(title)}</div>${rows}` : ''
        },
        advanced: [],
        // Save one setting where it belongs; the answer is the request's.
        async save(name, v) {
            const [section, key] = split(name)
            const r = mine(name) ? await post('/api/agent/settings', { identity: who.id, key: name, value: v }) : await post('/api/app/settings', { [section]: { [key]: v } })
            if (!r.ok) return r
            if (mine(name)) { if (r.data && r.data.values) { own = r.data; seen.set('/api/agent/settings' + JSON.stringify({ identity: who.id }), own) } } else {
                if (r.data && r.data.values) { core = { ...core, values: r.data.values }; seen.set('/api/app/settings{}', core) }
                if (app.applied) app.applied(section, key, v)
            }
            return r
        },
        // Read everything again and draw the page with it (after something was changed).
        reload() { seen.clear(); return open(app, id) },
    }
    return c
}

export async function open(app, id, again = false) {
    if (!PAGES[id]) id = 'general'
    if (target && !app.identities.some((i) => i.id === target)) target = null
    app.section = id
    const s = $('.pg-settings')
    // the keyboard stays on the list of pages while it moves through them
    const inNav = !s.classList.contains('open') || s.querySelector('nav').contains(document.activeElement)
    s.querySelector('nav').innerHTML = `<div class="nt">${tt('设置', 'Settings')}</div>`
        + SECTIONS.filter(([sid]) => PAGES[sid]).map(([sid, zh, en]) => `<button type="button" data-act="settings" data-arg="${sid}" class="${sid === id ? 'on' : ''}"${sid === id ? ' aria-current="page"' : ''}>${tt(zh, en)}</button>`).join('')
        // The way back is where the way in was: at the foot of the left bar, in the place of the
        // sidebar's Settings entry (one spot to go in and to come out), as well as Esc.
        + `<div class="nf"><button type="button" class="back" data-act="settings-close" data-tip="${tt('回到对话', 'Back to the chat')}" data-keys="Esc">${icon('left')}<span>${tt('返回', 'Back')}</span></button></div>`
    // exactly where the entry it stands in for is (the identity's row is under that one): measured
    // while the sidebar is still in view, applied once the page is
    const entry = $('.pg-foot .set'), side = $('.pg-side')
    if (entry && side && entry.getClientRects().length && !s.classList.contains('open')) {
        const at = entry.getBoundingClientRect()
        entryAt = { left: at.left, top: at.top }
        s.style.setProperty('--back-rise', `${Math.max(0, Math.round(side.getBoundingClientRect().bottom - at.bottom - 18))}px`)
    }
    const pane = s.querySelector('.pane')
    const page = PAGES[id]
    const who = () => (page.identity && app.identities.length > 1
        ? `<div class="applies" role="radiogroup" aria-label="${tt('作用于', 'Applies to')}"><span>${tt('作用于', 'Applies to')}</span>${app.identities.map((i) => `<button type="button" role="radio" aria-checked="${i.id === (target || app.identity.id)}" data-act="settings-target" data-arg="${esc(i.id)}">${esc(i.name || i.id)}</button>`).join('')}</div>` : '')
    const head = () => `<div class="lt"><h2>${esc(sectionName(id))}</h2></div>${who()}`
    const mark = `${id}/${target || app.identity.id}`
    if (!s.classList.contains('open') || pane.dataset.page !== mark) { pane.innerHTML = head() + loading(); pane.scrollTop = 0 }
    pane.dataset.page = mark
    s.classList.add('open')
    const back = s.querySelector('nav .back')
    if (back && entryAt) {
        back.style.transform = ''
        const now = back.getBoundingClientRect()
        back.style.transform = `translate(${Math.round(entryAt.left - now.left)}px, ${Math.round(entryAt.top - now.top)}px)`
    }
    if (inNav && !again) s.querySelector('nav button.on').focus({ preventScroll: true })
    // A second drawing (something changed in the background) uses what was just read.
    if (!again) fresh = new Set()
    changed = again ? null : () => { if (app.section === id && !pane.contains(document.activeElement) && !dialogOpen() && !menuOpen()) open(app, id, true) }
    const who_id = target || app.identity.id
    const [settings, mine] = await Promise.all([read('/api/app/settings'), read('/api/agent/settings', { identity: who_id })])
    if (app.section !== id || pane.dataset.page !== mark) return
    core = settings || { values: {}, schema: {} }
    own = mine
    ctx = context(app, id)
    let html
    if (!Object.keys(core.schema || {}).length) {
        // the settings themselves were not read: the reason, and a way to try again
        seen.delete('/api/app/settings{}')
        html = problem(failed.get('/api/app/settings') || {}, { title: tt('设置没有读出来', 'The settings could not be read'), retry: 'settings' })
    } else {
        try {
            html = await page.draw(ctx)
            if (ctx.advanced.length) html += `<details class="adv"${prefs.get(`settings.advanced.${id}`, false) ? ' open' : ''}><summary>${tt('高级', 'Advanced')}<small>${tt(`${ctx.advanced.length} 项`, `${ctx.advanced.length} setting${ctx.advanced.length === 1 ? '' : 's'}`)}</small></summary>${ctx.advanced.join('')}</details>`
        } catch (error) {
            console.error(error)
            html = problem({ error: String((error && error.message) || error) }, { title: tt('这一页没有画出来', 'This page could not be drawn'), retry: 'settings' })
        }
    }
    if (app.section !== id || pane.dataset.page !== mark) return
    // the keyboard stays on the control it was on
    const at = pane.contains(document.activeElement) ? document.activeElement : null
    const sign = at ? [at.dataset.act, at.dataset.arg, (at.closest('[data-name]') || {}).dataset?.name, at.id] : null
    const top = pane.scrollTop
    pane.innerHTML = head() + html
    pane.scrollTop = top
    wireSettings(pane, (name, v) => ctx.save(name, v), (name, told) => rulesDialog(ctx, name, told))
    const more = pane.querySelector('details.adv')
    if (more) more.ontoggle = () => prefs.set(`settings.advanced.${id}`, more.open)
    if (page.wire && !pane.querySelector(':scope > .st-problem')) page.wire(ctx, pane)
    if (sign) {
        const back = $$('[data-act], .sr[data-name] .ctl > *, [id]', pane).find((n) => (sign[0] && n.dataset.act === sign[0] && n.dataset.arg === sign[1])
            || (sign[2] && n.closest('[data-name]') && n.closest('[data-name]').dataset.name === sign[2]) || (sign[3] && n.id === sign[3]))
        if (back) back.focus({ preventScroll: true })
    }
}
export function closeSettings(app) {
    const s = $('.pg-settings'), was = s.classList.contains('open')
    app.section = null; s.classList.remove('open')
    if (was && (s.contains(document.activeElement) || document.activeElement === document.body)) { const back = $('.pg-foot .set'); if (back) back.focus() }
}
// The identity in use changed: the pages follow it again.
export function follow() { target = null; seen.clear() }
export const current = () => ctx

export function actions(app) {
    on('settings', (n) => open(app, n.dataset.arg || app.section || 'general'))
    on('settings-close', () => closeSettings(app))
    on('settings-target', (n) => { target = n.dataset.arg === app.identity.id ? null : n.dataset.arg; return open(app, app.section) })
    for (const page of Object.values(PAGES)) if (page.actions) page.actions(app)
}
