const params=new URLSearchParams(location.search);
const zh=location.pathname.startsWith('/zh-cn')||document.documentElement.lang.startsWith('zh');
const L=(en,cn)=>zh?cn:en;
const docs=zh?'/docs/zh-cn/':'/docs/';
const systemTheme=()=>matchMedia('(prefers-color-scheme: light)').matches?'day':'night';
function readTheme(){
  try{
    const stored=localStorage.getItem('starlight-theme');
    if(stored!==null)return stored==='light'?'day':stored==='dark'?'night':systemTheme();
    const legacy=localStorage.getItem('harness-theme');
    if(legacy==='day'||legacy==='night'){
      localStorage.setItem('starlight-theme',legacy==='day'?'light':'dark');
      return legacy;
    }
  }catch{}
  const query=params.get('theme');
  return query?(['day','pearl','yellow','blue'].includes(query)?'day':'night'):systemTheme();
}
let theme=readTheme();
document.body.className=theme==='day'?'pearl':'midnight';
document.documentElement.dataset.theme=theme==='day'?'light':'dark';
const repo='https://github.com/EvolvingLMMs-Lab/the-harness';
const ext='target="_blank" rel="noopener"';
// npm package name reserved for the upcoming release.
const installCommands={npm:'npm install -g @lmmslab/harness',pip:'pip install the-harness'};
let installMethod='npm';
const arrow='<span aria-hidden="true">↗</span>';
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// The archive marks every framed panel shares: a fine registration frame with scan
// lines, the cyan register corner, the right-hand index rail and the barcode.
const archiveOverlay='<div class="archive-overlay" aria-hidden="true"><span class="archive-scan"></span><span class="archive-axis"></span><span class="archive-register"></span><span class="archive-barcode"></span><span class="archive-index"><i></i><i></i><i></i><i></i></span></div>';
// A screenshot is framed as a capture: four corner brackets, the last one magenta.
const captureMarks='<span class="capture-marks" aria-hidden="true"><i></i><i></i><i></i><i></i></span>';
// The end of a block of copy: a short rule with the magenta tick on the right.
const archiveEnd='<span class="archive-end" aria-hidden="true"></span>';
// The section's place in the page, as an index rail with the current square lit.
const sectionIndex=n=>`<span class="section-index" aria-hidden="true">${[0,1,2].map(i=>`<i${i===n?' class="on"':''}></i>`).join('')}</span>`;
// The same edited clock drives the recording and its trace-derived timeline.
const demoFigure=id=>HarnessDemos.figure(id,{zh,overlay:archiveOverlay});

const stackPaths='<path d="M0 22 18 31 36 22"/><path d="M0 13 18 22 36 13"/><path d="M18 -5 36 4 18 13 0 4Z" class="fill"/>';
// What each integration connects to, as logos the reader recognises at a glance; the
// arrow says who calls whom. Logos come from logos.js, drawn in the text colour.
// The lists are examples, so each ends with a tile that leads to the full guide.
const logoTile=([key,name])=>`<li><span class="logo">${(window.HARNESS_LOGOS||{})[key]||''}</span><span class="logo-name">${esc(name)}</span></li>`;
function logoFigure(x){
  return`<div class="extend-flow"><span class="extend-hub"><svg viewBox="-2 -7 40 40" aria-hidden="true"><g class="d-stack">${stackPaths}</g></svg>The Harness</span><span class="extend-arrow ${x.dir}" aria-hidden="true"><i></i></span><span class="extend-kind">${x.tab}</span></div><ul class="logo-grid" aria-label="${esc(x.logos.map(l=>l[1]).join(', '))}">${x.logos.map(logoTile).join('')}<li class="more"><a href="${x.link[1]}"><span class="logo" aria-hidden="true">+</span><span class="logo-name">${L('More','更多')}</span></a></li></ul>`;
}

const extensions=[
// Most asked first: the apps people work in, what it acts on, the model; then MCP, agents, policies.
// A product is listed once: editors and desktop apps under Apps, coding and other agents under Agents.
  {id:'apps',tab:L('Apps','应用'),
   text:L('Call it from the app you already work in. It runs as an MCP server, and every task it takes is a session you can watch, steer and approve.','在你常用的应用里直接调用它。它作为 MCP 服务器运行，接下的每个任务都是一个会话，你可以查看、引导和审批。'),
   logos:[['cursor','Cursor'],['zed','Zed'],['openai','ChatGPT'],['claude','Claude'],['mcp',L('Any MCP client','任意 MCP 客户端')]],dir:'in',
   code:`harness install mcp-server
<span># Cursor: .cursor/mcp.json</span>
{"mcpServers": {"harness": {"command": "harness", "args": ["mcp"]}}}`,
   link:[L('Use it from an app','在应用里使用'),`${docs}extend/integrations/${L('#apps','#应用')}`]},
  {id:'tasks',tab:L('Any task','任意任务'),
   text:L('The same few calls wherever it acts. Each environment is a package that installs itself the first time a task needs it.','无论在哪里行动，都是同样几个调用。每个环境都是一个包，任务第一次用到时自动安装。'),
   logos:[['apple','macOS'],['windows','Windows'],['linux','Linux'],['bash',L('Terminal','终端')],['chrome',L('Browser','浏览器')],['cube','Minecraft'],['robot',L('Robots','机器人')]],dir:'out',
   code:`click(550, 224)
type_text("=B2+C2")
press("enter")`,
   link:[L('Packages and environments','包与环境'),`${docs}configure/packages/`]},
  {id:'models',tab:L('Any model','任意模型'),
   text:L('Hosted models through OpenRouter, OpenAI, Anthropic, Gemini, DeepSeek, Qwen and more, or one you serve yourself. Switching is one line.','通过 OpenRouter、OpenAI、Anthropic、Gemini、DeepSeek、Qwen 等使用托管模型，或者用你自己部署的模型。换模型只改一行。'),
   logos:[['openrouter','OpenRouter'],['openai','OpenAI'],['claude','Claude'],['gemini','Gemini'],['deepseek','DeepSeek'],['qwen','Qwen'],['grok','Grok'],['kimi','Kimi'],['glm','GLM'],['ollama','Ollama'],['vllm','vLLM']],dir:'out',
   code:`[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"`,
   link:[L('Choose a model','选择模型'),`${docs}configure/models/`]},
  {id:'mcp',tab:L('MCP servers','MCP 服务器'),
   text:L('Give it the tools of any MCP server: a desktop, a browser, GitHub, your own service. Every grant is explicit, and it is checked again before each call.','把任意 MCP 服务器的工具交给它：桌面、浏览器、GitHub，或者你自己的服务。每项授权都要明确给出，每次调用前都会再核对一次。'),
   logos:[['mcp',L('Any MCP server','任意 MCP 服务器')],['desktop','agent-desktop'],['github','GitHub'],['notion','Notion'],['figma','Figma'],['linear','Linear']],dir:'out',
   code:`<span># ~/.harness/config.toml</span>
[[connectors]]
id = "desktop"
transport = "stdio"
command = "agent-desktop"
args = ["mcp"]
allowed_tools = ["*"]`,
   link:[L('Connect an MCP server','接入 MCP 服务器'),`${docs}extend/integrations/${L('#mcp-servers','#mcp-服务器')}`]},
  {id:'agents',tab:L('Agents','Agent'),
   text:L('Coding agents and others. Call The Harness from one, or run one inside a session in a terminal of its own; either way its work lands on the same timeline.','Coding agent 和其他 agent 都可以。从它那里调用 The Harness，或者把它放进一个会话、在它自己的终端里运行；两种方式，它做的事都记在同一条时间线上。'),
   logos:[['claudecode','Claude Code'],['codex','Codex'],['opencode','OpenCode'],['pi','Pi'],['hermes','Hermes Agent'],['openclaw','OpenClaw'],['acp',L('ACP agents','ACP agent')]],dir:'both',
   code:`<span># it calls The Harness</span>
claude mcp add harness -- harness mcp
<span># The Harness runs it</span>
harness agents add --terminal hermes -- hermes chat
harness --agent terminal:hermes --folder .`,
   link:[L('Work with another agent','与其他 agent 协作'),`${docs}extend/integrations/${L('#agents','#agent')}`]},
  {id:'policies',tab:L('Any policy','任意策略'),
   text:L('Where code cannot express a motion, a program hands control to a learned policy for a bounded run, then checks what it did.','代码表达不了的动作，程序交给学习型策略执行一段有边界的运行，再检查它做了什么。'),
   logos:[['policy','VLA'],['world','WAM'],['diffusion',L('Diffusion policy','扩散策略')],['rl',L('RL policy','强化学习策略')],['pytorch','PyTorch'],['http',L('HTTP server','HTTP 服务')],['plug',L('Your adapter','你的适配器')]],dir:'out',
   code:`<span># in a program</span>
trace = run_policy("pi05", max_seconds=8)
print(trace.event.kind)`,
   link:[L('Add a learned policy','加入学习型策略'),`${docs}extend/integrations/${L('#learned-policies','#学习型策略')}`]},
];

const layers=[
  [3,L('At decision points','在决策点'),L('Language model','语言模型'),L('Plans and writes programs at decision points, and thinks while they run. Swap the model in one line of configuration.','在决策点规划、写程序，程序运行时也在思考。换模型只改一行配置。'),`${docs}concepts/harness/`],
  [2,L('While a program runs','程序运行期间'),L('Programs','程序'),L('Programs compose skills and tools; a learned policy takes over what code cannot express.','程序组合 skill 和工具；代码表达不了的部分，交给学习型策略。'),`${docs}extend/skills/`],
  [1,L('Every control step','每个控制步'),L('Reflexes','反射'),L('Guards and controllers the model writes run on every control step, so a slip is caught before the model hears of it.','模型写的 guard 和控制器在每个控制步运行，偏差在模型知道之前就被接住。'),`${docs}extend/reactive-rules/`],
  [0,L('Before every command','每条命令执行前'),L('Safety layer','安全层'),L('Every command passes limits that nothing learns or rewrites, whoever wrote it.','每条命令都要经过一组不会被学习、也不会被改写的限制，不管它是谁写的。'),L(`${docs}concepts/harness/#four-layers`,`${docs}concepts/harness/#四层结构`)],
];

const features=[
  {id:'run-continuously',title:L('Runs continuously','自动运行'),
   text:L('Sensing and acting carry on while the model considers what comes next.','模型考虑下一步的时候，感知和行动照常进行。'),
   link:[L('The continuous control loop','持续运行的控制循环'),L(`${docs}concepts/harness/#runs-continuously`,`${docs}concepts/harness/#自动运行`)],
   figure:demoFigure('run-continuously')},
  {id:'one-call',title:L('One call, many actions','一次调用，多个动作'),
   text:L('One call returns a program: a run of actions with checks of its own.','一次调用拿到一段程序：一串动作，自带检查。'),
   link:[L('Automatic Control','自主控制'),`${docs}concepts/harness/`],figure:demoFigure('one-call')},
  {id:'think-while-acting',title:L('Thinks while it acts','边想边做'),
   text:L('The next decision is worked out while the current program runs, and a message from you reaches it at once.','当前程序运行的同时，下一个决定已经在想；你发来的消息，它马上就能收到。'),
   link:[L('Thinking while acting','边想边做'),L(`${docs}concepts/harness/#thinking-while-acting`,`${docs}concepts/harness/#边想边做`)],
   figure:demoFigure('think-while-acting')},
  {id:'learn-while-working',title:L('Learns while it works','边做边学'),
   text:L('A skill joins the library once its own test passes, and the same run can use it.','skill 通过自己的测试就加入库，同一次运行里就能用上。'),
   link:[L('Learn while it works','边做边学'),`${docs}learn/while-working/`],
   figure:demoFigure('learn-while-working')},
];
const stageBlock=(id,label,items,cls='')=>`<div class="stage${cls?' '+cls:''}" data-stage><div class="stage-list" role="tablist" aria-orientation="vertical" aria-label="${label}">${items.map((f,i)=>`<div class="stage-item${i?'':' on'}"><i class="stage-progress" aria-hidden="true"></i><h3><button type="button" role="tab" id="${id}-tab-${f.id}" aria-controls="${id}-${f.id}" aria-selected="${i===0}" tabindex="${i===0?0:-1}">${f.title}${f.note?` <span>${f.note}</span>`:''}</button></h3><div class="stage-detail"><p>${f.text}</p>${f.extra||''}${f.link?`<a class="text-link" href="${f.link[1]}">${f.link[0]} ${arrow}</a>`:''}</div></div>`).join('')}</div><div class="stage-screen">${items.map((f,i)=>`<div class="stage-panel${i?'':' on'}" id="${id}-${f.id}" role="tabpanel" aria-labelledby="${id}-tab-${f.id}">${f.figure}</div>`).join('')}</div></div>`;
const inputs=[
  {id:'computer',title:L('Computer use','电脑操作'),note:L('with agent-desktop','搭配 agent-desktop'),
   text:L('It works from the screen and from what the system reports about it, and clicks, types and drags the way a person at the keyboard does.','它既看屏幕，也用系统报告的窗口信息，像坐在键盘前的人一样点击、输入、拖动。'),
   link:[L('Connect an MCP server','接入 MCP 服务器'),`${docs}extend/integrations/${L('#mcp-servers','#mcp-服务器')}`],
   figure:demoFigure('multimodal-computer')},
  {id:'coding',title:L('Coding','编程'),note:L('with coding agent','搭配 coding agent'),
   text:L('It reads the repository and the terminal as text, and a command is an action like any other.','它把代码仓库和终端当作文本来读，一条命令和其他动作没有区别。'),
   link:[L('Packages and environments','包与环境'),`${docs}configure/packages/`],
   figure:demoFigure('multimodal-coding')},
  {id:'robot',title:L('Robot','机器人'),note:L('with VLA','搭配 VLA'),
   text:L('Camera views and robot state go where they are needed, and where code cannot express a motion a program hands it to a learned policy.','摄像头画面和机器人状态各自送到需要它们的地方；代码表达不了的动作，程序交给学习型策略。'),
   link:[L('Add a learned policy','加入学习型策略'),`${docs}extend/integrations/${L('#learned-policies','#学习型策略')}`],
   figure:demoFigure('multimodal-robot')},
  {id:'game',title:L('Game','游戏'),note:L('coming soon','即将推出'),
   text:L('The picture the game draws is the input, the same one a player sees.','输入就是游戏画出来的画面，和玩家看到的一样。'),
   figure:demoFigure('multimodal-game')},
];
document.querySelector('#app').innerHTML=`<header class="ar-masthead">${ArchiveBanner.html({origin:'https://www.lmms-lab.com',locale:zh?'zh':'en',langHref:zh?'/':'/zh-cn/',github:repo})}</header><div class="ar-page-crt" aria-hidden="true"><i></i></div><main class="home-content">
<section class="home-hero wrap">
<div class="hero-copy"><h1>The Harness</h1><h2 class="home-tagline">${L('Automatic Control for<br><em>intelligence in action.</em>','自主控制，<br><em>让智能付诸行动。</em>')}</h2>
<div class="install-switcher"><div class="install-tabs" role="tablist" aria-label="${L('Installation method','安装方式')}"><button type="button" role="tab" id="install-tab-npm" aria-selected="true" aria-controls="install-panel" tabindex="0" data-install="npm">npm</button><button type="button" role="tab" id="install-tab-pip" aria-selected="false" aria-controls="install-panel" tabindex="-1" data-install="pip">pip</button></div><div class="hero-install" id="install-panel" role="tabpanel" aria-labelledby="install-tab-npm"><button id="hero-copy" aria-label="${L('Copy installation command','复制安装命令')}"><code id="install-command">npm install -g @lmmslab/harness</code><span class="copy-icon" aria-hidden="true">⧉</span></button><span id="hero-copy-status" class="sr-only" role="status"></span></div></div>
<div class="actions"><a class="primary" href="${docs}">${L('Get started','开始使用')} ${arrow}</a><a class="text-link" href="${docs}concepts/harness/">${L('Concepts','概念')} ${arrow}</a></div></div>
<div class="archive-panel hero-stack">${archiveOverlay}<div data-home-figure="-1" aria-label="${L('The Harness four-layer architecture','The Harness 的四层结构')}"></div></div>
</section>

<section class="home-modal wrap" aria-labelledby="modal-heading"><h2 id="modal-heading">${L('Multimodal <em>first.</em>','多模态<em>优先。</em>')}</h2><p class="section-lead">${L('The Harness was designed for several modalities from the start. Text, structure and images each keep their own form, and every step uses the one that serves it.','The Harness 从设计之初就面向多种模态。文本、结构和图像各自保持原样，每一步使用最适合它的那一种。')} <a href="${docs}concepts/multimodal/">${L('Multimodal first','多模态优先')} ${arrow}</a></p>
${stageBlock('modal',L('Inputs','输入'),inputs,'reverse')}
</section>

<section class="home-features wrap" aria-labelledby="features-heading"><h2 id="features-heading">${L('Autonomous<em>.</em>','自主运行<em>。</em>')}</h2>${sectionIndex(0)}<p class="section-lead">${L('The Harness keeps sensing and acting on its own. The model is called at decision points, and what it decides keeps working after the call returns.','The Harness 自己持续感知和行动。模型只在决策点被调用，它的决定在调用结束后继续起作用。')}</p>
${stageBlock('stage',L('Demos','演示'),features)}
</section>

<section class="home-layers wrap" aria-labelledby="layers-heading"><h2 id="layers-heading">${L('How it works','工作原理')}</h2>${sectionIndex(1)}<p class="section-lead">${L('The model writes the controller, then steps out of the loop. Four layers run at their own pace; what one cannot handle goes up as an event and reaches the model at its next decision point.','模型写出控制器，然后退出控制循环。四层各按自己的节奏运行；下层处理不了的情况作为事件向上传，在下一个决策点交给模型。')}</p><div class="home-layer-grid">
${layers.map(([n,when,title,text,href])=>`<article class="layer-card${n===1?' layer-reflex':''}"><div data-home-figure="${n}"></div><span class="layer-when">${when}</span><h3>${title}</h3><p>${text}</p><a href="${href}">${L('Learn more','了解更多')} ${arrow}</a></article>`).join('')}
</div></section>

<section class="home-extend wrap" aria-labelledby="extend-heading"><h2 id="extend-heading">${L('Works with<br><em>what you already use.</em>','接上你<br><em>已经在用的工具。</em>')}</h2>${sectionIndex(2)}
<div class="extend-grid">
${extensions.map(x=>`<article class="extend-card" id="extend-${x.id}"><figure class="archive-panel demo-figure logo-figure" data-demo="${x.id}">${archiveOverlay}${logoFigure(x)}</figure><div class="extend-copy"><h3><span aria-hidden="true">+</span> ${x.tab}</h3><p>${x.text}</p><details class="extend-setup pop"><summary>${L('Setup','配置')}</summary><div class="pop-body"><pre><code>${x.code}</code></pre></div></details><a class="text-link" href="${x.link[1]}">${x.link[0]} ${arrow}</a>${archiveEnd}</div></article>`).join('')}
</div></section>
</main><footer class="wrap"><a class="lab-logo" href="https://lmms-lab.com/" ${ext}><img src="/assets/logo-neon.png" alt="LMMS Lab"></a><span>The Harness</span><div><a href="${repo}" ${ext}>GitHub</a><a href="${ArchiveBanner.social.discord}" ${ext}>Discord</a><a href="${ArchiveBanner.social.x}" ${ext}>X</a><a href="${docs}">${L('Documentation','文档')}</a><a href="#">${L('Back to top ↑','回到顶部 ↑')}</a></div></footer>`;

function applyTheme(next,persist=false){theme=next;document.body.className=next==='day'?'pearl':'midnight';document.documentElement.style.colorScheme=next==='day'?'light':'dark';document.documentElement.dataset.theme=next==='day'?'light':'dark';if(persist){try{localStorage.setItem('starlight-theme',next==='day'?'light':'dark')}catch{}}const url=new URL(location.href);url.searchParams.delete('theme');history.replaceState(null,'',url);document.dispatchEvent(new CustomEvent('harness-theme',{detail:next}));}
// A query is an initial preview preference, never an override of a saved choice.
try{if(localStorage.getItem('starlight-theme')===null&&params.has('theme'))localStorage.setItem('starlight-theme',theme==='day'?'light':'dark')}catch{}
window.addEventListener('pageshow',()=>applyTheme(readTheme()));
window.addEventListener('storage',e=>{if(e.key==='starlight-theme'||e.key===null)applyTheme(readTheme())});
matchMedia('(prefers-color-scheme: light)').addEventListener('change',()=>applyTheme(readTheme()));
applyTheme(theme);ArchiveBanner.mount(document.querySelector('.ar-masthead'),{toggleTheme:()=>applyTheme(theme==='day'?'night':'day',true)});ArchiveBanner.account(document.querySelector('.ar-masthead'),{origin:'https://www.lmms-lab.com',locale:zh?'zh':'en'});

// Arrow keys, Home and End move between tabs; select() decides what a tab shows.
function tablist(buttons,select){
 buttons.forEach((tab,i)=>{
  tab.addEventListener('click',()=>select(i));
  tab.addEventListener('keydown',event=>{
   const n=buttons.length;let next;
   if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(i+1)%n;
   else if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(i-1+n)%n;
   else if(event.key==='Home')next=0;
   else if(event.key==='End')next=n-1;
   else return;
   event.preventDefault();select(next);buttons[next].focus();
  });
 });
}

const installTabs=[...document.querySelectorAll('[data-install]')];
tablist(installTabs,index=>{
 installMethod=installTabs[index].dataset.install;
 installTabs.forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1});
 document.querySelector('#install-panel').setAttribute('aria-labelledby',installTabs[index].id);
 document.querySelector('#install-command').textContent=installCommands[installMethod];
 document.querySelector('#hero-copy').disabled=!installCommands[installMethod];
 document.querySelector('#hero-copy-status').textContent='';
 document.querySelector('.copy-icon').textContent='⧉';
});
document.querySelector('#hero-copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(installCommands[installMethod]);document.querySelector('#hero-copy-status').textContent=L('Installation command copied.','安装命令已复制。');document.querySelector('.copy-icon').textContent='✓';setTimeout(()=>document.querySelector('.copy-icon').textContent='⧉',2000)}catch{document.querySelector('#hero-copy-status').classList.remove('sr-only');document.querySelector('#hero-copy-status').textContent=L('Select and copy the command above.','请选中并复制上面的命令。')}});

// Folded code opens as a floating panel over the page, one at a time; a click elsewhere
// or Escape closes it, so the layout never moves.
const pops=[...document.querySelectorAll('details.pop')];
pops.forEach(p=>p.addEventListener('toggle',()=>{
 if(!p.open)return;
 pops.forEach(o=>{if(o!==p)o.open=false});
 // As wide as its code; moved left if it would run past the edge of the screen.
 const body=p.querySelector('.pop-body');body.style.left='';
 const over=body.getBoundingClientRect().right-(document.documentElement.clientWidth-16);
 if(over>0)body.style.left=`${-over}px`;
}));
document.addEventListener('click',e=>pops.forEach(p=>{if(p.open&&!p.contains(e.target))p.open=false}));
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;pops.forEach(p=>{if(p.open){p.open=false;p.querySelector('summary').focus()}})});

// Playback, seeking and switching all use the actual media clock.
for(const stageEl of document.querySelectorAll('[data-stage]')) HarnessDemos.mount(stageEl,tablist,zh);
