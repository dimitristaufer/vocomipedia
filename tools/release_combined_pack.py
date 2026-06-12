#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import iter_pack_items, load_pack_catalog, load_pack_manifest, read_yaml, repo_root_from_tool, validate_item
from export_legacy_structure import pack_from_manifest
from validate_corpus import find_pack_dirs


TOOLS = Path(__file__).resolve().parent


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def level_order(level: str) -> tuple[int, int | str]:
    value = str(level or "").lower()
    jlpt = ["n5", "n4", "n3", "n2", "n1"]
    cefr = ["a1", "a2", "b1", "b2", "c1", "c2"]
    if value in jlpt:
        return (0, jlpt.index(value))
    if value in cefr:
        return (1, cefr.index(value))
    try:
        return (2, int(value))
    except ValueError:
        return (3, value)


def source_path(root: Path, raw: str | Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else root / p


def find_manifests(roots: Iterable[Path]) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for pack_dir in find_pack_dirs(root):
            manifest = load_pack_manifest(pack_dir)
            # Earlier roots win. This lets workflow temp data override checked-in
            # canonical data while still using canonical data for unchanged siblings.
            found.setdefault(str(manifest["pack_code"]).lower(), pack_dir)
    return found


def catalog_combined_codes(catalog: Dict[str, dict], changed_decks: Iterable[str]) -> List[str]:
    groups: Dict[str, list[str]] = {}
    for code, cfg in catalog.items():
        data_code = str(cfg.get("data_pack_code") or "").lower()
        if data_code:
            groups.setdefault(data_code, []).append(code)
    changed = {code.lower() for code in changed_decks}
    out: set[str] = set()
    for code in changed:
        data_code = str((catalog.get(code) or {}).get("data_pack_code") or "").lower()
        if data_code and len(groups.get(data_code, [])) > 1:
            out.add(data_code)
        elif code in groups and len(groups[code]) > 1:
            out.add(code)
    return sorted(out)


def component_codes_for_data_code(catalog: Dict[str, dict], data_pack_code: str) -> List[str]:
    code = data_pack_code.lower()
    components = [
        pack_code
        for pack_code, cfg in catalog.items()
        if str(cfg.get("data_pack_code") or "").lower() == code
    ]
    return sorted(components, key=lambda c: level_order(str(catalog[c].get("lang_level") or c)))


def validate_release_items(pack_dir: Path, release_allowed: set[str], approved_only: bool) -> None:
    failures: list[str] = []
    for item, item_path in iter_pack_items(pack_dir, approved_only=approved_only):
        for error in validate_item(item, release_allowed_licenses=release_allowed, require_release_ready=approved_only):
            failures.append(f"{item_path}: {error}")
    if failures:
        for failure in failures[:100]:
            print(f"ERROR: {failure}")
        if len(failures) > 100:
            print(f"... {len(failures) - 100} more errors")
        raise SystemExit("Combined release validation failed.")


def build_combined(
    *,
    data_pack_code: str,
    component_dirs: List[Path],
    pack_generation_dir: Path,
    outdir: Path,
    approved_only: bool,
    skip_vpack: bool,
    upload: bool,
    chunk_mb: int,
    app_pubkey: Path | None,
    validate_private_key: Path | None,
    release_allowed: set[str],
    upload_retries: int,
    upload_timeout: int,
    upload_max_concurrency: int,
) -> Path:
    manifests = [load_pack_manifest(pack_dir) for pack_dir in component_dirs]
    lang_prefixes = {str(m["lang_prefix"]) for m in manifests}
    if len(lang_prefixes) != 1:
        raise SystemExit(f"{data_pack_code}: cannot combine mixed lang_prefix values: {sorted(lang_prefixes)}")
    lang_prefix = lang_prefixes.pop()
    lang_level = data_pack_code.split("_", 1)[1] if data_pack_code.startswith(f"{lang_prefix}_") else data_pack_code

    for pack_dir in component_dirs:
        validate_release_items(pack_dir, release_allowed, approved_only)

    staging = outdir / "staging" / "combined" / data_pack_code
    if staging.exists():
        shutil.rmtree(staging)
    components_root = staging / "components"
    combined_parent = staging / "combined-assets"
    packs_out = outdir / "packs"
    components_root.mkdir(parents=True, exist_ok=True)
    combined_parent.mkdir(parents=True, exist_ok=True)
    packs_out.mkdir(parents=True, exist_ok=True)

    combined_args: list[str] = []
    for pack_dir, manifest in zip(component_dirs, manifests):
        pack = pack_from_manifest(manifest)
        pack_code = str(manifest["pack_code"])
        component_root = components_root / f"{lang_prefix}_{str(pack['lang_level']).lower()}"
        asset_dir = component_root
        legacy_json = component_root / f"{pack_code}_structure.json"
        asset_dir.mkdir(parents=True, exist_ok=True)
        export_cmd = [
            sys.executable,
            str(TOOLS / "export_legacy_structure.py"),
            "--deck-dir",
            str(pack_dir),
            "--out-json",
            str(legacy_json),
            "--copy-media-to",
            str(asset_dir),
        ]
        if approved_only:
            export_cmd.append("--approved-only")
        run(export_cmd)
        combined_args.extend(["--pack", str(asset_dir), str(legacy_json), lang_prefix, str(pack["lang_level"])])

    build_assets_cmd = [
        sys.executable,
        str(pack_generation_dir / "ios_package_assets_combined.py"),
        *combined_args,
        "--parent-dir",
        str(combined_parent),
        "--clean",
    ]
    run(build_assets_cmd)

    combined_dirs = sorted(p for p in combined_parent.iterdir() if p.is_dir())
    if len(combined_dirs) != 1:
        raise SystemExit(f"Expected one combined asset directory under {combined_parent}, found {combined_dirs}")
    ios_assets = combined_dirs[0] / "iOS_assets"
    if not ios_assets.exists():
        raise SystemExit(f"Combined iOS assets missing: {ios_assets}")

    if skip_vpack:
        print(f"Built combined iOS assets in {ios_assets}")
        return ios_assets

    pubkey = app_pubkey or (pack_generation_dir / "ios_public.pem")
    builder_name = "make_server_language_pack_chunked_upload.py" if upload else "make_server_language_pack_chunked.py"
    pack_cmd = [
        sys.executable,
        str(pack_generation_dir / builder_name),
        "--source",
        str(ios_assets),
        "--lang-prefix",
        lang_prefix,
        "--lang-level",
        lang_level,
        "--pack-kind",
        "data",
        "--outdir",
        str(packs_out),
        "--chunk-mb",
        str(chunk_mb),
        "--app-pubkey",
        str(pubkey),
    ]
    if upload:
        pack_cmd.append("--upload")
        pack_cmd.extend(["--upload-retries", str(upload_retries)])
        pack_cmd.extend(["--upload-timeout", str(upload_timeout)])
        pack_cmd.extend(["--upload-max-concurrency", str(upload_max_concurrency)])
    run(pack_cmd, cwd=pack_generation_dir)

    if validate_private_key:
        vpacks = sorted(packs_out.glob(f"{lang_prefix}_{lang_level}_*.vpack"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not vpacks:
            raise SystemExit(f"No combined .vpack found for {lang_prefix}_{lang_level}.")
        run(
            [
                sys.executable,
                str(TOOLS / "validate_vpack.py"),
                "--vpack",
                str(vpacks[0]),
                "--private-key",
                str(validate_private_key),
                "--require-sqlite",
            ]
        )
    print(f"Built combined release artifacts in {packs_out}")
    return ios_assets


def main() -> int:
    ap = argparse.ArgumentParser(description="Build combined Vocomipedia data packs from canonical component decks.")
    ap.add_argument("--data-pack-code", action="append", help="Combined data pack code to build, e.g. ja_n5-n4. May be repeated.")
    ap.add_argument("--changed-decks", nargs="+", help="Deck codes that changed; builds any affected combined data packs.")
    ap.add_argument("--root", action="append", type=Path, help="Canonical root to search. Earlier roots override later roots.")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("vocomi_pack_generation"), type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--approved-only", action="store_true", default=True)
    ap.add_argument("--include-unapproved", action="store_true")
    ap.add_argument("--skip-vpack", action="store_true")
    ap.add_argument("--chunk-mb", type=int, default=16)
    ap.add_argument("--app-pubkey", default=None, type=Path)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--upload-retries", type=int, default=5)
    ap.add_argument("--upload-timeout", type=int, default=1800)
    ap.add_argument("--upload-max-concurrency", type=int, default=4)
    ap.add_argument("--validate-private-key", default=None, type=Path)
    ap.add_argument("--licenses", default=Path("catalog/licenses.yaml"), type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = source_path(root, args.catalog).resolve()
    pack_generation_dir = source_path(root, args.pack_generation_dir).resolve()
    outdir = source_path(root, args.outdir).resolve()
    roots_arg = args.root or [Path("data/languages")]
    roots = [source_path(root, p).resolve() for p in roots_arg]
    licenses_path = source_path(root, args.licenses).resolve()
    app_pubkey = source_path(root, args.app_pubkey).resolve() if args.app_pubkey else None
    validate_private_key = source_path(root, args.validate_private_key).resolve() if args.validate_private_key else None

    catalog = load_pack_catalog(catalog_path)
    data_codes = set(code.lower() for code in (args.data_pack_code or []))
    if args.changed_decks:
        data_codes.update(catalog_combined_codes(catalog, args.changed_decks))
    if not data_codes:
        print("No affected combined data packs.")
        return 0

    manifests = find_manifests(roots)
    licenses = read_yaml(licenses_path) if licenses_path.exists() else {}
    release_allowed = set((licenses or {}).get("release_allowed", []))
    approved_only = args.approved_only and not args.include_unapproved

    for data_code in sorted(data_codes):
        component_codes = component_codes_for_data_code(catalog, data_code)
        if len(component_codes) < 2:
            print(f"Skipping {data_code}: fewer than two component decks in catalog.")
            continue
        missing = [code for code in component_codes if code not in manifests]
        if missing:
            raise SystemExit(f"{data_code}: missing component deck(s): {', '.join(missing)} in roots {roots}")
        component_dirs = [manifests[code] for code in component_codes]
        print(f"Building combined data pack {data_code} from: {', '.join(component_codes)}")
        if args.dry_run:
            print(f"DRY RUN: would build {data_code} from {component_dirs}")
            continue
        build_combined(
            data_pack_code=data_code,
            component_dirs=component_dirs,
            pack_generation_dir=pack_generation_dir,
            outdir=outdir,
            approved_only=approved_only,
            skip_vpack=args.skip_vpack,
            upload=args.upload,
            chunk_mb=args.chunk_mb,
            app_pubkey=app_pubkey,
            validate_private_key=validate_private_key,
            release_allowed=release_allowed,
            upload_retries=max(1, args.upload_retries),
            upload_timeout=max(60, args.upload_timeout),
            upload_max_concurrency=max(1, args.upload_max_concurrency),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
