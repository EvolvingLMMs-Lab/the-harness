"""Build package files: a deterministic tar.gz of each package (harness.packages.archive),
the same bytes every time from the same files.

    python tools/build.py                   every package, into dist/
    python tools/build.py workspace --out /tmp/files

Prints each file with its sha256. Exit status 1 when a package does not load.
"""

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check import PACKAGES, packages_in  # noqa: E402


def build(folder: Path, out: Path) -> tuple[Path, str]:
    from harness.packages.archive import build as archive
    from harness.packages.manifest import load

    package = load(folder)
    file = Path(out) / f"{package.name}-{package.version}.tar.gz"
    return file, archive(package.path, file, prefix=package.name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", help="packages (default all)")
    parser.add_argument("--root", type=Path, default=PACKAGES)
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    everything = packages_in(args.root)
    unknown = [name for name in args.names if name not in everything]
    if unknown:
        print(f"no package {', '.join(unknown)} under {args.root}", file=sys.stderr)
        return 1
    failed = 0
    for name in args.names or sorted(everything):
        try:
            file, digest = build(everything[name], args.out)
            print(f"{file}  {digest}")
        except ValueError as error:
            print(f"{name}: {error}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
