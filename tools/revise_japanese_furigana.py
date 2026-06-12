#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backup import create_backup
from common import iter_pack_items, load_pack_manifest, validate_item, write_json
from japanese_ruby import (
    clean_reading,
    is_kanji,
    normalize_japanese_item,
    parse_ruby_text,
    reading_from_ruby_text,
    ruby_from_surface_reading,
    sentence_reading_from_tokens,
    token_reading_kana,
)


SUDACHI_SOURCE_PREFIX = "sudachipy_sudachidict"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def has_kanji(text: str) -> bool:
    return any(is_kanji(ch) for ch in text or "")


def katakana_to_hiragana(text: str) -> str:
    return clean_reading(text)


class SudachiRubyAnalyzer:
    def __init__(self, *, dict_type: str = "core", split_mode: str = "C") -> None:
        try:
            from sudachipy import dictionary, tokenizer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Sudachi revision requires Python packages 'sudachipy' and "
                "'sudachidict_core'. Install with: python3 -m pip install sudachipy sudachidict_core"
            ) from exc

        mode_name = split_mode.upper()
        if mode_name not in {"A", "B", "C"}:
            raise ValueError("--sudachi-mode must be A, B, or C")
        self.dict_type = dict_type
        self.mode_name = mode_name
        self.mode = getattr(tokenizer.Tokenizer.SplitMode, mode_name)
        self.source = f"{SUDACHI_SOURCE_PREFIX}_{dict_type}_{mode_name.lower()}"
        self.tokenizer = dictionary.Dictionary(dict=dict_type).create()

    def analyze(self, text: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for morpheme in self.tokenizer.tokenize(text, self.mode):
            surface = morpheme.surface()
            if not surface:
                continue
            reading = katakana_to_hiragana(morpheme.reading_form() or "")
            if not reading or reading == "*":
                reading = clean_reading(surface)
            out.append(
                {
                    "surface": surface,
                    "furigana": reading,
                    "dictionary_form": morpheme.dictionary_form(),
                    "pos": morpheme.part_of_speech(),
                    "start": morpheme.begin(),
                    "end": morpheme.end(),
                }
            )
        return out


def token_ranges(target: str, tokens: List[Dict[str, Any]]) -> Tuple[List[Tuple[int, int]], bool]:
    ranges: List[Tuple[int, int]] = []
    cursor = 0
    ok = True
    for token in tokens:
        surface = str(token.get("surface") or "")
        if not surface:
            ranges.append((-1, -1))
            ok = False
            continue
        found = target.find(surface, cursor)
        if found < 0:
            ranges.append((-1, -1))
            ok = False
            continue
        ranges.append((found, found + len(surface)))
        cursor = found + len(surface)
    return ranges, ok


def segment_to_ruby_text(surface: str, reading: str) -> str:
    fields = ruby_from_surface_reading(surface, reading)
    return str(fields.get("ruby_text") or surface)


def ruby_text_from_sudachi_segments(surface: str, segments: List[Dict[str, Any]]) -> Optional[str]:
    if not segments:
        return None
    joined = "".join(str(seg.get("surface") or "") for seg in segments)
    if joined != surface:
        return None

    parts: List[str] = []
    for seg in segments:
        seg_surface = str(seg.get("surface") or "")
        reading = clean_reading(str(seg.get("furigana") or ""))
        if reading and has_kanji(seg_surface):
            parts.append(segment_to_ruby_text(seg_surface, reading))
        else:
            parts.append(seg_surface)

    ruby_text = "".join(parts)
    parsed_surface, spans = parse_ruby_text(ruby_text)
    if parsed_surface != surface:
        return None
    if has_kanji(surface) and not spans:
        return None
    return ruby_text


def revise_token_from_sudachi(
    token: Dict[str, Any],
    *,
    segments: List[Dict[str, Any]],
    source: str,
) -> Tuple[Dict[str, Any], str]:
    surface = str(token.get("surface") or "")
    ruby_text = ruby_text_from_sudachi_segments(surface, segments)
    token_source = source
    if ruby_text is None:
        fields = ruby_from_surface_reading(surface, token_reading_kana(token))
        ruby_text = str(fields.get("ruby_text") or surface)
        token_source = "deterministic_fallback"

    parsed_surface, spans = parse_ruby_text(ruby_text)
    if parsed_surface != surface:
        fields = ruby_from_surface_reading(surface, token_reading_kana(token))
        ruby_text = str(fields.get("ruby_text") or surface)
        parsed_surface, spans = parse_ruby_text(ruby_text)
        token_source = "deterministic_fallback"

    out = dict(token)
    out["surface"] = parsed_surface or surface
    out["ruby_text"] = ruby_text
    out["ruby_spans"] = spans
    out["reading_kana"] = reading_from_ruby_text(ruby_text)
    out["furigana"] = out["reading_kana"]
    out["ruby_source"] = token_source
    if token_source == source:
        out["ruby_confidence"] = "high"
    else:
        out["ruby_confidence"] = "needs_review" if has_kanji(surface) else str(out.get("ruby_confidence") or "medium")
    return out, token_source


def revise_sentence(
    sentence: Dict[str, Any],
    *,
    analyzer: SudachiRubyAnalyzer,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    target = str(sentence.get("target") or "")
    old_tokens = [t for t in (sentence.get("tokens") or []) if isinstance(t, dict)]
    ranges, ranges_ok = token_ranges(target, old_tokens)
    segments = analyzer.analyze(target) if target else []
    stats = {"tokens": 0, "sudachi": 0, "fallback": 0}

    new_tokens: List[Dict[str, Any]] = []
    for idx, token in enumerate(old_tokens):
        stats["tokens"] += 1
        if ranges_ok and idx < len(ranges):
            start, end = ranges[idx]
            token_segments = [seg for seg in segments if int(seg["start"]) >= start and int(seg["end"]) <= end]
        else:
            token_segments = []
        new_token, source = revise_token_from_sudachi(token, segments=token_segments, source=analyzer.source)
        stats["sudachi" if source == analyzer.source else "fallback"] += 1
        new_tokens.append(new_token)

    out = dict(sentence)
    out["tokens"] = new_tokens
    out["reading"] = sentence_reading_from_tokens(target, new_tokens, str(sentence.get("reading") or ""))
    out["ruby_source"] = analyzer.source if ranges_ok else "deterministic_fallback"
    return out, stats


def revise_item(
    item: Dict[str, Any],
    *,
    analyzer: SudachiRubyAnalyzer,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    item = normalize_japanese_item(item)
    if item.get("language") != "ja":
        return item, {"items": 0, "sentences": 0, "tokens": 0, "sudachi": 0, "fallback": 0}

    stats = {"items": 1, "sentences": 0, "tokens": 0, "sudachi": 0, "fallback": 0}
    out = copy.deepcopy(item)
    new_sentences: List[Dict[str, Any]] = []
    for sentence in out.get("sentences") or []:
        target = str(sentence.get("target") or "")
        if not target:
            new_sentences.append(sentence)
            continue
        revised, sentence_stats = revise_sentence(sentence, analyzer=analyzer)
        new_sentences.append(revised)
        stats["sentences"] += 1
        for key in ("tokens", "sudachi", "fallback"):
            stats[key] += sentence_stats[key]
    out["sentences"] = new_sentences

    payload = dict(out.get("app_payload") or {})
    pos_analysis = payload.get("pos_analysis")
    if isinstance(pos_analysis, list):
        for idx, sentence in enumerate(new_sentences):
            if idx >= len(pos_analysis) or not isinstance(pos_analysis[idx], dict):
                continue
            pos_analysis[idx]["sentence"] = sentence.get("target", "")
            pos_analysis[idx]["tokens"] = sentence.get("tokens", [])
            if sentence.get("difficulty") is not None:
                pos_analysis[idx]["difficulty_aggregated"] = sentence.get("difficulty")
        payload["pos_analysis"] = pos_analysis
    out["app_payload"] = payload

    provenance = dict(out.get("provenance") or {})
    provenance["ruby_revision"] = {
        "source": analyzer.source,
        "sudachi_dict": analyzer.dict_type,
        "sudachi_mode": analyzer.mode_name,
        "updated_utc": utc_now(),
    }
    out["provenance"] = provenance
    return normalize_japanese_item(out), stats


def find_pack_dirs(root: Path) -> List[Path]:
    if (root / "pack.json").exists():
        return [root]
    return sorted(p.parent for p in root.rglob("pack.json"))


def selected_pack_dirs(root: Path, deck_codes: Optional[List[str]]) -> List[Path]:
    dirs = find_pack_dirs(root)
    if not deck_codes:
        return [p for p in dirs if (load_pack_manifest(p).get("language") == "ja")]
    wanted = {code.lower() for code in deck_codes}
    return [p for p in dirs if str(load_pack_manifest(p).get("pack_code") or "").lower() in wanted]


def revise_pack_dir(
    pack_dir: Path,
    *,
    analyzer: SudachiRubyAnalyzer,
    dry_run: bool,
    limit: int,
) -> Dict[str, int]:
    manifest = load_pack_manifest(pack_dir)
    if manifest.get("language") != "ja":
        print(f"Skipping non-Japanese deck {manifest.get('pack_code')}: {pack_dir}")
        return {"items": 0, "sentences": 0, "tokens": 0, "sudachi": 0, "fallback": 0, "changed": 0}

    stats = {"items": 0, "sentences": 0, "tokens": 0, "sudachi": 0, "fallback": 0, "changed": 0}
    for idx, (item, item_path) in enumerate(iter_pack_items(pack_dir), start=1):
        if limit and idx > limit:
            break
        revised, item_stats = revise_item(item, analyzer=analyzer)
        for key in ("items", "sentences", "tokens", "sudachi", "fallback"):
            stats[key] += item_stats[key]
        if revised != item:
            stats["changed"] += 1
            errors = validate_item(revised)
            if errors:
                raise RuntimeError(f"{item_path}: " + "; ".join(errors))
            if dry_run:
                print(f"DRY RUN: would update {item_path}")
            else:
                write_json(item_path, revised)
    print(
        f"{'Would revise' if dry_run else 'Revised'} {manifest.get('pack_code')}: "
        f"{stats['changed']} item(s), {stats['sentences']} sentence(s), "
        f"{stats['sudachi']} Sudachi token(s), {stats['fallback']} fallback token(s)."
    )
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Revise Japanese Vocomipedia ruby_text using SudachiPy + SudachiDict.")
    ap.add_argument("--root", type=Path, default=Path("data/languages"), help="A deck dir or root containing pack.json files.")
    ap.add_argument("--deck-code", "--deck", dest="deck_codes", action="append", help="Deck code to revise. May be repeated.")
    ap.add_argument("--backup-dir", type=Path, default=Path("backups"))
    ap.add_argument("--sudachi-dict", choices=["small", "core", "full"], default="core")
    ap.add_argument("--sudachi-mode", choices=["A", "B", "C", "a", "b", "c"], default="C")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    pack_dirs = selected_pack_dirs(args.root, args.deck_codes)
    if not pack_dirs:
        raise SystemExit("No Japanese deck directories selected.")

    if not args.dry_run:
        backup = create_backup(paths=pack_dirs, backup_dir=args.backup_dir, label="sudachi-furigana", base_dir=Path.cwd())
        print(f"Backup created before Sudachi furigana revision: {backup}", flush=True)

    analyzer = SudachiRubyAnalyzer(dict_type=args.sudachi_dict, split_mode=args.sudachi_mode)

    total = {"items": 0, "sentences": 0, "tokens": 0, "sudachi": 0, "fallback": 0, "changed": 0}
    for pack_dir in pack_dirs:
        stats = revise_pack_dir(pack_dir, analyzer=analyzer, dry_run=args.dry_run, limit=args.limit)
        for key in total:
            total[key] += stats[key]
    print(
        f"Total: {total['changed']} changed item(s), {total['sentences']} sentence(s), "
        f"{total['sudachi']} Sudachi token(s), {total['fallback']} fallback token(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
