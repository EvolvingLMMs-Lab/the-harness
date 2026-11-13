// The version menu at the top of the documentation sidebar: which version of the
// documentation this page is, and the same page in another version. tools/site.ts adds this
// script to every page of every version and writes /docs/versions.json beside it.

const chinese = document.documentElement.lang.toLowerCase().startsWith("zh");
const words = chinese
  ? { version: "版本", latest: "最新发布", dev: "main（未发布）" }
  : { version: "Version", latest: "latest release", dev: "main (unreleased)" };

async function mount() {
  const response = await fetch("/docs/versions.json").catch(() => null);
  if (!response?.ok) return;
  const { versions } = await response.json();
  const here = location.pathname;
  const current = versions.filter((entry) => here.startsWith(entry.path)).sort((a, b) => b.path.length - a.path.length)[0];
  if (!current) return;
  const rest = here.slice(current.path.length);

  const label = document.createElement("label");
  label.className = "docs-version";
  const name = document.createElement("span");
  name.textContent = words.version;
  const select = document.createElement("select");
  for (const entry of versions) {
    const option = document.createElement("option");
    option.value = entry.path;
    option.textContent = entry.id === "dev" ? words.dev : entry.latest ? `${entry.id} · ${words.latest}` : entry.id;
    option.selected = entry === current;
    select.append(option);
  }
  // The same page in the chosen version, or that version's start page (in this language)
  // when the page is not there.
  select.addEventListener("change", async () => {
    const target = select.value + rest;
    const found = await fetch(target, { method: "HEAD" }).then((reply) => reply.ok, () => false);
    location.href = found ? target : select.value + (rest.startsWith("zh-cn/") ? "zh-cn/" : "");
  });
  label.append(name, select);

  const anchor = document.querySelector(".docs-home");
  if (anchor) anchor.after(label);
  else document.querySelector(".sidebar-content, nav.sidebar")?.prepend(label);
}

mount();
