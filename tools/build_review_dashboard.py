#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import html
from collections import Counter, defaultdict
from pathlib import Path

from common import iter_pack_items
from validate_corpus import find_pack_dirs


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a static review dashboard for Vocomipedia canonical packs.")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    rows = []
    totals = Counter()
    per_pack = defaultdict(Counter)
    for pack_dir in find_pack_dirs(args.root):
        for item, path in iter_pack_items(pack_dir):
            status = str((item.get("review") or {}).get("status", "unknown"))
            license_status = str((item.get("provenance") or {}).get("license_status", "unknown"))
            media_status = str((item.get("media") or {}).get("review_status", "unknown"))
            pack = str(item.get("pack_code", ""))
            totals[status] += 1
            per_pack[pack][status] += 1
            if status != "approved" or license_status not in {"generated_by_vocomi", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"}:
                rows.append((pack, status, license_status, media_status, item, path))

    parts = [
        "<!doctype html><meta charset='utf-8'><title>Vocomipedia Review Dashboard</title>",
        "<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:6px}th{background:#f4f4f4;text-align:left}.bad{background:#fff3f3}.ok{background:#f3fff5}</style>",
        "<h1>Vocomipedia Review Dashboard</h1>",
        "<h2>Totals</h2>",
        "<ul>",
    ]
    for key, value in sorted(totals.items()):
        parts.append(f"<li>{html.escape(key)}: {value}</li>")
    parts.extend(["</ul>", "<h2>By Pack</h2>", "<table><tr><th>Pack</th><th>Status Counts</th></tr>"])
    for pack, counts in sorted(per_pack.items()):
        summary = ", ".join(f"{html.escape(k)}={v}" for k, v in sorted(counts.items()))
        parts.append(f"<tr><td>{html.escape(pack)}</td><td>{summary}</td></tr>")
    parts.extend(["</table>", "<h2>Needs Attention</h2>", "<table><tr><th>Pack</th><th>Entry</th><th>Headword</th><th>Review</th><th>License</th><th>Media</th><th>File</th></tr>"])
    for pack, status, license_status, media_status, item, path in rows[:1000]:
        cls = "ok" if status == "approved" else "bad"
        parts.append(
            "<tr class='{cls}'><td>{pack}</td><td>{entry}</td><td>{head}</td><td>{status}</td><td>{lic}</td><td>{media}</td><td>{path}</td></tr>".format(
                cls=cls,
                pack=html.escape(pack),
                entry=html.escape(str(item.get("entry_id", ""))),
                head=html.escape(str(item.get("headword", ""))),
                status=html.escape(status),
                lic=html.escape(license_status),
                media=html.escape(media_status),
                path=html.escape(str(path)),
            )
        )
    parts.append("</table>")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote dashboard to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

