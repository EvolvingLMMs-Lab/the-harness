"""Read and act on live DOM nodes in a Chromium isolated world."""

import json


# Chrome runs this in a world separate from page scripts. IDs belong to one document.
# Top-document and open-shadow targets are supported. Iframes and opaque hit targets
# are reported as unresolved so managed input cannot fall through to a different node.
_QUERY = r"""({op, id, x, y, role, text, limit, action, value, expected}) => {
  const state = globalThis.harnessDOM ??= {ids: new WeakMap(), nodes: new Map(), serial: 0};
  const identify = node => {
    let id = state.ids.get(node);
    if (id && state.nodes.has(id)) return id;
    id = ++state.serial;
    state.ids.set(node, id);
    state.nodes.set(id, node);
    if (state.nodes.size > 4096) state.nodes.delete(state.nodes.keys().next().value);
    return id;
  };
  const selector = 'a[href],button,input:not([type=hidden]),textarea,select,summary,[role],[contenteditable=true]';
  const focused = () => {
    let node = document.activeElement;
    while (node?.shadowRoot?.activeElement) node = node.shadowRoot.activeElement;
    return node;
  };
  const hit = () => {
    let node = document.elementFromPoint(x, y);
    while (node?.shadowRoot) {
      const inside = node.shadowRoot.elementFromPoint(x, y);
      if (!inside || node === inside) break;
      node = inside;
    }
    return node;
  };
  const resolve = () => {
    if (id !== undefined) return state.nodes.get(id);
    const node = x == null ? focused() : hit();
    return node?.closest(selector) || node;
  };
  const describe = node => {
    if (!node?.isConnected || /^(IFRAME|FRAME|OBJECT|EMBED)$/.test(node.tagName) ||
        (node.localName?.includes('-') && !node.shadowRoot && !node.matches(selector))) return null;
    const field = node.matches('input,textarea,select,[contenteditable=true]');
    const pressed = node.matches('button,summary,input[type=button],input[type=submit],input[type=image]');
    const role = node.getAttribute('role') ||
      (pressed ? 'button' : node.matches('a[href]') ? 'link' : node.type === 'checkbox' ? 'checkbox' :
       node.type === 'radio' ? 'radio' : node.tagName === 'SELECT' ? 'select' : field ? 'edit' : node.localName);
    const name = (node.getAttribute('aria-label') ||
      [...(node.labels || [])].map(label => label.textContent).join(' ') ||
      (pressed || !field ? node.textContent : node.placeholder || node.name) ||
      (pressed ? node.value : '') || '').trim().slice(0, 200);
    const form = node.form;
    const controls = Array.from(form?.elements || []);
    const submit = /^(submit|image)$/.test(node.type) && !node.matches(':disabled');
    const submitter = submit ? node : controls.find(control => /^(submit|image)$/.test(control.type));
    const method = submitter?.getAttribute('formmethod') || form?.method;
    const destination = submitter?.hasAttribute('formaction') ? submitter.formAction : form?.action;
    const search = method === 'get' && (form?.getAttribute('role') === 'search' ||
      controls.some(control => control.type === 'search'));
    const autocomplete = node.autocomplete || '';
    const password = node.type === 'password' ||
      /(?:^|\s)(?:current-password|new-password|one-time-code|username)(?:\s|$)/i.test(autocomplete);
    let kind = null;
    if (form && method !== 'dialog') {
      if (controls.some(control => control.type === 'password')) kind = 'credentials';
      else if (controls.some(control => /\bcc-/.test(control.autocomplete || ''))) kind = 'payment';
      else if (method === 'post') kind = 'sending';
    }
    const rect = node.getBoundingClientRect();
    const editable = field && !node.readOnly && !node.matches(':disabled') &&
      !/^(file|hidden|checkbox|radio|submit|button|image|reset)$/.test(node.type);
    const actions = ['scroll_into_view'];
    if (node instanceof HTMLElement && !node.matches(':disabled')) actions.push('click', 'invoke');
    if (node.type === 'checkbox') actions.push('toggle');
    if (node.type === 'radio') actions.push('select');
    if (editable) actions.push('set_value');
    return {
      role: search && submit && !kind ? 'search' : role, name, autocomplete,
      states: [...(password ? ['password'] : []), ...(node === focused() ? ['focused'] : []),
               ...(node.checked ? ['checked'] : []), ...(node.matches(':disabled') ? ['disabled'] : [])],
      value: password || /\bcc-/.test(autocomplete) || pressed ? '' :
        String(node.value ?? (node.isContentEditable ? node.textContent : '')).slice(0, 300),
      rect: [rect.left, rect.top, rect.right, rect.bottom].map(Math.round), actions,
      submits: submit ? kind : null,
      enter_submits: submit || (field && node.tagName === 'INPUT') ? kind : null,
      binding: [location.href, node.localName, node.type, name, autocomplete, node.href,
                destination, method, node.formTarget || form?.target, kind, node.matches(':disabled')]
    };
  };
  if (op === 'list') {
    const rows = [];
    const roots = [document];
    let more = 0;
    for (const root of roots) {
      for (const node of root.querySelectorAll('*')) {
        if (node.shadowRoot) roots.push(node.shadowRoot);
        if (!node.matches(selector) || !node.getClientRects().length) continue;
        const row = describe(node);
        if (!row || (role && row.role !== role) ||
            (text && ![row.name, row.value].some(value => value.toLowerCase().includes(text)))) continue;
        if (rows.length < limit) rows.push({...row, id: identify(node)});
        else more++;
      }
    }
    return {rows, more};
  }
  const node = resolve();
  const row = describe(node);
  if (row) row.id = identify(node);
  if (op === 'state') return {ready: document.readyState !== 'loading', focused: row?.id};
  if (op === 'resolve') return row;
  if (!row || row.id !== expected.id || JSON.stringify(row.binding) !== JSON.stringify(expected.binding))
    return {refused: 'the live target changed'};
  if (action === 'insert_text') {
    if (!row.actions.includes('set_value') || node.selectionStart == null)
      return {refused: 'the focused target does not support bound text insertion'};
    node.setRangeText(value, node.selectionStart, node.selectionEnd, 'end');
    node.dispatchEvent(new InputEvent('input', {bubbles: true, composed: true, data: value}));
    return {delivered: true};
  }
  if (!row.actions.includes(action)) return {refused: 'the element does not support this action'};
  if (action === 'scroll_into_view') node.scrollIntoView({block: 'nearest'});
  else if (action === 'set_value') {
    if (node.isContentEditable) node.textContent = value;
    else {
      if (node instanceof HTMLSelectElement && !Array.from(node.options).some(option => option.value === value))
        return {refused: 'no option has that value'};
      const prototype = node instanceof HTMLInputElement ? HTMLInputElement.prototype :
        node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLSelectElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, value);
    }
    node.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
    node.dispatchEvent(new Event('change', {bubbles: true}));
  } else if (action !== 'select' || !node.checked) HTMLElement.prototype.click.call(node);
  return {delivered: true};
}"""


class BrowserDOM:
    """A private Chrome session for querying and delivering to the observed document."""

    def __init__(self, page, page_id):
        self.session = page.context.new_cdp_session(page)
        self.page_id = page_id
        self.document = None
        self.generation = 0
        self.context = None

    def _query(self, op, *, expected_document=None, **arguments):
        frame = self.session.send("Page.getFrameTree")["frameTree"]["frame"]
        document = frame["id"], frame.get("loaderId")
        if expected_document is not None and document != expected_document:
            return {"refused": "the document changed"}
        if self.document != document:
            self.context = self.session.send("Page.createIsolatedWorld", {
                "frameId": frame["id"], "worldName": "harness-dom",
            })["executionContextId"]
            self.document = document
            self.generation += 1
        result = self.session.send("Runtime.evaluate", {
            "expression": f"({_QUERY})({json.dumps({'op': op, **arguments}, allow_nan=False)})",
            "contextId": self.context, "returnByValue": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError("The browser could not inspect or act on the live document")
        return result["result"].get("value")

    def _element_id(self, identifier):
        return f"e{self.page_id}_{self.generation}_{identifier}"

    def state(self):
        observed = self._query("state")
        document = f"{self.page_id}:{self.generation}"
        focused = observed.get("focused")
        return {"page_ready": document if observed["ready"] else None,
                "focus_id": f"{document}:{focused}" if focused else document}

    def elements(self, role, text, limit):
        observed = self._query("list", role=role, text=text, limit=limit)
        for row in observed["rows"]:
            row["id"] = self._element_id(row["id"])
            for key in ("binding", "submits", "enter_submits", "autocomplete"):
                row.pop(key, None)
        return observed

    def target(self, **selector):
        if "id" in selector:
            element_id = selector["id"]
            if "_" not in element_id:
                return None
            identifier = int(element_id.rsplit("_", 1)[1])
            if self._element_id(identifier) != element_id:
                return None
            selector = {"id": identifier}
        row = self._query("resolve", **selector)
        if row is None or ("id" in selector and self._element_id(row["id"]) != element_id):
            return None
        row["key"] = self.page_id, self.generation, row["id"], row["binding"]
        return row

    def act(self, target, action, value=None, **selector):
        generation = self.generation
        if target["key"][:2] != (self.page_id, generation):
            return {"refused": "the document changed"}
        if "id" in selector:
            selector = {"id": target["id"]}
        return self._query("act", expected_document=self.document, action=action, value=value, **selector,
                           expected={"id": target["id"], "binding": target["binding"]})
