---
core: patch
browser: patch
computer: patch
external-agents: patch
---
Package removal retains shared immutable cache files for other projects and independently configured data directories, and updates choose compatible versions while keeping your declared ranges. Explicit updates refresh published versions, including in a running app. A project install paused for trust refuses changed declarations instead of overwriting them. Preparing path, Git or URL sources and waiting for trust leave other package commands available. If another package change is already publishing files or records, a new request stops promptly and asks you to retry after it finishes. Broken environment caches rebuild on first use; installation errors show their cause and retry only transient network failures, and the terminal uses its declared dependency pins.

Browser depends on computer 0.8, and current browser, computer and external-agents packages require Harness 0.82 or newer. The core refuses older computer packages with an upgrade command instead of running an incompatible managed-workspace protocol.
Project updates change the lock without turning indirect dependencies into declarations; outside a project, `--update --project` refuses to touch user packages.
Installing from a project's declarations preserves its source references and ranges, including legacy local-path records. Named dependency updates respect retained parent packages' constraints; jointly updated or replaced parents use their new dependencies.
Local sources stay local and resolve relative to the project root; older URL records remain usable. Manifest installs retain compatible registry locks. Dependency changes, including local replacements, respect retained parents and recorded ranges; incompatible existing records are refused before writes. The old computer/browser pair has one joint-upgrade command, and obsolete project lock conflicts explain explicit removal.

Cache reuse checks source identity and compatibility, including identical-version switches from development copies or another registry. Cleanup refuses the working directory, its ancestors, the home directory and filesystem roots.

Registry mirrors are recognized by identical archive checksums; implicit lock restore refuses different or missing content until you explicitly update or select a source. Source selection updates project declarations and dependencies together. Automatic installation respects development/disabled choices and pinned ranges; updates preserve enabled state and select versions compatible with the current platform.

Capability recovery refreshes an already installed provider and restores missing selected cache files without dropping owner settings. Recovery commands retain saved ranges; unnamed development dependencies and unavailable project locks refuse before writes, and missing-cache lock restoration checks its archive checksum.

Automatic recovery validates existing registry content in every scope, while explicit updates keep their selection authority. Dependency recovery names compatible joint commands, registry read failures preserve their real cause, and ready installed capabilities remain available before installation-policy gates without repeated change notifications.

Recovery commands stay limited to the related installed packages, including with obsolete lock entries or a stray lock. First-use installation of a new provider applies the same protection to already selected shared dependencies.

<!-- zh -->
卸载包会保留其他项目或数据目录可能仍在使用的共享缓存。更新选择兼容版本并保留声明的版本范围，在运行中的应用里也会刷新 registry。项目安装等待信任确认时，如果依赖声明发生变化，会要求重新安装，避免覆盖修改。下载来源和等待确认不会锁住其他包操作；如果另一项操作正在写入包文件或记录，新请求会立即说明未排队并提示稍后重试。损坏的环境会自动重建，安装失败会显示原因，只重试暂时性网络故障；终端会使用声明的固定依赖版本。
Browser 依赖 computer 0.8；browser、computer 和 external-agents 要求 Harness 0.82 或更新版本。核心遇到旧 computer 包时会给出升级命令，不再运行不兼容的托管工作区协议。
项目更新只改变锁定结果，不会把间接依赖加入声明；在项目外执行 `--update --project` 会拒绝操作，不会改动用户级包。
按项目清单安装会保留原来的来源引用与版本范围，也兼容旧的本地路径记录。单独更新依赖时会遵守保留的父包约束；一起更新或替换父包时则使用它的新依赖要求。
本地来源不会被当成 registry 包，相对路径以项目根目录为起点，旧 URL 记录也可继续使用。按清单安装会沿用仍兼容的 registry 锁定版本。依赖变更与本地替换都会遵守保留父包和已记录的范围；已有记录不兼容时会在写入前拒绝。旧 computer/browser 可用一条命令联合升级，项目的过时锁定记录冲突会提示显式移除。

复用缓存会检查来源身份与兼容性，包括从开发副本或其他 registry 切换到同版本包。清理会拒绝当前目录、它的祖先目录、用户主目录及文件系统根目录。

Registry 镜像按相同归档校验和识别；隐式恢复遇到不同或缺失的内容，会要求显式更新或选择来源。来源选择会同步声明和依赖。自动安装尊重开发来源、禁用状态与固定范围；更新保留启用状态，并选择当前平台兼容的版本。

恢复已有能力时会刷新进程中的包信息，并补齐缺失的缓存文件，保留用户设置。恢复命令保留已保存的范围；未具名的开发依赖和不可恢复的项目锁会在写入前拒绝，缺缓存时也会核对锁定归档的校验和。

自动恢复会在所有作用域核验已有 registry 内容，显式更新则保留选择新内容的权限。依赖恢复给出联合命令，registry 读取失败保留真实原因；已安装且可用的能力会在安装策略检查之前复用，不再反复发出包变更通知。

恢复命令只处理相关的已安装包，也能处理过时锁条目或孤立锁文件。首次安装新 provider 时，同样会保护已经选定的共享依赖。
