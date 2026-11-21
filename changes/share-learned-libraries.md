---
core: minor
---
`harness share` sends what an agent learned (a library) as a package to GitHub, another git remote, a website's folder or another computer, and prints the one line that installs it. Installing such a package gives a copy under `$HARNESS_HOME/libraries` that `--library NAME` uses and keeps learning in; a later install replaces it only while no run learned in it. `harness install` also takes a GitHub repository's address.
<!-- zh -->
`harness share` 把 agent 学到的东西（一个 library）作为包发到 GitHub、其他 git 远端、网站文件夹或另一台电脑，并给出安装它的那一行命令。安装后在 `$HARNESS_HOME/libraries` 下得到一份副本，`--library NAME` 直接使用并在里面继续学；之后再安装时，只有没被学过的副本才会被替换。`harness install` 也接受 GitHub 仓库地址。
