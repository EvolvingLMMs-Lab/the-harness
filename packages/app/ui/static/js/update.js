// The app's own update (/api/app/update). The desktop shell checks and downloads in the
// background; once an update is ready, "Restart to update to x.y.z" sits at the bottom of the left
// column beside the identity (dismissed, it stays in the identity menu; the tray has it too) and
// Settings › About shows the version, the state and Check for updates. The click installs and
// restarts onto the same chat; while the agent is at work it waits, or interrupts if the owner
// says so. A pip install is updated with `harness update`.
import { get, post } from './api.js'
import { esc, tt } from './i18n.js'
import { $, dialog, closeDialog, closeMenu, said } from './ui.js'
import { icon } from './icons.js'

let st = null // the host's answer
let asked = false // the owner clicked Restart to update, and it has not happened yet
let timer = null

const readyVersion = () => (st && st.shell && st.shell.phase === 'ready' ? st.shell.version : null)
const windows = () => !!(st && st.shell && st.shell.os === 'windows')
const closesNote = () => tt('窗口会关一下再打开', 'The window closes for a moment and reopens')

export async function refresh(app) {
    const got = await get('/api/app/update', { chat: app.view === 'chat' ? app.chat : '' })
    if (got) st = got
    else if (asked) { installing(); return schedule(app) } // the host stopped: the shell is installing
    draw(app)
    if (asked && st && st.restart && (st.busy || []).length) waiting(app)
    else if (asked) installing()
    if (app.section === 'about') { const box = $('.pg-settings [data-upd-about]'); if (box) box.innerHTML = aboutState() }
    schedule(app)
}
function schedule(app) {
    clearTimeout(timer)
    const phase = st && st.shell ? st.shell.phase : ''
    const quick = asked || phase === 'checking' || phase === 'downloading' || app.section === 'about'
    timer = setTimeout(() => refresh(app), quick ? 1000 : 5000)
}
export function start(app) { refresh(app) }

// the bottom of the left column
export function draw(app) {
    const box = $('.pg-upd'); if (!box) return
    const version = readyVersion()
    const show = version && st.dismissed !== version
    box.hidden = !show
    if (!show) { box.innerHTML = ''; return }
    box.innerHTML = `<button type="button" class="go" data-act="update-go">${icon('retry', 14)}<span>${esc(tt(`重启以更新到 ${version}`, `Restart to update to ${version}`))}</span></button>`
        + `<button type="button" class="x" data-act="update-hide" aria-label="${tt('收起到身份菜单', 'Move it to the identity menu')}" data-tip="${tt('收起到身份菜单', 'Move it to the identity menu')}">${icon('close', 12)}</button>`
        + (windows() ? `<small>${esc(closesNote())}</small>` : '')
}

// the identity menu's item (always there while an update is ready)
export function menuItem(app) {
    const version = readyVersion()
    return version ? { label: tt(`重启以更新到 ${version}`, `Restart to update to ${version}`), icon: 'retry', run: () => restart(app) } : null
}

export async function restart(app, interrupt = false) {
    closeMenu()
    const view = app.view === 'calendar' ? 'calendar' : app.section ? `settings:${app.section}` : ''
    const r = await post('/api/app/update', { action: 'restart', chat: app.chat, view, interrupt })
    if (!r.ok) return said(r, tt('没有可安装的更新', 'No update is ready'))
    st = r.data; asked = true
    if ((st.busy || []).length && !interrupt) waiting(app)
    else installing()
    schedule(app)
}

export async function dismiss(app) {
    const r = await post('/api/app/update', { action: 'dismiss', version: readyVersion() })
    if (r.ok) st = r.data
    draw(app)
}

export async function cancel(app) {
    asked = false
    const r = await post('/api/app/update', { action: 'cancel' })
    if (r.ok) st = r.data
    closeDialog(); draw(app)
}

export async function check(app) {
    const r = await post('/api/app/update', { action: 'check' })
    if (!r.ok) return said(r)
    st = r.data
    const box = $('.pg-settings [data-upd-about]'); if (box) box.innerHTML = aboutState()
    schedule(app)
}

// while the agent is at work: what it waits for, and the choice to interrupt
function waiting(app) {
    const titles = Object.fromEntries((app.chats || []).map((c) => [c.chat, c.kind === 'main' ? tt('主对话', 'Main conversation') : c.title || c.chat]))
    const rows = (st.busy || []).map((b) => (b.session ? tt('一个正在运行的会话', 'a running session')
        : `${b.identity === app.identity.id ? '' : esc(b.identity) + ' · '}${esc(titles[b.chat] || b.chat)}`))
    const body = `<h5>${tt('等它告一段落再更新', 'Updating when it reaches a stopping point')}</h5>`
        + `<p>${tt('它正在做事：', 'It is at work in:')} ${rows.join(tt('、', ', ')) || '—'}</p>`
        + `<p class="note">${tt('做完这一段后安装并重启；现在中断的话，进行中的动作记为取消或结果未知。', 'It installs and restarts after this stretch; interrupted now, what is in progress ends as cancelled or unknown.')}</p>`
        + (windows() ? `<p class="note">${esc(closesNote())}</p>` : '')
        + `<div class="row"><span class="res"></span><button type="button" class="btn quiet" data-act="update-cancel">${tt('先不更新', 'Not now')}</button><button type="button" class="btn" data-act="update-interrupt">${tt('现在中断并更新', 'Interrupt and update now')}</button></div>`
    show(body, 'wait', { onClose: () => { if (asked && st && st.restart) cancel(app) } })
}
// The update's dialog; drawn again only when what it says changed, so the keyboard stays put.
function show(body, phase, options) {
    const open = $('.pg-layer .dlg[data-upd]')
    if (open && open._body === body) return
    const d = open || dialog(body, options)
    if (open) open.innerHTML = body
    d._body = body; d.dataset.upd = phase
}
function installing() {
    const s = (st && st.shell) || {}
    if (s.phase === 'downloading' && s.version) {
        const pct = s.total ? Math.round((s.got / s.total) * 100) : null
        const body = `<h5>${esc(tt(`正在下载最新版本 ${s.version}`, `Downloading latest ${s.version}`))}</h5>`
            + `<p>${esc(pct !== null ? tt(`已下载 ${pct}%，完成后自动安装并重启`, `Downloaded ${pct}%; installs and restarts automatically`) : tt('发现更新版本，下载完成后自动安装并重启', 'Newer release found; installing and restarting once downloaded'))}</p>`
        show(body, 'installing')
        return
    }
    const body = `<h5>${tt('正在安装更新', 'Installing the update')}</h5><p>${tt('装好后自动重启', 'It restarts by itself when installed')}</p>`
    show(body, 'installing')
}

// Settings › About
function aboutState() {
    if (!st) return ''
    if (st.installer === 'pip') {
        const p = st.pip || {}
        const line = p.newer ? tt(`PyPI 上有 ${p.version}。`, `PyPI has ${p.version}.`) : p.version ? tt(`已是最新（PyPI：${p.version}）。`, `Up to date (PyPI: ${p.version}).`) : ''
        return `<p>${esc(line)} ${tt('pip 装的由 pip 更新：在终端运行', 'A pip install is updated by pip: run')} <code>harness update</code>${tt('。', '.')}${p.error ? ` <span class="c-failed">${esc(p.error)}</span>` : ''}</p>`
    }
    const s = st.shell || {}
    const pct = s.total ? Math.round((s.got / s.total) * 100) : null
    const text = {
        checking: tt('正在检查…', 'Checking…'),
        downloading: tt(`正在下载 ${s.version || ''}${pct !== null ? ` · ${pct}%` : ''}`, `Downloading ${s.version || ''}${pct !== null ? ` · ${pct}%` : ''}`),
        ready: tt(`${s.version} 已下载并验证签名，重启即可更新。`, `${s.version} is downloaded and its signature verified; restart to update.`),
        latest: tt('已是最新。', 'Up to date.'),
        installing: tt('正在安装…', 'Installing…'),
        error: tt('更新失败：', 'The update failed: ') + (s.error || ''),
        off: tt('这个版本没有更新密钥，不检查更新。', 'This build has no updater key and does not check.'),
    }[s.phase] || (st.mode === 'none' ? tt('更新已关闭（app.update = none）。', 'Updates are off (app.update = none).') : '')
    const when = s.checked ? ` · ${tt('上次检查', 'last checked')} ${new Date(s.checked * 1000).toLocaleString()}` : ''
    return `<p>${esc(text)}<span style="color:var(--ar-dim)">${esc(when)}</span></p>`
        + `<div class="btns">${s.phase === 'ready' ? `<button type="button" class="b" data-act="update-go">${icon('retry', 14)}${esc(tt(`重启以更新到 ${s.version}`, `Restart to update to ${s.version}`))}</button>` : ''}`
        + `<button type="button" class="b" data-act="update-check"${st.mode === 'none' || ['checking', 'downloading', 'installing'].includes(s.phase) ? ' disabled' : ''}>${tt('检查更新', 'Check for updates')}</button></div>`
        + (s.phase === 'ready' && windows() ? `<p class="note">${esc(closesNote())}</p>` : '')
}
export async function about(app, setting) {
    st = (await get('/api/app/update', { chat: app.chat })) || st
    return `<div class="lg">${tt('更新', 'Updates')}</div>`
        + (st && st.installer === 'desktop' ? setting('app.update') : '')
        + `<div data-upd-about>${aboutState()}</div>`
}
