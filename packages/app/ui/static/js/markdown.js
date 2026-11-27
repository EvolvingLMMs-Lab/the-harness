// Single pure Markdown + offline KaTeX math rendering pipeline (`renderMarkdown(raw)`).
// Exports both `renderMarkdown` and `markdown` (alias) so every surface shares one pipeline:
//   1. Skip fenced and inline code spans; extract $$...$$, \[...\], $...$, \(...\) using
//      Pandoc-style left/right $ boundaries and per-call random nonces while preserving
//      blockquote (`> `) and list (`- `, `1. `) structure.
//   2. Render Markdown natively via ESM Marked (with highlight.js + code header/copy +
//      clickable file paths + scrollable table wrapper; decoding Marked v18 pre-escaped codespans).
//   3. Restore math placeholders with offline vendored KaTeX (`throwOnError: false`, `trust: false`)
//      wrapped in horizontally scrollable `.math-block` containers for display math.
//   4. Sanitize final HTML via ESM DOMPurify when DOM is available, preserving KaTeX HTML/MathML/SVG
//      and code-block copy buttons while stripping XSS.
import { Marked } from '../vendor/marked.js'
import DOMPurify from '../vendor/dompurify.js'

let defaultKatex = (typeof globalThis !== 'undefined' && globalThis.katex) || null
if (!defaultKatex && typeof process !== 'undefined' && process.versions && process.versions.node) {
    const nodeMod = 'node:module'
    const { createRequire } = await import(nodeMod)
    defaultKatex = createRequire(import.meta.url)('../vendor/katex/katex.min.js')
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const unescBasic = (s) => String(s ?? '').replace(/&(?:#39|apos|quot|gt|lt|amp);/g, (m) => ({
    '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&apos;': "'",
}[m] || m))

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

const PURIFY_CONFIG = {
    USE_PROFILES: { html: true, mathMl: true, svg: true, svgFilters: true },
    ADD_TAGS: ['button', 'semantics', 'annotation'],
    ADD_ATTR: ['data-act', 'data-arg', 'target', 'rel', 'type', 'encoding', 'xmlns', 'aria-hidden', 'focusable'],
}

function isEscaped(src, idx) {
    let slashes = 0
    for (let i = idx - 1; i >= 0 && src[i] === '\\'; i--) slashes++
    return (slashes % 2) === 1
}

function isSpace(ch) {
    return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r'
}

function makeNonce() {
    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
        const bytes = new Uint8Array(6)
        crypto.getRandomValues(bytes)
        return Array.from(bytes, (b) => b.toString(36).padStart(2, '0')).join('')
    }
    return Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 6)
}

function currentLinePrefix(out) {
    const nl = out.lastIndexOf('\n')
    return nl === -1 ? out : out.slice(nl + 1)
}

function cleanDisplayInner(inner, linePrefix) {
    const bq = linePrefix.match(/^(\s*(?:>\s*)+)/)
    if (!bq) return inner.trim()
    return inner.split('\n').map((ln) => ln.replace(/^\s*(?:>\s*)+/, '')).join('\n').trim()
}

function extractMath(raw) {
    const src = String(raw ?? '').replace(/\r\n?/g, '\n')
    const blocks = []
    const nonce = makeNonce()
    const tokenOf = (idx, display) => (display ? `HMATHB${nonce}I${idx}E` : `HMATHI${nonce}I${idx}E`)
    const pushMath = (tex, display) => {
        const idx = blocks.length
        blocks.push({ tex, display })
        return tokenOf(idx, display)
    }

    let out = ''
    let i = 0
    let atLineStart = true
    const n = src.length

    while (i < n) {
        if (atLineStart) {
            let j = i
            while (j < n && (src[j] === ' ' || src[j] === '\t')) j++
            const ch = src[j]
            if (ch === '`' || ch === '~') {
                let k = j
                while (k < n && src[k] === ch) k++
                const fenceLen = k - j
                if (fenceLen >= 3) {
                    const nl = src.indexOf('\n', k)
                    if (nl === -1) { out += src.slice(i); break }
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

        const emitDisplay = (inner) => {
            const prefix = currentLinePrefix(out)
            const tex = cleanDisplayInner(inner, prefix)
            if (!tex) return false
            const tok = pushMath(tex, true)
            const inContainer = /^\s*>/.test(prefix) || /^\s*(?:[-*+]|\d+[.)])\s+/.test(prefix) || /^\s{2,}/.test(prefix)
            if (inContainer) {
                out += tok
            } else {
                const needLead = out.length > 0 && !out.endsWith('\n\n')
                out += `${needLead ? '\n\n' : ''}${tok}\n\n`
            }
            return true
        }

        if (ch === '\\' && src[i + 1] === '[' && !isEscaped(src, i)) {
            let k = i + 2, found = -1
            while (k < n - 1) {
                if (src[k] === '\\' && src[k + 1] === ']' && !isEscaped(src, k)) { found = k; break }
                k++
            }
            if (found !== -1 && emitDisplay(src.slice(i + 2, found))) {
                i = found + 2; atLineStart = out.endsWith('\n'); continue
            }
        }

        if (ch === '\\' && src[i + 1] === '(' && !isEscaped(src, i)) {
            let k = i + 2, found = -1
            while (k < n - 1) {
                if (src[k] === '\\' && src[k + 1] === ')' && !isEscaped(src, k)) { found = k; break }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 2, found).trim()
                if (inner) { out += pushMath(inner, false); i = found + 2; atLineStart = false; continue }
            }
        }

        if (ch === '$' && src[i + 1] === '$' && !isEscaped(src, i)) {
            let k = i + 2, found = -1
            while (k < n - 1) {
                if (src[k] === '$' && src[k + 1] === '$' && !isEscaped(src, k)) { found = k; break }
                k++
            }
            if (found !== -1 && emitDisplay(src.slice(i + 2, found))) {
                i = found + 2; atLineStart = out.endsWith('\n'); continue
            }
            out += '$$'; i += 2; atLineStart = false; continue
        }

        const prevCh = i > 0 ? src[i - 1] : ''
        if (ch === '$' && src[i + 1] !== '$' && !isEscaped(src, i) && i + 1 < n && !isSpace(src[i + 1]) && !/[A-Za-z0-9_]/.test(prevCh)) {
            let k = i + 1, found = -1
            while (k < n) {
                if (src[k] === '\n' && src[k + 1] === '\n') break
                if (src[k] === '`' && !isEscaped(src, k)) break
                if (src[k] === '$' && !isEscaped(src, k)) {
                    if (src[k + 1] === '$') break
                    const prev = src[k - 1], next = src[k + 1] || ''
                    if (!isSpace(prev) && !/[A-Za-z0-9_]/.test(next)) { found = k; break }
                    break
                }
                k++
            }
            if (found !== -1) {
                const inner = src.slice(i + 1, found).trim()
                if (inner) { out += pushMath(inner, false); i = found + 1; atLineStart = false; continue }
            }
        }

        out += ch
        atLineStart = (ch === '\n')
        i++
    }
    return { text: out, blocks, tokenOf }
}

function renderCodeBlock(body, lang) {
    const cleanLang = String(lang || '').trim().split(/\s+/)[0] || ''
    let rendered = esc(body), cls = ''
    if (typeof window !== 'undefined' && window.hljs) {
        try {
            if (cleanLang && window.hljs.getLanguage(cleanLang)) {
                rendered = window.hljs.highlight(body, { language: cleanLang, ignoreIllegals: true }).value
                cls = ' class="hljs"'
            } else if (!cleanLang && body.length < 20000) {
                rendered = window.hljs.highlightAuto(body).value
                cls = ' class="hljs"'
            }
        } catch { /* fallback */ }
    }
    return `<div class="cb"><div class="cb-h"><span class="cb-lang">${esc(cleanLang || labelCode())}</span><button type="button" data-act="copy-code">${esc(labelCopy())}</button></div><pre><code${cls}>${rendered}</code></pre></div>`
}

function renderCodespan(codeText) {
    const text = String(codeText ?? ''), trimmed = text.trim(), fm = trimmed.match(FILE_PATH)
    if (fm) return `<button type="button" class="md-file" data-act="open-file" data-arg="${esc(fm[1])}"><code>${esc(trimmed)}</code></button>`
    return `<code>${esc(text)}</code>`
}

function decodeCodespanToken(token) {
    if (typeof token === 'string') return unescBasic(token)
    return unescBasic(token && token.text != null ? token.text : '')
}

const markedInstance = new Marked({
    gfm: true,
    breaks: false,
    renderer: {
        code(token) { return renderCodeBlock(typeof token === 'string' ? token : (token.text || ''), typeof token === 'string' ? '' : (token.lang || '')) },
        codespan(token) { return renderCodespan(decodeCodespanToken(token)) },
        table(token) {
            const header = `<tr>${(token.header || []).map((cell) => `<th${cell.align ? ` style="text-align:${cell.align}"` : ''}>${this.parser.parseInline(cell.tokens || [])}</th>`).join('')}</tr>`
            const rows = (token.rows || []).map((row) => `<tr>${row.map((cell) => `<td${cell.align ? ` style="text-align:${cell.align}"` : ''}>${this.parser.parseInline(cell.tokens || [])}</td>`).join('')}</tr>`).join('')
            return `<div class="tbl"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div>`
        },
        link(token) {
            const href = String((token && token.href) || ''), text = this.parser.parseInline(token.tokens || [])
            if (!SAFE_HREF.test(href)) return text
            return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`
        },
        html() { return '' },
    },
})

function restoreMath(html, blocks, tokenOf, katexLib) {
    if (!blocks.length) return html
    const lib = katexLib || (typeof globalThis !== 'undefined' && globalThis.katex) || defaultKatex
    let out = html
    for (let idx = 0; idx < blocks.length; idx++) {
        const { tex, display } = blocks[idx]
        const placeholder = tokenOf(idx, display)
        let rendered
        if (lib && typeof lib.renderToString === 'function') {
            try { rendered = lib.renderToString(tex, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore' }) }
            catch { rendered = `<code>${esc(display ? `$$${tex}$$` : `$${tex}$`)}</code>` }
        } else {
            rendered = `<code>${esc(display ? `$$${tex}$$` : `$${tex}$`)}</code>`
        }
        const wrapped = display ? `<div class="math-block">${rendered}</div>` : `<span class="math-inline">${rendered}</span>`
        if (display) out = out.replace(new RegExp(`<p>\\s*${placeholder}\\s*</p>`, 'g'), wrapped)
        out = out.split(placeholder).join(wrapped)
    }
    return out
}

function sanitizeHtml(html, purifyLib) {
    const lib = purifyLib || DOMPurify
    if (lib && lib.isSupported && typeof lib.sanitize === 'function') return lib.sanitize(html, PURIFY_CONFIG)
    return html
}

export function renderMarkdown(raw, opts = {}) {
    const { text, blocks, tokenOf } = extractMath(raw)
    const parsed = String(markedInstance.parse(text) || '')
    const withMath = restoreMath(parsed, blocks, tokenOf, opts.katex)
    return sanitizeHtml(withMath, opts.purify)
}

export const markdown = renderMarkdown
