// Settings › Data, after Hermes Desktop's profile export and import and ChatGPT's data
// controls: each thing that can be done with an identity's data is a line saying what it does,
// with its button. Sharing shows everything that becomes public before it is sent; a backup
// is encrypted with a passphrase and restored from a file picked here; retiring and deleting
// say what goes and ask first.
import { esc, tt, usd } from '../i18n.js'
import { post, get } from '../api.js'
import { on, dialog, closeDialog, press, toast, row } from '../ui.js'
import { importDialog } from '../onboarding.js'

export const identity = true
let c = null

const line = (title, sub, label, action, danger = false) => row({ title: esc(title), sub: esc(sub), actions: `<button type="button" class="lb${danger ? ' danger' : ''}" data-act="${action}">${esc(label)}</button>` })
const failedIn = (d, r) => { d.querySelector('.res').innerHTML = `<span class="c-failed">✕ ${esc(r.error || tt('没有成功', 'That did not work'))}</span>${r.fix ? `<small class="fix">${esc(r.fix)}</small>` : ''}` }
const buttons = (yes, danger = false) => `<div class="row"><span class="res" role="status"></span><button type="button" class="btn quiet" data-no>${tt('取消', 'Cancel')}</button><button type="button" class="btn${danger ? ' danger' : ''}" data-default>${esc(yes)}</button></div>`

export async function draw(ctx) {
    c = ctx
    return `<p>${tt(`“${ctx.name}”的数据在它自己的文件夹里：`, `The data of "${ctx.name}" is in its own folder: `)}<code>agents/${esc(ctx.id)}/</code></p>`
        + `<div class="lg">${tt('带走', 'Take it along')}</div>`
        + line(tt('分享', 'Share'), tt('人设、技能和反应', 'Persona, skills and reactions'), tt('分享…', 'Share…'), 'data-share')
        + line(tt('角色卡', 'Character card'), tt('名字、人设和头像', 'Name, persona and avatar'), tt('导出…', 'Export…'), 'data-card')
        + line(tt('备份', 'Back up'), tt('整个身份，口令加密', 'The whole identity, encrypted with a passphrase'), tt('备份…', 'Back up…'), 'data-backup')
        + line(tt('恢复', 'Restore'), '', tt('恢复…', 'Restore…'), 'data-restore')
        + line(tt('接过来', 'Bring over'), tt('OpenClaw、Hermes，或别人分享的', 'OpenClaw, Hermes, or one shared with you'), tt('导入…', 'Import…'), 'data-import')
        + `<div class="lg">${tt('保留多久', 'How long things are kept')}</div>` + ctx.setting('agent.keep_days') + ctx.setting('data.keep_days')
        + `<div class="lg">${tt('离开这台电脑', 'Leaving this computer')}</div>`
        + line(tt('在这台电脑上停用', 'Retire on this computer'), tt('这台电脑不再运行它', 'This computer stops running it'), tt('停用…', 'Retire…'), 'data-retire', true)
        + line(tt('删除这个身份', 'Delete this identity'), tt('删掉后找不回来', 'Cannot be brought back'), tt('删除…', 'Delete…'), 'data-delete', true)
}

async function saveTo(name) {
    const a = (await get('/api/app/about', { identity: c.id })) || {}
    return a.save_to ? `${a.save_to}${a.save_to.includes('\\') ? '\\' : '/'}${name}` : name
}

function share() {
    const fixed = [tt('人设', 'Persona'), tt('头像', 'Avatar'), tt('技能', 'Skills'), tt('反应', 'Reactions')]
    const d = dialog(`<h5>${tt('分享', 'Share')} ${esc(c.name)}</h5><div class="checks">${fixed.map((n) => `<span class="ck on fixed">${n}</span>`).join('')}<label class="check"><input type="checkbox" data-memory><span>${tt('也带上记忆', 'Memory too')}</span></label></div>
<div class="pv"><b>${tt('将公开的内容', 'What becomes public')}</b><div data-preview><span class="spin"></span></div></div>

<label><span>${tt('发到', 'Send to')}</span><input class="field" data-to spellcheck="false" placeholder="github:you/${esc(c.id)}-agent"></label>` + buttons(tt('分享', 'Share')))
    d.classList.add('wide')
    const memory = d.querySelector('[data-memory]')
    const preview = async () => {
        const box = d.querySelector('[data-preview]')
        box.innerHTML = '<span class="spin"></span>'
        const r = await post('/api/agent/take', { identity: c.id, action: 'share', preview: true, with_memory: memory.checked })
        if (!d.isConnected) return
        if (!r.ok) { box.innerHTML = `<span class="c-failed">✕ ${esc(r.error)}</span>`; return }
        const p = r.data || {}
        const names = (list) => (list || []).map((x) => (typeof x === 'string' ? x : x.name || x.file || '')).filter(Boolean)
        box.innerHTML = [[tt('文字', 'Texts'), (p.texts || []).map((t) => String(t.file || '').split('/').slice(2).join('/') || t.file)], [tt('技能', 'Skills'), names(p.skills)], [tt('反应', 'Reactions'), names(p.reactions)],
            [tt('其他文件', 'Other files'), (p.other_files || []).map((f) => String(f).split('/').slice(2).join('/'))], [tt('留在这里、不带的', 'Left here'), p.left_out || []]]
            .filter(([, list]) => list.length).map(([name, list]) => `<div><i>${esc(name)}</i> ${list.map(esc).join(' · ')}</div>`).join('')
            + (Object.keys(p.replaced || {}).length ? `<div>${tt('群和人的名字换成了占位符。', 'Names of groups and people are replaced with placeholders.')}</div>` : '')
    }
    memory.onchange = preview
    preview()
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const to = d.querySelector('[data-to]').value.trim()
        if (!to) { failedIn(d, { error: tt('先填发到哪里。', 'Say where to send it first.'), fix: tt('一个 GitHub 仓库（github:你/名字）或者一个文件夹。', 'A GitHub repository (github:you/name) or a folder.') }); return }
        const r = await post('/api/agent/take', { identity: c.id, action: 'share', to, with_memory: memory.checked })
        if (!r.ok) return failedIn(d, r)
        d.querySelector('.res').innerHTML = `<span class="c-done">✓ ${esc(r.data.sent || r.data.link || tt('已发出', 'sent'))}</span>`
    })
}

async function card() {
    const d = dialog(`<h5>${tt('导出角色卡', 'Export a character card')}</h5><p class="note">${tt('.json：纯文字的卡；.png：放进头像图片里（要先有头像）', '.json: a card of text; .png: inside the avatar picture (it needs an avatar)')}</p>
<label><span>${tt('存到', 'Save to')}</span><input class="field" data-path spellcheck="false" value="${esc(await saveTo(`${c.id}.card.json`))}"></label>` + buttons(tt('导出', 'Export')))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await post('/api/agent/take', { identity: c.id, action: 'card', path: d.querySelector('[data-path]').value })
        if (!r.ok) return failedIn(d, r)
        closeDialog(); toast(tt(`已导出到 ${r.data.sent || r.data.path || ''}`, `Exported to ${r.data.sent || r.data.path || ''}`))
    })
}

async function backup() {
    const d = dialog(`<h5>${tt('备份', 'Back up')} ${esc(c.name)}</h5><p class="note warn">${tt('口令丢了就恢复不了。', 'Without the passphrase it cannot be restored.')}</p>
<label><span>${tt('口令', 'Passphrase')}</span><input class="field" data-pass type="password" autocomplete="new-password"></label>
<label><span>${tt('再输一次', 'Once more')}</span><input class="field" data-again type="password" autocomplete="new-password"></label>
<label><span>${tt('存到', 'Save to')}</span><input class="field" data-path spellcheck="false" value="${esc(await saveTo(`${c.id}.harness-backup`))}"></label>
<label class="check"><input type="checkbox" data-keys><span>${tt('带上模型的 key', 'Include the model keys')}</span></label>` + buttons(tt('备份', 'Back up')))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const pass = d.querySelector('[data-pass]').value
        if (!pass) return failedIn(d, { error: tt('先填口令。', 'Give a passphrase first.') })
        if (pass !== d.querySelector('[data-again]').value) return failedIn(d, { error: tt('两次输入的口令不一样。', 'The two passphrases differ.') })
        const r = await post('/api/agent/take', { identity: c.id, action: 'backup', path: d.querySelector('[data-path]').value, passphrase: pass, with_keys: d.querySelector('[data-keys]').checked })
        if (!r.ok) return failedIn(d, r)
        closeDialog(); toast(tt('已备份。在新电脑上恢复后要重新登录渠道。', 'Backed up. After restoring on the new computer, log in to channels again.'))
    })
}

// Restore from a file picked here: its bytes go to the host with the passphrase. The host
// checks the passphrase before it touches anything; an identity of the same id that is
// already here is replaced only after the owner says so (the one that was here is kept aside).
function restore() {
    const d = dialog(`<h5>${tt('恢复', 'Restore')}</h5>
<label><span>${tt('备份文件', 'Backup file')}</span><input class="field" data-file type="file" accept=".harness-backup,application/octet-stream"></label>
<label><span>${tt('口令', 'Passphrase')}</span><input class="field" data-pass type="password" autocomplete="off"></label>` + buttons(tt('恢复', 'Restore')))
    const main = d.querySelector('[data-default]'), picked = d.querySelector('[data-file]'), phrase = d.querySelector('[data-pass]')
    let replace = false
    const again = () => { replace = false; main.textContent = tt('恢复', 'Restore'); main.classList.remove('danger') }
    picked.onchange = again; phrase.oninput = again
    d.querySelector('[data-no]').onclick = closeDialog
    press(main, async () => {
        const file = picked.files[0], pass = phrase.value
        if (!file) return failedIn(d, { error: tt('先选备份文件。', 'Pick the backup file first.') })
        if (!pass) return failedIn(d, { error: tt('先填口令。', 'Give the passphrase first.') })
        d.querySelector('.res').innerHTML = `<span class="spin"></span>${tt('正在恢复…', 'restoring…')}`
        const data = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(String(reader.result).split(',')[1] || ''); reader.onerror = () => fail(reader.error); reader.readAsDataURL(file) }).catch(() => null)
        if (data === null) return failedIn(d, { error: tt('这个文件读不出来。', 'This file could not be read.') })
        const r = await post('/api/agent/take', { action: 'restore', name: file.name, data, passphrase: pass, replace })
        if (!r.ok) {
            failedIn(d, r)
            if (r.code === 'identity_exists') { replace = true; main.textContent = tt('替换这里的那个', 'Replace the one here'); main.classList.add('danger') } // pressing again says yes
            else if (r.code === 'backup_passphrase') { phrase.focus(); phrase.select() }
            else if (r.code === 'not_backup' || r.code === 'backup_data') picked.focus()
            return
        }
        const got = r.data || {}, name = got.name || got.identity || ''
        closeDialog()
        toast(tt(`已恢复“${name}”。`, `Restored "${name}".`) + ((got.channels || []).length ? ' ' + tt(`这些渠道账号要重新登录：${got.channels.join('、')}`, `Log in again to: ${got.channels.join(', ')}`) : ''))
        await c.app.reloadIdentities(); c.reload()
    })
}

function retire() {
    const d = dialog(`<h5>${tt('在这台电脑上停用', 'Retire on this computer')} · ${esc(c.name)}</h5><p class="note warn">${tt('这台电脑不再运行它；数据留着。', 'This computer stops running it; its data stays.')}</p>` + buttons(tt('停用', 'Retire'), true))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await post('/api/agent/take', { identity: c.id, action: 'retire' })
        if (!r.ok) return failedIn(d, r)
        closeDialog(); toast(tt('已停用', 'Retired')); c.app.refresh()
    })
}

// Deleting says what goes with it first: its chats, its channels and what it spent.
async function remove() {
    const d = dialog(`<h5>${tt('删除身份', 'Delete the identity')} ${esc(c.name)}</h5><div data-goes><span class="spin"></span>${tt('正在数它有什么…', 'counting what it has…')}</div>
<p class="note warn">${tt('这些连同它的记忆、技能和私钥都会删掉，找不回来。', 'These go with its memory, skills and private key, and cannot be brought back.')}</p>
<label><span>${tt('输入它的 id 确认', 'Type its id to confirm')}</span><input class="field" data-confirm spellcheck="false" placeholder="${esc(c.id)}"></label>` + buttons(tt('删除', 'Delete'), true))
    d.querySelector('[data-no]').onclick = closeDialog
    d.querySelector('[data-no]').focus()
    const [chats, channels, usage] = await Promise.all([get('/api/agent/chats', { identity: c.id }), get('/api/agent/channels', { identity: c.id }), get('/api/agent/usage', { identity: c.id, range: 'month' })])
    if (!d.isConnected) return
    const n = ((chats && chats.chats) || []).length, accounts = ((channels && channels.channels) || [])
    d.querySelector('[data-goes]').innerHTML = `<ul class="goes"><li>${tt(`${n} 个对话和它们的记录`, `${n} chat${n === 1 ? '' : 's'} and their records`)}</li>`
        + `<li>${accounts.length ? tt(`${accounts.length} 个渠道账号：`, `${accounts.length} channel account${accounts.length === 1 ? '' : 's'}: `) + accounts.map((a) => esc(a.title || a.account)).join(tt('、', ', ')) : tt('没有渠道账号', 'no channel accounts')}</li>`
        + `<li>${tt(`最近 30 天花了 ${usd((usage || {}).cost_usd)}（记录一起删）`, `${usd((usage || {}).cost_usd)} spent in the last 30 days (the record goes too)`)}</li></ul>`
    press(d.querySelector('[data-default]'), async () => {
        if (d.querySelector('[data-confirm]').value.trim() !== c.id) return failedIn(d, { error: tt(`输入 ${c.id} 才能删除。`, `Type ${c.id} to delete it.`) })
        const r = await post('/api/agent/identity', { action: 'delete', id: c.id })
        if (!r.ok) return failedIn(d, r)
        closeDialog(); toast(tt(`已删除 ${c.id}`, `Deleted ${c.id}`))
        await c.app.identityGone(c.id)
    })
}

export function actions(app) {
    on('data-share', share)
    on('data-card', card)
    on('data-backup', backup)
    on('data-restore', restore)
    on('data-import', () => importDialog(app))
    on('data-retire', retire)
    on('data-delete', remove)
}
