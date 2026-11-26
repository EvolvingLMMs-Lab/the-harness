---
core: minor
app: minor
---
There is a dev channel: The Harness Dev, a desktop app of its own beside The Harness, as VS Code Insiders is beside VS Code. It has its own icon (the cursor in amber), terminal command (`harness-dev`), data (`~/.harness-dev`), installs (`~/.cache/harness-dev`), login item and port, so both can be installed and run at once and neither touches the other's. It is built from every change to the main branch, published as the prerelease tagged `dev`, and updates itself from there with the same "Restart to update" as the release. `harness --version` says the build and the channel (`harness-dev 0.87.0-dev.412 (dev channel)`).
<!-- zh -->
新增开发版渠道：The Harness Dev，一个和 The Harness 并存的独立桌面应用，就像 VS Code Insiders 之于 VS Code。它有自己的图标（光标是琥珀色）、终端命令（`harness-dev`）、数据目录（`~/.harness-dev`）、安装目录（`~/.cache/harness-dev`）、登录项和端口，两者可以同时安装、同时运行，互不影响。main 分支每次变更都会构建它，发布在 tag 为 `dev` 的 prerelease 里，它从那里自动更新，和正式版一样提示“重启以更新”。`harness --version` 会显示构建号和渠道（`harness-dev 0.87.0-dev.412 (dev channel)`）。
