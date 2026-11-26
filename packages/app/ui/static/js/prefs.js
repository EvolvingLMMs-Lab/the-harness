// What this window remembers on this computer, not on the host: how the frame is arranged,
// whether thinking is shown, and per chat the unsent draft and the reading position. Kept in
// the browser's storage of the host's address, so it survives closing the window and
// restarting the host; another computer, or another address of the same host, has its own.
// Everything a second window must agree on (the chats, the queue, the settings) is the host's.

const PREFIX = 'harness.app.'
// Chats a per-chat table keeps; the least recently written go first.
const KEPT = 200

function read(key, fallback) {
    try {
        const raw = localStorage.getItem(PREFIX + key)
        return raw === null ? fallback : JSON.parse(raw)
    } catch { return fallback } // storage off, or something else's text under the key
}
function write(key, value) {
    try {
        if (value === undefined || value === null) localStorage.removeItem(PREFIX + key)
        else localStorage.setItem(PREFIX + key, JSON.stringify(value))
    } catch { /* storage full or off: the page goes on without remembering */ }
}

export const prefs = { get: read, set: write }

// One value per chat of an identity (drafts, reading positions): {"identity/chat": value}.
export function perChat(name) {
    const key = (app) => `${app.identity.id}/${app.chat}`
    return {
        get(app, fallback = null) {
            const all = read(name, {})
            return key(app) in all ? all[key(app)] : fallback
        },
        set(app, value) {
            const all = read(name, {})
            delete all[key(app)]
            if (value !== null && value !== undefined && value !== '') all[key(app)] = value
            const keys = Object.keys(all)
            for (const old of keys.slice(0, Math.max(0, keys.length - KEPT))) delete all[old]
            write(name, all)
        },
    }
}
