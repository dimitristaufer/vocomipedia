#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from common import load_pack_catalog


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve Vocomipedia catalog deck selections for workflows.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--decks", nargs="*", default=[])
    ap.add_argument("--deck-string", default="", help="Whitespace-separated deck codes from workflow input.")
    ap.add_argument("--all", action="store_true", help="Select every deck in the catalog.")
    ap.add_argument("--with-combined-siblings", action="store_true")
    args = ap.parse_args()

    catalog = load_pack_catalog(args.catalog)
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
        groups: dict[str, list[str]] = {}
        for code, cfg in catalog.items():
            data_code = str(cfg.get("data_pack_code") or "").lower()
            if data_code:
                groups.setdefault(data_code, []).append(code)
        for code in selected:
            data_code = str(catalog[code].get("data_pack_code") or "").lower()
            siblings = groups.get(data_code, [])
            if len(siblings) > 1:
                out.update(siblings)

    print(" ".join(code for code in sorted(catalog) if code in out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
