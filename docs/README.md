# Documentation site

The public documentation at `https://harness.lmms-lab.com/docs/`, built with
[Astro Starlight](https://starlight.astro.build/) in the theme of The Simulator's
documentation (the same Hairline palette, line weights, Geist type, search and
headers), so LMMs-Lab's projects read as one family. It is a static site.

## Layout

| Path | Purpose |
| --- | --- |
| `docs/src/content/docs/` | Pages. `index.mdx` is the home page; a page that uses a component is `.mdx`, the rest Markdown. |
| `docs/src/content/docs/zh-cn/` | The Chinese pages, at the same paths, served under `/docs/zh-cn/`. All Chinese pages, including reference translations and the changelog, are maintained directly as Markdown or MDX and committed to Git. Tests require full Chinese coverage. `docs/TRANSLATING.md` has the rules and the term table. |
| `docs/src/content/docs/reference/` | Benches, worker protocol and traces are written by hand; the CLI, configuration keys, skills, services, the agent, configs, embodiments, the environment and the Python API are generated before every build by `scripts/gen_docs_reference.py --write`, and git ignores them. |
| `docs/src/sidebar.json` | The navigation, with the Chinese group labels under `translations`. Keep every page in it, every entry valid, and every Chinese page paired with an English one. |
| `docs/src/styles/theme.css` | The Hairline theme, as The Simulator's documentation has it. |
| `docs/src/components/` | Starlight overrides (site title and mark, search, footer), `FigureCard` for the home page, and `Diagram` with the two diagrams (`ProcessesDiagram`, `EpisodeDiagram`): static SVG that follows the page theme. |
| `docs/src/figures/` | The home page's figure, the layer stack drawn on the Hairline engine (`hairline-kernel.js`, vendored under its MIT license, `HAIRLINE-LICENSE`). |
| `docs/src/scripts/figures.ts` | Draws the figure into `[data-figure="harness"]` elements as they approach the viewport. |
| `docs/src/integrations/snippets.ts` | A line `--8<-- "path"` inside a code block becomes that repository file. |
| `docs/src/integrations/inline-csp-hashes.ts` | Adds hashes of Starlight's inline scripts to each page's CSP. |
| `docs/_headers`, `docs/_redirects` | Security and cache headers, and `/` → `/docs/`, copied to `dist/` for Workers static assets. |
| `docs/wrangler.jsonc` | The `harness-docs` Worker, which serves the whole `harness.lmms-lab.com` host. |
| `docs/tools/bundle.ts` | Size budgets: 64 KiB gzip JS, 24 KiB gzip CSS, 256 KiB of fonts, 32 KiB gzip for the largest page. They cover `dist/docs` only. |
| `docs/tools/registry.ts` | The package registry: validates a worktree of the repository's `registry` branch (`index.json` schema 1, every listed file present, every archive's size and sha256), copies it to `dist/registry/`, and writes the package pages to `dist/packages/` (English) and `dist/packages/zh-cn/` (Chinese) with their stylesheet `packages.css`. Package READMEs and changelogs are rendered by Sätteri with raw HTML shown as text. |

## Dependencies

Local validation is the PR gate; GitHub Actions CI is disabled. Follow
[the testing guide](TESTING.md) before opening or updating a PR. Use Deno 2.9.x.

This directory has its own `deno.json` and `deno.lock`; nothing here enters a Python
environment. Deno has no `package.json` for Astro to crawl, so
`astro.config.mts` lists the integrations Vite must bundle. Markdown goes through
Sätteri, Astro's native processor, so plugins are Sätteri mdast plugins, not remark
plugins. The build also needs Python 3.11 (standard library only) for the reference pages.

## Local workflow

Run from this directory:

```sh
deno install --frozen
deno task dev            # http://localhost:4321/docs/
deno task check
deno task build          # reference pages, then dist/docs plus dist/_headers and dist/_redirects
deno task check:bundle
deno task registry       # dist/registry and the pages under dist/packages
deno task preview        # the Workers runtime with routes, headers and 404 handling
```

`deno task registry [REGISTRY_DIR]` runs after `build`. The directory defaults to
`$HARNESS_REGISTRY_DIR`, else `../../registry`: a worktree of the repository's
`registry` branch next to this repository. It stops with an error if the registry does
not validate. Without a registry it writes a `/packages/` page that says no packages are
published yet, and no `/registry/`.

`deno task preview` serves the build at `http://localhost:8787/docs/`. The Content
Security Policy applies only to builds; check the browser console on a build, not `dev`.
