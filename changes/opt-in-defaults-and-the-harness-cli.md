core: minor
agent: minor
app: minor
---
- Remove opinionated user-decision defaults: daily spending budget (`agent.daily_budget`), unpriced call cap (`agent.daily_calls`), reserve (`agent.reserve`), raw record retention (`agent.keep_days`), autonomous mode (`agent.proactive`), and login autostart (`agent.autostart`) now default to unset/off (`0.0`, `0`, `0.0`, `0`, `"off"`, `false`), with unlimited handling across spending enforcement, TUI, and Desktop App UI.
- Make `the-harness` the primary CLI command everywhere (Python entry point, npm bin, desktop installers/PATH launchers, shell completions, CLI help, README, and English/Chinese docs) while keeping `harness` fully compatible as a shorthand alias.
- Fix chat feed flexbox compression (`flex-shrink: 0` on `.pg-feed > *` and removing `overflow: hidden` on `.pe.card`) so briefing/summary cards such as "Since yesterday" never collapse vertically when scrolling.
