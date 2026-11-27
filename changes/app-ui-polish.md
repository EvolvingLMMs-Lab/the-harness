---
core: patch
agent: minor
app: minor
---

Upgrade app chat layout, automatic conversation titles, attachment rendering, offline KaTeX/Markdown pipeline, and collapsible Overview panel:

- Center the chat column (`--chat-max-width: 760px`) with clean assistant typography and right-aligned user bubbles.
- Add read-only attachment API (`GET /api/attachments/<id>`), unified attachment chips/thumbnails, and native `<dialog>` lightbox preview.
- Add automatic first-turn conversation title generation (`titles.py`, `title_source` guard against overwriting manual titles, SSE sync).
- Bundle offline KaTeX + Marked + DOMPurify with Pandoc-style `$` math boundaries in `markdown.js`.
- Consolidate the right-hand tools into a collapsible ~280px Overview panel backed by `/api/app/overview` (showing only populated real sections).

### 中文

- 升级桌面端对话排版（`--chat-max-width: 760px` 居中阅读列与简洁助手排版）。
- 新增只读附件接口与图片缩略图 / `<dialog>` 大图灯箱预览。
- 新增首轮对话自动生成标题（`title_source` 保护手动改名 + SSE 实时同步）。
- 离线打包 Marked + DOMPurify + KaTeX，支持 Pandoc 风格数学公式渲染。
- 右侧工具收敛为可折叠 ~280px Overview 面板（聚合真实后端状态，无数据区块自动隐藏）。
