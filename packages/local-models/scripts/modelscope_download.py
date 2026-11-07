#!/usr/bin/env python3
"""Download a ModelScope model or dataset folder with resume and sha256 checks.

    python3 scripts/modelscope_download.py model Qwen/Qwen3-VL-8B-Instruct /mnt/.../Qwen3-VL-8B-Instruct
    python3 scripts/modelscope_download.py dataset RoboDojo-Benchmark/RoboDojo DEST --root ckpt/RoboDojo/G05

ModelScope serves large files from a CDN in China, which GPU hosts there can
reach when huggingface.co and its CDN cannot. Files that already match their
sha256 are skipped. Uses curl for transfer, the harness for the checks (its digest()); standard library otherwise.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen

from harness.sdk import digest

API = "https://modelscope.cn/api/v1"


def list_files(kind, repo, root, revision):
    if kind == "model":
        with urlopen(f"{API}/models/{repo}/repo/files?Revision={revision}&Recursive=true", timeout=120) as response:
            files = json.load(response)["Data"]["Files"]
    else:
        # A dataset's tree comes in pages (100 entries unless asked for more).
        files, page = [], 1
        while True:
            url = (f"{API}/datasets/{repo}/repo/tree?Revision={revision}&Root={quote(root)}&Recursive=true"
                   f"&PageSize=1000&PageNumber={page}")
            with urlopen(url, timeout=300) as response:
                data = json.load(response)["Data"]
            files += data["Files"] or []
            if not data["Files"] or len(files) >= int(data.get("TotalCount") or 0):
                break
            page += 1
    return [f for f in files if f.get("Type") in ("blob", None) and f.get("Path")]


def file_url(kind, repo, path, revision):
    section = "models" if kind == "model" else "datasets"
    return f"{API}/{section}/{repo}/repo?Revision={revision}&FilePath={quote(path)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["model", "dataset"])
    parser.add_argument("repo")
    parser.add_argument("dest", type=Path)
    parser.add_argument("--root", default="", help="dataset folder to download")
    parser.add_argument("--revision", default="master")
    parser.add_argument("--parallel", type=int, default=4, help="files downloaded at once")
    parser.add_argument("--exclude", action="append", default=[], help="glob of paths to skip (repeatable)")
    args = parser.parse_args()
    from fnmatch import fnmatch

    files = [f for f in list_files(args.kind, args.repo, args.root, args.revision)
             if not any(fnmatch(f["Path"], pattern) for pattern in args.exclude)]
    total = sum(int(f.get("Size") or 0) for f in files)
    print(f"{len(files)} files, {total / 1e9:.1f} GB", flush=True)

    def fetch(item):
        path = item["Path"]
        relative = path[len(args.root):].lstrip("/") if args.root and path.startswith(args.root) else path
        target = args.dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = (item.get("Sha256") or "").lower()
        size = int(item.get("Size") or -1)
        if target.exists() and expected and target.stat().st_size == size and digest(target) == expected:
            return f"ok   {relative}"
        # The file gets its name only once it is complete and checked; a download in
        # progress (or an earlier one into the name itself) resumes from <name>.part.
        partial = target.with_name(target.name + ".part")
        if target.exists() and not partial.exists():
            target.rename(partial)
        # A stalled CDN connection never errors; abort below 100 KB/s for 60 s and resume.
        command = ["curl", "-L", "--fail", "-C", "-", "--speed-limit", "102400", "--speed-time", "60",
                   "-sS", "-o", str(partial), file_url(args.kind, args.repo, path, args.revision)]
        for attempt in range(60):
            if partial.exists() and partial.stat().st_size == size:
                break
            if attempt:
                time.sleep(min(30, 2 * attempt))  # a refused or dropped connection: wait, then resume
            subprocess.run(command)
        if not partial.exists() or (size >= 0 and partial.stat().st_size != size):
            return f"FAIL {relative} (download)"
        if expected and digest(partial) != expected:
            partial.unlink()
            return f"FAIL {relative} (sha256 mismatch)"
        partial.replace(target)
        return f"done {relative} {target.stat().st_size}"

    from concurrent.futures import ThreadPoolExecutor

    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        for line in pool.map(fetch, files):
            print(line, flush=True)
            failures += line.startswith("FAIL")
    print("COMPLETE" if not failures else f"{failures} FAILED", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
