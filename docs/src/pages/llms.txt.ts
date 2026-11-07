// /docs/llms.txt: the pages of the documentation for language models (llmstxt.org): a title,
// a summary, and a link with its description for every English page, in the sidebar's order.
import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import { entries, SITE } from "../scripts/llms.ts";

export const GET: APIRoute = async () => {
  const pages = await entries(await getCollection("docs"));
  const lines = [
    "# The Harness",
    "",
    "> Agentic control for anything that acts: an agent that sees and acts in apps, websites, games and robots, thinks while it acts, and learns as it works.",
    "",
    `The full text of every page is at ${SITE}llms-full.txt.`,
  ];
  let group = "";
  for (const page of pages) {
    if (page.group !== group) {
      group = page.group;
      lines.push("", `## ${group}`, "");
    }
    lines.push(`- [${page.title}](${page.url})${page.description ? `: ${page.description}` : ""}`);
  }
  return new Response(lines.join("\n") + "\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
