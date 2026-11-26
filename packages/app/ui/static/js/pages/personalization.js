// Settings › Personalization: who the identity is. Its persona and memory are Markdown files
// in its folder, as OpenClaw's workspace files are (SOUL.md, IDENTITY.md, USER.md, MEMORY.md),
// edited here or by telling it; USER.md is where what it should know about you goes, as the
// "about you" text of ChatGPT's personalization page.
import { esc, tt } from '../i18n.js'
import { post } from '../api.js'
import { on, flash, lock, empty, problem } from '../ui.js'
import { failed } from '../api.js'

export const identity = true
let c = null

export async function draw(ctx) {
    c = ctx
    const p = await ctx.get('/api/app/persona', { identity: ctx.id })
    if (!p) return problem(failed.get('/api/app/persona'), { title: tt('人设文件没有读出来', 'The persona files could not be read'), retry: 'settings' })
    return `<p>${tt('人设和记忆是它文件夹里的 Markdown 文件，可以在这里改，也可以直接告诉它。', 'Persona and memory are Markdown files in its folder: edit them here, or just tell it.')} <code>${esc(p.folder || `agents/${ctx.id}/`)}</code></p>`
        + `<div class="sr" data-rename><div><b id="sr-rename">${tt('显示名', 'Display name')}</b><small>${tt('随时能改；id 不变：', 'It can change any time; the id stays: ')}${esc(ctx.id)}</small></div><div class="ctl"><input type="text" aria-labelledby="sr-rename" value="${esc(ctx.name)}"></div></div>`
        + `<div class="lg">${tt('它的文件', 'Its files')}</div>`
        + (p.files.length ? p.files.map((f) => `<div class="file" data-file="${esc(f.name)}"><div class="fn"><span>${esc(f.name)}</span><span class="fs" role="status"></span><button type="button" data-act="persona-edit" data-arg="${esc(f.name)}">${tt('编辑', 'Edit')}</button></div><pre>${esc(f.text || tt('（空）', '(empty)'))}</pre></div>`).join('')
            : empty(tt('它还没有人设文件', 'It has no persona files yet')))
        + ctx.group(tt('指令文件', 'Instruction files'), ['instructions.load', 'instructions.files', 'instructions.root_markers', 'instructions.max_bytes', 'instructions.exclude'])
}

export function wire(ctx, pane) {
    const name = pane.querySelector('[data-rename] input')
    name.dataset.was = name.value
    name.onchange = () => lock(name, post('/api/agent/identity', { action: 'rename', id: ctx.id, name: name.value }).then((r) => {
        if (!r.ok) { name.value = name.dataset.was; return flash(name.parentElement, r.error || tt('没改成', 'Not renamed'), { error: true, fix: r.fix || '' }) }
        name.dataset.was = name.value
        flash(name.parentElement, tt('已保存', 'Saved'))
        ctx.app.reloadIdentities()
    }))
}

export function actions() {
    // A file opens for editing in place: Save writes it, Cancel leaves it as it was.
    on('persona-edit', (n) => {
        const box = n.closest('.file'), pre = box.querySelector('pre')
        if (!pre) return
        const text = pre.textContent === tt('（空）', '(empty)') ? '' : pre.textContent
        const area = document.createElement('textarea')
        area.value = text; area.rows = Math.min(24, Math.max(6, text.split('\n').length + 1))
        area.setAttribute('aria-label', n.dataset.arg)
        pre.replaceWith(area)
        box._text = text
        n.outerHTML = `<button type="button" data-act="persona-cancel" data-arg="${esc(n.dataset.arg)}">${tt('取消', 'Cancel')}</button><button type="button" class="pri" data-act="persona-save" data-arg="${esc(n.dataset.arg)}">${tt('保存', 'Save')}</button>`
        area.oninput = () => { box.querySelector('.fs').textContent = area.value === box._text ? '' : tt('有没保存的改动', 'unsaved changes') }
        area.focus()
    })
    const closed = (box, text, name) => {
        const pre = document.createElement('pre')
        pre.textContent = text || tt('（空）', '(empty)')
        box.querySelector('textarea').replaceWith(pre)
        for (const b of box.querySelectorAll('.fn button')) b.remove()
        box.querySelector('.fn').insertAdjacentHTML('beforeend', `<button type="button" data-act="persona-edit" data-arg="${esc(name)}">${tt('编辑', 'Edit')}</button>`)
        box.querySelector('.fn button').focus()
    }
    on('persona-cancel', (n) => { const box = n.closest('.file'); box.querySelector('.fs').textContent = ''; closed(box, box._text, n.dataset.arg) })
    on('persona-save', async (n) => {
        const box = n.closest('.file'), area = box.querySelector('textarea'), name = n.dataset.arg, text = area.value
        const r = await post('/api/app/persona', { identity: c.id, file: name, text })
        const status = box.querySelector('.fs')
        if (!r.ok) { status.innerHTML = `<span class="c-failed">${esc(r.error || tt('没存上', 'Not saved'))}${r.fix ? ' ' + esc(r.fix) : ''}</span>`; return }
        closed(box, text, name)
        status.innerHTML = `<span class="c-done">${tt('已保存', 'Saved')}</span>`
        setTimeout(() => { if (status.textContent === tt('已保存', 'Saved')) status.textContent = '' }, 2400)
    })
}
