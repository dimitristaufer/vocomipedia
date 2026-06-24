#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Dict, List

from common import iter_pack_items, load_pack_catalog, repo_root_from_tool, write_json
from japanese_ruby import is_kanji, normalize_japanese_item, reading_from_ruby_text, token_reading_kana


def source_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def pack_dir_for(out_root: Path, cfg: Dict[str, Any], code: str) -> Path:
    lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0])
    return out_root / lang / code


def find_pack_dirs(root: Path) -> List[Path]:
    if (root / "pack.json").exists():
        return [root]
    return sorted(path.parent for path in root.rglob("pack.json"))


def selected_pack_dirs(root: Path, catalog_path: Path, decks: List[str] | None) -> List[Path]:
    if not decks:
        return [path for path in find_pack_dirs(root) if path.parent.name == "ja"]

    catalog = load_pack_catalog(catalog_path)
    dirs: List[Path] = []
    for code in decks:
        cfg = catalog.get(code.lower())
        if not cfg:
            raise SystemExit(f"unknown deck code: {code}")
        if str(cfg.get("language") or cfg.get("lang_prefix") or "").lower() != "ja":
            continue
        pack_dir = pack_dir_for(root, cfg, code.lower())
        if (pack_dir / "pack.json").exists():
            dirs.append(pack_dir)
    return dirs


def safe_reading_replacement(old: str, new: str) -> str | None:
    old = str(old or "")
    new = str(new or "")
    if "きごう" not in old:
        return None
    if not new or new == old or "きごう" in new:
        return None
    if any(is_kanji(ch) for ch in new):
        return None
    return new


def needs_token_ruby_repair(token: Dict[str, Any], normalized: Dict[str, Any]) -> bool:
    ruby_text = token.get("ruby_text")
    if not isinstance(ruby_text, str) or not ruby_text.strip():
        return False
    old_reading = reading_from_ruby_text(ruby_text.strip())
    explicit_reading = token_reading_kana(token)
    if not old_reading or not explicit_reading:
        return False
    if not any(is_kanji(ch) for ch in old_reading):
        return False
    if any(is_kanji(ch) for ch in explicit_reading):
        return False
    return any(token.get(key) != normalized.get(key) for key in ("reading_kana", "ruby_text", "ruby_spans", "ruby_confidence", "furigana"))


def repair_token_ruby_fields(token: Dict[str, Any], normalized: Dict[str, Any]) -> bool:
    if not needs_token_ruby_repair(token, normalized):
        return False
    for key in ("reading_kana", "ruby_text", "ruby_spans", "ruby_confidence", "furigana"):
        if key in normalized:
            token[key] = copy.deepcopy(normalized[key])
    return True


def normalize_pack(pack_dir: Path, dry_run: bool) -> Dict[str, int]:
    stats = {"items": 0, "changed": 0, "sentences": 0, "tokens": 0, "payload_tokens": 0, "skipped": 0}
    for item, item_path in iter_pack_items(pack_dir):
        stats["items"] += 1
        normalized = normalize_japanese_item(copy.deepcopy(item))
        changed = False
        for sentence_idx, (sentence, normalized_sentence) in enumerate(zip(item.get("sentences") or [], normalized.get("sentences") or [])):
            if not isinstance(sentence, dict) or not isinstance(normalized_sentence, dict):
                continue
            for token, normalized_token in zip(sentence.get("tokens") or [], normalized_sentence.get("tokens") or []):
                if not isinstance(token, dict) or not isinstance(normalized_token, dict):
                    continue
                if repair_token_ruby_fields(token, normalized_token):
                    changed = True
                    stats["tokens"] += 1
            payload = item.get("app_payload") if isinstance(item.get("app_payload"), dict) else {}
            pos_analysis = payload.get("pos_analysis") if isinstance(payload.get("pos_analysis"), list) else []
            if sentence_idx < len(pos_analysis) and isinstance(pos_analysis[sentence_idx], dict):
                payload_tokens = pos_analysis[sentence_idx].get("tokens")
                normalized_payload = (normalized.get("app_payload") or {}).get("pos_analysis") or []
                normalized_payload_tokens = []
                if sentence_idx < len(normalized_payload) and isinstance(normalized_payload[sentence_idx], dict):
                    normalized_payload_tokens = normalized_payload[sentence_idx].get("tokens") or []
                if isinstance(payload_tokens, list):
                    for token, normalized_token in zip(payload_tokens, normalized_payload_tokens):
                        if not isinstance(token, dict) or not isinstance(normalized_token, dict):
                            continue
                        if repair_token_ruby_fields(token, normalized_token):
                            changed = True
                            stats["payload_tokens"] += 1
            replacement = safe_reading_replacement(sentence.get("reading", ""), normalized_sentence.get("reading", ""))
            if replacement is None:
                if "きごう" in str(sentence.get("reading") or "") and sentence.get("reading") != normalized_sentence.get("reading"):
                    stats["skipped"] += 1
                continue
            sentence["reading"] = replacement
            changed = True
            stats["sentences"] += 1
        if changed:
            stats["changed"] += 1
            if not dry_run:
                write_json(item_path, item)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove stale Japanese sentence-reading artifacts produced by blank space tokens.")
    ap.add_argument("--root", default=Path("data/languages"), type=Path)
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--decks", "--packs", dest="decks", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    data_root = source_path(root, str(args.root)).resolve()
    catalog_path = source_path(root, str(args.catalog)).resolve()
    pack_dirs = selected_pack_dirs(data_root, catalog_path, args.decks)
    if not pack_dirs:
        print("ERROR: no Japanese pack directories selected")
        return 2

    total = {"items": 0, "changed": 0, "sentences": 0, "tokens": 0, "payload_tokens": 0, "skipped": 0}
    for pack_dir in pack_dirs:
        stats = normalize_pack(pack_dir, args.dry_run)
        for key, value in stats.items():
            total[key] += value
        print(
            f"{pack_dir}: changed {stats['changed']} / {stats['items']} item(s), "
            f"updated {stats['sentences']} sentence reading(s), repaired {stats['tokens']} token(s), "
            f"repaired {stats['payload_tokens']} payload token(s), skipped {stats['skipped']} candidate(s)"
        )

    action = "Would normalize" if args.dry_run else "Normalized"
    print(
        f"{action} {total['changed']} / {total['items']} item(s); "
        f"updated {total['sentences']} sentence reading(s), repaired {total['tokens']} token(s), "
        f"repaired {total['payload_tokens']} payload token(s), skipped {total['skipped']} candidate(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
