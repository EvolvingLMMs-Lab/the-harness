// Settings › Packages, after Hermes Desktop's Capabilities and its skills catalog: what is
// installed, each with a switch, an update and a removal; below it the registry to search,
// with one click to install. Installing shows that it is at work and says what came of it; a
// package from outside the registry is installed only after the page showed what it brings.
import { esc, tt } from '../i18n.js'
import { get, post, failed } from '../api.js'
import { $, on, confirm, said, toast, row, mark, act, empty, loading, problem } from '../ui.js'
import { icon } from '../icons.js'

export const identity = false
let c = null
let query = ''
let asking = null
let installed = new Set()

export async function draw(ctx) {
    c = ctx
    const [st, host] = await Promise.all([ctx.get('/api/app/packages'), ctx.get('/api/host')])
    if (!st) return problem(failed.get('/api/app/packages'), { title: tt('扩展包没有读出来', 'The packages could not be read'), retry: 'settings' })
    const rows = st.packages || []
    installed = new Set(rows.map((p) => p.name))
    const left = Object.entries((host && host.problems) || {})
    return ``
        + ctx.setting('packages.auto_install') + ctx.setting('packages.registry')
        + `<div class="lg">${tt('已安装', 'Installed')}</div>`
        + left.map(([name, why]) => row({ title: esc(name), sub: esc(why), marks: mark(tt('没有加载', 'left out'), 'failed') })).join('')
        + (rows.length ? rows.map((p) => {
            const shown = p.shown || {}
            return row({ title: `${esc(p.name)} <span class="ver">${esc(p.version || '')}</span>`, sub: esc(shown.problem || p.summary || shown.summary || ''),
                marks: (shown.problem ? mark(tt('有问题', 'problem'), 'failed') : '') + (p.link ? mark(tt('链接到文件夹', 'linked folder'), 'none') : '') + mark(p.enabled === false ? tt('关', 'off') : tt('开', 'on'), p.enabled === false ? 'off' : 'eff'),
                actions: act(p.enabled === false ? tt('打开', 'Enable') : tt('关掉', 'Disable'), 'package-enable', p.name, { more: `data-on="${p.enabled === false ? 1 : 0}"` })
                    + (p.link ? '' : act(tt('更新', 'Update'), 'package-update', p.name)) + act(tt('移除', 'Remove'), 'package-remove', p.name, { danger: true }) })
        }).join('') + (rows.some((p) => !p.link) ? `<div class="btns"><button type="button" class="b" data-act="package-update" data-arg="">${icon('retry', 14)}${tt('全部更新', 'Update all')}</button></div>` : '')
            : empty(tt('还没有装扩展包', 'No packages are installed yet'), ''))
        + `<div class="lg">${tt('目录', 'Registry')}</div>`
        + `<div class="finder"><input type="search" id="pkg-q" value="${esc(query)}" placeholder="${tt('按名字或用途找扩展包', 'Find a package by name or by what it is for')}" aria-label="${tt('找扩展包', 'Find packages')}"></div><div id="pkg-results" aria-live="polite">${loading(tt('正在读目录…', 'Reading the registry…'))}</div>`
        + `<div class="lg">${tt('从别处安装', 'Install from elsewhere')}</div><p>${tt('文件夹、压缩包的地址，或 git 仓库（github:OWNER/REPO）', 'A folder, the address of an archive, or a git repository (github:OWNER/REPO)')}</p>`
        + `<div class="finder"><input type="text" id="pkg-source" spellcheck="false" placeholder="github:OWNER/REPO" aria-label="${tt('来源', 'Source')}"><button type="button" class="b" data-act="package-install-source">${tt('安装…', 'Install…')}</button></div><div id="pkg-status" role="status"></div>`
}

async function search() {
    const box = $('#pkg-results'); if (!box) return
    const asked = query
    const got = await get('/api/app/packages/search', { q: query })
    if (asked !== query || !box.isConnected) return
    if (!got) { box.innerHTML = problem(failed.get('/api/app/packages/search'), { title: tt('目录没有读出来', 'The registry could not be read'), retry: 'package-search' }); return }
    if (got.error) { box.innerHTML = problem({ error: got.error, fix: tt('检查网络，或者在上面的"目录地址"里换一个。', 'Check the network, or give another registry address above.') }, { title: tt('目录没有读出来', 'The registry could not be read'), retry: 'package-search' }); return }
    const rows = got.results || []
    box.innerHTML = rows.length ? rows.map((p) => row({ title: `${esc(p.name)} <span class="ver">${esc(p.version || '')}</span>`, sub: esc(p.summary || ''),
        marks: installed.has(p.name) ? mark(tt('已安装', 'installed'), 'eff') : '',
        actions: installed.has(p.name) ? '' : act(tt('安装', 'Install'), 'package-install', p.name, { glyph: 'plus' }) })).join('')
        : empty(query ? tt(`目录里没有匹配“${query}”的包`, `No package in the registry matches "${query}"`) : tt('目录是空的', 'The registry is empty'))
}

export function wire(ctx, pane) {
    const field = pane.querySelector('#pkg-q')
    field.oninput = () => { query = field.value.trim(); clearTimeout(asking); asking = setTimeout(search, 250) }
    pane.querySelector('#pkg-source').onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); pane.querySelector('[data-act="package-install-source"]').click() } }
    search()
}

// Install from a registry name or a source; a source from outside the registry is shown first.
async function install(source) {
    const status = $('#pkg-status')
    const say = (html) => { if (status && status.isConnected) status.innerHTML = html }
    say(`<span class="spin"></span>${esc(tt(`正在安装 ${source}，可能要一两分钟…`, `Installing ${source}; this can take a minute or two…`))}`)
    let r = await post('/api/app/packages/install', { source })
    if (r.ok && r.data && r.data.needs_trust) {
        const found = r.data.found || []
        say('')
        const go = await confirm({ title: tt('安装目录之外的包？', 'Install a package from outside the registry?'),
            text: found.map((f) => ((f.shown || {}).lines || [`${f.name} ${f.version || ''}`]).join(' · ')).join('\n') + '\n\n' + tt('它带的代码没有人审过，装上后会在这台电脑上运行。', 'Nobody reviewed the code it brings, and once installed it runs on this computer.'),
            yes: tt('信任并安装', 'Trust and install'), danger: true })
        if (!go) return
        say(`<span class="spin"></span>${esc(tt(`正在安装 ${source}…`, `Installing ${source}…`))}`)
        r = await post('/api/app/packages/install', { source, trust: true })
    }
    if (!r.ok) { say(''); return said(r, tt('没装上', 'It was not installed')) }
    const problems = (r.data && r.data.problems) || []
    say('')
    if (problems.length) toast(problems.map((p) => (typeof p === 'string' ? p : p.problem || p.error || JSON.stringify(p))).join(' · '), { error: true })
    else toast(tt(`已安装 ${((r.data && r.data.installed) || [source]).map((p) => (typeof p === 'string' ? p : p.name)).join('、')}`, `Installed ${((r.data && r.data.installed) || [source]).map((p) => (typeof p === 'string' ? p : p.name)).join(', ')}`))
    return c.reload()
}

export function actions() {
    on('package-search', search)
    on('package-install', (n) => install(n.dataset.arg))
    on('package-install-source', () => { const v = $('#pkg-source').value.trim(); if (!v) { $('#pkg-source').focus(); return null } return install(v) })
    on('package-enable', async (n) => {
        const r = await post('/api/app/packages/enable', { name: n.dataset.arg, on: n.dataset.on === '1' })
        if (!r.ok) return said(r)
        return c.reload()
    })
    on('package-update', async (n) => {
        const r = await post('/api/app/packages/update', { names: n.dataset.arg ? [n.dataset.arg] : [] })
        if (!r.ok) return said(r, tt('没更新成', 'It was not updated'))
        toast(tt('已是最新', 'Up to date'))
        return c.reload()
    })
    on('package-remove', async (n) => {
        if (!(await confirm({ title: tt(`移除扩展包 ${n.dataset.arg}？`, `Remove the package ${n.dataset.arg}?`), text: tt('它提供的环境、技能或渠道不再可用；数据不动。', 'What it provides (environments, skills, channels) is no longer available; data is not touched.'), yes: tt('移除', 'Remove'), danger: true }))) return
        const r = await post('/api/app/packages/remove', { name: n.dataset.arg })
        if (!r.ok) return said(r)
        return c.reload()
    })
}
