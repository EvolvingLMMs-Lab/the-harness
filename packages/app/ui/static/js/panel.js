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
import { markdown } from './markdown.js'

export const RAIL = [
    ['overview', '概览', 'Overview'],
    ['changes', '审查与改动', 'Review / Changes'],
    ['files', '文件', 'Files'],
    ['terminal', '终端', 'Terminal'],
    ['browser', '浏览器', 'Browser'],
]
export const toolName = (id) => {
    if (id === 'context') return tt('概览', 'Overview')
    const r = RAIL.find((x) => x[0] === id)
    return r ? tt(r[1], r[2]) : id
}
const isWideViewport = () => (typeof matchMedia === 'function' ? matchMedia('(min-width: 960px)').matches : true)
let panelOpen = (() => {
    if (isWideViewport()) return prefs.get('overview.docked', true) !== false
    return false
})()
export const isOpen = () => panelOpen

const tabs = new Map() // chat -> {open: [ids], on: id | null}
const terms = new Map() // chat -> {id, cwd, shell, mode, term, fit, ro, es, wrap, host, alive, closing}
const filesState = new Map() // chat -> {root, folder, expanded: Set, children: Map, viewing: obj|null}
const browserState = new Map() // chat -> {mode: 'preview'|'agent', url: string, nonce: number}
const artifactState = new Map() // chat -> {viewing: obj|null}

const getFileState = (chat) => {
    if (!filesState.has(chat)) filesState.set(chat, { root: '', folder: '', expanded: new Set(), children: new Map(), viewing: null })
    return filesState.get(chat)
}
const getBrowserState = (chat) => {
    if (!browserState.has(chat)) browserState.set(chat, { mode: 'preview', url: '', history: [], index: -1, nonce: 0 })
    return browserState.get(chat)
}
const getArtifactState = (chat) => {
    if (!artifactState.has(chat)) artifactState.set(chat, { viewing: null })
    return artifactState.get(chat)
}

export function syncOpen(app) {
    const t = tabs.get(app.chat) || { open: ['overview'], on: panelOpen ? 'overview' : null }
    if (panelOpen && !t.on) t.on = 'overview'
    if (!panelOpen) t.on = null
    tabs.set(app.chat, t)
    render(app)
}

export function open(app, id = 'overview') {
    const target = id === 'context' ? 'overview' : id
    const t = tabs.get(app.chat) || { open: ['overview'], on: null }
    if (!t.open.includes(target)) t.open.push(target)
    t.on = target
    panelOpen = true
    if (isWideViewport()) prefs.set('overview.docked', true)
    tabs.set(app.chat, t)
    render(app)
}

export function close(app, id) {
    if (!id || id === 'overview') return closePanel(app)
    backToOverview(app)
}

export function closePanel(app) {
    panelOpen = false
    if (isWideViewport()) prefs.set('overview.docked', false)
    const t = tabs.get(app.chat)
    if (t) t.on = null
    render(app)
}

export function backToOverview(app) {
    const ast = getArtifactState(app.chat)
    ast.viewing = null
    open(app, 'overview')
}

export function toggle(app) {
    if (panelOpen) { closePanel(app); return }
    open(app, 'overview')
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

// Open a session Markdown artifact (e.g. implementation_plan.md) rendered inside the right Context pane.
export async function openArtifact(app, name) {
    const clean = String(name || '').trim()
    if (!clean) return
    const st = getArtifactState(app.chat)
    open(app, 'overview')
    const data = await get('/api/app/artifact', { identity: app.identity.id, chat: app.chat, name: clean })
    if (!data) {
        const why = failed.get('/api/app/artifact')
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

let renderSeq = 0
let overviewRefreshTimer = null
const prRetryDone = new Set()
export function scheduleOverviewRefresh(app, delayMs = 600) {
    if (!panelOpen) return
    const t = tabs.get(app.chat)
    const shown = (t && t.on) || 'overview'
    if (shown !== 'overview' || getArtifactState(app.chat).viewing) return
    if (overviewRefreshTimer) clearTimeout(overviewRefreshTimer)
    overviewRefreshTimer = setTimeout(() => {
        overviewRefreshTimer = null
        const cur = tabs.get(app.chat)
        if (!panelOpen || ((cur && cur.on) || 'overview') !== 'overview' || getArtifactState(app.chat).viewing) return
        render(app, { force: false })
    }, delayMs)
}
export function copyViewingArtifact(app) {
    const v = getArtifactState(app.chat).viewing
    if (v) copy(v.text || '', tt('Markdown 已复制', 'Markdown copied'))
}
export async function openViewingArtifactExternal(fullPath) {
    if (!fullPath) return
    const r = await post('/api/app/open_path', { path: fullPath })
    if (!r.ok) said(r)
}
export async function render(app, { force = false } = {}) {
    const seq = ++renderSeq
    const panel = $('.pg-panel'), t = tabs.get(app.chat)
    if (!panel) return
    const shown = panelOpen ? ((t && t.on) || 'overview') : null
    const viewingArt = shown === 'overview' ? getArtifactState(app.chat).viewing : null
    const isOv = shown === 'overview' && !viewingArt
    panel.classList.toggle('open', !!shown)
    panel.classList.toggle('is-overview', isOv)
    const backdrop = $('.pg-panel-backdrop')
    if (backdrop) backdrop.classList.toggle('open', !!shown)
    const tog = $('.pg-bar .overview-toggle')
    if (tog) {
        tog.classList.toggle('on', !!shown)
        tog.setAttribute('aria-pressed', shown ? 'true' : 'false')
    }
    const strip = panel.querySelector('.pg-tabs'), pane = panel.querySelector('.pg-pane')
    if (!shown) {
        detachLiveTerminal(pane)
        strip.innerHTML = ''; pane.innerHTML = ''; pane.dataset.view = ''
        return
    }
    if (viewingArt) {
        strip.innerHTML = `<button type="button" class="ov-back" data-act="overview-back">${icon('left', 13)}<span>${esc(tt('概览', 'Overview'))}</span></button>`
            + `<span class="ov-crumb" title="${esc(viewingArt.path || viewingArt.name)}">${icon('file', 14)}<span>${esc(viewingArt.name)}</span></span>`
            + `<span class="pg-tabs-end">${ic('copy', tt('复制 Markdown', 'Copy Markdown'), { act: 'artifact-copy' })}${viewingArt.path ? ic('external', tt('在外部打开本地文件', 'Open local file'), { act: 'artifact-open-external', attrs: `data-full="${esc(viewingArt.path)}"` }) : ''}${ic('close', tt('返回概览', 'Back to Overview'), { act: 'overview-back' })}</span>`
    } else if (shown === 'overview') {
        strip.innerHTML = `<div class="ov-head">${icon('overview', 14)}<span>${esc(tt('概览', 'Overview'))}</span></div>`
            + `<span class="pg-tabs-end">${ic('retry', tt('刷新概览', 'Refresh overview'), { act: 'overview-refresh' })}${ic('close', tt('收起概览面板', 'Close Overview'), { act: 'tools-close', cls: 'ov-close-narrow', keys: keysOf('tools') })}</span>`
    } else {
        strip.innerHTML = `<button type="button" class="ov-back" data-act="overview-back">${icon('left', 13)}<span>${esc(tt('概览', 'Overview'))}</span></button>`
            + `<span class="ov-crumb">${icon(shown, 14)}<span>${esc(toolName(shown))}</span></span>`
            + `<span class="pg-tabs-end">${ic('close', tt('返回概览', 'Back to Overview'), { act: 'overview-back' })}</span>`
    }
    const chat = app.chat, viewKey = `${chat}/${shown}`
    if (shown === 'terminal') {
        pane.dataset.view = viewKey
        await renderTerminal(app, pane)
        return
    }
    detachLiveTerminal(pane)
    if (force || pane.dataset.view !== viewKey) pane.innerHTML = `<div class="pg-view">${loading()}</div>`
    pane.dataset.view = viewKey
    const fn = VIEWS[shown] || VIEWS.overview
    const html = await fn(app)
    if (seq !== renderSeq || app.chat !== chat || !panelOpen || ((tabs.get(chat) || {}).on || 'overview') !== shown) return
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
        const pasteFromClipboard = async () => {
            if (!s.term || !s.alive || !navigator.clipboard || !navigator.clipboard.readText) return
            try {
                const text = await navigator.clipboard.readText()
                if (text) s.term.paste(text)
            } catch { /* clipboard permission denied */ }
        }
        // Standard VS Code / Windows Terminal copy & paste shortcuts:
        //   - Ctrl+V / Cmd+V: return false so native browser/WebView2 paste event fires directly into xterm
        //   - Ctrl+Shift+V / Shift+Insert: paste via Clipboard API
        //   - Ctrl+C (when selection exists) / Ctrl+Shift+C / Cmd+C (with selection): copy instead of SIGINT
        s.term.attachCustomKeyEventHandler((e) => {
            if (e.type !== 'keydown') return true
            const key = (e.key || '').toLowerCase()
            const mod = e.ctrlKey || e.metaKey
            if (mod && key === 'v') {
                if (e.shiftKey) { e.preventDefault(); pasteFromClipboard() }
                return false
            }
            if (e.shiftKey && key === 'insert') {
                e.preventDefault()
                pasteFromClipboard()
                return false
            }
            if (mod && key === 'c' && (e.shiftKey || s.term.hasSelection())) {
                const sel = s.term.getSelection()
                if (sel) {
                    e.preventDefault()
                    copy(sel, tt('已复制', 'Copied'))
                    s.term.clearSelection()
                    return false
                }
            }
            return true
        })
        // Right-click in terminal: copy selection if any, otherwise paste (Windows Terminal / VS Code convention)
        s.host.oncontextmenu = (e) => {
            e.preventDefault()
            if (s.term.hasSelection()) {
                copy(s.term.getSelection(), tt('已复制', 'Copied'))
                s.term.clearSelection()
            } else {
                pasteFromClipboard()
            }
        }
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
    async overview(app) {
        const ast = getArtifactState(app.chat)
        if (ast.viewing) {
            return `<div class="pane-scroll"><div class="art-view md">${markdown(ast.viewing.text || '')}</div></div>`
        }
        const snap = await get('/api/app/overview', { identity: app.identity.id, chat: app.chat }) || {}
        const ws = snap.workspace || {}
        if (snap.pull_requests_pending) {
            const prKey = `${app.identity.id}:${app.chat}:${ws.folder || ''}`
            if (!prRetryDone.has(prKey)) {
                prRetryDone.add(prKey)
                scheduleOverviewRefresh(app, 1800)
            }
        }
        const row = app.row()
        const spent = Object.values((app.usage.today || {}).by_source || {}).filter((s) => s.id === app.chat).reduce((a, s) => a + (s.cost_usd || 0), 0)
        const snapCtx = snap.context || {}
        const liveCtx = app.context[app.chat] || {}
        const used = snapCtx.used || liveCtx.input_tokens || 0
        const limit = snapCtx.limit || liveCtx.window || 0
        const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0
        const mode = row.mode || snapCtx.mode || ((app.values.approvals || {}).mode) || 'auto'
        const modeName = { plan: tt('计划', 'Plan'), ask: tt('询问', 'Ask'), auto: tt('自动', 'Auto'), full: tt('完整权限', 'Full Access') }[mode] || mode

        // Tools section (honor t.available so unavailable workspace/git tools are cleanly disabled)
        const tools = Array.isArray(snap.tools) && snap.tools.length ? snap.tools : [
            { id: 'changes', label: 'Review / Changes', available: false, badge: 0 },
            { id: 'files', label: 'Files', available: false },
            { id: 'terminal', label: 'Terminal', available: true },
            { id: 'plugins', label: 'Plugins', available: true },
        ]
        const toolLabel = (t) => ({
            changes: tt('审查与改动', 'Review / Changes'),
            files: tt('文件', 'Files'),
            terminal: tt('终端', 'Terminal'),
            plugins: tt('插件与自定义', 'Plugins'),
            browser: tt('浏览器', 'Browser'),
        }[t.id] || t.label || t.id)
        const unavailableReason = (t) => (t.id === 'changes'
            ? tt('需要 Git 工作区', 'Requires a Git workspace')
            : tt('未绑定项目目录', 'No workspace folder attached'))
        const toolsHtml = `<div class="ov-sec"><div class="vt">${tt('工具', 'Tools')}</div><div class="ov-tools">`
            + tools.map((t) => {
                const avail = t.available !== false
                if (!avail) {
                    return `<button type="button" class="ov-tool is-unavailable" disabled aria-disabled="true" title="${esc(unavailableReason(t))}">`
                        + `${icon(t.id, 14)}<span>${esc(toolLabel(t))}</span></button>`
                }
                const act = t.id === 'plugins' ? 'customizations' : 'tool'
                const arg = t.id === 'plugins' ? '' : t.id
                const badge = t.badge > 0 ? `<span class="ov-badge">${t.badge}</span>` : ''
                return `<button type="button" class="ov-tool" data-act="${act}"${arg ? ` data-arg="${esc(arg)}"` : ''}>`
                    + `${icon(t.id, 14)}<span>${esc(toolLabel(t))}</span>${badge}${icon('right', 12)}</button>`
            }).join('')
            + `</div></div>`

        // Conditional optional sections (hidden when empty)
        const bgTasks = Array.isArray(snap.background_tasks) ? snap.background_tasks : []
        const tasksHtml = bgTasks.length
            ? `<div class="ov-sec"><div class="vt">${tt('后台任务', 'Background Tasks')} <span class="ov-cnt">${bgTasks.length}</span></div><div class="ov-list">`
                + bgTasks.map((t) => `<div class="ov-row"><span class="ov-dot ${esc(t.status || 'running')}"></span><span class="ov-txt">${esc(t.title || t.id)}</span><small>${esc(t.status || '')}</small></div>`).join('')
                + `</div></div>`
            : ''

        const goals = Array.isArray(snap.goals) ? snap.goals : []
        const goalsHtml = goals.length
            ? `<div class="ov-sec"><div class="vt">${tt('目标与计划', 'Goals')} <span class="ov-cnt">${goals.filter((g) => g.done).length}/${goals.length}</span></div><div class="ov-list">`
                + goals.map((g) => `<div class="ov-row ov-goal${g.done ? ' done' : ''}"><span class="ov-chk">${g.done ? '☑' : '☐'}</span><span class="ov-txt">${esc(g.text)}</span></div>`).join('')
                + `</div></div>`
            : ''

        const arts = Array.isArray(snap.artifacts) ? snap.artifacts : []
        const artHtml = arts.length
            ? `<div class="ov-sec"><div class="vt">${tt('产物文档', 'Artifacts')} <span class="ov-cnt">${arts.length}</span></div><div class="art-list">`
                + arts.map((a) => `<button type="button" class="art-item" data-art-open="${esc(a.name)}" title="${esc(a.path || a.name)}">`
                    + `${icon('file', 14)}<span class="art-main"><b>${esc(a.title || a.name)}</b><small>${esc(a.name)} · ${esc(formatSize(a.size))}</small></span></button>`).join('')
                + `</div></div>`
            : ''

        const prs = Array.isArray(snap.pull_requests) ? snap.pull_requests : []
        const prHtml = prs.length
            ? `<div class="ov-sec"><div class="vt">${tt('拉取请求', 'Pull Requests')} <span class="ov-cnt">${prs.length}</span></div><div class="ov-list">`
                + prs.map((pr) => `<a class="ov-row ov-pr" href="${esc(pr.url || '#')}" target="_blank" rel="noopener noreferrer">`
                    + `${icon('pr', 13)}<span class="ov-txt"><b>#${esc(pr.number)}</b> ${esc(pr.title)}</span></a>`).join('')
                + `</div></div>`
            : ''

        const wsHtml = `<div class="ov-sec"><div class="vt">${tt('工作区', 'Workspace')}</div><div class="kv">`
            + `<b>${tt('项目', 'Project')}</b><span>${esc(ws.project || tt('无项目', 'No project'))}</span>`
            + (ws.branch ? `<b>${tt('分支', 'Branch')}</b><span>${esc(ws.branch)}</span>` : '')
            + `<b>${tt('权限模式', 'Mode')}</b><span>${esc(modeName)}</span>`
            + `<b>${tt('模型', 'Model')}</b><span>${esc(modelOf(app).id || modelOf(app).name)}</span>`
            + `<b>${tt('今日花费', 'Today')}</b><span>${usd(spent)}</span></div>`
            + (limit ? `<div class="ctx-meter"><div class="ubar"><i style="width:${pct}%"></i></div><small>${used.toLocaleString()} / ${limit.toLocaleString()} (${pct}%)</small><button type="button" class="b" data-ctx-compact>${tt('压缩上下文', 'Compact')}</button></div>`
                : `<div class="ctx-actions"><button type="button" class="b" data-ctx-compact>${tt('压缩上下文', 'Compact')}</button></div>`)
            + `</div>`

        return `<div class="pane-scroll ov-body">${toolsHtml}${tasksHtml}${goalsHtml}${artHtml}${prHtml}${wsHtml}</div>`
    },
    async context(app) { return VIEWS.overview(app) },

    async browser(app) {
        const st = getBrowserState(app.chat)
        const run = runs(app).slice(-1)[0]
        const hasUrl = !!st.url
        const canBack = st.index > 0
        const canFwd = st.index >= 0 && st.index < st.history.length - 1
        const bar = `<div class="br-bar">
            ${ic('arrowLeft', tt('后退', 'Back'), { act: 'br-back', attrs: canBack ? '' : 'disabled' })}
            ${ic('arrowRight', tt('前进', 'Forward'), { act: 'br-fwd', attrs: canFwd ? '' : 'disabled' })}
            ${ic('retry', tt('刷新', 'Reload'), { act: 'br-reload', attrs: hasUrl ? '' : 'disabled' })}
            <form class="br-form"><input class="field br-url" value="${esc(st.url)}" spellcheck="false" aria-label="URL" placeholder="${tt('输入网址按回车打开…', 'Enter a URL and press Enter…')}"></form>
            <button type="button" class="br-agent-tog${st.mode === 'agent' ? ' on' : ''}" data-act="br-agent" title="${esc(tt('切换 Agent 浏览器视图', 'Toggle Agent browser view'))}">${tt('Agent 视图', 'Agent')}</button>
            ${ic('external', tt('在外部浏览器打开', 'Open in external browser'), { act: 'br-ext', attrs: hasUrl ? '' : 'disabled' })}
        </div>`
        if (st.mode === 'agent') {
            if (!run) return bar + `<div class="br-blank">${icon('browser', 24)}<b>${tt('暂无 Agent 浏览器画面', 'No agent browser view')}</b></div>`
            return bar + `<div class="frame"><img class="shot" alt="${esc(tt('浏览器画面', 'Browser view'))}" src="/api/app/screen?run=${encodeURIComponent(run)}&t=${Date.now()}"></div>`
        }
        if (!hasUrl) {
            return bar + `<div class="br-blank">${icon('browser', 24)}<p>${tt('在上方地址栏输入网址', 'Enter a URL in the address bar above')}</p></div>`
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
    if (shown === 'overview' || shown === 'context') {
        const ast = getArtifactState(app.chat)
        pane.onclick = async (e) => {
            const artOpen = e.target.closest('[data-art-open]')
            if (artOpen) { openArtifact(app, artOpen.dataset.artOpen); return }
            const artAct = e.target.closest('[data-art-act]')
            if (artAct) {
                const a = artAct.dataset.artAct
                if (a === 'back') { ast.viewing = null; render(app, { force: true }) }
                else if (a === 'copy' && ast.viewing) copy(ast.viewing.text || '', tt('Markdown 已复制', 'Markdown copied'))
                else if (a === 'open' && artAct.dataset.full) {
                    const r = await post('/api/app/open_path', { path: artAct.dataset.full })
                    if (!r.ok) said(r)
                }
                return
            }
            const cb = e.target.closest('[data-ctx-compact]')
            if (cb) {
                cb.disabled = true
                const r = await post('/api/agent/compact', { identity: app.identity.id, chat: app.chat })
                cb.disabled = false
                if (!r.ok) return said(r)
                toast(tt('已压缩上下文', 'Context compacted'))
                app.kick()
            }
        }
    }
    if (shown === 'browser') {
        const st = getBrowserState(app.chat)
        const navigate = (raw, push = true) => {
            const v = String(raw || '').trim()
            st.mode = 'preview'
            if (!v) { st.url = ''; st.nonce++; render(app, { force: true }); return }
            const norm = /^https?:\/\//i.test(v) ? v : `https://${v}`
            if (push && st.history[st.index] !== norm) {
                st.history = st.history.slice(0, st.index + 1)
                st.history.push(norm)
                st.index = st.history.length - 1
            }
            st.url = norm; st.nonce++
            render(app, { force: true })
        }
        const back = pane.querySelector('[data-act="br-back"]')
        if (back) back.onclick = () => { if (st.index > 0) { st.index--; navigate(st.history[st.index], false) } }
        const fwd = pane.querySelector('[data-act="br-fwd"]')
        if (fwd) fwd.onclick = () => { if (st.index < st.history.length - 1) { st.index++; navigate(st.history[st.index], false) } }
        const ag = pane.querySelector('[data-act="br-agent"]')
        if (ag) ag.onclick = () => { st.mode = st.mode === 'agent' ? 'preview' : 'agent'; render(app, { force: true }) }
        const form = pane.querySelector('.br-form'), input = pane.querySelector('.br-url')
        if (form && input) form.onsubmit = (e) => { e.preventDefault(); navigate(input.value, true) }
        const rel = pane.querySelector('[data-act="br-reload"]')
        if (rel) rel.onclick = () => { if (!st.url) return; st.nonce++; render(app, { force: true }) }
        const ext = pane.querySelector('[data-act="br-ext"]')
        if (ext) ext.onclick = () => {
            if (!st.url) return
            const safeUrl = /^https?:\/\//i.test(st.url) ? st.url : `https://${st.url}`
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
