---
core: patch
agent: patch
app: patch
---

First-principles workbench architecture overhaul across Desktop App, Backend, and Terminal TUI:

- **Desktop Root Shell & Design System**: Replaced fixed `.pg-win` overlay caption buttons with a dedicated 32px Row-1 `.pg-titlebar` (brand, File/View/Window menus, drag region, native 46x32 caption controls on Windows/Linux, 78px traffic-light inset on macOS, 0px in web mode), eliminating all titlebar collisions across Chat, Overview, Calendar, Customizations, and Settings. Consolidated unified radii and monotonic Z-index tokens (`--z-base` through `--z-toast`).
- **Workbench Spatial Model**: Added unified 40px full-width Chat breadcrumb header (`Project / Title`), redesigned Overview as an Antigravity-style inset rounded card (no competing topbar, no redundant workspace KV table, up to 20 PRs with `See all`, collapsible Tasks/Goals/Artifacts), added a compact Diff Summary Bar above the composer (`N files changed +A -D`), moved Terminal into a full-width bottom resizable drawer (`Ctrl+\``), and kept Review/Files/Artifact/Browser in a right resizable split work pane.
- **Desktop Surfaces**: Single-line 30px sidebar rows with navigation history (`Alt+Left/Right`), pinned project chats kept inside their project, clickable `@scope:ref` mention pills inside user bubbles, single 24px composer footer row, responsive Calendar view selector (`< 720px`), and 6-tab Customizations with dedicated Memory CRUD, zero search-input focus loss, and real settings wiring.
- **Backend & SSH Parity**: Unified local and SSH workspace handling in `overview()` and `place_search()`, increased PR limit to 20, included diff line counts (`diff_added`/`diff_removed`), and added SSE-priority busy state guard against stale polling bounce.
- **Terminal TUI Parity**: Aligned `Shift+Tab` and `/mode` (`/plan`, `/ask`, `/auto`, `/full`) with 4-level execution modes, upgraded approvals to 3 options forwarding `scope="session"`, added structured `@rule:/@memory:/@chat:/@artifact:/@file:/@skill:` completion, added `/artifacts`, `/rewind`, and Agent `/diff`, rendered `artifact` and `task_step` events, wired real `/api/agent/attach` uploads, and synced auto-generated titles live into the status bar.
