# Skills

What a model's programs can call: one directory per skill, a `skill.toml` manifest and an
`__init__.py` with a mixin class. A system turns skills on by interface layer or by name;
a skill whose services are missing drops out, and the prompt drops its text with it.

- How it works: [docs/src/content/docs/concepts/skills.md](../docs/src/content/docs/concepts/skills.md)
- Write one: [docs/src/content/docs/guides/write-a-skill.md](../docs/src/content/docs/guides/write-a-skill.md)
- Every skill with its functions: the documentation site's *Reference → Skills*
  (generated from these directories by `scripts/gen_docs_reference.py`)
