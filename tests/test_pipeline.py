#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "vocomipedia" / "tools"
FIXTURES = ROOT / "vocomipedia" / "tests" / "fixtures"


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)


class VocomipediaPipelineTests(unittest.TestCase):
    def test_import_validate_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            legacy_json = tmp / "sample_legacy.json"
            shutil.copy2(FIXTURES / "sample_legacy.json", legacy_json)
            asset_dir = tmp / "assets"
            asset_dir.mkdir()
            Image.new("RGBA", (256, 256), (255, 255, 255, 255)).save(asset_dir / "comic_愛__あい__sample_blank.png")

            out_root = tmp / "data"
            run(
                [
                    sys.executable,
                    str(TOOLS / "import_legacy_pack.py"),
                    "--pack-code",
                    "ja_n5",
                    "--input-json",
                    str(legacy_json),
                    "--asset-dir",
                    str(asset_dir),
                    "--out-root",
                    str(out_root),
                    "--copy-media",
                    "--mark-approved",
                ]
            )
            pack_dir = out_root / "ja" / "ja_n5"
            run([sys.executable, str(TOOLS / "validate_corpus.py"), "--root", str(pack_dir), "--strict-media"])

            exported = tmp / "exported.json"
            run(
                [
                    sys.executable,
                    str(TOOLS / "export_legacy_structure.py"),
                    "--pack-dir",
                    str(pack_dir),
                    "--out-json",
                    str(exported),
                    "--approved-only",
                ]
            )
            original = json.loads(legacy_json.read_text(encoding="utf-8"))[0]
            rebuilt = json.loads(exported.read_text(encoding="utf-8"))[0]
            self.assertEqual(rebuilt["entry_id"], original["entry_id"])
            self.assertEqual(rebuilt["word"], original["word"])
            self.assertEqual(rebuilt["jp"], original["jp"])
            self.assertEqual(rebuilt["fu"], original["fu"])
            self.assertEqual(rebuilt["en"], original["en"])
            self.assertEqual(rebuilt["de"], original["de"])
            self.assertEqual(rebuilt["word_en"], original["word_en"])

    def test_release_skip_vpack_builds_sqlite_assets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            legacy_json = tmp / "sample_legacy.json"
            shutil.copy2(FIXTURES / "sample_legacy.json", legacy_json)
            asset_dir = tmp / "assets"
            asset_dir.mkdir()
            Image.new("RGBA", (512, 512), (240, 240, 240, 255)).save(asset_dir / "comic_愛__あい__sample_blank.png")
            out_root = tmp / "data"
            run(
                [
                    sys.executable,
                    str(TOOLS / "import_legacy_pack.py"),
                    "--pack-code",
                    "ja_n5",
                    "--input-json",
                    str(legacy_json),
                    "--asset-dir",
                    str(asset_dir),
                    "--out-root",
                    str(out_root),
                    "--copy-media",
                    "--mark-approved",
                ]
            )
            pack_dir = out_root / "ja" / "ja_n5"
            release_out = tmp / "release"
            run(
                [
                    sys.executable,
                    str(TOOLS / "release_pack.py"),
                    "--pack-dir",
                    str(pack_dir),
                    "--pack-generation-dir",
                    str(ROOT / "vocomi_pack_generation"),
                    "--outdir",
                    str(release_out),
                    "--skip-vpack",
                ]
            )
            db_path = release_out / "staging" / "ja_n5" / "iOS_assets" / "ja_n5.db"
            self.assertTrue(db_path.exists())
            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()

