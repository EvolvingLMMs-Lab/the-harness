// The page's fixed text follows its language: general.language, or the browser's ("system").
// Conversation content is shown as it was written.

let lang = (navigator.language || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en'

export function setLanguage(choice) {
    if (choice === 'zh' || choice === 'en') lang = choice
    else lang = (navigator.language || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en'
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
}
export const language = () => lang
export const tt = (zh, en) => (lang === 'zh' ? zh : en)

export const SECTIONS = [
    ['general', '通用', 'General'], ['model', '模型', 'Model'], ['usage', '用量', 'Usage'],
    ['permissions', '权限与限额', 'Permissions and limits'], ['computer', '电脑', 'Computer'],
    ['personalization', '个性化', 'Personalization'], ['data', '数据', 'Data'], ['about', '关于', 'About'],
]
const ALL_SECTIONS = [...SECTIONS, ['packages', '扩展包', 'Packages'], ['learned', '学到的东西', 'What it learned'], ['connectors', '连接器', 'Connectors']]
export const sectionName = (id) => { const s = ALL_SECTIONS.find((x) => x[0] === id); return s ? tt(s[1], s[2]) : id }

// the five outcomes, the evidence levels and the scopes, as every frontend names them
export const OUTCOME = { done: ['完成', 'done'], refused: ['拒绝', 'refused'], failed: ['失败', 'failed'], cancelled: ['取消', 'cancelled'],
    unknown: ['不确定', 'unknown'], pending: ['进行中', 'in progress'], missed: ['错过', 'missed'] }
export const outcome = (end) => { const o = OUTCOME[end] || OUTCOME.unknown; return tt(o[0], o[1]) }
export const EVIDENCE = { proposed: ['提议', 'proposed', 'prop'], own_test: ['自测通过', 'own test', 'own'], replayed: ['重放通过', 'replayed', 'rep'],
    effective: ['实际有效', 'effective', 'eff'], owner: ['主人添加', 'added by owner', 'owner'], builtin: ['出厂', 'built in', 'builtin'],
    private: ['私人', 'private', 'private'], chat: ['本对话', 'this chat', 'chat'] }
export const evidence = (e) => { const v = EVIDENCE[e]; return v ? { text: tt(v[0], v[1]), cls: v[2] } : { text: e || '—', cls: 'none' } }

export function when(seconds, { day = true } = {}) {
    if (!seconds) return ''
    const d = new Date(seconds * 1000), now = new Date()
    const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    if (d.toDateString() === now.toDateString()) return now - d >= 0 && now - d < 60000 ? tt('刚刚', 'now') : hm
    const y = new Date(now); y.setDate(now.getDate() - 1)
    if (d.toDateString() === y.toDateString()) return tt('昨天', 'yesterday')
    return day ? `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` : hm
}
export const usd = (v) => '$' + (Number(v) || 0).toFixed(2)
export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[m])

// a model id as people read it: deepseek/deepseek-v4.1-flash → DeepSeek V4.1 Flash
const BRANDS = { deepseek: 'DeepSeek', openai: 'OpenAI', gpt: 'GPT', glm: 'GLM', qwen: 'Qwen', claude: 'Claude', gemini: 'Gemini', grok: 'Grok', kimi: 'Kimi' }
export function modelName(id) {
    if (!id) return ''
    return String(id).split('/').pop().split(/[-_:]/).map((w) => BRANDS[w.toLowerCase()] || (/^v?\d/.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1))).join(' ')
}
