import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
    downloadMarkdown,
    exportChatMarkdown,
    exportFilename,
    formatChatMarkdown,
} from '../packages/app/ui/static/js/export.js'

function makeLongHistory(count = 1000) {
    const records = []
    for (let i = 1; i <= count; i++) {
        if (i === 1) {
            records.push({ seq: i, event: 'user', text: 'EARLIEST_USER_MESSAGE_SEQ_1' })
        } else if (i === count) {
            records.push({ seq: i, event: 'reply', text: `LATEST_ASSISTANT_REPLY_SEQ_${count}` })
        } else if (i % 2 === 1) {
            records.push({ seq: i, event: 'user', text: `user message ${i}` })
        } else {
            records.push({ seq: i, event: 'reply', text: `assistant reply ${i}` })
        }
    }
    return records
}

test('exports complete server history beyond the 800-record cache with earliest and latest text', async () => {
    const fullRecords = makeLongHistory(1000)
    const cachedSlice = fullRecords.slice(-800)
    assert.equal(cachedSlice.length, 800)
    assert.ok(!cachedSlice.some((r) => r.text === 'EARLIEST_USER_MESSAGE_SEQ_1'))

    const fetchCalls = []
    const downloads = []
    const toasts = []

    const res = await exportChatMarkdown({
        identity: 'default',
        chat: 'chat-long',
        fallbackTitle: 'Fallback Title',
        fetchHistory: async (identity, chat) => {
            fetchCalls.push({ identity, chat })
            return {
                chat,
                meta: { title: 'Long Conversation' },
                records: fullRecords,
                complete: true,
            }
        },
        download: (md, filename) => downloads.push({ md, filename }),
        notify: (text, opts) => toasts.push({ text, opts: opts || {} }),
    })

    assert.equal(res.ok, true)
    assert.deepEqual(fetchCalls, [{ identity: 'default', chat: 'chat-long' }])
    assert.equal(downloads.length, 1)
    assert.equal(downloads[0].filename, 'Long_Conversation.md')

    const { md } = downloads[0]
    assert.ok(md.startsWith('# Long Conversation\n'))
    const earliestIdx = md.indexOf('EARLIEST_USER_MESSAGE_SEQ_1')
    const latestIdx = md.indexOf('LATEST_ASSISTANT_REPLY_SEQ_1000')
    assert.ok(earliestIdx > 0, 'earliest record must be included in exported Markdown')
    assert.ok(latestIdx > earliestIdx, 'latest record must follow earliest record in exported Markdown')

    assert.equal(toasts.length, 1)
    assert.equal(toasts[0].opts.error, undefined)
    assert.match(toasts[0].text, /Exported conversation Markdown/)
})

test('fetch returning null reports error and does not download or claim a successful full export', async () => {
    const downloads = []
    const toasts = []

    const res = await exportChatMarkdown({
        identity: 'default',
        chat: 'chat-err',
        fallbackTitle: 'Errored Chat',
        fetchHistory: async () => null,
        lastError: () => ({ status: 500, error: 'host read failed', fix: 'Restart the host.' }),
        download: (md, filename) => downloads.push({ md, filename }),
        notify: (text, opts) => toasts.push({ text, opts: opts || {} }),
    })

    assert.equal(res.ok, false)
    assert.equal(downloads.length, 0)
    assert.equal(toasts.length, 1)
    assert.equal(toasts[0].opts.error, true)
    assert.equal(toasts[0].text, 'host read failed')
    assert.equal(toasts[0].opts.fix, 'Restart the host.')
    assert.doesNotMatch(toasts[0].text, /Exported conversation Markdown/)
})

test('incomplete server payload (without complete: true) does not claim a successful full export', async () => {
    const downloads = []
    const toasts = []

    // Simulates an older server that ignored all=1 and returned only the 500-record tail
    const truncatedRecords = makeLongHistory(1000).slice(-500)
    const res = await exportChatMarkdown({
        identity: 'default',
        chat: 'chat-truncated',
        fetchHistory: async () => ({
            chat: 'chat-truncated',
            meta: { title: 'Truncated' },
            records: truncatedRecords,
        }),
        download: (md, filename) => downloads.push({ md, filename }),
        notify: (text, opts) => toasts.push({ text, opts: opts || {} }),
    })

    assert.equal(res.ok, false)
    assert.equal(downloads.length, 0)
    assert.equal(toasts.length, 1)
    assert.equal(toasts[0].opts.error, true)
    assert.match(toasts[0].text, /Could not load complete conversation history/)
})

test('thrown fetch or download error reports error and never claims success', async () => {
    const fetchToasts = []
    const fetchRes = await exportChatMarkdown({
        identity: 'default',
        chat: 'chat-throw',
        fetchHistory: async () => { throw new Error('socket hang up') },
        download: () => { throw new Error('should not be called') },
        notify: (text, opts) => fetchToasts.push({ text, opts: opts || {} }),
    })
    assert.equal(fetchRes.ok, false)
    assert.equal(fetchToasts.length, 1)
    assert.equal(fetchToasts[0].opts.error, true)
    assert.equal(fetchToasts[0].opts.fix, 'socket hang up')

    const dlToasts = []
    const dlRes = await exportChatMarkdown({
        identity: 'default',
        chat: 'chat-dl-fail',
        fetchHistory: async () => ({
            chat: 'chat-dl-fail',
            meta: { title: 'DL Fail' },
            records: [{ seq: 1, event: 'user', text: 'hello' }],
            complete: true,
        }),
        download: () => { throw new Error('blob creation blocked') },
        notify: (text, opts) => dlToasts.push({ text, opts: opts || {} }),
    })
    assert.equal(dlRes.ok, false)
    assert.equal(dlToasts.length, 1)
    assert.equal(dlToasts[0].opts.error, true)
    assert.equal(dlToasts[0].opts.fix, 'blob creation blocked')
})

test('downloadMarkdown cleans up anchor and revokes object URL even if click throws', () => {
    let removed = false
    let revoked = null
    let scheduledFn = null
    const doc = {
        body: { append() {} },
        createElement(tag) {
            assert.equal(tag, 'a')
            return {
                href: '',
                download: '',
                click() { throw new Error('click failed') },
                remove() { removed = true },
            }
        },
    }
    const url = {
        createObjectURL() { return 'blob:test-url' },
        revokeObjectURL(href) { revoked = href },
    }
    assert.throws(
        () => downloadMarkdown('# Test\n', 'test.md', {
            doc,
            url,
            scheduleRevoke: (fn) => { scheduledFn = fn },
        }),
        /click failed/,
    )
    assert.equal(removed, true)
    assert.equal(typeof scheduledFn, 'function')
    scheduledFn()
    assert.equal(revoked, 'blob:test-url')
})

test('formatChatMarkdown ignores non-dialogue records and exportFilename sanitizes titles', () => {
    const md = formatChatMarkdown('Demo', [
        { seq: 1, event: 'user', text: 'first question' },
        { seq: 2, event: 'action', verb: 'task', text: 'should be skipped' },
        { seq: 3, event: 'reply', text: 'final answer' },
    ])
    assert.equal(md, '# Demo\n\n## User\n\nfirst question\n\n## Assistant\n\nfinal answer\n')
    assert.equal(exportFilename('中文 / Title: v1?'), '中文_Title_v1_.md')
    assert.equal(exportFilename('***', 'chat-1'), '_.md')
    assert.equal(exportFilename('', ''), 'chat.md')
})

test('app.js wires app.exportChat to complete server history instead of the 800-record cache', () => {
    const appJs = readFileSync(new URL('../packages/app/ui/static/js/app.js', import.meta.url), 'utf8')
    assert.match(appJs, /import\s*\{\s*exportChatMarkdown\s*\}\s*from\s*'\.\/export\.js'/)
    const match = appJs.match(/app\.exportChat\s*=\s*\(\)\s*=>\s*\{[\s\S]*?\n\}/)
    assert.ok(match, 'expected app.exportChat definition in app.js')
    const body = match[0]
    assert.match(body, /exportChatMarkdown\(/)
    assert.match(body, /get\('\/api\/agent\/chat',\s*\{[^}]*after:\s*0,\s*all:\s*1/)
    assert.doesNotMatch(body, /app\.records/)
})
