// Settings › General, after Hermes Desktop's Appearance, Chat and Advanced: how the app looks
// and speaks, what it notifies about, how the chat shows thinking, and whether it stays on.
import { tt } from '../i18n.js'
import { toggle, flash } from '../ui.js'
import { prefs } from '../prefs.js'

export const identity = false

export async function draw(ctx) {
    return `<p>${tt('它是常驻在这台电脑上的服务：关掉窗口它也照常工作，托盘里能暂停或退出。', 'It is a resident service on this computer: it keeps working with the window closed; the tray pauses or quits it.')}</p>`
        + `<div class="lg">${tt('外观', 'Appearance')}</div>` + ctx.setting('general.language') + ctx.setting('general.theme')
        + `<div class="lg">${tt('对话', 'Chat')}</div>`
        + `<div class="sr" data-thinking><div><b id="sr-thinking">${tt('显示思考内容', 'Show thinking')}</b><small>${tt('模型回答前想的内容显示在回答上方，可以展开；关掉后只显示回答。这是这个窗口自己的偏好。', "What the model thought before answering shows above its answer, to open; off shows answers only. It is this window's own preference.")}</small></div><div class="ctl">${toggle(prefs.get('thinking.show', true), tt('显示思考内容', 'Show thinking'))}</div></div>`
        + `<div class="lg">${tt('通知', 'Notifications')}</div>` + ctx.setting('general.notifications')
        + `<p>${tt('系统通知只用于要你决定或知道的事：批准请求、额度用完、失败或不确定的动作、渠道登录过期。', 'System notifications are only for what you must decide or know: approval requests, the limit reached, actions that failed or ended unknown, an expired channel login.')}</p>`
        + `<div class="lg">${tt('启动', 'Starting')}</div>` + ctx.setting('agent.autostart') + ctx.setting('general.open_browser')
        + ctx.group(tt('终端里的对话', 'The terminal chat'), ['terminal.editor_mode'])
}

export function wire(ctx, pane) {
    const think = pane.querySelector('[data-thinking] .tog')
    think.onclick = () => {
        const shown = !think.classList.contains('on')
        think.classList.toggle('on', shown); think.setAttribute('aria-checked', shown ? 'true' : 'false')
        ctx.app.showThinking(shown)
        flash(think.parentElement, tt('已保存', 'Saved'))
    }
}
