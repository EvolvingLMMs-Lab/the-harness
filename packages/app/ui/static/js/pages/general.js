// Settings › General, after Hermes Desktop's Appearance, Chat and Advanced: how the app looks
// and speaks, what it notifies about, how the chat shows thinking, and whether it stays on.
import { tt } from '../i18n.js'
import { toggle, flash } from '../ui.js'
import { prefs } from '../prefs.js'

export const identity = false

export async function draw(ctx) {
    return ``
        + `<div class="lg">${tt('外观', 'Appearance')}</div>` + ctx.setting('general.language') + ctx.setting('general.theme')
        + `<div class="lg">${tt('对话', 'Chat')}</div>`
        + `<div class="sr" data-thinking><div><b id="sr-thinking">${tt('显示思考内容', 'Show thinking')}</b></div><div class="ctl">${toggle(prefs.get('thinking.show', true), tt('显示思考内容', 'Show thinking'))}</div></div>`
        + `<div class="lg">${tt('通知', 'Notifications')}</div>` + ctx.setting('general.notifications')
        + ``
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
