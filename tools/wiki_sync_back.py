#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import iter_pack_items, load_pack_catalog, repo_root_from_tool


TOOLS = Path(__file__).resolve().parent
INACTIVE_PROPOSAL_STATUSES = {"applied", "rejected"}


def run(cmd: list[str], cwd: Path) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def source_path(root: Path, pack_generation_dir: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "vocomi_pack_generation":
        return pack_generation_dir.joinpath(*path.parts[1:])
    return root / path


def pack_dir_for(out_root: Path, cfg: Dict[str, Any], code: str) -> Path:
    lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
    return out_root / lang / code


def selected_codes(catalog: Dict[str, Dict[str, Any]], decks: list[str] | None, all_decks: bool) -> list[str]:
    if all_decks or not decks:
        return sorted(catalog)
    wanted = {deck.lower() for deck in decks}
    missing = sorted(wanted - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))
    return [code for code in sorted(catalog) if code in wanted]


def comma_split(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def active_sentence_proposals(pack_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item, path in iter_pack_items(pack_dir):
        for proposal in (item.get("review") or {}).get("sentence_proposals", []) or []:
            if not isinstance(proposal, dict):
                continue
            status = str(proposal.get("status") or "")
            if status in INACTIVE_PROPOSAL_STATUSES:
                continue
            out.append(
                {
                    "item_id": item.get("id"),
                    "entry_id": item.get("entry_id"),
                    "headword": item.get("headword"),
                    "file": str(path),
                    "proposal": proposal,
                }
            )
    return out


def write_summary(
    report_path: Path,
    *,
    rows: list[dict[str, Any]],
    proposal_rows: list[dict[str, Any]],
    export_source: bool,
) -> None:
    lines = [
        "# Vocomipedia Wiki Sync Back",
        "",
        "## Decks",
        "",
        "| Deck | Pulled | Applied files | Exported source | Source diff |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {deck} | {pulled} | {applied_files} | {source} | {changed} |".format(
                deck=row["deck"],
                pulled=row["pulled_count"],
                applied_files=row["applied_files"],
                source=row["source_json"] if export_source else "not requested",
                changed="yes" if row["source_changed"] else "no",
            )
        )
    lines.extend(["", "## Active Sentence Proposals", ""])
    if not proposal_rows:
        lines.append("No active sentence proposals were found.")
    else:
        lines.append("| Deck | Proposal | Item | Sentence | Kind | Status | Analyzer |")
        lines.append("| --- | --- | --- | ---: | --- | --- | --- |")
        for row in proposal_rows:
            proposal = row["proposal"]
            lines.append(
                "| {deck} | `{pid}` | {item} | {sentence} | {kind} | {status} | {analyzer} |".format(
                    deck=row["deck"],
                    pid=proposal.get("id", ""),
                    item=str(row.get("headword") or row.get("entry_id") or row.get("item_id") or "").replace("|", "\\|"),
                    sentence=proposal.get("sentence_index", ""),
                    kind=proposal.get("kind", ""),
                    status=proposal.get("status", ""),
                    analyzer=proposal.get("analyzer", ""),
                )
            )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote sync summary to {report_path}")


def file_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull approved MediaWiki edits, apply them to canonical temp data, and optionally export them back to Vocomi source JSON.")
    ap.add_argument("--decks", nargs="+", help="Deck codes to sync, e.g. ja_n5 de_a2.")
    ap.add_argument("--all", action="store_true", help="Sync every catalog deck.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("../vocomi_pack_generation"), type=Path)
    ap.add_argument("--api-url", default="")
    ap.add_argument("--work-root", default=Path("tmp/wiki-sync-back-data"), type=Path)
    ap.add_argument("--pulled-root", default=Path("tmp/wiki-pull"), type=Path)
    ap.add_argument("--reports-dir", default=Path("reports/wiki-sync-back"), type=Path)
    ap.add_argument("--skip-pull", action="store_true", help="Use existing pulled JSON files; useful for local dry tests.")
    ap.add_argument("--copy-media", action="store_true", help="Copy media into temp canonical decks before validation.")
    ap.add_argument("--export-source", action="store_true", help="Write updated deck content back to catalog source_json files.")
    ap.add_argument("--apply-all-proposals", action="store_true", help="Apply every active sentence proposal after analysis.")
    ap.add_argument("--proposal-id", action="append", help="Apply one proposal id. May be repeated or comma-separated.")
    ap.add_argument("--mark-approved-proposals", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else (root / args.catalog).resolve()
    pack_generation_dir = args.pack_generation_dir if args.pack_generation_dir.is_absolute() else (root / args.pack_generation_dir).resolve()
    work_root = args.work_root if args.work_root.is_absolute() else (root / args.work_root).resolve()
    pulled_root = args.pulled_root if args.pulled_root.is_absolute() else (root / args.pulled_root).resolve()
    reports_dir = args.reports_dir if args.reports_dir.is_absolute() else (root / args.reports_dir).resolve()
    proposal_ids = comma_split(args.proposal_id)

    if not args.skip_pull and not args.api_url:
        raise SystemExit("--api-url is required unless --skip-pull is used.")
    if not pack_generation_dir.exists():
        raise SystemExit(f"pack generation directory does not exist: {pack_generation_dir}")

    catalog = load_pack_catalog(catalog_path)
    codes = selected_codes(catalog, args.decks, args.all)
    if not codes:
        raise SystemExit("No deck codes selected.")

    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    pulled_root.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    proposal_rows: list[dict[str, Any]] = []

    for code in codes:
        cfg = catalog[code]
        source_json = source_path(root, pack_generation_dir, str(cfg.get("source_json") or ""))
        source_asset_dir = source_path(root, pack_generation_dir, str(cfg.get("source_asset_dir") or ""))
        if not source_json.exists():
            raise SystemExit(f"{code}: source_json does not exist: {source_json}")
        if not source_asset_dir.exists():
            raise SystemExit(f"{code}: source_asset_dir does not exist: {source_asset_dir}")

        import_cmd = [
            sys.executable,
            str(TOOLS / "import_legacy_pack.py"),
            "--deck-code",
            code,
            "--input-json",
            str(source_json),
            "--asset-dir",
            str(source_asset_dir),
            "--catalog",
            str(catalog_path),
            "--out-root",
            str(work_root),
            "--mark-approved",
        ]
        if args.copy_media:
            import_cmd.append("--copy-media")
        run(import_cmd, cwd=root)

        pack_dir = pack_dir_for(work_root, cfg, code)
        pulled_dir = pulled_root / code
        if pulled_dir.exists() and not args.skip_pull:
            shutil.rmtree(pulled_dir)
        pulled_count = 0
        if not args.skip_pull:
            run(
                [
                    sys.executable,
                    str(TOOLS / "sync_mediawiki.py"),
                    "pull-api",
                    "--api-url",
                    args.api_url,
                    "--prefix",
                    f"Item:{code}/",
                    "--out-dir",
                    str(pulled_dir),
                ],
                cwd=root,
            )
        pulled_files = sorted(pulled_dir.glob("*.json")) if pulled_dir.exists() else []
        pulled_count = len(pulled_files)

        applied_files = 0
        if pulled_files:
            diff_report = reports_dir / f"wiki-apply-{code}.diff"
            run(
                [
                    sys.executable,
                    str(TOOLS / "apply_pulled_items.py"),
                    "--deck-dir",
                    str(pack_dir),
                    "--pulled-dir",
                    str(pulled_dir),
                    "--backup-dir",
                    str(reports_dir / "backups"),
                    "--diff-report",
                    str(diff_report),
                ],
                cwd=root,
            )
            applied_files = pulled_count

        analysis_report = reports_dir / f"sentence-proposals-analyzed-{code}.diff"
        run(
            [
                sys.executable,
                str(TOOLS / "apply_sentence_proposals.py"),
                "--deck-dir",
                str(pack_dir),
                "--backup-dir",
                str(reports_dir / "backups"),
                "--diff-report",
                str(analysis_report),
            ],
            cwd=root,
        )

        if args.apply_all_proposals or proposal_ids:
            apply_base = [
                sys.executable,
                str(TOOLS / "apply_sentence_proposals.py"),
                "--deck-dir",
                str(pack_dir),
                "--apply",
                "--backup-dir",
                str(reports_dir / "backups"),
                "--diff-report",
                str(reports_dir / f"sentence-proposals-applied-{code}.diff"),
            ]
            if args.mark_approved_proposals:
                apply_base.append("--mark-approved")
            if args.apply_all_proposals:
                run(apply_base, cwd=root)
            for proposal_id in proposal_ids:
                run([*apply_base, "--proposal-id", proposal_id], cwd=root)

        run([sys.executable, str(TOOLS / "validate_corpus.py"), "--root", str(pack_dir)], cwd=root)

        for proposal_row in active_sentence_proposals(pack_dir):
            proposal_row["deck"] = code
            proposal_rows.append(proposal_row)

        before_source = file_bytes(source_json)
        source_changed = False
        if args.export_source:
            export_cmd = [
                sys.executable,
                str(TOOLS / "export_legacy_structure.py"),
                "--deck-dir",
                str(pack_dir),
                "--out-json",
                str(source_json),
                "--approved-only",
            ]
            if args.dry_run:
                print("DRY RUN: would export " + " ".join(export_cmd))
            else:
                run(export_cmd, cwd=root)
                source_changed = file_bytes(source_json) != before_source

        rows.append(
            {
                "deck": code,
                "pulled_count": pulled_count,
                "applied_files": applied_files,
                "source_json": str(source_json),
                "source_changed": source_changed,
            }
        )

    write_summary(reports_dir / "summary.md", rows=rows, proposal_rows=proposal_rows, export_source=args.export_source)
    (reports_dir / "summary.json").write_text(json.dumps({"decks": rows, "active_sentence_proposals": proposal_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
