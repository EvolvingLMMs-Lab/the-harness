# Local testing before a pull request

The public repository runs `.github/workflows/checks.yml` on pull requests and pushes to `main`. Core checks use Python 3.11; terminal checks run on macOS and Linux with Python 3.12 and pinned UI dependencies. Tests do not require model keys, a simulator or a foreground desktop.

Run the core checks from the repository root:

```bash
python -m ruff check --isolated --select E9,F63,F7 src tests
python -m unittest discover -s tests -p test_packages.py
python -m unittest discover -s tests -p test_cli.py
python -m unittest discover -s tests -p test_model_attribution.py
```

For the Windows-specific ConPTY checks, use Python 3.12 with
`prompt-toolkit==3.0.52`, `rich` and `pywinpty==3.1.2`. On Windows, run:

```bash
python -m unittest discover -s tests -p test_tui_resize.py -v
python -m unittest discover -s tests -p test_tui_details.py -v
```

On macOS, `test_tui_resize_macos.py` starts the real Chat layout in a private tmux server, changes its terminal size, and checks scrollback, complete wide-character drafts and separator counts. Install tmux before running it; it never opens a foreground window. The `terminal` CI job also checks the installed wheel outside its checkout and the npm launcher's exit signals.

The resize checks launch the actual Chat layout in ConPTY, resize the console and
inspect its native character buffer. They verify separator counts, draft input,
transcript preservation and wide-character prompts without a model or desktop UI.

Lint checks syntax and invalid control flow; it does not enforce formatting, unused imports or undefined-name rules. Tests cover offline package resolution and installation, the CLI version entrypoint, and attribution headers using a local HTTP server. The four core commands above need no user namespaces and have no platform skips. The terminal job also verifies an installed wheel; the full suite, docs build and live integrations remain outside the minimal core job.

Authors and agents must still run the required checks for their change locally before opening a PR or pushing an update. Keep the actual results in the PR description; passing minimal CI does not validate contracts outside its coverage.

## Prepare the environment

Use Python 3.11 or newer in an isolated environment:

```bash
python -m venv .venv-test
. .venv-test/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -p test_packages.py
```

Core and package-management checks use the standard library. For an affected worker,
prepare the dependencies declared by that package's manifest. Desktop/browser integration
checks need the corresponding platform and installed browser; a skip is not evidence.
Checks must not download dependencies or make paid model calls. Real model acceptance
runs are separate, explicitly scoped tasks with their own budget and provenance.

For documentation or anything that changes generated references (CLI help, config
keys, skills, services, defaults or Python API docstrings), prepare Deno 2.9.x and the
site dependencies before running checks:

```bash
cd docs
deno install --frozen
```

See [the documentation workflow](README.md) for the site's setup and preview.

## Required checks

Run only checks for the affected modules and integration boundaries. Do not run the full
suite. Public checks live in `tests/`; internal cross-package checks are maintained separately.
Installation and entrypoint changes require an installed wheel outside the checkout and
representative actual task execution. Report scripted transport checks separately from model quality.

For documentation and generated-reference changes, also run these from `docs/`:

```bash
deno task check
deno task build
deno task check:bundle
```

Missing site dependencies do not satisfy the documentation gate. Do not skip type
checks, the build or size budgets when the change affects them. Keep
English and Chinese documentation consistent; edit generated English references at
their source and update the authored Chinese references.

Changes to installation, packaging, resources shipped in the wheel or entrypoints
also need an installed-wheel smoke check in a clean environment outside the checkout.
Exercise the affected entrypoint using synthetic fixtures or a local worker and check
that no source-checkout import or undeclared dependency is masking a failure.

For a platform-specific change, run the affected tests on that platform. Live
simulator/model evaluations are separate, explicitly scoped runs, not unit tests.
Use development layouts and the repository's evidence rules for agent-quality claims;
neither a mock nor a recorded observation replay is a fresh closed-loop result.

## When to add tests

| Change | Required evidence |
|---|---|
| New functional behavior or a changed contract | Add or extend a test that asserts the externally observable result, plus relevant failure paths and boundary cases. |
| Bug fix | Add or extend a regression that reproduces the failure on the old code and passes with the fix. |
| Persistence, resume, concurrency or budget behavior | Test the affected interruption, duplicate-execution, ownership, accounting or limit boundary, as applicable. |
| Performance-sensitive behavior | Add a regression test or repeatable benchmark appropriate to the claim, and measure before/after using the same workload, budget, environment and hardware. |
| Prose, formatting or a reversible change without behavior/performance impact | Run the required existing checks; no new test is needed. |

Tests should verify the contract, not duplicate the implementation or assert private
helper structure. Prefer deterministic work-count, allocation or concurrency-limit
assertions for ordinary regressions. For latency, throughput or memory claims, report
repeated measurements, their spread and the relevant resource/call/cost figures. Use
a representative workload and justify any threshold from the measurements; avoid
fragile wall-clock assertions on shared machines. Do not call a performance change an
improvement solely because its correctness tests pass.

## PR evidence and updates

Before publishing, confirm that the required checks pass for the current change.
After a further behavior change, rerun the affected checks. If
the environment or a required check is blocked, report the exact blocker and complete
the validation before opening or updating the PR.

In the PR description, record:

- The tested revision or working-tree state, OS, Python version and relevant tools.
- Exact commands, pass/fail results and skipped tests with their reasons. Distinguish
  platform skips unrelated to the change from missing validation of changed behavior.
- New or updated tests and the contract or regression they verify.
- For performance-sensitive work, the benchmark, workload, before/after measurements,
  repeated-run spread, resource/call/cost figures and measurement conditions.

Keep logs and run artifacts outside Git. Update the PR description after validation;
do not post progress-only comments or imply that checks outside CI coverage have passed.
