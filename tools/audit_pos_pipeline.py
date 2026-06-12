#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import statistics
from pathlib import Path

from vocomipedia_nlp import analyze_sentence


POS_MAP = {
    "noun": "NOUN",
    "proper noun": "PROPN",
    "propn": "PROPN",
    "pron": "PRON",
    "pronoun": "PRON",
    "verb": "VERB",
    "verb (te-form)": "VERB",
    "verb (past)": "VERB",
    "verb (volitional)": "VERB",
    "adjective": "ADJ",
    "adj": "ADJ",
    "i-adjective": "ADJ",
    "na-adjective": "ADJ",
    "adjective (na)": "ADJ",
    "demonstrative adjective": "ADJ",
    "adverbial adjective": "ADV",
    "adverb": "ADV",
    "adv": "ADV",
    "determiner": "DET",
    "det": "DET",
    "article": "DET",
    "demonstrative": "DET",
    "adp": "ADP",
    "preposition": "ADP",
    "postposition": "ADP",
    "particle": "PART",
    "part": "PART",
    "particle (genitive)": "PART",
    "auxiliary verb": "AUX",
    "auxiliary": "AUX",
    "aux": "AUX",
    "copula": "AUX",
    "cop": "AUX",
    "cconj": "CCONJ",
    "conj": "CCONJ",
    "conjunction": "CCONJ",
    "sconj": "SCONJ",
    "interjection": "INTJ",
    "interj": "INTJ",
    "intj": "INTJ",
    "numeral": "NUM",
    "num": "NUM",
    "punctuation": "PUNCT",
    "punct": "PUNCT",
    "symbol": "SYM",
    "sym": "SYM",
    "x": "X",
    "prt": "PART",
    "ptk": "PART",
}


def coarse_pos(value: object) -> str:
    pos = str(value or "").strip().lower()
    if "+" in pos:
        pos = pos.split("+", 1)[0]
    mapped = POS_MAP.get(pos)
    if mapped:
        return mapped
    upos = pos.upper()
    if upos in {"NOUN", "VERB", "ADJ", "ADV", "PRON", "DET", "ADP", "AUX", "PART", "CCONJ", "SCONJ", "INTJ", "NUM", "PUNCT", "PROPN", "SYM", "X"}:
        return upos
    return "UNK"


def compatible(existing: str, generated: str) -> bool:
    if existing == generated:
        return True
    compatible_pairs = {
        ("PART", "ADP"),
        ("PART", "SCONJ"),
        ("ADP", "PART"),
        ("AUX", "VERB"),
        ("VERB", "AUX"),
        ("DET", "PRON"),
        ("PRON", "DET"),
        ("PROPN", "NOUN"),
        ("CCONJ", "SCONJ"),
        ("SCONJ", "CCONJ"),
    }
    return (existing, generated) in compatible_pairs


def normalize_surface(value: object, language: str) -> str:
    text = str(value or "").strip()
    if language in {"de", "fr", "es"}:
        text = text.lower()
    return text


def clean_surface(value: object) -> str:
    return re.sub(r'[\s、。，．！？!?「」『』（）()"“”]', "", str(value or ""))


def exact_alignment(existing: list[dict], generated: list[dict], language: str) -> tuple[int, int, int]:
    existing_tokens = [token for token in existing if str(token.get("surface") or "").strip()]
    generated_tokens = [token for token in generated if str(token.get("surface") or "").strip()]
    existing_surfaces = [normalize_surface(token.get("surface"), language) for token in existing_tokens]
    generated_surfaces = [normalize_surface(token.get("surface"), language) for token in generated_tokens]
    matcher = difflib.SequenceMatcher(a=existing_surfaces, b=generated_surfaces, autojunk=False)
    matched = compared = pos_matched = 0
    for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        matched += i2 - i1
        for offset, i in enumerate(range(i1, i2)):
            generated_token = generated_tokens[j1 + offset]
            existing_pos = coarse_pos(existing_tokens[i].get("pos"))
            generated_pos = str(generated_token.get("upos") or generated_token.get("pos") or "").upper()
            if existing_pos == "UNK" or not generated_pos:
                continue
            compared += 1
            if compatible(existing_pos, generated_pos):
                pos_matched += 1
    return matched, compared, pos_matched


def merge_alignment(existing: list[dict], generated: list[dict]) -> tuple[int, int, int]:
    generated_tokens = [token for token in generated if clean_surface(token.get("surface"))]
    generated_index = 0
    total = matched = pos_matched = 0
    for existing_token in existing:
        existing_surface = clean_surface(existing_token.get("surface"))
        if not existing_surface:
            continue
        total += 1
        start = generated_index
        accumulator = ""
        used: list[dict] = []
        while generated_index < len(generated_tokens) and len(accumulator) < len(existing_surface):
            token = generated_tokens[generated_index]
            accumulator += clean_surface(token.get("surface"))
            used.append(token)
            generated_index += 1
            if accumulator == existing_surface:
                break
        if accumulator != existing_surface:
            generated_index = start
            continue
        matched += 1
        existing_pos = coarse_pos(existing_token.get("pos"))
        generated_pos = {str(token.get("upos") or token.get("pos") or "").upper() for token in used}
        if any(compatible(existing_pos, pos) for pos in generated_pos):
            pos_matched += 1
    return total, matched, pos_matched


def iter_pack_items(root: Path):
    for manifest_path in sorted(root.glob("*/*/pack.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        language = str(manifest.get("language") or manifest_path.parent.parent.name)
        for meta in manifest.get("items") or []:
            item_path = manifest_path.parent / str(meta.get("file") or "")
            if item_path.exists():
                yield manifest, language, json.loads(item_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare regenerated offline POS/token analysis against existing Vocomipedia deck tokenization.")
    ap.add_argument("--root", default=Path("data/languages"), type=Path)
    ap.add_argument("--examples", default=8, type=int)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    summary: dict[str, collections.Counter] = {}
    examples: dict[str, list[dict]] = collections.defaultdict(list)
    ratios: dict[str, dict[str, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))

    for manifest, language, item in iter_pack_items(args.root):
        stats = summary.setdefault(language, collections.Counter())
        for sentence_index, sentence in enumerate(item.get("sentences") or [], 1):
            existing = sentence.get("tokens") or []
            if not existing:
                continue
            result = analyze_sentence(language, sentence.get("target") or "", existing_sentence=sentence, entry=item)
            generated = result.tokens
            exact_matched, exact_compared, exact_pos = exact_alignment(existing, generated, language)
            merge_total, merge_matched, merge_pos = merge_alignment(existing, generated)
            stats["sentences"] += 1
            stats["existing_tokens"] += len(existing)
            stats["generated_tokens"] += len(generated)
            stats[f"analyzer:{result.analyzer}"] += 1
            stats["exact_surface_matches"] += exact_matched
            stats["exact_pos_compared"] += exact_compared
            stats["exact_pos_matches"] += exact_pos
            stats["merge_surface_matches"] += merge_matched
            stats["merge_pos_matches"] += merge_pos
            ratios[language]["exact_surface"].append(exact_matched / max(1, len(existing)))
            ratios[language]["merge_surface"].append(merge_matched / max(1, merge_total))
            if exact_compared:
                ratios[language]["exact_pos"].append(exact_pos / exact_compared)
            if merge_matched:
                ratios[language]["merge_pos"].append(merge_pos / merge_matched)
            if (merge_matched / max(1, merge_total) < 0.85 or (merge_matched and merge_pos / merge_matched < 0.75)) and len(examples[language]) < args.examples:
                examples[language].append(
                    {
                        "pack": manifest.get("pack_code"),
                        "item": item.get("id"),
                        "sentence_index": sentence_index,
                        "sentence": sentence.get("target"),
                        "analyzer": result.analyzer,
                        "existing": [(token.get("surface"), token.get("pos")) for token in existing[:20]],
                        "generated": [(token.get("surface"), token.get("upos") or token.get("pos")) for token in generated[:30]],
                        "merge_surface": round(merge_matched / max(1, merge_total), 3),
                        "merge_pos": round(merge_pos / max(1, merge_matched), 3) if merge_matched else None,
                    }
                )

    out = {"summary": {}, "examples": examples}
    for language, stats in sorted(summary.items()):
        row = dict(stats)
        for key, values in ratios[language].items():
            row[f"median_{key}_pct"] = round(statistics.median(values) * 100, 1) if values else 0
        out["summary"][language] = row

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for language, stats in out["summary"].items():
            analyzers = {key: value for key, value in stats.items() if key.startswith("analyzer:")}
            print(
                language,
                analyzers,
                "median_merge_surface",
                stats.get("median_merge_surface_pct", 0),
                "median_merge_pos",
                stats.get("median_merge_pos_pct", 0),
                "merge_surface_total_pct",
                round(stats["merge_surface_matches"] / max(1, stats["existing_tokens"]) * 100, 1),
                "merge_pos_total_pct",
                round(stats["merge_pos_matches"] / max(1, stats["merge_surface_matches"]) * 100, 1),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
