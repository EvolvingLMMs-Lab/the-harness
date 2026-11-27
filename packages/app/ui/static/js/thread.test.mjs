import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Minimal DOM implementation for testing thread.draw() and chat.rows() in Node without external deps.
const VOID_TAGS = new Set(['AREA', 'BASE', 'BR', 'COL', 'EMBED', 'HR', 'IMG', 'INPUT', 'LINK', 'META', 'PARAM', 'SOURCE', 'TRACK', 'WBR'])

class MockClassList {
    constructor(el) { this.el = el }
    _list() { return (this.el.getAttribute('class') || '').split(/\s+/).filter(Boolean) }
    contains(c) { return this._list().includes(c) }
    add(...cs) {
        const s = new Set(this._list())
        for (const c of cs) if (c) s.add(c)
        this.el.setAttribute('class', [...s].join(' '))
    }
    toggle(c, force) {
        const has = this.contains(c)
        const want = force === undefined ? !has : !!force
        const s = new Set(this._list())
        if (want) s.add(c); else s.delete(c)
        this.el.setAttribute('class', [...s].join(' '))
        return want
    }
}

function parseAttrs(raw) {
    const attrs = new Map()
    const re = /([:@\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g
    let m
    while ((m = re.exec(raw))) {
        const name = m[1].toLowerCase()
        const val = m[2] ?? m[3] ?? m[4] ?? ''
        attrs.set(name, val)
    }
    return attrs
}

function matchesCompound(el, compound) {
    let rest = compound
    const tagMatch = rest.match(/^[a-zA-Z][\w-]*/)
    if (tagMatch) {
        if (el.tagName !== tagMatch[0].toUpperCase()) return false
        rest = rest.slice(tagMatch[0].length)
    }
    const tokenRe = /(\.[a-zA-Z0-9_-]+|\[[^\]]+\])/g
    let m
    while ((m = tokenRe.exec(rest))) {
        const tok = m[1]
        if (tok.startsWith('.')) {
            if (!el.classList.contains(tok.slice(1))) return false
        } else {
            const inner = tok.slice(1, -1)
            const eq = inner.indexOf('=')
            if (eq < 0) {
                if (!el.hasAttribute(inner.toLowerCase())) return false
            } else {
                const k = inner.slice(0, eq).trim().toLowerCase()
                const v = inner.slice(eq + 1).trim().replace(/^["']|["']$/g, '')
                if (el.getAttribute(k) !== v) return false
            }
        }
    }
    return true
}

function matchesSelector(el, selector) {
    const parts = selector.trim().split(/\s+/)
    if (!matchesCompound(el, parts[parts.length - 1])) return false
    let cur = el.parentElement
    for (let i = parts.length - 2; i >= 0; i--) {
        while (cur && !matchesCompound(cur, parts[i])) cur = cur.parentElement
        if (!cur) return false
        cur = cur.parentElement
    }
    return true
}

class MockElement {
    constructor(tagName, attrs = new Map()) {
        this.tagName = tagName.toUpperCase()
        this._attrs = attrs
        this.children = []
        this.parentElement = null
        this._text = ''
        this.dataset = {}
        this.classList = new MockClassList(this)
        this.scrollTop = 0
        this.scrollHeight = 100
        this.clientHeight = 100
        for (const [k, v] of attrs.entries()) {
            if (k.startsWith('data-')) {
                const camel = k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())
                this.dataset[camel] = v
            }
        }
    }
    getAttribute(name) { const v = this._attrs.get(name.toLowerCase()); return v === undefined ? null : v }
    hasAttribute(name) { return this._attrs.has(name.toLowerCase()) }
    setAttribute(name, val) { this._attrs.set(name.toLowerCase(), String(val)) }
    removeAttribute(name) { this._attrs.delete(name.toLowerCase()) }
    get open() { return this._attrs.has('open') }
    set open(v) { if (v) this._attrs.set('open', ''); else this._attrs.delete('open') }
    get lastElementChild() { return this.children[this.children.length - 1] || null }
    get nextElementSibling() {
        if (!this.parentElement) return null
        const idx = this.parentElement.children.indexOf(this)
        return idx >= 0 ? (this.parentElement.children[idx + 1] || null) : null
    }
    get textContent() { return this._text + this.children.map((c) => c.textContent).join('') }
    set textContent(v) { this._text = String(v ?? ''); this.children = [] }
    set innerHTML(html) {
        this.children = []
        this._text = ''
        if (html) this.insertAdjacentHTML('beforeend', html)
    }
    appendChild(child) {
        child.parentElement = this
        this.children.push(child)
        return child
    }
    remove() {
        if (!this.parentElement) return
        const i = this.parentElement.children.indexOf(this)
        if (i >= 0) this.parentElement.children.splice(i, 1)
        this.parentElement = null
    }
    insertAdjacentHTML(position, html) {
        assert.equal(position, 'beforeend')
        const stack = [this]
        const tagRe = /<!--[\s\S]*?-->|<(\/)?([a-zA-Z][\w-]*)([^>]*?)(\/)?>|([^<]+)/g
        let m
        while ((m = tagRe.exec(html))) {
            if (m[5] !== undefined) {
                stack[stack.length - 1]._text += m[5]
                continue
            }
            if (!m[2]) continue
            const closing = !!m[1]
            const tag = m[2].toUpperCase()
            const attrRaw = m[3] || ''
            const selfClose = !!m[4] || VOID_TAGS.has(tag)
            if (closing) {
                for (let i = stack.length - 1; i > 0; i--) {
                    if (stack[i].tagName === tag) { stack.length = i; break }
                }
            } else {
                const el = new MockElement(tag, parseAttrs(attrRaw))
                stack[stack.length - 1].appendChild(el)
                if (!selfClose) stack.push(el)
            }
        }
    }
    matches(sel) { return matchesSelector(this, sel) }
    querySelectorAll(sel) {
        const out = []
        const walk = (node) => {
            for (const c of node.children) {
                if (matchesSelector(c, sel)) out.push(c)
                walk(c)
            }
        }
        walk(this)
        return out
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null }
}

const feed = new MockElement('div')
feed.setAttribute('class', 'pg-feed')

globalThis.location = { search: '' }
globalThis.document = {
    compatMode: 'CSS1Compat',
    activeElement: null,
    body: new MockElement('body'),
    querySelector(sel) {
        if (sel === '.pg-feed') return feed
        return null
    },
    querySelectorAll() { return [] },
}

const { draw } = await import('./thread.js')
const { rows } = await import('./chat.js')

function makeApp({ chat = 'c1', records = [], live = null, busy = true } = {}) {
    return {
        identity: { id: 'default', name: 'Harness' },
        chat,
        records: { [chat]: records },
        loaded: { [chat]: true },
        problems: {},
        live: { [chat]: live },
        busy: () => busy,
        titles: () => ({}),
        row: () => ({}),
        showTimeline: false,
    }
}

test('CSS hides .task-live immediately following an open details.act', () => {
    const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8')
    const baseIdx = css.indexOf('.task-live {')
    const hideIdx = css.search(/details\.act\[open\]\s*\+\s*\.task-live\s*\{\s*display:\s*none;?\s*\}/)
    assert.ok(baseIdx >= 0, 'expected .task-live base rule in app.css')
    assert.ok(hideIdx > baseIdx, 'expected details.act[open] + .task-live { display: none; } after .task-live')

    // Verify rendered DOM places .task-live as the immediate next sibling of details.act while running,
    // and removes .task-live once the task finishes.
    const ctx = { name: 'Harness', identity: 'default', chat: 'c1', titles: {}, thinking: true, busy: true }
    const runningRecs = [
        { seq: 1, event: 'action', verb: 'task', goal: 'run tests', time: 100 },
        { seq: 2, event: 'task_step', kind: 'cell', number: 1, code: 'pytest', status: 'ok', time: 101 },
    ]
    const host = new MockElement('div')
    host.innerHTML = rows(runningRecs, ctx).join('')
    const actDetails = host.querySelector('details.act')
    assert.ok(actDetails, 'running task with steps renders details.act')
    assert.ok(actDetails.nextElementSibling?.classList.contains('task-live'), '.task-live is immediate sibling of details.act')

    const endedRecs = [...runningRecs, { seq: 3, event: 'outcome', verb: 'task', end: 'done', time: 105 }]
    host.innerHTML = rows(endedRecs, { ...ctx, busy: false }).join('')
    assert.equal(host.querySelector('.task-live'), null, 'ended task omits .task-live')
})

test('thread.draw preserves expanded details.act across live task_step updates', () => {
    const recs = [
        { seq: 1, event: 'user', text: 'Run checks', time: 100 },
        { seq: 2, event: 'action', verb: 'task', goal: 'Run checks', time: 101 },
        { seq: 3, event: 'task_step', kind: 'cell', number: 1, code: 'step 1', status: 'ok', time: 102 },
    ]
    draw(makeApp({ chat: 'chat-steps', records: recs, busy: true }))

    let act = feed.querySelector('details.act')
    assert.ok(act)
    assert.equal(act.open, false)

    // User expands the running task details
    act.open = true

    // Several new task_step records arrive; each causes row replacement in thread.draw()
    for (let n = 2; n <= 7; n++) {
        recs.push({ seq: n + 2, event: 'task_step', kind: 'cell', number: n, code: `step ${n}`, status: 'ok', time: 101 + n })
        draw(makeApp({ chat: 'chat-steps', records: recs, busy: true }))
        act = feed.querySelector('details.act')
        assert.ok(act)
        assert.equal(act.open, true, `details.act should stay open after step ${n}`)
        assert.match(act.textContent, new RegExp(`Steps \\(${n}\\)|执行步骤 \\(${n}\\)`))
    }

    // If user collapses it while still running, subsequent steps keep it collapsed
    act.open = false
    recs.push({ seq: 20, event: 'task_step', kind: 'cell', number: 8, code: 'step 8', status: 'ok', time: 120 })
    draw(makeApp({ chat: 'chat-steps', records: recs, busy: true }))
    assert.equal(feed.querySelector('details.act').open, false)
})

test('thread.draw preserves details open state across group transitions, sumup, thinking, and chat switch', () => {
    // 1. Single action expanded -> gains second action in same group -> first stays open, second starts closed
    const recs = [
        { seq: 10, event: 'action', verb: 'task', goal: 'first task', time: 200 },
        { seq: 11, event: 'task_step', kind: 'cell', number: 1, code: 'cmd 1', status: 'ok', time: 201 },
    ]
    draw(makeApp({ chat: 'chat-trans', records: recs, busy: true }))
    const firstAct = feed.querySelector('details.act')
    firstAct.open = true

    recs.push({ seq: 12, event: 'action', verb: 'task', goal: 'second task', time: 202 })
    recs.push({ seq: 13, event: 'task_step', kind: 'cell', number: 1, code: 'cmd 2', status: 'ok', time: 203 })
    draw(makeApp({ chat: 'chat-trans', records: recs, busy: true }))

    let acts = feed.querySelectorAll('details.act')
    assert.equal(acts.length, 2)
    assert.equal(acts[0].open, true, 'first action stays open when group grows from 1 to 2 actions')
    assert.equal(acts[1].open, false, 'newly added second action starts closed')

    // 2. Turn ends -> group wraps into details.pe.acts.sumup; inner open state survives,
    //    and once sumup is opened, further redraws keep both sumup and inner act open.
    recs.push({ seq: 14, event: 'outcome', verb: 'task', end: 'done', time: 204 })
    recs.push({ seq: 15, event: 'outcome', verb: 'task', end: 'done', time: 205 })
    draw(makeApp({ chat: 'chat-trans', records: recs, busy: false }))

    let sumup = feed.querySelector('details.sumup')
    assert.ok(sumup)
    assert.equal(sumup.open, false)
    assert.equal(sumup.querySelectorAll('details.act')[0].open, true)

    sumup.open = true
    // Trigger replacement of the sumup row (e.g., an action_result arrives on the last action)
    recs.push({ seq: 16, event: 'action_result', result: 'all passed', time: 206 })
    draw(makeApp({ chat: 'chat-trans', records: recs, busy: false }))
    sumup = feed.querySelector('details.sumup')
    assert.equal(sumup.open, true, 'sumup details stays open across row replacement')
    assert.equal(sumup.querySelectorAll('details.act')[0].open, true, 'inner act stays open inside sumup')

    // 3. Live thinking starts open, respects user collapse during streaming, and resets to closed on final reply
    draw(makeApp({ chat: 'chat-trans', records: recs, live: { reasoning: 'part 1', text: '' }, busy: true }))
    let liveThink = feed.querySelector('details.thinking')
    assert.equal(liveThink.open, true)
    liveThink.open = false
    draw(makeApp({ chat: 'chat-trans', records: recs, live: { reasoning: 'part 1 + part 2', text: 'hi' }, busy: true }))
    liveThink = feed.querySelector('details.thinking')
    assert.equal(liveThink.open, false, 'manually collapsed live thinking stays collapsed while streaming')

    recs.push({ seq: 17, event: 'reply', reasoning: 'part 1 + part 2', text: 'hi', time: 207 })
    draw(makeApp({ chat: 'chat-trans', records: recs, live: null, busy: false }))
    const replyThink = feed.querySelector('details.thinking')
    assert.equal(replyThink.open, false)

    // 4. Switching to another chat does not inherit open state
    const otherRecs = [
        { seq: 10, event: 'action', verb: 'task', goal: 'other chat task', time: 300 },
        { seq: 11, event: 'task_step', kind: 'cell', number: 1, code: 'other', status: 'ok', time: 301 },
    ]
    draw(makeApp({ chat: 'chat-other', records: otherRecs, busy: true }))
    assert.equal(feed.querySelector('details.act').open, false, 'chat switch resets details open state')
})

test('thread.draw preserves details.act open state even when records omit seq', () => {
    const recs = [
        { event: 'action', verb: 'task', goal: 'no seq task', time: 400 },
        { event: 'task_step', kind: 'cell', number: 1, code: 'a', status: 'ok', time: 401 },
    ]
    draw(makeApp({ chat: 'chat-noseq', records: recs, busy: true }))
    feed.querySelector('details.act').open = true

    recs.push({ event: 'task_step', kind: 'cell', number: 2, code: 'b', status: 'ok', time: 402 })
    draw(makeApp({ chat: 'chat-noseq', records: recs, busy: true }))
    assert.equal(feed.querySelector('details.act').open, true)
})
