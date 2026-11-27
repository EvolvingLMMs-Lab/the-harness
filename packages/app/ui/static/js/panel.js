// The tools rail on the right and its interactive workspace panel:
//   - Terminal: real local PTY shell powered by xterm.js + SSE (/api/app/terminal), plus Agent log view
//   - Files: expandable project tree (/api/app/place_tree), syntax-highlighted preview (/api/app/place_file),
//            @ mention insertion, and Open in Editor / File Manager (/api/app/open_path)
//   - Changes: structured per-file git diff + revert (/api/app/place_changes) + Worktree Merge/Discard
//   - Browser: interactive URL bar + live localhost iframe preview + Agent view toggle
//   - Context: workspace/model/mode/token overview + Compact action
import { esc, tt, when, usd } from './i18n.js'
import { get, post, failed, sessionKey } from './api.js'
import { $, $$, ic, loading, empty, problem, toast, said, confirm, copy } from './ui.js'
import { icon } from './icons.js'
import { keysOf } from './keys.js'
import { prefs } from './prefs.js'
import { modelOf, insertText } from './composer.js'

export const RAIL = [
    ['context', '上下文', 'Context'],
    ['terminal', '终端', 'Terminal'],
    ['browser', '浏览器', 'Browser'],
    ['files', '文件', 'Files'],
    ['changes', '改动', 'Changes'],
]
export const toolName = (id) => { const r = RAIL.find((x) => x[0] === id); return r ? tt(r[1], r[2]) : id }

const tabs = new Map() // chat -> {open: [ids], on: id | null}
const terms = new Map() // chat -> {id, cwd, shell, mode, term, fit, ro, es, wrap, host, alive, closing}
const filesState = new Map() // chat -> {root, folder, expanded: Set, children: Map, viewing: obj|null}
const browserState = new Map() // chat -> {mode: 'preview'|'agent', url: string, nonce: number}

const getFileState = (chat) => {
    if (!filesState.has(chat)) filesState.set(chat, { root: '', folder: '', expanded: new Set(), children: new Map(), viewing: null })
    return filesState.get(chat)
}
const getBrowserState = (chat) => {
    if (!browserState.has(chat)) browserState.set(chat, { mode: 'preview', url: '', nonce: 0 })
    return browserState.get(chat)
}

export function railHtml() {
    return RAIL.map(([id]) => ic(id, toolName(id), { act: 'tool', attrs: `data-arg="${id}" aria-pressed="false"` })).join('')
}

export function open(app, id) {
    const t = tabs.get(app.chat) || { open: [], on: null }
    if (!t.open.includes(id)) t.open.push(id)
    t.on = id; tabs.set(app.chat, t); prefs.set('tools.last', id); render(app)
}

export function close(app, id) {
    const t = tabs.get(app.chat); if (!t) return
    t.open = t.open.filter((x) => x !== id); if (t.on === id) t.on = t.open[t.open.length - 1] || null
    render(app)
}

export function toggle(app) {
    const t = tabs.get(app.chat)
    if (t && t.on) { t.on = null; render(app); return }
    const last = prefs.get('tools.last', 'terminal')
    open(app, t && t.open.includes(last) ? last : (t && t.open[t.open.length - 1]) || (RAIL.some((r) => r[0] === last) ? last : 'terminal'))
}

// Jump directly from a chat message or Changes card into the syntax-highlighted file preview.
export async function openFile(app, relPath) {
    const clean = String(relPath || '').replace(/^\.\//, '').replace(/\\/g, '/')
    if (!clean) return
    const st = getFileState(app.chat)
    open(app, 'files')
    const data = await get('/api/app/place_file', { identity: app.identity.id, chat: app.chat, path: clean })
    if (!data) {
        const why = failed.get('/api/app/place_file')
        if (why) said({ ok: false, ...why })
        return
    }
    st.viewing = data
    render(app, { force: true })
}

function detachLiveTerminal(pane) {
    for (const s of terms.values()) {
        if (s.wrap && s.wrap.parentNode === pane) pane.removeChild(s.wrap)
    }
}

export async function render(app, { force = false } = {}) {
    const panel = $('.pg-panel'), t = tabs.get(app.chat)
    if (!panel) return
    const shown = t && t.on
    panel.classList.toggle('open', !!shown)
    $$('.pg-rail .pg-ic').forEach((b) => {
        b.classList.toggle('on', b.dataset.arg === shown)
        b.setAttribute('aria-pressed', b.dataset.arg === shown ? 'true' : 'false')
    })
    const strip = panel.querySelector('.pg-tabs'), pane = panel.querySelector('.pg-pane')
    if (!shown) {
        detachLiveTerminal(pane)
        strip.innerHTML = ''; pane.innerHTML = ''; pane.dataset.view = ''
        return
    }
    strip.innerHTML = t.open.map((id) => `<div class="pg-tab${id === shown ? ' on' : ''}"><button type="button" role="tab" aria-selected="${id === shown}" data-act="tool-tab" data-arg="${id}">${icon(id, 14)}<span>${esc(toolName(id))}</span></button>`
        + `<button type="button" class="x" data-act="tool-close" data-arg="${id}" aria-label="${esc(tt(`关闭${toolName(id)}`, `Close ${toolName(id)}`))}">${icon('close', 12)}</button></div>`).join('')
        + `<span class="pg-tabs-end">${ic('right', tt('收起工具面板', 'Close the tools panel'), { act: 'tools-toggle', keys: keysOf('tools') })}</span>`
    const chat = app.chat, viewKey = `${chat}/${shown}`
    if (shown === 'terminal') {
        pane.dataset.view = viewKey
        await renderTerminal(app, pane)
        return
    }
    detachLiveTerminal(pane)
    if (force || pane.dataset.view !== viewKey) pane.innerHTML = `<div class="pg-view">${loading()}</div>`
    pane.dataset.view = viewKey
    const html = await VIEWS[shown](app)
    if (app.chat !== chat || (tabs.get(chat) || {}).on !== shown) return
    pane.innerHTML = `<div class="pg-view">${html}</div>`
    wireView(app, pane, shown)
}

function runs(app) {
    return (app.records[app.chat] || []).filter((r) => r.run && (r.event === 'outcome' || r.event === 'action')).map((r) => r.run)
}

const broke = (path) => problem(failed.get(path), { retry: 'tool-retry' })

function b64ToText(b64) {
    const raw = atob(b64), bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
    return new TextDecoder('utf-8').decode(bytes)
}

function termTheme() {
    const cs = getComputedStyle(document.documentElement)
    const v = (name, fb) => (cs.getPropertyValue(name) || '').trim() || fb
    const bg = v('--ar-bg', '#0e1726'), fg = v('--ar-fg', '#e6edf3'), acc = v('--ar-accent', '#4da6ff')
    return {
        background: bg, foreground: fg, cursor: acc, cursorAccent: bg,
        selectionBackground: v('--ar-raise', '#1f3652'),
        black: '#1f2937', red: v('--ar-outcome-failed', '#ff5c7a'), green: v('--ar-outcome-done', '#3ddc97'),
        yellow: v('--ar-outcome-refused', '#f5b14c'), blue: acc, magenta: v('--ar-outcome-unknown', '#b79cff'),
        cyan: v('--ar-chart-1', '#25a5b6'), white: fg,
    }
}

function closeTermSession(chat) {
    const s = terms.get(chat)
    if (!s) return
    s.closing = true
    if (s.es) { try { s.es.close() } catch { /* ignore */ } s.es = null }
    if (s.ro) { try { s.ro.disconnect() } catch { /* ignore */ } s.ro = null }
    if (s.term) { try { s.term.dispose() } catch { /* ignore */ } s.term = null }
    if (s.id) post('/api/app/terminal', { action: 'close', id: s.id })
    if (s.wrap && s.wrap.parentNode) s.wrap.parentNode.removeChild(s.wrap)
    terms.delete(chat)
}

async function renderTerminal(app, pane) {
    const chat = app.chat
    let s = terms.get(chat)
    if (!s) {
        s = { id: null, cwd: '', shell: '', mode: 'shell', term: null, fit: null, ro: null, es: null, wrap: null, host: null, alive: false, closing: false }
        terms.set(chat, s)
    }
    if (!s.wrap) {
        s.wrap = document.createElement('div')
        s.wrap.className = 'term-wrap'
        s.wrap.innerHTML = `<div class="term-bar">
            <div class="seg term-mode">
                <button type="button" data-tmode="shell" class="on">${tt('终端', 'Shell')}</button>
                <button type="button" data-tmode="log">${tt('日志', 'Log')}</button>
            </div>
            <span class="term-meta" data-meta></span>
            <span class="grow"></span>
            ${ic('trash', tt('清屏', 'Clear'), { attrs: 'data-tact="clear"' })}
            ${ic('retry', tt('重启终端', 'Restart shell'), { attrs: 'data-tact="restart"' })}
        </div>
        <div class="term-host" data-host></div>
        <div class="term-log" data-log hidden></div>`
        s.host = s.wrap.querySelector('[data-host]')
        s.wrap.addEventListener('click', async (e) => {
            const mb = e.target.closest('[data-tmode]')
            if (mb) {
                s.mode = mb.dataset.tmode
                updateTermMode(app, s)
                return
            }
            const ab = e.target.closest('[data-tact]')
            if (!ab) return
            if (ab.dataset.tact === 'clear' && s.term) s.term.clear()
            if (ab.dataset.tact === 'restart') {
                closeTermSession(chat)
                render(app, { force: true })
            }
        })
    }
    if (s.wrap.parentNode !== pane) {
        detachLiveTerminal(pane)
        pane.innerHTML = ''
        pane.appendChild(s.wrap)
    }
    updateTermMode(app, s)
    if (s.mode === 'shell' && !s.id && !s.starting) {
        await startTermSession(app, chat, s)
    } else if (s.term) {
        s.term.options.theme = termTheme()
        requestAnimationFrame(() => { try { s.fit && s.fit.fit(); s.term.focus() } catch { /* ignore */ } })
    }
}

async function updateTermMode(app, s) {
    s.wrap.querySelectorAll('[data-tmode]').forEach((b) => b.classList.toggle('on', b.dataset.tmode === s.mode))
    const logEl = s.wrap.querySelector('[data-log]')
    s.host.hidden = s.mode !== 'shell'
    logEl.hidden = s.mode !== 'log'
    if (s.mode === 'log') {
        const run = runs(app).slice(-1)[0]
        if (!run) { logEl.innerHTML = empty(tt('暂无任务输出', 'No agent task output yet'), ''); return }
        const row = await get('/api/sessions/show', { id: run, lines: 120 })
        if (!row) { logEl.innerHTML = broke('/api/sessions/show'); return }
        const lines = row.agents ? row.agents.flatMap((a) => a.lines || []) : []
        logEl.innerHTML = `<div class="vt">${esc(run)}</div>` + (lines.length ? `<div class="term">${esc(lines.join('\n'))}</div>` : empty(tt('无输出', 'No output')))
    } else if (s.term) {
        requestAnimationFrame(() => { try { s.fit && s.fit.fit(); s.term.focus() } catch { /* ignore */ } })
    }
}

async function startTermSession(app, chat, s) {
    s.starting = true
    const metaEl = s.wrap.querySelector('[data-meta]')
    metaEl.textContent = tt('启动中…', 'Starting…')
    // Wait for .pg-panel.open layout to settle before measuring xterm cols/rows so lines never wrap at ~35 cols
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
    if (s.closing) { s.starting = false; return }
    const cs = getComputedStyle(document.documentElement)
    const fontFamily = (cs.getPropertyValue('--ar-mono') || '').trim() || 'monospace'
    const hasXterm = typeof window.Terminal === 'function'
    let cols = 90, rows = 26
    const fitNow = (sync = false) => {
        if (!s.fit || !s.term || s.host.hidden || s.host.clientWidth < 80) return
        try {
            s.fit.fit()
            if (sync && s.id && s.alive) post('/api/app/terminal', { action: 'resize', id: s.id, cols: s.term.cols, rows: s.term.rows })
        } catch { /* ignore */ }
    }
    if (hasXterm) {
        s.host.innerHTML = ''
        s.term = new window.Terminal({
            cursorBlink: true, fontSize: 13, fontFamily, theme: termTheme(), scrollback: 3000,
            allowProposedApi: false, convertEol: false,
        })
        if (window.FitAddon && window.FitAddon.FitAddon) {
            s.fit = new window.FitAddon.FitAddon()
            s.term.loadAddon(s.fit)
        }
        s.term.open(s.host)
        fitNow(false)
        if (s.term.cols && s.term.cols >= 40) cols = s.term.cols
        if (s.term.rows && s.term.rows >= 6) rows = s.term.rows
    } else {
        s.host.innerHTML = `<pre class="term fallback"></pre><input class="field term-in" placeholder="${tt('输入命令后按回车', 'Type a command and press Enter')}">`
    }
    const r = await post('/api/app/terminal', { action: 'open', identity: app.identity.id, chat, cols, rows })
    s.starting = false
    if (!r.ok || !r.data || !r.data.id) {
        metaEl.textContent = tt('启动失败', 'Failed')
        if (s.term) s.term.writeln(`\r\n\x1b[31m${r.error || 'Unable to start terminal'}\x1b[0m`)
        return
    }
    s.id = r.data.id; s.cwd = r.data.cwd || ''; s.shell = r.data.shell || ''; s.alive = true
    if (s.term && r.data.pty === 'pipe') s.term.options.convertEol = true
    metaEl.textContent = `${s.shell}${s.cwd ? ' · ' + s.cwd.split(/[\\/]/).filter(Boolean).slice(-1)[0] : ''}`
    metaEl.title = s.cwd
    if (s.term) {
        s.term.onData((data) => { if (s.id && s.alive) post('/api/app/terminal', { action: 'input', id: s.id, data }) })
        let resizeTimer = null
        const scheduleFit = () => {
            clearTimeout(resizeTimer)
            resizeTimer = setTimeout(() => fitNow(true), 50)
        }
        if (typeof ResizeObserver === 'function') {
            s.ro = new ResizeObserver(() => {
                if (!s.fit || !s.term || s.host.hidden || !s.host.offsetWidth) return
                scheduleFit()
            })
            s.ro.observe(s.host)
        }
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (!s.closing) scheduleFit() })
        scheduleFit()
        s.term.focus()
    } else {
        const inp = s.host.querySelector('.term-in')
        inp.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault()
                const val = inp.value + '\r\n'; inp.value = ''
                if (s.id && s.alive) post('/api/app/terminal', { action: 'input', id: s.id, data: val })
            }
        })
    }
    const tok = sessionKey()
    const streamUrl = `/api/app/terminal?action=stream&id=${encodeURIComponent(s.id)}` + (tok ? `&token=${encodeURIComponent(tok)}` : '')
    const es = new EventSource(streamUrl)
    s.es = es
    es.onmessage = (ev) => {
        try {
            const msg = JSON.parse(ev.data)
            const text = b64ToText(msg.data || '')
            if (s.term) s.term.write(text)
            else {
                const pre = s.host.querySelector('pre')
                if (pre) { pre.textContent += text; pre.scrollTop = pre.scrollHeight }
            }
        } catch { /* ignore */ }
    }
    es.addEventListener('exit', (ev) => {
        s.alive = false
        es.close()
        let code = 0
        try { code = JSON.parse(ev.data).exit_code } catch { /* ignore */ }
        if (s.term) s.term.writeln(`\r\n\x1b[2m[exited: ${code}]\x1b[0m`)
        metaEl.textContent = `${s.shell} · ${tt('已退出', 'exited')}`
    })
}

function highlightCode(text, lang) {
    if (window.hljs) {
        try {
            if (lang && window.hljs.getLanguage(lang)) return window.hljs.highlight(text, { language: lang, ignoreIllegals: true }).value
            return window.hljs.highlightAuto(text).value
        } catch { /* fallback */ }
    }
    return esc(text)
}

function renderTreeRows(st, relPath, depth) {
    const entries = st.children.get(relPath) || []
    if (!entries.length && depth === 0) return empty(tt('这个文件夹是空的', 'Empty folder'))
    return entries.map((f) => {
        const isOpen = f.dir && st.expanded.has(f.path)
        const pad = 8 + depth * 14
        const stBadge = f.status ? `<em class="ft-st st-${esc(f.status[0] || 'M')}">${esc(f.status)}</em>` : ''
        const row = `<button type="button" class="ft-row${f.dir ? ' dir' : ''}" style="padding-left:${pad}px" data-ft-path="${esc(f.path)}" data-ft-dir="${f.dir ? '1' : '0'}">`
            + (f.dir ? `<span class="ft-tw">${icon(isOpen ? 'down' : 'right', 11)}</span>` : '<span class="ft-tw"></span>')
            + `${icon(f.dir ? 'folder' : 'file', 14)}<span class="ft-name">${esc(f.name)}</span>${stBadge}</button>`
        return row + (isOpen ? renderTreeRows(st, f.path, depth + 1) : '')
    }).join('')
}

function formatSize(n) {
    if (n == null) return ''
    return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`
}

const VIEWS = {
    async context(app) {
        const meta = app.meta[app.chat] || {}, row = app.row()
        const place = (app.life.places || []).find((p) => p.id === (meta.place || row.place))
        const spent = Object.values((app.usage.today || {}).by_source || {}).filter((s) => s.id === app.chat).reduce((a, s) => a + (s.cost_usd || 0), 0)
        const ctx = app.context[app.chat] || {}
        const used = ctx.used || 0, limit = ctx.limit || 0, pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0
        const mode = row.mode || ((app.values.approvals || {}).mode) || 'auto'
        const modeName = { plan: tt('计划', 'Plan'), ask: tt('询问', 'Ask'), auto: tt('自动', 'Auto'), full: tt('完整权限', 'Full Access') }[mode] || mode
        return `<div class="pane-scroll"><div class="vt">${tt('工作区', 'Workspace')}</div><div class="kv">`
            + `<b>${tt('项目', 'Project')}</b><span>${place ? esc((place.title || place.id).replace(/^folder\s*·\s*/i, '')) : tt('无项目', 'No project')}</span>`
            + (row.branch ? `<b>Worktree</b><span>${esc(row.branch)}</span>` : '')
            + `<b>${tt('权限模式', 'Mode')}</b><span>${esc(modeName)}</span>`
            + `<b>${tt('模型', 'Model')}</b><span>${esc(modelOf(app).id || modelOf(app).name)}</span>`
            + `<b>${tt('今日花费', 'Today')}</b><span>${usd(spent)}</span></div>`
            + (limit ? `<div class="vt">${tt('上下文窗口', 'Context window')}</div><div class="ctx-meter"><div class="ubar"><i style="width:${pct}%"></i></div><small>${used.toLocaleString()} / ${limit.toLocaleString()} (${pct}%)</small><button type="button" class="b" data-ctx-compact>${tt('压缩上下文', 'Compact')}</button></div>`
                : `<div class="vt">${tt('操作', 'Actions')}</div><div class="ctx-actions"><button type="button" class="b" data-ctx-compact>${tt('压缩上下文', 'Compact')}</button><button type="button" class="b quiet" data-act="customizations">${tt('自定义与规则', 'Customizations')}</button></div>`)
            + `</div>`
    },

    async browser(app) {
        const st = getBrowserState(app.chat)
        const run = runs(app).slice(-1)[0]
        const hasUrl = !!st.url
        const bar = `<div class="br-bar">
            <div class="seg">
                <button type="button" data-bmode="preview" class="${st.mode === 'preview' ? 'on' : ''}">${tt('预览', 'Preview')}</button>
                <button type="button" data-bmode="agent" class="${st.mode === 'agent' ? 'on' : ''}">${tt('Agent 视图', 'Agent')}</button>
            </div>
            <form class="br-form"><input class="field br-url" value="${esc(st.url)}" spellcheck="false" aria-label="URL" placeholder="${tt('输入网址按回车打开…', 'Enter a URL and press Enter…')}"></form>
            ${ic('retry', tt('刷新', 'Reload'), { act: 'br-reload', attrs: hasUrl ? '' : 'disabled' })}
            ${ic('external', tt('在浏览器打开', 'Open external'), { act: 'br-ext', attrs: hasUrl ? '' : 'disabled' })}
        </div>`
        if (st.mode === 'agent') {
            if (!run) return bar + `<div class="br-blank">${icon('browser', 26)}<b>${tt('暂无 Agent 浏览器画面', 'No agent browser view')}</b></div>`
            return bar + `<div class="frame"><img class="shot" alt="${esc(tt('浏览器画面', 'Browser view'))}" src="/api/app/screen?run=${encodeURIComponent(run)}&t=${Date.now()}"></div>`
        }
        if (!hasUrl) {
            const last = prefs.get('browser.url', '')
            const picks = [...new Set([last, 'http://localhost:3000', 'http://localhost:5173', 'http://localhost:8000'].filter(Boolean))].slice(0, 4)
            return bar + `<div class="br-blank">${icon('browser', 26)}<b>${tt('空白预览页', 'Blank preview')}</b><p>${tt('在上方地址栏输入本地服务或网页地址开始预览', 'Enter a local server or web URL above to preview')}</p>`
                + `<div class="br-chips">${picks.map((u) => `<button type="button" class="br-chip" data-br-go="${esc(u)}">${esc(u.replace(/^https?:\/\//, ''))}</button>`).join('')}</div></div>`
        }
        const safeUrl = /^https?:\/\//i.test(st.url) ? st.url : `http://${st.url}`
        return bar + `<div class="br-stage"><iframe class="br-frame" src="${esc(safeUrl)}" data-nonce="${st.nonce}" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe></div>`
    },

    async files(app) {
        const st = getFileState(app.chat)
        if (st.viewing) {
            const f = st.viewing
            const header = `<div class="ft-bar">
                <button type="button" class="b quiet" data-fv="back">${icon('left', 13)}${tt('返回', 'Back')}</button>
                <span class="ft-crumb" title="${esc(f.path)}">${esc(f.path)}</span>
                <span class="grow"></span>
                <button type="button" class="b quiet" data-fv="mention" data-path="${esc(f.path)}">@ ${tt('引用', 'Mention')}</button>
                ${ic('copy', tt('复制路径', 'Copy path'), { attrs: `data-fv="copy" data-path="${esc(f.path)}"` })}
                ${ic('external', tt('在编辑器打开', 'Open in VS Code'), { attrs: `data-fv="code" data-full="${esc(f.full_path || '')}"` })}
            </div>`
            if (f.binary) return header + empty(tt('二进制文件', 'Binary file'), formatSize(f.size))
            const highlighted = highlightCode(f.text || '', f.language)
            const lineCount = Math.max(1, f.lines || 1)
            const nums = Array.from({ length: lineCount }, (_, i) => i + 1).join('\n')
            return header + `<div class="fv-meta">${f.lines} ${tt('行', 'lines')} · ${formatSize(f.size)}${f.truncated ? ' · ' + tt('已截断', 'truncated') : ''}</div>`
                + `<div class="fv-code"><pre class="fv-nums" aria-hidden="true">${nums}</pre><pre class="fv-body"><code class="hljs">${highlighted}</code></pre></div>`
        }
        const got = await get('/api/app/place_tree', { identity: app.identity.id, chat: app.chat, path: '' })
        if (!got) return broke('/api/app/place_tree')
        if (!got.folder) {
            return `<div class="ft-empty">${empty(tt('当前对话未关联项目', 'No project attached'), '')}<button type="button" class="b" data-act="project-open-folder">${icon('folderPlus', 14)}${tt('打开文件夹…', 'Open folder…')}</button></div>`
        }
        if (st.root !== got.root) { st.root = got.root; st.folder = got.folder; st.expanded.clear(); st.children.clear() }
        st.children.set('', got.entries || [])
        return `<div class="ft-bar">
            <span class="ft-title" title="${esc(got.root)}">${icon('folder', 14)}<b>${esc(got.folder)}</b></span>
            <span class="grow"></span>
            ${ic('retry', tt('刷新', 'Refresh'), { attrs: 'data-ft-act="refresh"' })}
            ${ic('external', tt('打开所在文件夹', 'Open in file manager'), { attrs: `data-ft-act="open" data-full="${esc(got.root)}"` })}
            <button type="button" class="b quiet" data-ft-act="code" data-full="${esc(got.root)}">VS Code</button>
        </div><div class="pane-scroll flush"><div class="ft-tree">${renderTreeRows(st, '', 0)}</div></div>`
    },

    async changes(app) {
        const got = await get('/api/app/place_changes', { identity: app.identity.id, chat: app.chat })
        if (!got) return broke('/api/app/place_changes')
        if (!got.folder) {
            return `<div class="ft-empty">${empty(tt('当前对话未关联项目', 'No project attached'), '')}<button type="button" class="b" data-act="project-open-folder">${icon('folderPlus', 14)}${tt('打开文件夹…', 'Open folder…')}</button></div>`
        }
        const wt = got.worktree || {}
        const wtBanner = wt.is_worktree ? `<div class="wt-banner">
            <div class="wt-info">${icon('branch', 14)}<b>${esc(wt.branch || '')}</b><span>→ ${esc(wt.base_branch || 'main')}</span><em>+${wt.ahead ?? wt.commits_ahead ?? 0} ${tt('提交', 'commits')}${wt.dirty ? ` · ${wt.dirty} ${tt('未提交', 'dirty')}` : ''}</em></div>
            <div class="wt-btns">
                <button type="button" class="b" data-wt-act="merge">${tt('合并到', 'Merge to')} ${esc(wt.base_branch || 'main')}</button>
                <button type="button" class="b quiet danger" data-wt-act="discard">${tt('丢弃', 'Discard')}</button>
            </div>
        </div>` : ''
        const header = `<div class="ft-bar">
            <span class="ft-title">${icon('branch', 14)}<b>${esc(got.branch || got.folder)}</b><small>${got.files.length}</small></span>
            <span class="grow"></span>
            ${ic('retry', tt('刷新', 'Refresh'), { attrs: 'data-ch-act="refresh"' })}
        </div>`
        if (!got.files.length) return header + wtBanner + `<div class="pane-scroll">${empty(tt('工作区干净，暂无改动', 'No uncommitted changes'))}</div>`
        const cards = got.files.map((f) => `<details class="df-card" open>
            <summary class="df-head">
                <span class="ft-st st-${esc(f.status[0] || 'M')}">${esc(f.status)}</span>
                <span class="df-path" title="${esc(f.path)}">${esc(f.path)}</span>
                <span class="df-stat">${f.added ? `<b class="c-done">+${f.added}</b>` : ''}${f.removed ? `<b class="c-failed">-${f.removed}</b>` : ''}</span>
                <button type="button" class="b quiet" data-ch-open="${esc(f.path)}">${tt('查看', 'Open')}</button>
                <button type="button" class="b quiet" data-ch-revert="${esc(f.path)}">${tt('撤销', 'Revert')}</button>
            </summary>
            <div class="pg-diff">${diffHtml(f.diff || '')}</div>
        </details>`).join('')
        return header + wtBanner + `<div class="pane-scroll"><div class="df-list">${cards}</div></div>`
    },
}

function wireView(app, pane, shown) {
    for (const img of pane.querySelectorAll('img.shot')) img.onerror = () => { img.closest('.frame').outerHTML = empty(tt('现在没有画面', 'No view now')) }
    if (shown === 'context') {
        const cb = pane.querySelector('[data-ctx-compact]')
        if (cb) cb.onclick = async () => {
            cb.disabled = true
            const r = await post('/api/agent/compact', { identity: app.identity.id, chat: app.chat })
            cb.disabled = false
            if (!r.ok) return said(r)
            toast(tt('已压缩上下文', 'Context compacted'))
            app.kick()
        }
    }
    if (shown === 'browser') {
        const st = getBrowserState(app.chat)
        const go = (raw) => {
            const v = String(raw || '').trim()
            st.url = v; st.mode = 'preview'; st.nonce++
            if (v) prefs.set('browser.url', v)
            render(app, { force: true })
        }
        pane.querySelectorAll('[data-bmode]').forEach((b) => { b.onclick = () => { st.mode = b.dataset.bmode; render(app, { force: true }) } })
        pane.querySelectorAll('[data-br-go]').forEach((b) => { b.onclick = () => go(b.dataset.brGo) })
        const form = pane.querySelector('.br-form'), input = pane.querySelector('.br-url')
        if (form && input) form.onsubmit = (e) => { e.preventDefault(); go(input.value) }
        const rel = pane.querySelector('[data-act="br-reload"]')
        if (rel) rel.onclick = () => { if (!st.url) return; st.nonce++; render(app, { force: true }) }
        const ext = pane.querySelector('[data-act="br-ext"]')
        if (ext) ext.onclick = () => {
            if (!st.url) return
            const safeUrl = /^https?:\/\//i.test(st.url) ? st.url : `http://${st.url}`
            window.open(safeUrl, '_blank', 'noopener')
        }
    }
    if (shown === 'files') {
        const st = getFileState(app.chat)
        pane.onclick = async (e) => {
            const fv = e.target.closest('[data-fv]')
            if (fv) {
                const act = fv.dataset.fv
                if (act === 'back') { st.viewing = null; render(app, { force: true }) }
                else if (act === 'mention') { insertText(`@${fv.dataset.path} `); toast(`@${fv.dataset.path}`) }
                else if (act === 'copy') copy(fv.dataset.path, tt('路径已复制', 'Path copied'))
                else if (act === 'code' && fv.dataset.full) {
                    const r = await post('/api/app/open_path', { path: fv.dataset.full, editor: 'code' })
                    if (!r.ok) said(r)
                }
                return
            }
            const fa = e.target.closest('[data-ft-act]')
            if (fa) {
                if (fa.dataset.ftAct === 'refresh') { st.children.clear(); render(app, { force: true }) }
                else if (fa.dataset.ftAct === 'open') { const r = await post('/api/app/open_path', { path: fa.dataset.full }); if (!r.ok) said(r) }
                else if (fa.dataset.ftAct === 'code') { const r = await post('/api/app/open_path', { path: fa.dataset.full, editor: 'code' }); if (!r.ok) said(r) }
                return
            }
            const row = e.target.closest('[data-ft-path]')
            if (!row) return
            const rel = row.dataset.ftPath
            if (row.dataset.ftDir === '1') {
                if (st.expanded.has(rel)) { st.expanded.delete(rel); render(app, { force: true }); return }
                const sub = await get('/api/app/place_tree', { identity: app.identity.id, chat: app.chat, path: rel })
                if (!sub) return said(failed.get('/api/app/place_tree'))
                st.children.set(rel, sub.entries || [])
                st.expanded.add(rel)
                render(app, { force: true })
            } else {
                openFile(app, rel)
            }
        }
    }
    if (shown === 'changes') {
        pane.onclick = async (e) => {
            const ref = e.target.closest('[data-ch-act="refresh"]')
            if (ref) { render(app, { force: true }); return }
            const op = e.target.closest('[data-ch-open]')
            if (op) { e.preventDefault(); openFile(app, op.dataset.chOpen); return }
            const rev = e.target.closest('[data-ch-revert]')
            if (rev) {
                e.preventDefault()
                const rel = rev.dataset.chRevert
                if (!(await confirm({ title: tt(`撤销 ${rel} 的改动？`, `Revert changes to ${rel}?`), text: tt('该文件将恢复为最近一次提交的内容。', 'Uncommitted changes to this file will be lost.'), yes: tt('撤销', 'Revert'), danger: true }))) return
                const r = await post('/api/app/place_changes', { action: 'revert', identity: app.identity.id, chat: app.chat, path: rel })
                if (!r.ok) return said(r)
                toast(tt(`已撤销 ${rel}`, `Reverted ${rel}`))
                render(app, { force: true })
                return
            }
            const wt = e.target.closest('[data-wt-act]')
            if (wt) {
                const act = wt.dataset.wtAct
                if (act === 'discard') {
                    if (!(await confirm({ title: tt('丢弃该 Worktree？', 'Discard this worktree?'), text: tt('孤立工作目录与分支将被删除。', 'The isolated directory and its branch will be deleted.'), yes: tt('丢弃', 'Discard'), danger: true }))) return
                }
                const r = await post('/api/agent/worktree', { action: act, identity: app.identity.id, chat: app.chat })
                if (!r.ok) return said(r)
                toast(act === 'merge' ? tt('已合并到主分支', 'Merged into base branch') : tt('已丢弃 Worktree', 'Worktree discarded'))
                await app.refreshList()
                render(app, { force: true })
            }
        }
    }
}

export function diffHtml(text) {
    let html = '', left = 0, right = 0
    for (const raw of text.split('\n')) {
        if (raw.startsWith('diff --git')) continue
        if (raw.startsWith('index ') || raw.startsWith('--- ') || raw.startsWith('+++ ') || raw.startsWith('new file') || raw.startsWith('deleted file')) continue
        const h = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/)
        if (h) { left = +h[1]; right = +h[2]; html += `<div class="dl hunk">${esc(raw)}</div>`; continue }
        if (raw.startsWith('-')) html += `<div class="dl del"><span class="ln">${left++}</span>- ${esc(raw.slice(1))}</div>`
        else if (raw.startsWith('+')) html += `<div class="dl add"><span class="ln">${right++}</span>+ ${esc(raw.slice(1))}</div>`
        else if (raw.startsWith(' ')) { html += `<div class="dl"><span class="ln">${right}</span>  ${esc(raw.slice(1))}</div>`; left++; right++ }
    }
    return html || `<div class="dl">${tt('无行级差异', 'No textual diff')}</div>`
}
