// Full-history Markdown export for a conversation.
// Reads complete history from the host instead of the page's bounded record cache,
// and reports an error rather than claiming a full export when history cannot be loaded.

export function formatChatMarkdown(title, records) {
    const lines = [`# ${title}`, '']
    for (const r of records || []) {
        if (r && r.event === 'user' && r.text) lines.push('## User', '', r.text, '')
        else if (r && r.event === 'reply' && r.text) lines.push('## Assistant', '', r.text, '')
    }
    return lines.join('\n')
}

export function exportFilename(title, fallback = 'chat') {
    const base = String(title || fallback || 'chat')
        .replace(/[^\w\u4e00-\u9fa5-]+/g, '_')
        .slice(0, 60)
    return `${base || 'chat'}.md`
}

export function downloadMarkdown(md, filename, { doc = document, url = URL, scheduleRevoke = setTimeout } = {}) {
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const href = url.createObjectURL(blob)
    let a = null
    try {
        a = doc.createElement('a')
        a.href = href
        a.download = filename
        doc.body.append(a)
        a.click()
    } finally {
        if (a) a.remove()
        scheduleRevoke(() => url.revokeObjectURL(href), 1000)
    }
}

export async function exportChatMarkdown({
    identity,
    chat,
    fallbackTitle = '',
    fetchHistory,
    lastError,
    download = downloadMarkdown,
    notify,
    t = (_zh, en) => en,
}) {
    if (!identity || !chat) {
        const error = t('当前没有可导出的对话', 'No conversation to export')
        const fix = t('请先打开一个对话。', 'Open a conversation first.')
        if (notify) notify(error, { error: true, fix })
        return { ok: false, error }
    }
    let got
    try {
        got = await fetchHistory(identity, chat)
    } catch (err) {
        const error = t('未能导出对话', 'Could not export conversation')
        const fix = (err && err.message) || t('请重试。', 'Try again.')
        if (notify) notify(error, { error: true, fix })
        return { ok: false, error }
    }
    if (!got) {
        const why = (typeof lastError === 'function' ? lastError() : lastError) || {}
        const error = why.error || t('未能导出对话', 'Could not export conversation')
        const fix = why.fix || t('请重试。', 'Try again.')
        if (notify) notify(error, { error: true, fix })
        return { ok: false, error }
    }
    if (!Array.isArray(got.records) || got.complete !== true) {
        const error = t('未能获取完整对话记录', 'Could not load complete conversation history')
        const fix = t('请更新并重启后台服务后重试。', 'Update and restart the host, then try again.')
        if (notify) notify(error, { error: true, fix })
        return { ok: false, error }
    }
    const title = (got.meta && got.meta.title) || fallbackTitle || chat
    const md = formatChatMarkdown(title, got.records)
    const filename = exportFilename(title, chat)
    try {
        download(md, filename)
    } catch (err) {
        const error = t('未能导出对话', 'Could not export conversation')
        const fix = (err && err.message) || t('请重试。', 'Try again.')
        if (notify) notify(error, { error: true, fix })
        return { ok: false, error }
    }
    if (notify) notify(t('已导出对话 Markdown', 'Exported conversation Markdown'))
    return { ok: true, filename, markdown: md, count: got.records.length }
}
