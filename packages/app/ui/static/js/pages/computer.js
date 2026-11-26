// Settings › Computer: the places on this computer an identity works in (project folders, the
// browser, the desktop), how much it does on its own in each, and how it may use the real
// mouse and keyboard. The closest pages of the reference are Hermes Desktop's Workspace and
// Safety; the places and the safety layer's fixed rules are the plan's own.
import { esc, tt } from '../i18n.js'
import { post } from '../api.js'
import { on, dialog, closeDialog, press, confirm, said, toast, row, mark, act, empty } from '../ui.js'

export const identity = true
let c = null
const KIND = { folder: ['项目文件夹', 'Project folder'], browser: ['浏览器', 'Browser'], desktop: ['桌面', 'Desktop'] }
const kind = (k) => (KIND[k] ? tt(KIND[k][0], KIND[k][1]) : k)

export async function draw(ctx) {
    c = ctx
    const got = await ctx.get('/api/agent/places', { identity: ctx.id })
    const places = ((got && got.places) || []).filter((p) => KIND[p.kind])
    return ``
        + `<div class="lg">${tt('接上的地方', 'Connected places')}</div>`
        + (places.length ? places.map((p) => row({ title: esc(p.title || p.id), sub: esc([kind(p.kind), p.folder, p.single_body ? tt('一次只给一个对话用', 'one chat at a time') : ''].filter(Boolean).join(' · ')),
            marks: mark(p.online === false ? tt('离线', 'offline') : tt('已接上', 'connected'), p.online === false ? 'prop' : 'eff'),
            actions: act(tt('断开', 'Disconnect'), 'computer-disconnect', p.id, { danger: true }) })
            + ctx.setting(`spaces.${p.id}.proactive`, { title: tt(`在“${p.title || p.id}”里自己做事`, `On its own in "${p.title || p.id}"`), about: '' })).join('')
            : empty(tt('还没有接上任何地方', 'Nothing is connected yet'), ''))
        + `<div class="btns">${Object.keys(KIND).map((k) => `<button type="button" class="b" data-act="computer-connect" data-arg="${k}">＋ ${esc(kind(k))}</button>`).join('')}</div>`
        + ctx.group(tt('真实的鼠标键盘', 'The real mouse and keyboard'), ['physical.level', 'physical.idle_seconds', 'physical.yield_on_user_input', 'physical.corner_stop', 'physical.rules', 'physical.max_hold_seconds'])
        + ctx.group(tt('你的其他窗口', 'Your other windows'), ['privacy.level', 'privacy.rules'])
        + ctx.group(tt('新对话在哪里做事', 'Where a new chat works'), ['session.environment', 'computer.mode', 'environments.attach', 'environments.rules'])
        + ctx.group(tt('用电脑时', 'While it uses a computer'), ['computer.monitor', 'computer.step_limit', 'computer.workspaces', 'computer.record_screen', 'computer.max_side'])
        + ctx.group(tt('后台浏览器', 'The background browser'), ['computer.browser_locale', 'computer.browser_windows', 'computer.chromes', 'computer.browser_display', 'computer.browser_area'])
        + ctx.group(tt('它自己的显示器', 'A display of its own'), ['computer.displays', 'computer.vm_image', 'computer.display_backend', 'computer.vm_hypervisor', 'computer.vm_memory', 'computer.vm_cpus', 'computer.vm_accel', 'computer.vm_user'])
}

function connect(what) {
    const d = dialog(`<h5>${tt('接上', 'Connect')} · ${esc(kind(what))}</h5>${what === 'folder' ? `<label><span>${tt('文件夹', 'Folder')}</span><input class="field" data-folder placeholder="~/code/project"></label>` : ''}
<label><span>${tt('名字', 'Title')}</span><input class="field" data-title value="${esc(kind(what))}"></label>
<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn" data-default>${tt('接上', 'Connect')}</button></div>`)
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const folder = d.querySelector('[data-folder]')
        const r = await post('/api/agent/places', { identity: c.id, action: 'connect', kind: what, id: `${what}-${Date.now().toString(36)}`, title: d.querySelector('[data-title]').value, ...(folder ? { folder: folder.value } : {}) })
        if (!r.ok) { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}`; return }
        closeDialog(); toast(tt('已接上', 'Connected'))
        await c.app.refresh(); c.reload()
    })
}

export function actions() {
    on('computer-connect', (n) => connect(n.dataset.arg))
    on('computer-disconnect', async (n) => {
        if (!(await confirm({ title: tt('断开这个地方？', 'Disconnect this place?'), text: tt('它不再在那里做事；那个对话和它的记录留着。', 'It no longer works there; the chat and its record stay.'), yes: tt('断开', 'Disconnect'), danger: true }))) return
        const r = await post('/api/agent/places', { identity: c.id, action: 'disconnect', place: n.dataset.arg })
        if (!r.ok) return said(r)
        await c.app.refresh(); c.reload()
    })
}
