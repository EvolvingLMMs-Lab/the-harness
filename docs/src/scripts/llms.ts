// The English pages for llms.txt and llms-full.txt, in the order and groups of the sidebar
// (src/sidebar.json). A directory the sidebar fills by itself (the skills, services and
// Python API references) lists its pages by path.
import sidebar from "../sidebar.json" with { type: "json" };

export const SITE = "https://harness.lmms-lab.com/docs/";

type Entry = { id: string; body?: string; data: { title: string; description?: string } };
type Item = string | { label: string; link?: string; items?: Item[]; autogenerate?: { directory: string } };
export type Page = { title: string; description: string; url: string; group: string; body: string };

function slugs(items: Item[], all: string[]): string[] {
  const out: string[] = [];
  for (const item of items) {
    if (typeof item === "string") out.push(item);
    else if (item.link === "/") out.push("");
    else if (item.autogenerate) {
      const directory = item.autogenerate.directory;
      out.push(...all.filter((id) => id === directory || id.startsWith(`${directory}/`)).sort());
    } else if (item.items) out.push(...slugs(item.items, all));
  }
  return out;
}

export async function entries(collection: Entry[]): Promise<Page[]> {
  const english = collection.filter((entry) => entry.id !== "zh-cn" && !entry.id.startsWith("zh-cn/"));
  const byId = new Map(english.map((entry) => [entry.id === "index" ? "" : entry.id, entry]));
  const pages: Page[] = [];
  for (const group of sidebar as { label: string; items: Item[] }[]) {
    for (const slug of slugs(group.items, [...byId.keys()])) {
      const entry = byId.get(slug);
      if (!entry) continue;
      pages.push({
        title: entry.data.title,
        description: entry.data.description ?? "",
        url: `${SITE}${slug ? `${slug}/` : ""}`,
        group: group.label,
        body: entry.body ?? "",
      });
    }
  }
  const changelog = byId.get("changelog");
  if (changelog) {
    pages.push({ title: changelog.data.title, description: changelog.data.description ?? "",
                 url: `${SITE}changelog/`, group: "Project", body: changelog.body ?? "" });
  }
  return pages;
}
