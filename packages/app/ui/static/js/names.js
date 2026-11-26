// What a setting is called on the page: its title, what it is for, and the name of each of
// its choices, in the page's language. Nothing on a settings page shows a raw key or value.
//
// Where a name comes from, first found first:
//   1. the page that shows the setting, when it gives one (a place's own title, for example);
//   2. the host's description of the setting (GET /api/app/settings → schema[section][key]):
//      `title` and `about` as text or {en, zh}, `labels` as {value: text or {en, zh}};
//   3. the tables below, for what the host does not describe yet;
//   4. the key or value made readable ("ask_once_session" → "Ask once session").
import { tt, language } from './i18n.js'

const TITLES = {
    'agent.autostart': ['开机时启动', 'Start at login'],
    'agent.daily_budget': ['每日额度（美元）', 'Daily limit (US$)'],
    'agent.daily_calls': ['没有价格的调用每天上限', 'Calls without a price a day'],
    'agent.keep_days': ['原始对话记录保留天数', 'Days raw chat records are kept'],
    'agent.proactive': ['主动做事', 'Acting on its own'],
    'agent.reserve': ['给你留的部分（美元）', 'Kept for you (US$)'],
    'app.update': ['自动更新', 'Updates'],
    'approvals.ask': ['哪些事要等你批准', 'What waits for your approval'],
    'approvals.programs': ['程序在自己文件夹之外能做什么', 'What programs may do outside their folder'],
    'approvals.timeout_minutes': ['多久没人批准就取消（分钟）', 'Cancel an approval after (minutes)'],
    'general.language': ['语言', 'Language'],
    'general.notifications': ['系统通知', 'System notifications'],
    'general.theme': ['主题', 'Theme'],
    'learning.mode': ['学习', 'Learning'],
    'limits.max_minutes': ['每回合分钟上限', 'Minutes a turn'],
    'limits.max_steps': ['每回合模型调用上限', 'Model calls a turn'],
    'model.reasoning_effort': ['思考强度', 'Reasoning effort'],
    'packages.auto_install': ['自动安装', 'Install automatically'],
    'physical.idle_seconds': ['你离开电脑多久后（秒）', 'Seconds you leave it alone first'],
    'physical.level': ['真实鼠标键盘', 'The real mouse and keyboard'],
}

// What each setting is for, in Chinese (the host's own descriptions are English).
const ABOUT_ZH = {
    'agent.autostart': '开机时启动后台服务，身份在重启后接着生活；以系统里的登录项为准。',
    'agent.daily_budget': '这个身份每天花在模型上的钱（美元），0:00 重置；每次叫醒模型前检查。',
    'agent.daily_calls': '没有价格的模型调用（本机模型、订阅下的 agent）每天最多几次，0:00 重置。',
    'agent.keep_days': '原始对话记录保留几天；学到的东西和摘要不受影响。',
    'agent.proactive': '它自己做事的程度：到时候就做，只为学习，或者只在有事找它时醒。',
    'agent.reserve': '每日额度里留给你的部分（美元）：你的事、点名和批准后的工作用；它自己的事不能用。',
    'approvals.ask': '哪些事等你批准：只是敏感的步骤（凭据、付款、发送、删除、不可撤回的步骤），或者再加上每个程序。',
    'approvals.programs': '程序在自己文件夹之外能做什么（运行命令、联网、写别处的文件）。',
    'approvals.timeout_minutes': '等批准超过这么久没人回答，就算"取消"，不会当成完成。',
    'general.language': '界面和回答用的语言。',
    'general.theme': '界面的亮暗：跟随系统，或固定亮色、暗色。',
    'general.notifications': '只在要你决定或知道的事上发系统通知：等你批准、额度用完、失败或结果不确定、渠道登录过期。',
    'learning.mode': '怎么学：学了马上生效（可撤销）、先等你看过、只用不学，或者不学也不加载学到的。',
    'limits.max_minutes': '每个回合最多做多少分钟。',
    'limits.max_steps': '每个回合最多调用几次模型。',
    'model.reasoning_effort': '模型每次回答前想得多深：越深越慢、越贵。',
    'packages.auto_install': '任务需要的扩展包没装时：自动装官方的、先问你，或者停下并说该装哪个。',
    'physical.idle_seconds': '你离开电脑多久后，它才在你的桌面上操作。',
    'physical.level': '它能不能用你真实的鼠标键盘。',
    'app.update': '应用怎么更新：自动下载、点一下重启更新；只在启动时检查；只在你检查时；或者不更新。',
}

const CHOICES = {
    'agent.proactive': { on: ['到时候就做', 'On'], learn_only: ['只为学习', 'Learning only'], off: ['只在有事找它时醒', 'Off'] },
    'app.update': { default: ['自动下载，点一下再安装', 'Download in the background'], start: ['只在启动时检查', 'Check at start only'], manual: ['只在我检查时', 'Only when I check'], none: ['不更新', 'Never'] },
    'approvals.ask': { sensitive: ['敏感的步骤', 'Sensitive steps'], programs: ['敏感的步骤和每个程序', 'Sensitive steps and every program'] },
    'approvals.programs': { never: ['不允许', 'Never'], ask_each: ['每次都问', 'Ask each time'], ask_once_session: ['每个对话问一次', 'Ask once per chat'], allow: ['允许', 'Allow'] },
    'general.language': { system: ['跟随系统', 'System'], zh: ['中文', '中文'], en: ['English', 'English'] },
    'general.theme': { system: ['跟随系统', 'System'], light: ['亮色', 'Light'], dark: ['暗色', 'Dark'] },
    'learning.mode': { on: ['学了马上生效', 'On'], review_first: ['先等我看过', 'Review first'], frozen: ['只用不学', 'Frozen'], off: ['关', 'Off'] },
    'packages.auto_install': { official: ['自动装官方的', 'Official packages'], ask: ['先问我', 'Ask first'], off: ['不自动装', 'Off'] },
    'physical.level': { never: ['不允许', 'Never'], ask_each: ['每次都问', 'Ask each time'], ask_once_app: ['每个应用问一次', 'Ask once per app'],
        ask_once_session: ['每个对话问一次', 'Ask once per chat'], when_idle: ['我离开时才用', 'When I am away'], allow: ['允许', 'Allow'] },
    // a place's own "acting on its own" (spaces.<place>.proactive)
    'spaces.proactive': { off: ['不主动', 'Not on its own'], learn: ['只学习', 'Learning only'], do: ['学习也做事', 'Learning and doing'] },
}
// values many settings share
const COMMON = { default: ['默认', 'Default'], system: ['跟随系统', 'System'], on: ['开', 'On'], off: ['关', 'Off'], none: ['无', 'None'],
    minimal: ['最浅', 'Minimal'], low: ['浅', 'Low'], medium: ['中', 'Medium'], high: ['深', 'High'], xhigh: ['最深', 'Extra high'], max: ['最深', 'Max'],
    never: ['不允许', 'Never'], allow: ['允许', 'Allow'], ask: ['先问我', 'Ask'] }

const said = (given) => (given && typeof given === 'object' ? given[language()] || given.en || '' : given || '')
const pair = (row) => (row ? tt(row[0], row[1]) : '')
// a_key_like_this → "A key like this"
export const readable = (text) => { const s = String(text ?? '').replace(/[_.]+/g, ' ').trim(); return s ? s.charAt(0).toUpperCase() + s.slice(1) : '' }
// spaces.<place>.proactive is one setting whatever the place
const table = (section, key) => (section === 'spaces' ? 'spaces.proactive' : `${section}.${key}`)

export function settingTitle(section, key, spec = {}, given = '') {
    return given || said(spec.title) || pair(TITLES[table(section, key)]) || readable(key)
}
export function settingAbout(section, key, spec = {}, given) {
    if (given !== undefined && given !== null) return given
    if (spec.about && typeof spec.about === 'object') return said(spec.about)
    return (language() === 'zh' && ABOUT_ZH[table(section, key)]) || spec.about || ''
}
export function choiceLabel(section, key, value, spec = {}) {
    const mine = (spec.labels || {})[value]
    return said(mine) || pair((CHOICES[table(section, key)] || {})[value]) || pair(COMMON[value]) || readable(value)
}
