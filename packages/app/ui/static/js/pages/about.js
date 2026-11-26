// Settings › About, after Hermes Desktop's About: the version, the identity and its key's
// fingerprint, which `harness` a terminal on this computer runs, and updates.
import { esc, tt } from '../i18n.js'
import { failed } from '../api.js'
import { row, problem, ic } from '../ui.js'
import * as update from '../update.js'

export const identity = true
let looks = 0 // how often the page asked again for the terminal's command

export async function draw(ctx) {
    const a = await ctx.get('/api/app/about', { identity: ctx.id })
    if (!a) return problem(failed.get('/api/app/about'), { title: tt('这一页没有读出来', 'This page could not be read'), retry: 'settings' })
    const fact = (label, value, more = '') => row({ title: esc(label), actions: `<span class="fv">${esc(value || '—')}</span>${more}` })
    const copy = (text) => (text ? ic('copy', tt('复制', 'Copy'), { act: 'copy-text', attrs: `data-arg="${esc(text)}"` }) : '')
    // which harness a terminal runs: the host looks it up in the background, so the first answer may have none yet
    const command = a.command
    const terminal = command === undefined ? ''
        : command === null ? (looks < 4 ? fact(tt('终端里的 harness', 'harness in a terminal'), tt('正在查…', 'looking…')) : '')
            : fact(tt('终端里的 harness', 'harness in a terminal'), command.path ? `${command.path}${command.version ? ` · ${command.version}` : ''}` : tt('PATH 上没有 harness', 'no harness on the PATH'), copy(command.path))
            + (command.mine === false || !command.path ? `<div class="warnline" role="alert">${esc(command.mine === false && command.path ? tt('终端用的是另一份安装，它和这个应用共用同一份数据。', 'A terminal runs another install, which shares its data with this app.') : tt('终端里敲 harness 找不到这个应用的命令。', 'Typing harness in a terminal does not find this app’s command.'))} ${esc(command.fix || '')}</div>` : '')
    return `<div class="lg">The Harness</div>` + fact(tt('版本', 'Version'), a.version) + terminal
        + `<div class="lg">${tt('身份', 'Identity')}</div>` + fact(tt('显示名', 'Display name'), a.name || ctx.name) + fact('id', a.identity || ctx.id)
        + fact(tt('文件夹', 'Folder'), a.folder, copy(a.folder)) + fact(tt('密钥指纹', 'Key fingerprint'), a.fingerprint, copy(a.fingerprint))
        + `<p>${tt('私钥只在这台电脑上，永远不进分享。', 'The private key stays on this computer and never goes into a share.')}</p>`
        + await update.about(ctx.app, (name) => ctx.setting(name))
        + (command === null && looks < 4 ? '<span data-looking hidden></span>' : '')
}

// The host looks the terminal's command up in the background: ask again in a moment.
export function wire(ctx, pane) {
    // a host that never finds it (no desktop shell beside it) stops being asked, and the line goes
    if (!pane.querySelector('[data-looking]')) return
    looks++
    setTimeout(() => { if (ctx.app.section === 'about') ctx.reload() }, 2500)
}
