// The host's API, the only thing the page reads and writes. The session key arrives in the
// address (?token=); the host then keeps it in a cookie, and the page also sends it as a header.
// A route the host does not have yet (404), or one that refuses (400), answers null: the
// page shows that part empty instead of failing.

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

export async function get(path, query) {
    try {
        const r = await fetch(url(path, query), { headers: headers(false), credentials: 'same-origin' })
        if (!r.ok) return null
        return await r.json()
    } catch { return null }
}

// POST: {ok, data} or {ok: false, error}; callers that only want the answer use `data`.
export async function post(path, body) {
    try {
        const r = await fetch(path, { method: 'POST', headers: headers(true), credentials: 'same-origin', body: JSON.stringify(body || {}) })
        const text = await r.text()
        let data = null
        try { data = text ? JSON.parse(text) : null } catch { data = null }
        if (!r.ok) return { ok: false, status: r.status, error: (data && data.error) || text || r.statusText }
        return { ok: true, data }
    } catch (e) { return { ok: false, status: 0, error: String(e) } }
}

export const sessionKey = () => token
