// What a setting is called on the page: its title, what it is for, and the name of each of
// its choices, in the page's language. They are the host's: every setting is described by
// the package that owns it (GET /api/app/settings → schema[section][key], and
// GET /api/agent/settings → schema["section.key"] for an identity's own):
//
//     {name, title: {en, zh}, about: {en, zh}, type, choices: [value…] | null,
//      labels: {value: {en, zh}}, options: [{value, en, zh}], scope, bounds, …}
//
// The page keeps no copy of these texts. A package that describes a setting only in part
// still reads well: a missing title is the key made readable, a missing choice name the value.
import { language } from './i18n.js'

// A text of the host in the page's language: {en, zh} or one string for both.
export const said = (given) => (given && typeof given === 'object' ? given[language()] || given.en || given.zh || '' : given || '')
// a_key_like_this → "A key like this"
export const readable = (text) => { const s = String(text ?? '').replace(/[_.]+/g, ' ').trim(); return s ? s.charAt(0).toUpperCase() + s.slice(1) : '' }

export const settingTitle = (name, spec = {}, given = '') => given || said(spec.title) || readable(String(name).split('.').pop())
export const settingAbout = (spec = {}, given) => (given !== undefined && given !== null ? given : said(spec.about) || said(spec.description))
// The choices of a setting as [{value, label}]; `only` narrows them to the values a page offers.
export function choicesOf(spec = {}, only) {
    const named = (value) => said((spec.labels || {})[value]) || readable(value)
    const rows = Array.isArray(spec.options) ? spec.options.map((o) => ({ value: o.value, label: said(o) || named(o.value) }))
        : Array.isArray(spec.choices) ? spec.choices.map((c) => (c && typeof c === 'object' ? { value: c.value, label: said(c) || named(c.value) } : { value: c, label: named(c) }))
            : (spec.type || spec.kind) === 'choice' && Array.isArray(spec.bounds) ? spec.bounds.map((value) => ({ value, label: named(value) })) : null
    if (!only) return rows
    return only.map((value) => (rows || []).find((r) => String(r.value) === String(value)) || { value, label: named(value) })
}
export const choiceLabel = (spec, value) => ((choicesOf(spec) || []).find((c) => String(c.value) === String(value)) || { label: readable(value) }).label
