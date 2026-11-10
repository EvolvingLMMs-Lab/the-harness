/** The layer stack figure, shared with the project page (design/site-preview/web/figures/harness.js). */
export const LAYERS: readonly ["shield", "reactive", "programs", "model"];
export function harness(
  el: HTMLElement,
  options?: { hold?: number; lift?: number; label?: string; activity?: boolean },
): { destroy(): void };
