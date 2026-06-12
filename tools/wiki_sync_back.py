#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from common import iter_pack_items, load_pack_catalog, load_pack_manifest, repo_root_from_tool


TOOLS = Path(__file__).resolve().parent
INACTIVE_PROPOSAL_STATUSES = {"applied", "rejected"}


def run(cmd: list[str], cwd: Path) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def pack_dir_for(out_root: Path, cfg: Dict[str, Any], code: str) -> Path:
    lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
    return out_root / lang / code


def canonical_pack_dir(root: Path, canonical_root: Path, cfg: Dict[str, Any], code: str) -> Path:
    raw = cfg.get("canonical_dir")
    if raw:
        path = Path(str(raw))
        return path if path.is_absolute() else root / path
    return pack_dir_for(canonical_root, cfg, code)


def selected_codes(catalog: Dict[str, Dict[str, Any]], decks: list[str] | None, all_decks: bool) -> list[str]:
    if all_decks or not decks:
        return sorted(catalog)
    wanted = {deck.lower() for deck in decks}
    missing = sorted(wanted - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))
    return [code for code in sorted(catalog) if code in wanted]


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
        "| Deck | Pulled | Applied files | Canonical deck | Canonical diff |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {deck} | {pulled} | {applied_files} | {source} | {changed} |".format(
                deck=row["deck"],
                pulled=row["pulled_count"],
                applied_files=row["applied_files"],
                source=row["canonical_dir"] if export_source else "not requested",
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


def tree_digest(root: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    if not root.exists():
        return ""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def copy_pack_dir(src: Path, dest: Path) -> None:
    if not src.exists():
        raise SystemExit(f"canonical deck does not exist: {src}")
    if dest.exists():
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns(".DS_Store", "__pycache__")
    shutil.copytree(src, dest, ignore=ignore)
    # Fail early if the copied path is not a valid canonical deck.
    load_pack_manifest(dest)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull approved MediaWiki edits into Vocomipedia canonical deck data.")
    ap.add_argument("--decks", nargs="+", help="Deck codes to sync, e.g. ja_n5 de_a2.")
    ap.add_argument("--all", action="store_true", help="Sync every catalog deck.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--canonical-root", default=Path("data/languages"), type=Path)
    ap.add_argument("--api-url", default="")
    ap.add_argument("--work-root", default=Path("tmp/wiki-sync-back-data"), type=Path)
    ap.add_argument("--pulled-root", default=Path("tmp/wiki-pull"), type=Path)
    ap.add_argument("--reports-dir", default=Path("reports/wiki-sync-back"), type=Path)
    ap.add_argument("--skip-pull", action="store_true", help="Use existing pulled JSON files; useful for local dry tests.")
    ap.add_argument("--export-source", action="store_true", help="Write updated deck content back to data/languages.")
    ap.add_argument("--no-auto-apply-proposals", action="store_true", help="Leave active sentence proposals in review instead of applying approved wiki proposals.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else (root / args.catalog).resolve()
    canonical_root = args.canonical_root if args.canonical_root.is_absolute() else (root / args.canonical_root).resolve()
    work_root = args.work_root if args.work_root.is_absolute() else (root / args.work_root).resolve()
    pulled_root = args.pulled_root if args.pulled_root.is_absolute() else (root / args.pulled_root).resolve()
    reports_dir = args.reports_dir if args.reports_dir.is_absolute() else (root / args.reports_dir).resolve()

    if not args.skip_pull and not args.api_url:
        raise SystemExit("--api-url is required unless --skip-pull is used.")
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
        canonical_dir = canonical_pack_dir(root, canonical_root, cfg, code)
        pack_dir = pack_dir_for(work_root, cfg, code)
        copy_pack_dir(canonical_dir, pack_dir)

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

        if not args.no_auto_apply_proposals:
            apply_base = [
                sys.executable,
                str(TOOLS / "apply_sentence_proposals.py"),
                "--deck-dir",
                str(pack_dir),
                "--apply",
                "--mark-approved",
                "--backup-dir",
                str(reports_dir / "backups"),
                "--diff-report",
                str(reports_dir / f"sentence-proposals-applied-{code}.diff"),
            ]
            run(apply_base, cwd=root)

        run([sys.executable, str(TOOLS / "validate_corpus.py"), "--root", str(pack_dir)], cwd=root)

        for proposal_row in active_sentence_proposals(pack_dir):
            proposal_row["deck"] = code
            proposal_rows.append(proposal_row)

        before_source = tree_digest(canonical_dir)
        source_changed = False
        if args.export_source:
            if args.dry_run:
                print(f"DRY RUN: would copy {pack_dir} to {canonical_dir}")
            else:
                copy_pack_dir(pack_dir, canonical_dir)
                source_changed = tree_digest(canonical_dir) != before_source

        rows.append(
            {
                "deck": code,
                "pulled_count": pulled_count,
                "applied_files": applied_files,
                "canonical_dir": str(canonical_dir),
                "source_changed": source_changed,
            }
        )

    write_summary(reports_dir / "summary.md", rows=rows, proposal_rows=proposal_rows, export_source=args.export_source)
    (reports_dir / "summary.json").write_text(json.dumps({"decks": rows, "active_sentence_proposals": proposal_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
