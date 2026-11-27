---
app: patch
---
Stop binding the unassigned `main` conversation to the first connected project folder in `_place_folder()`, so a chat with no project attached no longer leaks another project's git diff count, branch, files, or pull requests.
<!-- zh -->
移除 `_place_folder()` 对未绑定项目的 `main` 主对话自动回退到第一个已连接项目文件夹的逻辑，避免无项目对话串出其他项目的 git 改动、分支、文件树和拉取请求。
