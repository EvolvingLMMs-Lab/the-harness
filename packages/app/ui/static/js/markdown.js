// A reply as Markdown: headings, paragraphs, lists, quotes, rules, tables, fenced code with
// its language and a Copy button, and inside a line code, bold, italic, strike-through and
// links. Line breaks follow Markdown, as in Hermes Desktop's chat: two trailing spaces (or a
// backslash) break the line, an ordinary newline does not. Everything is escaped first and
// only the tags written here are produced; a link opens only http, https and mailto.
// A reply that is still being written renders as far as it goes: an open code fence is a
// code block to the end.
import { esc, tt } from './i18n.js'

const FENCE = /^(\s*)(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const DIVIDER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/
const indent = (line) => line.match(/^\s*/)[0].replace(/\t/g, '    ').length

const FILE_PATH = /^([A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]{1,10}|[A-Za-z0-9_.-]+\.(?:py|js|mjs|ts|tsx|jsx|rs|go|c|h|cpp|java|json|toml|ya?ml|md|css|html|sh|ps1|sql))(?::(\d+))?$/

function inline(text) {
    const kept = []
    const keep = (html) => `\u0000${kept.push(html) - 1}\u0000`
    // code first: nothing inside it is formatting; project file paths become clickable links
    let s = String(text).replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (_, ticks, code) => {
        const trimmed = code.trim()
        const fm = trimmed.match(FILE_PATH)
        if (fm) return keep(`<button type="button" class="md-file" data-act="open-file" data-arg="${esc(fm[1])}"><code>${esc(trimmed)}</code></button>`)
        return keep(`<code>${esc(trimmed)}</code>`)
    })
    s = esc(s)
    const link = (href, label) => (/^(https?:\/\/|mailto:)/i.test(href) ? keep(`<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`) : label)
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (_, label, href) => link(href, emphasis(label)))
    s = s.replace(/\bhttps?:\/\/[^\s<\u0000]+/g, (found) => {
        const tail = (found.match(/[.,;:!?)\]}'"。，；：！？）】]+$/) || [''])[0]
        const href = tail ? found.slice(0, -tail.length) : found
        return link(href, href) + tail
    })
    s = emphasis(s)
    return s.replace(/\u0000(\d+)\u0000/g, (_, n) => kept[+n])
}
function emphasis(s) {
    return s.replace(/\*\*([^\s*](?:[^*]*[^\s*])?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^\w])__([^\s_](?:[^_]*[^\s_])?)__(?!\w)/g, '$1<strong>$2</strong>')
        .replace(/\*([^\s*](?:[^*]*[^\s*])?)\*/g, '<em>$1</em>')
        .replace(/(^|[^\w])_([^\s_](?:[^_]*[^\s_])?)_(?!\w)/g, '$1<em>$2</em>')
        .replace(/~~([^\s~](?:[^~]*[^\s~])?)~~/g, '<del>$1</del>')
}

function code(body, lang) {
    let rendered = esc(body)
    let cls = ''
    if (typeof window !== 'undefined' && window.hljs) {
        try {
            if (lang && window.hljs.getLanguage(lang)) {
                rendered = window.hljs.highlight(body, { language: lang, ignoreIllegals: true }).value
                cls = ' class="hljs"'
            } else if (!lang && body.length < 20000) {
                rendered = window.hljs.highlightAuto(body).value
                cls = ' class="hljs"'
            }
        } catch { /* fallback to escaped plain text */ }
    }
    return `<div class="cb"><div class="cb-h"><span>${esc(lang || tt('代码', 'code'))}</span><button type="button" data-act="copy-code">${esc(tt('复制', 'Copy'))}</button></div><pre><code${cls}>${rendered}</code></pre></div>`
}

function cells(line) {
    const row = line.trim().replace(/^\|/, '').replace(/\|$/, '')
    return row.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'))
}

export function markdown(source) {
    const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n')
    const out = []
    let i = 0
    // whether a line begins something other than more of a paragraph
    const begins = (n) => {
        const line = lines[n]
        return FENCE.test(line) || HEAD.test(line) || RULE.test(line) || ITEM.test(line) || /^\s*>/.test(line)
            || (line.includes('|') && n + 1 < lines.length && DIVIDER.test(lines[n + 1]) && lines[n + 1].includes('-'))
    }
    while (i < lines.length) {
        const line = lines[i]
        if (!line.trim()) { i++; continue }
        let m = line.match(FENCE)
        if (m) {
            const body = []
            i++
            while (i < lines.length && !lines[i].trim().startsWith(m[2])) body.push(lines[i++].slice(Math.min(m[1].length, indent(lines[i - 1]))))
            i++
            out.push(code(body.join('\n'), m[3]))
            continue
        }
        m = line.match(HEAD)
        if (m) { out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); i++; continue }
        if (RULE.test(line)) { out.push('<hr>'); i++; continue }
        if (line.includes('|') && i + 1 < lines.length && DIVIDER.test(lines[i + 1]) && lines[i + 1].includes('-')) {
            const head = cells(line), align = cells(lines[i + 1]).map((c) => (/^:-+:$/.test(c) ? 'center' : /-:$/.test(c) ? 'right' : ''))
            const at = (n) => (align[n] ? ` style="text-align:${align[n]}"` : '')
            i += 2
            const body = []
            while (i < lines.length && lines[i].trim() && lines[i].includes('|')) body.push(cells(lines[i++]))
            out.push(`<div class="tbl"><table><thead><tr>${head.map((c, n) => `<th${at(n)}>${inline(c)}</th>`).join('')}</tr></thead><tbody>`
                + body.map((r) => `<tr>${head.map((_, n) => `<td${at(n)}>${inline(r[n] ?? '')}</td>`).join('')}</tr>`).join('') + `</tbody></table></div>`)
            continue
        }
        if (/^\s*>/.test(line)) {
            const quoted = []
            while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ''))
            out.push(`<blockquote>${markdown(quoted.join('\n'))}</blockquote>`)
            continue
        }
        m = line.match(ITEM)
        if (m) {
            const base = m[1].length, ordered = /\d/.test(m[2])
            const first = ordered ? parseInt(m[2], 10) : 1
            const items = []
            while (i < lines.length) {
                const item = lines[i].match(ITEM)
                if (!item || Math.abs(item[1].length - base) > 1 || /\d/.test(item[2]) !== ordered) break
                const inside = [], deep = item[1].length + item[2].length + 1
                i++
                // what belongs to the item: lines indented under it, blank lines between them
                while (i < lines.length) {
                    if (!lines[i].trim()) {
                        let next = i + 1
                        while (next < lines.length && !lines[next].trim()) next++
                        if (next < lines.length && indent(lines[next]) > base + 1) { inside.push(''); i++; continue }
                        break
                    }
                    if (indent(lines[i]) <= base + 1) break
                    inside.push(lines[i].replace(/\t/g, '    ').slice(Math.min(deep, indent(lines[i]))))
                    i++
                }
                const box = item[3].match(/^\[([ xX])\]\s+(.*)$/)
                const text = box ? `<span class="box">${box[1] === ' ' ? '☐' : '☑'}</span> ${inline(box[2])}` : inline(item[3])
                items.push(`<li>${text}${inside.length ? markdown(inside.join('\n')) : ''}</li>`)
            }
            out.push(ordered ? `<ol${first !== 1 ? ` start="${first}"` : ''}>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`)
            continue
        }
        const para = [line]
        i++
        while (i < lines.length && lines[i].trim() && !begins(i)) para.push(lines[i++])
        out.push(`<p>${para.map((l, n) => inline(l.replace(/(\s{2,}|\\)$/, '').trimStart()) + (n < para.length - 1 ? (/(\s{2,}|\\)$/.test(l) ? '<br>' : '\n') : '')).join('')}</p>`)
    }
    return out.join('')
}
