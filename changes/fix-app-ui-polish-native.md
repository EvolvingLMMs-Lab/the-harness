---
agent: patch
app: patch
---

### English

- **Native UI layout, Markdown/KaTeX ESM, auto-titles, Overview & attachments rework**:
  - Refactored `app.css` into a 3-tier responsive layout (`>=1100px`, `700–1099px`, `<700px`) with a uniform centered reading column and unified `.pe.pe-user-wrap` message wrapper.
  - Loaded Marked and DOMPurify as native ES modules in `markdown.js`, kept single minified offline `katex.min.js`, fixed codespan double-escaping, per-call random math nonces, blockquote/list display math, and inline `$` left boundaries.
  - Reworked first-turn auto-titles (`title_source='default'`, localized default title recognition, dedicated one-shot non-thinking `ChatModel` for built-in HTTP providers with real spending charge, clean fallback on non-HTTP/ACP backends).
  - Fixed Overview backend contracts (`Life.context`, `Life.intend`, active session pending tasks & host sessions), separated `--w-overview` from `--w-panel`, and added debounced reactive refresh.
  - Hardened attachment thumbnails, Escape lightbox isolation, download attribute on non-image chips, SVG attachment disposition, and omitting empty `input_text` parts in `Session._with_files`.

### 中文

- **原生重构界面布局、ESM Markdown/KaTeX、自动标题、Overview 与附件处理**：
  - 将 `app.css` 原生重构为三档响应式布局（`>=1100px`、`700–1099px`、`<700px`），统一居中阅读列与用户消息包装层。
  - `markdown.js` 改用原生 ES Module 加载 Marked/DOMPurify，保留精简离线 `katex.min.js`，修复行内代码双重转义、随机公式占位 nonce、引用/列表块级公式与行内 `$` 边界。
  - 完善首轮自动标题（支持多语言默认标题识别与显式 `title_source='default'`、内置 HTTP 模型独立一次性非思考调用并计入账单、ACP 等后端优雅降级）。
  - 修复 Overview 后端数据契约、分离 Overview 与面板宽度变量并增加防抖刷新；加固附件安全（SVG 强制下载、合法 `..` 文件名放行、灯箱 Esc 隔离、空文本附件省略空 `input_text`）。
