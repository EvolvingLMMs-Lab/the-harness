// Single 24px environment footer row directly under the composer:
//   Left: Project selector (`.pick.where` updated by composer.draw) + active git branch
//   Right: Clickable Context % (opens full Context Breakdown Inspector popover — NEVER auto-compacts!) + Today's spend (when > 0)
import { esc, tt, usd, language } from './i18n.js'
import { post, agent } from './api.js'
import { $, menu, said, toast } from './ui.js'
import { icon } from './icons.js'
import { choicesOf } from './names.js'

export const frameHtml = () => `<div class="pg-status" aria-label="${tt('工作区与状态', 'Workspace and status')}">`
    + `<button type="button" class="pick where" data-act="where-pick" data-tip="${tt('工作项目', 'Project')}"></button>`
    + `<span class="pg-status-meta" role="status"></span></div>`

function fmtTokens(n) {
    if (n == null || Number.isNaN(Number(n))) return '—'
    const v = Math.max(0, Math.round(Number(n)))
    if (language() === 'zh') {
        if (v >= 10000) {
            const w = v / 10000
            return w >= 100 ? `${Math.round(w)}万` : `${Number(w.toFixed(1))}万`
        }
        return v.toLocaleString()
    }
    if (v >= 1e6) return `${Number((v / 1e6).toFixed(1))}M`
    if (v >= 1000) return `${Number((v / 1000).toFixed(v >= 1e4 ? 0 : 1))}k`
    return String(v)
}

let activePop = null
export function closeContextInspector() {
    if (activePop) {
        activePop.cleanup()
        activePop = null
    }
}

export function draw(app) {
    const bar = $('.pg-status'), meta = $('.pg-status-meta')
    if (!bar || !meta) return
    let ctx = app.context[app.chat] || null
    let used = ctx && (ctx.input_tokens || ctx.total_used || ctx.estimated_tokens) ? Number(ctx.input_tokens || ctx.total_used || ctx.estimated_tokens) : 0
    let win = ctx && ctx.window ? Number(ctx.window) : 0
    if (!used) {
        const recs = app.records[app.chat] || []
        for (let i = recs.length - 1; i >= 0; i--) {
            if (recs[i].event === 'model_reply' && recs[i].usage && recs[i].usage.input_tokens) {
                used = Number(recs[i].usage.input_tokens)
                win = Number(recs[i].usage.window || recs[i].usage.context_window || 0)
                break
            }
        }
    }
    const full = used && win ? Math.min(100, Math.round((used / win) * 100)) : null
    const row = app.row()
    const ws = (app.workspaceStats && app.workspaceStats[app.chat]) || {}
    const branch = row.branch || ws.branch || ''
    const day = app.usage.today || {}
    const spent = Number(day.cost_usd) || 0
    const showSpend = spent > 0

    const leftParts = []
    if (branch) {
        leftParts.push(`<span class="sb sb-branch" data-tip="${esc(ws.folder || row.folder || branch)}">${icon('branch', 12)}<span>${esc(branch)}</span></span>`)
    }
    const rightParts = []
    const ctxTip = used
        ? tt(`上下文 ${used.toLocaleString()}${win ? ' / ' + win.toLocaleString() : ''} · 点击查看上下文分析`,
            `Context ${used.toLocaleString()}${win ? ' / ' + win.toLocaleString() : ''} · Click for context breakdown`)
        : tt('查看上下文占用分析', 'View context breakdown')
    const ctxLbl = full !== null
        ? tt(`上下文 ${full}%`, `Context ${full}%`)
        : used
            ? tt(`上下文 ${fmtTokens(used)}`, `Context ${fmtTokens(used)}`)
            : tt('上下文', 'Context')
    rightParts.push(`<button type="button" class="sb ctx-btn${full !== null && full >= 80 ? ' warn' : ''}" data-act="ctx-inspect" aria-haspopup="dialog" aria-expanded="${activePop ? 'true' : 'false'}" data-tip="${esc(ctxTip)}">${icon('context', 12)}<span>${esc(ctxLbl)}</span></button>`)

    if (showSpend) {
        rightParts.push(`<button type="button" class="sb" data-act="settings" data-arg="usage" data-tip="${esc(tt('今日用量', "Today's usage"))}"><span>${usd(spent)}${day.daily_budget ? ` / ${usd(day.daily_budget)}` : ''}</span></button>`)
    }
    const html = `${leftParts.join('')}<span class="grow"></span>${rightParts.join('')}`
    if (meta._html !== html) { meta._html = html; meta.innerHTML = html }
}

function renderInspectorHtml(data) {
    const bd = (data && data.breakdown) || {}
    const det = (data && data.details) || {}
    const win = Number(data && data.window) || 0
    const used = Number((data && (data.input_tokens ?? data.total_used ?? data.estimated_tokens)) || 0)
    const buf = Number(bd.autocompact_buffer || 0)
    const denom = win || Math.max(1, used + buf)
    const usedPct = win ? Math.min(100, Math.round((used / win) * 100)) : null
    const pctStr = (v) => (v == null ? '—' : `${((Number(v) / denom) * 100).toFixed(1)}%`)

    const rows = [
        { key: 'messages', color: '#2563eb', label: tt('消息', 'Messages'), val: Number(bd.messages || 0), seg: true },
        { key: 'system_tools', color: '#ea580c', label: tt('系统工具', 'System tools'), val: Number(bd.system_tools || 0), seg: true },
        { key: 'mcp_tools', color: '#059669', label: tt('MCP 工具', 'MCP tools'), val: Number(bd.mcp_tools || 0), seg: true },
        { key: 'system_prompt', color: '#6b7280', label: tt('系统提示词', 'System prompt'), val: Number(bd.system_prompt || 0), seg: true },
        { key: 'skills', color: '#7c8594', label: tt('技能 (Skills)', 'Skills'), val: Number(bd.skills || 0), seg: true },
        { key: 'memory_files', color: '#8b95a5', label: tt('记忆文件', 'Memory files'), val: Number(bd.memory_files || 0), seg: true },
        { key: 'rules_files', color: '#9ca3af', label: tt('规则文件', 'Rules'), val: Number(bd.rules_files || 0), seg: true },
    ].filter((r) => r.val > 0 || r.key === 'messages' || r.key === 'system_prompt')

    if (buf > 0) {
        rows.push({ key: 'autocompact_buffer', color: '#b4bcc8', label: tt('自动压缩缓冲区', 'Autocompact buffer'), val: buf, seg: true })
    }
    if (win > 0 && bd.free_space != null) {
        rows.push({ key: 'free_space', color: 'var(--ar-raise)', label: tt('可用空间', 'Free space'), val: Number(bd.free_space), seg: false })
    }

    const barSegs = rows.filter((r) => r.seg && r.val > 0).map((r) => {
        const w = Math.max(0.8, (r.val / denom) * 100)
        return `<i style="width:${w.toFixed(2)}%;background:${r.color}" title="${esc(r.label)}: ${esc(fmtTokens(r.val))}"></i>`
    }).join('')

    const tableRows = rows.map((r) => `<div class="ctx-row">`
        + `<span class="ctx-sw" style="background:${r.color}"></span>`
        + `<span class="ctx-lbl">${esc(r.label)}</span>`
        + `<span class="ctx-tok">${esc(fmtTokens(r.val))}</span>`
        + `<span class="ctx-pct">${esc(win ? pctStr(r.val) : '—')}</span></div>`).join('')

    const detailGroup = (label, items) => {
        if (!Array.isArray(items) || !items.length) return ''
        return `<details class="ctx-det"><summary><span class="ctx-det-lbl">${esc(label)}</span><span class="ctx-det-cnt">${items.length}</span></summary>`
            + `<div class="ctx-det-list">${items.map((it) => `<div class="ctx-det-row"><span>${esc(it.name)}</span><small>${esc(fmtTokens(it.tokens))}</small></div>`).join('')}</div></details>`
    }
    const detailsHtml = [
        detailGroup(tt('MCP 工具', 'MCP tools'), det.mcp_tools),
        detailGroup(tt('记忆文件', 'Memory files'), det.memory_files),
        detailGroup(tt('技能 (Skills)', 'Skills'), det.skills),
        detailGroup(tt('规则文件', 'Rules'), det.rules_files),
    ].filter(Boolean).join('')

    const headRight = win ? `${fmtTokens(used)} / ${fmtTokens(win)}` : tt(`约 ${fmtTokens(used)} tokens`, `~${fmtTokens(used)} tokens`)
    const headLeft = usedPct !== null ? tt(`已使用 ${usedPct}%`, `${usedPct}% used`) : tt('上下文占用', 'Context usage')
    const metaSub = data && data.model ? `<span class="ctx-model">${esc(data.model)}</span>` : ''

    return `<div class="ctx-pop-head"><b>${tt('上下文', 'Context')}</b>${metaSub}</div>`
        + `<div class="ctx-pop-sum"><span>${esc(headLeft)}</span><span class="ctx-pop-ratio">${esc(headRight)}</span></div>`
        + `<div class="ctx-pop-bar" role="img" aria-label="${esc(headLeft)}">${barSegs}</div>`
        + `<div class="ctx-pop-rows">${tableRows}</div>`
        + (detailsHtml ? `<div class="ctx-pop-dets">${detailsHtml}</div>` : '')
        + `<div class="ctx-pop-foot">`
        + `<span class="ctx-pop-note">${data && data.summarized ? tt('已含历史摘要', 'Includes compacted summary') : tt(`${Number((data && data.messages) || 0)} 条消息`, `${Number((data && data.messages) || 0)} messages`)}</span>`
        + `<button type="button" class="b" data-ctx-compact>${icon('context', 13)}<span>${tt('压缩上下文', 'Compact context')}</span></button></div>`
}

export async function openContextInspector(app, anchor) {
    if (activePop) {
        const same = activePop.anchor === anchor
        closeContextInspector()
        if (same) return
    }
    const pop = document.createElement('div')
    pop.className = 'ctx-pop'
    pop.setAttribute('role', 'dialog')
    pop.setAttribute('aria-label', tt('上下文分析', 'Context breakdown'))
    const cached = app.context[app.chat] || {}
    pop.innerHTML = renderInspectorHtml(cached)
    document.body.appendChild(pop)

    const position = () => {
        if (!anchor || !anchor.isConnected) return
        const r = anchor.getBoundingClientRect()
        const pw = Math.min(348, innerWidth - 16)
        pop.style.width = `${pw}px`
        const left = Math.max(8, Math.min(innerWidth - pw - 8, r.right - pw))
        const bottom = Math.max(8, innerHeight - r.top + 8)
        pop.style.left = `${Math.round(left)}px`
        pop.style.bottom = `${Math.round(bottom)}px`
    }
    position()

    const onDown = (e) => {
        if (pop.contains(e.target) || (anchor && anchor.contains(e.target))) return
        closeContextInspector()
    }
    const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); closeContextInspector() } }
    addEventListener('pointerdown', onDown, true)
    addEventListener('keydown', onKey, true)
    addEventListener('resize', position)

    const cleanup = () => {
        removeEventListener('pointerdown', onDown, true)
        removeEventListener('keydown', onKey, true)
        removeEventListener('resize', position)
        pop.remove()
        if (anchor && anchor.isConnected) anchor.setAttribute('aria-expanded', 'false')
    }
    activePop = { pop, anchor, cleanup }
    if (anchor) anchor.setAttribute('aria-expanded', 'true')

    const wireActions = () => {
        const btn = pop.querySelector('[data-ctx-compact]')
        if (!btn) return
        btn.onclick = async () => {
            btn.disabled = true
            btn.setAttribute('aria-busy', 'true')
            const r = await post('/api/agent/compact', { identity: app.identity.id, chat: app.chat })
            btn.disabled = false
            btn.removeAttribute('aria-busy')
            if (!r.ok) return said(r)
            toast(tt('已压缩上下文', 'Context compacted'))
            const fresh = await agent.context(app.identity.id, app.chat)
            if (fresh) {
                app.context[app.chat] = fresh
                draw(app)
                if (activePop && activePop.pop === pop) {
                    pop.innerHTML = renderInspectorHtml(fresh)
                    wireActions()
                }
            }
            app.kick()
        }
    }
    wireActions()

    // Fetch live breakdown from backend
    const live = await agent.context(app.identity.id, app.chat)
    if (live && activePop && activePop.pop === pop) {
        app.context[app.chat] = live
        draw(app)
        pop.innerHTML = renderInspectorHtml(live)
        wireActions()
        position()
    }
}

export function approvalsMenu(app, anchor) {
    const spec = ((app.schema || {}).approvals || {}).ask || {}
    const now = (app.values.approvals || {}).ask
    menu(anchor, [{ head: tt('哪些事先问你 · 所有对话', 'What it asks first · every chat') },
        ...(choicesOf(spec) || [{ value: now, label: String(now) }]).map(({ value: v, label }) => ({ label, checked: v === now, run: async () => {
            const r = await post('/api/app/settings', { approvals: { ask: v } })
            if (!r.ok) return said(r)
            app.applied('approvals', 'ask', v)
        } })),
        '-', { label: tt('权限与限额…', 'Permissions and limits…'), icon: 'settings', run: () => app.openSettings('permissions') }], { side: 'top' })
}
