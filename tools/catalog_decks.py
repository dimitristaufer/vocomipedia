#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_pack_catalog


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve Vocomipedia catalog deck selections for workflows.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--decks", nargs="*", default=[])
    ap.add_argument("--deck-string", default="", help="Whitespace-separated deck codes from workflow input.")
    ap.add_argument("--all", action="store_true", help="Select every deck in the catalog.")
    ap.add_argument("--combined-data-codes", action="store_true", help="Print affected combined data pack codes instead of deck codes.")
    ap.add_argument("--data-pack-code-components", help="Print component deck codes for this combined data pack code.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--with-combined-siblings", action="store_true")
    args = ap.parse_args()

    catalog = load_pack_catalog(args.catalog)
    groups: dict[str, list[str]] = {}
    for code, cfg in catalog.items():
        data_code = str(cfg.get("data_pack_code") or "").lower()
        if data_code:
            groups.setdefault(data_code, []).append(code)

    if args.data_pack_code_components:
        data_pack_code = args.data_pack_code_components.lower()
        selected = sorted(groups.get(data_pack_code, []))
        if len(selected) < 2:
            raise SystemExit(f"Unknown combined data pack code: {data_pack_code}")
        print(json.dumps(selected) if args.format == "json" else " ".join(selected))
        return 0

    requested_decks = list(args.decks)
    if args.deck_string:
        requested_decks.extend(args.deck_string.split())
    selected = sorted(catalog) if args.all else [deck.lower() for deck in requested_decks]
    if not selected:
        raise SystemExit("Provide at least one deck with --decks, or pass --all.")
    missing = sorted(set(selected) - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))

    out = set(selected)
    if args.with_combined_siblings:
        for code in selected:
            data_code = str(catalog[code].get("data_pack_code") or "").lower()
            siblings = groups.get(data_code, [])
            if len(siblings) > 1:
                out.update(siblings)

    if args.combined_data_codes:
        combined = {
            str(catalog[code].get("data_pack_code") or "").lower()
            for code in selected
            if len(groups.get(str(catalog[code].get("data_pack_code") or "").lower(), [])) > 1
        }
        values = sorted(code for code in combined if code)
    else:
        values = [code for code in sorted(catalog) if code in out]
    print(json.dumps(values) if args.format == "json" else " ".join(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
