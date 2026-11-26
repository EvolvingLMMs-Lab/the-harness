// The host's API, the only thing the page reads and writes. The session key arrives in the
// address (?token=); the host then keeps it in a cookie, and the page also sends it as a header.
// A GET the host refuses or cannot answer gives null, and why is kept in `failed` (the
// host's {error, fix, log}: what went wrong, what to do, where the log is), so that the
// page says it instead of showing that part empty. A host that does not answer at all is told
// to whoever listens (onReach): the frame then says so and keeps asking.
import { tt } from './i18n.js'

const KEY = 'harness.token'
let token = new URLSearchParams(location.search).get('token')
try {
    if (token) sessionStorage.setItem(KEY, token)
    else token = sessionStorage.getItem(KEY)
} catch { /* storage may be unavailable: the cookie still carries the key */ }

const headers = (json) => ({ ...(json ? { 'Content-Type': 'application/json' } : {}), ...(token ? { 'X-Session-API-Key': token } : {}) })

function url(path, query) {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(query || {})) if (v !== undefined && v !== null && v !== '') q.set(k, v)
    const s = q.toString()
    return s ? `${path}?${s}` : path
}

// path -> {status, error, fix, log} of its last failed GET; absent once it answers again.
export const failed = new Map()

function problem(status, data, fallback) {
    const said = data && typeof data === 'object' ? data : {}
    if (status === 0) {
        return { status, code: 'unreachable', log: '', detail: fallback,
            error: tt('后台服务没有应答。', 'The background service does not answer.'),
            fix: tt('它可能还在启动，或者已经停了。这里会接着重试；在终端运行 harness doctor 能看到原因。', 'It may still be starting, or it has stopped. This page keeps trying; harness doctor in a terminal says why.') }
    }
    if (status === 404 && said.error === 'no such route') {
        // the page asks for something this host does not have: the two were not updated together
        return { status, code: 'no-route', log: '', detail: said.error,
            error: tt('这个后台还没有这个功能。', 'This host does not have this yet.'),
            fix: tt('页面比后台新：更新 The Harness，再重启后台服务。', 'The page is newer than the host: update The Harness, then restart the host.') }
    }
    const fix = said.fix || (status === 401 ? tt('用 harness app 打印的地址重新打开（地址里带着会话密钥）。', 'Open the address harness app prints again (it carries the session key).') : '')
    return { status, error: said.error || fallback, fix, log: said.log || '', code: said.code || '' }
}

// Whether the host answers at all: null, or the problem of the request that found it gone.
let down = null
const listeners = []
export function onReach(listener) { listeners.push(listener) }
export const unreachable = () => down
function reached(found) {
    if ((found === null) === (down === null)) { down = found; return }
    down = found
    for (const listener of listeners) listener(down)
}

export async function get(path, query) {
    try {
        const r = await fetch(url(path, query), { headers: headers(false), credentials: 'same-origin' })
        reached(null)
        if (!r.ok) {
            let data = null
            try { data = await r.json() } catch { data = null }
            failed.set(path, problem(r.status, data, r.statusText))
            return null
        }
        failed.delete(path)
        return await r.json()
    } catch (e) {
        const found = problem(0, null, String(e && e.message || e))
        failed.set(path, found)
        reached(found)
        return null
    }
}

// POST: {ok, data} or {ok: false, status, error, fix, log}; callers that only want the answer use `data`.
export async function post(path, body) {
    try {
        const r = await fetch(path, { method: 'POST', headers: headers(true), credentials: 'same-origin', body: JSON.stringify(body || {}) })
        reached(null)
        const text = await r.text()
        let data = null
        try { data = text ? JSON.parse(text) : null } catch { data = null }
        if (!r.ok) return { ok: false, ...problem(r.status, data, text || r.statusText) }
        return { ok: true, data }
    } catch (e) {
        const found = problem(0, null, String(e && e.message || e))
        reached(found)
        return { ok: false, ...found }
    }
}

export const sessionKey = () => token

// ── The chat's own requests, one function each, as the host's API gives them ──
// (the agent package's /api/agent/<name>; every one takes the identity).
export const agent = {
    // The record after number `after`, and the reply being written:
    // {chat, meta, records, live: null | {job, text, reasoning, since}}.
    chat: (identity, chat, after) => get('/api/agent/chat', { identity, chat, after }),
    // The owner's words into the chat's queue: {queued: id, chat}. `more`: {place, files}.
    say: (identity, chat, text, more = {}) => post('/api/agent/say', { identity, chat, text, ...more }),
    // What waits in the chat: {chat, held, running: null | {id, text, since}, queued: [{id, text, queued}]}.
    queue: (identity, chat) => get('/api/agent/queue', { identity, chat }),
    // action: edit {id, text} | remove {id} | clear | send_now {id} | resume → the queue after it.
    queueAct: (identity, chat, action, more = {}) => post('/api/agent/queue', { identity, chat, action, ...more }),
    // Stop the turn at work in the chat; hold keeps what is queued from starting:
    // {stopped, queued, held}.
    stop: (identity, chat, hold) => post('/api/agent/stop', { identity, chat, hold: !!hold }),
    // The list: [{chat, kind, title, updated, unread, waiting, busy, pinned, archived, model, effort}],
    // without the archived ones unless asked for; q finds by title and content.
    chats: (identity, { archived = false, q = '' } = {}) => get('/api/agent/chats', { identity, archived: archived ? 1 : 0, q }),
    // action: rename {title} | pin | unpin | archive | unarchive | delete | model {model, effort}
    // → the list after it.
    chatsAct: (identity, action, chat, more = {}) => post('/api/agent/chats', { identity, action, chat, ...more }),
    newChat: (identity, title) => post('/api/agent/new_chat', { identity, title }),
    opened: (identity, chat) => post('/api/agent/opened', { identity, chat }),
    approvals: (identity) => get('/api/agent/approvals', { identity }),
    // The owner's answer to an approval request; the first answer wins.
    answer: (identity, code, accept, reason = '') => post('/api/agent/approvals', { identity, code, accept, reason }),
    // A file for the next message: {identity, chat, name, type, data (base64)} → {id, name, size}.
    attach: (identity, chat, file) => post('/api/agent/attach', { identity, chat, ...file }),
}
