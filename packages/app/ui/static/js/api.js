// The host's API, the only thing the page reads and writes. The session key arrives in the
// address (?token=); the host then keeps it in a cookie, and the page also sends it as a header.
// A GET the host refuses or cannot answer gives null, and why is kept in `failed` (the
// host's {error, fix, log}: what went wrong, what to do, where the log is), so that the
// page says it instead of showing that part empty.

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
    return { status, error: said.error || fallback, fix: said.fix || '', log: said.log || '', code: said.code || '' }
}

export async function get(path, query) {
    try {
        const r = await fetch(url(path, query), { headers: headers(false), credentials: 'same-origin' })
        if (!r.ok) {
            let data = null
            try { data = await r.json() } catch { data = null }
            failed.set(path, problem(r.status, data, r.statusText))
            return null
        }
        failed.delete(path)
        return await r.json()
    } catch (e) {
        failed.set(path, problem(0, null, String(e && e.message || e)))
        return null
    }
}

// POST: {ok, data} or {ok: false, status, error, fix, log}; callers that only want the answer use `data`.
export async function post(path, body) {
    try {
        const r = await fetch(path, { method: 'POST', headers: headers(true), credentials: 'same-origin', body: JSON.stringify(body || {}) })
        const text = await r.text()
        let data = null
        try { data = text ? JSON.parse(text) : null } catch { data = null }
        if (!r.ok) return { ok: false, ...problem(r.status, data, text || r.statusText) }
        return { ok: true, data }
    } catch (e) { return { ok: false, ...problem(0, null, String(e && e.message || e)) } }
}

export const sessionKey = () => token
