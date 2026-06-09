#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

ITEM_SCHEMA_VERSION = "vocomipedia-item-1"
PACK_SCHEMA_VERSION = "vocomipedia-pack-1"

REVIEW_STATUSES = {"draft", "needs_review", "approved", "deprecated"}
NON_TRANSLATION_LIST_KEYS = {
    "jp",
    "fu",
    "png_files",
    "palette_png_files",
    "pos_analysis",
    "jp_audio",
}


class VocomipediaError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def repo_root_from_tool() -> Path:
    return Path(__file__).resolve().parents[2]


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "catalog" / "packs.yaml"


def load_pack_catalog(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    catalog_path = path or default_catalog_path()
    obj = read_yaml(catalog_path)
    packs = obj.get("packs", {}) if isinstance(obj, dict) else {}
    if not isinstance(packs, dict):
        raise VocomipediaError(f"Invalid pack catalog: {catalog_path}")
    return packs


def pack_config(pack_code: str, catalog_path: Optional[Path] = None) -> Dict[str, Any]:
    packs = load_pack_catalog(catalog_path)
    key = pack_code.lower()
    if key not in packs:
        raise VocomipediaError(f"Unknown pack_code {pack_code!r}; add it to vocomipedia/catalog/packs.yaml")
    cfg = dict(packs[key])
    cfg["pack_code"] = key
    cfg.setdefault("target_sentence_key", "jp")
    cfg.setdefault("reading_sentence_key", "fu")
    cfg.setdefault("language", cfg.get("lang_prefix", key.split("_", 1)[0]))
    cfg.setdefault("title", key)
    cfg.setdefault("level", str(cfg.get("lang_level", "")))
    return cfg


def stable_item_id(pack_code: str, entry_id: str) -> str:
    digest = hashlib.sha1(f"{pack_code}\0{entry_id}".encode("utf-8")).hexdigest()[:16]
    return f"{pack_code}:{digest}"


def safe_filename(item_id: str, headword: str = "") -> str:
    digest = item_id.split(":")[-1] if ":" in item_id else hashlib.sha1(item_id.encode("utf-8")).hexdigest()[:16]
    hint = re.sub(r"[^A-Za-z0-9._-]+", "-", headword).strip("-._")[:40]
    return f"{hint + '-' if hint else ''}{digest}.json"


def entry_identifier(entry: Dict[str, Any]) -> str:
    value = entry.get("entry_id") or entry.get("word")
    if not isinstance(value, str) or not value:
        raise VocomipediaError(f"Entry without valid entry_id or word: {entry!r}")
    return value


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    return []


def _translation_keys(entry: Dict[str, Any], target_key: str, reading_key: str) -> List[str]:
    out: List[str] = []
    for key, value in entry.items():
        if key in NON_TRANSLATION_LIST_KEYS or key in {target_key, reading_key}:
            continue
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            out.append(key)
    return out


def _word_glosses(entry: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in entry.items():
        if not key.startswith("word_") or not isinstance(value, str):
            continue
        lang = key[5:]
        if lang in {"reading", "label", "romanized", "hanja", "pinyin", "POS"}:
            continue
        out[lang] = value
    return out


def _parts_of_speech(entry: Dict[str, Any]) -> List[str]:
    raw = entry.get("parts_of_speech") or entry.get("word_POS")
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x)]
    if isinstance(raw, str) and raw:
        return [part.strip() for part in re.split(r"[,;/]", raw) if part.strip()]
    return []


def legacy_to_canonical(
    entry: Dict[str, Any],
    *,
    pack: Dict[str, Any],
    order: int,
    media_root: Optional[Path] = None,
) -> Dict[str, Any]:
    pack_code = pack["pack_code"]
    target_key = pack.get("target_sentence_key", "jp")
    reading_key = pack.get("reading_sentence_key", "fu")
    legacy_id = entry_identifier(entry)
    item_id = stable_item_id(pack_code, legacy_id)

    targets = _string_list(entry.get(target_key))
    readings = _string_list(entry.get(reading_key))
    pos_analysis = entry.get("pos_analysis") if isinstance(entry.get("pos_analysis"), list) else []
    translation_keys = _translation_keys(entry, target_key, reading_key)

    sentence_count = max([len(targets), len(readings), len(pos_analysis), 1])
    for key in translation_keys:
        sentence_count = max(sentence_count, len(_string_list(entry.get(key))))

    sentences: List[Dict[str, Any]] = []
    for idx in range(sentence_count):
        translations: Dict[str, str] = {}
        for key in translation_keys:
            arr = _string_list(entry.get(key))
            if idx < len(arr):
                translations[key] = arr[idx]

        pos_obj = pos_analysis[idx] if idx < len(pos_analysis) and isinstance(pos_analysis[idx], dict) else {}
        sentences.append(
            {
                "target": targets[idx] if idx < len(targets) else str(pos_obj.get("sentence", "")),
                "reading": readings[idx] if idx < len(readings) else "",
                "translations": translations,
                "tokens": pos_obj.get("tokens", []) if isinstance(pos_obj.get("tokens"), list) else [],
                "difficulty": pos_obj.get("difficulty_aggregated"),
            }
        )

    image_filename = f"comic_{legacy_id}_blank.png"
    media_status = "missing"
    if media_root and (media_root / image_filename).exists():
        media_status = "present"

    return {
        "schema_version": ITEM_SCHEMA_VERSION,
        "id": item_id,
        "pack_code": pack_code,
        "language": pack.get("language", pack.get("lang_prefix", "")),
        "entry_id": legacy_id,
        "headword": str(entry.get("word", legacy_id)),
        "reading": str(entry.get("word_reading", "")),
        "label": str(entry.get("word_label", "")),
        "level": str(pack.get("level", pack.get("lang_level", ""))),
        "order": order,
        "part_of_speech": _parts_of_speech(entry),
        "glosses": _word_glosses(entry),
        "sentences": sentences,
        "media": {
            "image_filename": image_filename,
            "source_image_filename": image_filename,
            "license": "needs-audit",
            "review_status": media_status,
            "attribution": None,
            "source_url": None,
        },
        "review": {
            "status": "needs_review",
            "language_reviewers": [],
            "content_reviewers": [],
            "last_reviewed_utc": None,
        },
        "provenance": {
            "origin": "legacy_import",
            "ai_generated": True,
            "license_status": "needs-audit",
            "source_urls": [],
        },
        "app_payload": dict(entry),
    }


def canonical_to_legacy(item: Dict[str, Any], *, pack: Dict[str, Any]) -> Dict[str, Any]:
    target_key = pack.get("target_sentence_key", "jp")
    reading_key = pack.get("reading_sentence_key", "fu")
    payload = dict(item.get("app_payload") or {})

    payload["entry_id"] = item["entry_id"]
    payload["word"] = item["headword"]
    if item.get("reading") is not None:
        payload["word_reading"] = item.get("reading", "")
    if item.get("label"):
        payload["word_label"] = item["label"]

    for lang, gloss in (item.get("glosses") or {}).items():
        payload[f"word_{lang}"] = gloss

    sentences = item.get("sentences") or []
    payload[target_key] = [s.get("target", "") for s in sentences]
    payload[reading_key] = [s.get("reading", "") for s in sentences]

    translation_keys: List[str] = sorted(
        {
            key
            for s in sentences
            for key in (s.get("translations") or {}).keys()
        }
    )
    for key in translation_keys:
        payload[key] = [(s.get("translations") or {}).get(key, "") for s in sentences]

    pos_analysis = []
    for s in sentences:
        pos_analysis.append(
            {
                "sentence": s.get("target", ""),
                "tokens": s.get("tokens", []),
                "difficulty_aggregated": s.get("difficulty"),
            }
        )
    payload["pos_analysis"] = pos_analysis

    if item.get("part_of_speech") and "word_POS" not in payload:
        payload["word_POS"] = ", ".join(item["part_of_speech"])

    return payload


def validate_item(item: Dict[str, Any], *, strict_media_root: Optional[Path] = None) -> List[str]:
    errors: List[str] = []
    for key in ("schema_version", "id", "pack_code", "language", "entry_id", "headword", "sentences", "media", "review", "provenance", "app_payload"):
        if key not in item:
            errors.append(f"missing required key: {key}")
    if errors:
        return errors

    if item["schema_version"] != ITEM_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {item['schema_version']!r}")
    if not isinstance(item["sentences"], list) or not item["sentences"]:
        errors.append("sentences must be a non-empty list")
    else:
        for idx, sentence in enumerate(item["sentences"]):
            if not isinstance(sentence, dict):
                errors.append(f"sentences[{idx}] must be an object")
                continue
            if not sentence.get("target"):
                errors.append(f"sentences[{idx}].target is required")
            translations = sentence.get("translations")
            if not isinstance(translations, dict):
                errors.append(f"sentences[{idx}].translations must be an object")
    status = (item.get("review") or {}).get("status")
    if status not in REVIEW_STATUSES:
        errors.append(f"invalid review.status: {status!r}")

    media = item.get("media") or {}
    image_filename = media.get("image_filename")
    if strict_media_root and image_filename:
        if not (strict_media_root / image_filename).exists():
            errors.append(f"missing media file: {image_filename}")

    return errors


def load_pack_manifest(pack_dir: Path) -> Dict[str, Any]:
    manifest = read_json(pack_dir / "pack.json")
    if manifest.get("schema_version") != PACK_SCHEMA_VERSION:
        raise VocomipediaError(f"Unsupported pack manifest: {pack_dir / 'pack.json'}")
    return manifest


def iter_pack_items(pack_dir: Path, approved_only: bool = False) -> Iterable[Tuple[Dict[str, Any], Path]]:
    manifest = load_pack_manifest(pack_dir)
    for ref in sorted(manifest.get("items", []), key=lambda x: int(x.get("order", 0))):
        item_path = pack_dir / ref["file"]
        item = read_json(item_path)
        if approved_only and (item.get("review") or {}).get("status") != "approved":
            continue
        yield item, item_path


def copy_item_media(item: Dict[str, Any], source_dirs: List[Path], dest_dir: Path) -> Optional[Path]:
    media = item.get("media") or {}
    name = media.get("source_image_filename") or media.get("image_filename")
    if not name:
        return None
    for src_dir in source_dirs:
        src = src_dir / name
        if src.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / name
            shutil.copy2(src, dest)
            return dest
    return None

