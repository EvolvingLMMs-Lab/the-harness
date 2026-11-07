import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineMdastPlugin } from "satteri";

/** The repository root: docs/src/integrations -> ../../.. */
const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const SNIPPET = /^\s*--8<--\s+"([^"]+)"\s*$/;

/**
 * A line `--8<-- "path"` inside a code block becomes the text of that repository file,
 * so the configuration files the docs show are the real ones. A missing file fails the
 * build.
 */
export const snippets = defineMdastPlugin({
  name: "harness-snippets",
  code(node, ctx) {
    if (!node.value.includes("--8<--")) return;
    const value = node.value
      .split("\n")
      .map((line) => {
        const match = SNIPPET.exec(line);
        if (!match) return line;
        return readFileSync(ROOT + match[1], "utf8").replace(/\r\n/g, "\n").replace(/\n$/, "");
      })
      .join("\n");
    ctx.setProperty(node, "value", value);
  },
});
