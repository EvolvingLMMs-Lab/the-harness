import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { AstroIntegration } from "astro";

const CSP_META = /(<meta http-equiv="content-security-policy" content=")([^"]*)(")/;
const INLINE_SCRIPT = /<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g;
const INLINE_STYLE = /<style[^>]*>([\s\S]*?)<\/style>/g;

/**
 * Astro hashes the scripts and styles it bundles, but not Starlight's
 * `is:inline` elements. The documentation keeps a strict policy, so
 * instead of allowing 'unsafe-inline' this adds the hash of
 * every inline element to the page's own CSP meta tag after the build.
 */
export function inlineCspHashes(): AstroIntegration {
  return {
    name: "harness-docs:inline-csp-hashes",
    hooks: {
      "astro:build:done": async ({ dir }) => {
        for (const file of await htmlFiles(fileURLToPath(dir))) {
          const html = await readFile(file, "utf8");
          const updated = withInlineHashes(html);
          if (updated !== html) await writeFile(file, updated);
        }
      },
    },
  };
}

async function htmlFiles(root: string): Promise<string[]> {
  const entries = await readdir(root, { recursive: true });
  return entries
    .filter((entry) => entry.endsWith(".html"))
    .map((entry) => join(root, entry));
}

function withInlineHashes(html: string): string {
  const scriptHashes = elementHashes(html, INLINE_SCRIPT);
  const styleHashes = elementHashes(html, INLINE_STYLE);
  return html.replace(
    CSP_META,
    (_match, start: string, policy: string, end: string) => {
      const directives = policy
        .split(";")
        .map((directive) => directive.trim())
        .filter((directive) => directive.length > 0)
        .map((directive) => {
          if (directive.startsWith("script-src "))
            return withSources(directive, scriptHashes);
          if (directive.startsWith("style-src "))
            return withSources(directive, styleHashes);
          return directive;
        });
      return `${start}${directives.join("; ")}${end}`;
    },
  );
}

function elementHashes(html: string, element: RegExp): string[] {
  return [...html.matchAll(element)].map(
    ([, body = ""]) => `'sha256-${createHash("sha256").update(body).digest("base64")}'`,
  );
}

function withSources(directive: string, sources: string[]): string {
  const present = new Set(directive.split(/\s+/));
  const missing = [...new Set(sources)].filter((source) => !present.has(source));
  return missing.length > 0 ? `${directive} ${missing.join(" ")}` : directive;
}
