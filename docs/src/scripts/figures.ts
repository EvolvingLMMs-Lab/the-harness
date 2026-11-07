/// <reference lib="dom" />
// @ts-types="../figures/harness.d.ts"
import { harness } from "../figures/harness.js";

/**
 * Draws the layer stack into every `[data-figure="harness"]` element as it nears the
 * viewport; `data-hold` names the layer a card keeps open. The hero places its element
 * through frontmatter HTML, so mounting is by attribute rather than per component. The
 * theme follows Starlight's `data-theme` on the root element through the figure's CSS.
 */
function mountFigures(): void {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const element = entry.target as HTMLElement;
        const hold = element.dataset.hold === undefined ? -1 : Number(element.dataset.hold);
        harness(element, { hold, label: element.dataset.figureLabel });
      }
    },
    { rootMargin: "200px" },
  );
  for (const element of document.querySelectorAll<HTMLElement>('[data-figure="harness"]')) {
    observer.observe(element);
  }
}

mountFigures();
