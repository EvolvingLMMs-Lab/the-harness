---
core: patch
agent: patch
app: patch
---
Flush and fsync temporary files in `atomic_write` before `os.replace` so sudden reboots or power loss do not leave zero-filled JSON files, gracefully recover corrupted `meta.json` and `origin.json` metadata so one damaged file never breaks the conversation list or skills listing, and place the chat timeline inside `.pg-composer-dock` so it aligns with the reading column when the floating Overview card is visible.
<!-- zh -->
在 `atomic_write` 执行 `os.replace` 前先 `flush` 并 `os.fsync`，避免突然断电或重启导致 NTFS 留下全零损坏的 JSON 文件；为损坏的 `meta.json` 和 `origin.json` 增加优雅降级恢复，避免单个异常文件拖垮整个对话列表或技能列表；并将对话时间线放进 `.pg-composer-dock` 对齐容器内，修复悬浮概览卡片显示时时间线向右偏移错位的问题。
