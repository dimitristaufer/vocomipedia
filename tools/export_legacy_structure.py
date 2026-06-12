#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any, Dict, List

from common import canonical_to_legacy, iter_pack_items, load_pack_manifest, validate_item, write_json


def pack_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pack_code": manifest["pack_code"],
        "language": manifest["language"],
        "lang_prefix": manifest["lang_prefix"],
        "lang_level": manifest["lang_level"],
        "level": manifest.get("level", manifest["lang_level"]),
        "target_sentence_key": manifest.get("target_sentence_key", "jp"),
        "reading_sentence_key": manifest.get("reading_sentence_key", "fu"),
        "data_pack_code": manifest.get("data_pack_code"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export canonical Vocomipedia deck data back to current flat Vocomi structure JSON.")
    ap.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", metavar="DECK_DIR", required=True, type=Path)
    ap.add_argument("--out-json", required=True, type=Path)
    ap.add_argument("--approved-only", action="store_true")
    ap.add_argument("--copy-media-to", default=None, type=Path, help="Copy canonical media next to the exported legacy JSON.")
    args = ap.parse_args()

    manifest = load_pack_manifest(args.pack_dir)
    pack = pack_from_manifest(manifest)
    media_dir = args.pack_dir / "media"
    out: List[Dict[str, Any]] = []
    failures: List[str] = []

    for item, item_path in iter_pack_items(args.pack_dir, approved_only=args.approved_only):
        errors = validate_item(item)
        if errors:
            failures.extend(f"{item_path}: {e}" for e in errors)
            continue
        out.append(canonical_to_legacy(item, pack=pack))
        if args.copy_media_to:
            image = (item.get("media") or {}).get("image_filename")
            if image and (media_dir / image).exists():
                args.copy_media_to.mkdir(parents=True, exist_ok=True)
                shutil.copy2(media_dir / image, args.copy_media_to / image)

    if failures:
        for msg in failures[:50]:
            print(f"ERROR: {msg}")
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more errors")
        return 1

    write_json(args.out_json, out)
    print(f"Exported {len(out)} entries to {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
