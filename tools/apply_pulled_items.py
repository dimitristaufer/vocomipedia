#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

from backup import create_backup
from common import load_pack_manifest, read_json, safe_filename, validate_item, write_json


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply pulled MediaWiki canonical item JSON files into an existing Vocomipedia pack.")
    ap.add_argument("--pack-dir", required=True, type=Path)
    ap.add_argument("--pulled-dir", required=True, type=Path)
    ap.add_argument("--backup-dir", default=Path("vocomipedia/backups"), type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = load_pack_manifest(args.pack_dir)
    refs: List[Dict] = list(manifest.get("items", []))
    by_id = {ref["id"]: ref for ref in refs}
    existing_orders = [int(ref.get("order", 0)) for ref in refs]
    next_order = (max(existing_orders) + 1) if existing_orders else 0

    pulled_files = sorted(args.pulled_dir.glob("*.json"))
    if not pulled_files:
        raise SystemExit(f"No pulled JSON files found in {args.pulled_dir}")

    backup = create_backup(paths=[args.pack_dir], backup_dir=args.backup_dir, label="apply-pulled", base_dir=Path.cwd())
    print(f"Backup created before applying pulled items: {backup}", flush=True)

    changed = 0
    for pulled in pulled_files:
        item = read_json(pulled)
        errors = validate_item(item)
        if errors:
            raise SystemExit(f"{pulled}: " + "; ".join(errors))
        if item.get("pack_code") != manifest.get("pack_code"):
            raise SystemExit(f"{pulled}: pack_code {item.get('pack_code')} does not match {manifest.get('pack_code')}")

        ref = by_id.get(item["id"])
        if ref is None:
            rel = f"items/{safe_filename(item['id'], item.get('headword', ''))}"
            ref = {"id": item["id"], "entry_id": item["entry_id"], "file": rel, "order": next_order}
            next_order += 1
            refs.append(ref)
            by_id[item["id"]] = ref
        else:
            ref["entry_id"] = item["entry_id"]

        if args.dry_run:
            print(f"DRY RUN: would write {args.pack_dir / ref['file']}")
        else:
            write_json(args.pack_dir / ref["file"], item)
        changed += 1

    refs.sort(key=lambda r: int(r.get("order", 0)))
    manifest["items"] = refs
    if args.dry_run:
        print(f"DRY RUN: would update {args.pack_dir / 'pack.json'}")
    else:
        write_json(args.pack_dir / "pack.json", manifest)
    print(f"Applied {changed} pulled item(s) into {args.pack_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

