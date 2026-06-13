#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import contextlib
import importlib.util
import io
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FIXTURES = ROOT / "tests" / "fixtures"
PACK_GENERATION_DIR = ROOT / "tools" / "pack_builder"
PACK_GENERATION_AVAILABLE = (PACK_GENERATION_DIR / "ios_package_assets.py").exists()

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
SYNC_SPEC = importlib.util.spec_from_file_location("sync_mediawiki", TOOLS / "sync_mediawiki.py")
assert SYNC_SPEC and SYNC_SPEC.loader
sync_mediawiki = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(sync_mediawiki)
REVISE_SPEC = importlib.util.spec_from_file_location("revise_japanese_furigana", TOOLS / "revise_japanese_furigana.py")
assert REVISE_SPEC and REVISE_SPEC.loader
revise_japanese_furigana = importlib.util.module_from_spec(REVISE_SPEC)
REVISE_SPEC.loader.exec_module(revise_japanese_furigana)
APPLY_SENTENCE_SPEC = importlib.util.spec_from_file_location("apply_sentence_proposals", TOOLS / "apply_sentence_proposals.py")
assert APPLY_SENTENCE_SPEC and APPLY_SENTENCE_SPEC.loader
apply_sentence_proposals = importlib.util.module_from_spec(APPLY_SENTENCE_SPEC)
APPLY_SENTENCE_SPEC.loader.exec_module(apply_sentence_proposals)
DEPLOY_PACKS_SPEC = importlib.util.spec_from_file_location("deploy_packs_to_vps", TOOLS / "deploy_packs_to_vps.py")
assert DEPLOY_PACKS_SPEC and DEPLOY_PACKS_SPEC.loader
deploy_packs_to_vps = importlib.util.module_from_spec(DEPLOY_PACKS_SPEC)
DEPLOY_PACKS_SPEC.loader.exec_module(deploy_packs_to_vps)
CHANGED_ITEMS_SPEC = importlib.util.spec_from_file_location("changed_deck_items", TOOLS / "changed_deck_items.py")
assert CHANGED_ITEMS_SPEC and CHANGED_ITEMS_SPEC.loader
changed_deck_items = importlib.util.module_from_spec(CHANGED_ITEMS_SPEC)
CHANGED_ITEMS_SPEC.loader.exec_module(changed_deck_items)
from vocomipedia_nlp import analyze_sentence


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise AssertionError(f"command failed with exit {result.returncode}: {' '.join(cmd)}\n{result.stdout}")
    return result


def write_test_keypair(tmp: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp / "ios_private.pem"
    public_path = tmp / "ios_public.pem"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


class VocomipediaPipelineTests(unittest.TestCase):
    def test_vps_partial_pack_deploy_preserves_existing_catalog(self) -> None:
        script = deploy_packs_to_vps.remote_deploy_script("/srv/vocomi-packs", "test-release", 3)
        self.assertIn('find -L "$root/current"', script)
        self.assertIn("-name '*.vpack'", script)
        self.assertIn("-name 'release-state.json'", script)
        self.assertIn("release-state.previous.json", script)
        self.assertIn('state["deck_git_sha"] = deck_git_sha', script)
        self.assertIn("rm -f packs.json packs-images.json", script)
        self.assertIn("python3 - <<'PY'", script)
        self.assertIn('root.glob("*.meta.json")', script)
        self.assertIn('(root / "packs-images.json").write_text', script)
        self.assertLess(script.find('find -L "$root/current"'), script.find('tar -xzf "$root/incoming/$name.tar.gz"'))
        self.assertLess(script.find('rm -f packs.json packs-images.json'), script.find("if compgen -G"))

    def test_release_workflow_uses_previous_release_base_and_reconciles_images(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("actions/checkout@v6", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-artifact@v6", workflow)
        self.assertIn("Resolve previous release base", workflow)
        self.assertIn("current/release-state.json", workflow)
        self.assertIn("--release-state-file tmp/release-state/previous.json", workflow)
        self.assertIn("--base \"$RELEASE_BASE_SHA\"", workflow)
        self.assertIn("Reconcile MediaWiki entry images", workflow)
        self.assertIn("sync-images-api", workflow)
        self.assertIn("--source-sha \"${{ github.sha }}\"", workflow)
        self.assertIn("--updated-decks ${{ inputs.deck_codes }}", workflow)

    def test_push_api_filters_changed_items_without_shrinking_index_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "ja_n5"
            item_dir = pack_dir / "items"
            item_dir.mkdir(parents=True)

            def item(item_id: str, entry_id: str) -> dict:
                return {
                    "schema_version": "vocomipedia-item-2",
                    "id": f"ja_n5:{item_id}",
                    "pack_code": "ja_n5",
                    "language": "ja",
                    "entry_id": entry_id,
                    "headword": entry_id,
                    "reading": "",
                    "label": "",
                    "level": "N5",
                    "order": 0,
                    "part_of_speech": ["Noun"],
                    "glosses": {"en": entry_id},
                    "sentences": [],
                    "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
                    "review": {"status": "approved"},
                    "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                    "app_payload": {},
                }

            (item_dir / "one.json").write_text(json.dumps(item("one", "one"), ensure_ascii=False), encoding="utf-8")
            (item_dir / "two.json").write_text(json.dumps(item("two", "two"), ensure_ascii=False), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "items": [
                            {"id": "ja_n5:one", "entry_id": "one", "file": "items/one.json", "order": 0},
                            {"id": "ja_n5:two", "entry_id": "two", "file": "items/two.json", "order": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            changed = tmp / "changed.txt"
            changed.write_text("items/two.json\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                count = sync_mediawiki.push_api(
                    pack_dir,
                    "https://example.invalid/api.php",
                    "",
                    "",
                    approved_only=True,
                    dry_run=True,
                    skip_index_pages=True,
                    admin_pages=False,
                    structure=False,
                    entry_images=False,
                    changed_items_file=changed,
                    skip_if_no_changed_items=True,
                )
            output = buf.getvalue()
            self.assertEqual(count, 1)
            self.assertIn("Selected 1 changed item page(s) out of 2 approved item(s).", output)
            self.assertIn("DRY RUN: would edit Item:ja_n5/two", output)
            self.assertNotIn("DRY RUN: would edit Item:ja_n5/one", output)

    def test_sync_images_api_reconciles_images_without_editing_pages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "ja_n5"
            item_dir = pack_dir / "items"
            media_dir = pack_dir / "media"
            item_dir.mkdir(parents=True)
            media_dir.mkdir(parents=True)
            Image.new("RGBA", (96, 96), (200, 10, 10, 255)).save(media_dir / "source.png")
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:one",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "one",
                "headword": "one",
                "reading": "",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "one"},
                "sentences": [],
                "media": {"image_filename": "source.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved"},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {},
            }
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "items": [{"id": "ja_n5:one", "entry_id": "one", "file": "items/one.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                count = sync_mediawiki.sync_images_api(
                    pack_dir,
                    "https://example.invalid/api.php",
                    "",
                    "",
                    approved_only=True,
                    dry_run=True,
                )
            output = buf.getvalue()
            self.assertEqual(count, 1)
            self.assertIn("DRY RUN: would upload File:Vocomipedia_ja_n5_one_entry.jpg", output)
            self.assertNotIn("DRY RUN: would edit", output)

    def test_sync_images_api_skips_unchanged_remote_images(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "ja_n5"
            item_dir = pack_dir / "items"
            media_dir = pack_dir / "media"
            item_dir.mkdir(parents=True)
            media_dir.mkdir(parents=True)
            Image.new("RGBA", (96, 96), (10, 20, 200, 255)).save(media_dir / "source.png")
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:one",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "one",
                "headword": "one",
                "reading": "",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "one"},
                "sentences": [],
                "media": {"image_filename": "source.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved"},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {},
            }
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "items": [{"id": "ja_n5:one", "entry_id": "one", "file": "items/one.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            with tempfile.TemporaryDirectory() as image_td:
                filename, image_path = sync_mediawiki.prepare_entry_image(pack_dir, item, Path(image_td))
                image_bytes = image_path.read_bytes()

            class FakeClient:
                uploads: list[str] = []

                def __init__(self, api_url: str):
                    self.api_url = api_url

                def login(self, username: str, password: str) -> None:
                    pass

                def csrf_token(self) -> str:
                    return "token"

                def file_imageinfo(self, filenames: list[str]) -> dict[str, dict]:
                    self.seen = filenames
                    return {filename: {"size": len(image_bytes), "sha1": __import__("hashlib").sha1(image_bytes).hexdigest()}}

                def upload_file(self, filename: str, path: Path, comment: str, token: str) -> None:
                    self.uploads.append(filename)

            old_client = sync_mediawiki.MediaWikiClient
            sync_mediawiki.MediaWikiClient = FakeClient
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    count = sync_mediawiki.sync_images_api(
                        pack_dir,
                        "https://example.invalid/api.php",
                        "user",
                        "password",
                        approved_only=True,
                        dry_run=False,
                    )
            finally:
                sync_mediawiki.MediaWikiClient = old_client
            self.assertEqual(count, 0)
            self.assertIn("skipped 0 existing image(s), 1 unchanged image(s)", buf.getvalue())
            self.assertEqual(FakeClient.uploads, [])

    def test_changed_deck_items_detects_changed_canonical_item_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run(["git", "init"], cwd=tmp)
            run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp)
            run(["git", "config", "user.name", "Test User"], cwd=tmp)
            pack_dir = tmp / "data" / "languages" / "ja" / "ja_n5"
            item_dir = pack_dir / "items"
            item_dir.mkdir(parents=True)
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "items": [{"id": "ja_n5:one", "entry_id": "one", "file": "items/one.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            (item_dir / "one.json").write_text('{"id":"ja_n5:one"}\n', encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "base"], cwd=tmp)
            base = run(["git", "rev-parse", "HEAD"], cwd=tmp).stdout.strip()
            (item_dir / "one.json").write_text('{"id":"ja_n5:one","changed":true}\n', encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "change"], cwd=tmp)
            paths = changed_deck_items.changed_item_paths(tmp, base, "HEAD", pack_dir)
            self.assertEqual(paths, ["items/one.json"])

    def test_changed_deck_items_uses_per_deck_release_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run(["git", "init"], cwd=tmp)
            run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp)
            run(["git", "config", "user.name", "Test User"], cwd=tmp)
            for code, lang in [("ja_n5", "ja"), ("de_b2", "de")]:
                pack_dir = tmp / "data" / "languages" / lang / code
                item_dir = pack_dir / "items"
                item_dir.mkdir(parents=True)
                (pack_dir / "pack.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "vocomipedia-pack-1",
                            "pack_code": code,
                            "items": [{"id": f"{code}:one", "entry_id": "one", "file": "items/one.json", "order": 0}],
                        }
                    ),
                    encoding="utf-8",
                )
                (item_dir / "one.json").write_text(json.dumps({"id": f"{code}:one"}), encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "base"], cwd=tmp)
            ja_released = run(["git", "rev-parse", "HEAD"], cwd=tmp).stdout.strip()
            (tmp / "data" / "languages" / "de" / "de_b2" / "items" / "one.json").write_text('{"id":"de_b2:one","changed":true}\n', encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "de change"], cwd=tmp)
            catalog = tmp / "catalog" / "packs.yaml"
            catalog.parent.mkdir()
            catalog.write_text(
                """schema_version: vocomipedia-pack-catalog-1
packs:
  ja_n5:
    language: ja
  de_b2:
    language: de
""",
                encoding="utf-8",
            )
            state = tmp / "state.json"
            state.write_text(json.dumps({"deck_git_sha": {"ja_n5": ja_released}}), encoding="utf-8")
            release_state = changed_deck_items.load_release_state(state)
            ja_base = changed_deck_items.base_for_deck(release_state, "ja_n5", "")
            de_base = changed_deck_items.base_for_deck(release_state, "de_b2", "")
            self.assertEqual(ja_base, ja_released)
            self.assertEqual(de_base, "")
            self.assertEqual(
                changed_deck_items.changed_item_paths(tmp, ja_base, "HEAD", tmp / "data" / "languages" / "ja" / "ja_n5"),
                [],
            )
            self.assertEqual(
                changed_deck_items.all_item_paths(tmp / "data" / "languages" / "de" / "de_b2"),
                ["items/one.json"],
            )

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

    def test_sync_all_resolves_external_pack_generation_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_generation = tmp / "vocomi_pack_generation"
            assets = pack_generation / "language_packs" / "japanese_N5"
            assets.mkdir(parents=True)
            source_json = assets / "japanese_N5_structure.json"
            shutil.copy2(FIXTURES / "sample_legacy.json", source_json)
            Image.new("RGBA", (256, 256), (255, 255, 255, 255)).save(assets / "comic_愛__あい__sample_blank.png")
            catalog = tmp / "packs.yaml"
            catalog.write_text(
                """schema_version: vocomipedia-pack-catalog-1
packs:
  ja_n5:
    title: Japanese N5
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
    source_json: vocomi_pack_generation/language_packs/japanese_N5/japanese_N5_structure.json
    source_asset_dir: vocomi_pack_generation/language_packs/japanese_N5
""",
                encoding="utf-8",
            )
            out_root = tmp / "data"
            run(
                [
                    sys.executable,
                    str(TOOLS / "sync_all_packs.py"),
                    "--catalog",
                    str(catalog),
                    "--pack-generation-dir",
                    str(pack_generation),
                    "--out-root",
                    str(out_root),
                    "--backup-dir",
                    str(tmp / "backups"),
                    "--decks",
                    "ja_n5",
                    "--auto-pos-analysis",
                    "--mark-approved",
                    "--validate",
                ]
            )
            self.assertTrue((out_root / "ja" / "ja_n5" / "pack.json").exists())
            item_path = next((out_root / "ja" / "ja_n5" / "items").glob("*.json"))
            item = json.loads(item_path.read_text(encoding="utf-8"))
            self.assertTrue(item["sentences"][0]["tokens"])
            self.assertNotEqual(item["sentences"][0]["tokens"], json.loads(source_json.read_text(encoding="utf-8"))[0]["pos_analysis"][0]["tokens"])

    def test_scaffold_deck_adds_catalog_entry_and_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            catalog = tmp / "packs.yaml"
            catalog.write_text("schema_version: vocomipedia-pack-catalog-1\npacks: {}\n", encoding="utf-8")
            out_root = tmp / "data"
            run(
                [
                    sys.executable,
                    str(TOOLS / "scaffold_deck.py"),
                    "--deck-code",
                    "de_b2",
                    "--title",
                    "German B2",
                    "--language",
                    "de",
                    "--level",
                    "B2",
                    "--data-pack-code",
                    "de_b2",
                    "--source-json",
                    "vocomi_pack_generation/language_packs/german_B2/german_B2_structure.json",
                    "--source-asset-dir",
                    "vocomi_pack_generation/language_packs/german_B2",
                    "--catalog",
                    str(catalog),
                    "--out-root",
                    str(out_root),
                ]
            )
            catalog_obj = json.loads(json.dumps(__import__("yaml").safe_load(catalog.read_text(encoding="utf-8"))))
            self.assertIn("de_b2", catalog_obj["packs"])
            manifest = json.loads((out_root / "de" / "de_b2" / "pack.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["pack_code"], "de_b2")
            self.assertEqual(manifest["items"], [])

    @unittest.skipUnless(PACK_GENERATION_AVAILABLE, "bundled pack builder is required")
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
                    str(PACK_GENERATION_DIR),
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

    @unittest.skipUnless(PACK_GENERATION_AVAILABLE, "bundled pack builder is required")
    def test_combined_release_rebuilds_data_assets_from_component_decks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data_root = tmp / "data"

            n5_json = tmp / "n5.json"
            shutil.copy2(FIXTURES / "sample_legacy.json", n5_json)
            n5_assets = tmp / "n5_assets"
            n5_assets.mkdir()
            Image.new("RGBA", (256, 256), (255, 255, 255, 255)).save(n5_assets / "comic_愛__あい__sample_blank.png")

            n4_entries = json.loads((FIXTURES / "sample_legacy.json").read_text(encoding="utf-8"))
            n4_entries[0]["entry_id"] = "山__やま__sample"
            n4_entries[0]["word"] = "山"
            n4_entries[0]["word_reading"] = "やま"
            n4_entries[0]["word_label"] = "山"
            n4_entries[0]["word_en"] = "mountain"
            n4_entries[0]["word_de"] = "Berg"
            n4_entries[0]["jp"] = ["山は高いです。"]
            n4_entries[0]["fu"] = ["やまはたかいです。"]
            n4_entries[0]["en"] = ["The mountain is high."]
            n4_entries[0]["de"] = ["Der Berg ist hoch."]
            n4_entries[0]["pos_analysis"] = [
                {
                    "sentence": "山は高いです。",
                    "tokens": [
                        {
                            "surface": "山",
                            "surface_en": "mountain",
                            "furigana": "やま",
                            "pos": "noun",
                            "lemma": "山",
                            "difficulty": 1,
                            "is_main_word": True,
                        }
                    ],
                    "difficulty_aggregated": 1.0,
                }
            ]
            n4_json = tmp / "n4.json"
            n4_json.write_text(json.dumps(n4_entries, ensure_ascii=False), encoding="utf-8")
            n4_assets = tmp / "n4_assets"
            n4_assets.mkdir()
            Image.new("RGBA", (256, 256), (245, 245, 245, 255)).save(n4_assets / "comic_山__やま__sample_blank.png")

            for code, input_json, asset_dir in (("ja_n5", n5_json, n5_assets), ("ja_n4", n4_json, n4_assets)):
                run(
                    [
                        sys.executable,
                        str(TOOLS / "import_legacy_pack.py"),
                        "--pack-code",
                        code,
                        "--input-json",
                        str(input_json),
                        "--asset-dir",
                        str(asset_dir),
                        "--out-root",
                        str(data_root),
                        "--copy-media",
                        "--mark-approved",
                    ]
                )

            release_out = tmp / "release"
            private_key, public_key = write_test_keypair(tmp)
            run(
                [
                    sys.executable,
                    str(TOOLS / "release_combined_pack.py"),
                    "--data-pack-code",
                    "ja_n5-n4",
                    "--root",
                    str(data_root),
                    "--pack-generation-dir",
                    str(PACK_GENERATION_DIR),
                    "--outdir",
                    str(release_out),
                    "--app-pubkey",
                    str(public_key),
                    "--validate-private-key",
                    str(private_key),
                    "--chunk-mb",
                    "1",
                ]
            )

            db_path = release_out / "staging" / "combined" / "ja_n5-n4" / "combined-assets" / "ja_N5-N4" / "iOS_assets" / "ja_n5-n4.db"
            self.assertTrue(db_path.exists())
            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 2)
            self.assertTrue(list((release_out / "packs").glob("ja_n5-n4_*.vpack")))

    def test_visible_wiki_sentence_edits_create_analyzed_proposals(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ja_n5:test",
            "pack_code": "ja_n5",
            "language": "ja",
            "entry_id": "川",
            "headword": "川",
            "reading": "かわ",
            "label": "",
            "level": "N5",
            "order": 0,
            "part_of_speech": ["Noun"],
            "glosses": {"en": "river", "es": "rio", "de": "Fluss"},
            "sentences": [
                {
                    "target": "川を見る。",
                    "reading": "かわをみる。",
                    "translations": {"en": "I see a river.", "de": "Ich sehe einen Fluss."},
                    "tokens": [
                        {
                            "surface": "川",
                            "surface_en": "river",
                            "furigana": "かわ",
                            "reading_kana": "かわ",
                            "ruby_text": "川[かわ]",
                            "ruby_spans": [{"base": "川", "reading": "かわ", "start": 0, "length": 1}],
                            "ruby_confidence": "high",
                            "pos": "noun",
                            "lemma": "川",
                            "explanation": "River.",
                            "difficulty": 1,
                            "is_main_word": True,
                        },
                        {
                            "surface": "見る",
                            "surface_en": "see",
                            "furigana": "みる",
                            "reading_kana": "みる",
                            "ruby_text": "見[み]る",
                            "ruby_spans": [{"base": "見", "reading": "み", "start": 0, "length": 1}],
                            "ruby_confidence": "high",
                            "pos": "verb",
                            "lemma": "見る",
                            "explanation": "See.",
                            "difficulty": 1,
                            "is_main_word": False,
                        },
                    ],
                    "difficulty": 1,
                }
            ],
            "media": {"image_filename": "", "license": "needs-audit", "review_status": "missing"},
            "review": {"status": "approved"},
            "provenance": {"origin": "test", "license_status": "test"},
            "app_payload": {"pos_analysis": [{"sentence": "川を見る。", "tokens": [], "difficulty_aggregated": 1}]},
        }
        page = sync_mediawiki.render_item_page(item)
        self.assertIn("__NOEDITSECTION__", page)
        self.assertIn("VOCOMIPEDIA_ITEM_JSON_START", page)
        self.assertNotIn("== Sync data ==", page)
        self.assertNotIn("Do not edit this section manually.", page)
        self.assertIn("{{#default_form:Vocomipedia item}}", page)
        self.assertIn("{{VocomipediaItem", page)
        self.assertIn("{{VocomipediaSentence", page)
        self.assertNotIn("{{VocomipediaToken", page)
        self.assertNotIn("|reading_preview=", page)
        self.assertNotIn("|meaning=", page)
        self.assertIn("|ruby_source=川[かわ]を見[み]る。", page)
        self.assertLess(page.index("|target_label=Japanese"), page.index("|ruby_sentence=yes"))
        self.assertLess(page.index("|ruby_sentence=yes"), page.index("|japanese=川を見る。"))
        self.assertLess(page.index("|japanese=川を見る。"), page.index("|index=1"))
        self.assertLess(page.index("|index=1"), page.index("|ruby_source=川[かわ]を見[み]る。"))
        self.assertIn("|headword_ruby=川[かわ]", page)
        self.assertNotIn("\n|surface=川\n", page)
        self.assertIn("|gloss_en=river", page)
        self.assertIn("|gloss_de=Fluss", page)
        self.assertIn("|translation_en=I see a river.", page)
        self.assertIn("|translation_de=Ich sehe einen Fluss.", page)
        self.assertNotIn("|english=I see a river.", page)
        self.assertNotIn("|proposal_japanese=", page)
        self.assertNotIn("|proposal_english=", page)
        self.assertNotIn("|proposal_reason=", page)
        self.assertNotIn('<div class="vocomipedia-token-flow">', page)
        self.assertNotIn("|tokens={{VocomipediaToken", page)
        self.assertNotIn("{{{tokens|}}}", sync_mediawiki.render_sentence_template_page())
        self.assertNotIn("! Ruby status", page)
        self.assertNotIn("! Explanation", page)
        self.assertNotIn("! Main word", page)
        self.assertIn("vocomipedia-token-card", sync_mediawiki.render_token_template_page())
        self.assertNotIn("vocomipedia-token-meaning", sync_mediawiki.render_token_template_page())
        self.assertNotIn("vocomipedia-token-meta", sync_mediawiki.render_token_template_page())
        self.assertIn("vocomipediaSentence={{{index|}}}", sync_mediawiki.render_sentence_template_page())
        self.assertIn("[[Category:Sentence replacement proposals]]", sync_mediawiki.render_sentence_template_page())
        self.assertNotIn("=== Sentence", sync_mediawiki.render_sentence_template_page())
        self.assertNotIn("Reading preview", sync_mediawiki.render_sentence_template_page())
        self.assertNotIn("{{{field|surface|input type=text}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|reading_preview|input type=textarea", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|review_status", sync_mediawiki.render_item_form_page())
        self.assertIn("{{{field|japanese|hidden}}}", sync_mediawiki.render_item_form_page())
        self.assertIn("{{{field|ruby_source|input type=textarea|rows=2}}}", sync_mediawiki.render_item_form_page())
        self.assertIn("{{{field|translation_de|input type=textarea|rows=2}}}", sync_mediawiki.render_item_form_page())
        self.assertIn("{{{field|english|hidden}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|lemma|hidden}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|pos|hidden}}}", sync_mediawiki.render_item_form_page())
        self.assertIn("displayed fields when minimized=ruby_source,translation_en", sync_mediawiki.render_item_form_page())
        self.assertNotIn("displayed fields when minimized=sentence,index,ruby", sync_mediawiki.render_item_form_page())
        self.assertNotIn("holds template", sync_mediawiki.render_item_form_page())
        self.assertNotIn("embed in field", sync_mediawiki.render_item_form_page())
        self.assertNotIn("input type=hidden", sync_mediawiki.render_item_form_page())
        self.assertNotIn("<fieldset", sync_mediawiki.render_item_form_page())
        self.assertNotIn("</fieldset>", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|lemma|input type=text}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|pos|input type=text}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|meaning|input type=text}}}", sync_mediawiki.render_item_form_page())
        self.assertNotIn("{{{field|proposal_japanese|input type=textarea|rows=2}}}", sync_mediawiki.render_item_form_page())
        sentence_template = sync_mediawiki.render_sentence_template_page()
        self.assertIn('data-sentence="{{{index|}}}"', sentence_template)
        self.assertNotIn('data-token-flow-sentence="{{{index|}}}"', sentence_template)
        self.assertIn('data-lang="de"', sentence_template)
        self.assertIn("{{{translation_de|}}}", sentence_template)
        self.assertIn("vocomipediaMode=sentence", sentence_template)
        self.assertNotIn("vocomipediaMode=tokens", sentence_template)
        self.assertIn("edit sentence] ]", sentence_template)
        self.assertNotIn("correct tokens] ]", sentence_template)
        self.assertNotIn("suggestion] ]", sentence_template)
        filter_rule = sync_mediawiki.abuse_filter_rule()
        self.assertIn("VocomipediaItem", filter_rule)
        self.assertIn("VocomipediaSentence", filter_rule)
        self.assertIn("VOCOMIPEDIA_ITEM_JSON_START", filter_rule)
        self.assertNotIn("VocomipediaToken", filter_rule)
        item_form = sync_mediawiki.render_item_form_page()
        self.assertIn("vocomipedia-current-translation-row", item_form)
        self.assertIn("vocomipedia-proposal-row", item_form)
        gloss_edited = page.replace("|gloss_de=Fluss", "|gloss_de=Strom")
        gloss_pulled = sync_mediawiki.extract_item_json(gloss_edited)
        self.assertEqual(gloss_pulled["glosses"]["de"], "Strom")
        sentence_edited = sync_mediawiki.extract_item_json(page.replace("|ruby_source=川[かわ]を見[み]る。", "|ruby_source=山[やま]を見[み]る。"))
        self.assertEqual(sentence_edited["sentences"][0]["target"], "川を見る。")
        direct_proposal = sentence_edited["review"]["sentence_proposals"][0]
        self.assertEqual(direct_proposal["proposed_sentence"], "山を見る。")
        self.assertEqual(direct_proposal["proposed_ruby_source"], "山[やま]を見[み]る。")
        self.assertEqual(direct_proposal["proposed_translations"]["de"], "Ich sehe einen Fluss.")
        self.assertEqual(direct_proposal["analysis_status"], "generated")
        self.assertTrue(direct_proposal["generated_tokens"])
        self.assertEqual(direct_proposal["generated_tokens"][0]["ruby_text"], "山[やま]")
        self.assertEqual(direct_proposal["generated_tokens"][0]["ruby_source"], "mediawiki_sentence_ruby")
        translation_edited = page.replace("|translation_de=Ich sehe einen Fluss.", "|translation_de=Ich sehe den Fluss.")
        translation_pulled = sync_mediawiki.extract_item_json(translation_edited)
        self.assertEqual(translation_pulled["sentences"][0]["translations"]["de"], "Ich sehe den Fluss.")
        proposal_page = page.replace(
            "|translation_en=I see a river.",
            "|translation_en=I see a river.\n"
            "|proposal_japanese=山を見る。\n"
            "|proposal_english=I see a mountain.\n"
            "|proposal_reason=The example should use the headword in a more common context.",
            1,
        )
        proposed = sync_mediawiki.extract_item_json(proposal_page)
        self.assertEqual(proposed["sentences"][0]["target"], "川を見る。")
        proposal = proposed["review"]["sentence_proposals"][0]
        self.assertEqual(proposal["old_japanese"], "川を見る。")
        self.assertEqual(proposal["proposed_japanese"], "山を見る。")
        self.assertEqual(proposal["proposed_english"], "I see a mountain.")
        self.assertEqual(proposal["status"], "pending_review")
        self.assertEqual(proposal["analysis_status"], "generated")
        self.assertTrue(proposal["generated_tokens"])
        self.assertFalse(proposal["validation"]["comic_invalidation_supported"])
        ruby_edited = sync_mediawiki.extract_item_json(page.replace("|ruby_source=川[かわ]を見[み]る。", "|ruby_source=川[がわ]を見[み]る。"))
        ruby_proposal = ruby_edited["review"]["sentence_proposals"][0]
        self.assertEqual(ruby_proposal["type"], "ruby_update")
        self.assertEqual(ruby_proposal["proposed_sentence"], "川を見る。")
        self.assertEqual(ruby_proposal["proposed_ruby_source"], "川[がわ]を見[み]る。")
        self.assertEqual(ruby_proposal["generated_tokens"][0]["ruby_text"], "川[がわ]")
        self.assertEqual(ruby_proposal["generated_tokens"][0]["reading_kana"], "がわ")
        pageforms_saved = page.replace(
            "|target_label=Japanese\n|ruby_sentence=yes\n|japanese=川を見る。\n|index=1\n|ruby_source=川[かわ]を見[み]る。",
            "|target_label=Japanese\n|ruby_sentence=yes\n|japanese=川を見る。\n|index=1\n|ruby_source=川[がわ]を見[み]る。",
        )
        pageforms_pulled = sync_mediawiki.extract_item_json(pageforms_saved)
        self.assertEqual(pageforms_pulled["sentences"][0]["target"], "川を見る。")
        self.assertEqual(pageforms_pulled["review"]["sentence_proposals"][0]["type"], "ruby_update")
        headword_edited = page.replace("|headword_ruby=川[かわ]", "|headword_ruby=川[がわ]")
        headword_pulled = sync_mediawiki.extract_item_json(headword_edited)
        self.assertEqual(headword_pulled["headword"], "川")
        self.assertEqual(headword_pulled["reading"], "がわ")

    def test_item_page_can_render_low_res_entry_image(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source = tmp / "comic.png"
            thumb = tmp / "thumb.jpg"
            Image.new("RGBA", (900, 500), (120, 150, 220, 255)).save(source)
            sync_mediawiki.make_low_res_entry_image(source, thumb, max_edge=360)
            self.assertTrue(thumb.exists())
            with Image.open(thumb) as image:
                self.assertLessEqual(max(image.size), 360)
                self.assertEqual(image.mode, "RGB")

        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ja_n5:test",
            "pack_code": "ja_n5",
            "language": "ja",
            "entry_id": "川",
            "headword": "川",
            "reading": "かわ",
            "label": "",
            "level": "N5",
            "order": 0,
            "part_of_speech": ["Noun"],
            "glosses": {"en": "river"},
            "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
            "media": {"image_filename": "comic.png", "license": "needs-audit", "review_status": "missing"},
            "review": {"status": "approved"},
            "provenance": {"origin": "test", "license_status": "test"},
            "app_payload": {},
        }
        filename = sync_mediawiki.entry_image_filename(item)
        self.assertEqual(filename, "Vocomipedia_ja_n5_test_entry.jpg")
        page = sync_mediawiki.render_item_page(item, entry_image=filename)
        self.assertIn(f"|image={filename}", page)
        self.assertIn("|image_caption=川", page)
        self.assertIn('class="vocomipedia-infobox"', sync_mediawiki.render_item_template_page())
        self.assertIn("vocomipedia-ruby-source", sync_mediawiki.render_item_template_page())
        self.assertIn("vocomipedia-gloss-list", sync_mediawiki.render_item_template_page())
        self.assertIn("[[File:{{{image|}}}|frameless|280px|{{{image_caption|}}}]]", sync_mediawiki.render_item_template_page())
        self.assertIn("{{{field|gloss_en|input type=text}}}", sync_mediawiki.render_item_form_page())
        self.assertIn("vocomipedia-form-headword", sync_mediawiki.render_item_form_page())
        css = sync_mediawiki.render_common_css_page()
        self.assertIn(".vocomipedia-token-table", css)
        self.assertIn(".vocomipedia-token-flow > p", css)
        self.assertIn(".vocomipedia-token-card > p", css)
        self.assertIn(".vocomipedia-translation-values > p", css)

        self.assertIn(".mw-parser-output > p:has(> br:only-child)", css)
        self.assertIn(".vocomipedia-token-card", css)
        self.assertIn("padding: .75em .65em .5em;", css)
        self.assertNotIn("min-height: 5.15em;", css)
        self.assertNotIn("min-height: 2.2em;", css)
        self.assertIn("gloss_ja", sync_mediawiki.render_item_form_page())
        self.assertIn("td.instanceRearranger", css)
        self.assertIn(".multipleTemplateWrapper .multipleTemplateAdder", css)
        self.assertIn(".multipleTemplateWrapper > p:has(.oo-ui-buttonWidget)", css)
        self.assertIn("td.fieldValuesDisplay", css)
        self.assertIn(".vocomipedia-scope-notice", css)
        self.assertIn("vocomipedia-scoped-sentence-edit", css)
        self.assertNotIn("vocomipedia-mode-tokens", css)
        self.assertIn("#ca-edit", css)
        self.assertIn("#t-specialpages", css)
        self.assertIn("skin-theme-clientpref-night", css)
        self.assertIn("parseRubySource", sync_mediawiki.render_common_js_page())
        self.assertIn("hideRegularUserChrome", sync_mediawiki.render_common_js_page())
        self.assertIn("expandPageFormsInstances", sync_mediawiki.render_common_js_page())
        self.assertIn("isFormEdit", sync_mediawiki.render_common_js_page())
        self.assertIn("arrangeTokenCards", sync_mediawiki.render_common_js_page())
        self.assertIn("applyScopedSentenceEdit", sync_mediawiki.render_common_js_page())
        self.assertIn("scopedEditMode", sync_mediawiki.render_common_js_page())
        self.assertIn("configureScopedEditableFields", sync_mediawiki.render_common_js_page())
        self.assertIn("enableEditableFormFields", sync_mediawiki.render_common_js_page())
        self.assertIn("initDisplayLanguageControl", sync_mediawiki.render_common_js_page())
        self.assertIn("preferredDisplayLanguage", sync_mediawiki.render_common_js_page())
        self.assertIn("proposal_reason", sync_mediawiki.render_common_js_page())
        self.assertIn("translation_[^", sync_mediawiki.render_common_js_page())
        self.assertNotIn("VocomipediaToken", sync_mediawiki.render_common_js_page())

    @unittest.skipUnless(PACK_GENERATION_AVAILABLE, "bundled pack builder is required")
    def test_sentence_proposal_apply_generates_tokens_and_updates_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "ja_n5"
            item_dir = pack_dir / "items"
            item_dir.mkdir(parents=True)
            media_dir = pack_dir / "media"
            media_dir.mkdir()
            Image.new("RGBA", (256, 256), (220, 230, 240, 255)).save(media_dir / "comic_川_blank.png")
            item_path = item_dir / "sample.json"
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:test",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "川",
                "headword": "川",
                "reading": "かわ",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "river"},
                "sentences": [{"target": "川を見る。", "reading": "かわをみる。", "translations": {"en": "I see a river."}, "tokens": [], "difficulty": 1}],
                "media": {"image_filename": "comic_川_blank.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved"},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {"pos_analysis": [{"sentence": "川を見る。", "tokens": [], "difficulty_aggregated": 1}]},
            }
            page = sync_mediawiki.render_item_page(item)
            proposed = sync_mediawiki.extract_item_json(
                page.replace("|ruby_source=川を見る。", "|ruby_source=山[やま]を見[み]る。").replace("|translation_en=I see a river.", "|translation_en=I see a mountain.")
            )
            proposal_id = proposed["review"]["sentence_proposals"][0]["id"]
            item_path.write_text(json.dumps(proposed, ensure_ascii=False, indent=2), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "lang_prefix": "ja",
                        "lang_level": "n5",
                        "level": "N5",
                        "target_sentence_key": "jp",
                        "reading_sentence_key": "fu",
                        "items": [{"id": "ja_n5:test", "entry_id": "川", "file": "items/sample.json", "order": 0}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            run(
                [
                    sys.executable,
                    str(TOOLS / "apply_sentence_proposals.py"),
                    "--deck-dir",
                    str(pack_dir),
                    "--proposal-id",
                    proposal_id,
                    "--apply",
                    "--mark-approved",
                    "--backup-dir",
                    str(tmp / "backups"),
                ]
            )
            applied = json.loads(item_path.read_text(encoding="utf-8"))
            self.assertEqual(applied["sentences"][0]["target"], "山を見る。")
            self.assertEqual(applied["sentences"][0]["translations"]["en"], "I see a mountain.")
            self.assertTrue(applied["sentences"][0]["tokens"])
            self.assertEqual(applied["sentences"][0]["tokens"][0]["ruby_text"], "山[やま]")
            self.assertEqual(applied["sentences"][0]["tokens"][0]["ruby_source"], "mediawiki_sentence_ruby")
            self.assertEqual(applied["app_payload"]["pos_analysis"][0]["sentence"], "山を見る。")
            self.assertEqual(applied["app_payload"]["pos_analysis"][0]["tokens"], applied["sentences"][0]["tokens"])
            self.assertEqual(applied["review"]["sentence_proposals"][0]["status"], "applied")
            self.assertEqual(applied["review"]["status"], "approved")
            release_out = tmp / "release"
            private_key, public_key = write_test_keypair(tmp)
            run(
                [
                    sys.executable,
                    str(TOOLS / "release_pack.py"),
                    "--deck-dir",
                    str(pack_dir),
                    "--pack-generation-dir",
                    str(PACK_GENERATION_DIR),
                    "--outdir",
                    str(release_out),
                    "--chunk-mb",
                    "1",
                    "--app-pubkey",
                    str(public_key),
                    "--validate-private-key",
                    str(private_key),
                ]
            )
            db_path = release_out / "staging" / "ja_n5" / "iOS_assets" / "ja_n5.db"
            self.assertTrue(db_path.exists())
            conn = sqlite3.connect(db_path)
            try:
                metadata = json.loads(conn.execute("SELECT metadata FROM vocab WHERE id = ?", ("川",)).fetchone()[0])
            finally:
                conn.close()
            self.assertEqual(metadata["jp"], ["山を見る。"])
            self.assertEqual(metadata["fu"], ["やまをみる。"])
            self.assertEqual(metadata["en"], ["I see a mountain."])
            self.assertEqual(metadata["pos_analysis"][0]["sentence"], "山を見る。")
            self.assertEqual(metadata["pos_analysis"][0]["tokens"][0]["ruby_text"], "山[やま]")
            self.assertTrue(list((release_out / "packs").glob("*.vpack")))
        self.assertIn("[name=\"wpSave\"], [name=\"wpPreview\"], [name=\"wpDiff\"]", sync_mediawiki.render_common_js_page())
        self.assertIn(".vocomipedia-sentence-heading[data-sentence]", sync_mediawiki.render_common_js_page())

    def test_wiki_sync_back_auto_applies_sentence_proposals_without_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            canonical_root = tmp / "data"
            pack_dir = canonical_root / "ja" / "ja_n5"
            item_dir = pack_dir / "items"
            item_dir.mkdir(parents=True)
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:test",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "川",
                "headword": "川",
                "reading": "かわ",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "river"},
                "sentences": [
                    {
                        "target": "川を見る。",
                        "reading": "かわをみる。",
                        "translations": {"en": "I see a river."},
                        "tokens": [],
                        "difficulty": 1,
                    }
                ],
                "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {"pos_analysis": [{"sentence": "川を見る。", "tokens": [], "difficulty_aggregated": 1}]},
            }
            (item_dir / "sample.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "lang_prefix": "ja",
                        "lang_level": "n5",
                        "level": "N5",
                        "target_sentence_key": "jp",
                        "reading_sentence_key": "fu",
                        "items": [{"id": "ja_n5:test", "entry_id": "川", "file": "items/sample.json", "order": 0}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            catalog = tmp / "packs.yaml"
            catalog.write_text(
                """schema_version: vocomipedia-pack-catalog-1
packs:
  ja_n5:
    title: Japanese N5
    language: ja
    lang_prefix: ja
    lang_level: n5
""",
                encoding="utf-8",
            )
            page = sync_mediawiki.render_item_page(item)
            pulled = sync_mediawiki.extract_item_json(
                page.replace("|ruby_source=川を見る。", "|ruby_source=山[やま]を見[み]る。")
                .replace("|translation_en=I see a river.", "|translation_en=I see a mountain.")
            )
            pulled["review"]["wiki"]["revision_id"] = 6
            pulled_dir = tmp / "pulled" / "ja_n5"
            pulled_dir.mkdir(parents=True)
            (pulled_dir / "sample.json").write_text(json.dumps(pulled, ensure_ascii=False, indent=2), encoding="utf-8")

            run(
                [
                    sys.executable,
                    str(TOOLS / "wiki_sync_back.py"),
                    "--decks",
                    "ja_n5",
                    "--catalog",
                    str(catalog),
                    "--canonical-root",
                    str(canonical_root),
                    "--work-root",
                    str(tmp / "work"),
                    "--pulled-root",
                    str(tmp / "pulled"),
                    "--reports-dir",
                    str(tmp / "reports"),
                    "--skip-pull",
                    "--export-source",
                ]
            )

            applied = json.loads((item_dir / "sample.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["sentences"][0]["target"], "山を見る。")
            self.assertEqual(applied["sentences"][0]["translations"]["en"], "I see a mountain.")
            self.assertEqual(applied["sentences"][0]["tokens"][0]["ruby_text"], "山[やま]")
            self.assertEqual(applied["app_payload"]["pos_analysis"][0]["sentence"], "山を見る。")
            self.assertEqual(applied["review"]["sentence_proposals"][0]["status"], "applied")
            self.assertEqual(applied["review"]["status"], "approved")

    def test_offline_sentence_analyzers_cover_supported_languages(self) -> None:
        cases = [
            ("ja", "山を見る。", "山[やま]を見る。"),
            ("de", "Ich sehe eine Katze.", None),
            ("fr", "Je vois un chat.", None),
            ("es", "Veo un gato.", None),
            ("ko", "고양이를 봅니다.", None),
            ("zh-Hans", "我看见一只猫。", None),
        ]
        for language, sentence, ruby_source in cases:
            with self.subTest(language=language):
                result = analyze_sentence(language, sentence, ruby_source=ruby_source)
                self.assertEqual(result.sentence, sentence)
                self.assertTrue(result.tokens)
                for token in result.tokens:
                    self.assertIn("surface", token)
                    self.assertIn("upos", token)
                    self.assertIn("analyzer", token)
                joined_surface = "".join(str(token.get("surface") or "") for token in result.tokens)
                if joined_surface != sentence.replace(" ", ""):
                    covered = set()
                    for token in result.tokens:
                        start = token.get("start")
                        end = token.get("end")
                        self.assertIsInstance(start, int)
                        self.assertIsInstance(end, int)
                        self.assertGreaterEqual(start, 0)
                        self.assertGreater(end, start)
                        self.assertLessEqual(end, len(sentence))
                        covered.update(range(start, end))
                    expected = {i for i, char in enumerate(sentence) if not char.isspace()}
                    self.assertEqual(covered, expected)
                if language == "ja":
                    self.assertEqual(result.tokens[0]["ruby_text"], "山[やま]")
                    self.assertEqual(result.tokens[0]["ruby_source"], "mediawiki_sentence_ruby")
                    self.assertEqual(result.reading, "やまをみる。")

    def test_entry_image_reference_survives_skipped_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td)
            media_dir = pack_dir / "media"
            media_dir.mkdir()
            Image.new("RGBA", (64, 64), (120, 150, 220, 255)).save(media_dir / "comic.png")
            item = {
                "id": "de_a1:test",
                "pack_code": "de_a1",
                "language": "de",
                "entry_id": "Haus",
                "headword": "Haus",
                "media": {"image_filename": "comic.png"},
            }
            filename = sync_mediawiki.entry_image_reference(pack_dir, item)
            self.assertEqual(filename, "Vocomipedia_de_a1_test_entry.jpg")
            page = sync_mediawiki.render_item_page(item, entry_image=filename)
            self.assertIn("|image=Vocomipedia_de_a1_test_entry.jpg", page)

    def test_local_setup_searches_vocomipedia_namespaces_by_default(self) -> None:
        source = (TOOLS / "local_mediawiki.py").read_text(encoding="utf-8")
        skeleton = (ROOT / "docker" / "LocalSettings.vocomipedia.php").read_text(encoding="utf-8")
        for text in (source, skeleton):
            self.assertIn("$wgNamespacesToBeSearchedDefault[NS_MAIN] = false;", text)
            self.assertIn("$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_ITEM] = true;", text)
            self.assertIn("$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_DECK] = true;", text)
            self.assertIn("$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_POLICY] = true;", text)
        for text in (source, skeleton):
            self.assertIn("wfLoadExtension( 'VocomipediaSearch' );", text)
            self.assertIn("wfLoadExtension( 'Elastica' );", text)
            self.assertIn("wfLoadExtension( 'CirrusSearch' );", text)
            self.assertIn("$wgSearchType = 'CirrusSearch';", text)
            self.assertIn("'host' => 'elasticsearch'", text)
            self.assertIn("error_reporting( E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED );", text)
        self.assertIn('sub.add_parser("reindex-search"', source)
        self.assertIn("CirrusSearch:UpdateSearchIndexConfig", source)
        self.assertIn("CirrusSearch:ForceSearchIndex", source)
        self.assertIn("cirrusSearchElasticaWrite", source)

    def test_local_search_stack_includes_cirrus_and_domain_ranker(self) -> None:
        dockerfile = (ROOT / "docker" / "mediawiki" / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker" / "compose.local.yml").read_text(encoding="utf-8")
        search_page = (
            ROOT
            / "docker"
            / "mediawiki"
            / "extensions"
            / "VocomipediaSearch"
            / "includes"
            / "SpecialVocomipediaSearch.php"
        ).read_text(encoding="utf-8")
        hooks = (
            ROOT
            / "docker"
            / "mediawiki"
            / "extensions"
            / "VocomipediaSearch"
            / "includes"
            / "VocomipediaSearchHooks.php"
        ).read_text(encoding="utf-8")

        self.assertIn("Elastica CirrusSearch", dockerfile)
        self.assertIn("composer install --no-dev", dockerfile)
        self.assertIn("COPY mediawiki/extensions/VocomipediaSearch", dockerfile)
        self.assertIn("docker.elastic.co/elasticsearch/elasticsearch:7.10.2", compose)
        self.assertIn("mw-elasticsearch", compose)
        self.assertIn("SpecialPageBeforeExecute", hooks)
        self.assertIn("vocomipediaFallback", hooks)
        self.assertIn("SpecialPage::getTitleFor( 'VocomipediaSearch' )", hooks)
        self.assertIn("vocomipedia_search_item", search_page)
        self.assertIn("INDEX_CANDIDATE_LIMIT", search_page)
        self.assertIn("searchIndexedItems", search_page)
        self.assertIn("scanItemPages", search_page)
        self.assertIn("strlen( $needle ) < 3", search_page)
        self.assertNotIn("if ( $this->isShortAsciiNeedle( $needle ) ) {\n            return '';\n        }", search_page)
        self.assertIn("$item['glosses']", search_page)
        self.assertIn("$sentence['translations']", search_page)
        self.assertIn("$sentence['tokens']", search_page)
        self.assertIn("6000, 1800, 450", search_page)
        self.assertIn("Token meaning", search_page)
        self.assertIn("private const SCAN_BATCH_SIZE = 20", search_page)
        self.assertIn("content_address LIKE", search_page)
        self.assertIn("$this->summarizeItem( $item )", search_page)
        self.assertIn("private function containsNeedle", search_page)
        self.assertIn("private function isShortAsciiNeedle", search_page)
        self.assertIn("gc_collect_cycles()", search_page)

        indexer = (ROOT / "tools" / "reindex_mediawiki_search.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE vocomipedia_search_item", indexer)
        self.assertIn("vsi_headword_norm", indexer)
        self.assertIn("collect_search_text", indexer)
        self.assertIn("def write_sql", indexer)
        self.assertIn("subprocess.Popen", indexer)

        docs = (ROOT / "docs" / "local-mediawiki.md").read_text(encoding="utf-8")
        self.assertIn("local_mediawiki.py reindex-search", docs)
        self.assertIn("reindex_mediawiki_search.py", docs)
        self.assertIn("any language deck", docs)

    def test_japanese_ruby_flags_do_not_create_public_review_queue_links(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ja_n5:test",
            "pack_code": "ja_n5",
            "language": "ja",
            "entry_id": "見つける",
            "headword": "見つける",
            "reading": "みつける",
            "label": "",
            "level": "N5",
            "order": 0,
            "part_of_speech": ["Verb"],
            "glosses": {"en": "to find"},
            "sentences": [
                {
                    "target": "見つけた。",
                    "reading": "みつけた。",
                    "translations": {"en": "I found it."},
                    "tokens": [
                        {
                            "surface": "見つけた",
                            "surface_en": "found",
                            "furigana": "みつけた",
                            "reading_kana": "みつけた",
                            "ruby_text": "見[み]つけた",
                            "ruby_spans": [{"base": "見", "reading": "み", "start": 0, "length": 1}],
                            "ruby_confidence": "needs_review",
                            "pos": "verb",
                            "lemma": "見つける",
                            "explanation": "Past form.",
                            "difficulty": 1,
                            "is_main_word": True,
                        }
                    ],
                    "difficulty": 1,
                }
            ],
            "media": {"image_filename": "", "license": "needs-audit", "review_status": "missing"},
            "review": {"status": "approved"},
            "provenance": {"origin": "test", "license_status": "test"},
            "app_payload": {"pos_analysis": [{"sentence": "見つけた。", "tokens": [], "difficulty_aggregated": 1}]},
        }
        page = sync_mediawiki.render_item_page(item)
        self.assertIn("[[Category:Japanese ruby needs review]]", page)
        self.assertNotIn("! Ruby status", page)
        self.assertNotIn("! Explanation", page)
        self.assertNotIn("! Main word", page)

        deck_page = sync_mediawiki.render_deck_index("ja_n5", [item])
        main_page = sync_mediawiki.render_main_page(["ja_n5"])
        self.assertNotIn("Review queues", deck_page)
        self.assertNotIn("Japanese ruby review", deck_page)
        self.assertNotIn("Review queues", main_page)
        self.assertNotIn("Japanese ruby review", main_page)

        resolved = page.replace("|ruby_source=見[み]つけた。", "|ruby_source=見[め]つけた。")
        pulled = sync_mediawiki.extract_item_json(resolved)
        proposal = pulled["review"]["sentence_proposals"][0]
        self.assertEqual(proposal["type"], "ruby_update")
        self.assertEqual(proposal["proposed_ruby_source"], "見[め]つけた。")
        self.assertEqual(proposal["generated_tokens"][0]["ruby_text"], "見[め]つけ")
        self.assertEqual(pulled["sentences"][0]["tokens"][0]["ruby_text"], "見[み]つけた")

    def test_template_item_pages_reject_structural_tampering(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ja_n5:test",
            "pack_code": "ja_n5",
            "language": "ja",
            "entry_id": "川",
            "headword": "川",
            "reading": "かわ",
            "label": "",
            "level": "N5",
            "order": 0,
            "part_of_speech": ["Noun"],
            "glosses": {"en": "river"},
            "sentences": [
                {
                    "target": "川を見る。",
                    "reading": "かわをみる。",
                    "translations": {"en": "I see a river."},
                    "tokens": [
                        {
                            "surface": "川",
                            "surface_en": "river",
                            "furigana": "かわ",
                            "reading_kana": "かわ",
                            "ruby_text": "川[かわ]",
                            "ruby_spans": [{"base": "川", "reading": "かわ", "start": 0, "length": 1}],
                            "ruby_confidence": "high",
                            "pos": "noun",
                            "lemma": "川",
                            "explanation": "River.",
                            "difficulty": 1,
                            "is_main_word": True,
                        }
                    ],
                    "difficulty": 1,
                }
            ],
            "media": {"image_filename": "", "license": "needs-audit", "review_status": "missing"},
            "review": {"status": "approved"},
            "provenance": {"origin": "test", "license_status": "test"},
            "app_payload": {"pos_analysis": [{"sentence": "川を見る。", "tokens": [], "difficulty_aggregated": 1}]},
        }
        page = sync_mediawiki.render_item_page(item)
        with self.assertRaisesRegex(sync_mediawiki.WikiPageFormatError, "protected field 'pack_code' changed"):
            sync_mediawiki.extract_item_json(page.replace("|pack_code=ja_n5", "|pack_code=ja_n4"))
        reordered = page.replace("|japanese=川を見る。\n|index=1", "|japanese=川を見る。\n|index=2", 1)
        with self.assertRaisesRegex(sync_mediawiki.WikiPageFormatError, "sentence template indexes changed"):
            sync_mediawiki.extract_item_json(reordered)
        with self.assertRaisesRegex(sync_mediawiki.WikiPageFormatError, "sentence template indexes changed"):
            sync_mediawiki.extract_item_json(page.replace("{{VocomipediaSentence", "{{BrokenSentence", 1))
        with self.assertRaisesRegex(sync_mediawiki.WikiPageFormatError, "missing Vocomipedia form templates"):
            sync_mediawiki.extract_item_json(page.replace("{{VocomipediaItem", "{{BrokenItem").replace("{{VocomipediaSentence", "{{BrokenSentence"))

    def test_namespace_admin_and_wiki_revision_metadata(self) -> None:
        self.assertEqual(sync_mediawiki.split_namespace_prefix("Item:ja_n5/abc"), (3000, "ja_n5/abc"))
        self.assertEqual(sync_mediawiki.split_namespace_prefix("Deck:"), (3002, ""))
        self.assertEqual(sync_mediawiki.split_namespace_prefix("plain-prefix"), (0, "plain-prefix"))
        self.assertEqual(sync_mediawiki.api_url_candidates("https://vocomipedia.com/wiki/api.php")[0], "https://vocomipedia.com/wiki/api.php")
        self.assertIn("https://vocomipedia.com/api.php", sync_mediawiki.api_url_candidates("https://vocomipedia.com/wiki/api.php"))
        self.assertIn("[[Special:Moderation|Moderation queue]]", sync_mediawiki.render_admin_page())
        self.assertIn("[[Category:Sentence replacement proposals|Sentence replacement proposals]]", sync_mediawiki.render_admin_page())
        self.assertNotIn("[[Vocomipedia:Admin|Admin dashboard]]", sync_mediawiki.render_main_page(["ja_n5"]))
        self.assertNotIn("vocomipedia-admin-only", sync_mediawiki.render_main_page(["ja_n5"]))
        self.assertNotIn("Special:Moderation|Moderation", sync_mediawiki.render_sidebar_page())
        self.assertNotIn("Vocomipedia:Admin|Admin", sync_mediawiki.render_sidebar_page())
        self.assertNotIn("Special:SpecialPages|specialpages", sync_mediawiki.render_sidebar_page())
        self.assertNotIn("recentchanges-url|recentchanges", sync_mediawiki.render_sidebar_page())

        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ja_n5:test",
            "pack_code": "ja_n5",
            "language": "ja",
            "entry_id": "川",
            "headword": "川",
            "reading": "かわ",
            "label": "",
            "level": "N5",
            "order": 0,
            "part_of_speech": ["Noun"],
            "glosses": {"en": "river"},
            "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
            "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
            "review": {"status": "needs_review"},
            "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
            "app_payload": {},
        }
        reviewed = sync_mediawiki.record_wiki_review(
            item,
            "Item:ja_n5/test",
            {
                "revision_id": 42,
                "parent_revision_id": 41,
                "revision_timestamp_utc": "2026-06-10T10:00:00Z",
                "revision_user": "Contributor",
                "revision_comment": "Fix example",
            },
        )
        self.assertEqual(reviewed["review"]["status"], "approved")
        self.assertEqual(reviewed["review"]["last_reviewed_utc"], "2026-06-10T10:00:00Z")
        self.assertEqual(reviewed["review"]["wiki"]["revision_id"], 42)

    def test_apply_pulled_rejects_stale_changed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "pack"
            pulled_dir = tmp / "pulled"
            (pack_dir / "items").mkdir(parents=True)
            pulled_dir.mkdir()
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:test",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "川",
                "headword": "川",
                "reading": "かわ",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "river", "de": "Fluss"},
                "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
                "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {},
            }
            (pack_dir / "items" / "item.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "lang_prefix": "ja",
                        "lang_level": "n5",
                        "items": [{"id": item["id"], "entry_id": item["entry_id"], "file": "items/item.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            pulled = json.loads(json.dumps(item))
            pulled["sentences"][0]["translations"]["en"] = "This is a river."
            pulled["review"]["wiki"]["revision_id"] = 4
            (pulled_dir / "item.json").write_text(json.dumps(pulled, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS / "apply_pulled_items.py"),
                    "--deck-dir",
                    str(pack_dir),
                    "--pulled-dir",
                    str(pulled_dir),
                    "--backup-dir",
                    str(tmp / "backups"),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not newer than current recorded revision", result.stdout)

    def test_apply_pulled_merges_visible_fields_without_trusting_hidden_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "pack"
            pulled_dir = tmp / "pulled"
            (pack_dir / "items").mkdir(parents=True)
            pulled_dir.mkdir()
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:test",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "川",
                "headword": "川",
                "reading": "かわ",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "river", "de": "Fluss"},
                "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
                "media": {"image_filename": "comic.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {},
            }
            (pack_dir / "items" / "item.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "title": "Japanese N5",
                        "language": "ja",
                        "lang_prefix": "ja",
                        "lang_level": "n5",
                        "items": [{"id": item["id"], "entry_id": item["entry_id"], "file": "items/item.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            pulled = json.loads(json.dumps(item))
            pulled["headword"] = "河"
            pulled["reading"] = "かわ"
            pulled["glosses"]["en"] = "stream"
            pulled["glosses"].pop("de")
            pulled["sentences"][0]["target"] = "山です。"
            pulled["sentences"][0]["translations"]["en"] = "This is a river."
            pulled["review"]["sentence_proposals"] = [
                {
                    "id": "sentprop-test",
                    "status": "needs_sentence_regeneration",
                    "type": "sentence_replacement",
                    "sentence_index": 1,
                    "old_japanese": "川です。",
                    "proposed_japanese": "山です。",
                    "validation": {"comic_invalidation_supported": False},
                }
            ]
            pulled["media"]["license"] = "external-reference-only"
            pulled["review"]["wiki"]["revision_id"] = 6
            (pulled_dir / "item.json").write_text(json.dumps(pulled, ensure_ascii=False), encoding="utf-8")

            run(
                [
                    sys.executable,
                    str(TOOLS / "apply_pulled_items.py"),
                    "--deck-dir",
                    str(pack_dir),
                    "--pulled-dir",
                    str(pulled_dir),
                    "--backup-dir",
                    str(tmp / "backups"),
                    "--diff-report",
                    str(tmp / "apply.diff"),
                ]
            )
            applied = json.loads((pack_dir / "items" / "item.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["headword"], "河")
            self.assertEqual(applied["reading"], "かわ")
            self.assertEqual(applied["glosses"]["en"], "stream")
            self.assertNotIn("de", applied["glosses"])
            self.assertEqual(applied["sentences"][0]["target"], "川です。")
            self.assertEqual(applied["sentences"][0]["translations"]["en"], "This is a river.")
            self.assertEqual(applied["media"]["license"], "Vocomi-created")
            self.assertEqual(applied["review"]["sentence_proposals"][0]["id"], "sentprop-test")
            self.assertFalse(applied["review"]["sentence_proposals"][0]["validation"]["comic_invalidation_supported"])
            self.assertEqual(applied["review"]["wiki"]["revision_id"], 6)
            self.assertTrue((tmp / "apply.diff").exists())

    def test_sudachi_segments_revise_tokens_dictionary_style(self) -> None:
        sentence = {
            "target": "漢字かな交じり文にふりがなを振ること。",
            "reading": "かんじかなまじりぶんにふりがなをふること。",
            "translations": {"en": "Adds furigana to mixed kanji-kana text."},
            "tokens": [
                {"surface": "漢字", "furigana": "かんじ", "pos": "noun", "lemma": "漢字", "explanation": "", "difficulty": 1},
                {"surface": "かな交じり", "furigana": "かなまじり", "pos": "noun", "lemma": "かな交じり", "explanation": "", "difficulty": 1},
                {"surface": "文", "furigana": "ぶん", "pos": "noun", "lemma": "文", "explanation": "", "difficulty": 1},
                {"surface": "に", "furigana": "に", "pos": "particle", "lemma": "に", "explanation": "", "difficulty": 1},
                {"surface": "ふりがな", "furigana": "ふりがな", "pos": "noun", "lemma": "ふりがな", "explanation": "", "difficulty": 1},
                {"surface": "を", "furigana": "を", "pos": "particle", "lemma": "を", "explanation": "", "difficulty": 1},
                {"surface": "振る", "furigana": "ふる", "pos": "verb", "lemma": "振る", "explanation": "", "difficulty": 1},
                {"surface": "こと", "furigana": "こと", "pos": "noun", "lemma": "こと", "explanation": "", "difficulty": 1},
                {"surface": "。", "furigana": "。", "pos": "punct", "lemma": "。", "explanation": "", "difficulty": 1},
            ],
        }

        class FakeSudachiAnalyzer:
            source = "sudachipy_sudachidict_core_c"

            def analyze(self, text: str) -> list[dict]:
                parts = [
                    ("漢字", "かんじ"),
                    ("かな", "かな"),
                    ("交じり", "まじり"),
                    ("文", "ぶん"),
                    ("に", "に"),
                    ("ふりがな", "ふりがな"),
                    ("を", "を"),
                    ("振る", "ふる"),
                    ("こと", "こと"),
                    ("。", "。"),
                ]
                segments = []
                cursor = 0
                for surface, reading in parts:
                    start = text.find(surface, cursor)
                    end = start + len(surface)
                    segments.append({"surface": surface, "furigana": reading, "start": start, "end": end})
                    cursor = end
                return segments

        revised, stats = revise_japanese_furigana.revise_sentence(sentence, analyzer=FakeSudachiAnalyzer())
        tokens = revised["tokens"]

        self.assertEqual(stats["sudachi"], 9)
        self.assertEqual(stats["fallback"], 0)
        self.assertEqual(tokens[0]["ruby_text"], "漢字[かんじ]")
        self.assertEqual(tokens[1]["ruby_text"], "かな交[ま]じり")
        self.assertEqual(tokens[2]["ruby_text"], "文[ぶん]")
        self.assertEqual(tokens[6]["ruby_text"], "振[ふ]る")
        self.assertEqual(tokens[6]["reading_kana"], "ふる")
        self.assertEqual(tokens[6]["furigana"], "ふる")
        self.assertEqual(tokens[6]["ruby_source"], "sudachipy_sudachidict_core_c")


if __name__ == "__main__":
    unittest.main()
