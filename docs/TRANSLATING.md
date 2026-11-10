# Translating the documentation into Chinese

English is the source. A Chinese page lives at the same path under
`src/content/docs/zh-cn/` and is served at `/docs/zh-cn/...`; a page without a Chinese
version would fall back to English in Starlight, so `tests/test_docs.py` requires full
Chinese coverage, including the changelog and generated reference pages.

All Chinese pages are maintained directly as Markdown or MDX under `zh-cn/` and
committed to Git, including the reference pages. There is no translation catalog or
translation step in the build. `scripts/gen_docs_reference.py` generates only the
English reference pages; it does not overwrite Chinese files.

When reference code or its English descriptions change, run
`python scripts/gen_docs_reference.py --write`, compare the English reference with its
Chinese page, and update the Chinese Markdown directly. Keep commands, defaults,
signatures, code examples and snippets synchronized. `tests/test_docs.py` checks page
coverage and example/identifier consistency; prose changes require manual review.
Preserve the explicit English heading anchors in Chinese reference pages so existing
links keep working.

## Rules

- Translate everything a reader reads: frontmatter `title` and `description`, headings,
  prose, table cells, list items, aside titles (`:::note[...]`), figure captions.
- Leave unchanged: code blocks (including the comments inside them), inline code, commands,
  file paths, configuration keys, identifiers, numbers, `--8<-- "..."` lines, and quoted
  task instructions such as *"Stack the three bowls together."* (they are data).
- Links: `/docs/<page>/` becomes `/docs/zh-cn/<page>/`. Drop a `#anchor` when it points
  into a translated page unless that page preserves the original anchor. Chinese
  reference pages (`reference/cli`, `reference/configuration`, `reference/skills/*`,
  `reference/services/*`, `reference/agent`, `reference/configs`, `reference/embodiments`,
  `reference/environment`, `reference/api/*`) preserve their original anchors; keep those links.
  External links stay as they are.
- MDX: imports gain one `../` (the page is one directory deeper). Diagrams take
  `lang="zh-CN"`: `<ProcessesDiagram lang="zh-CN" />`, `<EpisodeDiagram lang="zh-CN" />`.
  `<Tabs>` / `<TabItem label="...">`: translate the label.
- Keep the structure: same sections, same order, nothing added or left out.
- Style: plain, precise technical Chinese, sentence by sentence faithful; no marketing
  words (赋能、助力、一站式、打造). A space between Chinese and Latin text or numbers
  (`用 SAM 3 分割`). Chinese punctuation in Chinese sentences.

## Terms

| English | Chinese |
|---|---|
| Automatic Control | 自动化控制 |
| The Harness, harness | The Harness, harness（不译） |
| agent | agent |
| language model / model | 语言模型 / 模型 |
| main model | 主模型 |
| model call | 模型调用 |
| program | 程序 |
| decision point | 决策点 |
| skill | skill |
| prompt pack | prompt pack |
| learned policy | 学习型策略 |
| policy | 策略 |
| strategy (the A / B / C choice) | strategy（不译，避免和 policy 混淆） |
| reactive layer | 反应层 |
| guard / controller / handler | guard / 控制器 / handler |
| reflexes | 反射 |
| shield, safety layer | 安全层（shield） on first use in a page, then 安全层 |
| service | 服务 |
| manifest | 清单 |
| deploy (file) | deploy 文件 |
| placement | 放置 |
| resident / on demand / swap group | 常驻 / 按需 / swap group |
| environment (where tasks run; also a Python environment) | 环境 |
| benchmark, bench | benchmark |
| task / episode / layout / seed / suite | 任务 / episode / layout / seed / suite |
| run (noun) | 一次运行 |
| trace | trace |
| identity / lock | identity / lock |
| worker / kernel / driver / broker | worker / kernel / driver / broker |
| world model | 世界模型 |
| leaderboard | 排行榜 |
| evaluation pack | 评测包 |
| development layouts / evaluation layouts | 开发 layout / 评测 layout |
| ablation | 消融 |
