#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from common import load_pack_catalog


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve Vocomipedia catalog deck selections for workflows.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--decks", nargs="+", required=True)
    ap.add_argument("--with-combined-siblings", action="store_true")
    args = ap.parse_args()

    catalog = load_pack_catalog(args.catalog)
    selected = [deck.lower() for deck in args.decks]
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
