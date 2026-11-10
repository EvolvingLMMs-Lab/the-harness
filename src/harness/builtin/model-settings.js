// Shared by the App and TapTab.
export async function mountModels(root, { api, tr, changed }) {
  function node(tag, props = {}, ...children) {
    const element = Object.assign(document.createElement(tag), props);
    element.append(...children);
    return element;
  }
  const [{ models, path }, { providers, llm }, { agents }] = await Promise.all([
    api("/api/app/models"), api("/api/app"), api("/api/app/agents"),
  ]);
  const sources = [...providers, ...agents.filter((agent) => agent.installed)];
  const source = node("select", { ariaLabel: tr("Provider", "服务商") },
    ...sources.map((provider) => new Option(provider.name, provider.id)));
  source.value = llm.provider || sources[0]?.id || "";
  const query = node("input", { type: "search", placeholder: tr("Search or enter a model ID", "搜索或输入模型 ID"),
    ariaLabel: tr("Model ID", "模型 ID") });
  const endpoint = node("input", { type: "url", placeholder: tr("Base URL", "服务地址") });
  const name = node("input", { placeholder: tr("Display name (optional)", "显示名称（选填）") });
  const levels = node("input", { placeholder: tr("Effort IDs, comma separated", "推理档位 ID，用逗号分隔") });
  const images = node("input", { type: "checkbox", checked: true });
  const reads = node("label", { title: tr("Untick for a text-only model: no picture is sent to it.",
    "纯文本模型请取消勾选：不会向它发送图片。") }, images, " " + tr("Reads images", "能读图"));
  const saved = node("div");
  const matches = node("div", { className: "saved-model-matches" });
  const message = node("div", { role: "status" });
  const details = node("details", {}, node("summary", { textContent: tr("Model details", "模型详情") }),
    node("div", { className: "saved-model-controls" }, name, levels, endpoint, reads));
  let rows = models;
  let catalog = [];
  let selected = null;
  let editing = null;
  let revision = 0;
  const button = (label, onclick) => node("button", { type: "button", textContent: label, onclick });
  async function run(action, operation) {
    action.disabled = true;
    message.textContent = "";
    try { await operation(); } catch (failure) { message.textContent = failure.message; }
    finally { action.disabled = false; }
  }
  async function change(body) {
    ({ models: rows } = await api("/api/app/models", body));
    renderRows();
    await changed?.();
  }
  function choose(row, local = false) {
    if (local) {
      source.value = row.provider;
      reset(false);
      editing = row.id;
    }
    selected = local ? null : row;
    query.value = local ? row.model : row.id;
    name.value = row.name;
    levels.value = (row.efforts || []).join(", ");
    endpoint.value = row.base_url || "";
    // Whether the model reads images: the catalog's or the saved entry's word; unknown reads them.
    images.checked = row.images !== false;
    renderMatches();
    query.focus();
    if (local) details.open = true;
  }
  function renderRows() {
    saved.replaceChildren(...rows.map((row) => {
      const toggle = node("input", { type: "checkbox", role: "switch", checked: row.enabled,
        ariaLabel: tr("Show in picker", "在模型菜单中显示") + " · " + row.name });
      toggle.onchange = () => run(toggle, async () => {
        try { await change({ action: "enable", id: row.id, enabled: toggle.checked }); }
        catch (error) { toggle.checked = row.enabled; throw error; }
      });
      const provider = sources.find(({ id }) => id === row.provider)?.name || row.provider;
      const copy = node("div", {}, node("div", { textContent: row.name }),
        node("small", { textContent: [provider, row.base_url,
          row.images === false ? tr("text only", "纯文本") : null].filter(Boolean).join(" · ") }));
      return node("div", { className: "saved-model-row" }, copy, toggle,
        button(tr("Edit", "编辑"), () => choose(row, true)),
        button(tr("Remove", "移除"), (event) => run(event.currentTarget, () => change({ action: "remove", id: row.id }))));
    }));
    if (!rows.length) saved.append(node("p", { textContent: tr("Add a model to use it in a conversation.", "添加一个模型，即可在会话中选用。") }));
  }
  function renderMatches() {
    const term = query.value.trim().toLowerCase();
    const filtered = catalog.filter((row) => (row.id + " " + row.name).toLowerCase().includes(term)).slice(0, 30);
    matches.replaceChildren(...(selected ? [] : filtered.map((row) => button(row.name, () => choose(row)))));
  }
  function reset(clear = true) {
    revision++;
    editing = selected = null;
    catalog = [];
    if (clear) query.value = "";
    levels.value = name.value = "";
    images.checked = true;
    endpoint.value = source.value === llm.provider ? llm.base_url || "" : "";
    endpoint.hidden = source.value.includes(":") || source.value === "openrouter";
    renderMatches();
  }
  source.onchange = () => reset();
  query.oninput = () => {
    if (selected) {
      selected = null;
      name.value = levels.value = "";
    }
    renderMatches();
  };
  const discover = button(tr("Discover", "查找模型"), (event) => run(event.currentTarget, async () => {
    const stamp = ++revision;
    const result = await api("/api/app/models/catalog?provider=" + encodeURIComponent(source.value));
    if (stamp !== revision) return;
    selected = null;
    catalog = result.models;
    renderMatches();
    if (!catalog.length) message.textContent = tr("This provider returned no model list.", "该服务商未返回模型列表。");
  }));
  const add = button(tr("Save model", "保存模型"), (event) => run(event.currentTarget, async () => {
    const provider = source.value;
    const model = query.value.trim();
    let efforts = levels.value.split(",").map((value) => value.trim()).filter(Boolean);
    if (provider.startsWith("acp:")) {
      const result = await api("/api/app/models/catalog?provider=" + encodeURIComponent(provider) + "&model=" + encodeURIComponent(model));
      if (!result.models.some((row) => row.id === model)) throw new Error(tr("Choose a model offered by this agent.", "请选择该 Agent 提供的模型。"));
      efforts = result.efforts;
    }
    const base_url = endpoint.hidden ? null : endpoint.value.trim() || null;
    const previous = rows.find((row) => row.id === editing || row.provider === provider && row.model === model
      && (row.base_url || null) === base_url);
    await change({ action: "save", id: editing, provider, model, name: name.value.trim(), base_url, efforts,
      enabled: previous?.enabled ?? true, images: images.checked });
    reset();
  }));
  const styles = node("style", { textContent: [
    ".saved-model-row,.saved-model-controls {display:flex;align-items:center;gap:12px;padding:9px 0;flex-wrap:wrap}",
    ".saved-model-row {border-top:1px solid var(--line,#8883)}",
    ".saved-model-row > div {flex:1 1 180px;overflow-wrap:anywhere}",
    ".saved-model-row small,.saved-model-path {display:block;opacity:.65;font-size:.84em;overflow-wrap:anywhere}",
    ".saved-model-controls input,.saved-model-controls select {flex:1 1 120px;min-width:0}",
    ".saved-model-matches {display:grid;gap:3px;max-height:200px;overflow:auto}",
    ".saved-model-matches button {text-align:left}",
  ].join("\n") });
  root.replaceChildren(styles, node("h3", { textContent: tr("Saved models", "已保存的模型") }), saved,
    node("div", { className: "saved-model-controls" }, source, query, discover, add),
    matches, details, message, node("p", { className: "saved-model-path" }, path));
  reset();
  renderRows();
}
