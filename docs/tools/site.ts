/**
 * Build the whole site into dist/: the homepage, the documentation of every release and of
 * main, and the version menu that moves between them.
 *
 *   deno task site
 *
 * Every release tag vX.Y.Z of this repository is built from its own tree, so its reference
 * pages come from its own code. The newest release is served at /docs/ (what `pip install`
 * gives), main at /docs/dev/ and each older release at /docs/X.Y.Z/. A repository with no
 * release tag builds main at /docs/ only. The homepage, the banner and the version menu are
 * the current tree's for every version.
 */

const docs = new URL("../", import.meta.url);
const root = new URL("../../", import.meta.url);
// Versions are assembled in .site/ (a tree's own build clears its dist/) and moved to dist/.
const dist = new URL("dist/", docs);
const site = new URL(".site/", docs);
const work = new URL(".versions/", docs);
const path = (url: URL) => decodeURIComponent(url.pathname).replace(/^\/([A-Za-z]:)/, "$1");

async function run(command: string, args: string[], cwd: URL, env: Record<string, string> = {}) {
  const output = await new Deno.Command(command, { args, cwd: path(cwd), env, stdout: "inherit", stderr: "inherit" })
    .output();
  if (!output.success) throw new Error(`${command} ${args.join(" ")} failed in ${path(cwd)}`);
}

async function git(...args: string[]): Promise<string> {
  const output = await new Deno.Command("git", { args, cwd: path(root), stdout: "piped", stderr: "inherit" }).output();
  if (!output.success) throw new Error(`git ${args.join(" ")} failed`);
  return new TextDecoder().decode(output.stdout).trim();
}

/** Release versions, newest first, from the tags vX.Y.Z. */
async function releases(): Promise<string[]> {
  const tags = (await git("tag", "--list", "v*.*.*")).split("\n").filter((tag) => /^v\d+\.\d+\.\d+$/.test(tag));
  const key = (tag: string) => tag.slice(1).split(".").map(Number);
  return tags.sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    return y[0] - x[0] || y[1] - x[1] || y[2] - x[2];
  }).map((tag) => tag.slice(1));
}

async function copyTree(from: URL, to: URL) {
  await Deno.mkdir(to, { recursive: true });
  for await (const entry of Deno.readDir(from)) {
    const source = new URL(entry.name + (entry.isDirectory ? "/" : ""), from);
    const target = new URL(entry.name + (entry.isDirectory ? "/" : ""), to);
    if (entry.isDirectory) await copyTree(source, target);
    else await Deno.copyFile(source, target);
  }
}

async function* files(dir: URL): AsyncGenerator<URL> {
  for await (const entry of Deno.readDir(dir)) {
    const url = new URL(entry.name + (entry.isDirectory ? "/" : ""), dir);
    if (entry.isDirectory) yield* files(url);
    else yield url;
  }
}

/**
 * Build the documentation of one tree under `base` and return the folder it landed in.
 * Trees from before HARNESS_DOCS_BASE existed get their base written into the config.
 */
async function buildTree(tree: URL, base: string): Promise<URL> {
  const folder = new URL("docs/", tree);
  const config = new URL("astro.config.mts", folder);
  const text = await Deno.readTextFile(config);
  if (!text.includes("HARNESS_DOCS_BASE") && base !== "/docs") {
    const [baseLine, outLine] = [/base: "\/docs",/, /outDir: "\.\/dist\/docs",/];
    if (!baseLine.test(text) || !outLine.test(text)) throw new Error(`${path(config)}: no base "/docs" to replace`);
    await Deno.writeTextFile(config, text.replace(baseLine, `base: "${base}",`).replace(outLine, `outDir: "./dist${base}",`));
  }
  await Deno.remove(new URL("dist/", folder), { recursive: true }).catch(() => {});
  if (tree !== root) await run("deno", ["install", "--frozen"], folder);
  await run("deno", ["task", "reference"], folder);
  await run("deno", ["run", "-A", "npm:astro@" + astroVersion(await Deno.readTextFile(new URL("deno.json", folder))), "build"], folder, {
    HARNESS_DOCS_BASE: base,
  });
  return new URL(`dist${base}/`, folder);
}

function astroVersion(denoJson: string): string {
  const spec: string = JSON.parse(denoJson).imports.astro;
  return spec.replace(/^npm:astro@/, "");
}

/** A release's tree: a worktree of its tag, with the current homepage files its header reads. */
async function releaseTree(version: string): Promise<URL> {
  const tree = new URL(`${version}/`, work);
  await git("worktree", "remove", "--force", path(tree)).catch(() => {});
  await Deno.remove(tree, { recursive: true }).catch(() => {});
  await git("-c", "core.autocrlf=false", "worktree", "add", "--detach", path(tree), `v${version}`);
  const design = new URL("design/site-preview/", tree);
  await Deno.remove(design, { recursive: true }).catch(() => {});
  await copyTree(new URL("design/site-preview/", root), design);
  return tree;
}

/**
 * Pages of a version below /docs/X/ keep their hand-written links (`/docs/use/app/`) in their
 * own version. Script bodies are left alone: their CSP hashes must stay valid.
 */
function rebase(html: string, base: string): string {
  const prefix = `${base}/`;
  return html.split(/(<script\b[\s\S]*?<\/script>)/).map((part, index) =>
    index % 2 ? part : part.replace(/((?:href|src|action)=["'])\/docs\/(?!dev\/|\d+\.\d+\.\d+\/)/g, `$1${prefix}`)
  ).join("");
}

/** The version menu's files and data, and its tags in every page's head. */
async function versionMenu(entries: { id: string; path: string; latest?: boolean }[]) {
  const target = new URL("docs/", site);
  await Deno.writeTextFile(new URL("versions.json", target), JSON.stringify({ versions: entries }, null, 2) + "\n");
  for (const name of ["versions.js", "versions.css"]) {
    await Deno.copyFile(new URL(`site/${name}`, docs), new URL(name, target));
  }
  const tags = '<link rel="stylesheet" href="/docs/versions.css"><script type="module" src="/docs/versions.js"></script>';
  const indexed = entries.find((entry) => entry.latest)?.path ?? "/docs/";
  for await (const file of files(target)) {
    if (!file.pathname.endsWith(".html")) continue;
    const url = "/" + path(file).slice(path(site).length).replaceAll("\\", "/");
    const version = entries.filter((entry) => url.startsWith(entry.path)).sort((a, b) => b.path.length - a.path.length)[0];
    let html = await Deno.readTextFile(file);
    if (version && version.path !== "/docs/") html = rebase(html, version.path.slice(0, -1));
    // Only the newest release is for search engines; the others say so.
    const robots = version && version.path !== indexed ? '<meta name="robots" content="noindex">' : "";
    html = html.replace("</head>", `${robots}${tags}</head>`);
    await Deno.writeTextFile(file, html);
  }
}

const versions = await releases();
await Deno.remove(site, { recursive: true }).catch(() => {});
await Deno.mkdir(new URL("docs/", site), { recursive: true });
const entries: { id: string; path: string; latest?: boolean }[] = [];

if (versions.length === 0) {
  await copyTree(await buildTree(root, "/docs"), new URL("docs/", site));
} else {
  const [latest, ...older] = versions;
  await Deno.mkdir(work, { recursive: true });
  try {
    await copyTree(await buildTree(await releaseTree(latest), "/docs"), new URL("docs/", site));
    entries.push({ id: latest, path: "/docs/", latest: true });
    await copyTree(await buildTree(root, "/docs/dev"), new URL("docs/dev/", site));
    entries.push({ id: "dev", path: "/docs/dev/" });
    for (const version of older) {
      await copyTree(await buildTree(await releaseTree(version), `/docs/${version}`), new URL(`docs/${version}/`, site));
      entries.push({ id: version, path: `/docs/${version}/` });
    }
  } finally {
    for (const version of versions) await git("worktree", "remove", "--force", path(new URL(`${version}/`, work))).catch(() => {});
    await Deno.remove(work, { recursive: true }).catch(() => {});
  }
  await versionMenu(entries);
}

// The files at the site root: Vercel's settings, the 404 page and the homepage.
await Deno.remove(dist, { recursive: true }).catch(() => {});
await Deno.rename(site, dist);
await Deno.copyFile(new URL("vercel.json", docs), new URL("vercel.json", dist));
await Deno.copyFile(new URL("docs/404.html", dist), new URL("404.html", dist));
await run("deno", ["run", "--allow-read", "--allow-write=dist", "tools/homepage.ts"], docs);
console.log(`Site: ${entries.length ? entries.map((entry) => `${entry.id} at ${entry.path}`).join(", ") : "main at /docs/"}`);
