#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from common import load_pack_catalog, repo_root_from_tool, write_json


def normalize_code(value: str) -> str:
    code = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    if not re.match(r"^[a-z]{2,3}_[a-z0-9]+$", code):
        raise SystemExit(f"Deck code must look like de_b2, ja_n3, or sv_a1; got {value!r}")
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="Add a new Vocomipedia deck level/language to the catalog and create its canonical directory.")
    ap.add_argument("--deck-code", required=True, help="Deck code such as de_b2, ja_n3, or sv_a1.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--language", help="BCP-ish language code. Defaults to the prefix in --deck-code.")
    ap.add_argument("--level", required=True, help="Human-readable level, e.g. B2, N3, HSK 2.")
    ap.add_argument("--data-pack-code", help="Combined data pack code. Defaults to the deck code.")
    ap.add_argument("--source-json", required=True, help="Path to generated source structure JSON, usually under vocomi_pack_generation.")
    ap.add_argument("--source-asset-dir", required=True, help="Path to generated image/audio assets, usually under vocomi_pack_generation.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--out-root", default=Path("data/languages"), type=Path)
    ap.add_argument("--target-sentence-key", default="jp")
    ap.add_argument("--reading-sentence-key", default="fu")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else root / args.catalog
    out_root = args.out_root if args.out_root.is_absolute() else root / args.out_root
    code = normalize_code(args.deck_code)
    language = (args.language or code.split("_", 1)[0]).strip().lower()
    lang_level = code.split("_", 1)[1]

    catalog_obj = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog_obj, dict):
        raise SystemExit(f"Invalid catalog: {catalog_path}")
    catalog_obj.setdefault("schema_version", "vocomipedia-pack-catalog-1")
    packs = catalog_obj.setdefault("packs", {})
    if code in load_pack_catalog(catalog_path):
        raise SystemExit(f"{code} already exists in {catalog_path}")

    packs[code] = {
        "title": args.title,
        "language": language,
        "lang_prefix": language,
        "lang_level": lang_level,
        "level": args.level,
        "source_kind": "single",
        "target_sentence_key": args.target_sentence_key,
        "reading_sentence_key": args.reading_sentence_key,
        "data_pack_code": args.data_pack_code or code,
        "review_policy": "approved-only",
        "license_policy": "restricted-until-audited",
        "source_json": args.source_json,
        "source_asset_dir": args.source_asset_dir,
    }

    pack_dir = out_root / language / code
    manifest = {
        "schema_version": "vocomipedia-pack-1",
        "pack_code": code,
        "title": args.title,
        "language": language,
        "lang_prefix": language,
        "lang_level": lang_level,
        "level": args.level,
        "target_sentence_key": args.target_sentence_key,
        "reading_sentence_key": args.reading_sentence_key,
        "data_pack_code": args.data_pack_code or code,
        "source": {
            "kind": "legacy_json",
            "json": args.source_json,
            "asset_dir": args.source_asset_dir,
        },
        "items": [],
    }

    if args.dry_run:
        print(f"Would add {code} to {catalog_path}")
        print(f"Would create {pack_dir}")
        return 0

    catalog_path.write_text(
        yaml.safe_dump(catalog_obj, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    (pack_dir / "items").mkdir(parents=True, exist_ok=True)
    (pack_dir / "media").mkdir(parents=True, exist_ok=True)
    write_json(pack_dir / "pack.json", manifest)
    print(f"Added {code} to {catalog_path}")
    print(f"Created {pack_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
