// /docs/llms-full.txt: the Markdown of every English page, in the sidebar's order.
import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import { entries } from "../scripts/llms.ts";

export const GET: APIRoute = async () => {
  const pages = await entries(await getCollection("docs"));
  const parts = pages.map((page) => `# ${page.title}\n\nURL: ${page.url}\n\n${page.body.trim()}\n`);
  return new Response(parts.join("\n---\n\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
