#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from common import load_pack_catalog, load_pack_manifest, repo_root_from_tool
from prepare_release_workspace import canonical_pack_dir


def run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def ref_has_path(root: Path, ref: str, path: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    return run_git(root, ["cat-file", "-e", f"{ref}:{rel}"]).returncode == 0


def changed_item_paths(root: Path, base: str, head: str, deck_dir: Path) -> list[str]:
    items_dir = deck_dir / "items"
    if not ref_has_path(root, base, deck_dir / "pack.json"):
        manifest = load_pack_manifest(deck_dir)
        return sorted(str(ref.get("file") or "") for ref in manifest.get("items", []) if str(ref.get("file") or "").startswith("items/"))

    rel_items = items_dir.relative_to(root).as_posix()
    result = run_git(root, ["diff", "--name-only", "--diff-filter=ACMRT", base, head, "--", rel_items])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git diff failed")
    prefix = deck_dir.relative_to(root).as_posix().rstrip("/") + "/"
    out: list[str] = []
    for raw in result.stdout.splitlines():
        value = raw.strip()
        if not value.endswith(".json") or not value.startswith(prefix):
            continue
        rel = value[len(prefix) :]
        if rel.startswith("items/"):
            out.append(rel)
    return sorted(set(out))


def all_item_paths(deck_dir: Path) -> list[str]:
    manifest = load_pack_manifest(deck_dir)
    return sorted(str(ref.get("file") or "") for ref in manifest.get("items", []) if str(ref.get("file") or "").startswith("items/"))


def load_release_state(path: Path | None) -> dict:
    if path is None or not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid release state JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def base_for_deck(state: dict, code: str, fallback_base: str) -> str:
    deck_git_sha = state.get("deck_git_sha")
    if isinstance(deck_git_sha, dict):
        return str(deck_git_sha.get(code) or "")
    # Backward compatibility with the first release-state.json written before
    # per-deck state existed.
    return str(state.get("git_sha") or fallback_base or "")


def selected_codes(catalog: Dict[str, Dict[str, Any]], decks: list[str]) -> list[str]:
    wanted = {deck.lower() for deck in decks}
    missing = sorted(wanted - set(catalog))
    if missing:
        raise SystemExit("Unknown deck code(s): " + ", ".join(missing))
    return [code for code in sorted(catalog) if code in wanted]


def main() -> int:
    ap = argparse.ArgumentParser(description="Write per-deck changed item lists for delta MediaWiki pushes.")
    ap.add_argument("--decks", nargs="+", required=True)
    ap.add_argument("--base", default="")
    ap.add_argument("--release-state-file", type=Path, help="Use per-deck release base SHAs from a deployed release-state.json.")
    ap.add_argument("--fallback-base", default="", help="Fallback base commit when release-state has no usable SHA.")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--catalog", default=Path("catalog/packs.yaml"), type=Path)
    ap.add_argument("--source-root", default=Path("data/languages"), type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    root = repo_root_from_tool()
    catalog_path = args.catalog if args.catalog.is_absolute() else root / args.catalog
    source_root = args.source_root if args.source_root.is_absolute() else root / args.source_root
    out_dir = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    catalog = load_pack_catalog(catalog_path)
    release_state_path = args.release_state_file if args.release_state_file is None or args.release_state_file.is_absolute() else root / args.release_state_file
    release_state = load_release_state(release_state_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    for code in selected_codes(catalog, args.decks):
        deck_dir = canonical_pack_dir(root, source_root, catalog[code], code)
        base = args.base or base_for_deck(release_state, code, args.fallback_base)
        if base and run_git(root, ["cat-file", "-e", f"{base}^{{commit}}"]).returncode == 0:
            paths = changed_item_paths(root, base, args.head, deck_dir)
            base_note = base
        else:
            paths = all_item_paths(deck_dir)
            base_note = "all-items"
        target = out_dir / f"{code}.txt"
        target.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
        print(f"{code}: {len(paths)} changed item(s) from {base_note} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
