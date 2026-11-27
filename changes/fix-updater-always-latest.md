---
app: patch
---

### English

- **Desktop updater always jumps straight to the newest release in one restart**:
  - `packages/app/shell/src-tauri/src/main.rs`: `check()` no longer short-circuits when `phase == "ready"`, so manual and periodic checks detect newer releases (e.g. `dev.27` after `dev.26`), atomically upgrade the cached bundle without re-downloading identical versions, and preserve the already-verified `ready` bundle on transient errors.
  - Added a fast 6-second pre-install check inside `restart()` (run on a worker thread so `/api/app/update` keeps receiving live progress) that upgrades straight to the latest release before stopping the host and installing.
  - Shortened automatic check interval on non-stable channels (`dev`) to 10 minutes, updated the tray item label whenever the cached `ready` version advances, and showed live download progress in `update.js` when upgrading during restart.

### 中文

- **桌面更新器一步直达最新版本（不再先更旧包再更最新包）**：
  - `packages/app/shell/src-tauri/src/main.rs`：`check()` 不再在 `phase == "ready"` 时早退拦截，手动或定时检查发现更新版本（如 `dev.26` 缓存期间又发布了 `dev.27`）时会直接下载校验并原子替换内存缓存包；若版本一致则复用缓存不重复下载，若检查/下载出错则保留原已验证的 `ready` 包。
  - 在 `restart()` 停止宿主安装前加入 6 秒快速预检（运行在独立线程保证进度实时上报），即使定时检查尚未触发，点击「重启更新」也会直接一步拉取并安装最新可用版本，网络不可用时自动回退安装本地已验证包。
  - `dev` 渠道自动检查间隔调整为 10 分钟；缓存版本号升级时同步刷新系统托盘文案，前端 `update.js` 在重启前升级下载时实时显示最新版本号与下载百分比。
