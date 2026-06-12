#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import json
from pathlib import Path
from typing import Dict, List

from backup import create_backup
from common import load_pack_manifest, read_json, safe_filename, validate_item, write_json

VISIBLE_GLOSS_LANGS = {
    "en",
    "es",
    "fr",
    "de",
    "it",
    "ko",
    "zh-Hans",
    "yue",
    "ru",
    "pt",
    "he",
    "tr",
    "vi",
    "ar",
    "nl",
    "uk",
    "hu",
    "hi",
    "pl",
    "el",
    "nb",
    "id",
    "sv",
    "ro",
    "cs",
    "da",
    "fi",
    "ja",
}


def wiki_revision_id(item: Dict) -> int | None:
    wiki = ((item.get("review") or {}).get("wiki") or {})
    value = wiki.get("revision_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def comparable_item(item: Dict) -> Dict:
    out = copy.deepcopy(item)
    wiki = ((out.get("review") or {}).get("wiki") or {})
    wiki.pop("pulled_utc", None)
    wiki.pop("applied_utc", None)
    wiki.pop("applied_by", None)
    return out


def item_diff(before: Dict | None, after: Dict) -> str:
    before_text = "" if before is None else json.dumps(before, ensure_ascii=False, indent=2, sort_keys=True)
    after_text = json.dumps(after, ensure_ascii=False, indent=2, sort_keys=True)
    return "\n".join(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="current",
            tofile="pulled",
            lineterm="",
        )
    )


def mark_applied(item: Dict, applied_by: str) -> Dict:
    updated = copy.deepcopy(item)
    review = updated.setdefault("review", {})
    wiki = review.setdefault("wiki", {})
    wiki["applied_utc"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    wiki["applied_by"] = applied_by
    return updated


def merge_review_metadata(current: Dict, pulled: Dict) -> Dict:
    current_review = copy.deepcopy(current.get("review") or {})
    pulled_review = pulled.get("review") or {}
    for key in ("status", "last_reviewed_utc", "approval_source"):
        if key in pulled_review:
            current_review[key] = pulled_review[key]
    if "wiki" in pulled_review:
        current_review["wiki"] = copy.deepcopy(pulled_review["wiki"])
    reviewers = current_review.setdefault("content_reviewers", [])
    if not isinstance(reviewers, list):
        reviewers = []
    for reviewer in pulled_review.get("content_reviewers") or []:
        if reviewer not in reviewers:
            reviewers.append(reviewer)
    current_review["content_reviewers"] = reviewers
    current_proposals = copy.deepcopy(current_review.get("sentence_proposals") or [])
    if not isinstance(current_proposals, list):
        current_proposals = []
    pulled_proposals = pulled_review.get("sentence_proposals") or []
    seen = {proposal.get("id") for proposal in current_proposals if isinstance(proposal, dict)}
    for proposal in pulled_proposals:
        if not isinstance(proposal, dict):
            continue
        proposal_id = proposal.get("id")
        if proposal_id in seen:
            for idx, existing in enumerate(current_proposals):
                if isinstance(existing, dict) and existing.get("id") == proposal_id:
                    current_proposals[idx] = copy.deepcopy(proposal)
                    break
        else:
            current_proposals.append(copy.deepcopy(proposal))
            seen.add(proposal_id)
    if current_proposals or "sentence_proposals" in current_review or "sentence_proposals" in pulled_review:
        current_review["sentence_proposals"] = current_proposals
    return current_review


def merge_visible_fields(current: Dict, pulled: Dict) -> Dict:
    updated = copy.deepcopy(current)
    for key in ("headword", "reading"):
        if key in pulled and isinstance(pulled.get(key), str):
            updated[key] = pulled[key]

    pulled_glosses = pulled.get("glosses") or {}
    current_glosses = updated.setdefault("glosses", {})
    if isinstance(pulled_glosses, dict) and isinstance(current_glosses, dict):
        for lang in VISIBLE_GLOSS_LANGS:
            value = pulled_glosses.get(lang)
            if isinstance(value, str) and value:
                current_glosses[lang] = value
            elif lang in current_glosses:
                current_glosses.pop(lang)

    pulled_sentences = pulled.get("sentences") or []
    current_sentences = updated.setdefault("sentences", [])
    for idx, pulled_sentence in enumerate(pulled_sentences):
        if idx >= len(current_sentences) or not isinstance(current_sentences[idx], dict):
            current_sentences.append(copy.deepcopy(pulled_sentence))
            continue
        current_sentence = current_sentences[idx]
        for key in ("reading", "tokens", "difficulty"):
            if key in pulled_sentence:
                current_sentence[key] = copy.deepcopy(pulled_sentence[key])
        pulled_translations = pulled_sentence.get("translations") or {}
        current_translations = current_sentence.setdefault("translations", {})
        if "en" in pulled_translations:
            current_translations["en"] = pulled_translations["en"]

    pulled_payload = pulled.get("app_payload") or {}
    current_payload = updated.setdefault("app_payload", {})
    pulled_pos = pulled_payload.get("pos_analysis")
    current_pos = current_payload.get("pos_analysis")
    if isinstance(pulled_pos, list) and isinstance(current_pos, list):
        for idx, pulled_pos_item in enumerate(pulled_pos):
            if idx < len(current_pos) and isinstance(current_pos[idx], dict) and isinstance(pulled_pos_item, dict):
                for key in ("tokens", "difficulty_aggregated"):
                    if key in pulled_pos_item:
                        current_pos[idx][key] = copy.deepcopy(pulled_pos_item[key])
                current_pos[idx]["sentence"] = current_sentences[idx].get("target", "")

    updated["review"] = merge_review_metadata(current, pulled)
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply pulled MediaWiki canonical item JSON files into an existing Vocomipedia deck.")
    ap.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", metavar="DECK_DIR", required=True, type=Path)
    ap.add_argument("--pulled-dir", required=True, type=Path)
    ap.add_argument("--backup-dir", default=Path("backups"), type=Path)
    ap.add_argument("--diff-report", default=None, type=Path, help="Write a unified JSON diff report for applied changes.")
    ap.add_argument("--applied-by", default="vocomipedia-apply-pulled")
    ap.add_argument("--force-stale", action="store_true", help="Allow applying a pulled revision older than the current recorded wiki revision.")
    ap.add_argument("--trust-hidden-json", action="store_true", help="Apply the full pulled hidden JSON for existing items instead of only visible editable fields.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = load_pack_manifest(args.pack_dir)
    refs: List[Dict] = list(manifest.get("items", []))
    by_id = {ref["id"]: ref for ref in refs}
    existing_orders = [int(ref.get("order", 0)) for ref in refs]
    next_order = (max(existing_orders) + 1) if existing_orders else 0

    pulled_files = sorted(args.pulled_dir.glob("*.json"))
    if not pulled_files:
        raise SystemExit(f"No pulled JSON files found in {args.pulled_dir}")

    backup = create_backup(paths=[args.pack_dir], backup_dir=args.backup_dir, label="apply-pulled", base_dir=Path.cwd())
    print(f"Backup created before applying pulled items: {backup}", flush=True)

    changed = 0
    skipped = 0
    diff_blocks: List[str] = []
    for pulled in pulled_files:
        item = read_json(pulled)
        errors = validate_item(item)
        if errors:
            raise SystemExit(f"{pulled}: " + "; ".join(errors))
        if item.get("pack_code") != manifest.get("pack_code"):
            raise SystemExit(f"{pulled}: pack_code {item.get('pack_code')} does not match {manifest.get('pack_code')}")

        ref = by_id.get(item["id"])
        current_item = None
        if ref is None:
            rel = f"items/{safe_filename(item['id'], item.get('headword', ''))}"
            ref = {"id": item["id"], "entry_id": item["entry_id"], "file": rel, "order": next_order}
            next_order += 1
            refs.append(ref)
            by_id[item["id"]] = ref
        else:
            current_path = args.pack_dir / ref["file"]
            if current_path.exists():
                current_item = read_json(current_path)
            current_revision = wiki_revision_id(current_item or {})
            pulled_revision = wiki_revision_id(item)
            if current_revision is not None and pulled_revision is not None and pulled_revision <= current_revision:
                if comparable_item(current_item or {}) == comparable_item(item):
                    skipped += 1
                    continue
                if not args.force_stale:
                    raise SystemExit(
                        f"{pulled}: pulled wiki revision {pulled_revision} is not newer than "
                        f"current recorded revision {current_revision}. Use --force-stale to override."
                    )
            ref["entry_id"] = item["entry_id"]
            if not args.trust_hidden_json and current_item is not None:
                item = merge_visible_fields(current_item, item)

        item = mark_applied(item, args.applied_by)
        errors = validate_item(item)
        if errors:
            raise SystemExit(f"{pulled} after merge: " + "; ".join(errors))
        diff = item_diff(current_item, item)
        if diff:
            diff_blocks.append(f"## {item['id']} ({item.get('headword', '')})\n{diff}\n")
        if args.dry_run:
            print(f"DRY RUN: would write {args.pack_dir / ref['file']}")
        else:
            write_json(args.pack_dir / ref["file"], item)
        changed += 1

    refs.sort(key=lambda r: int(r.get("order", 0)))
    manifest["items"] = refs
    manifest.setdefault("mediawiki_sync", {})["last_apply"] = {
        "changed": changed,
        "skipped": skipped,
        "applied_by": args.applied_by,
    }
    if args.dry_run:
        print(f"DRY RUN: would update {args.pack_dir / 'pack.json'}")
    else:
        write_json(args.pack_dir / "pack.json", manifest)
    if args.diff_report and diff_blocks:
        args.diff_report.parent.mkdir(parents=True, exist_ok=True)
        args.diff_report.write_text("\n".join(diff_blocks), encoding="utf-8")
        print(f"Wrote diff report to {args.diff_report}")
    print(f"Applied {changed} pulled item(s) into {args.pack_dir}; skipped {skipped} unchanged/stale item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
