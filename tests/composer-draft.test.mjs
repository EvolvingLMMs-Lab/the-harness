import assert from 'node:assert/strict'
import test from 'node:test'

// Minimal DOM, localStorage, and controllable fetch harness for composer.js draft tests.
class MockStorage {
    constructor() { this.map = new Map() }
    getItem(k) { return this.map.has(k) ? this.map.get(k) : null }
    setItem(k, v) { this.map.set(String(k), String(v)) }
    removeItem(k) { this.map.delete(String(k)) }
    clear() { this.map.clear() }
}

class MockElement {
    constructor(tagName) {
        this.tagName = tagName.toUpperCase()
        this.className = ''
        this.hidden = false
        this.disabled = false
        this.value = ''
        this.innerHTML = ''
        this.scrollHeight = 24
        this.selectionStart = 0
        this.selectionEnd = 0
        this.style = {}
        this.attrs = new Map()
        this.children = []
        this.parentElement = null
        this.listeners = new Map()
        this.focused = false
    }
    setAttribute(k, v) { this.attrs.set(k, String(v)) }
    getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null }
    addEventListener(type, fn) {
        if (!this.listeners.has(type)) this.listeners.set(type, [])
        this.listeners.get(type).push(fn)
    }
    dispatch(type, event = {}) {
        for (const fn of this.listeners.get(type) || []) fn(event)
    }
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end }
    focus() { this.focused = true; globalThis.document.activeElement = this }
    append(...nodes) {
        for (const n of nodes) {
            n.parentElement = this
            this.children.push(n)
        }
    }
    remove() {
        if (!this.parentElement) return
        const i = this.parentElement.children.indexOf(this)
        if (i >= 0) this.parentElement.children.splice(i, 1)
        this.parentElement = null
    }
    querySelector(sel) {
        if (sel === 'input[type=file]') return fileInput
        return null
    }
    querySelectorAll() { return [] }
}

const textarea = new MockElement('textarea')
const form = new MockElement('form')
const fileInput = new MockElement('input')
const acBox = new MockElement('div')
const attsBox = new MockElement('div')
const chatArea = new MockElement('section')
const queueBox = new MockElement('div')
const body = new MockElement('body')
const storage = new MockStorage()

function toastsBox() {
    return body.children.find((c) => c.className === 'toasts') || null
}

globalThis.location = { search: '' }
globalThis.localStorage = storage
globalThis.document = {
    activeElement: null,
    body,
    createElement(tag) { return new MockElement(tag) },
    querySelector(sel) {
        if (sel === '.pg-compose textarea') return textarea
        if (sel === '.pg-compose') return form
        if (sel === '.pg-ac') return acBox
        if (sel === '.pg-atts') return attsBox
        if (sel === '.pg-chatarea') return chatArea
        if (sel === '.pg-queue') return queueBox
        if (sel === '.toasts') return toastsBox()
        return null
    },
    querySelectorAll(sel) {
        if (sel === '.toast.has-act') {
            const box = toastsBox()
            return box ? box.children.filter((c) => c.className.includes('has-act')) : []
        }
        return []
    },
}

// Keep UI toast timers from delaying test process exit.
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (...args) => {
    const timer = realSetTimeout(...args)
    if (timer && typeof timer.unref === 'function') timer.unref()
    return timer
}

// Controllable /api/agent/say request queue.
const pendingSays = []
globalThis.fetch = (url, opts = {}) => {
    const u = String(url)
    if (u.startsWith('/api/agent/commands')) {
        return Promise.resolve({
            ok: true,
            status: 200,
            statusText: 'OK',
            json: async () => ({ commands: [] }),
            text: async () => JSON.stringify({ commands: [] }),
        })
    }
    if (u === '/api/agent/say') {
        const payload = JSON.parse(opts.body || '{}')
        let resolveReq, rejectReq
        const promise = new Promise((res, rej) => { resolveReq = res; rejectReq = rej })
        const entry = {
            payload,
            succeed(data = { queued: 'q1', chat: payload.chat }) {
                resolveReq({
                    ok: true,
                    status: 200,
                    statusText: 'OK',
                    text: async () => JSON.stringify(data),
                })
            },
            fail(error = 'send failed', status = 500) {
                resolveReq({
                    ok: false,
                    status,
                    statusText: 'Error',
                    text: async () => JSON.stringify({ error }),
                })
            },
            networkError(message = 'offline') {
                rejectReq(new Error(message))
            },
        }
        pendingSays.push(entry)
        return promise
    }
    throw new Error(`unexpected fetch: ${u}`)
}

const composer = await import('../packages/app/ui/static/js/composer.js')

function readStoredDrafts() {
    const raw = storage.getItem('harness.app.draft')
    return raw ? JSON.parse(raw) : {}
}

function makeApp({ identity = 'id1', chat = 'chat-a' } = {}) {
    const app = {
        identity: { id: identity, name: identity },
        chat,
        view: 'chat',
        life: { places: [] },
        records: {},
        queue: {},
        kicks: 0,
        row() { return { chat: this.chat, kind: this.chat === 'main' ? 'main' : 'new' } },
        kick() { this.kicks += 1 },
    }
    return app
}

function switchChat(app, nextChat) {
    composer.leave(app)
    app.chat = nextChat
    composer.show(app)
}

function switchIdentity(app, nextIdentity, nextChat = 'main') {
    composer.leave(app)
    app.identity = { id: nextIdentity, name: nextIdentity }
    app.chat = nextChat
    composer.show(app)
}

function resetHarness() {
    pendingSays.length = 0
    storage.clear()
    textarea.value = ''
    textarea.disabled = false
    body.children = []
}

test('restores original draft to originating chat when send fails after switching chats', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    textarea.value = 'unsent message for chat A'
    const sendPromise = composer.send(app)
    assert.equal(pendingSays.length, 1)
    assert.deepEqual(pendingSays[0].payload, { identity: 'id1', chat: 'chat-a', text: 'unsent message for chat A' })
    assert.equal(textarea.value, '')

    // Switch to chat B while chat A send is still in flight and type in chat B.
    switchChat(app, 'chat-b')
    textarea.value = 'draft in chat B'

    // Chat A send fails while user is viewing chat B.
    pendingSays[0].fail('host error')
    await sendPromise

    // Chat B's live composer must stay intact; chat A's draft must be restored in storage.
    assert.equal(textarea.value, 'draft in chat B')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'unsent message for chat A')

    // Returning to chat A surfaces the restored original draft and keeps chat B's draft.
    switchChat(app, 'chat-a')
    assert.equal(textarea.value, 'unsent message for chat A')
    switchChat(app, 'chat-b')
    assert.equal(textarea.value, 'draft in chat B')
})

test('preserves a newer draft written in the originating chat after switching away when send fails', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    textarea.value = 'first attempt'
    const sendPromise = composer.send(app)
    assert.equal(pendingSays.length, 1)

    // Switch away, return to chat A, write a newer draft, and switch away again before failure.
    switchChat(app, 'chat-b')
    switchChat(app, 'chat-a')
    assert.equal(textarea.value, '')
    textarea.value = 'newer draft in A'
    switchChat(app, 'chat-b')
    textarea.value = 'unrelated draft in B'
    assert.equal(readStoredDrafts()['id1/chat-a'], 'newer draft in A')

    pendingSays[0].networkError('connection dropped')
    await sendPromise

    // Chat B is untouched; chat A keeps both the failed message and the newer draft.
    assert.equal(textarea.value, 'unrelated draft in B')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'first attempt\nnewer draft in A')

    switchChat(app, 'chat-a')
    assert.equal(textarea.value, 'first attempt\nnewer draft in A')
})

test('preserves a newer draft typed in place on both send failure and send success', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    // 1. Failure while staying in chat A with a newer draft typed.
    textarea.value = 'failed original'
    const failSend = composer.send(app)
    assert.equal(pendingSays.length, 1)
    textarea.value = 'typed while sending'
    pendingSays[0].fail('timeout')
    await failSend

    assert.equal(textarea.value, 'failed original\ntyped while sending')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'failed original\ntyped while sending')

    // 2. Success while staying in chat A with a newer draft already persisted.
    textarea.value = 'will succeed'
    const okSend = composer.send(app)
    assert.equal(pendingSays.length, 2)
    textarea.value = 'follow-up draft'
    // Simulate leave/show or debounced save having stored the newer draft before response arrives.
    switchChat(app, 'chat-b')
    switchChat(app, 'chat-a')
    assert.equal(textarea.value, 'follow-up draft')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'follow-up draft')

    pendingSays[1].succeed()
    await okSend

    assert.equal(textarea.value, 'follow-up draft')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'follow-up draft')
})

test('respects identity as well as chat when both identities use the same chat id', async () => {
    resetHarness()
    const app = makeApp({ identity: 'alice', chat: 'main' })
    composer.show(app)

    // Failure case: alice/main fails while bob/main is open.
    textarea.value = 'alice unsent message'
    const failSend = composer.send(app)
    assert.equal(pendingSays.length, 1)
    assert.equal(pendingSays[0].payload.identity, 'alice')
    assert.equal(pendingSays[0].payload.chat, 'main')

    switchIdentity(app, 'bob', 'main')
    textarea.value = 'bob active draft'

    pendingSays[0].fail('boom')
    await failSend

    assert.equal(textarea.value, 'bob active draft')
    assert.equal(readStoredDrafts()['alice/main'], 'alice unsent message')

    // Success case: alice/main succeeds while bob/main has a saved draft; must not wipe bob/main.
    switchIdentity(app, 'alice', 'main')
    assert.equal(textarea.value, 'alice unsent message')
    const okSend = composer.send(app)
    assert.equal(pendingSays.length, 2)

    switchIdentity(app, 'bob', 'main')
    assert.equal(textarea.value, 'bob active draft')
    assert.equal(readStoredDrafts()['bob/main'], 'bob active draft')

    pendingSays[1].succeed()
    await okSend

    assert.equal(textarea.value, 'bob active draft')
    assert.equal(readStoredDrafts()['bob/main'], 'bob active draft')
    assert.equal(readStoredDrafts()['alice/main'], undefined)
})

test('restores draft to storage when leaving chat view without switching chat id', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    textarea.value = 'sent before opening calendar'
    const sendPromise = composer.send(app)
    assert.equal(pendingSays.length, 1)

    // Simulate navigating to calendar/settings (leave called, app.chat still chat-a).
    composer.leave(app)
    app.view = 'calendar'

    pendingSays[0].fail('host down')
    await sendPromise

    assert.equal(readStoredDrafts()['id1/chat-a'], 'sent before opening calendar')

    // Returning to chat view reloads the restored draft.
    app.view = 'chat'
    composer.show(app)
    assert.equal(textarea.value, 'sent before opening calendar')
})

test('allows independent in-flight sends across different chats and restores only failed ones', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    textarea.value = 'message A'
    const sendA = composer.send(app)
    assert.equal(pendingSays.length, 1)

    switchChat(app, 'chat-b')
    textarea.value = 'message B'
    const sendB = composer.send(app)
    assert.equal(pendingSays.length, 2)

    // Fail A while on B, succeed B.
    pendingSays[0].fail('A failed')
    await sendA
    assert.equal(textarea.value, '')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'message A')

    pendingSays[1].succeed()
    await sendB
    assert.equal(textarea.value, '')
    assert.equal(readStoredDrafts()['id1/chat-b'], undefined)

    switchChat(app, 'chat-a')
    assert.equal(textarea.value, 'message A')
})

test('programmatic send(app, given) does not overwrite or clear an existing typed draft', async () => {
    resetHarness()
    const app = makeApp({ identity: 'id1', chat: 'chat-a' })
    composer.show(app)

    textarea.value = 'my typed draft'
    switchChat(app, 'chat-b')
    switchChat(app, 'chat-a')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'my typed draft')

    const failGiven = composer.send(app, 'Continue')
    assert.equal(pendingSays.length, 1)
    pendingSays[0].fail('error')
    await failGiven
    assert.equal(textarea.value, 'my typed draft')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'my typed draft')

    const okGiven = composer.send(app, 'Continue')
    assert.equal(pendingSays.length, 2)
    pendingSays[1].succeed()
    await okGiven
    assert.equal(textarea.value, 'my typed draft')
    assert.equal(readStoredDrafts()['id1/chat-a'], 'my typed draft')
})
