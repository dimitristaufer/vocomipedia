#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import iter_pack_items, load_pack_catalog, read_json, repo_root_from_tool, write_json
from vocomipedia_nlp import sync_item_pos_analysis


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


def selected_pack_dirs(root: Path, catalog_path: Path, decks: List[str] | None, langs: List[str] | None) -> List[Path]:
    if not decks and not langs:
        return find_pack_dirs(root)

    catalog = load_pack_catalog(catalog_path)
    wanted_decks = {deck.lower() for deck in decks or []}
    wanted_langs = {lang.lower() for lang in langs or []}
    dirs: List[Path] = []
    for code, cfg in sorted(catalog.items()):
        lang = str(cfg.get("language") or cfg.get("lang_prefix") or code.split("_", 1)[0]).lower()
        if wanted_decks and code.lower() not in wanted_decks:
            continue
        if wanted_langs and lang not in wanted_langs:
            continue
        pack_dir = pack_dir_for(root, cfg, code)
        if (pack_dir / "pack.json").exists():
            dirs.append(pack_dir)
    return dirs


def non_token_projection(item: Dict[str, Any]) -> Dict[str, Any]:
    projected = copy.deepcopy(item)
    for sentence in projected.get("sentences") or []:
        if isinstance(sentence, dict):
            sentence.pop("tokens", None)
    app_payload = projected.get("app_payload")
    if isinstance(app_payload, dict):
        app_payload.pop("pos_analysis", None)
    return projected


def token_stats(item: Dict[str, Any]) -> tuple[int, int, int]:
    blank = 0
    true_flags = 0
    false_flags = 0
    for sentence in item.get("sentences") or []:
        if not isinstance(sentence, dict):
            continue
        tokens = sentence.get("tokens")
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if not isinstance(token, dict):
                continue
            if not str(token.get("surface") or "").strip():
                blank += 1
            if token.get("is_main_word") is True:
                true_flags += 1
            elif token.get("is_main_word") is False:
                false_flags += 1
    return blank, true_flags, false_flags


def normalize_pack(pack_dir: Path, dry_run: bool) -> Dict[str, int]:
    stats = {
        "items": 0,
        "changed": 0,
        "blank_tokens_removed": 0,
        "main_true_added": 0,
        "main_false_removed": 0,
    }
    for item, item_path in iter_pack_items(pack_dir):
        stats["items"] += 1
        before = copy.deepcopy(item)
        before_blank, before_true, before_false = token_stats(before)

        after = sync_item_pos_analysis(copy.deepcopy(item), regenerate=False)
        if non_token_projection(before) != non_token_projection(after):
            raise RuntimeError(f"{item_path}: normalization would change non-token fields")
        if before == after:
            continue

        after_blank, after_true, after_false = token_stats(after)
        stats["changed"] += 1
        stats["blank_tokens_removed"] += max(0, before_blank - after_blank)
        stats["main_true_added"] += max(0, after_true - before_true)
        stats["main_false_removed"] += max(0, before_false - after_false)
        if not dry_run:
            write_json(item_path, after)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Normalize existing canonical token/POS data without reimporting source decks or regenerating analyzers."
    )
    ap.add_argument("--root", default=Path("data/languages"), type=Path)
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--decks", "--packs", dest="decks", nargs="+")
    ap.add_argument("--langs", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root_from_tool()
    data_root = source_path(root, str(args.root)).resolve()
    catalog_path = source_path(root, str(args.catalog)).resolve()
    pack_dirs = selected_pack_dirs(data_root, catalog_path, args.decks, args.langs)
    if not pack_dirs:
        print("ERROR: no pack directories selected")
        return 2

    total = {
        "items": 0,
        "changed": 0,
        "blank_tokens_removed": 0,
        "main_true_added": 0,
        "main_false_removed": 0,
    }
    for pack_dir in pack_dirs:
        stats = normalize_pack(pack_dir, args.dry_run)
        for key, value in stats.items():
            total[key] += value
        print(
            f"{pack_dir}: changed {stats['changed']} / {stats['items']} item(s), "
            f"removed {stats['blank_tokens_removed']} blank token(s), "
            f"added {stats['main_true_added']} main-word flag(s), "
            f"removed {stats['main_false_removed']} false flag(s)"
        )

    action = "Would normalize" if args.dry_run else "Normalized"
    print(
        f"{action} {total['changed']} / {total['items']} item(s); "
        f"removed {total['blank_tokens_removed']} blank token(s), "
        f"added {total['main_true_added']} main-word flag(s), "
        f"removed {total['main_false_removed']} false flag(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
