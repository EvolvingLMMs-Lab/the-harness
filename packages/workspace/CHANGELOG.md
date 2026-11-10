# Changelog

## 0.2.1

- Declares the environment its host gives (`workspaces = ["project"]`), so a new installation finds and installs this package when a task names a folder or the project environment. Requires Harness 0.81.1.

## 0.2.0

- `Project folder` is one of the environments every new conversation chooses from, and can be taken into another conversation with `use_environment("project", why, folder=PATH)`. A project conversation takes a browser or the desktop the same way when a step must see something. Requires Harness 0.80.0.

## 0.1.0

- Own project binding, child inheritance, worker startup and settings through the package host provider; no computer dependency or core project fallback.
- Native project files and processes, controlled by model-written Python through the existing bounded execution lifecycle. Explicit project binding, target toolchains, conflict-checked file replacement, deadlines, cancellation and complete paginated process output.
- Trusted local execution. POSIX process-group cleanup; Windows tree cleanup is best effort. No external coding agent, browser or additional job service.
