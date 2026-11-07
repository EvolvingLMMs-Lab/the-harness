# Contributing to The Harness

Thank you for helping. This file is for people who change The Harness itself; the
documentation for using it is at <https://harness.lmms-lab.com/docs/>.

## Set up

```bash
git clone https://github.com/EvolvingLMMs-Lab/the-harness
cd the-harness
pip install -e .
```

The core needs Python 3.11 and its standard library only. Packages live in
`packages/<name>/`; install one you work on from its folder with
`harness install ./packages/<name> --link`.

## Conventions

- **One topic per pull request.** A change of several steps is one pull request with one
  commit per step.
- **The core stays small and standard-library Python.** Heavy dependencies (simulators,
  GPUs, model libraries) belong to the worker, kernel and service processes, each in an
  environment of its own, so configuration, resolution and reports work on any computer.
- **Capabilities are packages.** Skills, environments, services and prompts are found by
  their place in a package and turned on by configuration. A package imports The
  Harness only through `harness.sdk`.
- **A skill's calls are bounded executions** that end with an event, and a motion that may
  have been carried out is never retried silently.
- **Traces keep everything**: the original observations, every action's receipt and every
  error.
- **Nothing generated or secret is committed**: keys, credentials, model weights,
  environments, run outputs.

## Tests

```bash
python -m unittest discover -s tests -p test_packages.py
```

Select the checks affected by your change; do not run the full suite.

The tests start no simulator, call no model and download nothing. Some skip when their
platform or optional environment is missing; a skip does not validate a change, so run
the tests that cover your change where they can run.

Add or extend tests for new behavior, changed contracts and bug fixes: a regression test
fails on the old behavior and passes with the fix. Prose-only changes need no new tests.

## Packages

```bash
python tools/check.py NAME        # it loads, and imports only what it may
python tools/build.py NAME        # its package file and checksum
```

A package's README is its page in the package directory: what it does, what it needs
outside Python, how to use it, its settings and its limits, in at most 1500 words.

## Documentation

The site is an Astro Starlight project in `docs/`: pages in `docs/src/content/docs/`, the
sidebar in `docs/src/sidebar.json`, every page in English and Chinese
(`zh-cn/`). `docs/README.md` describes how it is built and published.

```bash
cd docs
deno install --frozen
deno task dev          # a local preview
deno task check        # type checks
deno task build        # the site, with the generated reference pages
deno task check:bundle # page size budgets
```

Keep documentation true to the code and within these rules:

- guides at most 1200 words, the introduction at most 600; reference pages have no limit;
- no source paths, plan names or run directories in the pages; public commands and API
  names only;
- every English page has its Chinese page;
- every `harness` command in a shell block parses, and every `/docs/` link names a page.

Write in the second person and a neutral tone. Guide titles start with a verb, reference
titles are nouns. Examples must run on an ordinary computer, without a GPU or a
benchmark.

## Reporting bugs

Open an issue with what you did, what you expected, what happened, and
`harness doctor --json`. Look through logs and traces before attaching them: they hold
the screenshots the agent took and the text it read.

## Community changes

Open contributions against this public repository. Maintainers coordinate each reviewed
change with the development source, validate affected integrations, and merge the original
public PR with its author and discussion intact. A changed PR head requires fresh validation.
Public CI and contributor tooling must never require development-repository access or secrets.
Source synchronization does not publish a package version.
