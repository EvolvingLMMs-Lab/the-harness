/** Narrow types for the untyped Pagefind default UI used by this component. */
export class PagefindUI {
  constructor(options: {
    element: HTMLElement;
    baseUrl: string;
    bundlePath: string;
    showImages: boolean;
    showSubResults: boolean;
    autofocus: boolean;
    translations: Record<string, string>;
  });
  destroy(): void;
}
