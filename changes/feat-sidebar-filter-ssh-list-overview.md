---
agent: patch
app: patch
---

### English

- **Sidebar Filter & Sort menu**: Added a Filter & Sort button in the Projects header (`sidebar.js`, `icons.js`) supporting Group By (`Project` / `Flat list`), Sort Conversations (`Last Updated` / `Created` / `Title`), Sort Projects (`Custom Order` / `Last Updated` / `Name`), Filter (`All` / `Unread` / `Running` / `Pinned`), `Archived Only`, and `Mark All as Read`, persisted in local preferences with an active filter indicator bar.
- **Open SSH Host vertical scrollable list**: Redesigned the SSH remote project modal (`composer.js`, `app.css`) with a top `user@host:port` + Connect bar, inline remote path control, and a clean single-column scrollable `~/.ssh/config` host list with live filtering, keyboard navigation, and double-click connect.
- **Overview docked permanently on desktop right**: Lowered the desktop docked breakpoint to `960px` (`panel.js`, `app.css`), defaulted Overview to docked open (`overview.docked`), kept Overview visible without an accidental close button on desktop, and made closing sub-tools/artifacts return cleanly to Overview instead of collapsing the right panel.
- **Fix stuck "Working..." (`工作中`) indicator after replies finish**: `Life._over()` now notifies SSE subscribers after clearing `busy` and `current`, `/api/agent/stream` tracks `(busy, queue.running, queued, held)` changes and pushes `busy` in SSE payloads, and `app.js` immediately syncs `app.life.busy` so the spinner and stop button clear the instant a turn completes.

### 中文

- **侧边栏项目筛选与排序菜单**：在「项目」标题栏加入筛选/排序按钮，支持分组方式（按项目/全部平铺）、对话排序（最近更新/创建时间/标题名称）、项目排序（默认顺序/最近活跃/名称）、筛选（全部/仅未读/进行中/仅置顶）、仅看已归档与一键全部标为已读，并记忆偏好与显示激活筛选条。
- **SSH 连接弹窗改为纵向滚动列表**：将原本堆成一团标签的 SSH 主机选择重构为顶部 `user@host:port` + 连接按钮、内联远程目录与下方单列纵向可滚动 `~/.ssh/config` 主机列表（支持实时搜索过滤、上下键选择与双击直连）。
- **右侧 Overview 桌面端常驻展示**：将桌面端常驻断点放宽至 `960px` 并默认展开常驻右侧，去掉桌面端 Overview 顶部的误触关闭按钮，关闭子工具（文件/改动/终端/浏览器）或方案文档时返回 Overview 而不再把整个右侧栏折叠收起。
- **修复回复结束后仍卡在「工作中…」的假运行状态**：`Life._over()` 在清理 `busy` 与 `current` 后立即触发 `chats.notify()`，`/api/agent/stream` 监听 `busy` 与队列状态变化并在 SSE 事件中下发 `busy`，前端即时同步清除「工作中…」动效与停止按钮。
