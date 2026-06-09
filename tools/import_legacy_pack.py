#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any, Dict, List

from common import (
    PACK_SCHEMA_VERSION,
    copy_item_media,
    legacy_to_canonical,
    pack_config,
    read_json,
    safe_filename,
    validate_item,
    write_json,
)


def build_manifest(pack: Dict[str, Any], source_json: Path, source_asset_dir: Path, item_refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_code": pack["pack_code"],
        "title": pack.get("title", pack["pack_code"]),
        "language": pack.get("language", pack.get("lang_prefix", "")),
        "lang_prefix": str(pack.get("lang_prefix", "")),
        "lang_level": str(pack.get("lang_level", "")),
        "level": str(pack.get("level", "")),
        "target_sentence_key": pack.get("target_sentence_key", "jp"),
        "reading_sentence_key": pack.get("reading_sentence_key", "fu"),
        "data_pack_code": pack.get("data_pack_code"),
        "source": {
            "kind": "legacy_json",
            "json": str(source_json),
            "asset_dir": str(source_asset_dir),
        },
        "items": item_refs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Import a current Vocomi structure JSON into canonical Vocomipedia items.")
    ap.add_argument("--pack-code", required=True)
    ap.add_argument("--input-json", required=True, type=Path)
    ap.add_argument("--asset-dir", required=True, type=Path)
    ap.add_argument("--out-root", default=Path("vocomipedia/data/languages"), type=Path)
    ap.add_argument("--catalog", default=None, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="Import only the first N entries, for smoke tests.")
    ap.add_argument("--copy-media", action="store_true", help="Copy comic images into the canonical pack media folder.")
    ap.add_argument("--mark-approved", action="store_true", help="Mark imported entries approved. Useful only for controlled smoke releases.")
    args = ap.parse_args()

    pack = pack_config(args.pack_code, args.catalog)
    entries = read_json(args.input_json)
    if not isinstance(entries, list):
        raise SystemExit(f"{args.input_json} must contain a JSON list")
    if args.limit > 0:
        entries = entries[: args.limit]

    pack_dir = args.out_root / str(pack["language"]) / pack["pack_code"]
    items_dir = pack_dir / "items"
    media_dir = pack_dir / "media"
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    items_dir.mkdir(parents=True, exist_ok=True)

    item_refs: List[Dict[str, Any]] = []
    failures: List[str] = []
    for idx, entry in enumerate(entries):
        item = legacy_to_canonical(entry, pack=pack, order=idx, media_root=args.asset_dir)
        if args.mark_approved:
            item["review"]["status"] = "approved"
            item["media"]["license"] = "Vocomi-created"
            item["media"]["review_status"] = "approved"
            item["provenance"]["license_status"] = "generated_by_vocomi"

        filename = safe_filename(item["id"], item["headword"])
        rel = f"items/{filename}"
        errors = validate_item(item)
        if errors:
            failures.extend(f"{item.get('entry_id', '<unknown>')}: {e}" for e in errors)
            continue
        write_json(pack_dir / rel, item)
        if args.copy_media:
            copy_item_media(item, [args.asset_dir], media_dir)
        item_refs.append({"id": item["id"], "entry_id": item["entry_id"], "file": rel, "order": idx})

    if failures:
        for msg in failures[:50]:
            print(f"ERROR: {msg}")
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more errors")
        return 1

    manifest = build_manifest(pack, args.input_json, args.asset_dir, item_refs)
    write_json(pack_dir / "pack.json", manifest)
    print(f"Imported {len(item_refs)} entries into {pack_dir}")
    if args.copy_media:
        print(f"Copied media into {media_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

