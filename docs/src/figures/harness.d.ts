/** The layer stack figure (harness.js). */
export const LAYERS: readonly ["shield", "reactive", "programs", "model"];
export function harness(
  el: HTMLElement,
  options?: { hold?: number; lift?: number; label?: string },
): { destroy(): void };
