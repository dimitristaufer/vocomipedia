#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any, Dict, List

from common import load_pack_catalog, load_pack_manifest, repo_root_from_tool, write_json


def selected_codes(catalog: Dict[str, Dict[str, Any]], decks: list[str] | None, all_decks: bool) -> list[str]:
    if all_decks or not decks:
        return sorted(catalog)
    wanted = {deck.lower() for deck in decks}
    missing = sorted(wanted - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))
    return [code for code in sorted(catalog) if code in wanted]


def pack_dir_for(root: Path, cfg: Dict[str, Any], code: str) -> Path:
    lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
    return root / lang / code


def canonical_pack_dir(repo_root: Path, source_root: Path, cfg: Dict[str, Any], code: str) -> Path:
    raw = cfg.get("canonical_dir")
    if raw:
        path = Path(str(raw))
        return path if path.is_absolute() else repo_root / path
    return pack_dir_for(source_root, cfg, code)


def copy_deck(src: Path, dest: Path, limit: int) -> None:
    if not src.exists():
        raise SystemExit(f"canonical deck does not exist: {src}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    manifest = load_pack_manifest(dest)
    if limit > 0:
        manifest["items"] = list(manifest.get("items") or [])[:limit]
        write_json(dest / "pack.json", manifest)


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy canonical Vocomipedia decks into a release workspace.")
    ap.add_argument("--decks", nargs="+", help="Deck codes to copy.")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--source-root", default=Path("data/languages"), type=Path)
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="Keep only the first N manifest items in copied decks.")
    args = ap.parse_args()

    repo = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else repo / args.catalog
    source_root = args.source_root if args.source_root.is_absolute() else repo / args.source_root
    out_root = args.out_root if args.out_root.is_absolute() else repo / args.out_root
    catalog = load_pack_catalog(catalog_path)
    codes = selected_codes(catalog, args.decks, args.all)
    if not codes:
        raise SystemExit("No deck codes selected.")
    if out_root.exists():
        shutil.rmtree(out_root)
    for code in codes:
        cfg = catalog[code]
        src = canonical_pack_dir(repo, source_root, cfg, code)
        dest = pack_dir_for(out_root, cfg, code)
        copy_deck(src, dest, max(0, args.limit))
        print(f"Copied {code}: {src} -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
