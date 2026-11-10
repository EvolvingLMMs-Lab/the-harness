import { readFileSync } from "node:fs";
import starlight from "@astrojs/starlight";
import { defineConfig, passthroughImageService } from "astro/config";
import { inlineCspHashes } from "./src/integrations/inline-csp-hashes.ts";
import { satteri } from "@astrojs/markdown-satteri";
import { snippets } from "./src/integrations/snippets.ts";

// Astro finds integrations that import astro:* virtual modules by crawling
// package.json, which this Deno project does not have. Bundle them explicitly.
const astroIntegrationPackages = [
  "@astrojs/starlight",
  "@astrojs/mdx",
  "@astrojs/sitemap",
  "astro-expressive-code",
  "cookie",
];

// The navigation. tests/test_docs.py reads the same file: every page is in it, and every
// entry names a page.
const sidebar = JSON.parse(readFileSync(new URL("./src/sidebar.json", import.meta.url), "utf8"));

// The site is served below /docs on its own domain (the root redirects there), as The
// Simulator's documentation is, so every generated path carries the /docs base and the
// build lands in dist/docs to match it.
export default defineConfig({
  site: "https://harness.lmms-lab.com",
  base: "/docs",
  outDir: "./dist/docs",
  trailingSlash: "always",
  prefetch: { prefetchAll: false, defaultStrategy: "hover" },
  // No raster processing; this keeps the native sharp dependency out.
  image: { service: passthroughImageService() },
  // `--8<-- "path"` inside a code block shows that repository file, so examples cannot drift.
  markdown: { processor: satteri({ mdastPlugins: [snippets] }) },
  vite: {
    // The layer figure is imported from the project page sources beside this directory.
    server: { fs: { allow: [".."] } },
    environments: {
      ssr: { resolve: { noExternal: astroIntegrationPackages } },
      prerender: { resolve: { noExternal: astroIntegrationPackages } },
    },
  },
  security: {
    csp: {
      directives: [
        "default-src 'self'",
        "img-src 'self' data:",
        "media-src 'self'",
        "font-src 'self' data:",
        "connect-src 'self' https://cloudflareinsights.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ],
      // Pagefind compiles its search index reader from WebAssembly. The zone injects
      // Cloudflare Web Analytics.
      scriptDirective: {
        resources: [
          "'self'",
          "'wasm-unsafe-eval'",
          "https://static.cloudflareinsights.com",
        ],
      },
      // Starlight and Expressive Code set style attributes; scripts stay hashed.
      styleDirective: {
        resources: ["'self'", { resource: "'unsafe-inline'", kind: "attribute" }],
      },
    },
  },
  integrations: [
    starlight({
      title: "The Harness",
      description: "The Harness: Automatic Control for anything that acts.",
      favicon: "/favicon.svg",
      // Header icons; Footer.astro repeats them as text links under every page.
      social: [
        { icon: "discord", label: "Discord", href: "https://discord.gg/zhkzEznBs" },
        { icon: "github", label: "GitHub", href: "https://github.com/EvolvingLMMs-Lab/the-harness" },
        { icon: "x.com", label: "X", href: "https://x.com/lmmslab" },
      ],
      // English at the root, Chinese under /zh-cn/; tests require full translation
      // coverage so Starlight's English fallback cannot hide a missing Chinese page.
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        "zh-cn": { label: "简体中文", lang: "zh-CN" },
      },
      // The archive standard (fonts, tokens, CRT layer) is needed before the first paint.
      head: [{ tag: "link", attrs: { rel: "stylesheet", href: "/archive.css" } }],
      customCss: [
        "./src/styles/theme.css",
      ],
      sidebar,
      // "Edit this page" under every page, and when it last changed (from git).
      editLink: { baseUrl: "https://github.com/EvolvingLMMs-Lab/the-harness/edit/main/docs/" },
      lastUpdated: true,
      components: {
        Footer: "./src/components/Footer.astro",
        ThemeProvider: "./src/components/ThemeProvider.astro",
        Search: "./src/components/search/Search.astro",
        SiteTitle: "./src/components/SiteTitle.astro",
      },
      // Code follows the quiet archive surfaces in both reading themes.
      expressiveCode: {
        themes: ["github-dark-default", "github-light-default"],
        useStarlightUiThemeColors: true,
        styleOverrides: {
          borderRadius: "2px",
          borderWidth: "0px",
          codeFontFamily: "var(--__sl-font-mono)",
          codeFontSize: "0.8125rem",
          uiFontFamily: "var(--__sl-font)",
          frames: {
            frameBoxShadowCssValue: "none",
            editorActiveTabIndicatorTopColor: "transparent",
            editorActiveTabIndicatorBottomColor: "var(--sl-color-white)",
          },
        },
      },
    }),
    inlineCspHashes(),
  ],
});
