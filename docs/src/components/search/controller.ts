/// <reference lib="dom" />
import type { PagefindUI } from "./pagefind.d.ts";

function requiredElement<T extends Element>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (!element) throw new Error(`Missing search element: ${selector}`);
  return element;
}

function loadStylesheet(href: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.addEventListener("load", () => resolve(), { once: true });
    link.addEventListener(
      "error",
      () => {
        link.remove();
        reject(new Error("Search styles failed to load"));
      },
      { once: true },
    );
    document.head.append(link);
  });
}

/** The dialog shell is eager; search code, styles and index wait for an open. */
class DocsSearch extends HTMLElement {
  private dispose?: () => void;

  connectedCallback(): void {
    const openButton = requiredElement<HTMLButtonElement>(this, "[data-open-modal]");
    const closeButton = requiredElement<HTMLButtonElement>(this, "[data-close-modal]");
    const dialog = requiredElement<HTMLDialogElement>(this, "dialog");
    const loading = requiredElement<HTMLElement>(this, "[data-loading]");
    const failure = requiredElement<HTMLElement>(this, "[data-error]");
    const results = requiredElement<HTMLElement>(this, "#docs-search-results");
    const reload = requiredElement<HTMLButtonElement>(this, "[data-reload]");
    const { base, translations, stylesheet } = this.dataset;
    if (!base || !translations || !stylesheet)
      throw new Error("Missing search configuration");
    const events = new AbortController();
    const options = { signal: events.signal };
    let previousFocus: HTMLElement | null = null;
    let started = false;
    let ui: PagefindUI | undefined;

    const focusInput = () => {
      // Closing during a slow import must not move focus back into the dialog.
      if (dialog.open) results.querySelector<HTMLInputElement>("input")?.focus();
    };
    const load = async () => {
      if (this.dataset.dev) return;
      try {
        const [{ createSearch }] = await Promise.all([
          import("./ui.ts"),
          loadStylesheet(stylesheet),
        ]);
        if (events.signal.aborted) return;
        ui = createSearch(results, base, JSON.parse(translations));
        loading.hidden = true;
        // Pagefind inserts the input synchronously, without autofocus of its own.
        focusInput();
      } catch {
        if (events.signal.aborted) return;
        loading.hidden = true;
        failure.hidden = false;
      }
    };
    const open = () => {
      if (dialog.open) return;
      previousFocus =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
      document.body.setAttribute("data-search-modal-open", "");
      if (!started) {
        started = true;
        void load();
      }
      focusInput();
    };

    const apple = /(Mac|iPhone|iPad|iPod)/i.test(navigator.platform);
    const shortcut = requiredElement<HTMLElement>(openButton, "kbd");
    shortcut.textContent = `${apple ? "⌘" : "Ctrl"} K`;
    shortcut.hidden = false;
    openButton.setAttribute("aria-keyshortcuts", apple ? "Meta+K" : "Control+K");
    openButton.disabled = false;
    openButton.addEventListener("click", open, options);
    closeButton.addEventListener("click", () => dialog.close(), options);
    reload.addEventListener("click", () => location.reload(), options);
    dialog.addEventListener(
      "click",
      (event) => {
        if (event.target === dialog) dialog.close();
        if (event.target instanceof Element && event.target.closest("a[href]"))
          dialog.close();
      },
      options,
    );
    dialog.addEventListener(
      "close",
      () => {
        document.body.removeAttribute("data-search-modal-open");
        if (previousFocus?.isConnected) previousFocus.focus();
        else openButton.focus();
      },
      options,
    );
    window.addEventListener(
      "keydown",
      (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
          event.preventDefault();
          if (dialog.open) dialog.close();
          else open();
        }
      },
      options,
    );
    this.dispose = () => {
      events.abort();
      ui?.destroy();
      document.body.removeAttribute("data-search-modal-open");
    };
  }

  disconnectedCallback(): void {
    this.dispose?.();
  }
}

customElements.define("docs-search", DocsSearch);
