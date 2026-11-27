// First-class Customizations workspace (Antigravity agy-customizations + Cursor Rules/Memories separation):
//   6 first-class tabs:
//   - Skills: installed & learned skills, syntax-highlighted SKILL.md / .py preview, live search (zero focus loss)
//   - Rules: two-pane editor for Global (AGENTS.md), Project (AGENTS.md / CLAUDE.md), and Persona files + unsaved guard
//   - Memory: dedicated tab for long-term memory entries (search, + New Memory, edit/save, delete confirm, MEMORY.md preview)
//   - Behavior Tree: two-pane Explorer (drag-and-drop, priority ordering, live search zero focus loss)
//   - MCP & Connectors: real settings context wired to /api/app/settings & /api/agent/settings
//   - Packages: real settings context wired to /api/app/settings & /api/agent/settings
import { esc, tt, evidence } from './i18n.js'
import { get, post, failed } from './api.js'
import { $, $$, ic, loading, empty, problem, toast, said, confirm, dialog, closeDialog, mark } from './ui.js'
import { icon } from './icons.js'
import { prefs } from './prefs.js'
import { keysOf } from './keys.js'
import { settingRow, wireSettings } from './fields.js'
import { rulesDialog } from './rules.js'
import * as connectors from './pages/connectors.js'
import * as packages from './pages/packages.js'

const TABS = [
    ['skills', '技能', 'Skills', 'command'],
    ['rules', '规则', 'Rules', 'file'],
    ['memory', '记忆', 'Memory', 'context'],
    ['tree', '行为树', 'Behavior Tree', 'branch'],
    ['connectors', 'MCP 与连接器', 'MCP & Connectors', 'sliders'],
    ['packages', '扩展包', 'Packages', 'folder'],
]

let tab = prefs.get('customizations.tab', 'skills')
let selectedRule = null // "scope:name"
let selectedMemory = null // "scope:name"
let memoryQuery = ''
let selectedSkill = null
let skillQuery = ''
let selectedNode = null // node name in Behavior Tree
let treeExpanded = new Set()
let treeQuery = ''
let treeNodes = [] // full recursive tree from /api/agent/tree?all=1
let addingNode = false
let dragNode = null
let editorDirty = false

function highlight(text, lang) {
    if (window.hljs) {
        try {
            if (lang && window.hljs.getLanguage(lang)) return window.hljs.highlight(text, { language: lang, ignoreIllegals: true }).value
            return window.hljs.highlightAuto(text).value
        } catch { /* fallback */ }
    }
    return esc(text)
}

async function guardUnsaved() {
    if (!editorDirty) return true
    const leave = await confirm({
        title: tt('放弃未保存的修改？', 'Discard unsaved changes?'),
        text: tt('当前文件有尚未保存的编辑，切换后修改将会丢失。', 'Your edits in the current file have not been saved yet.'),
        yes: tt('放弃修改', 'Discard'),
        danger: true,
    })
    if (leave) editorDirty = false
    return leave
}

async function makeSubCtx(app) {
    const id = app.identity.id
    const [coreRes, ownRes] = await Promise.all([
        get('/api/app/settings'),
        get('/api/agent/settings', { identity: id }),
    ])
    let core = coreRes || { values: app.values || {}, schema: app.schema || {} }
    let own = ownRes || { values: {}, schema: {} }
    const split = (name) => { const at = name.indexOf('.'); return [name.slice(0, at), name.slice(at + 1)] }
    const spec = (name) => {
        const [section, key] = split(name)
        return (own.schema && own.schema[name]) || (core.schema[section] || {})[key] || {}
    }
    const mine = (name) => spec(name).scope === 'identity'
    const value = (name) => {
        const [section, key] = split(name)
        if (mine(name) && own.values && name in own.values) return own.values[name]
        const v = (core.values[section] || {})[key]
        return v !== undefined ? v : spec(name).default
    }
    const c = {
        app, section: tab, id, name: app.identity.name || id,
        many: app.identities.length > 1, pane: $('.pg-custom .cu-body'),
        get: (path, params) => get(path, params),
        spec, value, core: () => core, own: () => own, advanced: [],
        setting(name, options = {}) {
            const s = spec(name)
            if (s.shown === false) return ''
            return settingRow({ name, spec: s, value: value(name), ...options })
        },
        group(title, names) {
            const rows = names.map((name) => c.setting(name)).join('')
            return rows ? `<div class="lg">${esc(title)}</div>${rows}` : ''
        },
        async save(name, v) {
            const [section, key] = split(name)
            const r = mine(name)
                ? await post('/api/agent/settings', { identity: id, key: name, value: v })
                : await post('/api/app/settings', { [section]: { [key]: v } })
            if (!r.ok) return r
            if (mine(name)) {
                if (r.data && r.data.values) own = r.data
            } else {
                if (r.data && r.data.values) core = { ...core, values: r.data.values }
                if (app.applied) app.applied(section, key, v)
            }
            return r
        },
        reload: () => render(app),
    }
    return c
}

export async function open(app, nextTab = null) {
    if (nextTab && TABS.some((t) => t[0] === nextTab)) {
        tab = nextTab
        prefs.set('customizations.tab', tab)
    }
    editorDirty = false
    return render(app)
}

export async function render(app) {
    const host = $('.pg-custom')
    if (!host) return
    editorDirty = false
    host.innerHTML = `<header class="cu-head">
        ${ic('sidebar', tt('展开左栏', 'Show sidebar'), { act: 'side-toggle', keys: keysOf('sidebar'), cls: 'show-side' })}
        <h2>${tt('自定义', 'Customizations')}</h2>
        <nav class="cu-tabs" role="tablist" aria-label="${tt('自定义分类', 'Customization tabs')}">
            ${TABS.map(([id, zh, en, icName]) => `<button type="button" role="tab" aria-selected="${tab === id}" class="${tab === id ? 'on' : ''}" data-cu-tab="${id}">${icon(icName, 14)}<span>${tt(zh, en)}</span></button>`).join('')}
        </nav>
    </header>
    <div class="cu-body">${loading()}</div>`
    host.querySelectorAll('[data-cu-tab]').forEach((b) => {
        b.onclick = async () => {
            if (b.dataset.cuTab === tab) return
            if (!(await guardUnsaved())) return
            tab = b.dataset.cuTab
            prefs.set('customizations.tab', tab)
            render(app)
        }
    })
    const body = host.querySelector('.cu-body')
    if (tab === 'skills') await renderSkills(app, body)
    else if (tab === 'rules') await renderRules(app, body)
    else if (tab === 'memory') await renderMemory(app, body)
    else if (tab === 'tree') await renderTree(app, body)
    else if (tab === 'connectors') await renderConnectors(app, body)
    else if (tab === 'packages') await renderPackages(app, body)
}

// ── 1. Skills (local list & detail updates preserve search input focus!) ──
async function renderSkills(app, body) {
    const [got, sources] = await Promise.all([
        get('/api/agent/learned', { identity: app.identity.id }),
        get('/api/agent/skill_sources', { identity: app.identity.id }),
    ])
    if (!got) { body.innerHTML = problem(failed.get('/api/agent/learned'), { retry: 'customizations' }); return }
    const allSkills = got.skills || []
    app.skills = allSkills
    const shared = (sources && sources.shared && sources.shared.length ? sources.shared : got.shared_libraries) || []
    if (selectedSkill && !allSkills.some((s) => s.name === selectedSkill)) selectedSkill = null
    if (!selectedSkill && allSkills.length) selectedSkill = allSkills[0].name

    body.innerHTML = `<div class="cu-split">
        <div class="cu-left">
            <div class="cu-bar">
                <input class="field" type="search" data-sk-q value="${esc(skillQuery)}" placeholder="${tt('搜索技能…', 'Search skills…')}">
                <button type="button" class="b" data-sk-src>${icon('plus', 13)}${tt('来源', 'Source')}</button>
            </div>
            <div class="cu-list" data-sk-list></div>
        </div>
        <div class="cu-right" data-sk-detail></div>
    </div>`

    const listEl = body.querySelector('[data-sk-list]')
    const detailEl = body.querySelector('[data-sk-detail]')

    const drawList = () => {
        const q = skillQuery.trim().toLowerCase()
        const filtered = q ? allSkills.filter((s) => `${s.name} ${s.description || ''}`.toLowerCase().includes(q)) : allSkills
        listEl.innerHTML = (filtered.length
            ? filtered.map((s) => `<button type="button" class="cu-item${s.name === selectedSkill ? ' on' : ''}${s.archived ? ' dim' : ''}" data-sk-sel="${esc(s.name)}">
                ${icon('command', 14)}<span class="cu-it-main"><b>${esc(s.name)}</b><small>${esc(s.description || '')}</small></span>
            </button>`).join('')
            : empty(q ? tt('没有匹配的技能', 'No matching skills') : tt('暂无技能', 'No skills yet'), ''))
            + (shared.length ? `<div class="cu-sec">${tt('共享只读库', 'Shared libraries')}</div>` + shared.map((l) => `<div class="cu-item static">${icon('folder', 14)}<span class="cu-it-main"><b>${esc(l.name || l)}</b><small>${esc(l.path || l.folder || '')}</small></span></div>`).join('') : '')
    }

    const drawDetail = async () => {
        const cur = allSkills.find((s) => s.name === selectedSkill) || null
        if (!cur) {
            detailEl.innerHTML = empty(tt('选择一个技能查看详情', 'Select a skill to inspect'), '')
            return
        }
        detailEl.innerHTML = loading()
        const files = await get('/api/app/skill', { identity: app.identity.id, name: cur.name })
        if (selectedSkill !== cur.name) return
        const e = evidence(cur.evidence)
        const doc = files && (files.files || []).find((f) => f.name === 'SKILL.md')
        const prog = files && (files.files || []).find((f) => f.name.endsWith('.py') && !f.name.startsWith('test'))
        detailEl.innerHTML = `<div class="cu-ins-head">
            <div><h3>${esc(cur.name)}</h3>${cur.description ? `<p class="cu-sub">${esc(cur.description)}</p>` : ''}</div>
            <div class="cu-ins-acts">
                ${mark(e.text, e.cls)}
                <span class="fv">${tt(`使用 ${cur.uses ?? 0} 次`, `${cur.uses ?? 0} uses`)}</span>
                ${cur.waiting ? `<button type="button" class="b" data-sk-act="approve" data-sk="${esc(cur.name)}">${tt('批准', 'Approve')}</button>` : ''}
                ${cur.archived || cur.loaded === false
                    ? `<button type="button" class="b" data-sk-act="restore" data-sk="${esc(cur.name)}">${tt('恢复', 'Restore')}</button>`
                    : `<button type="button" class="b quiet" data-sk-act="undo" data-sk="${esc(cur.name)}">${tt('撤销上一版', 'Undo')}</button>`}
                <button type="button" class="b quiet" data-sk-act="diff" data-sk="${esc(cur.name)}">${tt('差异', 'Diff')}</button>
                <button type="button" class="b quiet danger" data-sk-act="delete" data-sk="${esc(cur.name)}">${tt('删除', 'Delete')}</button>
            </div>
        </div>`
            + (doc ? `<div class="vt">SKILL.md</div><pre class="cu-code"><code class="hljs">${highlight(doc.text, 'markdown')}</code></pre>` : '')
            + (prog ? `<div class="vt">${esc(prog.name)}</div><pre class="cu-code"><code class="hljs">${highlight(prog.text, 'python')}</code></pre>` : '')
    }

    const qIn = body.querySelector('[data-sk-q]')
    if (qIn) qIn.oninput = () => { skillQuery = qIn.value; drawList() }
    body.onclick = async (e) => {
        const sel = e.target.closest('[data-sk-sel]')
        if (sel) { selectedSkill = sel.dataset.skSel; drawList(); drawDetail(); return }
        if (e.target.closest('[data-sk-src]')) { tab = 'connectors'; render(app); return }
        const ab = e.target.closest('[data-sk-act]')
        if (!ab) return
        const actName = ab.dataset.skAct, name = ab.dataset.sk
        if (actName === 'delete') {
            if (!(await confirm({ title: tt(`删除技能 ${name}？`, `Delete skill ${name}?`), text: tt('该技能将不再加载。', 'This skill will no longer be loaded.'), yes: tt('删除', 'Delete'), danger: true }))) return
        }
        const r = await post('/api/agent/learned', { identity: app.identity.id, action: actName, name })
        if (!r.ok) return said(r)
        if (actName === 'diff') {
            const txt = ((r.data.result || r.data).diff) || ''
            const d = dialog(`<h5>${tt('差异', 'Diff')} · ${esc(name)}</h5>` + (txt ? `<pre class="logtail">${esc(txt)}</pre>` : `<p class="say">${tt('暂无历史版本差异。', 'No previous version diff.')}</p>`) + `<div class="row"><button type="button" class="btn" data-default>${tt('关闭', 'Close')}</button></div>`)
            d.classList.add('wide'); d.querySelector('[data-default]').onclick = closeDialog
            return
        }
        if (actName === 'delete') selectedSkill = null
        toast(tt('已更新', 'Updated'))
        renderSkills(app, body)
    }
    drawList()
    await drawDetail()
}

// ── 2. Rules (Global / Project / Persona — Memory separated into its own tab) ──
async function renderRules(app, body) {
    const got = await get('/api/app/rules', { identity: app.identity.id, chat: app.chat })
    if (!got) { body.innerHTML = problem(failed.get('/api/app/rules'), { retry: 'customizations' }); return }
    const files = (got.files || []).filter((f) => f.scope !== 'memory' && f.name !== 'MEMORY.md')
    const keyOf = (f) => `${f.scope}:${f.name}`
    if (!selectedRule || !files.some((f) => keyOf(f) === selectedRule)) selectedRule = files[0] ? keyOf(files[0]) : null
    const cur = files.find((f) => keyOf(f) === selectedRule) || null
    const groups = [
        ['global', tt('全局规则', 'Global')],
        ...(got.project ? [['project', `${tt('项目', 'Project')} · ${got.project}`]] : []),
        ['persona', tt('身份人设', 'Persona')],
    ]
    editorDirty = false
    body.innerHTML = `<div class="cu-split">
        <div class="cu-left">
            <div class="cu-list">
                ${groups.map(([sc, label]) => {
                    const items = files.filter((f) => f.scope === sc)
                    if (!items.length) return ''
                    return `<div class="cu-sec">${esc(label)}</div>` + items.map((f) => `<button type="button" class="cu-item${keyOf(f) === selectedRule ? ' on' : ''}" data-rl-sel="${esc(keyOf(f))}">
                        ${icon('file', 14)}<span class="cu-it-main"><b>${esc(f.title || f.name)}</b><small>${f.exists ? tt('已存在', 'active') : tt('新建', 'new')}</small></span>
                    </button>`).join('')
                }).join('')}
            </div>
        </div>
        <div class="cu-right">
            ${cur ? `<div class="cu-ins-head">
                <div><h3>${esc(cur.title || cur.name)}</h3><p class="cu-sub">${esc(cur.path)}</p></div>
                <div class="cu-ins-acts"><span class="cu-dirty" data-dirty hidden>${tt('未保存', 'Unsaved')}</span><button type="button" class="b" data-rl-save>${tt('保存', 'Save')}</button></div>
            </div>
            <textarea class="cu-editor" data-rl-text spellcheck="false" placeholder="# ${esc(cur.name)}">${esc(cur.text || '')}</textarea>` : empty(tt('暂无规则文件', 'No rule files'))}
        </div>
    </div>`
    const ta = body.querySelector('[data-rl-text]'), dirty = body.querySelector('[data-dirty]')
    if (ta && dirty) ta.oninput = () => { editorDirty = ta.value !== (cur.text || ''); dirty.hidden = !editorDirty }
    body.onclick = async (e) => {
        const sel = e.target.closest('[data-rl-sel]')
        if (sel) {
            if (sel.dataset.rlSel === selectedRule) return
            if (!(await guardUnsaved())) return
            selectedRule = sel.dataset.rlSel
            renderRules(app, body)
            return
        }
        const save = e.target.closest('[data-rl-save]')
        if (save && cur && ta) {
            save.disabled = true
            const r = await post('/api/app/rules', { identity: app.identity.id, chat: app.chat, scope: cur.scope, file: cur.name, text: ta.value })
            save.disabled = false
            if (!r.ok) return said(r)
            cur.text = ta.value
            editorDirty = false
            if (dirty) dirty.hidden = true
            toast(tt(`已保存 ${cur.title || cur.name}`, `Saved ${cur.title || cur.name}`))
        }
    }
}

// ── 3. Memory (dedicated first-class tab with search, + New, edit, delete confirm, MEMORY.md preview) ──
async function renderMemory(app, body) {
    const got = await get('/api/app/rules', { identity: app.identity.id, chat: app.chat })
    if (!got) { body.innerHTML = problem(failed.get('/api/app/rules'), { retry: 'customizations' }); return }
    const memFiles = (got.files || []).filter((f) => f.scope === 'memory' || (f.scope === 'persona' && f.name === 'MEMORY.md'))
    const keyOf = (f) => `${f.scope}:${f.name}`
    const entries = memFiles.filter((f) => f.scope === 'memory')
    const indexFile = memFiles.find((f) => f.name === 'MEMORY.md') || null
    if (!selectedMemory || !memFiles.some((f) => keyOf(f) === selectedMemory)) {
        selectedMemory = entries[0] ? keyOf(entries[0]) : (indexFile ? keyOf(indexFile) : null)
    }

    body.innerHTML = `<div class="cu-split">
        <div class="cu-left">
            <div class="cu-bar">
                <input class="field" type="search" data-mem-q value="${esc(memoryQuery)}" placeholder="${tt('搜索记忆…', 'Search memory…')}">
                <button type="button" class="b" data-mem-new>${icon('plus', 13)}${tt('新建', 'New')}</button>
            </div>
            <div class="cu-list" data-mem-list></div>
        </div>
        <div class="cu-right" data-mem-detail></div>
    </div>`

    const listEl = body.querySelector('[data-mem-list]')
    const detailEl = body.querySelector('[data-mem-detail]')

    const drawList = () => {
        const q = memoryQuery.trim().toLowerCase()
        const filtered = q
            ? entries.filter((f) => `${f.title || ''} ${f.name} ${f.text || ''}`.toLowerCase().includes(q))
            : entries
        const idxHtml = indexFile
            ? `<div class="cu-sec">${tt('摘要索引', 'Index')}</div>`
                + `<button type="button" class="cu-item${keyOf(indexFile) === selectedMemory ? ' on' : ''}" data-mem-sel="${esc(keyOf(indexFile))}">`
                + `${icon('context', 14)}<span class="cu-it-main"><b>MEMORY.md</b><small>${tt('自动生成的记忆索引', 'Auto-generated index')}</small></span></button>`
            : ''
        const entHtml = `<div class="cu-sec">${tt(`记忆条目 (${filtered.length})`, `Memory Entries (${filtered.length})`)}</div>`
            + (filtered.length
                ? filtered.map((f) => `<button type="button" class="cu-item${keyOf(f) === selectedMemory ? ' on' : ''}" data-mem-sel="${esc(keyOf(f))}">`
                    + `${icon('file', 14)}<span class="cu-it-main"><b>${esc(f.title || f.name)}</b><small>${esc(f.name)}</small></span></button>`).join('')
                : empty(q ? tt('没有匹配的记忆', 'No matching memory') : tt('暂无记忆条目', 'No memory entries yet'), ''))
        listEl.innerHTML = idxHtml + entHtml
    }

    const drawDetail = () => {
        editorDirty = false
        const cur = memFiles.find((f) => keyOf(f) === selectedMemory) || null
        if (!cur) {
            detailEl.innerHTML = empty(tt('选择或新建一条记忆', 'Select or create a memory entry'), '')
            return
        }
        const ro = !!cur.readonly
        detailEl.innerHTML = `<div class="cu-ins-head">
            <div><h3>${esc(cur.title || cur.name)}</h3><p class="cu-sub">${esc(cur.path)}</p></div>
            <div class="cu-ins-acts">
                ${ro ? '' : `<span class="cu-dirty" data-dirty hidden>${tt('未保存', 'Unsaved')}</span>`}
                ${cur.scope === 'memory' ? `<button type="button" class="b quiet danger" data-mem-del>${tt('删除', 'Delete')}</button>` : ''}
                ${ro ? '' : `<button type="button" class="b" data-mem-save>${tt('保存', 'Save')}</button>`}
            </div>
        </div>
        ${ro ? `<div class="cu-ro-note">${tt('MEMORY.md 是自动生成的记忆索引，保存或删除左侧记忆条目后会自动刷新。', 'MEMORY.md is an auto-generated summary index; it updates automatically when entries are saved or deleted.')}</div>` : ''}
        <textarea class="cu-editor" data-mem-text spellcheck="false"${ro ? ' readonly' : ''} placeholder="${tt('输入需要长期记住的偏好、事实或项目约定…', 'Write preferences, facts, or conventions to remember…')}">${esc(cur.text || '')}</textarea>`
        const ta = detailEl.querySelector('[data-mem-text]'), dirty = detailEl.querySelector('[data-dirty]')
        if (ta && dirty && !ro) {
            ta.oninput = () => { editorDirty = ta.value !== (cur.text || ''); dirty.hidden = !editorDirty }
        }
    }

    const openNewMemoryDialog = () => {
        const d = dialog(`<h5>${tt('新建记忆', 'New Memory')}</h5>
            <label><span>${tt('标题', 'Title')}</span><input class="field" data-m-title placeholder="${tt('例如：代码风格偏好', 'e.g. Code style preferences')}" autofocus></label>
            <label><span>${tt('文件名', 'Filename')}</span><input class="field" data-m-slug placeholder="code-style.md" spellcheck="false"></label>
            <label><span>${tt('内容', 'Content')}</span><textarea class="field" data-m-body rows="5" placeholder="${tt('写下希望 Agent 长期记住的内容…', 'What should the agent remember?')}"></textarea></label>
            <div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('创建', 'Create')}</button></div>`)
        const titleIn = d.querySelector('[data-m-title]'), slugIn = d.querySelector('[data-m-slug]')
        const bodyIn = d.querySelector('[data-m-body]'), res = d.querySelector('.res')
        titleIn.oninput = () => {
            if (slugIn.dataset.touched) return
            const base = titleIn.value.trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5_-]+/g, '-').replace(/^-+|-+$/g, '')
            slugIn.value = base ? `${base}.md` : ''
        }
        slugIn.oninput = () => { slugIn.dataset.touched = '1' }
        d.querySelector('[data-no]').onclick = closeDialog
        d.querySelector('[data-default]').onclick = async () => {
            const titleVal = titleIn.value.trim()
            let file = slugIn.value.trim().replace(/[\\/]/g, '')
            if (!file) file = `note-${Date.now().toString(36)}.md`
            if (!file.endsWith('.md')) file += '.md'
            if (file.startsWith('.')) { res.innerHTML = `<span class="c-failed">✕ ${tt('文件名不能以点开头', 'Filename cannot start with a dot')}</span>`; return }
            const content = bodyIn.value.trim()
            const md = titleVal
                ? `---\nkey: ${JSON.stringify(titleVal)}\n---\n\n${content || titleVal}\n`
                : `${content}\n`
            const r = await post('/api/app/rules', { identity: app.identity.id, chat: app.chat, scope: 'memory', file, text: md })
            if (!r.ok) { res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
            closeDialog()
            selectedMemory = `memory:${file}`
            toast(tt(`已创建记忆 ${titleVal || file}`, `Created memory ${titleVal || file}`))
            renderMemory(app, body)
        }
    }

    const qIn = body.querySelector('[data-mem-q]')
    if (qIn) qIn.oninput = () => { memoryQuery = qIn.value; drawList() }
    body.onclick = async (e) => {
        if (e.target.closest('[data-mem-new]')) {
            if (!(await guardUnsaved())) return
            openNewMemoryDialog()
            return
        }
        const sel = e.target.closest('[data-mem-sel]')
        if (sel) {
            if (sel.dataset.memSel === selectedMemory) return
            if (!(await guardUnsaved())) return
            selectedMemory = sel.dataset.memSel
            drawList()
            drawDetail()
            return
        }
        const del = e.target.closest('[data-mem-del]')
        if (del) {
            const cur = memFiles.find((f) => keyOf(f) === selectedMemory)
            if (!cur || cur.scope !== 'memory') return
            if (!(await confirm({
                title: tt(`删除记忆“${cur.title || cur.name}”？`, `Delete memory "${cur.title || cur.name}"?`),
                text: tt('删除后该条记忆将从索引中移除，无法恢复。', 'This memory entry will be permanently deleted.'),
                yes: tt('删除', 'Delete'),
                danger: true,
            }))) return
            del.disabled = true
            const r = await post('/api/app/rules', { identity: app.identity.id, chat: app.chat, scope: 'memory', file: cur.name, action: 'delete' })
            del.disabled = false
            if (!r.ok) return said(r)
            selectedMemory = null
            editorDirty = false
            toast(tt(`已删除 ${cur.title || cur.name}`, `Deleted ${cur.title || cur.name}`))
            renderMemory(app, body)
            return
        }
        const save = e.target.closest('[data-mem-save]')
        if (save) {
            const cur = memFiles.find((f) => keyOf(f) === selectedMemory)
            const ta = detailEl.querySelector('[data-mem-text]'), dirty = detailEl.querySelector('[data-dirty]')
            if (!cur || !ta) return
            save.disabled = true
            const r = await post('/api/app/rules', { identity: app.identity.id, chat: app.chat, scope: 'memory', file: cur.name, text: ta.value })
            save.disabled = false
            if (!r.ok) return said(r)
            cur.text = ta.value
            editorDirty = false
            if (dirty) dirty.hidden = true
            toast(tt(`已保存 ${cur.title || cur.name}`, `Saved ${cur.title || cur.name}`))
        }
    }
    drawList()
    drawDetail()
}

// ── 4. Behavior Tree (Two-Pane File Explorer — local filter update preserves search focus!) ──
function flattenNodes(nodes, out = []) {
    for (const n of nodes || []) {
        out.push(n)
        if (n.children && n.children.length) flattenNodes(n.children, out)
    }
    return out
}

function findNode(nodes, name) {
    for (const n of nodes || []) {
        if (n.name === name) return n
        const hit = findNode(n.children, name)
        if (hit) return hit
    }
    return null
}

function siblingsOf(nodes, targetName, parent = null) {
    for (const n of nodes || []) {
        if (n.name === targetName) return { parent, list: nodes }
        const hit = siblingsOf(n.children, targetName, n.name)
        if (hit) return hit
    }
    return { parent: null, list: [] }
}

function matchesFilter(node, q) {
    if (!q) return true
    if (`${node.name} ${node.about || ''}`.toLowerCase().includes(q)) return true
    return (node.children || []).some((c) => matchesFilter(c, q))
}

const BUILTIN_LABELS = {
    named: ['被点名或提及时唤醒', 'Wake when addressed'],
    failed: ['动作失败或不确定时唤醒', 'Wake on failed action'],
    approval: ['需要批准时提醒', 'Remind on pending approval'],
}
function nodeLabel(n) {
    if (n.source === 'builtin' && BUILTIN_LABELS[n.name] && (!n.about || n.about.includes('→'))) {
        return tt(BUILTIN_LABELS[n.name][0], BUILTIN_LABELS[n.name][1])
    }
    return n.about || n.name
}

function renderTreeNodesHtml(nodes, depth, q) {
    const visible = (nodes || []).filter((n) => matchesFilter(n, q))
    return visible.map((n, idx) => {
        const isFolder = n.situation || (n.children && n.children.length > 0)
        const isOpen = isFolder && (treeExpanded.has(n.name) || !!q)
        const pad = 8 + depth * 16
        const selected = !addingNode && selectedNode === n.name
        const rowHtml = `<div class="bt-row${selected ? ' on' : ''}${n.enabled === false ? ' dim' : ''}${n.lit ? ' lit' : ''}" draggable="true" data-bt-node="${esc(n.name)}" data-bt-folder="${isFolder ? '1' : '0'}" style="padding-left:${pad}px">
            <button type="button" class="bt-tw" data-bt-toggle="${esc(n.name)}" aria-label="${isOpen ? tt('折叠', 'Collapse') : tt('展开', 'Expand')}">${isFolder ? icon(isOpen ? 'down' : 'right', 11) : ''}</button>
            <button type="button" class="bt-pick" data-bt-sel="${esc(n.name)}">
                <span class="bt-ord">${idx + 1}</span>
                ${icon(isFolder ? 'folder' : 'file', 14)}
                <span class="bt-name">${esc(nodeLabel(n))}</span>
                ${n.lit ? '<i class="bt-dot" title="Active"></i>' : ''}
                ${n.enabled === false ? `<em class="bt-off">${tt('停用', 'off')}</em>` : ''}
            </button>
            <span class="bt-acts">
                ${idx > 0 ? `<button type="button" class="pa" data-bt-up="${esc(n.name)}" data-before="${esc(visible[idx - 1].name)}" data-tip="${tt('上移优先级', 'Move up')}">${icon('up', 12)}</button>` : ''}
                ${idx < visible.length - 1 ? `<button type="button" class="pa" data-bt-down="${esc(n.name)}" data-after="${esc(visible[idx + 1].name)}" data-tip="${tt('下移优先级', 'Move down')}">${icon('down', 12)}</button>` : ''}
            </span>
        </div>`
        return rowHtml + (isOpen && n.children && n.children.length ? renderTreeNodesHtml(n.children, depth + 1, q) : '')
    }).join('')
}

function answerParts(doObj) {
    if (!doObj || typeof doObj !== 'object') return { kind: 'none', arg: '' }
    if ('wake' in doObj) return { kind: 'wake', arg: '' }
    if ('stop' in doObj && 'remind' in doObj) return { kind: 'stop_remind', arg: String(doObj.remind || '') }
    if ('stop' in doObj) return { kind: 'stop', arg: '' }
    if ('remind' in doObj) return { kind: 'remind', arg: String(doObj.remind || '') }
    if ('skill' in doObj) return { kind: 'skill', arg: String(doObj.skill || '') }
    if ('nothing' in doObj) return { kind: 'nothing', arg: '' }
    return { kind: 'none', arg: '' }
}

function buildAnswer(kind, arg) {
    if (kind === 'wake') return { wake: true }
    if (kind === 'stop') return { stop: true }
    if (kind === 'remind') return { remind: arg || 'Reminder' }
    if (kind === 'stop_remind') return { stop: true, remind: arg || 'Stopped' }
    if (kind === 'skill') return { skill: arg || '' }
    if (kind === 'nothing') return { nothing: true }
    return null
}

function inspectorHtml(node, situations) {
    if (addingNode) {
        return `<form class="bt-form" data-bt-create>
            <div class="cu-ins-head"><h3>${tt('新建行为树节点', 'New behavior tree node')}</h3><button type="button" class="b quiet" data-bt-cancel>${tt('取消', 'Cancel')}</button></div>
            <label><span>${tt('名称 (ID)', 'Name (ID)')}</span><input class="field" name="name" required placeholder="low-battery-stop" spellcheck="false"></label>
            <label><span>${tt('说明', 'Label')}</span><input class="field" name="about" placeholder="${tt('电量低时停止任务', 'Stop work on low battery')}"></label>
            <label><span>${tt('所属目录', 'Parent folder')}</span><select class="field" name="under"><option value="">${tt('根目录', 'Root')}</option>${situations.map((s) => `<option value="${esc(s.name)}"${s.name === selectedNode ? ' selected' : ''}>${esc(s.about || s.name)}</option>`).join('')}</select></label>
            <label><span>${tt('条件模板', 'Preset')}</span><select class="field" data-bt-preset>
                <option value="event">${tt('事件触发 (规则文件)', 'Event trigger (rule)')}</option>
                <option value="outcome">${tt('动作结果 (规则文件)', 'Action outcome (rule)')}</option>
                <option value="fact">${tt('持续状态 (目录分组)', 'Situation / fact (folder)')}</option>
            </select></label>
            <label><span>${tt('条件 (When)', 'Condition (When)')}</span><textarea class="field mono" name="when" rows="3" spellcheck="false">{"event": "*", "match": {"addressed": true}}</textarea></label>
            <label><span>${tt('动作 (Do)', 'Action (Do)')}</span><select class="field" name="do_kind">
                <option value="wake">${tt('唤醒 Agent', 'Wake agent')}</option>
                <option value="remind">${tt('提醒用户', 'Remind owner')}</option>
                <option value="skill">${tt('运行技能', 'Run skill')}</option>
                <option value="stop">${tt('停止当前任务', 'Stop task')}</option>
                <option value="nothing">${tt('忽略', 'Do nothing')}</option>
                <option value="none">${tt('仅作为子规则目录', 'Folder only (no action)')}</option>
            </select></label>
            <label data-arg-row hidden><span>${tt('参数', 'Argument')}</span><input class="field" name="do_arg" placeholder=""></label>
            <div class="cu-form-foot"><button type="submit" class="b">${tt('创建节点', 'Create node')}</button></div>
        </form>`
    }
    if (!node) return empty(tt('从左侧目录选择节点，或点击“新建”添加规则', 'Select a node from the tree or click New'), '')
    const e = evidence(node.source === 'builtin' ? 'builtin' : node.source === 'owner' ? 'owner' : node.evidence)
    const ans = answerParts(node.do)
    const builtin = node.source === 'builtin'
    const actLabels = { wake: tt('唤醒 Agent', 'Wake agent'), remind: tt('提醒用户', 'Remind owner'), skill: tt('运行技能', 'Run skill'), stop: tt('停止当前任务', 'Stop task'), stop_remind: tt('停止并提醒', 'Stop & remind'), nothing: tt('忽略', 'Do nothing'), none: tt('仅作为目录', 'Folder only') }
    return `<form class="bt-form" data-bt-edit="${esc(node.name)}">
        <div class="cu-ins-head">
            <div><h3>${esc(nodeLabel(node))}</h3><p class="cu-sub">${esc(node.name)} · ${node.situation ? tt('目录分组', 'Folder / Situation') : tt('规则', 'Rule')}${builtin ? ' · ' + tt('内置规则', 'Built-in') : ''}</p></div>
            <div class="cu-ins-acts">
                ${mark(e.text, e.cls)}
                <span class="fv">${tt(`触发 ${node.uses ?? 0} 次`, `${node.uses ?? 0} triggers`)}</span>
                <button type="button" class="b quiet" data-bt-enable="${esc(node.name)}" data-on="${node.enabled === false ? '1' : '0'}">${node.enabled === false ? tt('启用', 'Enable') : tt('停用', 'Disable')}</button>
                ${builtin ? '' : `<button type="button" class="b quiet danger" data-bt-del="${esc(node.name)}">${tt('删除', 'Delete')}</button>`}
            </div>
        </div>
        ${builtin
            ? `<label><span>${tt('触发条件 (When)', 'Condition (When)')}</span><div class="bt-readonly">${esc(JSON.stringify(node.when, null, 2))}</div></label>
               <label><span>${tt('执行动作 (Do)', 'Action (Do)')}</span><div class="bt-readonly">${esc(actLabels[ans.kind] || ans.kind)}${ans.arg ? ` · ${esc(ans.arg)}` : ''}</div></label>`
            : `<label><span>${tt('说明', 'Label')}</span><input class="field" name="about" value="${esc(nodeLabel(node))}"></label>
               <label><span>${tt('触发条件 (When)', 'Condition (When)')}</span><textarea class="field mono" name="when" rows="4" spellcheck="false">${esc(JSON.stringify(node.when, null, 2))}</textarea></label>
               <label><span>${tt('执行动作 (Do)', 'Action (Do)')}</span><select class="field" name="do_kind">
                <option value="wake"${ans.kind === 'wake' ? ' selected' : ''}>${tt('唤醒 Agent', 'Wake agent')}</option>
                <option value="remind"${ans.kind === 'remind' ? ' selected' : ''}>${tt('提醒用户', 'Remind owner')}</option>
                <option value="skill"${ans.kind === 'skill' ? ' selected' : ''}>${tt('运行技能', 'Run skill')}</option>
                <option value="stop"${ans.kind === 'stop' ? ' selected' : ''}>${tt('停止当前任务', 'Stop task')}</option>
                <option value="stop_remind"${ans.kind === 'stop_remind' ? ' selected' : ''}>${tt('停止并提醒', 'Stop & remind')}</option>
                <option value="nothing"${ans.kind === 'nothing' ? ' selected' : ''}>${tt('忽略', 'Do nothing')}</option>
                <option value="none"${ans.kind === 'none' ? ' selected' : ''}>${tt('仅作为目录', 'Folder only')}</option>
               </select></label>
               <label data-arg-row${['remind', 'stop_remind', 'skill'].includes(ans.kind) ? '' : ' hidden'}><span>${tt('参数', 'Argument')}</span><input class="field" name="do_arg" value="${esc(ans.arg)}"></label>
               <div class="cu-form-foot"><button type="submit" class="b">${tt('保存修改', 'Save changes')}</button></div>`}
    </form>`
}

async function renderTree(app, body) {
    const got = await get('/api/agent/tree', { identity: app.identity.id, all: 1 })
    if (!got) { body.innerHTML = problem(failed.get('/api/agent/tree'), { retry: 'customizations' }); return }
    treeNodes = got.nodes || []
    const flat = flattenNodes(treeNodes)
    const situations = flat.filter((n) => n.situation)
    if (!selectedNode && flat.length) selectedNode = flat[0].name
    if (selectedNode && !findNode(treeNodes, selectedNode)) selectedNode = flat[0] ? flat[0].name : null

    body.innerHTML = `<div class="cu-split">
        <div class="cu-left">
            <div class="cu-bar">
                <input class="field" type="search" data-bt-q value="${esc(treeQuery)}" placeholder="${tt('搜索行为树节点…', 'Search tree…')}">
                <button type="button" class="b" data-bt-new>${icon('plus', 13)}${tt('新建', 'New')}</button>
            </div>
            <div class="bt-explorer" data-bt-root></div>
        </div>
        <div class="cu-right" data-bt-detail></div>
    </div>`

    const exp = body.querySelector('[data-bt-root]')
    const detail = body.querySelector('[data-bt-detail]')

    const drawExplorer = () => {
        const q = treeQuery.trim().toLowerCase()
        exp.innerHTML = treeNodes.length
            ? (renderTreeNodesHtml(treeNodes, 0, q) || empty(tt('没有匹配的节点', 'No matching nodes'), ''))
            : empty(tt('行为树为空', 'No nodes'))
    }

    const drawInspector = () => {
        const cur = selectedNode ? findNode(treeNodes, selectedNode) : null
        detail.innerHTML = inspectorHtml(cur, situations)
        const doSel = detail.querySelector('select[name="do_kind"]'), argRow = detail.querySelector('[data-arg-row]')
        if (doSel && argRow) doSel.onchange = () => { argRow.hidden = !['remind', 'stop_remind', 'skill'].includes(doSel.value) }
        const preset = detail.querySelector('[data-bt-preset]'), whenTa = detail.querySelector('textarea[name="when"]')
        if (preset && whenTa) preset.onchange = () => {
            const map = {
                event: '{"event": "*", "match": {"addressed": true}}',
                outcome: '{"outcome": ["failed", "unknown"]}',
                fact: '{"fact": "battery", "below": 20}',
            }
            whenTa.value = map[preset.value] || map.event
            if (preset.value === 'fact' && doSel) doSel.value = 'none'
        }
        const createForm = detail.querySelector('[data-bt-create]')
        if (createForm) createForm.onsubmit = async (e) => {
            e.preventDefault()
            const fd = new FormData(createForm)
            let whenObj
            try { whenObj = JSON.parse(String(fd.get('when') || '{}')) } catch { return toast(tt('条件 JSON 格式有误', 'Invalid JSON condition'), { error: true }) }
            const under = String(fd.get('under') || '') || null
            const r = await post('/api/agent/tree', {
                identity: app.identity.id, action: 'add', all: true,
                name: String(fd.get('name') || '').trim(), about: String(fd.get('about') || '').trim(),
                under, when: whenObj, do: buildAnswer(String(fd.get('do_kind') || 'wake'), String(fd.get('do_arg') || '').trim()),
            })
            if (!r.ok) return said(r)
            addingNode = false; selectedNode = String(fd.get('name') || '').trim()
            if (under) treeExpanded.add(under)
            toast(tt('已添加节点', 'Node created'))
            renderTree(app, body)
        }
        const editForm = detail.querySelector('[data-bt-edit]')
        if (editForm) editForm.onsubmit = async (e) => {
            e.preventDefault()
            const name = editForm.dataset.btEdit
            const node = findNode(treeNodes, name)
            const fd = new FormData(editForm)
            const payload = { identity: app.identity.id, action: 'edit', all: true, name, about: String(fd.get('about') || '').trim() }
            if (node && node.source !== 'builtin') {
                try { payload.when = JSON.parse(String(fd.get('when') || '{}')) } catch { return toast(tt('条件 JSON 格式有误', 'Invalid JSON condition'), { error: true }) }
                payload.do = buildAnswer(String(fd.get('do_kind') || 'none'), String(fd.get('do_arg') || '').trim())
            }
            const r = await post('/api/agent/tree', payload)
            if (!r.ok) return said(r)
            toast(tt('已保存', 'Saved'))
            renderTree(app, body)
        }
    }

    const qIn = body.querySelector('[data-bt-q]')
    if (qIn) qIn.oninput = () => { treeQuery = qIn.value; drawExplorer() }

    if (exp) {
        exp.ondragstart = (e) => { const r = e.target.closest('[data-bt-node]'); if (r) { dragNode = r.dataset.btNode; e.dataTransfer.effectAllowed = 'move' } }
        exp.ondragover = (e) => { const r = e.target.closest('[data-bt-node]'); if (r && dragNode && r.dataset.btNode !== dragNode) { e.preventDefault(); $$('.bt-row.over', exp).forEach((x) => x.classList.remove('over')); r.classList.add('over') } }
        exp.ondragleave = (e) => { const r = e.target.closest('[data-bt-node]'); if (r) r.classList.remove('over') }
        exp.ondrop = async (e) => {
            e.preventDefault()
            $$('.bt-row.over', exp).forEach((x) => x.classList.remove('over'))
            const target = e.target.closest('[data-bt-node]')
            if (!target || !dragNode || target.dataset.btNode === dragNode) { dragNode = null; return }
            const targetName = target.dataset.btNode, moving = dragNode; dragNode = null
            const isFolder = target.dataset.btFolder === '1'
            const sib = siblingsOf(treeNodes, targetName)
            const bodyReq = isFolder
                ? { identity: app.identity.id, action: 'move', all: true, name: moving, under: targetName }
                : { identity: app.identity.id, action: 'move', all: true, name: moving, under: sib.parent, before: targetName }
            const r = await post('/api/agent/tree', bodyReq)
            if (!r.ok) return said(r)
            if (isFolder) treeExpanded.add(targetName)
            renderTree(app, body)
        }
    }

    body.onclick = async (e) => {
        if (e.target.closest('[data-bt-new]')) { addingNode = true; drawExplorer(); drawInspector(); return }
        if (e.target.closest('[data-bt-cancel]')) { addingNode = false; drawExplorer(); drawInspector(); return }
        const tog = e.target.closest('[data-bt-toggle]')
        if (tog) {
            const name = tog.dataset.btToggle
            if (treeExpanded.has(name)) treeExpanded.delete(name); else treeExpanded.add(name)
            drawExplorer(); return
        }
        const sel = e.target.closest('[data-bt-sel]')
        if (sel) { addingNode = false; selectedNode = sel.dataset.btSel; drawExplorer(); drawInspector(); return }
        const up = e.target.closest('[data-bt-up]')
        if (up) {
            const name = up.dataset.btUp, sib = siblingsOf(treeNodes, name)
            const r = await post('/api/agent/tree', { identity: app.identity.id, action: 'move', all: true, name, under: sib.parent, before: up.dataset.before })
            if (!r.ok) return said(r)
            renderTree(app, body); return
        }
        const down = e.target.closest('[data-bt-down]')
        if (down) {
            const name = down.dataset.btDown, sib = siblingsOf(treeNodes, name)
            const idx = sib.list.findIndex((x) => x.name === down.dataset.after)
            const afterNext = sib.list[idx + 1] ? sib.list[idx + 1].name : null
            const r = await post('/api/agent/tree', { identity: app.identity.id, action: 'move', all: true, name, under: sib.parent, before: afterNext })
            if (!r.ok) return said(r)
            renderTree(app, body); return
        }
        const en = e.target.closest('[data-bt-enable]')
        if (en) {
            const r = await post('/api/agent/tree', { identity: app.identity.id, action: en.dataset.on === '1' ? 'enable' : 'disable', all: true, name: en.dataset.btEnable })
            if (!r.ok) return said(r)
            renderTree(app, body); return
        }
        const del = e.target.closest('[data-bt-del]')
        if (del) {
            const name = del.dataset.btDel
            if (!(await confirm({ title: tt(`删除节点 ${name}？`, `Delete node ${name}?`), text: tt('该节点及其子节点将被移除。', 'This node and any child nodes will be removed.'), yes: tt('删除', 'Delete'), danger: true }))) return
            const r = await post('/api/agent/tree', { identity: app.identity.id, action: 'remove', all: true, name })
            if (!r.ok) return said(r)
            selectedNode = null; toast(tt('已删除', 'Deleted')); renderTree(app, body)
        }
    }
    drawExplorer()
    drawInspector()
}

// ── 5. MCP & Connectors (real settings context) ──
async function renderConnectors(app, body) {
    const ctx = await makeSubCtx(app)
    body.innerHTML = `<div class="cu-page">${await connectors.draw(ctx)}</div>`
    wireSettings(body, (name, v) => ctx.save(name, v), (name, told) => rulesDialog(ctx, name, told))
}

// ── 6. Packages (real settings context) ──
async function renderPackages(app, body) {
    const ctx = await makeSubCtx(app)
    body.innerHTML = `<div class="cu-page">${await packages.draw(ctx)}</div>`
    wireSettings(body, (name, v) => ctx.save(name, v), (name, told) => rulesDialog(ctx, name, told))
    if (packages.wire && !body.querySelector('.st-problem')) packages.wire(ctx, body)
}
