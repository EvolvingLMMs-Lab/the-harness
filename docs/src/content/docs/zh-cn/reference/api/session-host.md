---
title: "会话主机"
---

## `harness.host.http`

会话主机的 HTTP 服务器：所有前端通过它驱动对话、跟踪运行目录中的 episode 的 API，以及已安装时 app 包的页面。

仅使用标准库（http.server）。每次 API 调用都需要会话密钥：harness app 打印的 URL 中的 `token` 查询参数（页面随后保存到 cookie），或 X-Session-API-Key 请求头。通过 server-sent events 跟踪记录；重连客户端发送 Last-Event-ID（已收到的最后一个 `seq`），获取后续内容。它们发出的每条记录都带 `view`，即它的条目（transcript.py）。

| 请求 | 作用 |
|---|---|
| GET /api/runs | 列出 episode，最新的在前 |
| GET /api/meta?run=R | 获取 episode 的清单、摘要、结束方式和花费 |
| GET /api/events?run=R&after=N | 获取 seq N 之后的 trace 记录 |
| GET /api/stream?run=R | 获取上述记录，并持续接收新记录 |
| GET /api/file?run=R&name=F | 获取 episode 的文件（如视频或日志），或其中一段 |

/ 是首页（应用的页面），/dev 是运行列表页，/overlay?run=R 是时间轴悬浮窗口的页面（ui/overlay.py：一个运行的时间轴；不带 run 时跟随最新一个正在运行的 session）。其他包的页面在它的主机模块声明的路径上（pages()，harness/extensions.py），文件在 /static/&lt;package&gt;/&lt;file&gt;；它的 API（`api`）在 /api/&lt;package&gt;/&lt;name&gt;，GET 和 POST 都可以，和其他接口一样需要会话密钥。

服务器自身运行的对话（runtime/conversation.py，交互模式）写入 &lt;runs&gt;/ui/；POST 接受 JSON 请求体和会话密钥：

| 请求 | 参数与作用 |
|---|---|
| GET /api/options | 获取可选实验、模型文件和 deploy |
| GET /api/libraries | agent 学到的东西：$HARNESS_HOME 下的 library |
| GET /api/library?name=N | 一个 library 的版本和条目（证据档位、主动还是被动、测试、使用记录） |
| POST /api/conversations | 启动对话，参数为 experiment、task、seed、model、endpoint、instruction、confirmation、sets、deploy、title、frontend、workspace（一种工作区：应用的服务器从自己的池里为这个 session 取一个）；返回 {run, session} |
| POST /api/conversations/message | {run, text}：发送下次模型调用时使用的消息 |
| POST /api/conversations/pause | {run}：在下一执行步暂停 |
| POST /api/conversations/resume | {run}：继续运行 |
| POST /api/conversations/model | {run, model, reasoning_effort}：从下一次调用起换主模型（同一服务商的另一个 id）和思考强度（none、low、medium、high；"" 为服务商默认） |
| POST /api/conversations/confirm | {run, accept, reason, remember}：批准或拒绝等待确认的程序，或等待物理输入的步骤（remember：once、app、session、always） |
| POST /api/conversations/close | {run}：结束 episode |

对话的程序可以启动子 agent（runtime/agents.py）；这个服务器不给它们工作区（它没有工作区池：delegate 会说明），应用的服务器会给（app.py）。

run 是运行目录下某个 episode 的路径；对服务器自己运行的对话，也可以是它所属 session 的 id（session 中的某个 agent 写作 "&lt;session&gt;/&lt;agent&gt;"）。服务器运行的 session，每个都是一棵 agent 树（host/sessions.py）：

| 请求 | 参数与作用 |
|---|---|
| GET /api/sessions | 列出 session，最新的在前 |
| GET /api/sessions/show?id=S&lines=N | 一个 session、它的 agent 以及每个 agent 的最后几行 |
| POST /api/sessions/stop | {id, agent}：结束它的所有 agent（或指定的那个） |
| POST /api/sessions/approve | {id, agent, accept, reason}：对等待中的事项给出批准或拒绝 |

### `statics`

```python
def statics() -> dict
```

{package: 它的 ui/static/ 文件夹}：当前进程用到的、带页面的包。

### `static`

```python
def static() -> Path | None
```

/ 页面和 /static/&lt;file&gt; 文件所在的文件夹：app 包的 ui/static/；没有 app 时，取第一个主机模块在 / 给出页面的包的，否则取第一个有页面的包的。当前进程用到的包里都没有页面时为 None。

### `pages`

```python
def pages() -> dict
```

{path: (folder, file)}：这个服务器的页面。旧有的那些（PAGES）是 static() 文件夹里的文件；包的主机模块再加上自己的（`pages`，harness/extensions.py），是它 ui/static/ 里的文件。/ 仍然是 app 的页面；"/": None 是服务器自己的（Server.page）。

### `package_api`

```python
def package_api(path: str)
```

包的主机模块为 /api/&lt;package&gt;/&lt;name&gt; 提供的处理函数（它的 `api`，harness/extensions.py），没有则为 None。

### `bench_kind`

```python
def bench_kind(bench: str, worker: dict | None=None) -> str | None
```

实验的 worker 提供的工作区类型（None：没有工作区池能启动的那种）。

### `lanes_of`

```python
def lanes_of(directory: Path) -> dict
```

`directory` 中运行的泳道（core/lanes.py：泳道唯一的计算），作为每个网页视图绘制的快照；只有它的 trace 变化时才重新计算。

### `Server`

```python
class Server(OwnPort, ThreadingHTTPServer)
    __init__(address, root: Path, token: str | None=None, deploy: str | None=None)
```

面向运行目录 `root` 的 GUI HTTP 服务器，使用会话密钥 `token`（默认随机生成）。

#### `url`

```python
def url() -> str
```

含会话密钥的访问地址。

#### `info`

```python
def info() -> dict
```

提供给页面的服务器信息，含对话的各种状态和物理输入批准的文字。

#### `touch`

```python
def touch() -> None
```

有客户端发来请求（session host 把它算作活动）。

#### `model_changed`

```python
def model_changed(run: str, changed: dict) -> None
```

一个对话的模型或思考强度变了（POST /api/conversations/model）。

#### `session_directory`

```python
def session_directory(request: dict, config, seed: int) -> tuple[Path, str | None]
```

在这里启动的对话写到哪里，以及它的 run（None 表示用它所属 session 的 id）。

#### `directory`

```python
def directory(run: str) -> Path
```

`run` 的 episode 目录：先找这个服务器运行的对话，再找根目录下的 episode（都没有时抛出 ValueError）。

#### `sub_agents`

```python
def sub_agents(kind: str | None)
```

在这里启动、工作区类型为 `kind` 的 session 的子 agent（None：没有工作区池能提供的 bench）。

#### `start_conversation`

```python
def start_conversation(request: dict) -> str
```

启动交互对话（见模块 docstring）并返回其运行记录。

#### `workspace`

```python
def workspace(request: dict, experiment)
```

对话要的工作区（{endpoint, python, release}），没有要求时为 None。这个服务器自己不保留工作区：应用的服务器从它的池里取。

### `Handler`

```python
class Handler(BaseHTTPRequestHandler)
```

#### `log_message`

```python
def log_message(format, *args)
```

#### `do_GET`

```python
def do_GET()
```

#### `do_POST`

```python
def do_POST()
```

#### `get_options`

```python
def get_options(query)
```

#### `post_conversations`

```python
def post_conversations(body)
```

#### `post_conversations_message`

```python
def post_conversations_message(body)
```

#### `post_conversations_steer`

把新指令交给正在运行的外部回合。

```python
def post_conversations_steer(body)
```

#### `post_conversations_cancel`

取消当前外部回合。

```python
def post_conversations_cancel(body)
```

#### `post_conversations_config`

选取适配器实际公布的模型、模式或其他配置值。

```python
def post_conversations_config(body)
```

#### `post_conversations_answer`

回答当前 agent 的表单，传入空值可拒绝。

```python
def post_conversations_answer(body)
```

#### `post_conversations_diff`

查看所选会话的 Git 改动。

```python
def post_conversations_diff(body)
```

#### `post_conversations_merge`

将已关闭会话的托管 worktree 快进合并到原分支。

```python
def post_conversations_merge(body)
```

#### `post_conversations_discard`

移除已关闭会话的托管 worktree。

```python
def post_conversations_discard(body)
```

#### `post_conversations_terminal`

发送文本给会话的 PTY。

```python
def post_conversations_terminal(body)
```

#### `post_conversations_pause`

```python
def post_conversations_pause(body)
```

#### `post_conversations_resume`

```python
def post_conversations_resume(body)
```

#### `post_conversations_confirm`

```python
def post_conversations_confirm(body)
```

#### `post_conversations_model`

```python
def post_conversations_model(body)
```

#### `post_conversations_close`

```python
def post_conversations_close(body)
```

#### `get_sessions`

```python
def get_sessions(query)
```

#### `get_sessions_show`

```python
def get_sessions_show(query)
```

#### `post_sessions_stop`

```python
def post_sessions_stop(body)
```

#### `post_sessions_approve`

```python
def post_sessions_approve(body)
```

#### `get_info`

```python
def get_info(query)
```

#### `get_libraries`

```python
def get_libraries(query)
```

#### `get_library`

```python
def get_library(query)
```

#### `get_runs`

```python
def get_runs(query)
```

#### `get_meta`

```python
def get_meta(query)
```

#### `get_events`

```python
def get_events(query)
```

#### `get_lanes`

```python
def get_lanes(query)
```

#### `get_file`

```python
def get_file(query)
```

#### `get_stream`

```python
def get_stream(query)
```

### `FilesHandler`

```python
class FilesHandler(SimpleHTTPRequestHandler)
```

一个目录下的文件，只读，不需要密钥（serve_files），支持 Range 请求。

#### `send_head`

```python
def send_head()
```

#### `log_message`

```python
def log_message(*args)
```

### `serve_files`

```python
def serve_files(root: Path, host: str='127.0.0.1', port: int=8000) -> None
```

提供 `root` 下的文件直到被中断（harness view）；打印地址。

## `harness.host.client`

由本地客户端控制、在远程服务器上运行的对话（参考 OpenHands 的 RemoteConversation）。

RemoteConversation 通过本地 Conversation（runtime/conversation.py）相同的调用与 session host（host/http.py）通信：send_message、pause、resume、confirm、close，并接收实时 trace 记录。因此笔记本上的脚本或终端可通过通往服务器端口的 SSH 隧道，控制在 worker 和模型所在机器上运行的 episode。各个前端也通过它驱动 session host（host/）里的 session：这时 `run` 是 session 的 id，或 "&lt;session&gt;/&lt;agent&gt;"。

### `RemoteError`

```python
class RemoteError(RuntimeError)
```

服务器拒绝请求；消息中包含原因。

### `RemoteConversation`

```python
class RemoteConversation
    __init__(url: str, token: str, run: str, timeout: float=60.0, session: str | None=None)
```

GUI 服务器 `url`（http://host:port）上的对话 `run`，使用会话密钥 `token`。`status` 为其记录中报告的最新状态。

#### `start`

```python
def start(url: str, token: str, **request) -> 'RemoteConversation'
```

在服务器上启动对话：experiment、task、seed、model、endpoint、instruction、confirmation、sets（ui/server.py start_conversation）。

#### `describe`

```python
def describe() -> dict
```

这个对话所属的 session，按服务器列出的样子（状态、在等什么、它的 agent）；同时刷新 `status`。

#### `memory`

```python
def memory() -> list[dict]
```

它记得的东西：这一局的条目（看到了什么、在哪里）和它的 library 的条目，统一格式（runtime/memory.py rows），和每个前端显示的一样。

#### `send_message`

```python
def send_message(text: str, files=()) -> None
```

用户消息，供下次模型调用使用；`files`：它附上的文件路径。

#### `steer`

把新指令交给正在运行的外部回合。

```python
def steer(text: str, files=()) -> None
```

#### `cancel`

取消当前外部回合。

```python
def cancel() -> None
```

#### `set_config`

选取适配器实际公布的配置值。

```python
def set_config(identifier: str, value) -> dict
```

#### `answer`

回答当前 agent 的表单，传入空值可拒绝。

```python
def answer(request_id: str, content: dict | None) -> None
```

#### `diff`

查看所选会话的 Git 改动。

```python
def diff() -> dict
```

#### `merge`

将已关闭会话的托管 worktree 快进合并到原分支。

```python
def merge() -> dict
```

#### `discard`

移除已关闭会话的托管 worktree。

```python
def discard() -> dict
```

#### `terminal_input`

发送原始输入到会话的 PTY。

```python
def terminal_input(text: str) -> None
```

#### `handoff`

用用户选择的上下文启动新 agent，并关联原会话。

```python
def handoff(agent: str, context: str, *, folder=None, isolation=None)
```

#### `pause`

```python
def pause() -> None
```

在下一执行步暂停。

#### `resume`

```python
def resume() -> None
```

暂停后继续。

#### `confirm`

```python
def confirm(accept: bool, reason: str='', remember: str | None=None, *, request_id: str | None=None) -> None
```

批准或拒绝等待确认的程序，或等待物理输入的步骤（remember：once、app、session、always）。

#### `set_model`

```python
def set_model(model: str | None=None, reasoning_effort: str | None=None) -> dict
```

从下一次调用起换主模型（同一服务商的另一个 id）或思考强度。

#### `close`

```python
def close() -> None
```

结束 episode。

#### `records`

```python
def records(after: int=-1, stop=None)
```

返回 seq `after` 之后的 trace 记录，随后逐条返回新记录，直到 episode 最后一条记录（生成器；连接断开后恢复）。给了 `stop`（一个 threading.Event）时，事件被设置后它就结束，最迟在服务器的一个 keep-alive 间隔之内。

## `harness.core.episodes`

GUI 列出和读取的运行目录中的 episode。

episode 是含 events.jsonl 的目录（runtime/conversation.py）；manifest.json 和 summary.json 说明运行内容及结束方式。无摘要的 episode 仍在写入（或曾被中断）。summary()、usage() 和 ending() 是所有前端对它花费和结束方式的读法。

### `new_name`

```python
def new_name(suffix: str='') -> str
```

新运行的目录名："20261102-140530-3fa9c1"，给了后缀时再接 "-&lt;suffix&gt;"。

### `summary`

```python
def summary(directory) -> dict
```

episode 的 summary.json；没有或读不出来时为 {}。

### `usage`

```python
def usage(source) -> dict | None
```

摘要或目录里摘要的 {model_calls, cost_usd}（没有时为 None）。

### `ending`

```python
def ending(found: dict | None) -> str | None
```

episode 如何结束（ENDINGS 中的一个值，否则为摘要自己的状态）；没有摘要时为 None。

### `episode_dir`

```python
def episode_dir(root: Path, run: str) -> Path
```

episode 目录 `run`（相对于 `root` 的路径）；越出根目录或没有 trace 时抛出 ValueError。

### `describe`

```python
def describe(root: Path, directory: Path) -> dict
```

列表中的单个 episode：位置、任务、seed、状态、trace 最后修改时间，以及是否仍在写入。

### `list_episodes`

```python
def list_episodes(root: Path, limit: int=500) -> list[dict]
```

`root` 下的 episode，最近修改者优先（最多 `limit` 个）。

### `read_records`

```python
def read_records(directory: Path, after: int=-1) -> list[dict]
```

episode 中 `seq` 大于 `after` 的 trace 记录（仍在写入的行留待后续读取）。

### `Follow`

```python
class Follow
    __init__(directory: Path, after: int=-1)
```

随写入获取 trace 新记录：next() 返回上次调用以来新增的完整行。

#### `next`

```python
def next() -> list[dict]
```

#### `ended`

```python
def ended() -> bool
```

episode 是否已有摘要（不会再写入内容）。

## `harness.transcript`

人读到的 trace，供每个前端使用：items() 把一条记录变成条目 {kind（页面据此翻译）, role（终端据此着色）, text（英文）, keys（页面无法从记录读到的值）}；会话主机把它们作为每条记录的 `view` 发出。presentation() 是对模型回复的唯一读法。

### `presentation`

```python
def presentation(record: dict) -> dict
```

一条 model_reply 记录的读法：{kind, thought, body}，kind 为 python、action、verify、finish、message 或 invalid。没有 `presentation` 的旧 trace 从其文本读出（带动作标记却读不出来的为 invalid，其他文字为 message）。

### `answer_of`

```python
def answer_of(record: dict) -> str | None
```

当 `record` 是 agent 的最终回复时返回它的答案（harness run -p），否则返回 None。

### `physical`

```python
def physical(request: dict) -> tuple[str, str]
```

一个物理输入请求做什么（一个 doing.* 键），以及按人们叫法的应用：窗口标题的末尾（"Design - Figma"：Figma），否则是进程名。

### `items`

```python
def items(record: dict, names: dict, timeline: bool=False) -> list[dict]
```

一条记录的条目。`names` 把到目前为止开始的 span 和条目的 id 映射到名字（在这里填入）；`timeline` 会加上模型调用和 episode 如何结束。

### `approval_options`

```python
def approval_options(item: dict) -> list[tuple[str | None, str]]
```

返回此审批请求可用的授权范围及其标签。

### `item_lines`

```python
def item_lines(item: dict) -> list[tuple[str, str]]
```

一个 transcript 条目在终端里的文本行，每行附带它的 role（TUI 的颜色）。

### `record_lines`

```python
def record_lines(record, names, timeline=False) -> list[tuple[str, str]]
```

一条记录（它的 transcript.items）对应的文本行，每行附带 role：harness run 打印这些行。names 和 timeline 的含义与 transcript.items 相同。

### `TextTranscript`

```python
class TextTranscript
    __init__(timeline=False)
```

按顺序将一个对话的记录转换为文本行，每行前面是它的泳道路径（对话自己的行留空：用户的消息、状态）；
`timeline` 时还包括已结束 episode 的记录里显示的那些行（record_lines）。

#### `parts`

```python
def parts(record) -> list[tuple[str, str, str]]
```

`record` 的各行，形式为（类型、泳道路径、文本）。

#### `lines`

```python
def lines(record) -> list[str]
```

## `harness.terminal`

为终端把一个对话的记录转成文本行（harness run、harness replay、一个 session 的最后几行），每行前面是它在时间轴上的泳道路径（core/lanes.py：model、e0、e0/e2、env）；以及用户对对话下的命令，终端对话（tui/）和 harness run rpc 共用一张表。

### `Command`

```python
class Command(NamedTuple)
```

用户对对话说的一个词：调用它的 `method`，带上 `fixed` 和为 `takes` 给出的值（终端把命令后面的文字交给其中第一个）；`words`、`note` 是它的帮助。

### `command`

```python
def command(conversation, name: str, values: dict | None=None) -> None
```

在 `conversation` 上执行 COMMANDS[name]，带上用户为它的 `takes` 给出的 `values`（空的不传）；没有这个名字时抛出 KeyError。

## `harness.extensions`

包为会话主机及其前端添加的内容。包在 package.toml 中指定自己的一个模块（[provides] host = "module"）；核心按名称调用该模块定义的内容，自身不导入任何包。主机模块可以定义：
仅使用标准库。

    Workspaces(directory, settings)   where the session host's conversations run: workspaces
                                      of workers, one per conversation and sub-agent (the
                                      computer package's: a background browser, this
                                      computer's desktop, its applications, a display of
                                      their own). Its methods are those the assistant calls
                                      (host/assistant.py).
    note(values) -&gt; str               a line about this computer over the terminal chat's /settings
    waiting(owner) -&gt; str | None      what an agent of a session waits for (the input lock)
    recording(directory) -&gt; dict      a run's screen recording ({"path", "start", "stop",
                                      "area"}), or None
    areas(text) -&gt; tuple              a screen area "x,y,width,height" as numbers
    Chromes(directory, limit)         the headless Chromes a suite's background browsers share
    overlay                           the timeline overlay (the app package's: a window on top of
                                      the screen; launch, for_session, for_runs, close, Options)
    focus() -&gt; bool                   bring the package's window to the front (the app's, taptab's);
                                      False when it is not open (focus() tries each in turn)
    session_adapter(name, directory, *, cwd, isolation, model, effort)
                                      a host-managed external conversation, or None for a name
                                      this package does not provide. Its trace lives in directory.
    pages                             the package's pages: {"/taptab": "taptab.html"}, files of its
                                      ui/static/ served at those paths (host/http.py); its other
                                      files are at /static/&lt;package&gt;/&lt;file&gt;
    api                               the package's API: {"inbox": handler}, served at
                                      /api/&lt;package&gt;/inbox with the session key; handler(server,
                                      data) -&gt; JSON, or (body, content type, headers) as it is
                                      (data: a GET's query, a POST's JSON body; a ValueError or
                                      KeyError answers 400 with its text)
    mcp_servers(app) -&gt; dict          MCP servers for the conversations of the session host's
                                      assistant (the app's connectors), {name: client config};
                                      close_app(app) when the assistant closes
    export_video(directory, ...)      a run as a video (the app's: harness replay --export video)
    profiles                          {name: path}: conversation profiles a frontend starts the
                                      assistant's conversations with (POST /api/app/conversations
                                      {profile}); each file names skills only its conversations
                                      have and prompt text (host/assistant.py PROFILE_KEYS)

### `hosts`

```python
def hosts() -> list
```

本进程所用包中提供主机模块的那些，(package, 主机模块)，按包的顺序排列（paths.packages）。

### `modules`

```python
def modules() -> list
```

本进程所用包的主机模块，按包的顺序排列（paths.packages）。

### `first`

```python
def first(name: str)
```

第一个定义了 `name` 的主机模块中该名称对应的对象，没有则为 None。

### `require`

```python
def require(name: str, what: str, provider: str)
```

主机模块中 `name` 对应的对象；没有模块提供它时，先安装在其 `what` 中提供 `provider` 的包（按 packages.auto_install 的设置）：例如打开时间线浮窗的前端所需的 app 包浮窗。

### `focus`

```python
def focus() -> bool
```

对话需要用户时，把一个前端的窗口调到前台：依次调用每个主机模块的 focus()，直到有一个找到了打开着的窗口（先 app 的，再其他包的页面）。返回是否有一个找到了。

### `overlay`

```python
def overlay()
```

时间线浮窗（app 包的 harness_app/overlay.py）；没有包提供它时先安装。
