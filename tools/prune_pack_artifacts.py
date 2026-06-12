#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


PACK_RE = re.compile(r"^(?P<family>.+?)_(?P<timestamp>20\d{6}T\d{6}Z)_(?P<id>[0-9a-f]+)\.vpack$")


def artifact_group(vpack: Path) -> tuple[str, str]:
    match = PACK_RE.match(vpack.name)
    if not match:
        return (vpack.stem, "")
    family = match.group("family")
    meta = vpack.with_name(vpack.name.removesuffix(".vpack") + ".meta.json")
    pack_kind = ""
    if meta.exists():
        try:
            parsed = json.loads(meta.read_text(encoding="utf-8"))
            pack_kind = str(parsed.get("pack_kind") or "")
        except json.JSONDecodeError:
            pack_kind = ""
    return (family, pack_kind)


def timestamp_key(vpack: Path) -> str:
    match = PACK_RE.match(vpack.name)
    if match:
        return match.group("timestamp")
    return str(vpack.stat().st_mtime_ns)


def sidecars(vpack: Path) -> list[Path]:
    base = vpack.name.removesuffix(".vpack")
    return [
        vpack,
        vpack.with_name(base + ".meta.json"),
        vpack.with_name(base + ".sha256"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune stale local .vpack artifacts while keeping recent backups per deck/artifact family.")
    ap.add_argument("--packs-dir", required=True, type=Path)
    ap.add_argument("--keep", default=3, type=int, help="Number of recent artifacts to keep per family/kind.")
    ap.add_argument("--apply", action="store_true", help="Actually delete files. Without this, only prints what would be removed.")
    args = ap.parse_args()

    if args.keep < 1:
        raise SystemExit("--keep must be at least 1")
    if not args.packs_dir.is_dir():
        raise SystemExit(f"packs dir does not exist: {args.packs_dir}")

    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for vpack in sorted(args.packs_dir.glob("*.vpack")):
        groups[artifact_group(vpack)].append(vpack)

    removed = 0
    bytes_removed = 0
    for group, files in sorted(groups.items()):
        ordered = sorted(files, key=timestamp_key, reverse=True)
        stale = ordered[args.keep :]
        for vpack in stale:
            for path in sidecars(vpack):
                if not path.exists():
                    continue
                size = path.stat().st_size
                action = "delete" if args.apply else "would delete"
                print(f"{action}\t{group[0]}\t{group[1]}\t{path}")
                if args.apply:
                    path.unlink()
                removed += 1
                bytes_removed += size

    mode = "Deleted" if args.apply else "Would delete"
    print(f"{mode} {removed} file(s), {bytes_removed / 1024 / 1024:.1f} MiB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
