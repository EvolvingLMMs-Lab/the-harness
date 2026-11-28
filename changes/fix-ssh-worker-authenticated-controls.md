---
workspace: patch
---
Enable authenticated worker controls (`approval_from_stdin=True`) on the in-process SSH workspace worker server so `SpaceEnvironment.for_worker` accepts its `approval_key`.
<!-- zh -->
为进程内 SSH workspace worker 服务端开启受鉴权控制（`approval_from_stdin=True`），修复 `SpaceEnvironment.for_worker` 启动时报错 `Worker did not enable authenticated controls`。
