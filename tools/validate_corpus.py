#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Set

from common import PACK_SCHEMA_VERSION, iter_pack_items, read_json, validate_item


def validate_pack(pack_dir: Path, strict_media: bool) -> List[str]:
    errors: List[str] = []
    manifest_path = pack_dir / "pack.json"
    if not manifest_path.exists():
        return [f"{pack_dir}: missing pack.json"]
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != PACK_SCHEMA_VERSION:
        errors.append(f"{manifest_path}: unsupported schema_version {manifest.get('schema_version')!r}")
    for key in ("pack_code", "language", "lang_prefix", "lang_level", "items"):
        if key not in manifest:
            errors.append(f"{manifest_path}: missing {key}")

    seen_ids: Set[str] = set()
    seen_entry_ids: Set[str] = set()
    media_root = pack_dir / "media" if strict_media else None
    for item, item_path in iter_pack_items(pack_dir):
        item_errors = validate_item(item, strict_media_root=media_root)
        for err in item_errors:
            errors.append(f"{item_path}: {err}")
        if item.get("id") in seen_ids:
            errors.append(f"{item_path}: duplicate item id {item.get('id')}")
        seen_ids.add(item.get("id"))
        if item.get("entry_id") in seen_entry_ids:
            errors.append(f"{item_path}: duplicate entry_id {item.get('entry_id')}")
        seen_entry_ids.add(item.get("entry_id"))
        if item.get("pack_code") != manifest.get("pack_code"):
            errors.append(f"{item_path}: pack_code does not match manifest")

    return errors


def find_pack_dirs(root: Path) -> List[Path]:
    if (root / "pack.json").exists():
        return [root]
    return sorted(p.parent for p in root.rglob("pack.json"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate Vocomipedia canonical corpus files.")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--strict-media", action="store_true")
    args = ap.parse_args()

    pack_dirs = find_pack_dirs(args.root)
    if not pack_dirs:
        print(f"No pack.json files found under {args.root}")
        return 1

    all_errors: Dict[Path, List[str]] = {}
    total_items = 0
    for pack_dir in pack_dirs:
        errors = validate_pack(pack_dir, args.strict_media)
        if errors:
            all_errors[pack_dir] = errors
        else:
            manifest = read_json(pack_dir / "pack.json")
            total_items += len(manifest.get("items", []))

    if all_errors:
        for pack_dir, errors in all_errors.items():
            print(f"\n{pack_dir}")
            for err in errors[:100]:
                print(f"  ERROR: {err}")
            if len(errors) > 100:
                print(f"  ... {len(errors) - 100} more errors")
        return 1

    print(f"Validated {len(pack_dirs)} pack(s), {total_items} item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

