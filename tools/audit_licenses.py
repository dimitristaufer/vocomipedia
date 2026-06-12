#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from common import iter_pack_items, read_yaml
from validate_corpus import find_pack_dirs


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a license/provenance audit report for canonical Vocomipedia data.")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--licenses", default=Path("catalog/licenses.yaml"), type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    lic = read_yaml(args.licenses)
    allowed = set((lic or {}).get("release_allowed", []))
    restricted = set((lic or {}).get("restricted", []))

    rows: List[Dict[str, str]] = []
    for pack_dir in find_pack_dirs(args.root):
        for item, _path in iter_pack_items(pack_dir):
            media = item.get("media") or {}
            provenance = item.get("provenance") or {}
            media_license = str(media.get("license") or "")
            status = "allowed" if media_license in allowed else "restricted" if media_license in restricted else "unknown"
            rows.append(
                {
                    "pack_code": str(item.get("pack_code", "")),
                    "entry_id": str(item.get("entry_id", "")),
                    "headword": str(item.get("headword", "")),
                    "review_status": str((item.get("review") or {}).get("status", "")),
                    "media_license": media_license,
                    "license_status": str(provenance.get("license_status", "")),
                    "audit_status": status,
                    "image_filename": str(media.get("image_filename") or ""),
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "pack_code",
                "entry_id",
                "headword",
                "review_status",
                "media_license",
                "license_status",
                "audit_status",
                "image_filename",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    restricted_count = sum(1 for r in rows if r["audit_status"] != "allowed")
    print(f"Wrote {len(rows)} audit row(s) to {args.out}; {restricted_count} need attention.")
    return 1 if restricted_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
