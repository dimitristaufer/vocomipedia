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


def select_pack_codes(catalog: Dict[str, dict], packs: List[str] | None, langs: List[str] | None, all_packs: bool) -> List[str]:
    if all_packs or not packs:
        codes = sorted(catalog)
    else:
        wanted = {p.lower() for p in packs}
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup-aware sync between vocomi_pack_generation and Vocomipedia canonical data.")
    ap.add_argument("--catalog", default=Path("vocomipedia/catalog/packs.yaml"), type=Path)
    ap.add_argument("--out-root", default=Path("vocomipedia/data/languages"), type=Path)
    ap.add_argument("--backup-dir", default=Path("vocomipedia/backups"), type=Path)
    ap.add_argument("--packs", nargs="+")
    ap.add_argument("--langs", nargs="+")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Import only first N rows per pack for validation/smoke sync.")
    ap.add_argument("--copy-media", action="store_true")
    ap.add_argument("--mark-approved", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--strict-media", action="store_true")
    ap.add_argument("--release", action="store_true", help="Build current .vpack artifacts after import.")
    ap.add_argument("--release-outdir", default=Path("vocomipedia/release"), type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("vocomi_pack_generation"), type=Path)
    ap.add_argument("--skip-vpack", action="store_true")
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
    codes = select_pack_codes(catalog, args.packs, args.langs, args.all)
    if not codes:
        print("ERROR: no pack codes selected")
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
            "--pack-code",
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
                "--pack-dir",
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

