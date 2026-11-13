"""Assemble the npm package (@lmmslab/harness) from this source tree:

    python npm/build.py --out dist/npm

The package is the launcher (npm/bin/harness.js) with the Python package next to it
(src/harness, as the wheel has it), README.md and LICENSE, at the version of
harness.__version__. `npm pack` or `npm publish` then runs in the output folder.
"""

import argparse
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def version() -> str:
    text = (ROOT / "src" / "harness" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def build(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    (out / "bin").mkdir(parents=True)
    shutil.copy2(HERE / "bin" / "harness.js", out / "bin" / "harness.js")
    shutil.copytree(ROOT / "src" / "harness", out / "python" / "harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    for name in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / name, out / name)
    package = json.loads((HERE / "package.json").read_text(encoding="utf-8"))
    package["version"] = version()
    (out / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "npm")
    args = parser.parse_args(argv)
    out = build(args.out.resolve())
    print(f"{out}  @lmmslab/harness {version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
