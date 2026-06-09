#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import iter_pack_items, load_pack_manifest
from export_legacy_structure import pack_from_manifest


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build current Vocomi iOS assets and server pack from a Vocomipedia pack.")
    ap.add_argument("--pack-dir", required=True, type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("vocomi_pack_generation"), type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--approved-only", action="store_true", default=True)
    ap.add_argument("--include-unapproved", action="store_true", help="Release every item, including draft/needs_review entries.")
    ap.add_argument("--skip-vpack", action="store_true")
    ap.add_argument("--chunk-mb", type=int, default=16)
    ap.add_argument("--app-pubkey", default=None, type=Path)
    ap.add_argument("--upload", action="store_true", help="Use the existing upload-capable pack builder and upload artifacts to Azure.")
    ap.add_argument("--upload-retries", type=int, default=5)
    ap.add_argument("--upload-timeout", type=int, default=1800)
    ap.add_argument("--upload-max-concurrency", type=int, default=4)
    ap.add_argument("--validate-private-key", default=None, type=Path, help="Decrypt and validate the generated .vpack after build.")
    args = ap.parse_args()
    args.pack_dir = args.pack_dir.resolve()
    args.pack_generation_dir = args.pack_generation_dir.resolve()
    args.outdir = args.outdir.resolve()
    if args.app_pubkey:
        args.app_pubkey = args.app_pubkey.resolve()
    if args.validate_private_key:
        args.validate_private_key = args.validate_private_key.resolve()

    manifest = load_pack_manifest(args.pack_dir)
    pack = pack_from_manifest(manifest)
    approved_only = args.approved_only and not args.include_unapproved

    selected_count = sum(1 for _item, _path in iter_pack_items(args.pack_dir, approved_only=approved_only))
    if selected_count == 0:
        raise SystemExit("No releasable items selected.")

    staging = args.outdir / "staging" / manifest["pack_code"]
    legacy_asset_dir = staging / "legacy_assets"
    ios_assets_dir = staging / "iOS_assets"
    packs_out = args.outdir / "packs"
    legacy_json = legacy_asset_dir / f"{manifest['pack_code']}_structure.json"
    legacy_asset_dir.mkdir(parents=True, exist_ok=True)
    ios_assets_dir.mkdir(parents=True, exist_ok=True)
    packs_out.mkdir(parents=True, exist_ok=True)

    export_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "export_legacy_structure.py"),
        "--pack-dir",
        str(args.pack_dir),
        "--out-json",
        str(legacy_json),
        "--copy-media-to",
        str(legacy_asset_dir),
    ]
    if approved_only:
        export_cmd.append("--approved-only")
    run(export_cmd)

    run(
        [
            sys.executable,
            str(args.pack_generation_dir / "ios_package_assets.py"),
            "--asset-dir",
            str(legacy_asset_dir),
            "--json-file",
            str(legacy_json),
            "--lang-prefix",
            str(pack["lang_prefix"]),
            "--lang-level",
            str(pack["lang_level"]),
            "--output-dir",
            str(ios_assets_dir),
        ]
    )

    if args.skip_vpack:
        print(f"Built iOS assets in {ios_assets_dir}")
        return 0

    pubkey = args.app_pubkey or (args.pack_generation_dir / "ios_public.pem")
    builder_name = "make_server_language_pack_chunked_upload.py" if args.upload else "make_server_language_pack_chunked.py"
    cmd = [
        sys.executable,
        str(args.pack_generation_dir / builder_name),
        "--source",
        str(ios_assets_dir),
        "--lang-prefix",
        str(pack["lang_prefix"]),
        "--lang-level",
        str(pack["lang_level"]),
        "--app-pubkey",
        str(pubkey),
        "--outdir",
        str(packs_out),
        "--chunk-mb",
        str(args.chunk_mb),
        "--pack-kind",
        "data",
    ]
    data_pack_code = pack.get("data_pack_code")
    if data_pack_code:
        cmd.extend(["--data-pack-code", str(data_pack_code)])
    if args.upload:
        cmd.append("--upload")
        cmd.extend(["--upload-retries", str(args.upload_retries)])
        cmd.extend(["--upload-timeout", str(args.upload_timeout)])
        cmd.extend(["--upload-max-concurrency", str(args.upload_max_concurrency)])
    run(cmd, cwd=args.pack_generation_dir)
    if args.validate_private_key:
        vpacks = sorted(packs_out.glob("*.vpack"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not vpacks:
            raise SystemExit("No .vpack artifact found to validate.")
        validate_cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "validate_vpack.py"),
            "--vpack",
            str(vpacks[0]),
            "--private-key",
            str(args.validate_private_key),
            "--require-sqlite",
        ]
        run(validate_cmd)
    print(f"Built release artifacts in {packs_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
