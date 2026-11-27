// Single shared attachment renderer for both composer thumbnails/chips and message
// attachments, plus a native <dialog> image lightbox (Esc/backdrop close, prev/next).
import { esc, tt } from './i18n.js'
import { icon } from './icons.js'
import { ic } from './ui.js'
import { sessionKey } from './api.js'

const IMAGE_EXT = /\.(?:png|jpe?g|gif|webp|bmp|avif|svg)$/i

export function isImageAttachment(item) {
    if (!item || typeof item !== 'object') return false
    const mime = String(item.mime || item.type || '').toLowerCase()
    if (mime.startsWith('image/')) return true
    return IMAGE_EXT.test(String(item.name || ''))
}

export function attachmentUrl(item, ctx = {}) {
    if (!item || typeof item !== 'object') return ''
    if (item.previewUrl) return item.previewUrl
    const tok = sessionKey()
    const appendToken = (u) => {
        if (!u || !tok || u.startsWith('blob:') || u.startsWith('data:') || /[?&]token=/.test(u)) return u
        return `${u}${u.includes('?') ? '&' : '?'}token=${encodeURIComponent(tok)}`
    }
    if (item.url) return appendToken(String(item.url))
    if (item.id) {
        const q = new URLSearchParams()
        if (ctx.identity) q.set('identity', ctx.identity)
        if (ctx.chat) q.set('chat', ctx.chat)
        const qs = q.toString()
        return appendToken(`/api/app/attachments/${encodeURIComponent(item.id)}${qs ? '?' + qs : ''}`)
    }
    return ''
}

function formatBytes(n) {
    const v = Number(n || 0)
    if (!v || v < 0) return ''
    if (v < 1024) return `${v} B`
    if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`
    return `${(v / (1024 * 1024)).toFixed(1)} MB`
}

export function renderAttachments(items, mode = 'message', ctx = {}) {
    const list = Array.isArray(items) ? items : []
    if (mode === 'composer') {
        return list.map((f, i) => {
            const img = isImageAttachment(f)
            const url = attachmentUrl(f, ctx)
            const state = f.state || 'ready'
            const tip = f.problem ? ` data-tip="${esc([f.problem.error, f.problem.fix].filter(Boolean).join(' '))}" tabindex="0"` : ''
            const retryBtn = state === 'failed'
                ? ic('retry', tt('重试上传', 'Retry upload'), { act: 'attach-retry', attrs: `data-arg="${i}"` })
                : ''
            const rmBtn = `<button type="button" class="att-rm" data-act="attach-remove" data-arg="${i}" aria-label="${esc(tt(`去掉 ${f.name}`, `Remove ${f.name}`))}">${icon('close', 11)}</button>`
            if (img && url) {
                return `<div class="att-thumb ${esc(state)}"${tip} title="${esc(f.name || '')}">`
                    + `<img src="${esc(url)}" alt="${esc(f.name || '')}" loading="lazy">`
                    + (state === 'uploading' ? '<span class="att-spin"></span>' : '')
                    + retryBtn + rmBtn + `</div>`
            }
            const sz = formatBytes(f.size)
            return `<div class="att-chip ${esc(state)}"${tip}>`
                + icon(img ? 'image' : 'file', 13)
                + `<span class="att-name">${esc(f.name || 'file')}</span>`
                + (sz ? `<small class="att-sz">${esc(sz)}</small>` : '')
                + retryBtn + rmBtn + `</div>`
        }).join('')
    }

    const images = []
    const files = []
    for (const raw of list) {
        const f = typeof raw === 'string' ? { name: raw } : (raw || {})
        const url = attachmentUrl(f, ctx)
        if (isImageAttachment(f) && url) {
            images.push({ name: f.name || 'image', url, size: f.size })
        } else {
            files.push({ name: f.name || 'file', url, size: f.size, img: isImageAttachment(f) })
        }
    }

    const imagesJson = images.length ? esc(JSON.stringify(images.map((im) => ({ url: im.url, name: im.name })))) : ''
    const imagesHtml = images.length
        ? `<div class="msg-att-images" data-lightbox-group="${imagesJson}">`
            + images.map((im, idx) => `<button type="button" class="msg-att-img" data-act="att-lightbox" data-idx="${idx}" aria-label="${esc(tt(`查看大图 ${im.name}`, `View image ${im.name}`))}" title="${esc(im.name)}">`
                + `<img src="${esc(im.url)}" alt="${esc(im.name)}" loading="lazy" data-att-img>`
                + `<span class="msg-att-broken" hidden>${icon('image', 14)}<span>${esc(im.name)}</span></span>`
                + `</button>`).join('')
            + `</div>`
        : ''

    const filesHtml = files.length
        ? `<div class="msg-att-files">`
            + files.map((f) => {
                const inner = `${icon(f.img ? 'image' : 'file', 12)}<span>${esc(f.name)}</span>`
                    + (f.size ? `<small>${esc(formatBytes(f.size))}</small>` : '')
                return f.url
                    ? `<a class="msg-att-chip" href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
                    : `<span class="msg-att-chip">${inner}</span>`
            }).join('')
            + `</div>`
        : ''

    return { imagesHtml, filesHtml }
}

let dlg = null
let lbImages = []
let lbIndex = 0
let mounted = false

export function mountAttachments() {
    if (mounted || typeof document === 'undefined') return
    mounted = true
    document.addEventListener('error', (e) => {
        const img = e.target
        if (!img || img.tagName !== 'IMG' || !img.hasAttribute('data-att-img')) return
        img.hidden = true
        const broken = img.parentElement && img.parentElement.querySelector('.msg-att-broken')
        if (broken) broken.hidden = false
        if (img.parentElement) img.parentElement.classList.add('broken')
    }, true)
}

function ensureLightbox() {
    if (dlg) return dlg
    dlg = document.createElement('dialog')
    dlg.className = 'att-lightbox'
    dlg.setAttribute('aria-label', tt('图片预览', 'Image preview'))
    dlg.innerHTML = `<div class="lb-frame">
        <div class="lb-head"><span class="lb-title"></span><span class="lb-count"></span>
            <button type="button" class="pg-ic lb-close" aria-label="${esc(tt('关闭', 'Close'))}">${icon('close', 15)}</button>
        </div>
        <div class="lb-stage">
            <button type="button" class="lb-nav prev" aria-label="${esc(tt('上一张', 'Previous image'))}">${icon('left', 18)}</button>
            <img class="lb-img" alt="">
            <button type="button" class="lb-nav next" aria-label="${esc(tt('下一张', 'Next image'))}">${icon('right', 18)}</button>
        </div>
    </div>`
    dlg.addEventListener('click', (e) => {
        if (e.target === dlg) { dlg.close(); return }
        if (e.target.closest('.lb-close')) { dlg.close(); return }
        if (e.target.closest('.lb-nav.prev')) { stepLightbox(-1); return }
        if (e.target.closest('.lb-nav.next')) { stepLightbox(1); return }
    })
    dlg.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); stepLightbox(-1) }
        else if (e.key === 'ArrowRight') { e.preventDefault(); stepLightbox(1) }
    })
    document.body.appendChild(dlg)
    return dlg
}

function paintLightbox() {
    if (!dlg || !lbImages.length) return
    const cur = lbImages[lbIndex] || lbImages[0]
    const img = dlg.querySelector('.lb-img')
    img.src = cur.url
    img.alt = cur.name || ''
    dlg.querySelector('.lb-title').textContent = cur.name || ''
    const multi = lbImages.length > 1
    dlg.querySelector('.lb-count').textContent = multi ? `${lbIndex + 1} / ${lbImages.length}` : ''
    dlg.querySelector('.lb-nav.prev').hidden = !multi
    dlg.querySelector('.lb-nav.next').hidden = !multi
}

function stepLightbox(delta) {
    if (lbImages.length <= 1) return
    lbIndex = (lbIndex + delta + lbImages.length) % lbImages.length
    paintLightbox()
}

export function openLightbox(images, index = 0) {
    if (!Array.isArray(images) || !images.length) return
    const dialogEl = ensureLightbox()
    lbImages = images
    lbIndex = Math.max(0, Math.min(index, images.length - 1))
    paintLightbox()
    if (!dialogEl.open) dialogEl.showModal()
}

export function openLightboxFromButton(btn) {
    const group = btn && btn.closest('[data-lightbox-group]')
    if (!group) return
    try {
        const items = JSON.parse(group.dataset.lightboxGroup || '[]')
        openLightbox(items, Number(btn.dataset.idx || 0))
    } catch { /* ignore */ }
}
