#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import contextlib
import gzip
import hashlib
import importlib.util
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
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
SYNC_RELEASE_MEDIA_SPEC = importlib.util.spec_from_file_location("sync_release_media_from_vps", TOOLS / "sync_release_media_from_vps.py")
assert SYNC_RELEASE_MEDIA_SPEC and SYNC_RELEASE_MEDIA_SPEC.loader
sync_release_media_from_vps = importlib.util.module_from_spec(SYNC_RELEASE_MEDIA_SPEC)
SYNC_RELEASE_MEDIA_SPEC.loader.exec_module(sync_release_media_from_vps)
MEDIAWIKI_BACKUP_SPEC = importlib.util.spec_from_file_location("mediawiki_backup", TOOLS / "mediawiki_backup.py")
assert MEDIAWIKI_BACKUP_SPEC and MEDIAWIKI_BACKUP_SPEC.loader
mediawiki_backup = importlib.util.module_from_spec(MEDIAWIKI_BACKUP_SPEC)
MEDIAWIKI_BACKUP_SPEC.loader.exec_module(mediawiki_backup)
MEDIAWIKI_SECURITY_AUDIT_SPEC = importlib.util.spec_from_file_location("mediawiki_security_audit", TOOLS / "mediawiki_security_audit.py")
assert MEDIAWIKI_SECURITY_AUDIT_SPEC and MEDIAWIKI_SECURITY_AUDIT_SPEC.loader
mediawiki_security_audit = importlib.util.module_from_spec(MEDIAWIKI_SECURITY_AUDIT_SPEC)
MEDIAWIKI_SECURITY_AUDIT_SPEC.loader.exec_module(mediawiki_security_audit)
CHANGED_ITEMS_SPEC = importlib.util.spec_from_file_location("changed_deck_items", TOOLS / "changed_deck_items.py")
assert CHANGED_ITEMS_SPEC and CHANGED_ITEMS_SPEC.loader
changed_deck_items = importlib.util.module_from_spec(CHANGED_ITEMS_SPEC)
CHANGED_ITEMS_SPEC.loader.exec_module(changed_deck_items)
COMBINED_ASSETS_SPEC = importlib.util.spec_from_file_location("ios_package_assets_combined", TOOLS / "pack_builder" / "ios_package_assets_combined.py")
assert COMBINED_ASSETS_SPEC and COMBINED_ASSETS_SPEC.loader
ios_package_assets_combined = importlib.util.module_from_spec(COMBINED_ASSETS_SPEC)
COMBINED_ASSETS_SPEC.loader.exec_module(ios_package_assets_combined)
DECKSEARCH_SPEC = importlib.util.spec_from_file_location("decksearch_prebuilt_index", TOOLS / "pack_builder" / "decksearch_prebuilt_index.py")
assert DECKSEARCH_SPEC and DECKSEARCH_SPEC.loader
decksearch_prebuilt_index = importlib.util.module_from_spec(DECKSEARCH_SPEC)
sys.modules["decksearch_prebuilt_index"] = decksearch_prebuilt_index
DECKSEARCH_SPEC.loader.exec_module(decksearch_prebuilt_index)
import common
import apply_pulled_items
import wiki_visible_fields
from vocomipedia_nlp import analyze_sentence, ensure_real_analyzer_available, sync_item_pos_analysis
import vocomipedia_nlp.base as nlp_base


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
    def test_next_level_catalog_combined_pack_mapping(self) -> None:
        catalog = __import__("yaml").safe_load((ROOT / "catalog" / "packs.yaml").read_text(encoding="utf-8"))["packs"]
        self.assertEqual(catalog["ja_n5"]["data_pack_code"], "ja_n5-n3")
        self.assertEqual(catalog["ja_n4"]["data_pack_code"], "ja_n5-n3")
        self.assertEqual(catalog["ja_n3"]["data_pack_code"], "ja_n5-n3")
        self.assertEqual(catalog["ja_n3"]["source_json"], "vocomi_pack_generation/language_packs/japanese_N3/ja_n3_structure.json")
        self.assertEqual(catalog["es_a1"]["data_pack_code"], "es_a1-a2")
        self.assertEqual(catalog["es_a2"]["data_pack_code"], "es_a1-a2")
        self.assertEqual(catalog["ko_1"]["data_pack_code"], "ko_1-2")
        self.assertEqual(catalog["ko_2"]["data_pack_code"], "ko_1-2")

    def test_pack_manifests_match_catalog_data_pack_codes(self) -> None:
        catalog = __import__("yaml").safe_load((ROOT / "catalog" / "packs.yaml").read_text(encoding="utf-8"))["packs"]
        for code, cfg in catalog.items():
            manifest_path = ROOT / "data" / "languages" / str(cfg["language"]) / code / "pack.json"
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest.get("data_pack_code"),
                cfg.get("data_pack_code"),
                f"{code} data_pack_code mismatch",
            )

    def test_catalog_decks_resolves_all_catalog_decks(self) -> None:
        result = run([sys.executable, str(TOOLS / "catalog_decks.py"), "--all"])
        decks = result.stdout.strip().split()
        catalog = common.load_pack_catalog(ROOT / "catalog" / "packs.yaml")
        self.assertEqual(decks, sorted(catalog))
        self.assertIn("ko_1", decks)
        self.assertIn("ko_2", decks)

    def test_catalog_decks_accepts_workflow_deck_string(self) -> None:
        result = run([sys.executable, str(TOOLS / "catalog_decks.py"), "--deck-string", "ko_2 ko_1"])
        self.assertEqual(result.stdout.strip(), "ko_1 ko_2")

    def test_catalog_decks_emits_workflow_matrices(self) -> None:
        all_decks = run([sys.executable, str(TOOLS / "catalog_decks.py"), "--all", "--format", "json"])
        decks = json.loads(all_decks.stdout)
        self.assertIn("ko_1", decks)
        self.assertIn("ko_2", decks)

        combined = run(
            [
                sys.executable,
                str(TOOLS / "catalog_decks.py"),
                "--deck-string",
                "ko_2 ko_1",
                "--combined-data-codes",
                "--format",
                "json",
            ]
        )
        self.assertEqual(json.loads(combined.stdout), ["ko_1-2"])

        components = run([sys.executable, str(TOOLS / "catalog_decks.py"), "--data-pack-code-components", "ko_1-2"])
        self.assertEqual(components.stdout.strip(), "ko_1 ko_2")

    def test_catalog_decks_requires_explicit_selection(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOLS / "catalog_decks.py")],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Provide at least one deck", result.stdout)

    def test_combined_asset_builder_condenses_numeric_levels(self) -> None:
        self.assertEqual(ios_package_assets_combined.condense_levels(["1", "2"]), ("1-2", ["1", "2"]))
        self.assertEqual(ios_package_assets_combined.dir_label_from_levels(["1", "2"]), "1-2")

    def test_combined_asset_builder_normalizes_mixed_language_fields(self) -> None:
        fixed = {"word", "jp", "fu", "png_files", "palette_png_files", "comic_difficulty", "pos_analysis"}
        entries = [
            {"word": "것", "ko": ["그것이에요."], "en": ["It is that."], "de": ["Das ist es."]},
            {"word": "등", "ko": ["1등이에요."], "en": ["It is first place."]},
        ]

        langs = ios_package_assets_combined.normalize_sentence_language_fields(entries, fixed)

        self.assertEqual(langs, ["de", "en", "ko"])
        self.assertEqual(entries[1]["de"], [""])

    def test_decksearch_index_keeps_multilingual_sentences_out_of_global_body(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_db = tmp / "ko_1-2.db"
            conn = sqlite3.connect(source_db)
            try:
                conn.execute("CREATE TABLE vocab(id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
                conn.execute(
                    "INSERT INTO vocab(id, metadata) VALUES (?, ?)",
                    (
                        "nom",
                        json.dumps(
                            {
                                "word": "놈",
                                "word_reading": "nom",
                                "word_en": "a fellow",
                                "ko": ["그 놈이 또 약속을 안 지켰어요."],
                                "en": ["That cat climbed onto the table again."],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            out_db = tmp / "decksearch.sqlite3"
            decksearch_prebuilt_index.build_single_index(
                source_db,
                out_db,
                pack_code="ko_1-2",
                pack_version="test",
                ui_lang_ids=["en"],
            )

            conn = sqlite3.connect(out_db)
            try:
                body = conn.execute(
                    "SELECT body_norm FROM decksearch_entries WHERE entry_id='nom'"
                ).fetchone()[0]
                self.assertNotIn("cat", body)
                self.assertNotIn("climbed", body)
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(1) FROM decksearch_postings
                        WHERE kind='trans_prefix' AND token='cat' AND ui_lang_id='en'
                        """
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(1) FROM decksearch_postings
                        WHERE kind='sent_token' AND token='cat' AND ui_lang_id='en'
                        """
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(1) FROM decksearch_postings
                        WHERE kind='sent_token' AND token='climbed' AND ui_lang_id='en'
                        """
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_decksearch_index_keeps_romanized_readings_out_of_global_body(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_db = tmp / "ko_1-2.db"
            conn = sqlite3.connect(source_db)
            try:
                conn.execute("CREATE TABLE vocab(id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
                conn.execute(
                    "INSERT INTO vocab(id, metadata) VALUES (?, ?)",
                    (
                        "gwan",
                        json.dumps(
                            {
                                "word": "기관",
                                "word_reading": "gigwan",
                                "word_en": "an engine or a machine",
                                "ko": ["새 기관을 달면 속도가 빨라져요."],
                                "fu": ["sae gigwan eul damyeon sokdoga ppallajyeoyo."],
                                "en": ["If you install a new engine, the speed increases."],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            out_db = tmp / "decksearch.sqlite3"
            decksearch_prebuilt_index.build_single_index(
                source_db,
                out_db,
                pack_code="ko_1-2",
                pack_version="test",
                ui_lang_ids=["en"],
            )

            conn = sqlite3.connect(out_db)
            try:
                body = conn.execute(
                    "SELECT body_norm FROM decksearch_entries WHERE entry_id='gwan'"
                ).fetchone()[0]
                self.assertNotIn("gigwan", body)
                self.assertNotIn("sokdoga", body)
                self.assertGreater(
                    conn.execute(
                        """
                        SELECT COUNT(1) FROM decksearch_postings
                        WHERE kind='reading_prefix' AND token='sokd' AND ui_lang_id=''
                        """
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_release_export_annotates_korean_main_word_without_source_flags(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ko_2:test",
            "pack_code": "ko_2",
            "language": "ko",
            "entry_id": "해설",
            "headword": "해설",
            "reading": "",
            "label": "Commentary",
            "level": "TOPIK 2",
            "part_of_speech": ["Noun"],
            "glosses": {"en": "commentary", "ko": "해설"},
            "sentences": [
                {
                    "target": "선생님의 해설을 들으니 이해가 됐어요.",
                    "translations": {"en": "I understood after hearing the teacher's explanation."},
                    "tokens": [
                        {"surface": "선생님의", "lemma": "선생님의", "pos": "X"},
                        {"surface": "해설을", "lemma": "해설을", "pos": "X"},
                        {"surface": "들으니", "lemma": "들으니", "pos": "X"},
                    ],
                    "difficulty": 2,
                }
            ],
            "media": {},
            "review": {},
            "provenance": {},
            "app_payload": {},
        }
        payload = common.canonical_to_legacy(item, pack={"target_sentence_key": "jp", "reading_sentence_key": "fu"})
        tokens = payload["pos_analysis"][0]["tokens"]
        self.assertEqual([token["is_main_word"] for token in tokens], [False, True, False])

    def test_release_export_rebuilds_derived_legacy_payload_fields(self) -> None:
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
            "part_of_speech": ["Noun"],
            "glosses": {"en": "stream"},
            "sentences": [
                {
                    "target": "川です。",
                    "reading": "かわです。",
                    "translations": {"en": "This is a stream."},
                    "tokens": [],
                    "difficulty": 1,
                }
            ],
            "media": {},
            "review": {},
            "provenance": {},
            "app_payload": {
                "word_en": "river",
                "word_de": "Fluss",
                "word_label": "old label",
                "en": ["It is a river."],
                "de": ["Es ist ein Fluss."],
            },
        }
        payload = common.canonical_to_legacy(item, pack={"target_sentence_key": "jp", "reading_sentence_key": "fu"})
        self.assertEqual(payload["word_en"], "stream")
        self.assertEqual(payload["en"], ["This is a stream."])
        self.assertNotIn("word_de", payload)
        self.assertNotIn("word_label", payload)
        self.assertNotIn("de", payload)

    def test_release_export_annotates_korean_dictionary_verbs_without_pos(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ko_2:test-verb",
            "pack_code": "ko_2",
            "language": "ko",
            "entry_id": "구속하다",
            "headword": "구속하다",
            "reading": "",
            "label": "To arrest",
            "level": "TOPIK 2",
            "part_of_speech": ["Verb"],
            "glosses": {"en": "arrest", "ko": "구속하다"},
            "sentences": [
                {
                    "target": "경찰이 범인을 구속했어요.",
                    "translations": {"en": "The police arrested the criminal."},
                    "tokens": [
                        {"surface": "경찰이", "lemma": "경찰이", "pos": "X"},
                        {"surface": "범인을", "lemma": "범인을", "pos": "X"},
                        {"surface": "구속했어요", "lemma": "구속했어요", "pos": "X"},
                    ],
                    "difficulty": 2,
                }
            ],
            "media": {},
            "review": {},
            "provenance": {},
            "app_payload": {},
        }
        payload = common.canonical_to_legacy(item, pack={"target_sentence_key": "jp", "reading_sentence_key": "fu"})
        tokens = payload["pos_analysis"][0]["tokens"]
        self.assertEqual([token["is_main_word"] for token in tokens], [False, False, True])

    def test_release_export_annotates_split_korean_hada_compounds(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ko_2:test-split-verb",
            "pack_code": "ko_2",
            "language": "ko",
            "entry_id": "구속하다",
            "headword": "구속하다",
            "reading": "",
            "label": "To arrest",
            "level": "TOPIK 2",
            "part_of_speech": ["Verb"],
            "glosses": {"en": "arrest", "ko": "구속하다"},
            "sentences": [
                {
                    "target": "경찰이 범인을 구속했어요.",
                    "translations": {"en": "The police arrested the criminal."},
                    "tokens": [
                        {"surface": "경찰", "lemma": "경찰", "pos": "NOUN"},
                        {"surface": "이", "lemma": "이", "pos": "PART"},
                        {"surface": "범인", "lemma": "범인", "pos": "NOUN"},
                        {"surface": "을", "lemma": "을", "pos": "PART"},
                        {"surface": "구속", "lemma": "구속", "pos": "NOUN"},
                        {"surface": "하", "lemma": "하", "pos": "AUX"},
                        {"surface": "었어요", "lemma": "었어요", "pos": "PART"},
                    ],
                    "difficulty": 2,
                }
            ],
            "media": {},
            "review": {},
            "provenance": {},
            "app_payload": {},
        }
        payload = common.canonical_to_legacy(item, pack={"target_sentence_key": "jp", "reading_sentence_key": "fu"})
        tokens = payload["pos_analysis"][0]["tokens"]
        self.assertEqual([token["is_main_word"] for token in tokens], [False, False, False, False, True, False, False])

    def test_korean_auto_pos_requires_kiwi_analyzer(self) -> None:
        nlp_base.analyzer_for_language.cache_clear()
        try:
            with mock.patch.object(nlp_base, "KiwiAnalyzer", side_effect=RuntimeError("missing kiwi")):
                with self.assertRaises(nlp_base.RequiredAnalyzerUnavailable):
                    nlp_base.analyzer_for_language("ko")
        finally:
            nlp_base.analyzer_for_language.cache_clear()

    def test_release_ready_rejects_korean_fallback_pos_tokens(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ko_2:test",
            "pack_code": "ko_2",
            "language": "ko",
            "entry_id": "구속하다",
            "headword": "구속하다",
            "reading": "",
            "sentences": [
                {
                    "target": "경찰이 범인을 구속했어요.",
                    "translations": {"en": "The police arrested the criminal."},
                    "tokens": [
                        {
                            "surface": "구속했어요",
                            "lemma": "구속했어요",
                            "upos": "X",
                            "analyzer": "fallback_unicode_rules",
                        }
                    ],
                }
            ],
            "media": {"license": "Vocomi-created", "review_status": "approved"},
            "review": {"status": "approved"},
            "provenance": {"license_status": "generated_by_vocomi"},
            "app_payload": {},
        }
        errors = common.validate_item(item, require_release_ready=True, release_allowed_licenses={"Vocomi-created"})
        self.assertTrue(any("fallback Korean POS analyzer" in error for error in errors), errors)
        self.assertTrue(any("unknown Korean POS X" in error for error in errors), errors)

    def test_auto_pos_analysis_normalizes_known_korean_legacy_x_tokens(self) -> None:
        item = {
            "schema_version": "vocomipedia-item-2",
            "id": "ko_1:test",
            "pack_code": "ko_1",
            "language": "ko",
            "entry_id": "다섯째",
            "headword": "다섯째",
            "reading": "",
            "sentences": [
                {
                    "target": "이 단어 '보내다'는 'send'라는 뜻이에요.",
                    "translations": {"en": "This word means send."},
                    "tokens": [
                        {"surface": "'send'", "lemma": "send", "pos": "X", "surface_en": "send", "furigana": "[sɛnd]"}
                    ],
                },
                {
                    "target": "저는 다섯째 줄이에요.",
                    "translations": {"en": "I am in the fifth row."},
                    "tokens": [
                        {"surface": "째", "lemma": "째", "pos": "X", "surface_en": "th", "explanation": "ordinal suffix"}
                    ],
                },
            ],
            "media": {"license": "Vocomi-created", "review_status": "approved"},
            "review": {"status": "approved"},
            "provenance": {"license_status": "generated_by_vocomi"},
            "app_payload": {},
        }
        nlp_base.sync_item_pos_analysis(item, regenerate=True)
        self.assertEqual(item["sentences"][0]["tokens"][0]["upos"], "NOUN")
        self.assertEqual(item["sentences"][0]["tokens"][0]["xpos"], "SL")
        self.assertEqual(item["sentences"][1]["tokens"][0]["upos"], "PART")
        self.assertEqual(item["sentences"][1]["tokens"][0]["xpos"], "XSN")
        errors = common.validate_item(item, require_release_ready=True, release_allowed_licenses={"Vocomi-created"})
        self.assertFalse(any("unknown Korean POS X" in error for error in errors), errors)

    def test_vps_partial_pack_deploy_preserves_existing_catalog(self) -> None:
        script = deploy_packs_to_vps.remote_deploy_script("/srv/vocomi-packs", "test-release", 3)
        self.assertIn('find -L "$root/current"', script)
        self.assertIn("-name '*.vpack'", script)
        self.assertIn("-name 'release-state.json'", script)
        self.assertIn("release-files.json", script)
        self.assertIn("superseded_keys", script)
        self.assertIn("release-state.previous.json", script)
        self.assertIn('state["deck_git_sha"] = deck_git_sha', script)
        self.assertIn("rm -f packs.json packs-images.json", script)
        self.assertIn("python3 - <<'PY'", script)
        self.assertIn('root.glob("*.meta.json")', script)
        self.assertIn('(root / "packs-images.json").write_text', script)
        self.assertLess(script.find('find -L "$root/current"'), script.find('tar -xzf "$root/incoming/$name.tar.gz"'))
        self.assertLess(script.find('rm -f packs.json packs-images.json'), script.find("if compgen -G"))

    def test_deploy_archive_tracks_new_meta_files_for_stale_pack_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "ko_2_test.vpack").write_bytes(b"vpack")
            (tmp / "ko_2_test.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
            (tmp / "ko_2_test.meta.json").write_text(
                json.dumps(
                    {
                        "name": "ko_2_test.vpack",
                        "lang_prefix": "ko",
                        "lang_level": "2",
                        "pack_kind": "images",
                        "data_pack_code": "ko_1-2",
                    }
                ),
                encoding="utf-8",
            )

            release_files = deploy_packs_to_vps.write_release_files(tmp)
            files = deploy_packs_to_vps.collect_artifacts(tmp)
            payload = json.loads(release_files.read_text(encoding="utf-8"))

            self.assertIn(release_files.resolve(), {path.resolve() for path in files})
            self.assertEqual(payload["meta_files"], ["ko_2_test.meta.json"])

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
        self.assertIn("Prepare remote MediaWiki checkout and backup", workflow)
        self.assertIn("tools/mediawiki_backup.py backup", workflow)
        self.assertIn("tools/mediawiki_backup.py verify", workflow)
        self.assertIn("Reconcile MediaWiki entry images", workflow)
        self.assertIn("sync-images-api", workflow)
        self.assertIn("Refresh MediaWiki deck indexes", workflow)
        self.assertIn("--changed-items-file tmp/changed-items/none.txt", workflow)
        self.assertIn("--skip-entry-images", workflow)
        self.assertIn("--source-sha \"${{ github.sha }}\"", workflow)
        self.assertIn("process_all_decks:", workflow)
        self.assertIn("REQUESTED_DECK_INPUT: ${{ inputs.deck_codes }}", workflow)
        self.assertIn("REQUESTED_DECK_CODES=\"$(python tools/catalog_decks.py --all)\"", workflow)
        self.assertIn("REQUESTED_DECK_CODES=\"$(python tools/catalog_decks.py --deck-string \"$REQUESTED_DECK_INPUT\")\"", workflow)
        self.assertIn("requested_decks_json: ${{ steps.plan.outputs.requested_decks_json }}", workflow)
        self.assertIn("combined_data_codes_json: ${{ steps.plan.outputs.combined_data_codes_json }}", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("Refuse release while wiki sync PRs are open", workflow)
        self.assertIn('startswith("vocomipedia/wiki-sync-")', workflow)
        self.assertIn("Running it while a wiki-sync PR is open can publish stale pack data.", workflow)
        self.assertEqual(workflow.count("environment: production"), 1)
        self.assertIn("production-approval:", workflow)
        self.assertIn("secrets-preflight:", workflow)
        self.assertIn("Single-approval matrix releases cannot use secrets stored only in the protected production environment.", workflow)
        self.assertIn("build-deck:", workflow)
        self.assertIn("build-combined:", workflow)
        self.assertIn("mediawiki-backup:", workflow)
        self.assertIn("mediawiki-deck:", workflow)
        self.assertIn("matrix:", workflow)
        self.assertIn("deck: ${{ fromJson(needs.plan.outputs.requested_decks_json) }}", workflow)
        self.assertIn("data_pack_code: ${{ fromJson(needs.plan.outputs.combined_data_codes_json) }}", workflow)
        self.assertIn("max-parallel: 1", workflow)
        self.assertIn("actions/download-artifact@v6", workflow)
        self.assertIn("pattern: vocomipedia-release-pack-*", workflow)
        self.assertIn("merge-multiple: true", workflow)
        self.assertIn(
            "SYNC_DECK_CODES=\"$(python tools/catalog_decks.py --decks $REQUESTED_DECK_CODES --with-combined-siblings)\"",
            workflow,
        )
        self.assertIn("--updated-decks $REQUESTED_DECK_CODES", workflow)

    def test_production_workflows_serialize_mutating_runs(self) -> None:
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        sync_back = (ROOT / ".github" / "workflows" / "wiki-sync-back.yml").read_text(encoding="utf-8")
        self.assertIn("concurrency:", release)
        self.assertIn("group: vocomipedia-production-release", release)
        self.assertIn("cancel-in-progress: false", release)
        self.assertLess(release.find("Rebuild remote search projection"), release.find("Deploy pack artifacts to VPS"))
        self.assertIn("concurrency:", sync_back)
        self.assertIn("group: vocomipedia-production-wiki-sync-back", sync_back)
        self.assertIn("process_all_decks:", sync_back)
        self.assertIn("REQUESTED_DECK_INPUT: ${{ inputs.deck_codes }}", sync_back)
        self.assertEqual(sync_back.count("environment: production"), 1)
        self.assertIn("production-approval:", sync_back)
        self.assertIn("secrets-preflight:", sync_back)
        self.assertIn("Single-approval matrix sync-back cannot use secrets stored only in the protected production environment.", sync_back)
        self.assertIn("REQUESTED_DECK_CODES=\"$(python tools/catalog_decks.py --all)\"", sync_back)
        self.assertIn("REQUESTED_DECK_CODES=\"$(python tools/catalog_decks.py --deck-string \"$REQUESTED_DECK_INPUT\")\"", sync_back)
        self.assertIn("sync-back-deck:", sync_back)
        self.assertIn("aggregate:", sync_back)
        self.assertIn("max-parallel: 1", sync_back)
        self.assertIn("deck: ${{ fromJson(needs.plan.outputs.requested_decks_json) }}", sync_back)
        self.assertIn("pattern: vocomipedia-wiki-sync-back-*", sync_back)
        self.assertIn("PYTHONPATH: tools", sync_back)
        self.assertIn("Resolve per-deck artifact paths", sync_back)
        self.assertIn("path: ${{ steps.artifact-paths.outputs.paths }}", sync_back)
        self.assertIn('if [ -n "${DECK_DIR:-}" ]; then', sync_back)
        self.assertNotIn("${{ steps.deck-path.outputs.deck_dir }}/**", sync_back)
        self.assertIn("tools/merge_wiki_sync_reports.py", sync_back)
        self.assertIn("--decks \"$DECK_CODE\"", sync_back)
        self.assertIn("VOCOMI_REPO_TOKEN: ${{ secrets.VOCOMI_REPO_TOKEN }}", sync_back)
        self.assertIn('TOKEN_LABEL="VOCOMI_REPO_TOKEN"', sync_back)
        self.assertIn("exit 1", sync_back)

    def test_release_media_hydration_does_not_delete_local_media(self) -> None:
        script = (TOOLS / "sync_release_media_from_vps.py").read_text(encoding="utf-8")
        self.assertIn('"rsync"', script)
        self.assertNotIn('"--delete"', script)

    def test_merge_wiki_sync_reports_combines_per_deck_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            reports = Path(td) / "reports" / "wiki-sync-back"
            for deck, pulled in [("ko_1", 2), ("ko_2", 3)]:
                deck_dir = reports / deck
                deck_dir.mkdir(parents=True)
                (deck_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "decks": [
                                {
                                    "deck": deck,
                                    "pulled_count": pulled,
                                    "applied_files": pulled,
                                    "canonical_dir": f"/tmp/{deck}",
                                    "source_changed": deck == "ko_2",
                                }
                            ],
                            "active_sentence_proposals": [],
                        }
                    ),
                    encoding="utf-8",
                )

            run([sys.executable, str(TOOLS / "merge_wiki_sync_reports.py"), "--reports-dir", str(reports), "--export-source"])
            summary = (reports / "summary.md").read_text(encoding="utf-8")
            payload = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
            self.assertIn("| ko_1 | 2 | 2 | /tmp/ko_1 | no |", summary)
            self.assertIn("| ko_2 | 3 | 3 | /tmp/ko_2 | yes |", summary)
            self.assertEqual([row["deck"] for row in payload["decks"]], ["ko_1", "ko_2"])

    def test_mediawiki_backup_bundle_verification_checks_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db = tmp / "db.sql.gz"
            with gzip.open(db, "wb") as out:
                out.write(b"-- test dump\nCREATE TABLE page (page_id int);\n")
            images = tmp / "images.tar.gz"
            with tarfile.open(images, "w:gz") as tf:
                info = tarfile.TarInfo("images/example.jpg")
                payload = b"image"
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            config = tmp / "config.tar.gz"
            with tarfile.open(config, "w:gz") as tf:
                info = tarfile.TarInfo("docker/local/LocalSettings.php")
                payload = b"<?php\n"
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            manifest = {
                "schema_version": "vocomipedia-mediawiki-backup-1",
                "files": {
                    path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
                    for path in [db, images, config]
                },
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            bundle = tmp / "backup.tar.gz"
            with tarfile.open(bundle, "w:gz") as tf:
                for path in [tmp / "manifest.json", db, images, config]:
                    tf.add(path, arcname=path.name)

            verified = mediawiki_backup.verify_backup(bundle)
            self.assertEqual(verified["schema_version"], "vocomipedia-mediawiki-backup-1")

    def test_mediawiki_backup_systemd_units_are_daily_and_secret_aware(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            service = tmp / "vocomipedia-mediawiki-backup.service"
            timer = tmp / "vocomipedia-mediawiki-backup.timer"
            mediawiki_backup.write_systemd_units(
                service_path=service,
                timer_path=timer,
                root=ROOT,
                backup_dir=Path("/srv/backups/vocomipedia"),
                hour_utc=2,
            )
            self.assertIn("tools/mediawiki_backup.py backup", service.read_text(encoding="utf-8"))
            self.assertIn("--latest-symlink", service.read_text(encoding="utf-8"))
            self.assertIn("--keep-count 14", service.read_text(encoding="utf-8"))
            self.assertIn("OnCalendar=*-*-* 02:17:00 UTC", timer.read_text(encoding="utf-8"))
            self.assertIn("Persistent=true", timer.read_text(encoding="utf-8"))

    def test_mediawiki_backup_prunes_old_archives_by_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            paths = []
            for index in range(4):
                path = tmp / f"2026010{index}T000000Z-mediawiki.tar.gz"
                path.write_text(str(index), encoding="utf-8")
                os.utime(path, (index, index))
                paths.append(path)
            removed = mediawiki_backup.prune_backups(tmp, keep_count=2)
            self.assertEqual({path.name for path in removed}, {paths[0].name, paths[1].name})
            self.assertEqual(
                {path.name for path in tmp.glob("*-mediawiki.tar.gz")},
                {paths[2].name, paths[3].name},
            )

    def test_mediawiki_security_config_requires_privileged_2fa_and_rate_limits(self) -> None:
        skeleton = (ROOT / "docker" / "LocalSettings.vocomipedia.php").read_text(encoding="utf-8")
        compose = (ROOT / "docker" / "compose.local.yml").read_text(encoding="utf-8")
        self.assertIn("wfLoadExtension( 'OATHAuth' );", skeleton)
        self.assertIn("$wgOATHRequiredForGroups", skeleton)
        self.assertIn("'sysop'", skeleton)
        self.assertIn("'bureaucrat'", skeleton)
        self.assertIn("'moderator'", skeleton)
        self.assertIn("$wgStrictFileExtensions = true;", skeleton)
        self.assertNotIn("$wgRateLimits = [];", skeleton)
        self.assertIn("$wgGroupPermissions['bot']['noratelimit'] = true;", skeleton)
        self.assertIn("$wgGroupPermissions['sysop']['noratelimit'] = true;", skeleton)
        self.assertIn("MW_REQUIRE_PRIVILEGED_2FA: ${MW_REQUIRE_PRIVILEGED_2FA:-0}", compose)

        with tempfile.TemporaryDirectory() as td:
            settings = Path(td) / "LocalSettings.php"
            settings.write_text(skeleton, encoding="utf-8")
            checks = {check["id"]: check["ok"] for check in mediawiki_security_audit.setting_checks(settings)}
            self.assertTrue(checks["oathauth_loaded"])
            self.assertTrue(checks["oath_required_groups"])
            self.assertTrue(checks["strict_file_extensions"])
            self.assertTrue(checks["rate_limits_not_disabled"])
            self.assertTrue(checks["bot_noratelimit"])

    def test_mediawiki_edit_retries_api_ratelimit_response(self) -> None:
        client = object.__new__(sync_mediawiki.MediaWikiClient)
        client.api_ratelimit_attempts = 2
        client.api_ratelimit_initial_sleep = 0.01
        responses = [
            {"error": {"code": "ratelimited", "info": "wait"}},
            {"edit": {"result": "Success"}},
        ]
        calls = []

        def fake_request(params: dict, method: str = "POST") -> dict:
            calls.append(params)
            return responses.pop(0)

        client.request = fake_request
        with mock.patch.object(sync_mediawiki.time, "sleep") as sleep:
            client.edit("Item:test", "text", "summary", "token")

        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()

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

    def test_changed_deck_items_ignores_review_metadata_only_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run(["git", "init"], cwd=tmp)
            run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp)
            run(["git", "config", "user.name", "Test User"], cwd=tmp)
            pack_dir = tmp / "data" / "languages" / "ja" / "ja_n5"
            item_dir = pack_dir / "items"
            item_dir.mkdir(parents=True)
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:one",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "川",
                "headword": "川",
                "reading": "かわ",
                "label": "",
                "level": "N5",
                "part_of_speech": ["Noun"],
                "glosses": {"en": "river"},
                "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
                "media": {"image_filename": "comic.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 1, "pulled_utc": "2026-01-01T00:00:00Z"}},
                "provenance": {},
                "app_payload": {"word_en": "river"},
            }
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n5",
                        "items": [{"id": "ja_n5:one", "entry_id": "川", "file": "items/one.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "base"], cwd=tmp)
            base = run(["git", "rev-parse", "HEAD"], cwd=tmp).stdout.strip()

            item["review"]["wiki"]["revision_id"] = 2
            item["review"]["wiki"]["pulled_utc"] = "2026-01-02T00:00:00Z"
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "metadata only"], cwd=tmp)
            self.assertEqual(changed_deck_items.changed_item_paths(tmp, base, "HEAD", pack_dir), [])

            item["sentences"][0]["tokens"] = [{"surface": "川", "pos": "NOUN", "difficulty": 1}]
            item["sentences"][0]["difficulty"] = 99
            item["app_payload"]["pos_analysis"] = [
                {
                    "sentence": "川です。",
                    "tokens": [{"surface": "川", "pos": "NOUN", "difficulty": 1}],
                    "difficulty_aggregated": 99,
                }
            ]
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "analysis only"], cwd=tmp)
            self.assertEqual(changed_deck_items.changed_item_paths(tmp, base, "HEAD", pack_dir), [])

            item["glosses"]["en"] = "stream"
            (item_dir / "one.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            run(["git", "add", "."], cwd=tmp)
            run(["git", "commit", "-m", "visible change"], cwd=tmp)
            self.assertEqual(changed_deck_items.changed_item_paths(tmp, base, "HEAD", pack_dir), ["items/one.json"])

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
            Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(asset_dir / "comic_愛__あい__sample_blank_pal.png")

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
            with Image.open(pack_dir / "media" / "comic_愛__あい__sample_blank.png") as copied:
                self.assertEqual(copied.convert("RGBA").getpixel((0, 0)), (1, 2, 3, 255))
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

    def test_strict_media_validation_rejects_case_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            media_root = Path(td)
            (media_root / "Comic.png").write_bytes(b"not really a png")
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "ja_n5:test",
                "pack_code": "ja_n5",
                "language": "ja",
                "entry_id": "test",
                "headword": "test",
                "reading": "",
                "label": "",
                "level": "N5",
                "part_of_speech": ["Noun"],
                "glosses": {"en": "test"},
                "sentences": [],
                "media": {
                    "image_filename": "comic.png",
                    "source_image_filename": "comic.png",
                    "license": "Vocomi-created",
                    "review_status": "approved",
                },
                "review": {"status": "approved"},
                "provenance": {},
                "app_payload": {},
            }
            errors = common.validate_item(item, strict_media_root=media_root)
            self.assertIn("missing media file: comic.png", errors)

    def test_strict_media_validation_checks_app_image_not_import_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            media_root = Path(td)
            (media_root / "comic_test__v2_blank.png").write_bytes(b"not really a png")
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "de_a1:test",
                "pack_code": "de_a1",
                "language": "de",
                "entry_id": "Test__v2",
                "headword": "Test",
                "reading": "",
                "label": "",
                "level": "A1",
                "part_of_speech": ["Noun"],
                "glosses": {"en": "test"},
                "sentences": [],
                "media": {
                    "image_filename": "comic_test__v2_blank.png",
                    "source_image_filename": "comic_Test_blank.png",
                    "license": "Vocomi-created",
                    "review_status": "approved",
                },
                "review": {"status": "approved"},
                "provenance": {},
                "app_payload": {},
            }
            errors = common.validate_item(item, strict_media_root=media_root)
            self.assertNotIn("missing media file: comic_Test_blank.png", errors)
            self.assertNotIn("missing media file: comic_test__v2_blank.png", errors)

    def test_copy_item_media_resolves_source_case_but_writes_canonical_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_root = tmp / "source"
            dest_root = tmp / "dest"
            source_root.mkdir()
            (source_root / "Comic_Test_blank.png").write_bytes(b"not really a png")
            item = {
                "media": {
                    "image_filename": "comic_test_blank.png",
                    "source_image_filename": "comic_test_blank.png",
                }
            }

            copied = common.copy_item_media(item, [source_root], dest_root)

            self.assertEqual(copied, dest_root / "comic_test_blank.png")
            self.assertTrue(common.path_exists_exact(dest_root, "comic_test_blank.png"))
            self.assertFalse(common.path_exists_exact(dest_root, "Comic_Test_blank.png"))

    def test_release_media_hydration_materializes_canonical_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td) / "de" / "de_a1"
            media_dir = pack_dir / "media"
            items_dir = pack_dir / "items"
            media_dir.mkdir(parents=True)
            items_dir.mkdir()
            (media_dir / "comic_bitte_blank.png").write_bytes(b"image")
            item = {
                "schema_version": common.ITEM_SCHEMA_VERSION,
                "id": "de_a1:bitte-1eddbdf4ab037fea",
                "pack_code": "de_a1",
                "language": "de",
                "entry_id": "bitte__v2",
                "headword": "bitte",
                "reading": "",
                "sentences": [],
                "media": {
                    "image_filename": "comic_bitte__v2_blank.png",
                    "source_image_filename": "comic_bitte_blank.png",
                    "license": "Vocomi-created",
                    "review_status": "approved",
                },
                "review": {"status": "approved"},
                "provenance": {"license_status": "generated_by_vocomi"},
                "app_payload": {},
            }
            (items_dir / "bitte.json").write_text(json.dumps(item), encoding="utf-8")
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": common.PACK_SCHEMA_VERSION,
                        "pack_code": "de_a1",
                        "language": "de",
                        "items": [{"entry_id": "bitte__v2", "file": "items/bitte.json", "order": 1}],
                    }
                ),
                encoding="utf-8",
            )

            count = sync_release_media_from_vps.materialize_media_aliases(pack_dir)

            self.assertEqual(count, 1)
            self.assertTrue(common.path_exists_exact(media_dir, "comic_bitte__v2_blank.png"))
            self.assertEqual((media_dir / "comic_bitte__v2_blank.png").read_bytes(), b"image")

    def test_auto_pos_analysis_preserves_legacy_tokens_when_only_fallback_is_available(self) -> None:
        nlp_base.analyzer_for_language.cache_clear()
        item = {
            "language": "de",
            "app_payload": {},
            "sentences": [
                {
                    "target": "Heute Abend.",
                    "reading": "/ˈhɔʏtə ˈaːbn̩t/",
                    "tokens": [
                        {
                            "surface": "Heute",
                            "surface_en": "today",
                            "furigana": "[ˈhɔʏ̯tə]",
                            "pos": "ADV",
                            "lemma": "heute",
                            "explanation": "Temporal adverb.",
                            "difficulty": 7,
                            "is_main_word": False,
                        },
                        {
                            "surface": "Abend.",
                            "surface_en": "evening",
                            "furigana": "[ˈaːbn̩t]",
                            "pos": "NOUN",
                            "lemma": "Abend",
                            "explanation": "Common noun.",
                            "difficulty": 7,
                            "is_main_word": True,
                        },
                    ],
                    "difficulty": 7,
                }
            ],
        }

        try:
            with mock.patch.object(nlp_base, "SpacyAnalyzer", side_effect=RuntimeError("missing spacy")):
                sync_item_pos_analysis(item, regenerate=True)
        finally:
            nlp_base.analyzer_for_language.cache_clear()

        tokens = item["sentences"][0]["tokens"]
        self.assertEqual(tokens[0]["surface_en"], "today")
        self.assertEqual(tokens[0]["furigana"], "[ˈhɔʏ̯tə]")
        self.assertEqual(tokens[0]["pos"], "ADV")
        self.assertNotEqual(tokens[0].get("upos"), "X")
        self.assertEqual(item["app_payload"]["pos_analysis"][0]["tokens"][0]["surface_en"], "today")

    def test_auto_pos_analysis_preserves_rich_legacy_tokens_when_surfaces_do_not_match(self) -> None:
        nlp_base.analyzer_for_language.cache_clear()
        item = {
            "language": "de",
            "app_payload": {},
            "sentences": [
                {
                    "target": "Morgen Abend.",
                    "tokens": [
                        {
                            "surface": "Heute",
                            "surface_en": "today",
                            "furigana": "[ˈhɔʏ̯tə]",
                            "pos": "ADV",
                        },
                        {
                            "surface": "Abend.",
                            "surface_en": "evening",
                            "furigana": "[ˈaːbn̩t]",
                            "pos": "NOUN",
                        },
                    ],
                }
            ],
        }

        try:
            with mock.patch.object(nlp_base, "SpacyAnalyzer", side_effect=RuntimeError("missing spacy")):
                sync_item_pos_analysis(item, regenerate=True)
        finally:
            nlp_base.analyzer_for_language.cache_clear()

        tokens = item["sentences"][0]["tokens"]
        self.assertEqual(tokens[0]["surface"], "Heute")
        self.assertEqual(tokens[0]["surface_en"], "today")
        self.assertEqual(item["app_payload"]["pos_analysis"][0]["tokens"][0]["surface"], "Heute")

    def test_auto_pos_analysis_rejects_fallback_when_no_real_supported_analyzer_is_installed(self) -> None:
        nlp_base.analyzer_for_language.cache_clear()
        item = {
            "language": "de",
            "app_payload": {},
            "sentences": [{"target": "Heute Abend.", "tokens": []}],
        }

        try:
            with mock.patch.object(nlp_base, "SpacyAnalyzer", side_effect=RuntimeError("missing spacy")):
                with self.assertRaises(nlp_base.RequiredAnalyzerUnavailable):
                    sync_item_pos_analysis(item, regenerate=True)
        finally:
            nlp_base.analyzer_for_language.cache_clear()

    def test_auto_pos_analysis_preflight_rejects_missing_real_analyzer(self) -> None:
        nlp_base.analyzer_for_language.cache_clear()
        try:
            with mock.patch.object(nlp_base, "SpacyAnalyzer", side_effect=RuntimeError("missing spacy")):
                with self.assertRaises(nlp_base.RequiredAnalyzerUnavailable):
                    ensure_real_analyzer_available("de")
        finally:
            nlp_base.analyzer_for_language.cache_clear()

    def test_spacy_languages_use_large_models(self) -> None:
        self.assertEqual(nlp_base.SPACY_MODELS["de"], "de_core_news_lg")
        self.assertEqual(nlp_base.SPACY_MODELS["fr"], "fr_core_news_lg")
        self.assertEqual(nlp_base.SPACY_MODELS["es"], "es_core_news_lg")
        self.assertEqual(nlp_base.SPACY_MODELS["zh"], "zh_core_web_lg")

    def test_auto_pos_analysis_preserves_rich_legacy_tokens_even_when_real_analyzer_exists(self) -> None:
        class FakeAnalyzer(nlp_base.SentenceAnalyzer):
            source = "fake_real_analyzer"

            def analyze(self, language, text, *, existing_sentence=None, entry=None):
                return nlp_base.AnalysisResult(
                    language=language,
                    sentence=text,
                    tokens=[
                        {
                            "surface": "Heute",
                            "lemma": "heute",
                            "pos": "adv",
                            "upos": "ADV",
                            "analyzer": self.source,
                        },
                        {
                            "surface": "Abend",
                            "lemma": "Abend",
                            "pos": "noun",
                            "upos": "NOUN",
                            "analyzer": self.source,
                        },
                        {
                            "surface": ".",
                            "lemma": ".",
                            "pos": "punct",
                            "upos": "PUNCT",
                            "analyzer": self.source,
                        },
                    ],
                    reading="",
                    analyzer=self.source,
                    warnings=[],
                )

        nlp_base.analyzer_for_language.cache_clear()
        item = {
            "language": "de",
            "app_payload": {},
            "sentences": [
                {
                    "target": "Heute Abend.",
                    "tokens": [
                        {
                            "surface": "Heute",
                            "surface_en": "today",
                            "furigana": "[ˈhɔʏ̯tə]",
                            "pos": "ADV",
                        },
                        {
                            "surface": "Abend.",
                            "surface_en": "evening",
                            "furigana": "[ˈaːbn̩t]",
                            "pos": "NOUN",
                        },
                    ],
                }
            ],
        }

        try:
            with mock.patch.object(nlp_base, "analyzer_for_language", return_value=FakeAnalyzer()):
                sync_item_pos_analysis(item, regenerate=True)
        finally:
            nlp_base.analyzer_for_language.cache_clear()

        self.assertEqual(len(item["sentences"][0]["tokens"]), 2)
        self.assertEqual(item["sentences"][0]["tokens"][0]["furigana"], "[ˈhɔʏ̯tə]")
        self.assertEqual(item["app_payload"]["pos_analysis"][0]["tokens"][0]["surface_en"], "today")

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

    def test_auto_pos_analysis_imports_lightweight_source_without_legacy_pos(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_json = tmp / "de_b2_structure.json"
            source_json.write_text(
                json.dumps(
                    [
                        {
                            "entry_id": "Katze",
                            "word": "Katze",
                            "word_label": "Noun [ feminine ]",
                            "word_en": "cat",
                            "word_de": "Katze",
                            "comic_difficulty": 2.0,
                            "jp": ["Die Katze schläft."],
                            "fu": ["/diː ˈkatsə ʃlɛːft/"],
                            "de": ["Die Katze schläft."],
                            "en": ["The cat is sleeping."],
                            "generation": {"schema_version": "vocomipedia-source-1", "no_pos_analysis": True},
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            asset_dir = tmp / "assets"
            asset_dir.mkdir()
            Image.new("RGBA", (64, 64), (220, 220, 220, 255)).save(asset_dir / "comic_Katze_blank.png")
            catalog = tmp / "packs.yaml"
            catalog.write_text(
                """schema_version: vocomipedia-pack-catalog-1
packs:
  de_b2:
    title: German B2
    language: de
    lang_prefix: de
    lang_level: b2
    level: B2
    source_kind: single
    target_sentence_key: jp
    reading_sentence_key: fu
    data_pack_code: de_b2
    review_policy: approved-only
    license_policy: test
""",
                encoding="utf-8",
            )
            out_root = tmp / "data"
            run(
                [
                    sys.executable,
                    str(TOOLS / "import_legacy_pack.py"),
                    "--deck-code",
                    "de_b2",
                    "--catalog",
                    str(catalog),
                    "--input-json",
                    str(source_json),
                    "--asset-dir",
                    str(asset_dir),
                    "--out-root",
                    str(out_root),
                    "--copy-media",
                    "--mark-approved",
                    "--auto-pos-analysis",
                ]
            )
            item_path = next((out_root / "de" / "de_b2" / "items").glob("*.json"))
            item = json.loads(item_path.read_text(encoding="utf-8"))
            self.assertTrue(item["sentences"][0]["tokens"])
            self.assertEqual(item["app_payload"]["pos_analysis"][0]["tokens"], item["sentences"][0]["tokens"])
            self.assertNotIn("pos_analysis", item["app_payload"]["generation"])

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
    def test_release_component_with_combined_data_pack_builds_image_pack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            legacy_json = tmp / "sample_legacy.json"
            shutil.copy2(FIXTURES / "sample_legacy.json", legacy_json)
            asset_dir = tmp / "assets"
            asset_dir.mkdir()
            Image.new("RGBA", (512, 512), (240, 240, 240, 255)).save(asset_dir / "comic_愛__あい__sample_blank.png")
            out_root = tmp / "data"
            catalog = tmp / "packs.yaml"
            catalog.write_text(
                """
schema_version: vocomipedia-pack-catalog-1
packs:
  ko_2:
    title: Korean TOPIK 2
    language: ko
    lang_prefix: ko
    lang_level: "2"
    level: TOPIK 2
    source_kind: single
    target_sentence_key: jp
    reading_sentence_key: fu
    data_pack_code: ko_1-2
""".lstrip(),
                encoding="utf-8",
            )
            run(
                [
                    sys.executable,
                    str(TOOLS / "import_legacy_pack.py"),
                    "--pack-code",
                    "ko_2",
                    "--input-json",
                    str(legacy_json),
                    "--asset-dir",
                    str(asset_dir),
                    "--out-root",
                    str(out_root),
                    "--catalog",
                    str(catalog),
                    "--copy-media",
                    "--mark-approved",
                ]
            )
            release_out = tmp / "release"
            private_key, public_key = write_test_keypair(tmp)
            run(
                [
                    sys.executable,
                    str(TOOLS / "release_pack.py"),
                    "--pack-dir",
                    str(out_root / "ko" / "ko_2"),
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

            metas = sorted((release_out / "packs").glob("ko_2_*.meta.json"))
            self.assertEqual(len(metas), 2)
            by_kind = {}
            for meta_path in metas:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                by_kind[meta["pack_kind"]] = meta
            self.assertEqual(set(by_kind), {"images", "images_preview"})
            self.assertEqual(by_kind["images"]["data_pack_code"], "ko_1-2")
            self.assertEqual(by_kind["images_preview"]["data_pack_code"], "ko_1-2")
            self.assertNotEqual(by_kind["images"]["name"], by_kind["images_preview"]["name"])

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
            n3_dir = data_root / "ja" / "ja_n3"
            (n3_dir / "items").mkdir(parents=True)
            (n3_dir / "media").mkdir()
            (n3_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vocomipedia-pack-1",
                        "pack_code": "ja_n3",
                        "title": "Japanese N3",
                        "language": "ja",
                        "lang_prefix": "ja",
                        "lang_level": "n3",
                        "level": "N3",
                        "target_sentence_key": "jp",
                        "reading_sentence_key": "fu",
                        "data_pack_code": "ja_n5-n3",
                        "items": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            release_out = tmp / "release"
            private_key, public_key = write_test_keypair(tmp)
            run(
                [
                    sys.executable,
                    str(TOOLS / "release_combined_pack.py"),
                    "--data-pack-code",
                    "ja_n5-n3",
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

            db_path = release_out / "staging" / "combined" / "ja_n5-n3" / "combined-assets" / "ja_N5-N3" / "iOS_assets" / "ja_n5-n3.db"
            self.assertTrue(db_path.exists())
            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 2)
            self.assertTrue(list((release_out / "packs").glob("ja_n5-n3_*.vpack")))

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
        gloss_removed = sync_mediawiki.extract_item_json(page.replace("|gloss_de=Fluss\n", ""))
        self.assertNotIn("de", gloss_removed["glosses"])
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
        translation_removed = sync_mediawiki.extract_item_json(page.replace("|translation_de=Ich sehe einen Fluss.\n", ""))
        self.assertNotIn("de", translation_removed["sentences"][0]["translations"])
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
        de_item = json.loads(json.dumps(item))
        de_item["id"] = "de_a2:test"
        de_item["pack_code"] = "de_a2"
        de_item["language"] = "de"
        de_item["entry_id"] = "Ball"
        de_item["headword"] = "Ball"
        de_item["reading"] = "bal"
        de_page = sync_mediawiki.render_item_page(de_item)
        de_headword_pulled = sync_mediawiki.extract_item_json(de_page.replace("|headword_ruby=Ball", "|headword_ruby=Ball yoo"))
        self.assertEqual(de_headword_pulled["headword"], "Ball yoo")
        self.assertEqual(de_headword_pulled["reading"], "bal")

    def test_wiki_visible_language_definitions_are_shared(self) -> None:
        self.assertIs(sync_mediawiki.GLOSS_LANGUAGES, wiki_visible_fields.GLOSS_LANGUAGES)
        rendered_langs = {lang for lang, _label in sync_mediawiki.GLOSS_LANGUAGES}
        self.assertEqual(rendered_langs, apply_pulled_items.VISIBLE_GLOSS_LANGS)
        self.assertEqual(rendered_langs, apply_pulled_items.VISIBLE_SENTENCE_TRANSLATION_LANGS)

        form_page = sync_mediawiki.render_item_form_page()
        sentence_template = sync_mediawiki.render_sentence_template_page()
        for lang in rendered_langs:
            self.assertIn(f"field|{sync_mediawiki.gloss_field_name(lang)}", form_page)
            self.assertIn(f"field|{sync_mediawiki.translation_field_name(lang)}", form_page)
            self.assertIn(f"{{{{{{{sync_mediawiki.translation_field_name(lang)}|}}}}}}", sentence_template)

    def test_legacy_visible_wiki_sentence_tables_merge_non_english_translations(self) -> None:
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
            "sentences": [
                {
                    "target": "川を見る。",
                    "reading": "かわをみる。",
                    "translations": {"en": "I see a river.", "de": "Ich sehe einen Fluss."},
                    "tokens": [],
                }
            ],
            "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
            "review": {"status": "approved"},
            "provenance": {"origin": "test", "license_status": "test"},
            "app_payload": {},
        }
        source = "\n".join(
            [
                '{| class="wikitable vocomipedia-sentence-fields"',
                "! Field",
                "! Value",
                "|-",
                "| Sentence",
                "| 川を見る。",
                "|-",
                "| English",
                "| I see a river.",
                "|-",
                "| German",
                "| Ich sehe den Fluss.",
                "|}",
                f"<!-- {sync_mediawiki.JSON_START}",
                json.dumps(item, ensure_ascii=False, indent=2),
                f"{sync_mediawiki.JSON_END} -->",
            ]
        )
        pulled = sync_mediawiki.extract_item_json(source)
        self.assertEqual(pulled["sentences"][0]["translations"]["de"], "Ich sehe den Fluss.")

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
        self.assertIn("NORMALIZED_COLUMN_BYTES = 1024", indexer)
        self.assertIn('for column in ["vsi_headword_norm", "vsi_reading_norm", "vsi_entry_norm", "vsi_label_norm"]', indexer)
        self.assertIn("ALTER TABLE vocomipedia_search_item MODIFY {column}", indexer)
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

    def test_apply_pulled_merges_visible_non_english_sentence_translations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pack_dir = tmp / "pack"
            pulled_dir = tmp / "pulled"
            (pack_dir / "items").mkdir(parents=True)
            pulled_dir.mkdir()
            item = {
                "schema_version": "vocomipedia-item-2",
                "id": "de_a2:test",
                "pack_code": "de_a2",
                "language": "de",
                "entry_id": "Ball",
                "headword": "Ball",
                "reading": "",
                "label": "",
                "level": "A2",
                "order": 0,
                "part_of_speech": ["Noun"],
                "glosses": {"en": "ball", "de": "Ball"},
                "sentences": [
                    {
                        "target": "Ich suche den Ball im Garten.",
                        "translations": {"en": "I look for the ball.", "de": "Ich suche den Ball im Garten."},
                        "tokens": [],
                    }
                ],
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
                        "pack_code": "de_a2",
                        "title": "German A2",
                        "language": "de",
                        "lang_prefix": "de",
                        "lang_level": "a2",
                        "items": [{"id": item["id"], "entry_id": item["entry_id"], "file": "items/item.json", "order": 0}],
                    }
                ),
                encoding="utf-8",
            )
            pulled = json.loads(json.dumps(item))
            pulled["sentences"][0]["translations"]["de"] = "Ich suche den Ball im Garten.#"
            pulled["review"]["wiki"]["revision_id"] = 6
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
            self.assertEqual(result.returncode, 0, result.stdout)
            applied = json.loads((pack_dir / "items" / "item.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["sentences"][0]["translations"]["de"], "Ich suche den Ball im Garten.#")
            self.assertEqual(applied["app_payload"]["de"][0], "Ich suche den Ball im Garten.#")

    def test_apply_pulled_skips_same_revision_with_only_derived_payload_drift(self) -> None:
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
                "glosses": {"en": "river"},
                "sentences": [{"target": "川です。", "translations": {"en": "It is a river."}, "tokens": []}],
                "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {"word_en": "river", "fu": ["かわです。"]},
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
            pulled["app_payload"] = {"word_en": "old river", "fu": ["old"]}
            pulled["review"]["wiki"]["pulled_utc"] = "2026-01-01T00:00:00Z"
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
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("Applied 0 pulled item(s)", result.stdout)
            applied = json.loads((pack_dir / "items" / "item.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["app_payload"]["word_en"], "river")

    def test_apply_pulled_skips_same_revision_with_only_unicode_normalization_drift(self) -> None:
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
                "entry_id": "みんなで",
                "headword": "みんなで",
                "reading": "みんなで",
                "label": "",
                "level": "N5",
                "order": 0,
                "part_of_speech": ["Adverb"],
                "glosses": {"en": "all together"},
                "sentences": [
                    {
                        "target": "みんなでチーズと言います。",
                        "translations": {"en": "Everyone says cheese.", "hi": "हर कोई, 'चीज़' कहो!"},
                        "tokens": [],
                    }
                ],
                "media": {"image_filename": "", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
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
            pulled["sentences"][0]["translations"]["hi"] = "हर कोई, 'चीज़' कहो!"
            pulled["review"]["wiki"]["pulled_utc"] = "2026-01-01T00:00:00Z"
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
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("Applied 0 pulled item(s)", result.stdout)
            applied = json.loads((pack_dir / "items" / "item.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["sentences"][0]["translations"]["hi"], "हर कोई, 'चीज़' कहो!")

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
                "sentences": [
                    {
                        "target": "川です。",
                        "translations": {"en": "It is a river."},
                        "tokens": [{"surface": "川", "pos": "noun", "difficulty": 1}],
                        "difficulty": 1,
                    }
                ],
                "media": {"image_filename": "comic.png", "license": "Vocomi-created", "review_status": "approved"},
                "review": {"status": "approved", "wiki": {"revision_id": 5}},
                "provenance": {"origin": "test", "ai_generated": True, "license_status": "generated_by_vocomi"},
                "app_payload": {
                    "word_en": "river",
                    "word_de": "Fluss",
                    "en": ["It is a river."],
                    "de": ["Es ist ein Fluss."],
                    "pos_analysis": [
                        {
                            "sentence": "川です。",
                            "tokens": [{"surface": "川", "pos": "noun", "difficulty": 1}],
                            "difficulty_aggregated": 1,
                        }
                    ],
                },
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
            pulled["sentences"][0]["tokens"] = [{"surface": "川", "pos": "verb", "difficulty": 99}]
            pulled["sentences"][0]["difficulty"] = 99
            pulled["sentences"][0]["translations"]["en"] = "This is a river."
            pulled["app_payload"]["pos_analysis"][0]["tokens"] = [{"surface": "川", "pos": "adjective", "difficulty": 99}]
            pulled["app_payload"]["pos_analysis"][0]["difficulty_aggregated"] = 99
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
            self.assertEqual(applied["sentences"][0]["tokens"][0]["pos"], "noun")
            self.assertEqual(applied["sentences"][0]["difficulty"], 1)
            self.assertEqual(applied["sentences"][0]["translations"]["en"], "This is a river.")
            self.assertEqual(applied["app_payload"]["word_en"], "stream")
            self.assertEqual(applied["app_payload"]["en"], ["This is a river."])
            self.assertEqual(applied["app_payload"]["pos_analysis"][0]["tokens"][0]["pos"], "noun")
            self.assertEqual(applied["app_payload"]["pos_analysis"][0]["difficulty_aggregated"], 1)
            self.assertNotIn("word_de", applied["app_payload"])
            self.assertNotIn("de", applied["app_payload"])
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
