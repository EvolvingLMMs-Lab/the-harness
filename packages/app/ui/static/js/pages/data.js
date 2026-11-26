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
        + line(tt('分享', 'Share'), tt('把人设、技能和反应发给别人领养；发出去之前列出会公开的全部内容。私钥和凭据永远不带。', 'Send persona, skills and reactions for someone to adopt; everything that becomes public is listed first. The private key and credentials never go.'), tt('分享…', 'Share…'), 'data-share')
        + line(tt('角色卡', 'Character card'), tt('只带名字、人设和头像（Character Card V3）。', 'Only the name, persona and avatar (Character Card V3).'), tt('导出…', 'Export…'), 'data-card')
        + line(tt('备份', 'Back up'), tt('整个身份，含私钥、记忆和渠道凭据，用口令加密成一个文件。', 'The whole identity with its private key, memory and channel credentials, encrypted with a passphrase into one file.'), tt('备份…', 'Back up…'), 'data-backup')
        + line(tt('恢复', 'Restore'), tt('从一个备份文件恢复一个身份（换电脑之后）。', 'Bring an identity back from a backup file (after moving to another computer).'), tt('恢复…', 'Restore…'), 'data-restore')
        + line(tt('接过来', 'Bring over'), tt('从 OpenClaw 或 Hermes 导入，或者领养别人分享的身份、文件或角色卡。', 'Import from OpenClaw or Hermes, or adopt an identity, a file or a character card someone shared.'), tt('导入…', 'Import…'), 'data-import')
        + `<div class="lg">${tt('保留多久', 'How long things are kept')}</div>` + ctx.setting('agent.keep_days') + ctx.setting('data.keep_days')
        + `<div class="lg">${tt('离开这台电脑', 'Leaving this computer')}</div>`
        + line(tt('在这台电脑上停用', 'Retire on this computer'), tt('搬到另一台电脑并在那里恢复之后做：这台电脑不再运行它。', 'After it was restored on another computer: this computer no longer runs it.'), tt('停用…', 'Retire…'), 'data-retire', true)
        + line(tt('删除这个身份', 'Delete this identity'), tt('它的对话、记忆、技能和私钥都删掉，找不回来。', 'Its chats, memory, skills and private key are deleted for good.'), tt('删除…', 'Delete…'), 'data-delete', true)
}

async function saveTo(name) {
    const a = (await get('/api/app/about', { identity: c.id })) || {}
    return a.save_to ? `${a.save_to}${a.save_to.includes('\\') ? '\\' : '/'}${name}` : name
}

function share() {
    const fixed = [tt('人设', 'Persona'), tt('头像', 'Avatar'), tt('技能', 'Skills'), tt('反应', 'Reactions')]
    const d = dialog(`<h5>${tt('分享', 'Share')} ${esc(c.name)}</h5><div class="checks">${fixed.map((n) => `<span class="ck on fixed">${n}</span>`).join('')}<label class="check"><input type="checkbox" data-memory><span>${tt('也带上记忆', 'Memory too')}</span></label></div>
<div class="pv"><b>${tt('将公开的内容', 'What becomes public')}</b><div data-preview><span class="spin"></span></div></div>
<p class="note">${tt('私钥和凭据永远不带。领养的人得到一个新身份和新密钥。', 'The private key and credentials never go. Whoever adopts it gets a new identity and a new key.')}</p>
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
    const d = dialog(`<h5>${tt('导出角色卡', 'Export a character card')}</h5><p class="note">${tt('只带名字、人设和头像（Character Card V3）。文件名以 .json 结尾是一张纯文字的卡；以 .png 结尾是把卡放进头像图片里（要先有头像）。', 'Only the name, persona and avatar (Character Card V3). A name ending in .json is a card of text alone; one ending in .png puts the card inside the avatar picture (it needs an avatar first).')}</p>
<label><span>${tt('存到', 'Save to')}</span><input class="field" data-path spellcheck="false" value="${esc(await saveTo(`${c.id}.card.json`))}"></label>` + buttons(tt('导出', 'Export')))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const r = await post('/api/agent/take', { identity: c.id, action: 'card', path: d.querySelector('[data-path]').value })
        if (!r.ok) return failedIn(d, r)
        closeDialog(); toast(tt(`已导出到 ${r.data.sent || r.data.path || ''}`, `Exported to ${r.data.sent || r.data.path || ''}`))
    })
}

async function backup() {
    const d = dialog(`<h5>${tt('备份', 'Back up')} ${esc(c.name)}</h5><p class="note warn">${tt('备份含私钥、记忆和这个身份的渠道凭据，用口令加密。口令丢了就恢复不了。', "The backup holds the private key, memory and this identity's channel credentials, encrypted with a passphrase. Without the passphrase it cannot be restored.")}</p>
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

// Restore from a file picked here: its bytes go to the host with the passphrase.
function restore() {
    const d = dialog(`<h5>${tt('恢复', 'Restore')}</h5><p class="note">${tt('选一个备份文件，输入备份时的口令。恢复出来的是原来的那个身份（同一个 id、同一把密钥）；之后重新登录渠道，再在旧电脑上"停用"。', 'Pick a backup file and give the passphrase it was made with. What comes back is the same identity (the same id and key); afterwards log in to channels again, then retire it on the old computer.')}</p>
<label><span>${tt('备份文件', 'Backup file')}</span><input class="field" data-file type="file" accept=".harness-backup,application/octet-stream"></label>
<label><span>${tt('口令', 'Passphrase')}</span><input class="field" data-pass type="password" autocomplete="off"></label>
<label class="check"><input type="checkbox" data-replace><span>${tt('这里已有同一个 id 的身份时替换它（原来的留在旁边）', 'Replace an identity of the same id here (the one that was here is kept beside it)')}</span></label>` + buttons(tt('恢复', 'Restore')))
    d.querySelector('[data-no]').onclick = closeDialog
    press(d.querySelector('[data-default]'), async () => {
        const file = d.querySelector('[data-file]').files[0], pass = d.querySelector('[data-pass]').value
        if (!file) return failedIn(d, { error: tt('先选备份文件。', 'Pick the backup file first.') })
        if (!pass) return failedIn(d, { error: tt('先填口令。', 'Give the passphrase first.') })
        d.querySelector('.res').innerHTML = `<span class="spin"></span>${tt('正在恢复…', 'restoring…')}`
        const data = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(String(reader.result).split(',')[1] || ''); reader.onerror = () => fail(reader.error); reader.readAsDataURL(file) }).catch(() => null)
        if (data === null) return failedIn(d, { error: tt('这个文件读不出来。', 'This file could not be read.') })
        const r = await post('/api/agent/take', { action: 'restore', name: file.name, data, passphrase: pass, replace: d.querySelector('[data-replace]').checked })
        // refused without a way out (a host that takes no file from the page): the terminal restores the same file
        if (!r.ok) return failedIn(d, r.fix ? r : { ...r, fix: tt('在终端里运行 harness agent restore 加这个文件的路径，可以恢复同一个备份。', 'harness agent restore with the path of this file, in a terminal, restores the same backup.') })
        closeDialog(); toast(tt(`已恢复 ${r.data.identity || r.data.id || ''}`, `Restored ${r.data.identity || r.data.id || ''}`))
        await c.app.reloadIdentities(); c.reload()
    })
}

function retire() {
    const d = dialog(`<h5>${tt('在这台电脑上停用', 'Retire on this computer')} · ${esc(c.name)}</h5><p class="note warn">${tt('搬到另一台电脑并在那里恢复之后再做：这台电脑不再运行它，打开时会提示它已搬走。数据留着。', 'Do this after it was restored on another computer: this computer no longer runs it, and opening it here says it has moved. Its data stays.')}</p>` + buttons(tt('停用', 'Retire'), true))
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
<p class="note warn">${tt('这些连同它的记忆、技能和私钥都会删掉，找不回来。想留一份就先备份。', 'These go with its memory, skills and private key, for good. Back it up first to keep a copy.')}</p>
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
