import { gzipSync } from "node:zlib";

// Whole-build budgets include deferred JS/CSS. Browser measurements separately
// verify that search stays out of ordinary page loads; these are not LCP claims.
const root = Deno.args[0] ?? "dist/docs";
const limits = {
  javascriptGzipBytes: 64 * 1024,
  cssGzipBytes: 24 * 1024,
  fontBytes: 256 * 1024,
  largestHtmlGzipBytes: 32 * 1024,
};
const totals = {
  javascriptGzipBytes: 0,
  cssGzipBytes: 0,
  fontBytes: 0,
  largestHtmlGzipBytes: 0,
};
let htmlPages = 0;
let bundledScripts = 0;

async function inspect(directory: string): Promise<void> {
  for await (const entry of Deno.readDir(directory)) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory) {
      if (entry.name !== "pagefind") await inspect(path);
      continue;
    }
    if (!entry.isFile) continue;
    if (entry.name.endsWith(".woff2")) {
      totals.fontBytes += (await Deno.stat(path)).size;
      continue;
    }
    if (!/\.(js|css|html)$/.test(entry.name)) continue;
    const compressed = gzipSync(await Deno.readFile(path)).byteLength;
    if (entry.name.endsWith(".js")) {
      totals.javascriptGzipBytes += compressed;
      bundledScripts++;
    } else if (entry.name.endsWith(".css")) {
      totals.cssGzipBytes += compressed;
    } else {
      htmlPages++;
      totals.largestHtmlGzipBytes = Math.max(totals.largestHtmlGzipBytes, compressed);
    }
  }
}

await inspect(root);
if (!htmlPages || !bundledScripts) throw new Error("Build the documentation first");
console.log(JSON.stringify({ htmlPages, totals, limits }, null, 2));
for (const key of Object.keys(limits) as (keyof typeof limits)[]) {
  if (totals[key] > limits[key]) {
    console.error(`Documentation budget exceeded: ${key}`);
    Deno.exitCode = 1;
  }
}
