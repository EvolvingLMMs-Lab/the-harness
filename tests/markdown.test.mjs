import assert from 'node:assert/strict'
import test from 'node:test'
import { renderMarkdown, markdown } from '../packages/app/ui/static/js/markdown.js'

test('renders inline and display LaTeX with subscripts, row breaks, and operators', () => {
    assert.equal(markdown, renderMarkdown)
    const inlineHtml = renderMarkdown('Weight is $w_{i,j}$ and \\(a \\ge b\\).')
    assert.match(inlineHtml, /class="katex"/)
    assert.doesNotMatch(inlineHtml, /<em>/)
    assert.match(inlineHtml, /class="math-inline"/)

    const blockHtml = renderMarkdown('Matrix:\n\n$$\\begin{pmatrix} a \\\\ b \\end{pmatrix} \\ge 0$$\n\nAlso:\n\n\\[w_{i,j} = 1\\]')
    assert.match(blockHtml, /class="math-block"/)
    assert.match(blockHtml, /class="katex-display"/)
    assert.match(blockHtml, /class="katex"/)
})

test('does not double-escape angle brackets or ampersands in Marked v18 inline codespans', () => {
    const html = renderMarkdown('Compare `a < b && c > d` and `x === "y"` carefully.')
    assert.match(html, /<code>a &lt; b &amp;&amp; c &gt; d<\/code>/)
    assert.doesNotMatch(html, /&amp;lt;|&amp;gt;|&amp;amp;/)
    assert.match(html, /<code>x === &quot;y&quot;<\/code>/)
})

test('leaves $ inside inline and fenced code untouched and adds code header + copy button', () => {
    const html = renderMarkdown("Inline `$w_{i,j}$` and block:\n\n```python\nprice = '$1.50'\nmath = '$x + y$'\n```")
    assert.doesNotMatch(html, /class="katex"/)
    assert.match(html, /\$w_\{i,j\}\$/)
    assert.match(html, /class="cb"/)
    assert.match(html, /class="cb-lang">python</)
    assert.match(html, /data-act="copy-code"/)
})

test('enforces left and right $ boundaries so currency, env vars, and mid-word $ stay literal', () => {
    const html = renderMarkdown('Apples cost $1.50 and pears cost $0.50. Check $PATH, foo$x$, price$1$, and var$2$.')
    assert.doesNotMatch(html, /class="katex"/)
    assert.match(html, /\$1\.50/)
    assert.match(html, /\$0\.50/)
    assert.match(html, /\$PATH/)
    assert.match(html, /foo\$x\$/)
    assert.match(html, /price\$1\$/)
})

test('preserves blockquote and list structure around display math', () => {
    const bq = renderMarkdown('> Note before:\n> $$E = mc^2$$\n> still inside quote')
    assert.match(bq, /<blockquote>[\s\S]*class="math-block"[\s\S]*still inside quote[\s\S]*<\/blockquote>/)

    const list = renderMarkdown('- First item:\n  $$a^2 + b^2 = c^2$$\n- Second item')
    assert.match(list, /<ul>[\s\S]*<li>[\s\S]*class="math-block"[\s\S]*<\/li>[\s\S]*<li>Second item<\/li>[\s\S]*<\/ul>/)
})

test('uses per-call random math placeholder nonces so literal prose cannot collide', () => {
    const html = renderMarkdown('Literal HARNESSMATHBLOCK0END and $x + 1$ stay distinct.')
    assert.match(html, /HARNESSMATHBLOCK0END/)
    assert.match(html, /class="math-inline"/)
})

test('handles unclosed streaming $ and $$ safely without crashing', () => {
    const html1 = renderMarkdown('Streaming inline $x + y')
    assert.doesNotMatch(html1, /class="katex"/)
    assert.match(html1, /\$x \+ y/)

    const html2 = renderMarkdown('Streaming block $$a + b')
    assert.doesNotMatch(html2, /class="katex"/)
    assert.match(html2, /\$\$a \+ b/)
})

test('strips XSS payloads and enforces KaTeX trust: false', () => {
    const html = renderMarkdown(
        'Hello <script>alert(1)</script><img src="x" onerror="alert(2)"> '
        + '[bad](javascript:alert(3)) and $\\href{javascript:alert(4)}{click}$'
    )
    assert.doesNotMatch(html, /<script/i)
    assert.doesNotMatch(html, /onerror/i)
    assert.doesNotMatch(html, /href\s*=\s*["']?javascript:/i)
    assert.doesNotMatch(html, /<a[^>]+javascript:/i)
    assert.match(html, /#cc0000/i)
})

test('wraps wide Markdown tables in horizontally scrollable .tbl container', () => {
    const html = renderMarkdown('| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |')
    assert.match(html, /<div class="tbl"><table>/)
})
