# Documentation site

The documentation at `https://harness.lmms-lab.com/docs/` is built with Astro
Starlight. It uses a reading version of the archive design: the homepage's deep-sea navy,
mist-white and cyan/magenta colours, solid backgrounds, the lab fonts (Space Grotesk, Inter, JetBrains Mono) and flat code surfaces,
with no animated background or neon shadows. The page-wide cathode-ray glass from
`archive.css` is the one effect it shares with the homepage. Both languages share this theme.

## Layout

| Path | Purpose |
| --- | --- |
| `docs/src/content/docs/` | Pages. `index.mdx` is the Introduction; a page that uses a component is `.mdx`, the rest Markdown. The site's home page is not a Starlight page (see below). |
| `docs/src/content/docs/zh-cn/` | The Chinese pages, at the same paths, served under `/docs/zh-cn/`. All Chinese pages, including reference translations and the changelog, are maintained directly as Markdown or MDX and committed to Git. Tests require full Chinese coverage. `docs/TRANSLATING.md` has the rules and the term table. |
| `docs/src/content/docs/reference/` | Benches, worker protocol and traces are written by hand; the CLI, configuration keys, skills, services, the agent, configs, embodiments, the environment and the Python API are generated before every build by `scripts/gen_docs_reference.py --write`, and git ignores them. |
| `docs/src/sidebar.json` | The navigation, with the Chinese group labels under `translations`. Keep every page in it, every entry valid, and every Chinese page paired with an English one. |
| `design/site-preview/web/figures/` | The layer stack drawn on the Hairline engine (`hairline-kernel.js`, vendored under its MIT license, `HAIRLINE-LICENSE`). The project page and `HarnessFigure` on the concepts page use these same files; `docs/src/figures/harness.d.ts` holds its types. |
| `docs/src/scripts/figures.ts` | Draws the figure into `[data-figure="harness"]` elements as they approach the viewport. |
| `docs/src/styles/theme.css` | The reading version of the archive design. |
| `docs/src/components/` | Starlight overrides (the header, which is the lab banner; the sidebar's product name; search; footer; theme), `HarnessFigure`, `DemoFigure` (a drawn stand-in where a demo recording will go), and `Diagram` with the two diagrams (`ProcessesDiagram`, `EpisodeDiagram`): static SVG that follows the page theme. |
| `docs/src/integrations/snippets.ts` | A line `--8<-- "path"` inside a code block becomes that repository file. |
| `docs/src/integrations/inline-csp-hashes.ts` | Adds hashes of Starlight's inline scripts to each page's CSP. |
| `docs/vercel.json` | Redirects of moved pages, security and cache headers, and trailing slashes for the Vercel project `harness-site`, which serves the whole `harness.lmms-lab.com` host. `build` copies it to `dist/`, with the docs 404 page as the site's `404.html`. |
| `docs/tools/bundle.ts` | Size budgets: 64 KiB gzip JS, 24 KiB gzip CSS, 256 KiB of fonts, 32 KiB gzip for the largest page. They cover `dist/docs` only. |
| `docs/tools/registry.ts` | The package registry: validates a worktree of the repository's `registry` branch (`index.json` schema 1, every listed file present, every archive's size and sha256), copies it to `dist/registry/`, and writes the package pages to `dist/packages/` (English) and `dist/packages/zh-cn/` (Chinese) with their stylesheet `packages.css`. Package READMEs and changelogs are rendered by Sätteri with raw HTML shown as text. |

## Dependencies

The monorepo runs minimal Python lint and offline tests in GitHub Actions. Local validation of affected contracts remains the PR requirement. Follow
[the testing guide](TESTING.md) before opening or updating a PR. Use Deno 2.9.x.

This directory has its own `deno.json` and `deno.lock`; nothing here enters a Python
environment. Deno has no `package.json` for Astro to crawl, so
`astro.config.mts` lists the integrations Vite must bundle. Markdown goes through
Sätteri, Astro's native processor, so plugins are Sätteri mdast plugins, not remark
plugins. The build also needs Python 3.11 (standard library only) for the reference pages.

## Homepage and shared theme

`design/site-preview/web/` contains the homepage. `tools/homepage.ts` copies its active
assets to `dist/` after Astro builds `/docs/`, and writes the same page with
`<html lang="zh-CN">` to `/zh-cn/`; `app.js` holds both languages' strings and picks them
from the path. `archive.css`, `archive-banner.js`, the fonts in `archive-fonts/` and the banner logo are copies from the monorepo's `docs/brand/archive-design`; update them with its `sync_archive.py` (in the tools/website folder, outside the public export). Studies, anatomy experiments and preview artifacts are excluded. The
figures marked `data-demo` are drawn stand-ins for demo recordings.

The documentation's header is that same banner, not a Starlight header: `src/components/Header.astro`
renders `archive-banner.js` at build time and adds search to its right-hand group, and
`src/styles/theme.css` sets `--sl-nav-height` to the banner's height so the sidebar and contents
start below it. The banner's markup and styles stay the shared ones; change them in
`docs/brand/archive-design`. The monorepo's `tools/website/check_design_standard.py` (outside the
public export) fails when this header stops being the banner or a stylesheet here starts a font
list with anything but the lab's fonts. On phones the banner's menu tile opens the documentation sidebar
instead of the lab's links. The banner's files are served from the site root, which `tools/homepage.ts`
fills after the build, so `astro dev` shows the header without its styles; check it in `dist/`.

The homepage and Starlight use the same `starlight-theme` preference, with one-time
migration of legacy homepage choices. A saved choice wins over an old preview URL.
Both surfaces refresh their theme on history restoration and cross-tab changes.

## Local workflow

Run from this directory:

```sh
deno install --frozen
deno task dev            # http://localhost:4321/docs/
deno task check
deno task build          # reference pages, then dist/docs, the homepage and dist/vercel.json
deno task check:bundle
deno task registry       # dist/registry and the pages under dist/packages
deno task preview        # vercel dev on dist/: redirects, headers and 404 as in production
```

`deno task registry [REGISTRY_DIR]` runs after `build`. The directory defaults to
`$HARNESS_REGISTRY_DIR`, else `../../registry`: a checkout of the `registry` branch of
`EvolvingLMMs-Lab/the-harness-dev`, for example
`git clone --depth 1 -b registry https://github.com/EvolvingLMMs-Lab/the-harness-dev.git`.
In the monorepo it serves the branch as published, packages from `private/` included; the
public export accepts only packages from its own `packages/`. It stops with an error if the registry does
not validate. Without a registry it writes a `/packages/` page that says no packages are
published yet, and no `/registry/`.

`deno task preview` serves the build at `http://localhost:8787/docs/`. The Content
Security Policy applies only to builds; check the browser console on a build, not `dev`.

## Publishing

Production is the Vercel project `harness-site` in the team `luodians-projects`, with
`harness.lmms-lab.com` as its domain (a DNS-only CNAME to `cname.vercel-dns.com` on the
Cloudflare `lmms-lab.com` zone, like `www`). The project has no Git connection and no
build: the deploy uploads the local `dist/` as it is. That holds the pages under `/docs/`,
the homepage at `/` and `/zh-cn/`, the package pages under `/packages/` and the package
registry under `/registry/` (what `harness install` reads). Deploy after both `build`
and `registry`: a deployment without the registry step removes `/registry/` and the
package pages from the site.

The deploy runs as the logged-in Vercel CLI user, who must be a member of the team
(`vercel whoami`); the team and project IDs are in the `deno.json` tasks.

```sh
deno task build
HARNESS_REGISTRY_DIR=<registry checkout> deno task registry
deno task deploy:preview    # a preview URL to check first
deno task deploy            # production
deno task deploy:status
deno task deploy:rollback   # back to the previous production deployment
```

After a deployment, `/` and `/zh-cn/` should return the homepage, pages under `/docs/`
and `/packages/` should return 200 with the security headers from `vercel.json`, a moved
page such as `/docs/home/` should redirect, an unknown path should return the docs 404
page with status 404, and `/registry/index.json` should match the registry branch, with
a five-minute cache while the archives are cached as immutable.

Until 2026-11-08 the site was the Cloudflare Worker `harness-docs`; it still exists on
the account without a domain.

The repository is private, so the site has no "Edit on GitHub" or GitHub links yet.
Add `editLink` and a `social` entry in `astro.config.mts` when it becomes public.
