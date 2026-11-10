# Change notes

This folder holds a note for each change people would notice that is not released yet. A
pull request adds its note here instead of changing a version or a changelog; a release
(`python tools/release.py prepare`) turns the notes into versions and changelog entries and
removes them.

Name the file after the change, `<a short name>.md`, so that pull requests never touch the
same file. A note has a header and a text:

```markdown
---
core: minor
computer: patch
---
A task given only a folder installs the package of the environment it needs.
<!-- zh -->
只给一个目录的任务会自动安装它需要的环境包。
```

- **Header**: one line for each component the change touches, `core` (The Harness itself)
  or the name of a folder under `packages/`, with a level:
  - `patch`: a fix; nothing new to learn.
  - `minor`: a new capability, or a change in what something does: commands, settings, the
    agent's prompts, skills and defaults. Before 1.0, a breaking change is `minor` too, and
    the text says what breaks and what to do instead.
- **Text**: a sentence or two for the people who use The Harness: what changed for them,
  not how it was done. Write in the present tense.
- **Chinese**: optional, after a `<!-- zh -->` line. Maintainers translate the rest when
  they release.

A change people would not notice (a refactor, a faster test) needs a note with an empty
header, so that the check knows it was decided:

```markdown
---
---
```

Changes of tests, documentation or CI alone need no note.

`python tools/release.py check-pr --base origin/main` checks notes and versions as CI does.
