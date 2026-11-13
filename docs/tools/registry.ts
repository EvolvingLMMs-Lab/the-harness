// Publishes the package registry with the site: validates a registry checkout, copies
// it to dist/registry/ and writes the static package pages under dist/packages/.
//
//   deno task registry [REGISTRY_DIR] [--require]
//
// REGISTRY_DIR defaults to $HARNESS_REGISTRY_DIR, else ../../registry (a checkout of the
// repository's `registry` branch next to this checkout). Run it after
// `deno task build`. With --require (the deploy tasks pass it) a missing registry is an
// error, not an empty listing. The registry format is documented in
// src/harness/packages/registry.py.
import { createHash } from "node:crypto";
import { markdownToHast } from "satteri";

const DIST = "dist";
const OUT_REGISTRY = `${DIST}/registry`;
const OUT_PAGES = `${DIST}/packages`;
const ZH = "zh-cn";

const NAME = /^[a-z0-9][a-z0-9_-]*$/;
const VERSION = /^[0-9A-Za-z][0-9A-Za-z.+-]*$/;
const SHA256 = /^[0-9a-f]{64}$/;
const PROVIDES = [
  "kinds",
  "embodiments",
  "skills",
  "benches",
  "services",
  "profiles",
  "experiments",
  "agent_skills",
  "commands",
  "settings",
] as const;
type Provides = Partial<Record<(typeof PROVIDES)[number], string[]>>;

interface Version {
  file: string;
  sha256: string;
  size: number;
  harness?: string;
  depends?: Record<string, string>;
  platforms?: string[];
  provides?: Provides;
  readme?: string;
  changelog?: string;
  published?: string;
  yanked?: boolean;
}
interface Package {
  summary?: string;
  latest: string;
  versions: Record<string, Version>;
}
interface CoreBuild {
  file: string;
  sha256: string;
  size: number;
  published?: string;
}
interface Index {
  schema: number;
  updated?: string;
  packages: Record<string, Package>;
  // Pre-release builds of the harness itself (tools/release.py core).
  core?: { latest: string; versions: Record<string, CoreBuild> };
}

class RegistryError extends Error {}
function fail(message: string): never {
  throw new RegistryError(message);
}

async function exists(path: string): Promise<boolean> {
  try {
    await Deno.lstat(path);
    return true;
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) return false;
    throw error;
  }
}

async function removeIfPresent(path: string): Promise<void> {
  if (await exists(path)) await Deno.remove(path, { recursive: true });
}

// ---------- Validation ----------

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

// A path inside the registry: relative, forward slashes, under <name>/<version>/.
function checkPath(where: string, path: unknown, name: string, version: string): string {
  if (typeof path !== "string" || !path) fail(`${where}: missing path`);
  const parts = path.split("/");
  if (path.includes("\\") || parts.some((part) => !part || part === "." || part === "..")) {
    fail(`${where}: "${path}" is not a plain relative path`);
  }
  if (parts.length !== 3 || parts[0] !== name || parts[1] !== version || parts[2].startsWith(".")) {
    fail(`${where}: "${path}" is not a file directly under ${name}/${version}/`);
  }
  return path;
}

async function checkFile(root: string, where: string, path: string): Promise<Uint8Array> {
  let info: Deno.FileInfo;
  try {
    info = await Deno.lstat(`${root}/${path}`);
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) fail(`${where}: ${path} is listed but missing`);
    throw error;
  }
  if (!info.isFile) fail(`${where}: ${path} is not a regular file`);
  return await Deno.readFile(`${root}/${path}`);
}

async function validate(root: string): Promise<{ index: Index; raw: Uint8Array }> {
  const raw = await checkFile(root, "registry", "index.json");
  let index: Index;
  try {
    index = JSON.parse(new TextDecoder().decode(raw));
  } catch (error) {
    fail(`index.json is not valid JSON: ${(error as Error).message}`);
  }
  if (!index || typeof index !== "object") fail("index.json: not an object");
  if (index.schema !== 1) fail(`index.json: schema ${JSON.stringify(index.schema)} is not 1`);
  if (!index.packages || typeof index.packages !== "object" || Array.isArray(index.packages)) {
    fail("index.json: packages is not an object");
  }
  for (const [name, pkg] of Object.entries(index.packages)) {
    if (!NAME.test(name) || name === ZH) fail(`index.json: "${name}" is not a valid package name`);
    if (!pkg || typeof pkg !== "object") fail(`${name}: not an object`);
    if (pkg.summary !== undefined && typeof pkg.summary !== "string") fail(`${name}: summary is not a string`);
    if (!pkg.versions || typeof pkg.versions !== "object" || !Object.keys(pkg.versions).length) {
      fail(`${name}: no versions`);
    }
    if (typeof pkg.latest !== "string" || !(pkg.latest in pkg.versions)) {
      fail(`${name}: latest ${JSON.stringify(pkg.latest)} is not one of its versions`);
    }
    for (const [version, entry] of Object.entries(pkg.versions)) {
      const where = `${name} ${version}`;
      if (!VERSION.test(version)) fail(`${where}: not a valid version`);
      if (!entry || typeof entry !== "object") fail(`${where}: not an object`);
      if (typeof entry.sha256 !== "string" || !SHA256.test(entry.sha256)) fail(`${where}: sha256 is not 64 hex digits`);
      if (!Number.isInteger(entry.size) || entry.size < 0) fail(`${where}: size is not a byte count`);
      if (!checkPath(where, entry.file, name, version).endsWith(".tar.gz")) fail(`${where}: file is not a .tar.gz`);
      const tar = await checkFile(root, where, entry.file);
      if (tar.byteLength !== entry.size) {
        fail(`${where}: ${entry.file} is ${tar.byteLength} bytes, index.json says ${entry.size}`);
      }
      const digest = createHash("sha256").update(tar).digest("hex");
      if (digest !== entry.sha256) {
        fail(`${where}: sha256 mismatch for ${entry.file}\n  index.json: ${entry.sha256}\n  file:       ${digest}`);
      }
      for (const key of ["readme", "changelog"] as const) {
        if (entry[key] !== undefined) await checkFile(root, `${where} ${key}`, checkPath(`${where} ${key}`, entry[key], name, version));
      }
      for (const key of ["harness", "published"] as const) {
        if (entry[key] !== undefined && typeof entry[key] !== "string") fail(`${where}: ${key} is not a string`);
      }
      if (entry.platforms !== undefined && !isStringList(entry.platforms)) fail(`${where}: platforms is not a list of strings`);
      if (entry.depends !== undefined) {
        if (!entry.depends || typeof entry.depends !== "object" || Array.isArray(entry.depends) ||
          !Object.values(entry.depends).every((range) => typeof range === "string")) {
          fail(`${where}: depends is not a table of version ranges`);
        }
      }
      if (entry.provides !== undefined) {
        if (!entry.provides || typeof entry.provides !== "object") fail(`${where}: provides is not an object`);
        for (const [key, value] of Object.entries(entry.provides)) {
          if (!isStringList(value)) fail(`${where}: provides.${key} is not a list of strings`);
        }
      }
      if (entry.yanked !== undefined && typeof entry.yanked !== "boolean") fail(`${where}: yanked is not a boolean`);
    }
  }
  if (index.core !== undefined) {
    const core = index.core;
    if (!core || typeof core !== "object" || !core.versions || typeof core.versions !== "object") {
      fail("index.json: core has no versions");
    }
    if (typeof core.latest !== "string" || !(core.latest in core.versions)) {
      fail(`core: latest ${JSON.stringify(core.latest)} is not one of its versions`);
    }
    for (const [version, entry] of Object.entries(core.versions)) {
      const where = `core ${version}`;
      const file = entry?.file;
      if (typeof file !== "string" || !/^core\/the_harness-[0-9A-Za-z.+!]+-py3-none-any\.whl$/.test(file)) {
        fail(`${where}: file is not core/the_harness-<version>-py3-none-any.whl`);
      }
      if (typeof entry.sha256 !== "string" || !SHA256.test(entry.sha256)) fail(`${where}: sha256 is not 64 hex digits`);
      const wheel = await checkFile(root, where, file);
      if (wheel.byteLength !== entry.size) fail(`${where}: ${file} is ${wheel.byteLength} bytes, index.json says ${entry.size}`);
      const digest = createHash("sha256").update(wheel).digest("hex");
      if (digest !== entry.sha256) fail(`${where}: sha256 mismatch for ${file}`);
    }
  }
  return { index, raw };
}

// ---------- Copy ----------

async function copyTree(from: string, to: string): Promise<void> {
  await Deno.mkdir(to, { recursive: true });
  for await (const entry of Deno.readDir(from)) {
    if (entry.name.startsWith(".") || entry.isSymlink) continue;
    if (entry.isDirectory) await copyTree(`${from}/${entry.name}`, `${to}/${entry.name}`);
    else if (entry.isFile) await Deno.copyFile(`${from}/${entry.name}`, `${to}/${entry.name}`);
  }
}

async function copyRegistry(root: string, index: Index, raw: Uint8Array): Promise<void> {
  await Deno.mkdir(OUT_REGISTRY, { recursive: true });
  for (const [name, pkg] of Object.entries(index.packages)) {
    for (const version of Object.keys(pkg.versions)) {
      await copyTree(`${root}/${name}/${version}`, `${OUT_REGISTRY}/${name}/${version}`);
    }
  }
  if (index.core) {
    await Deno.mkdir(`${OUT_REGISTRY}/core`, { recursive: true });
    for (const entry of Object.values(index.core.versions)) {
      await Deno.copyFile(`${root}/${entry.file}`, `${OUT_REGISTRY}/${entry.file}`);
    }
  }
  // Last, so a reader never sees an index that names files not copied yet.
  await Deno.writeFile(`${OUT_REGISTRY}/index.json`, raw);
}

// ---------- HTML ----------

function esc(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// Markdown through Satteri to hast, then serialized here with an allowlist: raw HTML
// in a README is shown as text, never parsed, and style attributes are dropped.
interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}
const TAGS = new Set([
  "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
  "input", "li", "ol", "p", "pre", "section", "strong", "sup", "sub", "table", "tbody",
  "td", "th", "thead", "tr", "ul",
]);
const VOID = new Set(["br", "hr", "input"]);
const CLASSES = /^(language-[\w+-]+|sr-only|footnotes|task-list-item|contains-task-list|data-footnote-backref)$/;

function safeHref(href: unknown): string | undefined {
  if (typeof href !== "string") return undefined;
  if (href.startsWith("#")) return href;
  return /^(https?:|mailto:)/i.test(href) ? href : undefined;
}

function serialize(node: HastNode): string {
  switch (node.type) {
    case "root":
      return (node.children ?? []).map(serialize).join("");
    case "text":
    case "raw":
      return esc(node.value);
    case "element":
      break;
    default:
      return "";
  }
  const props = node.properties ?? {};
  const inner = (node.children ?? []).map(serialize).join("");
  let tag = node.tagName ?? "";
  if (tag === "img") {
    const alt = esc(props.alt ?? "");
    const href = safeHref(props.src);
    return href ? `<a href="${esc(href)}">${alt || esc(href)}</a>` : alt;
  }
  if (!TAGS.has(tag)) return inner;
  // The page already has its h1: README headings move down one level.
  const heading = /^h([1-6])$/.exec(tag);
  if (heading) tag = `h${Math.min(6, Number(heading[1]) + 1)}`;
  const attrs: string[] = [];
  if (tag === "a") {
    const href = safeHref(props.href);
    if (!href) return inner;
    attrs.push(`href="${esc(href)}"`);
    if (typeof props.ariaLabel === "string") attrs.push(`aria-label="${esc(props.ariaLabel)}"`);
  }
  if (tag === "input") {
    if (props.type !== "checkbox") return "";
    attrs.push('type="checkbox" disabled');
    if (props.checked) attrs.push("checked");
  }
  if (typeof props.id === "string") attrs.push(`id="${esc(props.id)}"`);
  if (Array.isArray(props.className)) {
    const classes = props.className.filter((name) => typeof name === "string" && CLASSES.test(name));
    if (classes.length) attrs.push(`class="${esc(classes.join(" "))}"`);
  }
  const open = `<${tag}${attrs.length ? " " + attrs.join(" ") : ""}>`;
  return VOID.has(tag) ? open : `${open}${inner}</${tag}>`;
}

// A leading h1 is the document's own title ("# computer", "# Changelog"); the page's
// heading already says it.
function markdown(source: string): string {
  const root = markdownToHast(source, { position: false }) as unknown as HastNode;
  const children = root.children ?? [];
  const first = children.findIndex((node) => node.type !== "text" || node.value?.trim());
  if (first >= 0 && children[first].type === "element" && children[first].tagName === "h1") children.splice(first, 1);
  return serialize(root);
}

// ---------- Strings ----------

const STRINGS = {
  en: {
    lang: "en",
    colon: ": ",
    other: ZH,
    otherLabel: "简体中文",
    docs: "/docs/",
    docsLabel: "Documentation",
    packages: "Packages",
    intro: "Installable packages for The Harness. Each adds skills, services, benchmarks or embodiments to an existing install.",
    preview: "The harness, pre-release",
    empty: "No packages are published yet.",
    updated: "Updated",
    latest: "Latest",
    platforms: "Platforms",
    allPlatforms: "any",
    provides: "Provides",
    install: "Install",
    harness: "Harness",
    depends: "Depends on",
    versions: "Versions",
    version: "Version",
    published: "Published",
    download: "Download",
    yanked: "yanked",
    readme: "Readme",
    changelog: "Changelog",
    none: "none",
    allPackages: "All packages",
    notFound: "No such package.",
    labels: {
      kinds: "Kinds",
      embodiments: "Embodiments",
      skills: "Skills",
      benches: "Benchmarks",
      services: "Services",
      profiles: "Profiles",
      experiments: "Experiments",
      agent_skills: "Agent skills",
      commands: "Commands",
      settings: "Settings",
    },
  },
  zh: {
    lang: "zh-CN",
    colon: "：",
    other: "",
    otherLabel: "English",
    docs: "/docs/zh-cn/",
    docsLabel: "文档",
    packages: "包",
    intro: "The Harness 的可安装包。每个包为已有的安装添加 skill、服务、benchmark 或本体。",
    preview: "The Harness 预发布版",
    empty: "还没有发布任何包。",
    updated: "更新于",
    latest: "最新版本",
    platforms: "平台",
    allPlatforms: "任意",
    provides: "提供",
    install: "安装",
    harness: "Harness 版本",
    depends: "依赖",
    versions: "版本",
    version: "版本",
    published: "发布日期",
    download: "下载",
    yanked: "已撤回",
    readme: "说明",
    changelog: "更新日志",
    none: "无",
    allPackages: "全部包",
    notFound: "没有这个包。",
    labels: {
      kinds: "种类",
      embodiments: "本体",
      skills: "Skill",
      benches: "Benchmark",
      services: "服务",
      profiles: "Profile",
      experiments: "实验",
      agent_skills: "Agent skill",
      commands: "命令",
      settings: "设置",
    },
  },
};
type Strings = (typeof STRINGS)["en"];

function base(t: Strings): string {
  return t === STRINGS.en ? "/packages/" : `/packages/${ZH}/`;
}
function otherBase(t: Strings): string {
  return t === STRINGS.en ? `/packages/${ZH}/` : "/packages/";
}

function page(t: Strings, title: string, sub: string, body: string, alternate = true): string {
  const there = otherBase(t) + sub;
  const alternates = alternate
    ? `<link rel="alternate" hreflang="en" href="/packages/${sub}">\n` +
      `<link rel="alternate" hreflang="zh-CN" href="/packages/${ZH}/${sub}">\n`
    : "";
  return `<!doctype html>
<html lang="${t.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; script-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'">
<meta name="color-scheme" content="light dark">
<title>${esc(title)} | The Harness</title>
<link rel="icon" href="/docs/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/packages/packages.css">
<link rel="stylesheet" href="/archive.css">
${alternates}</head>
<body>
<div class="ar-page-crt" aria-hidden="true"><i></i></div>
<header class="bar">
<a class="site" href="${t.docs}">The Harness</a>
<nav>
<a href="${t.docs}">${t.docsLabel}</a>
<a href="${base(t)}"${sub ? "" : ' aria-current="page"'}>${t.packages}</a>
<a href="${alternate ? there : otherBase(t)}" hreflang="${t === STRINGS.en ? "zh-CN" : "en"}">${t.otherLabel}</a>
</nav>
</header>
<main>
${body}
</main>
</body>
</html>
`;
}

function provided(t: Strings, provides: Provides | undefined): string {
  const rows = PROVIDES.filter((key) => provides?.[key]?.length).map((key) =>
    `<dt>${t.labels[key]}</dt><dd>${provides![key]!.map((item) => `<code>${esc(item)}</code>`).join(", ")}</dd>`
  );
  return rows.length ? `<dl class="provides">${rows.join("")}</dl>` : "";
}

function platforms(t: Strings, list: string[] | undefined): string {
  return list?.length ? list.map(esc).join(", ") : t.allPlatforms;
}

function day(value: string | undefined): string {
  return value ? esc(value.slice(0, 10)) : "";
}

function installBlock(name: string): string {
  return `<pre class="install"><code>harness install ${esc(name)}</code></pre>`;
}

function indexPage(t: Strings, index: Index | null): string {
  const names = index ? Object.keys(index.packages).sort() : [];
  let body = `<h1>${t.packages}</h1>\n<p class="lead">${t.intro}</p>\n`;
  const core = index?.core;
  if (core) {
    const url = `https://harness.lmms-lab.com/registry/${core.versions[core.latest].file}`;
    body += `<h2>${t.preview} ${esc(core.latest)}</h2>\n<pre class="install"><code>pip install ${esc(url)}</code></pre>\n`;
  }
  if (!names.length) {
    body += `<p class="empty">${t.empty}</p>\n`;
  } else {
    if (index?.updated) body += `<p class="meta">${t.updated} ${day(index.updated)}</p>\n`;
    body += `<ul class="packages">\n`;
    for (const name of names) {
      const pkg = index!.packages[name];
      const latest = pkg.versions[pkg.latest];
      body += `<li>
<h2><a href="${base(t)}${name}/">${esc(name)}</a> <span class="version">${esc(pkg.latest)}</span></h2>
${pkg.summary ? `<p>${esc(pkg.summary)}</p>` : ""}
<p class="meta">${t.platforms}${t.colon}${platforms(t, latest.platforms)}</p>
${provided(t, latest.provides)}
${installBlock(name)}
</li>\n`;
    }
    body += `</ul>\n`;
  }
  return page(t, t.packages, "", body);
}

function dependsList(t: Strings, index: Index, depends: Record<string, string> | undefined): string {
  const entries = Object.entries(depends ?? {});
  if (!entries.length) return t.none;
  return entries.map(([dep, range]) => {
    const label = `${esc(dep)} <code>${esc(range)}</code>`;
    return dep in index.packages ? `<a href="${base(t)}${esc(dep)}/">${label}</a>` : label;
  }).join("<br>");
}

async function readText(root: string, path: string | undefined): Promise<string | null> {
  return path ? await Deno.readTextFile(`${root}/${path}`) : null;
}

async function packagePage(t: Strings, root: string, index: Index, name: string): Promise<string> {
  const pkg = index.packages[name];
  const latest = pkg.versions[pkg.latest];
  const readme = await readText(root, latest.readme);
  const changelog = await readText(root, latest.changelog);
  const versions = Object.keys(pkg.versions).sort((a, b) =>
    (pkg.versions[b].published ?? "").localeCompare(pkg.versions[a].published ?? "") ||
    b.localeCompare(a, "en", { numeric: true })
  );
  const rows = versions.map((version) => {
    const entry = pkg.versions[version];
    return `<tr${entry.yanked ? ' class="yanked"' : ""}>
<td>${esc(version)}${entry.yanked ? ` <span class="note">(${t.yanked})</span>` : ""}</td>
<td>${entry.harness ? `<code>${esc(entry.harness)}</code>` : ""}</td>
<td>${dependsList(t, index, entry.depends)}</td>
<td><code title="${esc(entry.sha256)}">${esc(entry.sha256.slice(0, 12))}</code></td>
<td>${day(entry.published)}</td>
<td><a href="/registry/${esc(entry.file)}" download>${t.download}</a></td>
</tr>`;
  }).join("\n");
  const body = `<p class="crumb"><a href="${base(t)}">${t.allPackages}</a></p>
<h1>${esc(name)}</h1>
${pkg.summary ? `<p class="lead">${esc(pkg.summary)}</p>` : ""}
${installBlock(name)}
<dl class="facts">
<dt>${t.latest}</dt><dd>${esc(pkg.latest)}</dd>
<dt>${t.harness}</dt><dd>${latest.harness ? `<code>${esc(latest.harness)}</code>` : t.none}</dd>
<dt>${t.platforms}</dt><dd>${platforms(t, latest.platforms)}</dd>
<dt>${t.depends}</dt><dd>${dependsList(t, index, latest.depends)}</dd>
</dl>
${latest.provides && provided(t, latest.provides) ? `<h2>${t.provides}</h2>\n${provided(t, latest.provides)}` : ""}
${readme ? `<h2>${t.readme}</h2>\n<div class="prose">${markdown(readme)}</div>` : ""}
<h2>${t.versions}</h2>
<div class="scroll"><table class="versions">
<thead><tr><th>${t.version}</th><th>${t.harness}</th><th>${t.depends}</th><th>sha256</th><th>${t.published}</th><th></th></tr></thead>
<tbody>
${rows}
</tbody>
</table></div>
${changelog ? `<h2>${t.changelog}</h2>\n<div class="prose">${markdown(changelog)}</div>` : ""}`;
  return page(t, name, `${name}/`, body);
}

function notFoundPage(t: Strings): string {
  return page(t, t.notFound, "", `<h1>${t.notFound}</h1>\n<p><a href="${base(t)}">${t.allPackages}</a></p>`, false);
}

// ---------- Stylesheet ----------

// The Hairline tokens from src/styles/theme.css, light by default and dark by the
// system preference. Fonts are the lab standard from archive.css, linked on every page.
function stylesheet(): string {
  return `/* Generated by docs/tools/registry.ts from the Hairline tokens in src/styles/theme.css. */
:root {
  color-scheme: light dark;
  --radius: 12px;
  --font: var(--ar-body);
  --mono: var(--ar-mono);
  --line: rgba(0, 0, 0, 0.07);
  --header-bg: rgba(255, 255, 255, 0.82);
  --ink: #0a0a0a;
  --gray-1: #171717;
  --gray-2: #404040;
  --gray-3: #737373;
  --gray-4: #a3a3a3;
  --gray-6: #f5f5f5;
  --accent-low: #f4f4f5;
  --plate: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --line: rgba(255, 255, 255, 0.08);
    --header-bg: rgba(8, 9, 10, 0.82);
    --ink: #f4f5f7;
    --gray-1: #d0d6e0;
    --gray-2: #b4b9c2;
    --gray-3: #8a8f98;
    --gray-4: #5b5d64;
    --gray-6: #141517;
    --accent-low: #1c1d20;
    --plate: #08090a;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--plate);
  color: var(--gray-2);
  font: 400 1rem/1.75 var(--font);
}
::selection { background: color-mix(in srgb, var(--ink) 14%, transparent); }
a {
  color: var(--ink);
  text-decoration-color: var(--gray-4);
  text-decoration-thickness: 1px;
  text-underline-offset: 0.2em;
}
a:hover { text-decoration-color: currentColor; }
.bar {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1.5rem;
  background: var(--header-bg);
  border-bottom: 1px solid var(--line);
  backdrop-filter: saturate(1.4) blur(10px);
  -webkit-backdrop-filter: saturate(1.4) blur(10px);
}
.bar a { text-decoration: none; }
.bar .site { color: var(--ink); font-family: var(--ar-display); font-weight: 500; letter-spacing: -0.025em; }
.bar nav { display: flex; flex-wrap: wrap; gap: 1.25rem; font-size: 0.875rem; }
.bar nav a { color: var(--gray-3); }
.bar nav a:hover, .bar nav a[aria-current="page"] { color: var(--ink); }
main { max-width: 46rem; margin: 0 auto; padding: 3rem 1.5rem 5rem; }
h1, h2, h3, h4, h5, h6 { color: var(--ink); font-family: var(--ar-display); font-weight: 500; letter-spacing: -0.025em; line-height: 1.15; }
h1 { font-size: 2.25rem; letter-spacing: -0.035em; margin: 0 0 1rem; }
h2 { font-size: 1.5rem; margin: 3rem 0 1rem; }
h3 { font-size: 1.2rem; margin: 2rem 0 0.75rem; }
h4, h5, h6 { font-size: 1rem; margin: 1.5rem 0 0.5rem; }
.lead { font-size: 1.125rem; color: var(--gray-2); }
.meta, .crumb, .note, .empty { color: var(--gray-3); font-size: 0.875rem; }
.crumb { margin: 0 0 1.5rem; }
code, pre { font-family: var(--mono); }
:not(pre) > code {
  padding: 0.0625rem 0.3125rem;
  border-radius: 5px;
  background: var(--accent-low);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--ink);
  font-size: 0.875em;
}
h2 code, h3 code, a code { padding: 0; box-shadow: none; background: none; color: inherit; }
pre {
  overflow-x: auto;
  padding: 0.875rem 1rem;
  border-radius: var(--radius);
  background: var(--gray-6);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--gray-1);
  font-size: 0.8125rem;
  line-height: 1.6;
}
.packages { list-style: none; margin: 2rem 0 0; padding: 0; border-top: 1px solid var(--line); }
.packages > li { padding: 1.5rem 0; border-bottom: 1px solid var(--line); }
.packages h2 { margin: 0 0 0.5rem; font-size: 1.25rem; }
.packages h2 a { text-decoration: none; }
.packages p { margin: 0.25rem 0; }
.version { color: var(--gray-3); font-family: var(--mono); font-size: 0.875rem; font-weight: 400; letter-spacing: 0; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1.5rem; margin: 1rem 0; font-size: 0.875rem; }
dt { color: var(--gray-3); }
dd { margin: 0; }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th { font-weight: 400; color: var(--gray-3); text-align: start; }
th, td { padding: 0.5rem 0.75rem 0.5rem 0; border-bottom: 1px solid var(--line); vertical-align: top; }
tr.yanked td { color: var(--gray-3); }
.prose blockquote { margin: 1rem 0; padding-inline-start: 1rem; border-inline-start: 1px solid var(--line); color: var(--gray-3); }
.prose hr { border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }
.prose em { font-style: normal; color: var(--gray-3); }
.prose ul.contains-task-list { list-style: none; padding-inline-start: 1rem; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 40rem) {
  .bar { padding: 0.75rem 1rem; }
  main { padding: 2rem 1rem 4rem; }
  h1 { font-size: 1.875rem; }
  dl { grid-template-columns: 1fr; gap: 0; }
  dd { margin-bottom: 0.5rem; }
}
`;
}

// ---------- Main ----------

async function write(path: string, text: string): Promise<void> {
  await Deno.mkdir(path.slice(0, path.lastIndexOf("/")), { recursive: true });
  await Deno.writeTextFile(path, text);
}

async function main(): Promise<void> {
  if (!(await exists(`${DIST}/docs`))) fail("dist/docs is missing: run `deno task build` first");
  const required = Deno.args.includes("--require");
  const given = Deno.args.find((arg) => !arg.startsWith("--"));
  const root = (given ?? Deno.env.get("HARNESS_REGISTRY_DIR") ?? "../../registry").replace(/[\\/]+$/, "");

  let index: Index | null = null;
  let raw: Uint8Array | null = null;
  if (await exists(root)) {
    ({ index, raw } = await validate(root));
  } else if (required) {
    fail(`No registry at ${root}: name a checkout of the registry branch (HARNESS_REGISTRY_DIR)`);
  } else {
    console.log(`No registry at ${root}: writing an empty package listing.`);
  }

  if (index) {
    for (const [name, pkg] of Object.entries(index.packages)) {
      // The site serves public packages only: a listed package must be one of ../packages/.
      // One from private/packages, or one retired from the source, stops the step, so an
      // old copy of the registry cannot put it back on the site.
      if (!NAME.test(name) || !(await exists(`../packages/${name}/package.toml`))) {
        fail(`Package ${name} is not in packages/: the site publishes public packages only`);
      }
      for (const entry of Object.values(pkg.versions)) {
        for (const dependency of Object.keys(entry.depends ?? {})) {
          if (!(dependency in index.packages)) fail(`${name}: missing public dependency ${dependency}`);
        }
      }
    }
  }

  await removeIfPresent(OUT_REGISTRY);
  await removeIfPresent(OUT_PAGES);
  if (index && raw) await copyRegistry(root, index, raw);

  await write(`${OUT_PAGES}/packages.css`, stylesheet());
  for (const t of [STRINGS.en, STRINGS.zh]) {
    const dir = t === STRINGS.en ? OUT_PAGES : `${OUT_PAGES}/${ZH}`;
    await write(`${dir}/index.html`, indexPage(t, index));
    await write(`${dir}/404.html`, notFoundPage(t));
    for (const name of Object.keys(index?.packages ?? {})) {
      await write(`${dir}/${name}/index.html`, await packagePage(t, root, index!, name));
    }
  }
  const count = Object.keys(index?.packages ?? {}).length;
  console.log(index ? `Registry: ${count} package(s) to ${OUT_REGISTRY}/, pages to ${OUT_PAGES}/` : `Pages to ${OUT_PAGES}/`);
}

try {
  await main();
} catch (error) {
  if (!(error instanceof RegistryError)) throw error;
  console.error(`Registry error: ${error.message}`);
  Deno.exit(1);
}
