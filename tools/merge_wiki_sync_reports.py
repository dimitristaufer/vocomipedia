#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from wiki_sync_back import write_summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge per-deck wiki sync-back reports into one PR summary.")
    ap.add_argument("--reports-dir", default=Path("reports/wiki-sync-back"), type=Path)
    ap.add_argument("--export-source", action="store_true")
    args = ap.parse_args()

    reports_dir = args.reports_dir.resolve()
    rows: list[dict[str, Any]] = []
    proposal_rows: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*/summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}: invalid JSON: {exc}") from exc
        rows.extend(payload.get("decks") or [])
        proposal_rows.extend(payload.get("active_sentence_proposals") or [])

    rows.sort(key=lambda row: str(row.get("deck") or ""))
    proposal_rows.sort(key=lambda row: (str(row.get("deck") or ""), str(row.get("item_id") or "")))
    write_summary(reports_dir / "summary.md", rows=rows, proposal_rows=proposal_rows, export_source=args.export_source)
    (reports_dir / "summary.json").write_text(
        json.dumps({"decks": rows, "active_sentence_proposals": proposal_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
