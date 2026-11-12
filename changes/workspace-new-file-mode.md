---
workspace: patch
---
A file the agent creates in a project folder gets the same permissions as one you create
(usually `rw-r--r--`), not `rw-------`; a file it replaces keeps its own.
<!-- zh -->
agent 在项目文件夹里新建的文件，权限和你自己新建的一样（通常是 `rw-r--r--`），不再是
`rw-------`；它改写的文件保留原来的权限。
