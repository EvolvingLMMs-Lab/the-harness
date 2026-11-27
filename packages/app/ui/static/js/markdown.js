// Single pure Markdown + offline KaTeX math rendering pipeline (`renderMarkdown(raw)`).
// Exports both `renderMarkdown` and `markdown` (alias) so every surface shares one pipeline:
//   1. Skip fenced and inline code spans; extract $$...$$, \[...\], $...$, \(...\) using
//      Pandoc-style $ boundaries (protecting $1.50, $0.50, $PATH, and unclosed streaming $/$).
//   2. Render Markdown via Marked (with highlight.js + code header/copy + clickable file paths
//      + scrollable table wrapper) and sanitize via DOMPurify (or strict fallback in headless/Node).
//   3. Restore math placeholders with offline vendored KaTeX (`throwOnError: false`, `trust: false`)
//      wrapped in horizontally scrollable `.math-block` containers for display math.
import katex from '../vendor/katex/katex.mjs'

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const labelCopy = () => {
    try {
        const lang = (typeof document !== 'undefined' && document.documentElement.lang) || ''
        return lang.toLowerCase().startsWith('zh') ? '复制' : 'Copy'
    } catch { return 'Copy' }
}
const labelCode = () => {
    try {
        const lang = (typeof document !== 'undefined' && document.documentElement.lang) || ''
        return lang.toLowerCase().startsWith('zh') ? '代码' : 'code'
    } catch { return 'code' }
}

const FILE_PATH = /^([A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]{1,10}|[A-Za-z0-9_.-]+\.(?:py|js|mjs|ts|tsx|jsx|rs|go|c|h|cpp|java|json|toml|ya?ml|md|css|html|sh|ps1|sql))(?::(\d+))?$/
const SAFE_HREF = /^(https?:\/\/|mailto:)/i

function isEscaped(src, idx) {
    let slashes = 0
    for (let i = idx - 1; i >= 0 && src[i] === '\\'; i--) slashes++
    return (slashes % 2) === 1
}

function isSpace(ch) {
    return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r'
}

// Extract math outside fenced code blocks and inline code spans into collision-free placeholders.
function extractMath(raw) {
    const src = String(raw ?? '').replace(/\r\n?/g, '\n')
    const blocks = []
    const tokenOf = (idx, display) => (display ? `HARNESSMATHBLOCK${idx}END` : `HARNESSMATHINLINE${idx}END`)
    const pushMath = (tex, display) => {
        const idx = blocks.length
        blocks.push({ tex: tex.trim(), display })
        return tokenOf(idx, display)
    }

    let out = ''
    let i = 0
    let atLineStart = true
    const n = src.length

    while (i < n) {
        // 1. Fenced code block at start of line (``` or ~~~)
        if (atLineStart) {
            let j = i
            while (j < n && (src[j] === ' ' || src[j] === '\t')) j++
            const ch = src[j]
            if (ch === '`' || ch === '~') {
                let k = j
                while (k < n && src[k] === ch) k++
                const fenceLen = k - j
                if (fenceLen >= 3) {
                    let nl = src.indexOf('\n', k)
                    if (nl === -1) {
                        out += src.slice(i)
                        break
                    }
                    let pos = nl + 1
                    let closed = false
                    while (pos < n) {
                        const lineEnd = src.indexOf('\n', pos)
                        const end = lineEnd === -1 ? n : lineEnd
                        const trimmed = src.slice(pos, end).trim()
                        if (trimmed.length >= fenceLen && trimmed.startsWith(ch.repeat(fenceLen)) && /^[`~]+$/.test(trimmed)) {
                            const nextPos = lineEnd === -1 ? n : lineEnd + 1
                            out += src.slice(i, nextPos)
                            i = nextPos
                            atLineStart = true
                            closed = true
                            break
                        }
                        if (lineEnd === -1) break
                        pos = lineEnd + 1
                    }
                    if (closed) continue
                    out += src.slice(i)
                    break
                }
            }
        }

        const ch = src[i]

        // 2. Inline code span (`...`)
        if (ch === '`' && !isEscaped(src, i)) {
            let k = i
            while (k < n && src[k] === '`') k++
            const ticks = src.slice(i, k)
            const close = src.indexOf(ticks, k)
            if (close !== -1) {
                const seg = src.slice(i, close + ticks.length)
                out += seg
                i = close + ticks.length
                atLineStart = seg.endsWith('\n')
                continue
            }
            out += ticks
            i = k
            atLineStart = false
            continue
        }

        // 3. Display math: \[ ... \]
        if (ch === '\\' && src[i + 1] === '[' && !isEscaped(src, i)) {
            let k = i + 2
            let found = -1
            while (k < n - 1) {
                if (src[k] === '\\' && src[k + 1] === ']' && !isEscaped(src, k)) {
                    found = k
                    break
                }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 2, found)
                if (inner.trim()) {
                    out += `\n\n${pushMath(inner, true)}\n\n`
                    i = found + 2
                    atLineStart = false
                    continue
                }
            }
        }

        // 4. Inline math: \( ... \)
        if (ch === '\\' && src[i + 1] === '(' && !isEscaped(src, i)) {
            let k = i + 2
            let found = -1
            while (k < n - 1) {
                if (src[k] === '\\' && src[k + 1] === ')' && !isEscaped(src, k)) {
                    found = k
                    break
                }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 2, found)
                if (inner.trim()) {
                    out += pushMath(inner, false)
                    i = found + 2
                    atLineStart = false
                    continue
                }
            }
        }

        // 5. Display math: $$ ... $$ (unclosed streaming $$ stays literal)
        if (ch === '$' && src[i + 1] === '$' && !isEscaped(src, i)) {
            let k = i + 2
            let found = -1
            while (k < n - 1) {
                if (src[k] === '$' && src[k + 1] === '$' && !isEscaped(src, k)) {
                    found = k
                    break
                }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 2, found)
                if (inner.trim()) {
                    out += `\n\n${pushMath(inner, true)}\n\n`
                    i = found + 2
                    atLineStart = false
                    continue
                }
            }
            out += '$$'
            i += 2
            atLineStart = false
            continue
        }

        // 6. Inline math: Pandoc-style $...$
        if (ch === '$' && src[i + 1] !== '$' && !isEscaped(src, i) && i + 1 < n && !isSpace(src[i + 1])) {
            let k = i + 1
            let found = -1
            while (k < n) {
                if (src[k] === '\n' && src[k + 1] === '\n') break
                if (src[k] === '`' && !isEscaped(src, k)) break
                if (src[k] === '$' && !isEscaped(src, k)) {
                    if (src[k + 1] === '$') break
                    const prev = src[k - 1]
                    const next = src[k + 1] || ''
                    if (!isSpace(prev) && !/[A-Za-z0-9_]/.test(next)) {
                        found = k
                        break
                    }
                    break
                }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 1, found)
                if (inner.trim()) {
                    out += pushMath(inner, false)
                    i = found + 1
                    atLineStart = false
                    continue
                }
            }
        }

        out += ch
        atLineStart = (ch === '\n')
        i++
    }

    return { text: out, blocks }
}

function renderCodeBlock(body, lang) {
    const cleanLang = String(lang || '').trim().split(/\s+/)[0] || ''
    let rendered = esc(body)
    let cls = ''
    if (typeof window !== 'undefined' && window.hljs) {
        try {
            if (cleanLang && window.hljs.getLanguage(cleanLang)) {
                rendered = window.hljs.highlight(body, { language: cleanLang, ignoreIllegals: true }).value
                cls = ' class="hljs"'
            } else if (!cleanLang && body.length < 20000) {
                rendered = window.hljs.highlightAuto(body).value
                cls = ' class="hljs"'
            }
        } catch { /* fallback to escaped plain text */ }
    }
    return `<div class="cb"><div class="cb-h"><span class="cb-lang">${esc(cleanLang || labelCode())}</span><button type="button" data-act="copy-code">${esc(labelCopy())}</button></div><pre><code${cls}>${rendered}</code></pre></div>`
}

function renderCodespan(codeText) {
    const trimmed = String(codeText || '').trim()
    const fm = trimmed.match(FILE_PATH)
    if (fm) {
        return `<button type="button" class="md-file" data-act="open-file" data-arg="${esc(fm[1])}"><code>${esc(trimmed)}</code></button>`
    }
    return `<code>${esc(trimmed)}</code>`
}

function stripRawHtml(s) {
    return String(s || '')
        .replace(/<(script|style|iframe|object|embed|svg)[\s\S]*?<\/\1>/gi, '')
        .replace(/<\/?(?:script|style|iframe|object|embed|img|form|input|link|meta|base|body|html)\b[^>]*>/gi, '')
}

const FENCE = /^(\s*)(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const DIVIDER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/
const indentOf = (line) => line.match(/^\s*/)[0].replace(/\t/g, '    ').length

function renderInlinePure(text) {
    const kept = []
    const keep = (html) => `\u0000${kept.push(html) - 1}\u0000`
    let s = String(text).replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (_, _ticks, code) => keep(renderCodespan(code)))
    s = esc(stripRawHtml(s))
    const link = (href, label) => (SAFE_HREF.test(href) ? keep(`<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`) : label)
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (_, label, href) => link(href, emphasisPure(label)))
    s = s.replace(/\bhttps?:\/\/[^\s<\u0000]+/g, (found) => {
        const tail = (found.match(/[.,;:!?)\]}'"。，；：！？）】]+$/) || [''])[0]
        const href = tail ? found.slice(0, -tail.length) : found
        return link(href, href) + tail
    })
    s = emphasisPure(s)
    return s.replace(/\u0000(\d+)\u0000/g, (_, n) => kept[+n])
}

function emphasisPure(s) {
    return s.replace(/\*\*([^\s*](?:[^*]*[^\s*])?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^\w])__([^\s_](?:[^_]*[^\s_])?)__(?!\w)/g, '$1<strong>$2</strong>')
        .replace(/\*([^\s*](?:[^*]*[^\s*])?)\*/g, '<em>$1</em>')
        .replace(/(^|[^\w])_([^\s_](?:[^_]*[^\s_])?)_(?!\w)/g, '$1<em>$2</em>')
        .replace(/~~([^\s~](?:[^~]*[^\s~])?)~~/g, '<del>$1</del>')
}

function cellsPure(line) {
    const row = line.trim().replace(/^\|/, '').replace(/\|$/, '')
    return row.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'))
}

function parsePureMarkdown(source) {
    const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n')
    const out = []
    let i = 0
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
            while (i < lines.length && !lines[i].trim().startsWith(m[2])) {
                body.push(lines[i++].slice(Math.min(m[1].length, indentOf(lines[i - 1]))))
            }
            i++
            out.push(renderCodeBlock(body.join('\n'), m[3]))
            continue
        }
        m = line.match(HEAD)
        if (m) { out.push(`<h${m[1].length}>${renderInlinePure(m[2])}</h${m[1].length}>`); i++; continue }
        if (RULE.test(line)) { out.push('<hr>'); i++; continue }
        if (line.includes('|') && i + 1 < lines.length && DIVIDER.test(lines[i + 1]) && lines[i + 1].includes('-')) {
            const head = cellsPure(line)
            const align = cellsPure(lines[i + 1]).map((c) => (/^:-+:$/.test(c) ? 'center' : /-:$/.test(c) ? 'right' : ''))
            const at = (n) => (align[n] ? ` style="text-align:${align[n]}"` : '')
            i += 2
            const body = []
            while (i < lines.length && lines[i].trim() && lines[i].includes('|')) body.push(cellsPure(lines[i++]))
            out.push(`<div class="tbl"><table><thead><tr>${head.map((c, n) => `<th${at(n)}>${renderInlinePure(c)}</th>`).join('')}</tr></thead><tbody>`
                + body.map((r) => `<tr>${head.map((_, n) => `<td${at(n)}>${renderInlinePure(r[n] ?? '')}</td>`).join('')}</tr>`).join('') + '</tbody></table></div>')
            continue
        }
        if (/^\s*>/.test(line)) {
            const quoted = []
            while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ''))
            out.push(`<blockquote>${parsePureMarkdown(quoted.join('\n'))}</blockquote>`)
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
                while (i < lines.length) {
                    if (!lines[i].trim()) {
                        let next = i + 1
                        while (next < lines.length && !lines[next].trim()) next++
                        if (next < lines.length && indentOf(lines[next]) > base + 1) { inside.push(''); i++; continue }
                        break
                    }
                    if (indentOf(lines[i]) <= base + 1) break
                    inside.push(lines[i].replace(/\t/g, '    ').slice(Math.min(deep, indentOf(lines[i]))))
                    i++
                }
                const box = item[3].match(/^\[([ xX])\]\s+(.*)$/)
                const text = box ? `<span class="box">${box[1] === ' ' ? '☐' : '☑'}</span> ${renderInlinePure(box[2])}` : renderInlinePure(item[3])
                items.push(`<li>${text}${inside.length ? parsePureMarkdown(inside.join('\n')) : ''}</li>`)
            }
            out.push(ordered ? `<ol${first !== 1 ? ` start="${first}"` : ''}>${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`)
            continue
        }
        const para = [line]
        i++
        while (i < lines.length && lines[i].trim() && !begins(i)) para.push(lines[i++])
        out.push(`<p>${para.map((l, n) => renderInlinePure(l.replace(/(\s{2,}|\\)$/, '').trimStart()) + (n < para.length - 1 ? (/(\s{2,}|\\)$/.test(l) ? '<br>' : '\n') : '')).join('')}</p>`)
    }
    return out.join('')
}

function parseWithMarked(masked) {
    const markedLib = typeof window !== 'undefined' && window.marked ? window.marked : null
    const purifyLib = typeof window !== 'undefined' && window.DOMPurify ? window.DOMPurify : null
    if (!markedLib || typeof markedLib.Marked !== 'function') {
        return parsePureMarkdown(masked)
    }
    try {
        const renderer = {
            code(token) {
                const body = typeof token === 'string' ? token : (token.text || '')
                const lang = typeof token === 'string' ? '' : (token.lang || '')
                return renderCodeBlock(body, lang)
            },
            codespan(token) {
                const raw = typeof token === 'string' ? token : (token.text || '')
                return renderCodespan(raw)
            },
            table(token) {
                const header = `<tr>${(token.header || []).map((cell) => {
                    const align = cell.align ? ` style="text-align:${cell.align}"` : ''
                    return `<th${align}>${this.parser.parseInline(cell.tokens || [])}</th>`
                }).join('')}</tr>`
                const rows = (token.rows || []).map((row) => `<tr>${row.map((cell) => {
                    const align = cell.align ? ` style="text-align:${cell.align}"` : ''
                    return `<td${align}>${this.parser.parseInline(cell.tokens || [])}</td>`
                }).join('')}</tr>`).join('')
                return `<div class="tbl"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div>`
            },
            link(token) {
                const href = String((token && token.href) || '')
                const text = this.parser.parseInline(token.tokens || [])
                if (!SAFE_HREF.test(href)) return text
                return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`
            },
            html() {
                return ''
            },
        }
        const instance = new markedLib.Marked({ gfm: true, breaks: false, renderer })
        const rendered = String(instance.parse(masked) || '')
        if (purifyLib && typeof purifyLib.sanitize === 'function') {
            return purifyLib.sanitize(rendered, {
                ADD_TAGS: ['button'],
                ADD_ATTR: ['data-act', 'data-arg', 'target', 'rel', 'type'],
            })
        }
        return rendered
    } catch {
        return parsePureMarkdown(masked)
    }
}

function restoreMath(html, blocks, katexLib) {
    if (!blocks.length) return html
    const lib = katexLib || katex
    let out = html
    for (let idx = 0; idx < blocks.length; idx++) {
        const { tex, display } = blocks[idx]
        const placeholder = display ? `HARNESSMATHBLOCK${idx}END` : `HARNESSMATHINLINE${idx}END`
        let rendered
        try {
            rendered = lib.renderToString(tex, {
                displayMode: display,
                throwOnError: false,
                trust: false,
                strict: 'ignore',
            })
        } catch {
            rendered = `<code>${esc(display ? `$$${tex}$$` : `$${tex}$`)}</code>`
        }
        const wrapped = display
            ? `<div class="math-block">${rendered}</div>`
            : `<span class="math-inline">${rendered}</span>`
        if (display) {
            out = out.replace(new RegExp(`<p>\\s*${placeholder}\\s*</p>`, 'g'), wrapped)
        }
        out = out.split(placeholder).join(wrapped)
    }
    return out
}

export function renderMarkdown(raw, opts = {}) {
    const { text, blocks } = extractMath(raw)
    const html = parseWithMarked(text)
    return restoreMath(html, blocks, opts.katex)
}

export const markdown = renderMarkdown
