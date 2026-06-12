#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from backup import create_backup
from common import repo_root_from_tool


def run(cmd: list[str], cwd: Path) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup-aware CI validation for Vocomipedia.")
    ap.add_argument("--backup-dir", default=Path("reports/backups"), type=Path)
    ap.add_argument("--pack-generation-dir", default=Path("../vocomi_pack_generation"), type=Path)
    ap.add_argument("--skip-smoke-release", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    pack_generation_dir = args.pack_generation_dir if args.pack_generation_dir.is_absolute() else (root / args.pack_generation_dir).resolve()
    backup = create_backup(
        paths=[root / "data", root / "catalog"],
        backup_dir=(root / args.backup_dir).resolve() if not args.backup_dir.is_absolute() else args.backup_dir,
        label="ci",
        base_dir=root,
    )
    print(f"CI backup created: {backup}")

    run([sys.executable, "-m", "py_compile", *[str(p) for p in sorted((root / "tools").glob("*.py"))]], cwd=root)
    run([sys.executable, "-m", "unittest", "tests.test_pipeline", "-v"], cwd=root)

    if args.skip_smoke_release:
        return 0

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        assets = tmp / "assets"
        assets.mkdir()
        sample = root / "tests" / "fixtures" / "sample_legacy.json"
        sample_copy = tmp / "sample_legacy.json"
        shutil.copy2(sample, sample_copy)
        Image.new("RGBA", (512, 512), (235, 240, 245, 255)).save(assets / "comic_愛__あい__sample_blank.png")
        data_root = tmp / "data"
        release_out = tmp / "release"
        run(
            [
                sys.executable,
                "tools/import_legacy_pack.py",
                "--deck-code",
                "ja_n5",
                "--input-json",
                str(sample_copy),
                "--asset-dir",
                str(assets),
                "--out-root",
                str(data_root),
                "--copy-media",
                "--mark-approved",
            ],
            cwd=root,
        )
        pack_dir = data_root / "ja" / "ja_n5"
        run([sys.executable, "tools/validate_corpus.py", "--root", str(pack_dir), "--strict-media"], cwd=root)
        run(
            [
                sys.executable,
                "tools/release_pack.py",
                "--deck-dir",
                str(pack_dir),
                "--pack-generation-dir",
                str(pack_generation_dir),
                "--outdir",
                str(release_out),
                "--validate-private-key",
                str(pack_generation_dir / "ios_private.pem"),
                "--chunk-mb",
                "1",
            ],
            cwd=root,
        )
        db_path = release_out / "staging" / "ja_n5" / "iOS_assets" / "ja_n5.db"
        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
        finally:
            conn.close()
        if count != 1:
            raise RuntimeError(f"Expected one vocab row in smoke DB, got {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
