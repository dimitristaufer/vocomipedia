#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / "docker" / "local" / ".env"
PACK_GENERATION_DIR = ROOT.parent / "vocomi_pack_generation"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k] = v
    return out


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True, env=env)


def main() -> int:
    if not LOCAL_ENV.exists():
        run([sys.executable, "tools/local_mediawiki.py", "init"])
    cfg = read_env(LOCAL_ENV)

    with tempfile.TemporaryDirectory(prefix="vocomipedia-local-e2e.") as td:
        tmp = Path(td)
        assets = tmp / "assets"
        assets.mkdir()
        sample = tmp / "sample_legacy.json"
        catalog = tmp / "packs.yaml"
        shutil.copy2(ROOT / "tests" / "fixtures" / "sample_legacy.json", sample)
        Image.new("RGBA", (512, 512), (236, 240, 244, 255)).save(assets / "comic_愛__あい__sample_blank.png")
        catalog.write_text(
            f"""schema_version: vocomipedia-pack-catalog-1
packs:
  ja_e2e:
    title: Japanese E2E Smoke
    language: ja
    lang_prefix: ja
    lang_level: n5
    level: N5
    source_kind: single
    target_sentence_key: jp
    reading_sentence_key: fu
    data_pack_code: ja_n5-n4
    review_policy: approved-only
    license_policy: test
    source_json: {sample}
    source_asset_dir: {assets}
""",
            encoding="utf-8",
        )

        data_root = tmp / "data"
        pack_dir = data_root / "ja" / "ja_e2e"
        wiki_pages = tmp / "wiki-pages"
        pulled = tmp / "pulled"
        release = tmp / "release"

        run([
            sys.executable,
            "tools/import_legacy_pack.py",
            "--deck-code", "ja_e2e",
            "--input-json", str(sample),
            "--asset-dir", str(assets),
            "--catalog", str(catalog),
            "--out-root", str(data_root),
            "--copy-media",
            "--mark-approved",
        ])
        run([sys.executable, "tools/validate_corpus.py", "--root", str(pack_dir), "--strict-media"])
        run([sys.executable, "tools/sync_mediawiki.py", "generate", "--deck-dir", str(pack_dir), "--out-dir", str(wiki_pages), "--approved-only"])
        manifest = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
        item_suffix = str(manifest["items"][0]["id"]).split(":")[-1]

        env = os.environ.copy()
        env["MEDIAWIKI_USERNAME"] = cfg["MW_BOT_USER"]
        env["MEDIAWIKI_PASSWORD"] = cfg["MW_BOT_PASSWORD"]
        api = f"{cfg['MW_SERVER']}/api.php"
        run([sys.executable, "tools/sync_mediawiki.py", "push-api", "--deck-dir", str(pack_dir), "--api-url", api, "--approved-only", "--skip-index-pages"], env=env)
        run([sys.executable, "tools/sync_mediawiki.py", "pull-api", "--api-url", api, "--prefix", f"Item:ja_e2e/{item_suffix}", "--out-dir", str(pulled)])
        run([sys.executable, "tools/apply_pulled_items.py", "--deck-dir", str(pack_dir), "--pulled-dir", str(pulled), "--backup-dir", str(tmp / "backups")])
        run([sys.executable, "tools/validate_corpus.py", "--root", str(pack_dir), "--strict-media"])
        run([
            sys.executable,
            "tools/release_pack.py",
            "--deck-dir", str(pack_dir),
            "--pack-generation-dir", str(PACK_GENERATION_DIR),
            "--outdir", str(release),
            "--chunk-mb", "1",
            "--validate-private-key", str(PACK_GENERATION_DIR / "ios_private.pem"),
        ])
        print(f"\nLocal MediaWiki API end-to-end test passed. Temp output: {tmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
