---
core: minor
workspace: minor
agent: patch
---
Workspace and remote SSH tasks no longer enforce real-time reflex-tree, `situations()`, `expect()`, or 2-second async turn splits by default, mark read-only workspace operations as reads, keep simple lookup goals concise, and reuse warm SSH worker bridges across tasks while still releasing per-task processes and isolating artifacts.
<!-- zh -->
工作区与远程 SSH 任务不再默认强制执行面向实时环境的反射树、`situations()`、`expect()` 或 2 秒异步拆轮，将只读工作区操作标记为读取，避免对简单探查做目标膨胀，并在释放单次任务进程和隔离产物的前提下跨任务复用 SSH 持久桥。
