#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict

from common import load_pack_catalog, repo_root_from_tool


def selected_codes(catalog: Dict[str, Dict[str, Any]], decks: list[str]) -> list[str]:
    wanted = {deck.lower() for deck in decks}
    missing = sorted(wanted - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))
    return [code for code in sorted(catalog) if code in wanted]


def pack_dir_for(root: Path, cfg: Dict[str, Any], code: str) -> Path:
    lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
    return root / lang / code


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(shlex.quote(part) for part in cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Hydrate release workspace media folders from the production VPS canonical data tree.")
    ap.add_argument("--decks", nargs="+", required=True)
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--root", default=Path("tmp/actions-data"), type=Path, help="Local release workspace root.")
    ap.add_argument("--remote-root", default="/srv/vocomipedia/data/languages")
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--port", default=22, type=int)
    ap.add_argument("--ssh-key", required=True, type=Path)
    args = ap.parse_args()

    repo = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else repo / args.catalog
    root = args.root if args.root.is_absolute() else repo / args.root
    key = args.ssh_key.expanduser().resolve()
    if not key.exists():
        raise SystemExit(f"ssh key does not exist: {key}")
    catalog = load_pack_catalog(catalog_path)

    ssh = f"ssh -i {shlex.quote(str(key))} -p {int(args.port)} -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    for code in selected_codes(catalog, args.decks):
        cfg = catalog[code]
        local_pack = pack_dir_for(root, cfg, code)
        if not (local_pack / "pack.json").exists():
            raise SystemExit(f"{code}: local release workspace deck is missing: {local_pack}")
        local_media = local_pack / "media"
        local_media.mkdir(parents=True, exist_ok=True)
        lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
        remote_media = f"{args.remote_root.rstrip('/')}/{lang}/{code}/media/"
        run(
            [
                "rsync",
                "-a",
                "--delete",
                "-e",
                ssh,
                f"{args.user}@{args.host}:{remote_media}",
                str(local_media) + "/",
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
