#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List

from backup import create_backup
from common import load_pack_catalog, repo_root_from_tool


TOOLS = Path(__file__).resolve().parent


def run(cmd: list[str], dry_run: bool = False) -> None:
    print("+ " + " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def select_pack_codes(catalog: Dict[str, dict], decks: List[str] | None, langs: List[str] | None, all_decks: bool) -> List[str]:
    if all_decks or not decks:
        codes = sorted(catalog)
    else:
        wanted = {p.lower() for p in decks}
        codes = [code for code in sorted(catalog) if code in wanted]
    if langs:
        langset = {l.lower() for l in langs}
        codes = [code for code in codes if str(catalog[code].get("lang_prefix", "")).lower() in langset]
    return codes


def pack_dir_for(out_root: Path, cfg: dict, code: str) -> Path:
    return out_root / str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0]) / code


def source_path(root: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else root / p


def affected_combined_data_codes(catalog: Dict[str, dict], codes: Iterable[str]) -> List[str]:
    groups: Dict[str, list[str]] = {}
    for code, cfg in catalog.items():
        data_code = str(cfg.get("data_pack_code") or "").lower()
        if data_code:
            groups.setdefault(data_code, []).append(code)
    out: set[str] = set()
    for code in codes:
        cfg = catalog.get(code)
        if not cfg:
            continue
        data_code = str(cfg.get("data_pack_code") or "").lower()
        if data_code and len(groups.get(data_code, [])) > 1:
            out.add(data_code)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup-aware sync between vocomi_pack_generation and Vocomipedia canonical deck data.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--out-root", default=Path("data/languages"), type=Path)
    ap.add_argument("--backup-dir", default=Path("backups"), type=Path)
    ap.add_argument("--decks", "--packs", dest="decks", nargs="+")
    ap.add_argument("--langs", nargs="+")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Import only first N rows per deck for validation/smoke sync.")
    ap.add_argument("--copy-media", action="store_true")
    ap.add_argument("--mark-approved", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--strict-media", action="store_true")
    ap.add_argument("--release", action="store_true", help="Build current .vpack artifacts after import.")
    ap.add_argument("--release-outdir", default=Path("release"), type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("vocomi_pack_generation"), type=Path)
    ap.add_argument("--revise-japanese-furigana", action="store_true", help="Run Sudachi-backed Japanese ruby revision after importing Japanese decks.")
    ap.add_argument("--sudachi-dict", choices=["small", "core", "full"], default="core")
    ap.add_argument("--sudachi-mode", choices=["A", "B", "C", "a", "b", "c"], default="C")
    ap.add_argument("--skip-vpack", action="store_true")
    ap.add_argument("--skip-combined-release", action="store_true", help="Do not rebuild affected combined data packs such as ja_n5-n4.")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = source_path(root, str(args.catalog)).resolve()
    out_root = source_path(root, str(args.out_root)).resolve()
    backup_dir = source_path(root, str(args.backup_dir)).resolve()
    pack_generation_dir = source_path(root, str(args.pack_generation_dir)).resolve()
    release_outdir = source_path(root, str(args.release_outdir)).resolve()

    catalog = load_pack_catalog(catalog_path)
    codes = select_pack_codes(catalog, args.decks, args.langs, args.all)
    if not codes:
        print("ERROR: no deck codes selected")
        return 2

    affected = [pack_dir_for(out_root, catalog[code], code) for code in codes]
    if args.release:
        affected.append(release_outdir)
    backup = create_backup(paths=affected, backup_dir=backup_dir, label="sync", base_dir=root)
    print(f"Backup created before sync: {backup}")

    for code in codes:
        cfg = catalog[code]
        src_json = cfg.get("source_json")
        src_asset = cfg.get("source_asset_dir")
        if not src_json or not src_asset:
            print(f"ERROR: catalog entry {code} is missing source_json/source_asset_dir")
            return 2
        cmd = [
            sys.executable,
            str(TOOLS / "import_legacy_pack.py"),
            "--deck-code",
            code,
            "--input-json",
            str(source_path(root, src_json)),
            "--asset-dir",
            str(source_path(root, src_asset)),
            "--out-root",
            str(out_root),
            "--catalog",
            str(catalog_path),
        ]
        if args.limit:
            cmd.extend(["--limit", str(args.limit)])
        if args.copy_media:
            cmd.append("--copy-media")
        if args.mark_approved:
            cmd.append("--mark-approved")
        run(cmd, dry_run=args.dry_run)

        if args.revise_japanese_furigana and str(cfg.get("language") or cfg.get("lang_prefix") or "").lower() == "ja":
            revise_cmd = [
                sys.executable,
                str(TOOLS / "revise_japanese_furigana.py"),
                "--root",
                str(pack_dir_for(out_root, cfg, code)),
                "--sudachi-dict",
                str(args.sudachi_dict),
                "--sudachi-mode",
                str(args.sudachi_mode),
                "--backup-dir",
                str(backup_dir),
            ]
            if args.dry_run:
                revise_cmd.append("--dry-run")
            run(revise_cmd, dry_run=args.dry_run)

    if args.validate:
        cmd = [sys.executable, str(TOOLS / "validate_corpus.py"), "--root", str(out_root)]
        if args.strict_media:
            cmd.append("--strict-media")
        run(cmd, dry_run=args.dry_run)

    if args.release:
        for code in codes:
            pack_dir = pack_dir_for(out_root, catalog[code], code)
            cmd = [
                sys.executable,
                str(TOOLS / "release_pack.py"),
                "--deck-dir",
                str(pack_dir),
                "--pack-generation-dir",
                str(pack_generation_dir),
                "--outdir",
                str(release_outdir),
            ]
            if args.skip_vpack:
                cmd.append("--skip-vpack")
            if args.upload:
                cmd.append("--upload")
            run(cmd, dry_run=args.dry_run)

        combined_codes = affected_combined_data_codes(catalog, codes)
        if combined_codes and not args.skip_combined_release:
            cmd = [
                sys.executable,
                str(TOOLS / "release_combined_pack.py"),
                "--root",
                str(out_root),
                "--catalog",
                str(catalog_path),
                "--pack-generation-dir",
                str(pack_generation_dir),
                "--outdir",
                str(release_outdir),
            ]
            for data_code in combined_codes:
                cmd.extend(["--data-pack-code", data_code])
            if args.skip_vpack:
                cmd.append("--skip-vpack")
            if args.upload:
                cmd.append("--upload")
            run(cmd, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
