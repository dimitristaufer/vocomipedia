#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from backup import create_backup
from common import iter_pack_items, validate_item, write_json
from vocomipedia_nlp import analyze_sentence, sync_item_pos_analysis


ACTIVE_STATUSES = {"pending_review", "needs_analysis", "needs_sentence_regeneration"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def item_diff(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    before_text = json.dumps(before, ensure_ascii=False, indent=2, sort_keys=True)
    after_text = json.dumps(after, ensure_ascii=False, indent=2, sort_keys=True)
    return "\n".join(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )


def active_proposals(item: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    proposals = ((item.get("review") or {}).get("sentence_proposals") or [])
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        if proposal.get("status") in ACTIVE_STATUSES:
            yield proposal


def proposal_matches(proposal: Dict[str, Any], proposal_id: str | None) -> bool:
    return proposal_id is None or proposal.get("id") == proposal_id


def proposed_sentence_text(proposal: Dict[str, Any]) -> str:
    return str(proposal.get("proposed_sentence") or proposal.get("proposed_japanese") or "")


def proposed_translations(proposal: Dict[str, Any], sentence: Dict[str, Any]) -> Dict[str, str]:
    translations = proposal.get("proposed_translations")
    if isinstance(translations, dict) and translations:
        return {str(lang): str(value) for lang, value in translations.items() if str(value).strip()}
    out = dict(sentence.get("translations") or {})
    english = str(proposal.get("proposed_english") or "").strip()
    if english:
        out["en"] = english
    return out


def attach_analysis(item: Dict[str, Any], proposal: Dict[str, Any]) -> bool:
    sentence_index = int(proposal.get("sentence_index") or 0)
    sentences = item.get("sentences") or []
    if sentence_index <= 0 or sentence_index > len(sentences):
        proposal["analysis_status"] = "invalid_sentence_index"
        return True
    text = proposed_sentence_text(proposal)
    analysis = analyze_sentence(
        str(item.get("language") or ""),
        text,
        existing_sentence=sentences[sentence_index - 1],
        entry=item,
        ruby_source=proposal.get("proposed_ruby_source"),
    )
    proposal["analysis_status"] = "generated" if analysis.tokens else "needs_analysis"
    proposal["analysis"] = analysis.as_dict()
    proposal["generated_tokens"] = analysis.tokens
    proposal["generated_reading"] = analysis.reading
    proposal["analyzer"] = analysis.analyzer
    validation = proposal.setdefault("validation", {})
    validation["token_sequence_errors"] = []
    validation["notes"] = [
        "Automatic sentence analysis is attached to this proposal.",
        "Review generated tokens/POS before applying to release content.",
    ]
    proposal["updated_utc"] = utc_now()
    return True


def apply_proposal(item: Dict[str, Any], proposal: Dict[str, Any], *, applied_by: str, mark_approved: bool) -> bool:
    sentence_index = int(proposal.get("sentence_index") or 0)
    sentences = item.get("sentences") or []
    if sentence_index <= 0 or sentence_index > len(sentences):
        proposal["status"] = "invalid_sentence_index"
        proposal["updated_utc"] = utc_now()
        return True
    sentence = sentences[sentence_index - 1]
    if proposal.get("analysis_status") != "generated" or not proposal.get("generated_tokens"):
        attach_analysis(item, proposal)
    tokens = copy.deepcopy(proposal.get("generated_tokens") or [])
    text = proposed_sentence_text(proposal)
    sentence["target"] = text
    sentence["translations"] = proposed_translations(proposal, sentence)
    sentence["tokens"] = tokens
    if proposal.get("generated_reading"):
        sentence["reading"] = proposal["generated_reading"]
    elif str(item.get("language") or "") != "ja":
        sentence["reading"] = sentence.get("reading", "")
    proposal["status"] = "applied"
    proposal["applied_utc"] = utc_now()
    proposal["applied_by"] = applied_by
    proposal["updated_utc"] = proposal["applied_utc"]
    review = item.setdefault("review", {})
    review["status"] = "approved" if mark_approved else "needs_review"
    review["last_sentence_proposal_applied_utc"] = proposal["applied_utc"]
    sync_item_pos_analysis(item)
    return True


def process_item(
    item: Dict[str, Any],
    *,
    proposal_id: str | None,
    apply: bool,
    applied_by: str,
    mark_approved: bool,
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(item)
    changed = False
    for proposal in active_proposals(updated):
        if not proposal_matches(proposal, proposal_id):
            continue
        if apply:
            changed = apply_proposal(updated, proposal, applied_by=applied_by, mark_approved=mark_approved) or changed
        else:
            changed = attach_analysis(updated, proposal) or changed
    return updated, changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze or apply Vocomipedia sentence proposals with offline POS/token generation.")
    ap.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", required=True, type=Path)
    ap.add_argument("--proposal-id", default=None)
    ap.add_argument("--apply", action="store_true", help="Apply matching active proposals to canonical sentence data.")
    ap.add_argument("--mark-approved", action="store_true", help="Mark item review.status approved after applying a proposal.")
    ap.add_argument("--applied-by", default="vocomipedia-sentence-proposal-tool")
    ap.add_argument("--backup-dir", default=Path("backups"), type=Path)
    ap.add_argument("--diff-report", default=None, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    item_paths = [path for _item, path in iter_pack_items(args.pack_dir)]
    if not args.dry_run:
        create_backup(paths=item_paths + [args.pack_dir / "pack.json"], backup_dir=args.backup_dir, label="sentence-proposals", base_dir=args.pack_dir)

    diff_chunks: List[str] = []
    changed_count = 0
    for item, path in iter_pack_items(args.pack_dir):
        before = copy.deepcopy(item)
        after, changed = process_item(item, proposal_id=args.proposal_id, apply=args.apply, applied_by=args.applied_by, mark_approved=args.mark_approved)
        if not changed or before == after:
            continue
        errors = validate_item(after, strict_content=True)
        if errors:
            raise SystemExit(f"{path}: validation failed after proposal processing:\n- " + "\n- ".join(errors))
        changed_count += 1
        diff_chunks.append(f"### {path}\n{item_diff(before, after)}")
        if not args.dry_run:
            write_json(path, after)

    if args.diff_report:
        args.diff_report.parent.mkdir(parents=True, exist_ok=True)
        args.diff_report.write_text("\n\n".join(diff_chunks), encoding="utf-8")

    action = "applied" if args.apply else "analyzed"
    print(f"{action} sentence proposals in {changed_count} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
