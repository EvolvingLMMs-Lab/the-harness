// The composer, after Hermes Desktop's "Chat" and "Choosing a model":
//   - Enter sends, Shift+Enter is a new line, and an input method that is composing keeps its
//     Enter; while it works, what is sent joins the queue;
//   - the queue sits above the composer: each waiting message can be edited, deleted or sent
//     now. It is the host's (GET/POST /api/agent/queue), so it survives a restart and every
//     window on the chat shows the same list. Stop (or Esc) with messages waiting holds the
//     queue and opens it; Resume lets it go on;
//   - an unsent draft is kept per chat (this window's storage, prefs.js);
//   - Up and Down in an empty composer recall the messages sent in this chat;
//   - files dropped anywhere on the chat, pasted images and the + button become attachments
//     of the next message;
//   - the model picker beside the input changes the model of this chat only; signed-in agents,
//     keys and local models are one list. Settings › Model changes the default.
import { esc, tt, modelName } from './i18n.js'
import { get, post, failed, agent } from './api.js'
import { $, ic, toast, said, menu, confirm, dialog, closeDialog } from './ui.js'
import { icon } from './icons.js'
import { renderAttachments } from './attachments.js'
import { perChat } from './prefs.js'
import { label } from './keys.js'
import * as models from './models.js'
import * as onboarding from './onboarding.js'

const drafts = perChat('draft')
const state = new Map() // "identity/chat" -> {files: [attachment], editing: queued id | null}
const key = (app) => `${app.identity.id}/${app.chat}`
const of = (app) => { if (!state.has(key(app))) state.set(key(app), { files: [], editing: null }); return state.get(key(app)) }

let shown = null // the chat whose draft the textarea holds
let queueOpen = true // the list of waiting messages is shown, not only its heading
let recall = null // browsing sent messages: {at, kept (what was in the composer before)}
let saving = null
let sources = { status: null, models: [], found: null, read: false } // what the model picker lists

export function frameHtml() {
    return `<div class="pg-queue" hidden></div><div class="pg-notice" hidden></div>
    <form class="pg-compose"><div class="pg-atts" hidden></div><div class="pg-ac" hidden role="listbox"></div><textarea rows="1" placeholder="${tt('输入消息，@ 引用上下文，/ 调起命令…', 'Ask anything, @ to mention, / for actions…')}" aria-label="${tt('消息', 'Message')}"></textarea>
      <div class="pg-tools">${ic('plus', tt('添加文件', 'Attach files'), { act: 'attach' })}<input type="file" multiple hidden tabindex="-1" aria-hidden="true">`
        + `<button type="button" class="pick model" data-act="model-pick" data-tip="${tt('模型', 'Model')}"></button><button type="button" class="pick effort" data-act="effort-pick" data-tip="${tt('思考强度', 'Reasoning effort')}" hidden></button>`
        + `<span class="grow"></span>`
        + `<button type="button" class="pick mode" data-act="mode-pick" data-tip="${tt('权限模式', 'Permission mode')}"></button>`
        + `<button type="button" class="stop" data-act="turn-stop" aria-label="${tt('停止', 'Stop')}" data-tip="${tt('停止', 'Stop')}" data-keys="Esc" hidden>${icon('stop')}</button>`
        + `<button type="submit" class="send" aria-label="${tt('发送', 'Send')}" data-tip="${tt('发送', 'Send')}" data-keys="${label('enter')}">${icon('send')}</button></div></form>`
}

const area = () => $('.pg-compose textarea')
function grow() { const a = area(); a.style.height = 'auto'; a.style.height = Math.min(180, a.scrollHeight) + 'px' }
export function focus() { const a = area(); if (a && !a.disabled) a.focus() }
export function insertText(text) {
    const a = area(); if (!a || a.disabled) return
    const start = a.selectionStart ?? a.value.length, end = a.selectionEnd ?? a.value.length
    const before = a.value.slice(0, start), after = a.value.slice(end)
    const pad = before && !/\s$/.test(before) ? ' ' : ''
    a.value = before + pad + text + after
    const pos = before.length + pad.length + text.length
    grow(); a.focus(); a.setSelectionRange(pos, pos)
}
function setText(text) { const a = area(); a.value = text; grow(); a.setSelectionRange(text.length, text.length) }

export function loadText(text) { setText(String(text || '')); focus() }

// ── @ context mention picker (Antigravity-style Browse / Plugins & Skills) and / slash commands ──
let ac = { open: false, kind: null, items: [], index: -1, start: 0, end: 0, timer: null, seq: 0 }
const selectable = (it) => !!(it && !it.head && !it.hint)
function firstSelectable(items, preferNonBack = false) {
    if (preferNonBack) {
        const idx = items.findIndex((it) => selectable(it) && !it.back)
        if (idx >= 0) return idx
    }
    return items.findIndex((it) => selectable(it))
}
function moveAc(app, step) {
    const n = ac.items.length
    if (!n) return
    let idx = ac.index
    for (let tried = 0; tried < n; tried++) {
        idx = idx < 0 ? (step > 0 ? 0 : n - 1) : (idx + step + n) % n
        if (selectable(ac.items[idx])) {
            ac.index = idx
            drawAc(app)
            const active = $('.pg-ac .ac-item.on')
            if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' })
            return
        }
    }
}

function mentionCategories() {
    return [
        { scope: 'rule', icon: 'log', label: tt('规则', 'Rules'), sub: tt('浏览全局、项目与人设规则', 'Browse rules'), drill: '@rule:', keys: 'rule rules 规则 agents claude persona' },
        { scope: 'chat', icon: 'chat', label: tt('对话', 'Conversation'), sub: tt('搜索并引用历史对话', 'Search conversations'), drill: '@chat:', keys: 'chat conversation 对话 会话' },
        { scope: 'memory', icon: 'context', label: tt('记忆', 'Memory'), sub: tt('浏览长期记忆与偏好', 'Browse memory'), drill: '@memory:', keys: 'memory mem 记忆 偏好' },
        { scope: 'artifact', icon: 'plan', label: tt('方案与文档', 'Artifacts'), sub: tt('浏览当前对话的方案文档', 'Browse artifacts'), drill: '@artifact:', keys: 'artifact artifacts plan 文档 方案' },
        { scope: 'file', icon: 'folder', label: tt('文件', 'Files'), sub: tt('浏览当前工作区项目文件', 'Browse project files'), drill: '@file:', keys: 'file files folder 文件 代码 目录' },
    ]
}

function browseMenuItems(app) {
    const items = [
        { head: tt('浏览', 'Browse') },
        ...mentionCategories(),
    ]
    const skills = (app.skills || []).filter((s) => !s.archived)
    const places = (app.life.places || []).filter((p) => p.kind === 'browser' || p.kind === 'desktop')
    items.push({ head: tt('插件与技能', 'Plugins & Skills') })
    for (const s of skills.slice(0, 6)) {
        items.push({
            icon: 'plugins',
            label: s.name,
            sub: s.description || tt('技能', 'Skill'),
            insert: `@skill:${s.name} `,
            mono: true,
        })
    }
    if (skills.length > 6) {
        items.push({
            icon: 'plugins',
            label: tt('全部技能', 'All Skills'),
            sub: tt(`搜索全部 ${skills.length} 个技能`, `Search all ${skills.length} skills`),
            drill: '@skill:',
        })
    }
    for (const p of places) {
        items.push({
            icon: p.kind === 'browser' ? 'browser' : 'terminal',
            label: p.title || p.id,
            sub: p.online === false ? tt('未连接环境', 'Offline place') : tt('已连接环境', 'Connected place'),
            insert: `@${p.id} `,
        })
    }
    items.push({
        icon: 'sliders',
        label: tt('自定义与插件', 'Customizations'),
        sub: tt('在自定义中心管理技能、规则、行为树与 MCP', 'Manage skills, rules, and MCP in Customizations'),
        run: () => app.openCustomizations && app.openCustomizations(),
    })
    return items
}

const SCOPE_LABELS = {
    rule: () => tt('规则', 'Rules'),
    chat: () => tt('对话', 'Conversations'),
    memory: () => tt('记忆', 'Memory'),
    artifact: () => tt('方案与文档', 'Artifacts'),
    file: () => tt('项目文件', 'Project Files'),
    skill: () => tt('技能', 'Skills'),
}

const RULE_SCOPE_LABELS = {
    global: () => tt('全局规则', 'Global rule'),
    project: () => tt('项目规则', 'Project rule'),
    persona: () => tt('人设规则', 'Persona'),
}

function memorySnippet(text) {
    if (!text) return ''
    let body = String(text)
    if (body.startsWith('---\n')) {
        const end = body.indexOf('\n---\n', 4)
        if (end !== -1) body = body.slice(end + 5)
    }
    const line = body.split(/\r?\n/).map((s) => s.trim()).find(Boolean) || ''
    return line.slice(0, 72)
}

function slashCommands(app) {
    const base = [
        { id: '/continue', label: '/continue', sub: tt('继续未完成的任务（断点续跑）', 'Continue interrupted task'), icon: 'play', run: () => send(app, tt('继续', 'Continue')) },
        { id: '/plan', label: '/plan', sub: tt('计划模式（只读规划）', 'Plan mode (read-only)'), icon: 'plan', run: () => setMode(app, 'plan') },
        { id: '/ask', label: '/ask', sub: tt('询问模式（操作前确认）', 'Ask mode (approve actions)'), icon: 'shield', run: () => setMode(app, 'ask') },
        { id: '/auto', label: '/auto', sub: tt('自动模式（工作区自动执行）', 'Auto mode (workspace auto)'), icon: 'shield', run: () => setMode(app, 'auto') },
        { id: '/full', label: '/full', sub: tt('完整权限（免审批直接执行）', 'Full Access (no prompts)'), icon: 'bolt', run: () => setMode(app, 'full') },
        { id: '/compact', label: '/compact', sub: tt('压缩上下文', 'Compact context'), icon: 'context', run: async () => { const r = await post('/api/agent/compact', { identity: app.identity.id, chat: app.chat }); if (!r.ok) return said(r); toast(tt('已压缩上下文', 'Context compacted')); app.kick() } },
        { id: '/new', label: '/new', sub: tt('开始新对话', 'New conversation'), icon: 'edit', run: () => app.newChat && app.newChat() },
        { id: '/clear', label: '/clear', sub: tt('开始新对话', 'New conversation'), icon: 'edit', run: () => app.newChat && app.newChat() },
        { id: '/stop', label: '/stop', sub: tt('停止当前回合', 'Stop current turn'), icon: 'stop', run: () => stop(app) },
        { id: '/model', label: '/model', sub: tt('切换模型', 'Switch model'), icon: 'model', run: () => pickModel(app) },
        { id: '/project', label: '/project', sub: tt('切换或打开项目', 'Switch or open project'), icon: 'folder', run: () => pickWhere(app) },
        { id: '/memory', label: '/memory', sub: tt('查看和编辑长期记忆', 'View and edit memory'), icon: 'context', run: () => app.openCustomizations && app.openCustomizations('memory') },
        { id: '/customizations', label: '/customizations', sub: tt('打开自定义中心', 'Open Customizations'), icon: 'sliders', run: () => app.openCustomizations && app.openCustomizations() },
    ]
    const skills = (app.skills || []).map((s) => ({
        id: `/${s.name}`, label: `/${s.name}`, sub: s.description || tt('技能', 'Skill'), icon: 'command',
        insert: `/${s.name} `,
    }))
    return [...base, ...skills]
}

async function setMode(app, id) {
    const row = chatRow(app), prev = row.mode
    if (row && row.chat === app.chat) { row.mode = id; draw(app) }
    const r = await agent.chatsAct(app.identity.id, 'mode', app.chat, { mode: id })
    if (!r.ok) {
        if (row && row.chat === app.chat) { row.mode = prev; draw(app) }
        return said(r)
    }
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app)
    const names = { plan: tt('计划模式', 'Plan mode'), ask: tt('询问模式', 'Ask mode'), auto: tt('自动模式', 'Auto mode'), full: tt('完整权限模式', 'Full Access mode') }
    toast(names[id] || id)
}

export function closeAc() {
    ac.open = false; ac.items = []; ac.index = -1; ac.seq++
    clearTimeout(ac.timer)
    const box = $('.pg-ac')
    if (box) { box.hidden = true; box.innerHTML = '' }
}

function drawAc(app) {
    const box = $('.pg-ac')
    if (!box) return
    if (!ac.open || !ac.items.length) { box.hidden = true; box.innerHTML = ''; return }
    box.hidden = false
    box.innerHTML = ac.items.map((it, i) => {
        if (it.head) return `<div class="ac-head" role="presentation">${esc(it.head)}</div>`
        const active = !it.hint && i === ac.index
        const cls = `ac-item${it.back ? ' ac-back' : ''}${it.mono ? ' mono' : ''}${it.hint ? ' hint' : (active ? ' on' : '')}`
        const chev = it.drill && !it.back ? `<span class="ac-chev">${icon('right', 12)}</span>` : ''
        return `<button type="button" class="${cls}" role="option" aria-selected="${active}" data-ac-i="${i}"${it.hint ? ' disabled' : ''}>`
            + `${icon(it.icon || 'file', 14)}<b>${esc(it.label)}</b>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}${chev}</button>`
    }).join('')
    box.onmousedown = (e) => {
        const b = e.target.closest('[data-ac-i]')
        if (!b || b.disabled) return
        e.preventDefault()
        applyAc(app, +b.dataset.acI)
    }
}

function applyAc(app, idx) {
    const item = ac.items[idx]
    if (!selectable(item)) return
    const a = area()
    if (item.drill) {
        const val = a.value
        const rep = item.drill
        a.value = val.slice(0, ac.start) + rep + val.slice(ac.end)
        const pos = ac.start + rep.length
        grow(); a.focus(); a.setSelectionRange(pos, pos)
        updateAc(app)
        return
    }
    const start = ac.start, end = ac.end, kind = ac.kind
    closeAc()
    if (item.run) {
        if (kind === 'slash') {
            a.value = ''; grow(); drafts.set(app, '')
        } else {
            const val = a.value
            a.value = (val.slice(0, start) + val.slice(end)).replace(/\s{2,}/g, ' ')
            grow(); drafts.set(app, a.value)
        }
        item.run()
        return
    }
    const val = a.value
    const rep = item.insert || `${item.label} `
    a.value = val.slice(0, start) + rep + val.slice(end)
    const pos = start + rep.length
    drafts.set(app, a.value)
    grow(); a.focus(); a.setSelectionRange(pos, pos)
}

async function loadScopedMention(app, scope, q, mySeq) {
    const ql = q.toLowerCase()
    const backRow = {
        back: true,
        icon: 'arrowLeft',
        label: tt('返回', 'Back'),
        sub: SCOPE_LABELS[scope] ? SCOPE_LABELS[scope]() : scope,
        drill: '@',
    }
    let rows = []
    if (scope === 'rule') {
        const got = await get('/api/app/rules', { identity: app.identity.id, chat: app.chat })
        if (mySeq !== ac.seq) return
        const files = ((got && got.files) || [])
            .filter((f) => f.scope !== 'memory' && f.name !== 'MEMORY.md')
            .filter((f) => !ql || `${f.scope} ${f.name} ${f.title || ''}`.toLowerCase().includes(ql))
            .sort((a, b) => Number(!!b.exists) - Number(!!a.exists))
        rows = files.map((f) => ({
            icon: 'log',
            label: f.name,
            sub: `${RULE_SCOPE_LABELS[f.scope] ? RULE_SCOPE_LABELS[f.scope]() : f.scope}${f.exists ? '' : tt(' · 未创建', ' · not created')}`,
            insert: `@rule:${f.scope}/${f.name} `,
            mono: true,
        }))
        if (!rows.length) rows = [{ icon: 'log', label: tt('没有匹配的规则文件', 'No matching rule files'), sub: q || tt('可在自定义中创建规则', 'Create rules in Customizations'), hint: true }]
    } else if (scope === 'memory') {
        const got = await get('/api/app/rules', { identity: app.identity.id, chat: app.chat })
        if (mySeq !== ac.seq) return
        const files = ((got && got.files) || [])
            .filter((f) => f.scope === 'memory' || (f.scope === 'persona' && f.name === 'MEMORY.md'))
            .filter((f) => f.exists)
            .filter((f) => !ql || `${f.title || ''} ${f.name} ${f.text || ''}`.toLowerCase().includes(ql))
        rows = files.slice(0, 14).map((f) => ({
            icon: 'context',
            label: f.name === 'MEMORY.md' ? tt('记忆总览 (MEMORY.md)', 'Memory Index (MEMORY.md)') : (f.title || f.name),
            sub: memorySnippet(f.text) || f.name,
            insert: `@memory:${f.name} `,
        }))
        if (!rows.length) rows = [{ icon: 'context', label: tt('暂无匹配的记忆条目', 'No matching memory entries'), sub: q || tt('对话中记住的偏好与事实会显示在这里', 'Saved preferences and facts appear here'), hint: true }]
    } else if (scope === 'chat') {
        let list = Array.isArray(app.chats) ? app.chats.slice() : []
        if (ql) {
            const found = await agent.chats(app.identity.id, { q })
            if (mySeq !== ac.seq) return
            if (found && Array.isArray(found.chats)) list = found.chats
        }
        const filtered = list
            .filter((c) => !c.archived)
            .filter((c) => !ql || `${c.title || ''} ${c.chat}`.toLowerCase().includes(ql))
            .sort((a, b) => Number(a.chat === app.chat) - Number(b.chat === app.chat))
        rows = filtered.slice(0, 12).map((c) => ({
            icon: 'chat',
            label: c.title || c.chat,
            sub: c.chat === app.chat ? tt('当前对话', 'Current conversation') : (c.kind === 'main' ? tt('主对话', 'Main conversation') : c.chat),
            insert: `@chat:${c.chat} `,
        }))
        if (!rows.length) rows = [{ icon: 'chat', label: tt('没有匹配的对话', 'No matching conversations'), sub: q, hint: true }]
    } else if (scope === 'artifact') {
        const arts = await get('/api/app/artifacts', { identity: app.identity.id, chat: app.chat })
        if (mySeq !== ac.seq) return
        const list = ((arts && arts.artifacts) || [])
            .filter((x) => !ql || `${x.name} ${x.title || ''}`.toLowerCase().includes(ql))
        rows = list.slice(0, 12).map((x) => ({
            icon: 'plan',
            label: x.title || x.name,
            sub: x.name,
            insert: `@artifact:${x.name} `,
        }))
        if (!rows.length) rows = [{ icon: 'plan', label: tt('当前对话暂无方案文档', 'No artifacts in this chat'), sub: q || tt('在计划模式或方案输出后会自动生成', 'Generated plans and specs appear here'), hint: true }]
    } else if (scope === 'file') {
        const got = await get('/api/app/place_search', { identity: app.identity.id, chat: app.chat, q })
        if (mySeq !== ac.seq) return
        rows = ((got && got.matches) || []).slice(0, 14).map((m) => ({
            icon: m.dir ? 'folder' : 'file',
            label: m.path,
            sub: m.dir ? tt('文件夹', 'Folder') : (got.folder || ''),
            insert: `@file:${m.path} `,
            mono: true,
        }))
        if (!rows.length) {
            rows = [{
                icon: 'folder',
                label: got && got.folder ? tt('没有匹配的项目文件', 'No matching files') : tt('当前对话未绑定项目', 'No project folder bound'),
                sub: got && got.folder ? q : tt('输入 /project 绑定项目后可浏览文件', 'Run /project to bind a folder'),
                hint: true,
            }]
        }
    } else if (scope === 'skill') {
        const skills = (app.skills || [])
            .filter((s) => !s.archived)
            .filter((s) => !ql || `${s.name} ${s.description || ''}`.toLowerCase().includes(ql))
        rows = skills.slice(0, 14).map((s) => ({
            icon: 'plugins',
            label: s.name,
            sub: s.description || tt('技能', 'Skill'),
            insert: `@skill:${s.name} `,
            mono: true,
        }))
        if (!rows.length) rows = [{ icon: 'plugins', label: tt('没有匹配的技能', 'No matching skills'), sub: q || tt('可在自定义中心安装或管理技能', 'Manage skills in Customizations'), hint: true }]
    }
    ac.items = [backRow, ...rows]
    ac.index = firstSelectable(ac.items, true)
    ac.open = true
    drawAc(app)
}

async function loadGlobalMentionSearch(app, q, mySeq) {
    const ql = q.toLowerCase()
    const [rulesRes, artsRes, filesRes] = await Promise.all([
        get('/api/app/rules', { identity: app.identity.id, chat: app.chat }),
        get('/api/app/artifacts', { identity: app.identity.id, chat: app.chat }),
        get('/api/app/place_search', { identity: app.identity.id, chat: app.chat, q }),
    ])
    if (mySeq !== ac.seq) return
    const items = []
    const cats = mentionCategories().filter((c) => `${c.label} ${c.sub} ${c.keys}`.toLowerCase().includes(ql))
    if (cats.length) items.push({ head: tt('浏览', 'Browse') }, ...cats)

    const chats = (app.chats || [])
        .filter((c) => !c.archived && `${c.title || ''} ${c.chat}`.toLowerCase().includes(ql))
        .slice(0, 3)
        .map((c) => ({ icon: 'chat', label: c.title || c.chat, sub: c.chat, insert: `@chat:${c.chat} ` }))
    if (chats.length) items.push({ head: tt('对话', 'Conversations') }, ...chats)

    const allRuleFiles = (rulesRes && rulesRes.files) || []
    const rules = allRuleFiles
        .filter((f) => f.scope !== 'memory' && f.name !== 'MEMORY.md' && f.exists && `${f.scope} ${f.name}`.toLowerCase().includes(ql))
        .slice(0, 3)
        .map((f) => ({ icon: 'log', label: f.name, sub: RULE_SCOPE_LABELS[f.scope] ? RULE_SCOPE_LABELS[f.scope]() : f.scope, insert: `@rule:${f.scope}/${f.name} `, mono: true }))
    if (rules.length) items.push({ head: tt('规则', 'Rules') }, ...rules)

    const mems = allRuleFiles
        .filter((f) => (f.scope === 'memory' || (f.scope === 'persona' && f.name === 'MEMORY.md')) && f.exists && `${f.title || ''} ${f.name} ${f.text || ''}`.toLowerCase().includes(ql))
        .slice(0, 3)
        .map((f) => ({ icon: 'context', label: f.title || f.name, sub: memorySnippet(f.text) || f.name, insert: `@memory:${f.name} ` }))
    if (mems.length) items.push({ head: tt('记忆', 'Memory') }, ...mems)

    const arts = ((artsRes && artsRes.artifacts) || [])
        .filter((x) => `${x.name} ${x.title || ''}`.toLowerCase().includes(ql))
        .slice(0, 3)
        .map((x) => ({ icon: 'plan', label: x.title || x.name, sub: x.name, insert: `@artifact:${x.name} ` }))
    if (arts.length) items.push({ head: tt('方案与文档', 'Artifacts') }, ...arts)

    const skills = (app.skills || [])
        .filter((s) => !s.archived && `${s.name} ${s.description || ''}`.toLowerCase().includes(ql))
        .slice(0, 3)
        .map((s) => ({ icon: 'plugins', label: s.name, sub: s.description || tt('技能', 'Skill'), insert: `@skill:${s.name} `, mono: true }))
    if (skills.length) items.push({ head: tt('插件与技能', 'Plugins & Skills') }, ...skills)

    const files = ((filesRes && filesRes.matches) || [])
        .slice(0, 5)
        .map((m) => ({ icon: m.dir ? 'folder' : 'file', label: m.path, sub: m.dir ? tt('文件夹', 'Folder') : (filesRes.folder || ''), insert: `@file:${m.path} `, mono: true }))
    if (files.length) items.push({ head: tt('项目文件', 'Project Files') }, ...files)

    if (!items.length) {
        items.push({ icon: 'search', label: tt('没有匹配的上下文', 'No matching context'), sub: q, hint: true })
    }
    ac.items = items
    ac.index = firstSelectable(items)
    ac.open = true
    drawAc(app)
}

function updateAc(app) {
    const a = area()
    if (!a || a.disabled) return closeAc()
    const pos = a.selectionStart ?? a.value.length
    const before = a.value.slice(0, pos)
    // Slash commands: single-token /cmd at start of composer
    const sm = before.match(/^\/([^\s]*)$/)
    if (sm && !a.value.slice(pos).trim()) {
        const q = sm[1].toLowerCase()
        ac.seq++
        clearTimeout(ac.timer)
        ac.kind = 'slash'; ac.start = 0; ac.end = pos
        ac.items = slashCommands(app)
            .filter((c) => c.label.toLowerCase().includes(q) || (c.sub || '').toLowerCase().includes(q))
            .slice(0, 12)
            .map((c) => ({ ...c, mono: true }))
        ac.index = firstSelectable(ac.items)
        ac.open = ac.items.length > 0
        drawAc(app)
        return
    }
    // @ structured context mention picker (Antigravity-style; supports both space and CJK/punctuation boundaries)
    const am = before.match(/(?:^|[^A-Za-z0-9._%+-])@([^\s@]*)$/)
    if (am) {
        const raw = am[1]
        ac.kind = 'mention'; ac.start = pos - raw.length - 1; ac.end = pos
        clearTimeout(ac.timer)
        const mySeq = ++ac.seq
        // Level 0: bare `@` opens structured Browse + Plugins/Skills menu immediately (no raw file dump)
        if (!raw) {
            ac.items = browseMenuItems(app)
            ac.index = firstSelectable(ac.items)
            ac.open = true
            drawAc(app)
            return
        }
        // Level 1: scoped drill-down `@rule:`, `@chat:`, `@memory:`, `@artifact:`, `@file:`, `@skill:`
        const scoped = raw.match(/^(rule|chat|memory|artifact|file|skill):(.*)$/i)
        if (scoped) {
            const scope = scoped[1].toLowerCase(), q = scoped[2]
            ac.timer = setTimeout(() => loadScopedMention(app, scope, q, mySeq), 45)
            return
        }
        // Level 1b: unscoped `@<query>` cross-category grouped search
        ac.timer = setTimeout(() => loadGlobalMentionSearch(app, raw, mySeq), 70)
        return
    }
    closeAc()
}

export function mount(app) {
    const a = area(), form = $('.pg-compose')
    a.addEventListener('input', () => {
        grow(); recall = null
        clearTimeout(saving)
        const mine = key(app)
        saving = setTimeout(() => { if (key(app) === mine) drafts.set(app, a.value) }, 250)
        updateAc(app)
    })
    a.addEventListener('compositionend', () => updateAc(app))
    a.addEventListener('click', () => updateAc(app))
    a.addEventListener('keydown', (e) => {
        if (e.isComposing || e.keyCode === 229) return // the input method's own Enter and arrows
        if (ac.open && ac.items.length) {
            if (e.key === 'ArrowDown') { e.preventDefault(); moveAc(app, 1); return }
            if (e.key === 'ArrowUp') { e.preventDefault(); moveAc(app, -1); return }
            if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
                if (ac.index >= 0 && selectable(ac.items[ac.index])) {
                    e.preventDefault(); applyAc(app, ac.index); return
                }
                if (e.key === 'Tab') { e.preventDefault(); return }
            }
            if (e.key === 'Escape') { e.preventDefault(); closeAc(); return }
        }
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault()
            const exact = slashCommands(app).find((c) => c.run && c.label === a.value.trim().toLowerCase())
            if (exact) { a.value = ''; grow(); drafts.set(app, ''); exact.run(); return }
            send(app); return
        }
        if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && (recall || !a.value)) {
            if (history(app, e.key === 'ArrowUp' ? -1 : 1)) e.preventDefault()
        }
    })
    a.addEventListener('blur', () => { setTimeout(() => { if (document.activeElement !== a) closeAc() }, 120) })
    a.addEventListener('paste', (e) => {
        const files = [...((e.clipboardData && e.clipboardData.files) || [])]
        if (!files.length) return
        e.preventDefault(); attach(app, files)
    })
    form.addEventListener('submit', (e) => { e.preventDefault(); send(app) })
    const picker = form.querySelector('input[type=file]')
    picker.addEventListener('change', () => { attach(app, [...picker.files]); picker.value = '' })
    // files dropped anywhere on the chat
    const zone = $('.pg-chatarea')
    let depth = 0
    const carries = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files')
    zone.addEventListener('dragenter', (e) => { if (!carries(e)) return; e.preventDefault(); depth++; zone.classList.add('dropping') })
    zone.addEventListener('dragover', (e) => { if (carries(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' } })
    zone.addEventListener('dragleave', (e) => { if (!carries(e)) return; depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('dropping') })
    zone.addEventListener('drop', (e) => {
        if (!carries(e)) return
        e.preventDefault(); depth = 0; zone.classList.remove('dropping')
        attach(app, [...e.dataTransfer.files]); focus()
    })
    // a queued message being edited: Enter saves it
    $('.pg-queue').addEventListener('keydown', (e) => {
        if (e.target.tagName !== 'TEXTAREA' || e.isComposing || e.keyCode === 229) return
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); queueSave(app) }
    })
}

// The chat that is open changed: its own draft and attachments.
export function show(app) {
    const a = area()
    clearTimeout(saving)
    recall = null
    shown = key(app)
    a.value = drafts.get(app, '')
    grow()
    drawFiles(app)
}
// Before leaving a chat: what is typed is its draft.
export function leave(app) { closeAc(); clearTimeout(saving); if (shown === key(app)) drafts.set(app, area().value); shown = null }

// ── sending ──
let sending = false
export async function send(app, given) {
    closeAc()
    const a = area(), mine = of(app), chat = app.chat
    const text = (typeof given === 'string' ? given : a.value).trim()
    const files = mine.files
    if (sending || (!text && !files.length)) return
    if (files.some((f) => f.state === 'failed')) return toast(tt('有附件没传上去：先去掉它或重试，再发送。', 'An attachment was not uploaded: remove it or retry it, then send.'), { error: true })
    if (files.some((f) => f.state === 'uploading')) return toast(tt('附件还在上传，稍等一下。', 'Attachments are still uploading; one moment.'))
    sending = true
    const typed = typeof given !== 'string'
    if (typed) { a.value = ''; grow() }
    // the main conversation says where with each message; a chat opened on a place works there by itself
    const at = whereOf(app)
    const r = await agent.say(app.identity.id, chat, text, { ...(at && at.kind === 'main' && at.place ? { place: at.place } : {}), ...(files.length ? { files: files.map((f) => f.id) } : {}) })
    sending = false
    if (!r.ok) {
        // not sent: the words are back in the composer, to change and send again
        if (typed && app.chat === chat) setText(a.value ? `${text}\n${a.value}` : text)
        return said(r, tt('没发出去', 'Not sent'))
    }
    if (app.chat === chat) { drafts.set(app, ''); recall = null }
    for (const f of files) if (f.previewUrl) URL.revokeObjectURL(f.previewUrl)
    mine.files = []
    drawFiles(app)
    app.kick()
}

// Up and Down in an empty composer: the messages sent in this chat, the newest first.
function history(app, step) {
    const sent = []
    for (const r of app.records[app.chat] || []) if (r.event === 'user' && r.text && sent[sent.length - 1] !== r.text) sent.push(r.text)
    if (!recall) {
        if (step > 0 || !sent.length) return false
        recall = { at: sent.length, kept: area().value }
    }
    const at = recall.at + step
    if (at < 0) return true
    if (at >= sent.length) { const kept = recall.kept; recall = null; setText(kept); return true }
    const kept = recall.kept
    setText(sent[at])
    recall = { at, kept } // setText does not fire input, so the browsing goes on
    return true
}

// ── attachments ──
const size = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`)
function attach(app, files) {
    const mine = of(app)
    for (const file of files) {
        const mime = file.type || 'application/octet-stream'
        const item = { file, name: file.name || tt('粘贴的图片', 'pasted image'), size: file.size, type: mime, mime, state: 'uploading', id: null, url: null,
            previewUrl: mime.startsWith('image/') ? URL.createObjectURL(file) : null }
        mine.files.push(item)
        upload(app, item)
    }
    drawFiles(app)
}
async function upload(app, item) {
    const identity = app.identity.id, chat = app.chat, where = key(app)
    item.state = 'uploading'; item.problem = null
    let data
    try {
        data = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(String(reader.result).split(',')[1] || ''); reader.onerror = () => fail(reader.error); reader.readAsDataURL(item.file) })
    } catch (error) {
        item.state = 'failed'; item.problem = { error: tt('这个文件读不出来。', 'This file could not be read.'), fix: String((error && error.message) || '') }
        if (key(app) === where) drawFiles(app)
        return
    }
    const r = await agent.attach(identity, chat, { name: item.name, type: item.type, data })
    if (r.ok && r.data && r.data.id) {
        item.state = 'done'
        item.id = r.data.id
        item.url = r.data.url || item.url
        item.mime = r.data.mime || item.mime
    } else {
        item.state = 'failed'
        item.problem = r.status === 404
            ? { error: tt('这个后台还不能接收附件。', 'This host cannot receive attachments yet.'), fix: tt('更新 The Harness 后再试；文件没有发出去。', 'Update The Harness and try again; the file was not sent.') }
            : { error: r.error || tt('没传上去', 'The upload failed'), fix: r.fix || '' }
    }
    if (key(app) === where) drawFiles(app)
}
function drawFiles(app) {
    const box = $('.pg-atts'), files = of(app).files
    box.hidden = !files.length
    box.innerHTML = renderAttachments(files, 'composer', { identity: app.identity.id, chat: app.chat })
}
export function attachRemove(app, index) {
    const files = of(app).files, [gone] = files.splice(index, 1)
    if (gone && gone.previewUrl) URL.revokeObjectURL(gone.previewUrl)
    drawFiles(app); focus()
}
export function attachRetry(app, index) { const item = of(app).files[index]; if (!item) return null; const going = upload(app, item); drawFiles(app); return going }
export function attachPick() { $('.pg-compose input[type=file]').click() }

// ── the queue above the composer ──
const queueOf = (app) => app.queue[app.chat] || { held: false, running: null, queued: [] }
function drawQueue(app) {
    const box = $('.pg-queue'), q = queueOf(app), mine = of(app)
    if (mine.editing && !q.queued.some((m) => m.id === mine.editing)) mine.editing = null // it started, or was removed elsewhere
    if (mine.editing && box.querySelector('textarea')) return // being edited: left alone until saved or cancelled
    const n = q.queued.length
    if (!n) { box.hidden = true; box.innerHTML = ''; box._html = ''; return }
    const open = queueOpen || q.held
    const html = `<div class="qh"><button type="button" class="qt" data-act="queue-toggle" aria-expanded="${open}">${icon(open ? 'down' : 'right', 12)}${icon('clock', 14)}<b>${tt(`${n} 条在排队`, `${n} queued`)}</b>`
        + `<span>${q.held ? tt('停下之后暂停了，点“继续”接着发', 'paused after the stop; Resume sends them on') : open ? '' : esc(q.queued[0].text)}</span></button>`
        + (q.held ? `<button type="button" class="b" data-act="queue-resume">${icon('play', 12)}${tt('继续', 'Resume')}</button>` : '')
        + (n > 1 ? `<button type="button" class="b" data-act="queue-clear">${tt('全部去掉', 'Clear all')}</button>` : '') + `</div>`
        + (open ? `<ol class="ql">${q.queued.map((m) => (m.id === mine.editing
            ? `<li data-id="${esc(m.id)}" class="editing"><textarea rows="2" aria-label="${tt('改这条排队的消息', 'Edit this queued message')}">${esc(m.text)}</textarea><span class="qa"><button type="button" class="b" data-act="queue-save">${tt('保存', 'Save')}</button><button type="button" class="b quiet" data-act="queue-cancel">${tt('取消', 'Cancel')}</button></span></li>`
            : `<li data-id="${esc(m.id)}"><span class="qx">${esc(m.text)}</span><span class="qa">${ic('send', tt('现在就发（停下正在做的）', 'Send now (stops what it is doing)'), { act: 'queue-now', attrs: `data-arg="${esc(m.id)}"` })}${ic('edit', tt('编辑', 'Edit'), { act: 'queue-edit', attrs: `data-arg="${esc(m.id)}"` })}${ic('trash', tt('删除', 'Delete'), { act: 'queue-remove', attrs: `data-arg="${esc(m.id)}"` })}</span></li>`)).join('')}</ol>` : '')
    box.hidden = false
    if (box._html === html) return
    box._html = html; box.innerHTML = html
    const editor = box.querySelector('textarea')
    if (editor) { editor.focus(); editor.setSelectionRange(editor.value.length, editor.value.length) }
}
// One change of the queue: the host answers with the queue after it.
async function queueDo(app, action, more) {
    const chat = app.chat
    const r = await agent.queueAct(app.identity.id, chat, action, more)
    if (!r.ok) { said(r); app.kick(); return false }
    if (r.data && Array.isArray(r.data.queued)) app.queue[chat] = r.data
    if (app.chat === chat) drawQueue(app)
    app.kick()
    return true
}
export function queueToggle(app) { queueOpen = !(queueOpen || queueOf(app).held); $('.pg-queue')._html = ''; drawQueue(app) }
export function queueEdit(app, id) { of(app).editing = id; queueOpen = true; $('.pg-queue')._html = ''; $('.pg-queue').innerHTML = ''; drawQueue(app) }
export function queueCancel(app) {
    const mine = of(app)
    if (!mine.editing) return false
    mine.editing = null
    $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''
    drawQueue(app); focus()
    return true
}
export async function queueSave(app) {
    const mine = of(app), editor = $('.pg-queue textarea')
    if (!mine.editing || !editor) return
    const text = editor.value.trim(), id = mine.editing
    if (!text) return queueRemoveNow(app, id)
    mine.editing = null
    $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''
    await queueDo(app, 'edit', { id, text })
    focus()
}
async function queueRemoveNow(app, id) { of(app).editing = null; $('.pg-queue').innerHTML = ''; $('.pg-queue')._html = ''; await queueDo(app, 'remove', { id }); focus() }
export const queueRemove = (app, id) => queueDo(app, 'remove', { id })
export const queueNow = (app, id) => queueDo(app, 'send_now', { id })
export const queueResume = (app) => queueDo(app, 'resume')
export async function queueClear(app) {
    const n = queueOf(app).queued.length
    if (!(await confirm({ title: tt(`去掉排队的 ${n} 条消息？`, `Clear the ${n} queued messages?`), text: tt('它们不会被发出去。', 'They will not be sent.'), yes: tt('全部去掉', 'Clear all'), danger: true }))) return
    return queueDo(app, 'clear')
}

// Stop the turn at work in this chat (the button, or Esc). With messages waiting, the queue
// is held and shown, to resume, send, edit or delete from there.
export async function stop(app) {
    if (!app.busy(app.chat)) return false
    const chat = app.chat, held = queueOf(app).queued.length > 0
    const r = await agent.stop(app.identity.id, chat, held)
    if (!r.ok) { said(r, tt('没能停下', 'It could not be stopped')); return true }
    if (r.data && r.data.held) queueOpen = true
    if (r.data && r.data.stopped === false) toast(tt('它现在没有在做事。', 'It is not doing anything now.'))
    app.kick()
    return true
}

// ── the model of this chat ──
// What can be the model: the model in use and the model list, and (found: true) what the host
// finds on this computer, which takes it a moment (it looks for agents signed in here).
export async function loadSources({ found = false } = {}) {
    const [status, list, here] = await Promise.all([get('/api/app'), get('/api/app/models'), found || !sources.found ? get('/api/app/found') : null])
    sources = { status: status || sources.status, models: list ? list.models || [] : sources.models, found: here || sources.found, read: sources.read || !!list }
    return !!list
}
const chatRow = (app) => app.row()
const entry = (id) => sources.models.find((m) => m.id === id)
const defaultEntry = () => { const llm = (sources.status || {}).llm || {}; return entry(llm.id) || (llm.model ? llm : null) }
// A model by its own name; its source is said beside it, never in its place (models.js).
const shownName = (m) => models.modelLabel(m)
const ready = () => { const llm = (sources.status || {}).llm; return !llm || llm.ready !== false }
const current = (app) => entry(chatRow(app).model) || defaultEntry()

// Model picker aligned with OpenCode / T3 Chat / Hermes:
//   - Searchable command-popover grouped by unified Provider (Vendor + connection badge);
//   - Active model is checked in place (no redundant "Default · Default (...)" duplicate row);
//   - ACP agents expand their declared models inline so switching takes one click;
//   - Unconfigured providers stay in Settings > Model, never cluttering the chat switcher.
export async function pickModel(app, anchor) {
    if (sources.read) loadSources({ found: true })
    else if (!(await loadSources({ found: true }))) return said(failed.get('/api/app/models'), tt('模型列表没有读出来', 'The models could not be read'))
    const row = chatRow(app), base = defaultEntry(), active = current(app)
    const listed = sources.models.filter((m) => m.enabled !== false)
    const setUp = () => onboarding.modelDialog(app, { after: () => app.refresh() })
    const pickCatalogModel = async (provider, modelId) => {
        const existing = listed.find((m) => m.provider === provider && m.model === modelId)
        if (existing) return choose(app, base && existing.id === base.id ? null : existing.id)
        const kept = await models.use(provider, modelId)
        if (!kept.entry) return toast(kept.error || tt('未能切换模型', 'Could not switch model'), { error: true, fix: kept.fix || '' })
        await loadSources()
        return choose(app, kept.entry.id)
    }
    const extraCatalog = new Map() // provider -> [{id, name, description}]
    const buildItems = () => {
        const groups = models.bySource(listed)
        if (!groups.length) return [{ note: tt('还没有已配置的模型', 'No configured models yet') }]
        return groups.flatMap((g) => {
            const cat = extraCatalog.get(g.provider) || []
            const savedIds = new Set(g.models.map((m) => m.model))
            const inlineCat = models.isAgent(g.provider) ? cat.filter((x) => !savedIds.has(x.id)) : []
            // If an ACP agent already expanded its real models and the only saved row is unresolved "default",
            // still keep the saved row only if it's active or if no catalog rows exist.
            const rows = g.models.map((m) => {
                const isActive = !!(active && active.id === m.id)
                const isBase = !!(base && base.id === m.id)
                const lbl = models.modelLabel(m, { inGroup: true })
                const isDefaultName = lbl === tt('默认模型', 'Default model')
                return {
                    label: lbl,
                    right: isBase && !isDefaultName ? tt('默认', 'Default') : '',
                    checked: isActive,
                    run: () => choose(app, isBase ? null : m.id),
                }
            })
            const extraRows = inlineCat.map((x) => ({
                label: x.name || modelName(x.id),
                checked: false,
                run: () => pickCatalogModel(g.provider, x.id),
            }))
            // Keep the chat switcher focused on models (OpenCode / T3 style): only show a per-group
            // "Browse more" link when an ACP provider has no resolved concrete models yet.
            const hasConcrete = g.models.some((m) => m.model && m.model !== 'default') || inlineCat.length > 0
            const needMore = !hasConcrete && !extraCatalog.has(g.provider)
            return [
                { head: g.source, badge: g.via },
                ...rows,
                ...extraRows,
                ...(needMore ? [{
                    label: tt('浏览更多模型…', 'Browse more models…'),
                    icon: 'plus',
                    run: () => models.more(g.provider, g.label, {
                        current: (active || {}).provider === g.provider ? (active || {}).model : '',
                        then: async (kept) => { await loadSources(); choose(app, kept.id) },
                    }),
                }] : []),
            ]
        })
    }
    const footer = [
        { label: tt('添加提供方…', 'Add provider…'), icon: 'plus', run: setUp },
        { label: tt('管理模型…', 'Manage models…'), icon: 'settings', run: () => app.openSettings('model') },
    ]
    const node = menu(anchor && document.contains(anchor) ? anchor : $('.pick.model'), buildItems(), {
        side: 'top', align: 'end', cls: 'model-menu',
        label: tt('选择模型', 'Select model'),
        filter: tt('搜索模型或提供方…', 'Search models or providers…'),
        footer,
    })
    if (!node) return
    // Quietly fetch ACP agent model lists (cached per session) and expand them inline
    const agentProviders = [...new Set(listed.filter((m) => models.isAgent(m)).map((m) => m.provider))]
    for (const provider of agentProviders) {
        models.offered(provider).then((got) => {
            if (!node.isConnected) return
            extraCatalog.set(provider, (got && Array.isArray(got.models)) ? got.models : [])
            node.updateItems(buildItems())
        })
    }
}
async function choose(app, id, effort) {
    const row = chatRow(app), chat = app.chat
    const same = (row.model || null) === (id || null)
    if (same && effort === undefined) return
    // in the middle of a chat a switch costs: ask first (Hermes Desktop: "Switch anyway" / "Keep current model")
    if (!same && (app.records[chat] || []).some((r) => r.event === 'reply')) {
        const go = await confirm({ title: tt('在这个对话中途换模型？', 'Switch the model in the middle of this chat?'),
            text: tt('下一条消息会让新模型把整个对话从头读一遍，按完整的输入价格算。', 'With the next message the new model reads the whole conversation again, at the full input price.'),
            yes: tt('仍然切换', 'Switch anyway'), no: tt('保留现在的模型', 'Keep current model') })
        if (!go) return
    }
    // an effort belongs to its model: another model starts from its own default
    const next = entry(id) || defaultEntry() || {}
    const level = effort !== undefined ? effort : same ? row.effort : null
    const r = await agent.chatsAct(app.identity.id, 'model', chat, { model: id || null, effort: level && (next.efforts || []).includes(level) ? level : null })
    if (!r.ok) return said(r, tt('没换成', 'The model was not changed'))
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app); app.kick()
    if (!same) toast(tt(`这个对话现在用 ${shownName(next)}（${models.sourceLabel(next)}）`, `This chat now uses ${shownName(next)} (${models.sourceLabel(next)})`))
}
// How hard this chat's model thinks: the levels that model has, as its source names them.
export function pickEffort(app, anchor) {
    const row = chatRow(app), m = current(app) || {}
    menu(anchor, [{ head: tt(`思考强度 · ${shownName(m)}`, `Reasoning effort · ${shownName(m)}`) },
        ...['default', ...(m.efforts || [])].map((e) => ({ label: models.effortLabel(e), checked: (row.effort || 'default') === e, run: () => choose(app, row.model || null, e === 'default' ? null : e) }))],
    { side: 'top', align: 'end' })
}
// A model kept before its source was asked what it has (an entry without effort levels): the
// source is asked once, behind the page, and the entry gets its levels.
const told = new Set()
async function describe(app, m) {
    if (!m || !m.id || (m.efforts || []).length || told.has(m.id)) return
    told.add(m.id)
    const r = await post('/api/app/models', { action: 'describe', id: m.id })
    if (r.ok && r.data && Array.isArray(r.data.models) && JSON.stringify(r.data.models) !== JSON.stringify(sources.models)) { sources.models = r.data.models; draw(app) }
}

// ── where this chat works ──
// As a session of Claude Code or Codex is opened on a project: a chat the owner started works in
// one place (a project folder, the browser, the desktop), kept with the chat by the host, and for
// a git project either in the folder itself or in an isolated copy of it (a worktree on the
// chat's own branch). The main conversation is not tied to one place: its choice is said with
// each message, and remembered by this window.
const mainWhere = perChat('where')
const placeOf = (app, id) => (app.life.places || []).find((p) => p.id === id) || null
export function whereOf(app) {
    const row = chatRow(app)
    if (row.kind === 'new') return { kind: 'new', place: placeOf(app, row.place) ? row.place : null, isolation: row.isolation || null, branch: row.branch || '' }
    if (row.kind === 'main') { const kept = mainWhere.get(app, ''); return { kind: 'main', place: placeOf(app, kept) ? kept : null, isolation: null } }
    return null
}
async function setWhere(app, place, isolation = null) {
    const row = chatRow(app)
    if (row.kind === 'main') { mainWhere.set(app, place || ''); return draw(app) }
    const r = await agent.chatsAct(app.identity.id, 'place', app.chat, { place: place || null, isolation })
    if (!r.ok) return said(r, tt('没改成', 'It was not changed'))
    if (r.data && Array.isArray(r.data.chats)) app.chats = r.data.chats
    draw(app); app.kick()
    const p = placeOf(app, place)
    toast(!p ? tt('无项目', 'No project')
        : isolation === 'worktree' ? `${(p.title || p.id).replace(/^folder\s*·\s*/i, '')} · Worktree`
            : (p.title || p.id).replace(/^folder\s*·\s*/i, ''))
}
const MODES = [
    ['plan', '计划', 'Plan', 'plan', '只读分析与规划', 'Read-only planning'],
    ['ask', '询问', 'Ask', 'shield', '操作前逐项确认', 'Approve edits & commands'],
    ['auto', '自动', 'Auto', 'shield', '工作区自动执行，高风险询问', 'Auto in workspace, ask on high-risk'],
    ['full', '完整权限', 'Full Access', 'bolt', '免审批直接执行', 'Run all actions without prompts'],
]
export function pickMode(app, anchor) {
    const cur = chatRow(app).mode || ((app.values.approvals || {}).mode) || 'auto'
    menu(anchor && document.contains(anchor) ? anchor : $('.pick.mode'), [
        { head: tt('权限模式', 'Permission mode') },
        ...MODES.map(([id, zh, en, icName, subZh, subEn]) => ({
            label: tt(zh, en), sub: tt(subZh, subEn), icon: icName, danger: id === 'full', checked: cur === id,
            run: () => setMode(app, id),
        })),
        '-',
        { label: tt('权限设置…', 'Permissions…'), icon: 'settings', run: () => app.openSettings('permissions') },
    ], { side: 'top', align: 'start', label: tt('权限模式', 'Permission mode') })
}
export function pickWhere(app, anchor) {
    const at = whereOf(app)
    if (!at) return
    const places = app.life.places || [], own = at.kind === 'new'
    const projects = places.filter((p) => p.kind === 'folder' || p.kind === 'ssh')
    const others = places.filter((p) => ['browser', 'desktop'].includes(p.kind))
    const clean = (p) => (p.title || p.id).replace(/^folder\s*·\s*/i, '')
    const items = [
        { head: tt('项目', 'Project') },
        { label: tt('无项目', 'No project'), sub: '', checked: !at.place, run: () => setWhere(app, null) },
        ...projects.flatMap((p) => [
            {
                label: clean(p),
                sub: p.kind === 'ssh' ? `SSH · ${p.target || p.host}:${p.folder || '~'}` : (p.folder || ''),
                icon: p.kind === 'ssh' ? 'server' : 'folder',
                checked: at.place === p.id && at.isolation !== 'worktree',
                run: () => setWhere(app, p.id),
            },
            ...(own && p.kind === 'folder' && p.git ? [{ label: `${clean(p)} · Worktree`, sub: '', icon: 'branch', checked: at.place === p.id && at.isolation === 'worktree', run: () => setWhere(app, p.id, 'worktree') }] : []),
        ]),
        { label: tt('打开本地文件夹…', 'Open local folder…'), icon: 'folderPlus', run: () => openFolder(app) },
        { label: tt('连接 SSH 远程项目…', 'Connect SSH project…'), icon: 'server', run: () => openSshProject(app) },
        ...(others.length ? [{ head: tt('环境', 'Places') }] : []),
        ...others.map((p) => ({ label: p.title || p.id, icon: p.kind === 'browser' ? 'browser' : 'terminal', checked: at.place === p.id, run: () => setWhere(app, p.id) })),
    ]
    menu(anchor && document.contains(anchor) ? anchor : $('.pick.where'), items, { side: 'top', align: 'start', label: tt('项目', 'Project'), filter: projects.length > 8 ? tt('搜索项目', 'Find project') : '' })
}

export async function openSshProject(app, { then, initialHost = '', initialPort = null, initialPath = '', skipHostStep = false } = {}) {
    const got = (await get('/api/app/ssh_hosts')) || {}
    const hosts = Array.isArray(got.hosts) ? got.hosts : []
    const targetOf = (h) => {
        const base = [h.user ? `${h.user}@` : '', h.hostname || h.host, h.port ? `:${h.port}` : ''].join('')
        return h.proxy_jump ? `${base} via ${h.proxy_jump}` : base
    }
    const d = dialog(`<div class="ssh-dlg-head"><h5>${tt('连接 SSH 主机', 'Connect to Host')}</h5>${ic('close', tt('关闭', 'Close'), { act: 'ssh-close', cls: 'ssh-x' })}</div><div data-ssh-body></div>`)
    const bodyEl = d.querySelector('[data-ssh-body]')
    const closeBtn = d.querySelector('.ssh-x')
    if (closeBtn) closeBtn.onclick = closeDialog

    const parseHostInput = (raw, explicitPort) => {
        let host = String(raw || '').trim()
        let port = explicitPort || null
        const v6 = host.match(/^\[([^\]]+)\]:(\d{1,5})$/)
        if (v6) { host = v6[1]; port = Number(v6[2]) }
        else if (host.includes(':') && host.indexOf(':') === host.lastIndexOf(':')) {
            const [h, p] = host.split(':')
            if (/^\d{1,5}$/.test(p)) { host = h.trim(); port = Number(p) }
        }
        return { host, port }
    }

    const finishOpenFolder = async (spec, remoteDir, resEl, btnEl) => {
        if (btnEl) btnEl.disabled = true
        if (resEl) resEl.innerHTML = `<span class="spin"></span>${tt('正在打开远程目录…', 'Opening remote folder…')}`
        const r = await agent.places(app.identity.id, {
            action: 'ssh',
            host: spec.target || spec.host,
            folder: remoteDir || '~',
            ...(spec.port ? { port: spec.port } : {}),
        })
        if (!r.ok) {
            if (btnEl) btnEl.disabled = false
            if (resEl) resEl.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`
            return
        }
        closeDialog()
        await app.refresh()
        if (then) return then(r.data.place)
        const cur = chatRow(app)
        if (cur && cur.kind === 'new' && !(app.records[app.chat] || []).length) return setWhere(app, r.data.place)
        return app.newProjectChat ? app.newProjectChat(r.data.place) : setWhere(app, r.data.place)
    }

    // Step 2 (Cursor Remote-SSH "Open Folder"): browse arbitrary remote paths (/pfs/..., ~, /, symlinks)
    const renderFolderStep = (probeData) => {
        const spec = probeData.spec || {}
        const target = spec.target || spec.host || ''
        const port = spec.port || null
        const home = probeData.home || '~'
        const recent = Array.isArray(probeData.recent_folders) ? probeData.recent_folders : []
        const sysMeta = [probeData.os, probeData.arch].filter(Boolean).join(' · ')
        const titleEl = d.querySelector('.ssh-dlg-head h5')
        if (titleEl) titleEl.textContent = `${tt('打开远程目录', 'Open Remote Folder')} · ${target}`

        bodyEl.innerHTML = `<div class="ssh-sub-row">
  <span class="ssh-meta">${esc(sysMeta || target)}</span>
  <button type="button" class="btn quiet" data-ssh-change>${tt('切换主机', 'Change host')}</button>
</div>
<div class="ssh-nav">
  <input class="field ssh-dir-input" data-ssh-dir spellcheck="false" value="${esc(initialPath || home)}" placeholder="/path/to/project">
  <button type="button" class="btn quiet" data-ssh-go>${tt('前往', 'Go')}</button>
  <button type="button" class="btn quiet" data-ssh-hidden aria-pressed="false" title="${tt('显示隐藏目录', 'Show hidden folders')}">.*</button>
</div>
<div class="ssh-crumbs" data-ssh-crumbs></div>
${recent.length ? `<div class="ssh-recent" data-ssh-recent>${recent.map((p) => `<button type="button" class="ssh-crumb" data-jump="${esc(p)}" title="${esc(p)}">${esc(p.split('/').filter(Boolean).pop() || p)}</button>`).join('')}</div>` : ''}
<div class="ssh-list" role="listbox" aria-label="${tt('远程目录', 'Remote folders')}" data-ssh-dirs></div>
<div class="row ssh-foot">
  <span class="res" role="status"></span>
  <button type="button" class="btn quiet" data-ssh-cancel>${tt('取消', 'Cancel')}</button>
  <button type="button" class="btn" data-ssh-open data-default>${tt('打开此目录', 'Open Folder')}</button>
</div>`

        const dirInput = bodyEl.querySelector('[data-ssh-dir]')
        const crumbsEl = bodyEl.querySelector('[data-ssh-crumbs]')
        const dirsEl = bodyEl.querySelector('[data-ssh-dirs]')
        const resEl = bodyEl.querySelector('.res')
        const openBtn = bodyEl.querySelector('[data-ssh-open]')
        const hiddenBtn = bodyEl.querySelector('[data-ssh-hidden]')
        let currentPath = initialPath || home
        let selectedPath = ''
        let showHidden = false
        let reqSeq = 0

        const renderCrumbs = (absPath) => {
            const posix = String(absPath || '/').replace(/\\/g, '/')
            const norm = posix.replace(/\/+$/, '') || '/'
            const isWin = /^[A-Za-z]:/.test(norm)
            const segs = norm === '/' ? [] : norm.split('/').filter(Boolean)
            const homeNorm = String(home || '~').replace(/\\/g, '/').replace(/\/+$/, '')
            const parts = [
                `<button type="button" class="ssh-crumb${norm === homeNorm ? ' on' : ''}" data-crumb="${esc(home)}">~</button>`,
                ...(isWin ? [] : [`<button type="button" class="ssh-crumb${norm === '/' ? ' on' : ''}" data-crumb="/">/</button>`]),
            ]
            let acc = ''
            for (let i = 0; i < segs.length; i++) {
                const s = segs[i]
                acc = isWin ? (i === 0 ? `${s}/` : `${acc.replace(/\/$/, '')}/${s}`) : `${acc}/${s}`
                const cmp = acc.replace(/\/+$/, '')
                parts.push(`<button type="button" class="ssh-crumb${cmp === norm ? ' on' : ''}" data-crumb="${esc(acc)}">${esc(s)}</button>`)
            }
            crumbsEl.innerHTML = parts.join('')
            crumbsEl.querySelectorAll('[data-crumb]').forEach((b) => {
                b.onclick = () => loadDir(b.dataset.crumb)
            })
        }

        const loadDir = async (targetPath) => {
            const mySeq = ++reqSeq
            selectedPath = ''
            resEl.innerHTML = ''
            dirsEl.innerHTML = `<div class="ssh-empty"><span class="spin"></span>${tt('正在读取远程目录…', 'Loading…')}</div>`
            const r = await post('/api/app/ssh_browse', {
                host: target,
                ...(port ? { port } : {}),
                path: targetPath || '~',
                hidden: showHidden,
            })
            if (mySeq !== reqSeq) return
            if (!r.ok || !r.data) {
                dirsEl.innerHTML = `<div class="ssh-empty c-failed">✕ ${esc(r.error || tt('无法读取目录', 'Cannot read folder'))}</div>`
                return
            }
            currentPath = r.data.path || targetPath
            dirInput.value = currentPath
            renderCrumbs(currentPath)
            const folders = Array.isArray(r.data.folders) ? r.data.folders : []
            const rows = []
            if (r.data.parent) {
                rows.push(`<button type="button" class="ssh-row" data-up="${esc(r.data.parent)}">${icon('left', 14)}<span class="ssh-alias">..</span></button>`)
            }
            for (const f of folders) {
                const badges = [
                    f.symlink ? `<span class="ssh-badge link">→</span>` : '',
                    f.git ? `<span class="ssh-badge git">git</span>` : '',
                ].join('')
                rows.push(`<button type="button" class="ssh-row" role="option" aria-selected="false" data-dir="${esc(f.path)}">${icon('folder', 14)}<span class="ssh-alias">${esc(f.name)}</span>${badges}</button>`)
            }
            dirsEl.innerHTML = rows.length ? rows.join('') : `<div class="ssh-empty">${tt('此目录下没有子文件夹', 'No subfolders')}</div>`
            const upBtn = dirsEl.querySelector('[data-up]')
            if (upBtn) upBtn.onclick = () => loadDir(upBtn.dataset.up)
            dirsEl.querySelectorAll('[data-dir]').forEach((b) => {
                b.onclick = () => {
                    selectedPath = b.dataset.dir
                    dirInput.value = selectedPath
                    dirsEl.querySelectorAll('[data-dir]').forEach((x) => {
                        const on = x === b
                        x.classList.toggle('on', on)
                        x.setAttribute('aria-selected', String(on))
                    })
                }
                b.ondblclick = () => loadDir(b.dataset.dir)
            })
        }

        bodyEl.querySelector('[data-ssh-change]').onclick = () => renderHostStep(target)
        bodyEl.querySelector('[data-ssh-cancel]').onclick = closeDialog
        bodyEl.querySelector('[data-ssh-go]').onclick = () => loadDir(dirInput.value.trim() || '~')
        dirInput.onkeydown = (e) => {
            if (e.key === 'Enter') { e.preventDefault(); loadDir(dirInput.value.trim() || '~') }
        }
        hiddenBtn.onclick = () => {
            showHidden = !showHidden
            hiddenBtn.setAttribute('aria-pressed', String(showHidden))
            hiddenBtn.classList.toggle('on', showHidden)
            loadDir(currentPath)
        }
        bodyEl.querySelectorAll('[data-jump]').forEach((b) => { b.onclick = () => loadDir(b.dataset.jump) })
        openBtn.onclick = () => finishOpenFolder(spec, dirInput.value.trim() || selectedPath || currentPath, resEl, openBtn)
        loadDir(currentPath)
        dirInput.focus()
    }

    // Step 1 (Cursor Remote-SSH "Connect to Host"): pick ~/.ssh/config host or enter user@host[:port], probe connectivity first
    const renderHostStep = (prefill = '') => {
        const titleEl = d.querySelector('.ssh-dlg-head h5')
        if (titleEl) titleEl.textContent = tt('连接 SSH 主机', 'Connect to Host')
        bodyEl.innerHTML = `<div class="ssh-top-row">
  <input class="field ssh-input" data-ssh-host autofocus spellcheck="false" value="${esc(prefill)}" placeholder="user@host[:port]">
  <button type="button" class="btn ssh-connect" data-default>${tt('连接', 'Connect')}</button>
</div>
${hosts.length ? `<div class="ssh-list-head"><span>SSH Config</span><small data-ssh-count>${hosts.length}</small></div>
<div class="ssh-list" role="listbox" aria-label="SSH Config" data-ssh-list></div>` : `<div class="ssh-empty">${tt('~/.ssh/config 中无主机', 'No hosts in ~/.ssh/config')}</div>`}
<div class="row ssh-foot"><span class="res" role="status"></span></div>`

        const hostEl = bodyEl.querySelector('[data-ssh-host]')
        const listEl = bodyEl.querySelector('[data-ssh-list]')
        const countEl = bodyEl.querySelector('[data-ssh-count]')
        const res = bodyEl.querySelector('.res')
        const ok = bodyEl.querySelector('[data-default]')
        let activeIdx = -1
        let filtered = hosts.slice()

        const renderList = () => {
            if (!listEl) return
            const q = hostEl.value.trim().toLowerCase()
            filtered = q ? hosts.filter((h) => `${h.host} ${h.hostname || ''} ${h.user || ''} ${h.proxy_jump || ''}`.toLowerCase().includes(q)) : hosts.slice()
            if (countEl) countEl.textContent = String(filtered.length)
            if (!filtered.length) {
                listEl.innerHTML = `<div class="ssh-empty">${esc(tt('无匹配主机', 'No matching host'))}</div>`
                activeIdx = -1
                return
            }
            if (activeIdx >= filtered.length) activeIdx = 0
            listEl.innerHTML = filtered.map((h, i) => {
                const tgt = targetOf(h)
                const sub = tgt && tgt !== h.host ? `<span class="ssh-target">${esc(tgt)}</span>` : ''
                return `<button type="button" class="ssh-row${i === activeIdx ? ' on' : ''}" role="option" aria-selected="${i === activeIdx}" data-ssh-i="${i}">${icon('terminal', 15)}<span class="ssh-alias">${esc(h.host)}</span>${sub}</button>`
            }).join('')
            listEl.querySelectorAll('[data-ssh-i]').forEach((b) => {
                b.onclick = () => {
                    const idx = +b.dataset.sshI
                    const h = filtered[idx]
                    if (!h) return
                    activeIdx = idx
                    hostEl.value = h.host
                    listEl.querySelectorAll('[data-ssh-i]').forEach((x) => x.classList.toggle('on', x === b))
                    hostEl.focus()
                }
                b.ondblclick = () => {
                    const h = filtered[+b.dataset.sshI]
                    if (!h) return
                    hostEl.value = h.host
                    probeAndAdvance()
                }
            })
        }

        const probeAndAdvance = async (fresh = false) => {
            const parsed = parseHostInput(hostEl.value, initialHost && hostEl.value.trim() === initialHost ? initialPort : null)
            if (!parsed.host) {
                res.innerHTML = `<span class="c-failed">✕ ${tt('请输入 SSH 主机地址或别名', 'Enter an SSH host or alias')}</span>`
                hostEl.focus()
                return
            }
            ok.disabled = true
            res.innerHTML = `<span class="spin"></span>${tt('正在连接主机…', 'Connecting…')}`
            const r = await post('/api/app/ssh_probe', {
                host: parsed.host,
                ...(parsed.port ? { port: parsed.port } : {}),
                ...(fresh ? { fresh: true } : {}),
                identity: app.identity.id,
            })
            ok.disabled = false
            if (r.ok && r.data && r.data.ok) {
                renderFolderStep(r.data)
                return
            }
            const needsTermAuth = r.code === 'host_key_unknown' || r.code === 'auth_required'
            res.innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('连接失败', 'Connection failed'))}</span>`
                + (r.fix ? `<small class="fix">${esc(r.fix)}</small>` : '')
                + (needsTermAuth ? `<div class="ssh-auth-acts"><button type="button" class="btn quiet" data-ssh-auth>${tt('在终端中认证', 'Authenticate in Terminal')}</button><button type="button" class="btn quiet" data-ssh-retry>${tt('重试', 'Retry')}</button></div>` : '')
            const authBtn = res.querySelector('[data-ssh-auth]')
            if (authBtn) authBtn.onclick = () => {
                if (app.openSshAuthTerminal) app.openSshAuthTerminal({ host: parsed.host, target: parsed.host, port: parsed.port })
            }
            const retryBtn = res.querySelector('[data-ssh-retry]')
            if (retryBtn) retryBtn.onclick = () => probeAndAdvance(true)
        }

        hostEl.oninput = () => { activeIdx = -1; renderList() }
        hostEl.onkeydown = (e) => {
            if (e.key === 'ArrowDown' && filtered.length) {
                e.preventDefault()
                activeIdx = (activeIdx + 1) % filtered.length
                hostEl.value = filtered[activeIdx].host
                renderList()
                const el = listEl && listEl.querySelector(`[data-ssh-i="${activeIdx}"]`)
                if (el) el.scrollIntoView({ block: 'nearest' })
            } else if (e.key === 'ArrowUp' && filtered.length) {
                e.preventDefault()
                activeIdx = (activeIdx - 1 + filtered.length) % filtered.length
                hostEl.value = filtered[activeIdx].host
                renderList()
                const el = listEl && listEl.querySelector(`[data-ssh-i="${activeIdx}"]`)
                if (el) el.scrollIntoView({ block: 'nearest' })
            } else if (e.key === 'Enter') {
                e.preventDefault(); probeAndAdvance()
            }
        }
        ok.onclick = () => probeAndAdvance()
        renderList()
        hostEl.focus()
        if (skipHostStep && prefill) probeAndAdvance()
    }

    renderHostStep(initialHost)
}
// "Open folder": tries the native OS folder dialog first when available; falls back to the
// built-in folder browser (for remote browsers, headless sessions, or Linux without zenity).
export async function openFolder(app, { then } = {}) {
    const now = placeOf(app, (whereOf(app) || {}).place)
    const initial = now && now.folder ? now.folder.replace(/[\\/][^\\/]+[\\/]?$/, '') : ''
    const onOpened = (place) => {
        if (then) return then(place)
        const cur = chatRow(app)
        if (cur && cur.kind === 'new' && !(app.records[app.chat] || []).length) return setWhere(app, place)
        return app.newProjectChat ? app.newProjectChat(place) : setWhere(app, place)
    }
    if (!window.__HARNESS_NO_NATIVE_DIALOG && !navigator.webdriver) {
        const picked = await post('/api/app/pick_folder', initial ? { initial } : {})
        if (picked.ok && picked.data && picked.data.supported) {
            if (picked.data.cancelled || !picked.data.path) return
            const r = await agent.places(app.identity.id, { action: 'project', folder: picked.data.path })
            if (!r.ok) return said(r)
            await app.refresh()
            return onOpened(r.data.place)
        }
    }
    const d = dialog(`<h5>${tt('打开文件夹', 'Open folder')}</h5>
<label><span>${tt('路径', 'Path')}</span><input class="field" data-path spellcheck="false" autocomplete="off" aria-label="${tt('文件夹的路径', 'The folder’s path')}"></label>
<div class="picks folders" data-list role="listbox" aria-label="${tt('里面的文件夹', 'Folders inside')}"></div>

<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('用这个文件夹', 'Use this folder')}</button></div>`)
    const path = d.querySelector('[data-path]'), list = d.querySelector('[data-list]'), res = d.querySelector('.res'), ok = d.querySelector('[data-default]')
    d.querySelector('[data-no]').onclick = closeDialog
    let showSeq = 0
    const show = async (where) => {
        const mine = ++showSeq
        const got = await get('/api/app/folders', where ? { path: where } : {})
        if (!d.isConnected || mine !== showSeq) return
        if (!got) { const why = failed.get('/api/app/folders') || {}; res.innerHTML = `<span class="c-failed">✕ ${esc(why.error || tt('这个文件夹读不出来', 'That folder could not be read'))}</span>${why.fix ? `<small class="fix">${esc(why.fix)}</small>` : ''}`; return }
        res.innerHTML = ''
        path.value = got.path
        const rows = [...(got.parent ? [{ name: '..', path: got.parent, up: true }] : (got.roots || []).filter((r) => r !== got.path).map((r) => ({ name: r, path: r, up: true }))), ...got.folders]
        list.innerHTML = rows.map((f) => `<button type="button" class="opt" role="option" data-go="${esc(f.path)}">${icon(f.up ? 'up' : 'folder', 14)}<b>${esc(f.up && f.name === '..' ? tt('上一级', 'Up one level') : f.name)}</b>${f.git ? `<em>git</em>` : ''}</button>`).join('') || `<p class="note">${tt('里面没有文件夹。', 'No folders inside.')}</p>`
        list.scrollTop = 0
        ok.textContent = got.git ? tt('用这个文件夹（git 项目）', 'Use this folder (a git project)') : tt('用这个文件夹', 'Use this folder')
    }
    list.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) show(b.dataset.go) }
    list.onkeydown = (e) => {
        const all = [...list.querySelectorAll('[data-go]')], i = all.indexOf(document.activeElement)
        if (e.key === 'ArrowDown' && all[i + 1]) { e.preventDefault(); all[i + 1].focus() }
        else if (e.key === 'ArrowUp') { e.preventDefault(); (all[i - 1] || path).focus() }
    }
    path.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); show(path.value.trim()) }
        else if (e.key === 'ArrowDown' && list.querySelector('[data-go]')) { e.preventDefault(); list.querySelector('[data-go]').focus() }
    }
    ok.onclick = async () => {
        ok.disabled = true
        res.innerHTML = `<span class="spin"></span>${tt('正在接上这个项目…', 'connecting the project…')}`
        const r = await agent.places(app.identity.id, { action: 'project', folder: path.value.trim() })
        if (!r.ok) { ok.disabled = false; res.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog()
        await app.refresh()
        return onOpened(r.data.place)
    }
    // it opens beside the project this chat is on, else in the home folder
    await show(initial)
    path.focus(); path.select()
}

// ── what the composer shows of the chat's state ──
export function draw(app) {
    const row = chatRow(app), a = area()
    if (!a) return
    const busy = app.busy(app.chat)
    const modeBtn = $('.pick.mode')
    if (modeBtn) {
        const curMode = row.mode || ((app.values.approvals || {}).mode) || 'auto'
        const mInfo = MODES.find((x) => x[0] === curMode) || MODES[2]
        const mHtml = `${icon(mInfo[3], 13)}<span>${esc(tt(mInfo[1], mInfo[2]))}</span>`
        if (modeBtn._html !== mHtml) { modeBtn.innerHTML = mHtml; modeBtn._html = mHtml }
        modeBtn.classList.toggle('mode-plan', curMode === 'plan')
        modeBtn.classList.toggle('mode-ask', curMode === 'ask')
        modeBtn.classList.toggle('mode-full', curMode === 'full')
        modeBtn.classList.toggle('own', curMode !== 'auto')
    }
    const where = $('.pick.where'), at = whereOf(app)
    where.hidden = !at
    if (at) {
        const p = placeOf(app, at.place)
        const name = p ? (p.title || p.id).replace(/^folder\s*·\s*/i, '') : ''
        const label = !p ? tt('无项目', 'No project') : `${name}${at.isolation === 'worktree' ? ' · Worktree' : ''}`
        const html = `${icon(p ? (at.isolation === 'worktree' ? 'branch' : ({ folder: 'folder', ssh: 'server', browser: 'browser', desktop: 'terminal' })[p.kind] || 'folder') : 'folder', 13)}<span>${esc(label)}</span>`
        if (where._html !== html) { where.innerHTML = html; where._html = html }
        where.classList.toggle('own', !!p)
        where.dataset.tip = !p ? tt('项目', 'Project')
            : p.kind === 'ssh' ? `SSH · ${p.target || p.host}:${p.folder || '~'}`
                : at.isolation === 'worktree' ? `Worktree · ${at.branch || ''}`
                    : p.folder || name
    }
    a.disabled = row.kind === 'earlier'
    a.placeholder = row.kind === 'earlier' ? tt('只读对话', 'Read-only') : busy ? tt('继续补充…', 'Add a follow-up…') : tt('输入消息，@ 引用上下文，/ 调起命令…', 'Ask anything, @ to mention, / for actions…')
    $('.pg-compose .stop').hidden = !busy
    const sendButton = $('.pg-compose .send')
    sendButton.dataset.tip = busy ? tt('排队发送', 'Queue message') : tt('发送', 'Send')
    sendButton.setAttribute('aria-label', sendButton.dataset.tip)
    // until the models were read once, nothing is said about them (a host that does not answer is not "no model")
    const model = $('.pick.model'), m = current(app), usable = !sources.read || (ready() && !!m)
    model.textContent = !sources.read ? tt('模型', 'Model') : usable ? shownName(m) : tt('选择模型', 'Select model')
    // the button names the model; where it comes from is its tip
    model.dataset.tip = usable && m ? `${shownName(m)} · ${models.sourceLabel(m)}` : tt('模型', 'Model')
    if (usable && m) describe(app, m)
    model.classList.toggle('warn', !usable)
    model.classList.toggle('own', !!row.model)
    const effort = $('.pick.effort')
    effort.hidden = !usable || !m || !(m.efforts || []).length
    if (!effort.hidden) { effort.textContent = models.effortLabel(row.effort || 'default'); effort.dataset.tip = `${tt('思考强度', 'Reasoning effort')} · ${shownName(m)}` }
    // beside the composer: what is still missing before it can answer
    const notice = $('.pg-notice')
    notice.hidden = usable
    const html = usable ? '' : `${icon('alert', 14)}<span>${esc(tt('还没有可用的模型', 'No model is usable yet'))}</span><button type="button" class="b" data-act="model-choose">${esc(tt('选一个模型', 'Choose a model'))}</button>`
    if (notice._html !== html) { notice.innerHTML = html; notice._html = html }
    drawQueue(app)
}
export const modelOf = (app) => { const m = current(app); return m ? { name: shownName(m), id: m.model || '', source: models.sourceLabel(m), usable: ready() } : { name: sources.read ? tt('选一个模型', 'Choose a model') : '', id: '', usable: !sources.read } }
