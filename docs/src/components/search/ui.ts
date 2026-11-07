// @ts-types="./pagefind.d.ts"
import { PagefindUI } from "@pagefind/default-ui";

export function createSearch(
  element: HTMLElement,
  baseUrl: string,
  translations: Record<string, string>,
): PagefindUI {
  return new PagefindUI({
    element,
    baseUrl,
    bundlePath: `${baseUrl.replace(/\/$/, "")}/pagefind/`,
    showImages: false,
    showSubResults: true,
    autofocus: false,
    translations,
  });
}
