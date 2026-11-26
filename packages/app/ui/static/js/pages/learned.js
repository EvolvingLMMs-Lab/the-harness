// Settings › What it learned. The list of skills is Hermes Desktop's Skills panel (each with
// what it is and what can be done with it); the reaction tree is browsed like folders in a
// file manager, one level at a time with the path on top; memory is a list to read and
// forget from. What is the plan's own stays: the evidence of each item, how often it was
// used, the experience it came from ("expired" once that raw record was dropped for its
// age), the change against the version before, undo, and the read-only shared libraries.
import { esc, tt, evidence, when, modelName } from '../i18n.js'
import { post, failed } from '../api.js'
import { on, dialog, closeDialog, confirm, said, toast, row, mark, act, empty, problem } from '../ui.js'
import { icon } from '../icons.js'

export const identity = true
let c = null
let path = [] // where in the tree the page is
let opened = new Set() // skills shown with their detail
let skills = []

const chatTitle = (app, chat) => { const row = app.chats.find((x) => x.chat === chat); return row ? (row.kind === 'main' ? tt('主对话', 'Main conversation') : row.title) : chat }

function from(app, s) {
    const src = s.source || {}
    if (!src.chat && !src.source && !src.from) return ''
    const where = src.chat ? chatTitle(app, src.chat) : src.from || src.source
    return `${tt('来自', 'from')} ${where}${src.time ? ` · ${when(src.time)}` : ''}${src.expired ? ` · ${tt('原始记录已过期', 'its raw record has expired')}` : ''}`
}

async function skillHtml(ctx, s) {
    const e = evidence(s.evidence)
    const open = opened.has(s.name)
    const head = row({ title: `<button type="button" class="disc" data-act="skill-open" data-arg="${esc(s.name)}" aria-expanded="${open}">${icon(open ? 'down' : 'right', 12)}<span>${esc(s.description || s.name)}</span></button>`,
        sub: esc([s.description ? s.name : '', from(ctx.app, s)].filter(Boolean).join(' · ')),
        marks: mark(e.text, e.cls) + (s.archived ? mark(tt('已归档', 'archived'), 'off') : s.waiting ? mark(tt('等你批准', 'waits for you'), 'prop') : '') + `<span class="fv">${tt(`用过 ${s.uses ?? 0} 次`, `${s.uses ?? 0} use${s.uses === 1 ? '' : 's'}`)}</span>`,
        cls: s.archived ? 'dim' : '' })
    if (!open) return head
    const files = await ctx.get('/api/app/skill', { identity: ctx.id, name: s.name })
    const program = files && (files.files || []).find((f) => f.name.endsWith('.py') && !f.name.startsWith('test'))
    const text = files && (files.files || []).find((f) => f.name === 'SKILL.md')
    const src = s.source || {}
    return head + `<div class="ld">`
        + (s.success_rate !== null && s.success_rate !== undefined ? `<p>${tt(`完成率 ${Math.round(s.success_rate * 100)}%`, `${Math.round(s.success_rate * 100)}% done`)}</p>` : '')
        + (s.file ? `<p><code>${esc(s.file)}</code>${s.instructions_only ? ' · ' + tt('只有说明，没有程序', 'instructions only, no program') : ''}</p>` : '')
        + (program ? `<pre>${esc(program.text.trimEnd())}</pre>` : text ? `<pre>${esc(text.text.trimEnd())}</pre>` : '')
        + `<div class="la">${src.chat && !src.expired && ctx.id === ctx.app.identity.id ? act(tt('打开那次对话', 'Open that chat'), 'skill-chat', src.chat) : ''}`
        + (s.waiting ? act(tt('批准使用', 'Approve'), 'skill-do', s.name, { more: 'data-what="approve"' }) : '')
        + (s.archived || s.loaded === false ? act(tt('恢复', 'Restore'), 'skill-do', s.name, { more: 'data-what="restore"' }) : act(tt('撤销到上一版', 'Undo to the version before'), 'skill-do', s.name, { more: 'data-what="undo"' }))
        + act(tt('看改动', 'See the change'), 'skill-diff', s.name) + act(tt('删除', 'Delete'), 'skill-delete', s.name, { danger: true }) + `</div></div>`
}

function treeHtml(t) {
    const nodes = t.nodes || [], at = t.path || path
    const crumbs = [tt('根', 'root'), ...at]
    const lit = nodes.some((n) => n.lit)
    return `<div class="tv"><div class="crumbs" aria-label="${tt('在树里的位置', 'Where in the tree')}">${crumbs.map((x, i) => `<button type="button" class="bc${i === crumbs.length - 1 ? ' on' : ''}${lit && i === crumbs.length - 1 ? ' lit' : ''}" data-act="tree-up" data-arg="${i}">${esc(x)}</button>`).join('<i>›</i>')}</div>`
        + (nodes.length ? nodes.map((n, i) => {
            const label = n.about || [typeof n.when === 'string' ? n.when : '', typeof n.do === 'string' ? n.do : ''].filter(Boolean).join(' → ') || n.name
            const e = evidence(n.source === 'builtin' ? 'builtin' : n.source === 'owner' ? 'owner' : n.evidence)
            const order = `<span class="ord">${i + 1}</span>`
            if (n.children) {
                return row({ title: `<button type="button" class="disc" data-act="tree-open" data-arg="${esc(n.name)}">${order}${icon('folder', 14)}<span>${esc(label)}</span></button>`,
                    marks: `<span class="fv">${tt(`${n.children} 个节点`, `${n.children} node${n.children === 1 ? '' : 's'}`)}</span>`, cls: n.lit ? 'lit' : '',
                    actions: act(n.enabled === false ? tt('启用', 'Enable') : tt('停用', 'Disable'), 'tree-do', n.name, { more: `data-what="${n.enabled === false ? 'enable' : 'disable'}"` }) })
            }
            return row({ title: `${order}<span>${esc(label)}</span>`, sub: esc(n.name === label ? '' : n.name), cls: `${n.enabled === false ? 'dim' : ''}${n.lit ? ' lit' : ''}`,
                marks: mark(e.text, e.cls) + (n.enabled === false ? mark(tt('已停用', 'off'), 'off') : '') + `<span class="fv">${tt(`${n.uses ?? 0} 次`, `${n.uses ?? 0} use${n.uses === 1 ? '' : 's'}`)}</span>`,
                actions: (i > 0 ? `<button type="button" class="lb" data-act="tree-move" data-arg="${esc(n.name)}" data-before="${esc(nodes[i - 1].name)}" aria-label="${esc(tt(`把“${label}”上移`, `Move "${label}" up`))}" data-tip="${tt('上移：排在上面的先判断', 'Move up: the upper one is judged first')}">${icon('up', 14)}</button>` : '')
                    + act(n.enabled === false ? tt('启用', 'Enable') : tt('停用', 'Disable'), 'tree-do', n.name, { more: `data-what="${n.enabled === false ? 'enable' : 'disable'}"` })
                    + (n.source === 'builtin' ? '' : act(tt('删除', 'Delete'), 'tree-remove', n.name, { danger: true })) })
        }).join('') : empty(tt('这一层是空的', 'This level is empty'))) + `</div>`
}

export async function draw(ctx) {
    if (c && c.id !== ctx.id) { path = []; opened = new Set() }
    c = ctx
    const [got, tree, sources, models] = await Promise.all([ctx.get('/api/agent/learned', { identity: ctx.id }), ctx.get('/api/agent/tree', { identity: ctx.id, path: path.join('/') }),
        ctx.get('/api/agent/skill_sources', { identity: ctx.id }), ctx.get('/api/app/models')])
    if (!got) return problem(failed.get('/api/agent/learned'), { title: tt('学到的东西没有读出来', 'What it learned could not be read'), retry: 'settings' })
    skills = got.skills || []
    const raw = got.memory || {}
    const memory = Array.isArray(raw) ? raw : Object.entries(raw).map(([key, v]) => (typeof v === 'string' ? { key, text: v } : { key, ...v }))
    const shared = (sources && sources.shared && sources.shared.length ? sources.shared : got.shared_libraries) || []
    const entries = ((models && models.models) || []).filter((m) => m.enabled !== false)
    const review = [{ value: '', label: tt('这个身份的模型', "This identity's model") }, ...entries.map((m) => ({ value: m.id, label: String(m.provider || '').startsWith('acp:') ? m.name || m.provider.slice(4) : modelName(m.model) || m.name }))]
    const rows = await Promise.all(skills.map((s) => skillHtml(ctx, s)))
    return ``
        + ctx.setting('learning.mode') + ctx.setting('learning.admission') + ctx.setting('learning.review_model', { choices: review }) + ctx.setting('learning.active_minutes')
        + `<div class="lg">${tt('技能', 'Skills')}</div>` + (rows.length ? rows.join('') : empty(tt('还没有学会技能', 'No skills learned yet'), ''))
        + `<div class="btns"><button type="button" class="b" data-act="settings" data-arg="connectors">${tt('技能来源…', 'Skill sources…')}</button></div>`
        + `<div class="lg">${tt('反射树', 'Tree of reactions')}</div>`
        + (tree ? treeHtml(tree) : problem(failed.get('/api/agent/tree'), { title: tt('反射树没有读出来', 'The tree could not be read'), retry: 'settings' }))
        + `<div class="lg">${tt('记忆', 'Memory')}</div>` + (memory.length ? memory.map((m) => {
            const e = evidence(m.scope || 'private')
            return row({ title: esc(m.text || m.key), sub: esc([m.text ? m.key : '', m.chat ? chatTitle(ctx.app, m.chat) : '', m.source, m.updated ? when(m.updated) : ''].filter(Boolean).join(' · ')),
                marks: mark(e.text, e.cls), actions: m.key ? act(tt('忘掉', 'Forget'), 'memory-forget', m.key, { danger: true }) : '' })
        }).join('') : empty(tt('还没有记忆', 'Nothing remembered yet'), ''))
        + (shared.length ? `<div class="lg">${tt('共享库 · 只读', 'Shared libraries · read only')}</div>` + shared.map((l) => row({ title: esc(l.name || l), sub: esc([l.package, l.folder || l.path].filter(Boolean).join(' · ')),
            marks: l.entries !== undefined ? `<span class="fv">${tt(`${l.entries} 项`, `${l.entries} entries`)}</span>` : '' })).join('') : '')
}

async function learned(action, name) {
    const r = await post('/api/agent/learned', { identity: c.id, action, name })
    if (!r.ok) { said(r); return null }
    return r.data
}

export function actions(app) {
    on('skill-open', (n) => { const name = n.dataset.arg; if (opened.has(name)) opened.delete(name); else opened.add(name); return c.reload() })
    on('skill-chat', async (n) => { await app.openChat(n.dataset.arg) })
    on('skill-do', async (n) => {
        const done = await learned(n.dataset.what, n.dataset.arg)
        if (!done) return
        toast({ approve: tt('已批准使用', 'Approved'), restore: tt('已恢复', 'Restored'), undo: tt('已撤销到上一版', 'Back at the version before') }[n.dataset.what])
        return c.reload()
    })
    on('skill-diff', async (n) => {
        const done = await learned('diff', n.dataset.arg)
        if (!done) return
        const text = ((done.result || done).diff) || ''
        const d = dialog(`<h5>${tt('改动', 'The change')} · ${esc(n.dataset.arg)}</h5>`
            + (text ? `<pre class="logtail">${text.split(/\r?\n/).map((l) => `<span class="${l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : ''}">${esc(l)}</span>`).join('\n')}</pre>` : `<p class="say">${tt('没有上一版：这是它的第一版。', 'There is no version before: this is its first.')}</p>`)
            + `<div class="row"><span class="res"></span><button type="button" class="btn" data-default>${tt('关闭', 'Close')}</button></div>`)
        d.classList.add('wide')
        d.querySelector('[data-default]').onclick = closeDialog
    })
    on('skill-delete', async (n) => {
        if (!(await confirm({ title: tt(`删除技能 ${n.dataset.arg}？`, `Delete the skill ${n.dataset.arg}?`), text: tt('它不再被加载。想留着以后再用，用"撤销到上一版"或让它归档。', 'It is no longer loaded. To keep it for later, undo to the version before instead.'), yes: tt('删除', 'Delete'), danger: true }))) return
        if (await learned('delete', n.dataset.arg)) { opened.delete(n.dataset.arg); return c.reload() }
    })
    on('memory-forget', async (n) => {
        if (!(await confirm({ title: tt('忘掉这条记忆？', 'Forget this memory?'), text: n.dataset.arg, yes: tt('忘掉', 'Forget'), danger: true }))) return
        if (await learned('forget', n.dataset.arg)) return c.reload()
    })
    on('tree-up', (n) => { path = path.slice(0, +n.dataset.arg); return c.reload() })
    on('tree-open', (n) => { path = [...path, n.dataset.arg]; return c.reload() })
    const tree = async (body) => {
        const r = await post('/api/agent/tree', { identity: c.id, ...body })
        if (!r.ok) { said(r); return }
        return c.reload()
    }
    on('tree-do', (n) => tree({ action: n.dataset.what, path: [...path, n.dataset.arg].join('/') }))
    on('tree-move', (n) => tree({ action: 'move', name: n.dataset.arg, under: path[path.length - 1] || null, before: n.dataset.before, path: path.join('/') }))
    on('tree-remove', async (n) => {
        if (!(await confirm({ title: tt('删除这个节点？', 'Delete this node?'), text: tt('它下面的节点一起删掉。出厂的节点只能停用。', 'The nodes under it go with it. Built-in nodes can only be disabled.'), yes: tt('删除', 'Delete'), danger: true }))) return
        return tree({ action: 'remove', path: [...path, n.dataset.arg].join('/') })
    })
}
