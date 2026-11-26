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
