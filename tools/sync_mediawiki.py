#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import html
import http.client
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from common import iter_pack_items, load_pack_manifest, safe_filename, validate_token_sequence, write_json
from japanese_ruby import normalize_japanese_item, parse_ruby_text, reading_from_ruby_text, ruby_from_surface_reading, sentence_reading_from_tokens
from vocomipedia_nlp import analyze_sentence, sync_item_pos_analysis

JSON_START = "VOCOMIPEDIA_ITEM_JSON_START"
JSON_END = "VOCOMIPEDIA_ITEM_JSON_END"
JAPANESE_RUBY_REVIEW_CATEGORY = "Japanese ruby needs review"
SENTENCE_PROPOSAL_CATEGORY = "Sentence replacement proposals"
ITEM_TEMPLATE = "VocomipediaItem"
SENTENCE_TEMPLATE = "VocomipediaSentence"
TOKEN_TEMPLATE = "VocomipediaToken"
ITEM_FORM = "Vocomipedia item"
ITEM_CATEGORY = "Vocomipedia items"
STRUCTURE_WARNING_MESSAGE = "abusefilter-warning-vocomipedia-structure"
NS_MAIN = 0
NS_MEDIAWIKI = 8
NS_ITEM = 3000
NS_DECK = 3002
NS_POLICY = 3004
GLOSS_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("ko", "Korean"),
    ("zh-Hans", "Chinese (Simplified)"),
    ("yue", "Cantonese"),
    ("ru", "Russian"),
    ("pt", "Portuguese"),
    ("he", "Hebrew"),
    ("tr", "Turkish"),
    ("vi", "Vietnamese"),
    ("ar", "Arabic"),
    ("nl", "Dutch"),
    ("uk", "Ukrainian"),
    ("hu", "Hungarian"),
    ("hi", "Hindi"),
    ("pl", "Polish"),
    ("el", "Greek"),
    ("nb", "Norwegian Bokmal"),
    ("id", "Indonesian"),
    ("sv", "Swedish"),
    ("ro", "Romanian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("ja", "Japanese"),
]
GLOSS_LANG_BY_FIELD: dict[str, str] = {}
TRANSLATION_LANG_BY_FIELD: dict[str, str] = {}

NAMESPACE_IDS = {
    "": NS_MAIN,
    "Item": NS_ITEM,
    "Deck": NS_DECK,
    "Policy": NS_POLICY,
    "MediaWiki": NS_MEDIAWIKI,
    "Vocomipedia": 4,
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def split_namespace_prefix(prefix: str, namespace: int | None = None) -> tuple[int, str]:
    if namespace is not None:
        return namespace, prefix.split(":", 1)[1] if ":" in prefix and NAMESPACE_IDS.get(prefix.split(":", 1)[0]) == namespace else prefix
    if ":" not in prefix:
        return NS_MAIN, prefix
    ns_name, rest = prefix.split(":", 1)
    if ns_name in NAMESPACE_IDS:
        return NAMESPACE_IDS[ns_name], rest
    return NS_MAIN, prefix


def wiki_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "&#124;").replace("\n", "<br />")


def unwiki_cell(value: str) -> str:
    text = html.unescape(value.strip())
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return text.strip()


def yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "yes", "y", "true", "main"}


class WikiPageFormatError(ValueError):
    pass


def wiki_template_value(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "&#124;").strip()


def wiki_image_caption(value: object) -> str:
    return str(value or "").replace("|", " ").replace("[", "").replace("]", "").strip()


def headword_ruby_source(item: dict) -> str:
    headword = str(item.get("headword") or item.get("entry_id") or "")
    if str(item.get("language") or "") != "ja":
        return headword
    return str(ruby_from_surface_reading(headword, str(item.get("reading") or "")).get("ruby_text") or headword)


def gloss_field_name(lang: str) -> str:
    return "gloss_" + re.sub(r"[^a-z0-9]+", "_", lang.lower()).strip("_")


def translation_field_name(lang: str) -> str:
    return "translation_" + re.sub(r"[^a-z0-9]+", "_", lang.lower()).strip("_")


def gloss_language_label(lang: str) -> str:
    labels = dict(GLOSS_LANGUAGES)
    return labels.get(lang, lang)


def sentence_target_label(item: dict) -> str:
    lang = str(item.get("language") or "").strip()
    return gloss_language_label(lang) if lang else "Sentence"


def token_display_source(item: dict, token: dict) -> str:
    if str(item.get("language") or "") == "ja":
        return str(token.get("ruby_text") or token.get("furigana") or token.get("surface") or "")
    return str(token.get("surface") or "")


def sentence_ruby_source(item: dict, sentence: dict) -> str:
    target = str(sentence.get("target") or "")
    if str(item.get("language") or "") != "ja":
        return target
    out: list[str] = []
    cursor = 0
    for token in sentence.get("tokens") or []:
        source = token_display_source(item, token)
        surface, _spans = parse_ruby_text(source)
        surface = surface or str(token.get("surface") or "")
        if not surface:
            continue
        found = target.find(surface, cursor)
        if found < 0:
            continue
        out.append(target[cursor:found])
        out.append(source)
        cursor = found + len(surface)
    out.append(target[cursor:])
    return "".join(out) or target


GLOSS_LANG_BY_FIELD.update({gloss_field_name(lang): lang for lang, _label in GLOSS_LANGUAGES})
TRANSLATION_LANG_BY_FIELD.update({translation_field_name(lang): lang for lang, _label in GLOSS_LANGUAGES})


def entry_image_filename(item: dict) -> str:
    suffix = str(item.get("id") or item.get("entry_id") or "item").split(":")[-1]
    pack = str(item.get("pack_code") or "deck")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{pack}_{suffix}").strip("._")
    return f"Vocomipedia_{safe}_entry.jpg"


def make_low_res_entry_image(source: Path, dest: Path, max_edge: int = 360) -> None:
    from PIL import Image

    with Image.open(source) as img:
        img = img.convert("RGBA")
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        background.save(dest, "JPEG", quality=78, optimize=True, progressive=True)


def prepare_entry_image(pack_dir: Path, item: dict, work_dir: Path) -> tuple[str, Path] | None:
    media = item.get("media") or {}
    image = media.get("image_filename")
    if not image:
        return None
    source = pack_dir / "media" / str(image)
    if not source.exists():
        return None
    filename = entry_image_filename(item)
    dest = work_dir / filename
    make_low_res_entry_image(source, dest)
    return filename, dest


def entry_image_reference(pack_dir: Path, item: dict) -> str | None:
    media = item.get("media") or {}
    image = media.get("image_filename")
    if not image:
        return None
    source = pack_dir / "media" / str(image)
    if not source.exists():
        return None
    return entry_image_filename(item)


def unwiki_template_value(value: str) -> str:
    return unwiki_cell(value)


def render_template_call(name: str, fields: list[tuple[str, object]], raw_fields: set[str] | None = None) -> list[str]:
    raw_fields = raw_fields or set()
    lines = [f"{{{{{name}"]
    for key, value in fields:
        if key in raw_fields:
            lines.append(f"|{key}={'' if value is None else str(value).strip()}")
        else:
            lines.append(f"|{key}={wiki_template_value(value)}")
    lines.append("}}")
    return lines


def find_template_calls(source: str, names: set[str] | None = None) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    idx = 0
    length = len(source)
    while idx < length:
        start = source.find("{{", idx)
        if start < 0:
            break
        pos = start + 2
        depth = 1
        while pos < length and depth:
            if source.startswith("{{", pos):
                depth += 1
                pos += 2
            elif source.startswith("}}", pos):
                depth -= 1
                pos += 2
            else:
                pos += 1
        if depth:
            break
        body = source[start + 2 : pos - 2]
        name = body.split("|", 1)[0].strip()
        canonical = name.split(":", 1)[-1].strip()
        if names is None or canonical in names:
            calls.append((canonical, body))
        idx = pos
    return calls


def split_template_parts(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    brace_depth = 0
    link_depth = 0
    i = 0
    while i < len(body):
        if body.startswith("{{", i):
            brace_depth += 1
            current.append("{{")
            i += 2
            continue
        if body.startswith("}}", i) and brace_depth:
            brace_depth -= 1
            current.append("}}")
            i += 2
            continue
        if body.startswith("[[", i):
            link_depth += 1
            current.append("[[")
            i += 2
            continue
        if body.startswith("]]", i) and link_depth:
            link_depth -= 1
            current.append("]]")
            i += 2
            continue
        char = body[i]
        if char == "|" and brace_depth == 0 and link_depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    parts.append("".join(current))
    return parts


def parse_template_params(body: str) -> dict[str, str]:
    parts = split_template_parts(body)
    params: dict[str, str] = {}
    for raw in parts[1:]:
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        params[key.strip().lower()] = unwiki_template_value(value)
    return params


def token_ruby_status(token: dict) -> str:
    return str(token.get("ruby_confidence") or "").strip() or "untracked"


def sentence_english(sentence: dict) -> str:
    translations = sentence.get("translations") or {}
    return str(translations.get("en") or "")


def sentence_proposal_id(
    item: dict,
    sentence_index: int,
    old_sentence: str,
    old_translations: dict,
    proposed_sentence: str,
    proposed_translations: dict,
    reason: str,
    proposed_ruby_source: str | None = None,
) -> str:
    payload = {
        "item_id": item.get("id", ""),
        "sentence_index": sentence_index,
        "old_sentence": old_sentence,
        "old_translations": old_translations,
        "proposed_sentence": proposed_sentence,
        "proposed_translations": proposed_translations,
        "proposed_ruby_source": proposed_ruby_source or "",
        "reason": reason,
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"sentprop-{digest[:16]}"


def classify_sentence_proposal(sentence: dict, proposed_sentence: str, proposed_translations: dict) -> tuple[str, str, list[str], list[str]]:
    old_sentence = str(sentence.get("target") or "")
    old_translations = sentence.get("translations") or {}
    if proposed_sentence == old_sentence:
        if proposed_translations != old_translations:
            return "translation_update", "pending_review", ["human_review"], []
        return "no_content_change", "pending_review", ["human_review"], []
    return (
        "sentence_replacement",
        "pending_review",
        ["human_review", "auto_generated_token_review", "comic_scene_compatibility_review"],
        [],
    )


def add_sentence_proposal(
    updated: dict,
    item: dict,
    sentence_index: int,
    sentence: dict,
    proposed_sentence: str,
    proposed_translations: dict | None,
    reason: str,
    proposed_ruby_source: str | None = None,
) -> None:
    old_sentence = str(sentence.get("target") or "")
    old_translations = dict(sentence.get("translations") or {})
    proposed_sentence = proposed_sentence or old_sentence
    proposed_translations = dict(proposed_translations or old_translations)
    if "en" not in proposed_translations and sentence_english(sentence):
        proposed_translations["en"] = sentence_english(sentence)
    current_ruby_source = sentence_ruby_source(item, sentence)
    kind, status, requires, _old_token_errors = classify_sentence_proposal(sentence, proposed_sentence, proposed_translations)
    if proposed_sentence == old_sentence and proposed_translations == old_translations and proposed_ruby_source and proposed_ruby_source != current_ruby_source:
        kind = "ruby_update"
        requires = ["human_review", "auto_generated_token_review"]
    analysis = analyze_sentence(
        str(updated.get("language") or item.get("language") or ""),
        proposed_sentence,
        existing_sentence=sentence,
        entry=updated,
        ruby_source=proposed_ruby_source,
    )
    analysis_dict = analysis.as_dict()
    probe = copy.deepcopy(sentence)
    probe["target"] = proposed_sentence
    probe["tokens"] = analysis.tokens
    probe["reading"] = analysis.reading
    token_errors = validate_token_sequence(probe) if str(updated.get("language") or item.get("language") or "") == "ja" else []
    now = utc_now()
    proposal = {
        "id": sentence_proposal_id(
            item,
            sentence_index,
            old_sentence,
            old_translations,
            proposed_sentence,
            proposed_translations,
            reason,
            proposed_ruby_source,
        ),
        "status": status,
        "type": kind,
        "item_id": item.get("id", ""),
        "pack_code": item.get("pack_code", ""),
        "entry_id": item.get("entry_id", ""),
        "language": updated.get("language") or item.get("language", ""),
        "sentence_index": sentence_index,
        "old_sentence": old_sentence,
        "old_translations": old_translations,
        "proposed_sentence": proposed_sentence,
        "proposed_translations": proposed_translations,
        "old_ruby_source": current_ruby_source if str(updated.get("language") or item.get("language") or "") == "ja" else "",
        "proposed_ruby_source": proposed_ruby_source or "",
        "old_japanese": old_sentence,
        "old_english": old_translations.get("en", ""),
        "proposed_japanese": proposed_sentence,
        "proposed_english": proposed_translations.get("en", ""),
        "reason": reason,
        "analysis_status": "generated" if analysis.tokens else "needs_analysis",
        "analysis": analysis_dict,
        "generated_tokens": analysis.tokens,
        "generated_reading": analysis.reading,
        "analyzer": analysis.analyzer,
        "requires": requires,
        "validation": {
            "token_sequence_errors": token_errors,
            "comic_policy": "must_remain_valid",
            "comic_invalidation_supported": False,
            "notes": (
                [
                    "Automatic token analysis did not fully cover the proposed sentence. Review or regenerate before applying.",
                    "Comic invalidation is not supported; reviewers must keep or adapt the sentence to the existing comic scene.",
                ]
                if token_errors
                else [
                    "Automatic sentence analysis is attached to this proposal.",
                    "Review generated tokens/POS before applying to release content.",
                ]
            ),
        },
        "created_utc": now,
        "updated_utc": now,
    }
    review = updated.setdefault("review", {})
    proposals = review.setdefault("sentence_proposals", [])
    if not isinstance(proposals, list):
        proposals = []
        review["sentence_proposals"] = proposals
    for idx, existing in enumerate(proposals):
        if isinstance(existing, dict) and existing.get("id") == proposal["id"]:
            proposal["created_utc"] = existing.get("created_utc") or proposal["created_utc"]
            proposals[idx] = proposal
            return
    proposals.append(proposal)


def item_has_sentence_proposals(item: dict) -> bool:
    proposals = (item.get("review") or {}).get("sentence_proposals") or []
    return any(isinstance(proposal, dict) and proposal.get("status") not in {"applied", "rejected"} for proposal in proposals)


def render_sentence_fields(sentence: dict) -> list[str]:
    translations = sentence.get("translations") or {}
    rows = [
        ("Sentence", sentence.get("target", "")),
        ("Reading preview", sentence_reading_from_tokens(str(sentence.get("target", "")), sentence.get("tokens") or [], str(sentence.get("reading") or ""))),
    ]
    for lang, label in GLOSS_LANGUAGES:
        if translations.get(lang):
            rows.append((label, translations.get(lang, "")))
    lines = [
        '{| class="wikitable vocomipedia-sentence-fields"',
        "! Field",
        "! Value",
    ]
    for label, value in rows:
        lines.extend(["|-", f"| {label}", f"| {wiki_cell(value)}"])
    lines.append("|}")
    return lines


def render_token_table(sentence: dict) -> list[str]:
    lines = [
        '{| class="wikitable vocomipedia-token-table"',
        "! #",
        "! Surface",
        "! Ruby",
        "! Lemma",
        "! POS",
        "! Meaning",
    ]
    for idx, token in enumerate(sentence.get("tokens") or [], start=1):
        lines.extend(
            [
                "|-",
                f"| {idx}",
                f"| {wiki_cell(token.get('surface', ''))}",
                f"| {wiki_cell(token.get('ruby_text') or token.get('furigana', ''))}",
                f"| {wiki_cell(token.get('lemma', ''))}",
                f"| {wiki_cell(token.get('pos', ''))}",
                f"| {wiki_cell(token.get('surface_en', ''))}",
            ]
        )
    lines.append("|}")
    return lines


def japanese_ruby_review_rows(item: dict, needs_review_only: bool = False) -> list[dict]:
    if item.get("language") != "ja":
        return []
    rows: list[dict] = []
    for sentence_idx, sentence in enumerate(item.get("sentences") or [], start=1):
        target = str(sentence.get("target") or "")
        for token_idx, token in enumerate(sentence.get("tokens") or [], start=1):
            status = token_ruby_status(token)
            if needs_review_only and status != "needs_review":
                continue
            if status not in {"needs_review", "medium"}:
                continue
            rows.append(
                {
                    "item": item,
                    "sentence_idx": sentence_idx,
                    "token_idx": token_idx,
                    "target": target,
                    "surface": token.get("surface", ""),
                    "ruby_text": token.get("ruby_text") or token.get("furigana", ""),
                    "reading_kana": token.get("reading_kana") or token.get("furigana", ""),
                    "status": status,
                }
            )
    return rows


def item_has_ruby_review_flags(item: dict) -> bool:
    return bool(japanese_ruby_review_rows(item, needs_review_only=True))


def render_item_page(item: dict, entry_image: str | None = None) -> str:
    item = normalize_japanese_item(item)
    language = str(item.get("language") or "")
    canonical_json = json.dumps(item, ensure_ascii=False, indent=2)
    needs_ruby_review = item_has_ruby_review_flags(item)
    has_sentence_proposals = item_has_sentence_proposals(item)
    item_fields = [
        ("id", item.get("id", "")),
        ("pack_code", item.get("pack_code", "")),
        ("entry_id", item.get("entry_id", "")),
        ("language", item.get("language", "")),
        ("image", entry_image or ""),
        ("image_caption", wiki_image_caption(item.get("headword") or item.get("entry_id") or "")),
        ("level", item.get("level", "")),
        ("part_of_speech", ", ".join(str(part) for part in (item.get("part_of_speech") or []) if str(part))),
        ("headword_ruby", headword_ruby_source(item)),
    ]
    glosses = item.get("glosses") or {}
    for lang, _label in GLOSS_LANGUAGES:
        value = glosses.get(lang, "")
        if value:
            item_fields.append((gloss_field_name(lang), value))
    lines = [
        *render_template_call(ITEM_TEMPLATE, item_fields),
    ]
    for idx, sentence in enumerate(item.get("sentences") or [], start=1):
        translations = sentence.get("translations") or {}
        sentence_fields = [
            ("target_label", sentence_target_label(item)),
            ("ruby_sentence", yes_no(language == "ja")),
            ("japanese", sentence.get("target", "")),
            ("index", idx),
            ("ruby_source", sentence_ruby_source(item, sentence)),
        ]
        for lang, _label in GLOSS_LANGUAGES:
            value = translations.get(lang, "")
            if value:
                sentence_fields.append((translation_field_name(lang), value))
        lines.extend(
            [
                *render_template_call(
                    SENTENCE_TEMPLATE,
                    sentence_fields,
                ),
            ]
        )
    if needs_ruby_review:
        lines.extend([f"[[Category:{JAPANESE_RUBY_REVIEW_CATEGORY}]]"])
    if has_sentence_proposals:
        lines.extend([f"[[Category:{SENTENCE_PROPOSAL_CATEGORY}]]"])
    lines.extend(["__NOEDITSECTION__", f"{{{{#default_form:{ITEM_FORM}}}}}"])
    lines.extend([f"<!-- {JSON_START}", canonical_json, f"{JSON_END} -->"])
    return "\n".join(lines)


def extract_item_json(source: str) -> dict | None:
    pattern = rf"<!--\s*{re.escape(JSON_START)}\s*(.*?)\s*{re.escape(JSON_END)}\s*-->"
    match = re.search(pattern, source, flags=re.S)
    if not match:
        return None
    item = json.loads(match.group(1))
    return normalize_japanese_item(apply_visible_page_edits(source, item))


def has_vocomipedia_templates(source: str) -> bool:
    names = {ITEM_TEMPLATE, SENTENCE_TEMPLATE, TOKEN_TEMPLATE}
    return any(name in names for name, _body in find_template_calls(source, names))


def require_same(params: dict[str, str], key: str, expected: object, title: str) -> None:
    if key not in params:
        raise WikiPageFormatError(f"{title}: missing protected field {key!r}")
    actual = str(params.get(key) or "")
    if actual != str(expected or ""):
        raise WikiPageFormatError(f"{title}: protected field {key!r} changed from {expected!r} to {actual!r}")


def parse_positive_int(value: str, title: str, field: str) -> int:
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise WikiPageFormatError(f"{title}: {field} must be a positive integer, got {value!r}") from exc
    if parsed <= 0:
        raise WikiPageFormatError(f"{title}: {field} must be a positive integer, got {value!r}")
    return parsed


def apply_template_page_edits(source: str, item: dict) -> dict:
    updated = copy.deepcopy(item)
    template_calls = find_template_calls(source, {ITEM_TEMPLATE, SENTENCE_TEMPLATE, TOKEN_TEMPLATE})
    by_name: dict[str, list[dict[str, str]]] = {ITEM_TEMPLATE: [], SENTENCE_TEMPLATE: [], TOKEN_TEMPLATE: []}
    for name, body in template_calls:
        params = parse_template_params(body)
        if name in {ITEM_TEMPLATE, SENTENCE_TEMPLATE}:
            by_name[name].append(params)
        elif name == TOKEN_TEMPLATE:
            by_name[name].append(params)

    if len(by_name[ITEM_TEMPLATE]) != 1:
        raise WikiPageFormatError(f"{item.get('id', '<unknown>')}: expected exactly one {ITEM_TEMPLATE} template")
    item_params = by_name[ITEM_TEMPLATE][0]
    require_same(item_params, "id", item.get("id"), str(item.get("id", "<unknown>")))
    require_same(item_params, "pack_code", item.get("pack_code"), str(item.get("id", "<unknown>")))
    require_same(item_params, "entry_id", item.get("entry_id"), str(item.get("id", "<unknown>")))
    if "headword_ruby" in item_params:
        headword_source = item_params["headword_ruby"].strip()
        headword_surface, _spans = parse_ruby_text(headword_source)
        if headword_surface:
            updated["headword"] = headword_surface
            updated["reading"] = reading_from_ruby_text(headword_source)
    glosses = updated.setdefault("glosses", {})
    if not isinstance(glosses, dict):
        glosses = {}
        updated["glosses"] = glosses
    for field, lang in GLOSS_LANG_BY_FIELD.items():
        if field not in item_params:
            continue
        value = item_params[field].strip()
        if value:
            glosses[lang] = value
        else:
            glosses.pop(lang, None)

    sentences = updated.setdefault("sentences", [])
    sentence_params_by_index: dict[int, dict[str, str]] = {}
    for params in by_name[SENTENCE_TEMPLATE]:
        index = parse_positive_int(params.get("index", ""), str(item.get("id", "<unknown>")), "sentence index")
        if index in sentence_params_by_index:
            raise WikiPageFormatError(f"{item.get('id', '<unknown>')}: duplicate sentence template index {index}")
        sentence_params_by_index[index] = params
    expected_sentence_indexes = set(range(1, len(sentences) + 1))
    actual_sentence_indexes = set(sentence_params_by_index)
    if actual_sentence_indexes != expected_sentence_indexes:
        raise WikiPageFormatError(
            f"{item.get('id', '<unknown>')}: sentence template indexes changed; expected "
            f"{sorted(expected_sentence_indexes)}, got {sorted(actual_sentence_indexes)}"
        )

    sentence_order = [
        parse_positive_int(params.get("index", ""), str(item.get("id", "<unknown>")), "sentence index")
        for params in by_name[SENTENCE_TEMPLATE]
    ]
    expected_sentence_order = list(range(1, len(sentences) + 1))
    if sentence_order != expected_sentence_order:
        raise WikiPageFormatError(f"{item.get('id', '<unknown>')}: sentence template order changed")

    for sentence_index, sentence in enumerate(sentences, start=1):
        params = sentence_params_by_index[sentence_index]
        current_sentence = str(sentence.get("target") or "")
        current_ruby_source = sentence_ruby_source(item, sentence)
        current_translations = dict(sentence.get("translations") or {})
        incoming_ruby_source = params.get("ruby_source", "").strip()
        if incoming_ruby_source:
            incoming_sentence = parse_ruby_text(incoming_ruby_source)[0] if str(updated.get("language") or "") == "ja" else incoming_ruby_source
        else:
            incoming_sentence = params.get("japanese", current_sentence).strip()
            incoming_ruby_source = incoming_sentence
        incoming_translations: dict[str, str] = {}
        for field, lang in TRANSLATION_LANG_BY_FIELD.items():
            if field in params:
                incoming_translations[lang] = params[field].strip()
        if "english" in params and "en" not in incoming_translations:
            incoming_translations["en"] = params["english"].strip()
        proposal_sentence = params.get("proposal_japanese", "").strip()
        proposal_english = params.get("proposal_english", "").strip()
        proposal_reason = params.get("proposal_reason", "").strip()
        has_explicit_proposal = bool(proposal_sentence or proposal_english)
        changed_translations = {
            lang
            for lang, value in incoming_translations.items()
            if value != str(current_translations.get(lang) or "")
        }

        changed_ruby_source = str(updated.get("language") or "") == "ja" and incoming_ruby_source != current_ruby_source

        if incoming_sentence != current_sentence or changed_ruby_source or has_explicit_proposal:
            proposed_sentence = proposal_sentence or incoming_sentence
            proposed_ruby_source = incoming_ruby_source if not proposal_sentence else ""
            proposed_translations = dict(current_translations)
            proposed_translations.update({lang: value for lang, value in incoming_translations.items() if value})
            for lang, value in incoming_translations.items():
                if not value and lang in proposed_translations:
                    proposed_translations.pop(lang)
            if proposal_english:
                proposed_translations["en"] = proposal_english
            add_sentence_proposal(
                updated,
                item,
                sentence_index,
                sentence,
                proposed_sentence,
                proposed_translations,
                proposal_reason,
                proposed_ruby_source=proposed_ruby_source,
            )
        elif changed_translations:
            translations = sentence.setdefault("translations", {})
            if "english" in params and "en" not in incoming_translations:
                incoming_translations["en"] = params["english"].strip()
            for lang, value in incoming_translations.items():
                if value:
                    translations[lang] = value
                else:
                    translations.pop(lang, None)

    payload = updated.setdefault("app_payload", {})
    pos_analysis = payload.get("pos_analysis")
    if isinstance(pos_analysis, list):
        for idx, sentence in enumerate(sentences):
            if idx >= len(pos_analysis) or not isinstance(pos_analysis[idx], dict):
                continue
            pos_analysis[idx]["sentence"] = sentence.get("target", "")
            pos_analysis[idx]["tokens"] = sentence.get("tokens", [])
            if sentence.get("difficulty") is not None:
                pos_analysis[idx]["difficulty_aggregated"] = sentence.get("difficulty")
    return updated


def table_blocks(source: str, class_name: str) -> list[str]:
    blocks: list[str] = []
    pattern = rf'\{{\|[^\n]*\b{re.escape(class_name)}\b[^\n]*\n(.*?)^\|\}}'
    for match in re.finditer(pattern, source, flags=re.M | re.S):
        blocks.append(match.group(1))
    return blocks


def parse_table_rows(table_body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    current: list[str] = []
    for raw in table_body.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("|-"):
            if current:
                rows.append(current)
            current = []
            continue
        if line.startswith("|"):
            current.append(unwiki_cell(line[1:]))
    if current:
        rows.append(current)
    return rows


def apply_visible_page_edits(source: str, item: dict) -> dict:
    if has_vocomipedia_templates(source):
        return apply_template_page_edits(source, item)
    if "vocomipedia-sentence-fields" not in source and "vocomipedia-token-table" not in source:
        raise WikiPageFormatError(f"{item.get('id', '<unknown>')}: missing Vocomipedia form templates")

    updated = copy.deepcopy(item)
    sentences = updated.setdefault("sentences", [])
    field_tables = table_blocks(source, "vocomipedia-sentence-fields")
    token_tables = table_blocks(source, "vocomipedia-token-table")

    for idx, table in enumerate(field_tables):
        if idx >= len(sentences):
            break
        sentence = sentences[idx]
        fields = {row[0].strip().lower(): row[1] for row in parse_table_rows(table) if len(row) >= 2}
        incoming_sentence = fields.get("sentence", fields.get("japanese", str(sentence.get("target") or "")))
        if "english" in fields:
            translations = dict(sentence.get("translations") or {})
            translations["en"] = fields["english"]
        else:
            translations = dict(sentence.get("translations") or {})
        if incoming_sentence != str(sentence.get("target") or ""):
            add_sentence_proposal(updated, item, idx + 1, sentence, incoming_sentence, translations, "")
        elif translations != dict(sentence.get("translations") or {}):
            sentence["translations"] = translations

    payload = updated.setdefault("app_payload", {})
    pos_analysis = payload.get("pos_analysis")
    if isinstance(pos_analysis, list):
        for idx, sentence in enumerate(sentences):
            if idx >= len(pos_analysis) or not isinstance(pos_analysis[idx], dict):
                continue
            pos_analysis[idx]["sentence"] = sentence.get("target", "")
            pos_analysis[idx]["tokens"] = sentence.get("tokens", [])
            if sentence.get("difficulty") is not None:
                pos_analysis[idx]["difficulty_aggregated"] = sentence.get("difficulty")
    return updated


def api_url_candidates(api_url: str) -> list[str]:
    raw = str(api_url or "").strip()
    if not raw:
        return []
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return [raw]
    origin = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    path = parsed.path or ""
    candidates = [raw]
    if path.endswith("/api.php"):
        parent = path[: -len("/api.php")]
        if parent:
            candidates.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parent + "/api.php", "", "", "")))
    elif path.endswith("/"):
        candidates.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/") + "/api.php", "", "", "")))
    elif path:
        candidates.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/") + "/api.php", "", "", "")))
    candidates.extend([origin + "/api.php", origin + "/w/api.php"])
    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def resolve_api_url(api_url: str) -> str:
    candidates = api_url_candidates(api_url)
    if not candidates:
        raise ValueError("MediaWiki API URL is empty")
    probe_params = urllib.parse.urlencode({"action": "query", "meta": "siteinfo", "format": "json"})
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            with urllib.request.urlopen(candidate + "?" + probe_params, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data.get("query"), dict):
                if candidate != candidates[0]:
                    print(f"Resolved MediaWiki API URL from configured value to {candidate}", file=sys.stderr)
                return candidate
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return candidates[0]


class MediaWikiClient:
    def __init__(self, api_url: str):
        self.api_url = resolve_api_url(api_url)
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def open_with_retries(self, request_factory, *, attempts: int = 5) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with self.opener.open(request_factory(), timeout=180) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                    raise
                last_error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, http.client.RemoteDisconnected) as exc:
                if attempt == attempts:
                    raise
                last_error = exc
            time.sleep(min(30, 2 ** attempt))
        if last_error:
            raise last_error
        raise RuntimeError("MediaWiki request failed without an exception")

    def request(self, params: dict, method: str = "POST") -> dict:
        encoded = urllib.parse.urlencode(params).encode("utf-8")

        def make_request():
            if method == "GET":
                url = self.api_url + "?" + encoded.decode("utf-8")
                return urllib.request.Request(url)
            return urllib.request.Request(self.api_url, data=encoded)

        return json.loads(self.open_with_retries(make_request).decode("utf-8"))

    def login(self, username: str, password: str) -> None:
        token_resp = self.request({"action": "query", "meta": "tokens", "type": "login", "format": "json"})
        login_token = token_resp["query"]["tokens"]["logintoken"]
        resp = self.request(
            {
                "action": "login",
                "lgname": username,
                "lgpassword": password,
                "lgtoken": login_token,
                "format": "json",
            }
        )
        result = (resp.get("login") or {}).get("result")
        if result != "Success":
            raise RuntimeError(f"MediaWiki login failed: {resp}")

    def csrf_token(self) -> str:
        resp = self.request({"action": "query", "meta": "tokens", "format": "json"})
        return resp["query"]["tokens"]["csrftoken"]

    def edit(self, title: str, text: str, summary: str, token: str) -> None:
        resp = self.request(
            {
                "action": "edit",
                "title": title,
                "text": text,
                "summary": summary,
                "token": token,
                "format": "json",
                "bot": "1",
            }
        )
        if "error" in resp:
            raise RuntimeError(f"MediaWiki edit failed for {title}: {resp}")

    def upload_file(self, filename: str, path: Path, comment: str, token: str) -> None:
        boundary = "----VocomipediaBoundary" + os.urandom(12).hex()
        fields = {
            "action": "upload",
            "filename": filename,
            "comment": comment,
            "ignorewarnings": "1",
            "token": token,
            "format": "json",
        }
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
                b"Content-Type: image/jpeg\r\n\r\n",
                path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        body = b"".join(chunks)

        def make_request():
            return urllib.request.Request(
                self.api_url,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        data = json.loads(self.open_with_retries(make_request).decode("utf-8"))
        if "error" in data:
            if (data.get("error") or {}).get("code") == "fileexists-no-change":
                return
            raise RuntimeError(f"MediaWiki upload failed for {filename}: {data}")
        result = (data.get("upload") or {}).get("result")
        if result not in {"Success", "Warning"}:
            raise RuntimeError(f"MediaWiki upload failed for {filename}: {data}")

    def all_pages(self, prefix: str, namespace: int | None = None) -> list[str]:
        namespace_id, api_prefix = split_namespace_prefix(prefix, namespace)
        titles: list[str] = []
        cont: dict = {}
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apprefix": api_prefix,
                "apnamespace": str(namespace_id),
                "aplimit": "50",
                "format": "json",
            }
            params.update(cont)
            resp = self.request(params, method="GET")
            titles.extend(p["title"] for p in resp.get("query", {}).get("allpages", []))
            if "continue" not in resp:
                break
            cont = resp["continue"]
        return titles

    def raw_page_with_metadata(self, title: str) -> tuple[str, dict]:
        resp = self.request(
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "ids|timestamp|user|comment|content",
                "rvslots": "main",
                "formatversion": "2",
                "format": "json",
            },
            method="GET",
        )
        pages = resp.get("query", {}).get("pages", [])
        if not pages or "missing" in pages[0]:
            return "", {}
        revs = pages[0].get("revisions", [])
        if not revs:
            return "", {}
        rev = revs[0]
        return rev.get("slots", {}).get("main", {}).get("content", ""), {
            "revision_id": rev.get("revid"),
            "parent_revision_id": rev.get("parentid"),
            "revision_timestamp_utc": rev.get("timestamp"),
            "revision_user": rev.get("user"),
            "revision_comment": rev.get("comment"),
        }

    def raw_page(self, title: str) -> str:
        raw, _meta = self.raw_page_with_metadata(title)
        return raw


def page_title(pack_code: str, item: dict) -> str:
    return f"Item:{pack_code}/{item['id'].split(':')[-1]}"


def render_deck_index(pack_code: str, items: list[dict]) -> str:
    lines = [
        f"= Deck {pack_code} =",
        "",
        "== Items ==",
    ]
    for item in items:
        title = page_title(pack_code, item)
        label = f"{item.get('headword', item.get('entry_id'))} ({item.get('entry_id')})"
        lines.append(f"* [[{title}|{label}]]")
    lines.append("")
    return "\n".join(lines)


def normalize_deck_code(value: str) -> str:
    return str(value or "").strip().replace(" ", "_").lower()


def render_main_page(pack_codes: list[str]) -> str:
    canonical_codes = sorted({code for code in (normalize_deck_code(c) for c in pack_codes) if code})
    lines = [
        "= Vocomipedia =",
        "",
        "== Decks ==",
    ]
    for code in canonical_codes:
        lines.append(f"* [[Deck:{code}|{code}]]")
    lines.extend(
        [
            "",
            "== Browse ==",
            "* [[Special:AllPages|All pages]]",
            "",
        ]
    )
    return "\n".join(lines)


def render_admin_page() -> str:
    lines = [
        "= Vocomipedia Admin =",
        "",
        "== Daily queues ==",
        "* [[Special:Moderation|Moderation queue]]",
        "* [[Special:RecentChanges|Recent changes]]",
        f"* [[Category:{SENTENCE_PROPOSAL_CATEGORY}|Sentence replacement proposals]]",
        "* [[Category:Japanese ruby needs review|Japanese ruby needs review]]",
        "",
        "== Users and roles ==",
        "* [[Special:UserRights|User rights]]",
        "* [[Special:ListUsers|List users]]",
        "* [[Special:CreateAccount|Create account]]",
        "* [[Special:Block|Block user]]",
        "* [[Special:BlockList|Blocked users]]",
        "",
        "== Safety and cleanup ==",
        "* [[Special:AbuseFilter|Abuse filters]]",
        "* [[Vocomipedia:AbuseFilter item structure|Item structure filter source]]",
        "* [[Special:AbuseLog|Abuse log]]",
        "* [[Special:SpamBlacklist|Spam blacklist]]",
        "* [[Special:Nuke|Mass delete pages]]",
        "* [[Special:Log/delete|Deletion log]]",
        "",
        "== Bot and release operations ==",
        "* [[Special:BotPasswords|Bot passwords]]",
        f"* [[Form:{ITEM_FORM}|Item edit form]]",
        f"* [[Template:{ITEM_TEMPLATE}|Item template]]",
        "* [[Special:AllPages/Item:|Item pages]]",
        "* [[Special:AllPages/Deck:|Deck pages]]",
        "",
        "== Policies ==",
        "* [[Policy:Contributor_rules|Contributor rules]]",
        "* [[Policy:Licensing|Licensing]]",
        "* [[Policy:Moderation|Moderation]]",
        "* [[Policy:Takedown|Takedown]]",
        "",
    ]
    return "\n".join(lines)


def render_sidebar_page() -> str:
    return "\n".join(
        [
            "* navigation",
            "** mainpage|mainpage-description",
            "",
            "* vocomipedia",
            "** Special:AllPages/Item:|Items",
            "** Special:AllPages/Deck:|Decks",
            "** Policy:Contributor_rules|Contributor rules",
            "",
        ]
    )


def render_item_template_page() -> str:
    lines = [
        "<noinclude>Renders the protected Vocomipedia item header. Edit through the sync tool.</noinclude><includeonly>",
        '<div class="vocomipedia-language-control" data-vocomipedia-language-control></div>',
        '<div class="vocomipedia-infobox" data-vocomipedia-item-language="{{{language|}}}">',
        '<div class="vocomipedia-infobox-title"><span class="vocomipedia-ruby-source">{{{headword_ruby|}}}</span></div>',
        "{{#if:{{{image|}}}|<div class=\"vocomipedia-infobox-image\">[[File:{{{image|}}}|frameless|280px|{{{image_caption|}}}]]<div class=\"vocomipedia-infobox-caption\">{{{image_caption|}}}</div></div>|}}",
        '<div class="vocomipedia-infobox-section">Summary</div>',
        '<div class="vocomipedia-infobox-rows">',
        '<div class="vocomipedia-infobox-row"><span>ID</span><span>{{{id|}}}</span></div>',
        '<div class="vocomipedia-infobox-row"><span>Deck</span><span>{{{pack_code|}}}</span></div>',
        '<div class="vocomipedia-infobox-row"><span>Level</span><span>{{{level|}}}</span></div>',
        '<div class="vocomipedia-infobox-row"><span>POS</span><span>{{{part_of_speech|}}}</span></div>',
        '<div class="vocomipedia-infobox-row"><span>Language</span><span>{{{language|}}}</span></div>',
        "</div>",
        '<div class="vocomipedia-infobox-section">Translations</div>',
        '<div class="vocomipedia-gloss-list">',
    ]
    for lang, label in GLOSS_LANGUAGES:
        field = gloss_field_name(lang)
        lines.append(
            f'{{{{#if:{{{{{{{field}|}}}}}}|<div class="vocomipedia-gloss-row" data-lang="{lang}" data-label="{label}"><span>{label}</span><span>{{{{{{{field}|}}}}}}</span></div>|}}}}'
        )
    lines.extend(
        [
            "</div>",
            "</div>",
            f"[[Category:{ITEM_CATEGORY}]]",
            "</includeonly>",
            "",
        ]
    )
    return "\n".join(lines)


def render_sentence_template_page() -> str:
    lines = [
        "<noinclude>Renders one editable Vocomipedia sentence block. Edit through the sync tool.</noinclude><includeonly>",
        '<div class="vocomipedia-sentence-heading" data-sentence="{{{index|}}}"><span>Sentence {{{index|}}}</span> '
        '<span class="mw-editsection">[ [{{fullurl:{{FULLPAGENAME}}|action=formedit&vocomipediaSentence={{{index|}}}&vocomipediaMode=sentence}} edit sentence] ]</span></div>',
        '<div class="vocomipedia-sentence-fields" data-sentence="{{{index|}}}">',
        '<div class="vocomipedia-sentence-row"><span>{{{target_label|Sentence}}}</span><span class="vocomipedia-sentence-target" data-sentence-index="{{{index|}}}" data-ruby-sentence="{{{ruby_sentence|no}}}"><span class="vocomipedia-ruby-target">{{#if:{{{ruby_source|}}}|{{{ruby_source|}}}|{{{japanese|}}}}}</span></span></div>',
        '<div class="vocomipedia-sentence-row vocomipedia-translation-row"><span class="vocomipedia-translation-label">Translation</span><span class="vocomipedia-translation-values">',
    ]
    for lang, label in GLOSS_LANGUAGES:
        field = translation_field_name(lang)
        lines.append(
            f'{{{{#if:{{{{{{{field}|}}}}}}|<span class="vocomipedia-translation-value" data-lang="{lang}" data-label="{label}">{{{{{{{field}|}}}}}}</span>|}}}}'
        )
    lines.extend(
        [
            '{{#if:{{{english|}}}|<span class="vocomipedia-translation-value" data-lang="en" data-label="English">{{{english|}}}</span>|}}',
            "</span></div>",
            "</div>",
            f"{{{{#if:{{{{{{proposal_japanese|}}}}}}{{{{{{proposal_english|}}}}}}{{{{{{proposal_reason|}}}}}}|[[Category:{SENTENCE_PROPOSAL_CATEGORY}]]|}}}}",
            "</includeonly>",
            "",
        ]
    )
    return "\n".join(lines)


def render_token_template_page() -> str:
    return "\n".join(
        [
            "<noinclude>Renders one editable Vocomipedia token row. Edit through the sync tool.</noinclude><includeonly>",
            '<div class="vocomipedia-token-card" data-sentence="{{{sentence|}}}">',
            '<span class="vocomipedia-token-index">{{{index|}}}</span>',
            '<span class="vocomipedia-token-display vocomipedia-ruby-source">{{{ruby|}}}</span>',
            "</div>",
            "</includeonly>",
            "",
        ]
    )


def render_item_form_page() -> str:
    lines = [
        "<noinclude>This form edits Vocomipedia item pages through stable templates. Do not add unsupported fields.</noinclude><includeonly>",
        f"{{{{{{for template|{ITEM_TEMPLATE}}}}}}}",
        "{{{field|id|hidden}}}",
        "{{{field|pack_code|hidden}}}",
        "{{{field|entry_id|hidden}}}",
        "{{{field|language|hidden}}}",
        "{{{field|image|hidden}}}",
        "{{{field|image_caption|hidden}}}",
        "{{{field|level|hidden}}}",
        "{{{field|part_of_speech|hidden}}}",
        "{| class=\"formtable vocomipedia-form-headword\"",
        "! Headword",
        "| {{{field|headword_ruby|input type=text}}}",
        "|}",
        "{| class=\"formtable vocomipedia-form-glosses\"",
        "! colspan=\"2\" | Word translations",
    ]
    for lang, label in GLOSS_LANGUAGES:
        field = gloss_field_name(lang)
        lines.extend(
            [
                "|-",
                f"! {label}",
                f"| {{{{{{field|{field}|input type=text}}}}}}",
            ]
        )
    lines.extend(
        [
            "|}",
            "{{{end template}}}",
            "",
            f"{{{{{{for template|{SENTENCE_TEMPLATE}|multiple|label=Sentences|displayed fields when minimized=ruby_source,translation_en}}}}}}",
            "{{{field|target_label|hidden}}}",
            "{{{field|ruby_sentence|hidden}}}",
            "{{{field|japanese|hidden}}}",
            "{{{field|english|hidden}}}",
            "{| class=\"formtable vocomipedia-sentence-form\"",
            "! #",
            "| {{{field|index|input type=text|size=4|restricted}}}",
            "|- class=\"vocomipedia-current-sentence-row\"",
            "! Sentence",
            "| {{{field|ruby_source|input type=textarea|rows=2}}}",
            "|- class=\"vocomipedia-current-translations-heading\"",
            "! colspan=\"2\" | Translations",
        ]
    )
    for lang, label in GLOSS_LANGUAGES:
        field = translation_field_name(lang)
        lines.extend(
            [
                "|- class=\"vocomipedia-current-translation-row\"",
                f"! {label}",
                f"| {{{{{{field|{field}|input type=textarea|rows=2}}}}}}",
            ]
        )
    lines.extend(
        [
            "|- class=\"vocomipedia-proposal-row\"",
            "! Reason",
            "| {{{field|proposal_reason|input type=textarea|rows=2}}}",
            "|}",
            "{{{end template}}}",
            "",
            "{{{standard input|summary}}}",
            "{{{standard input|minor edit}}}",
            "{{{standard input|watch}}}",
            "{{{standard input|save}}} {{{standard input|preview}}} {{{standard input|changes}}} {{{standard input|cancel}}}",
            "</includeonly>",
            "",
        ]
    )
    return "\n".join(lines)


def render_item_category_page() -> str:
    return "\n".join(
        [
            f"{{{{#default_form:{ITEM_FORM}}}}}",
            "",
            "Pages in this category are Vocomipedia item pages. Use the form editor for content changes.",
            "",
        ]
    )


def render_sentence_proposal_category_page() -> str:
    return "\n".join(
        [
            "Items in this category contain pending sentence replacement proposals captured from Vocomipedia edits.",
            "",
            "Replacement proposals are review metadata only. They do not change canonical sentences until an offline sentence-bundle regeneration applies them.",
            "",
        ]
    )


def render_structure_warning_message() -> str:
    return "Vocomipedia item structure is generated. Use Edit with form and change field values only."


def render_common_css_page() -> str:
    return "\n".join(
        [
            "/* Vocomipedia generated item pages */",
            ":root {",
            "  --vocomipedia-bg: #fff;",
            "  --vocomipedia-surface: #f8f9fa;",
            "  --vocomipedia-surface-strong: #eaecf0;",
            "  --vocomipedia-border: #a2a9b1;",
            "  --vocomipedia-border-soft: #c8ccd1;",
            "  --vocomipedia-text: #202122;",
            "  --vocomipedia-muted: #54595d;",
            "}",
            "html.skin-theme-clientpref-night,",
            "body.skin-theme-clientpref-night,",
            ".skin-theme-clientpref-night,",
            "html[data-theme='dark'],",
            "body[data-theme='dark'] {",
            "  --vocomipedia-bg: #101418;",
            "  --vocomipedia-surface: #171d23;",
            "  --vocomipedia-surface-strong: #222a32;",
            "  --vocomipedia-border: #5f6b78;",
            "  --vocomipedia-border-soft: #3d4650;",
            "  --vocomipedia-text: #f2f5f7;",
            "  --vocomipedia-muted: #b7c0ca;",
            "}",
            ".vocomipedia-infobox {",
            "  float: right;",
            "  clear: right;",
            "  width: 320px;",
            "  margin: 0 0 1em 1.4em;",
            "  border: 1px solid var(--vocomipedia-border);",
            "  background: var(--vocomipedia-surface);",
            "  color: var(--vocomipedia-text);",
            "  font-size: 90%;",
            "  line-height: 1.35;",
            "}",
            ".vocomipedia-admin-only {",
            "  display: none;",
            "}",
            ".mw-parser-output > p:has(> br:only-child) {",
            "  display: none;",
            "  margin: 0;",
            "}",
            ".vocomipedia-infobox-title {",
            "  padding: .75em .65em .5em;",
            "  text-align: center;",
            "  font-weight: 700;",
            "  font-size: 120%;",
            "  border-bottom: 1px solid var(--vocomipedia-border);",
            "  background: var(--vocomipedia-surface-strong);",
            "}",
            ".vocomipedia-scope-notice {",
            "  max-width: 720px;",
            "  margin: 0 0 1em;",
            "  padding: .65em .8em;",
            "  border-left: 3px solid var(--vocomipedia-border);",
            "  background: var(--vocomipedia-surface);",
            "  color: var(--vocomipedia-text);",
            "}",
            ".vocomipedia-scope-notice a {",
            "  margin-left: 1em;",
            "}",
            ".vocomipedia-language-control {",
            "  max-width: 720px;",
            "  margin: 0 0 1em;",
            "  display: flex;",
            "  align-items: center;",
            "  gap: .55em;",
            "  color: var(--vocomipedia-text);",
            "}",
            ".vocomipedia-language-control label {",
            "  color: var(--vocomipedia-muted);",
            "  font-weight: 700;",
            "}",
            ".vocomipedia-language-control select {",
            "  max-width: 18em;",
            "}",
            ".vocomipedia-infobox-image {",
            "  padding: 8px 8px 4px;",
            "  text-align: center;",
            "}",
            ".vocomipedia-infobox-image img {",
            "  max-width: 280px;",
            "  height: auto;",
            "  filter: none !important;",
            "}",
            ".vocomipedia-infobox-caption {",
            "  margin-top: 3px;",
            "  font-size: 92%;",
            "}",
            ".vocomipedia-infobox-section {",
            "  padding: .35em .65em;",
            "  border-top: 1px solid var(--vocomipedia-border);",
            "  border-bottom: 1px solid var(--vocomipedia-border-soft);",
            "  background: var(--vocomipedia-surface-strong);",
            "  font-weight: 700;",
            "  text-align: center;",
            "}",
            ".vocomipedia-infobox-row {",
            "  display: grid;",
            "  grid-template-columns: 7.5em 1fr;",
            "  gap: .45em;",
            "  padding: .3em .65em;",
            "  border-top: 1px solid var(--vocomipedia-border-soft);",
            "}",
            ".vocomipedia-infobox-row:first-child {",
            "  border-top: 0;",
            "}",
            ".vocomipedia-infobox-row span:first-child {",
            "  color: var(--vocomipedia-muted);",
            "  font-weight: 700;",
            "}",
            ".vocomipedia-gloss-list {",
            "  display: grid;",
            "  grid-template-columns: repeat(2, minmax(0, 1fr));",
            "  overflow: visible;",
            "}",
            ".vocomipedia-gloss-row {",
            "  min-width: 0;",
            "  padding: .25em .55em;",
            "  border-top: 1px solid var(--vocomipedia-border-soft);",
            "}",
            ".vocomipedia-gloss-row:nth-child(even) {",
            "  border-left: 1px solid var(--vocomipedia-border-soft);",
            "}",
            ".vocomipedia-gloss-row span:first-child {",
            "  display: block;",
            "  color: var(--vocomipedia-muted);",
            "  font-size: 82%;",
            "  font-weight: 700;",
            "  overflow: hidden;",
            "  text-overflow: ellipsis;",
            "  white-space: nowrap;",
            "}",
            ".vocomipedia-gloss-row span:last-child {",
            "  display: block;",
            "  overflow-wrap: anywhere;",
            "}",
            ".vocomipedia-gloss-row.is-primary {",
            "  order: -1;",
            "  grid-column: 1 / -1;",
            "  background: var(--vocomipedia-bg);",
            "}",
            ".vocomipedia-sentence-heading {",
            "  margin: .15em 0 .3em;",
            "  font-weight: 700;",
            "}",
            ".vocomipedia-sentence-fields {",
            "  max-width: 720px;",
            "  margin: .15em 0 .45em;",
            "  padding: .45em .65em;",
            "  border-left: 3px solid var(--vocomipedia-border);",
            "  background: var(--vocomipedia-surface);",
            "  color: var(--vocomipedia-text);",
            "}",
            ".vocomipedia-sentence-row {",
            "  display: grid;",
            "  grid-template-columns: 8.5em minmax(0, 1fr);",
            "  gap: .6em;",
            "  margin: .15em 0;",
            "}",
            ".vocomipedia-sentence-row span:first-child {",
            "  color: var(--vocomipedia-muted);",
            "  font-weight: 700;",
            "}",
            ".vocomipedia-sentence-target {",
            "  font-size: 112%;",
            "}",
            ".vocomipedia-translation-value {",
            "  display: block;",
            "}",
            ".vocomipedia-translation-values > p {",
            "  display: contents;",
            "  margin: 0;",
            "}",
            ".vocomipedia-translation-values > p > br {",
            "  display: none;",
            "}",
            ".vocomipedia-translation-value::before {",
            "  content: attr(data-label) ': ';",
            "  color: var(--vocomipedia-muted);",
            "  font-weight: 700;",
            "}",
            "html.vocomipedia-js .vocomipedia-translation-value {",
            "  display: none;",
            "}",
            "html.vocomipedia-js .vocomipedia-translation-value.is-selected {",
            "  display: inline;",
            "}",
            "html.vocomipedia-js .vocomipedia-translation-value.is-selected::before {",
            "  content: '';",
            "}",
            ".vocomipedia-ruby-source ruby,",
            ".vocomipedia-sentence-target ruby {",
            "  ruby-position: over;",
            "}",
            ".vocomipedia-ruby-source rt,",
            ".vocomipedia-sentence-target rt {",
            "  font-size: 58%;",
            "  font-weight: 500;",
            "  color: var(--vocomipedia-muted);",
            "}",
            ".vocomipedia-token-flow {",
            "  display: flex;",
            "  flex-wrap: wrap;",
            "  align-items: stretch;",
            "  gap: .25em;",
            "  max-width: 720px;",
            "  margin: .15em 0 .55em;",
            "}",
            ".vocomipedia-token-flow > p {",
            "  display: contents;",
            "  margin: 0;",
            "}",
            ".vocomipedia-token-flow > p > br {",
            "  display: none;",
            "}",
            ".mw-parser-output p:has(.vocomipedia-token-card) {",
            "  display: contents;",
            "  margin: 0;",
            "}",
            ".mw-parser-output p:has(.vocomipedia-token-card) br {",
            "  display: none;",
            "}",
            ".vocomipedia-token-card {",
            "  position: relative;",
            "  display: inline-flex;",
            "  flex-direction: column;",
            "  justify-content: flex-start;",
            "  min-width: 3.6em;",
            "  max-width: 12.5em;",
            "  margin: 0;",
            "  padding: .3em .5em .3em 1.35em;",
            "  border: 1px solid var(--vocomipedia-border-soft);",
            "  background: var(--vocomipedia-bg);",
            "  color: var(--vocomipedia-text);",
            "  box-sizing: border-box;",
            "  border-radius: 2px;",
            "  vertical-align: top;",
            "  font-size: 88%;",
            "  line-height: 1.28;",
            "  overflow-wrap: anywhere;",
            "}",
            ".vocomipedia-token-card > p {",
            "  display: contents;",
            "  margin: 0;",
            "}",
            ".vocomipedia-token-index {",
            "  position: absolute;",
            "  top: .35em;",
            "  left: .45em;",
            "  color: var(--vocomipedia-muted);",
            "  font-weight: 700;",
            "  font-size: 85%;",
            "}",
            ".vocomipedia-token-display {",
            "  display: block;",
            "  font-weight: 700;",
            "  font-size: 105%;",
            "  line-height: 1.1;",
            "}",
            ".vocomipedia-token-table {",
            "  display: inline-table;",
            "  width: auto;",
            "  margin: 0 .35em .35em 0 !important;",
            "  font-size: 90%;",
            "  vertical-align: top;",
            "}",
            ".vocomipedia-token-table th,",
            ".vocomipedia-token-table td {",
            "  padding: .25em .45em;",
            "}",
            "#ca-edit,",
            "#ca-ve-edit,",
            "#ca-viewsource {",
            "  display: none !important;",
            "}",
            "#t-specialpages {",
            "  display: none !important;",
            "}",
            "@media (max-width: 720px) {",
            "  .vocomipedia-infobox {",
            "    float: none;",
            "    width: auto;",
            "    margin: 0 0 1em 0;",
            "  }",
            "  .vocomipedia-gloss-list {",
            "    grid-template-columns: 1fr;",
            "  }",
            "  .vocomipedia-sentence-row,",
            "  .vocomipedia-infobox-row {",
            "    grid-template-columns: 1fr;",
            "    gap: .1em;",
            "  }",
            "}",
            "",
            "/* Page Forms: Vocomipedia item instances are generated and indexed. */",
            ".multipleTemplateInstanceTable td.instanceRearranger,",
            ".multipleTemplateInstanceTable td.instanceAddAbove,",
            ".multipleTemplateInstanceTable td.instanceRemove,",
            ".multipleTemplateWrapper .multipleTemplateAdder,",
            ".multipleTemplateWrapper > p:has(.oo-ui-buttonWidget) {",
            "  display: none !important;",
            "}",
            ".multipleTemplateInstanceTable td.instanceMain {",
            "  padding-left: 0 !important;",
            "}",
            ".multipleTemplateInstance.minimized .multipleTemplateInstanceTable {",
            "  width: 100%;",
            "  table-layout: fixed;",
            "}",
            ".multipleTemplateInstance.minimized td.fieldValuesDisplay {",
            "  white-space: normal;",
            "  overflow-wrap: anywhere;",
            "  line-height: 1.35;",
            "  padding: .45em .6em;",
            "}",
            "html.vocomipedia-js:not(.vocomipedia-scoped-sentence-edit) .vocomipedia-proposal-row {",
            "  display: none;",
            "}",
            "html.vocomipedia-scoped-sentence-edit .multipleTemplateInstance.minimized td.instanceMain,",
            "html.vocomipedia-scoped-sentence-edit .multipleTemplateInstance.minimized .instanceMain {",
            "  display: table-cell !important;",
            "  opacity: 1 !important;",
            "}",
            "html.vocomipedia-scoped-sentence-edit .multipleTemplateInstance.minimized td.fieldValuesDisplay {",
            "  display: none !important;",
            "}",
            "html.vocomipedia-scoped-sentence-edit .multipleTemplateInstance.minimized .multipleTemplateInstanceTable {",
            "  table-layout: auto;",
            "}",
            "html.vocomipedia-scoped-sentence-edit .vocomipedia-proposal-row {",
            "  display: table-row !important;",
            "}",
            ".multipleTemplateInstanceTable input[readonly],",
            ".multipleTemplateInstanceTable textarea[readonly],",
            ".multipleTemplateInstanceTable input[disabled],",
            ".multipleTemplateInstanceTable textarea[disabled] {",
            "  color: var(--vocomipedia-muted) !important;",
            "  background: var(--vocomipedia-surface) !important;",
            "}",
            "",
        ]
    )


def render_common_js_page() -> str:
    return "\n".join(
        [
            "/* Vocomipedia ruby rendering for bracket notation, e.g. 漢字[かんじ]. */",
            "(function () {",
            f"  var SUPPORTED_UI_LANGUAGES = {json.dumps([lang for lang, _label in GLOSS_LANGUAGES], ensure_ascii=False)};",
            "  function parseRubySource(source) {",
            "    var nodes = [];",
            "    var text = source || '';",
            "    var i = 0;",
            "    function isCjk(ch) {",
            "      if (!ch) return false;",
            "      var c = ch.charCodeAt(0);",
            "      return (c >= 0x3400 && c <= 0x4DBF) || (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0xF900 && c <= 0xFAFF);",
            "    }",
            "    while (i < text.length) {",
            "      var open = text.indexOf('[', i);",
            "      if (open < 0) {",
            "        if (i < text.length) nodes.push({ type: 'text', text: text.slice(i) });",
            "        break;",
            "      }",
            "      var close = text.indexOf(']', open + 1);",
            "      if (close < 0) {",
            "        nodes.push({ type: 'text', text: text.slice(i) });",
            "        break;",
            "      }",
            "      var baseStart = open - 1;",
            "      while (baseStart > i && isCjk(text.charAt(baseStart - 1))) baseStart--;",
            "      if (baseStart < i) {",
            "        nodes.push({ type: 'text', text: text.slice(i, close + 1) });",
            "        i = close + 1;",
            "        continue;",
            "      }",
            "      if (baseStart > i) nodes.push({ type: 'text', text: text.slice(i, baseStart) });",
            "      nodes.push({ type: 'ruby', base: text.slice(baseStart, open), reading: text.slice(open + 1, close) });",
            "      i = close + 1;",
            "    }",
            "    return nodes;",
            "  }",
            "",
            "  function surfaceFromRubySource(source) {",
            "    return parseRubySource(source).map(function (node) { return node.type === 'ruby' ? node.base : node.text; }).join('');",
            "  }",
            "",
            "  function renderRubySource(source, container) {",
            "    container.textContent = '';",
            "    parseRubySource(source).forEach(function (node) {",
            "      if (node.type !== 'ruby') {",
            "        container.appendChild(document.createTextNode(node.text));",
            "        return;",
            "      }",
            "      var ruby = document.createElement('ruby');",
            "      ruby.appendChild(document.createTextNode(node.base));",
            "      var rt = document.createElement('rt');",
            "      rt.textContent = node.reading;",
            "      ruby.appendChild(rt);",
            "      container.appendChild(ruby);",
            "    });",
            "  }",
            "",
            "  function sentenceRubySource(target, tokenSources) {",
            "    var out = '';",
            "    var cursor = 0;",
            "    tokenSources.forEach(function (source) {",
            "      var surface = surfaceFromRubySource(source);",
            "      if (!surface) return;",
            "      var found = target.indexOf(surface, cursor);",
            "      if (found < 0) {",
            "        out += source;",
            "        return;",
            "      }",
            "      out += target.slice(cursor, found) + source;",
            "      cursor = found + surface.length;",
            "    });",
            "    out += target.slice(cursor);",
            "    return out || target;",
            "  }",
            "",
            "  function userGroups() {",
            "    if (typeof mw === 'undefined' || !mw.config) return [];",
            "    return mw.config.get('wgUserGroups') || [];",
            "  }",
            "",
            "  function isOperator() {",
            "    var groups = userGroups();",
            "    return ['sysop', 'moderator', 'bureaucrat', 'bot'].some(function (group) {",
            "      return groups.indexOf(group) >= 0;",
            "    });",
            "  }",
            "",
            "  function hideRegularUserChrome() {",
            "    if (isOperator()) {",
            "      document.querySelectorAll('.vocomipedia-admin-only').forEach(function (el) { el.style.display = 'block'; });",
            "      return;",
            "    }",
            "    document.querySelectorAll('#ca-move').forEach(function (el) { el.remove(); });",
            "    document.querySelectorAll('#mw-panel a, .vector-sidebar-container a, .mw-portlet-navigation a').forEach(function (link) {",
            "      var text = (link.textContent || '').trim().toLowerCase();",
            "      var href = link.getAttribute('href') || '';",
            "      if (text === 'recent changes' || text === 'moderation' || text === 'admin' || text === 'special pages' || href.indexOf('Special:Moderation') >= 0 || href.indexOf('Vocomipedia:Admin') >= 0 || href.indexOf('Special:SpecialPages') >= 0) {",
            "        var row = link.closest('li') || link;",
            "        row.remove();",
            "      }",
            "    });",
            "  }",
            "",
            "  function expandPageFormsInstances(root) {",
            "    var instances = [];",
            "    if (root && root.matches && root.matches('.multipleTemplateInstance')) {",
            "      instances = [root];",
            "    } else if (root && root.querySelectorAll) {",
            "      instances = Array.prototype.slice.call(root.querySelectorAll('.multipleTemplateInstance'));",
            "    }",
            "    instances.forEach(function (instance) {",
            "      var list = instance.closest('.multipleTemplateList.minimizeAll');",
            "      if (list) list.classList.remove('minimizeAll');",
            "      instance.classList.remove('minimized');",
            "      instance.querySelectorAll('td.fieldValuesDisplay').forEach(function (cell) { cell.remove(); });",
            "      instance.querySelectorAll('td.instanceMain').forEach(function (cell) {",
            "        cell.style.display = '';",
            "        cell.style.opacity = '';",
            "      });",
            "    });",
            "    document.querySelectorAll('.multipleTemplateWrapper > p').forEach(function (row) {",
            "      if ((row.textContent || '').trim() === 'Add another') row.remove();",
            "    });",
            "  }",
            "",
            "  function arrangeTokenCards() {",
            "    document.querySelectorAll('.vocomipedia-token-flow[data-token-flow-sentence]').forEach(function (flow) {",
            "      var sentence = String(flow.getAttribute('data-token-flow-sentence') || '').trim();",
            "      if (!sentence) return;",
            "      document.querySelectorAll('.vocomipedia-token-card[data-sentence=\"' + sentence.replace(/\"/g, '\\\\\"') + '\"]').forEach(function (card) {",
            "        if (card.parentNode !== flow) flow.appendChild(card);",
            "      });",
            "    });",
            "  }",
            "",
            "  function enableEditableFormFields(root) {",
            "    (root || document).querySelectorAll('input, textarea, select').forEach(function (field) {",
            "      var name = field.getAttribute('name') || '';",
            "      var editable =",
            "        /VocomipediaItem\\[[^\\]]*(headword_ruby|gloss_)/.test(name) ||",
            "        /VocomipediaSentence\\[[^\\]]+\\]\\[(ruby_source|translation_[^\\]]+|proposal_reason)\\]/.test(name);",
            "      if (editable) {",
            "        field.disabled = false;",
            "        field.removeAttribute('disabled');",
            "        field.removeAttribute('aria-disabled');",
            "      }",
            "    });",
            "    (root || document).querySelectorAll('[name=\"wpSave\"], [name=\"wpPreview\"], [name=\"wpDiff\"]').forEach(function (button) {",
            "      button.disabled = false;",
            "      button.removeAttribute('disabled');",
            "      button.removeAttribute('aria-disabled');",
            "      var widget = button.closest('.oo-ui-widget');",
            "      if (widget) widget.classList.remove('oo-ui-widget-disabled');",
            "    });",
            "  }",
            "",
            "  function requestParam(name) {",
            "    try {",
            "      return new URLSearchParams(window.location.search).get(name);",
            "    } catch (e) {",
            "      return null;",
            "    }",
            "  }",
            "",
            "  function normalizeUiLanguage(raw) {",
            "    var code = String(raw || '').trim();",
            "    if (!code) return '';",
            "    code = code.replace(/_/g, '-');",
            "    var lower = code.toLowerCase();",
            "    var aliases = {",
            "      'zh': 'zh-Hans',",
            "      'zh-cn': 'zh-Hans',",
            "      'zh-sg': 'zh-Hans',",
            "      'zh-hans': 'zh-Hans',",
            "      'no': 'nb',",
            "      'nb-no': 'nb',",
            "      'pt-br': 'pt',",
            "      'pt-pt': 'pt'",
            "    };",
            "    if (aliases[lower]) return aliases[lower];",
            "    for (var i = 0; i < SUPPORTED_UI_LANGUAGES.length; i++) {",
            "      if (SUPPORTED_UI_LANGUAGES[i].toLowerCase() === lower) return SUPPORTED_UI_LANGUAGES[i];",
            "    }",
            "    var base = lower.split('-', 1)[0];",
            "    for (var j = 0; j < SUPPORTED_UI_LANGUAGES.length; j++) {",
            "      if (SUPPORTED_UI_LANGUAGES[j].toLowerCase() === base) return SUPPORTED_UI_LANGUAGES[j];",
            "    }",
            "    return '';",
            "  }",
            "",
            "  function availableDisplayLanguages() {",
            "    var seen = {};",
            "    var out = [];",
            "    document.querySelectorAll('.vocomipedia-translation-value[data-lang], .vocomipedia-gloss-row[data-lang]').forEach(function (el) {",
            "      var lang = normalizeUiLanguage(el.getAttribute('data-lang'));",
            "      if (!lang || seen[lang]) return;",
            "      seen[lang] = true;",
            "      out.push({ lang: lang, label: el.getAttribute('data-label') || lang });",
            "    });",
            "    out.sort(function (a, b) {",
            "      return SUPPORTED_UI_LANGUAGES.indexOf(a.lang) - SUPPORTED_UI_LANGUAGES.indexOf(b.lang);",
            "    });",
            "    return out;",
            "  }",
            "",
            "  function firstMatchingLanguage(candidates, available) {",
            "    var availableCodes = available.map(function (item) { return item.lang; });",
            "    for (var i = 0; i < candidates.length; i++) {",
            "      var lang = normalizeUiLanguage(candidates[i]);",
            "      if (lang && availableCodes.indexOf(lang) >= 0) return lang;",
            "    }",
            "    return '';",
            "  }",
            "",
            "  function preferredDisplayLanguage(available) {",
            "    var candidates = [];",
            "    candidates.push(requestParam('vocomipediaLang'));",
            "    try { candidates.push(window.localStorage.getItem('vocomipedia.uiLanguage')); } catch (e) {}",
            "    if (typeof mw !== 'undefined' && mw.config) candidates.push(mw.config.get('wgUserLanguage'));",
            "    if (navigator.languages) candidates = candidates.concat(Array.prototype.slice.call(navigator.languages));",
            "    candidates.push(navigator.language);",
            "    candidates.push(document.documentElement.getAttribute('lang'));",
            "    var matched = firstMatchingLanguage(candidates, available);",
            "    if (matched) return matched;",
            "    if (firstMatchingLanguage(['en'], available)) return 'en';",
            "    return available[0] ? available[0].lang : '';",
            "  }",
            "",
            "  function chooseLanguageElement(elements, lang) {",
            "    var fallback = null;",
            "    for (var i = 0; i < elements.length; i++) {",
            "      var itemLang = normalizeUiLanguage(elements[i].getAttribute('data-lang'));",
            "      if (itemLang === lang) return elements[i];",
            "      if (!fallback && itemLang === 'en') fallback = elements[i];",
            "      if (!fallback) fallback = elements[i];",
            "    }",
            "    return fallback;",
            "  }",
            "",
            "  function applyDisplayLanguage(lang) {",
            "    var available = availableDisplayLanguages();",
            "    if (!available.length) return;",
            "    lang = firstMatchingLanguage([lang], available) || preferredDisplayLanguage(available);",
            "    try { window.localStorage.setItem('vocomipedia.uiLanguage', lang); } catch (e) {}",
            "    document.querySelectorAll('.vocomipedia-translation-row').forEach(function (row) {",
            "      var values = Array.prototype.slice.call(row.querySelectorAll('.vocomipedia-translation-value[data-lang]'));",
            "      values.forEach(function (value) { value.classList.remove('is-selected'); });",
            "      var selected = chooseLanguageElement(values, lang);",
            "      if (!selected) return;",
            "      selected.classList.add('is-selected');",
            "      var label = row.querySelector('.vocomipedia-translation-label');",
            "      if (label) label.textContent = selected.getAttribute('data-label') || selected.getAttribute('data-lang') || 'Translation';",
            "    });",
            "    document.querySelectorAll('.vocomipedia-gloss-row').forEach(function (row) { row.classList.remove('is-primary'); });",
            "    var glossRows = Array.prototype.slice.call(document.querySelectorAll('.vocomipedia-gloss-row[data-lang]'));",
            "    var selectedGloss = chooseLanguageElement(glossRows, lang);",
            "    if (selectedGloss) selectedGloss.classList.add('is-primary');",
            "    document.querySelectorAll('[data-vocomipedia-language-select]').forEach(function (select) { select.value = lang; });",
            "  }",
            "",
            "  function initDisplayLanguageControl() {",
            "    document.documentElement.classList.add('vocomipedia-js');",
            "    var available = availableDisplayLanguages();",
            "    if (available.length <= 1) {",
            "      applyDisplayLanguage(available[0] ? available[0].lang : '');",
            "      return;",
            "    }",
            "    document.querySelectorAll('[data-vocomipedia-language-control]').forEach(function (control) {",
            "      if (control.dataset.vocomipediaLanguageReady === '1') return;",
            "      control.dataset.vocomipediaLanguageReady = '1';",
            "      var label = document.createElement('label');",
            "      label.textContent = 'Display language';",
            "      var select = document.createElement('select');",
            "      select.setAttribute('data-vocomipedia-language-select', '1');",
            "      available.forEach(function (item) {",
            "        var option = document.createElement('option');",
            "        option.value = item.lang;",
            "        option.textContent = item.label;",
            "        select.appendChild(option);",
            "      });",
            "      select.addEventListener('change', function () { applyDisplayLanguage(select.value); });",
            "      control.appendChild(label);",
            "      control.appendChild(select);",
            "    });",
            "    applyDisplayLanguage(preferredDisplayLanguage(available));",
            "  }",
            "",
            "  function fieldValue(instance, templateName, fieldName) {",
            "    var selector = '[name^=\"' + templateName + '[\"][name$=\"[' + fieldName + ']\"]';",
            "    var field = instance.querySelector(selector);",
            "    return field ? String(field.value || '').trim() : '';",
            "  }",
            "",
            "  function scopedSentenceNumber() {",
            "    var raw = requestParam('vocomipediaSentence');",
            "    if (!raw || !/^\\d+$/.test(raw)) return '';",
            "    return String(parseInt(raw, 10));",
            "  }",
            "",
            "  function scopedEditMode() {",
            "    return 'sentence';",
            "  }",
            "",
            "  function configureScopedEditableFields(root, mode) {",
            "    (root || document).querySelectorAll('input, textarea, select').forEach(function (field) {",
            "      if ((field.getAttribute('type') || '').toLowerCase() === 'hidden') return;",
            "      var name = field.getAttribute('name') || '';",
            "      var editable = /VocomipediaSentence\\[[^\\]]+\\]\\[(ruby_source|translation_[^\\]]+|proposal_reason)\\]/.test(name);",
            "      field.disabled = !editable;",
            "      if (editable) {",
            "        field.removeAttribute('disabled');",
            "        field.removeAttribute('aria-disabled');",
            "      } else {",
            "        field.setAttribute('disabled', 'disabled');",
            "        field.setAttribute('aria-disabled', 'true');",
            "      }",
            "    });",
            "  }",
            "",
            "  function fieldsetByLegend(label) {",
            "    var wanted = label.toLowerCase();",
            "    var match = null;",
            "    document.querySelectorAll('fieldset').forEach(function (fieldset) {",
            "      var legend = fieldset.querySelector('legend');",
            "      if (legend && (legend.textContent || '').trim().toLowerCase() === wanted) match = fieldset;",
            "    });",
            "    return match;",
            "  }",
            "",
            "  function applyScopedSentenceEdit() {",
            "    var sentence = scopedSentenceNumber();",
            "    if (!sentence) return;",
            "    var mode = scopedEditMode();",
            "    document.documentElement.classList.add('vocomipedia-scoped-sentence-edit');",
            "    document.querySelectorAll('.vocomipedia-form-headword, .vocomipedia-form-glosses').forEach(function (el) {",
            "      el.style.display = 'none';",
            "    });",
            "    var form = document.getElementById('pfForm') || document.querySelector('form');",
            "    if (form && !document.querySelector('.vocomipedia-scope-notice')) {",
            "      var notice = document.createElement('div');",
            "      notice.className = 'vocomipedia-scope-notice';",
            "      var title = document.createElement('strong');",
            "      title.textContent = 'Sentence ' + sentence + ' edit proposal';",
            "      var link = document.createElement('a');",
            "      var unscoped = new URL(window.location.href);",
            "      unscoped.searchParams.delete('vocomipediaSentence');",
            "      unscoped.searchParams.delete('vocomipediaMode');",
            "      link.href = unscoped.toString();",
            "      link.textContent = 'Show full item edit';",
            "      notice.appendChild(title);",
            "      notice.appendChild(document.createTextNode(' '));",
            "      notice.appendChild(link);",
            "      form.insertBefore(notice, form.firstChild);",
            "    }",
            "    var sentenceFieldset = fieldsetByLegend('Sentences');",
            "    if (sentenceFieldset) {",
            "      sentenceFieldset.querySelectorAll('.multipleTemplateInstance').forEach(function (instance) {",
            "        instance.style.display = fieldValue(instance, 'VocomipediaSentence', 'index') === sentence ? '' : 'none';",
            "        if (instance.style.display !== 'none') {",
            "          expandPageFormsInstances(instance);",
            "          enableEditableFormFields(instance);",
            "          configureScopedEditableFields(instance, mode);",
            "        }",
            "      });",
            "    }",
            "    document.querySelectorAll('.vocomipedia-sentence-heading[data-sentence], .vocomipedia-sentence-fields[data-sentence]').forEach(function (el) {",
            "      var itemSentence = String(el.getAttribute('data-sentence') || '').trim();",
            "      if (itemSentence) el.style.display = itemSentence === sentence ? '' : 'none';",
            "    });",
            "  }",
            "",
            "  function renderAll() {",
            "    var isFormEdit = !!document.getElementById('pfForm') || document.body.classList.contains('action-formedit');",
            "    document.documentElement.classList.add('vocomipedia-js');",
            "    hideRegularUserChrome();",
            "    enableEditableFormFields(document);",
            "    applyScopedSentenceEdit();",
            "    if (!isFormEdit) {",
            "      arrangeTokenCards();",
            "      initDisplayLanguageControl();",
            "    }",
            "",
            "    if (isFormEdit) return;",
            "    document.querySelectorAll('.vocomipedia-ruby-source').forEach(function (el) {",
            "      if (el.dataset.vocomipediaRubyDone === '1') return;",
            "      var source = el.getAttribute('data-ruby-source') || el.textContent || '';",
            "      el.setAttribute('data-ruby-source', source);",
            "      renderRubySource(source, el);",
            "      el.dataset.vocomipediaRubyDone = '1';",
            "    });",
            "",
            "    document.querySelectorAll('.vocomipedia-sentence-target').forEach(function (el) {",
            "      if ((el.getAttribute('data-ruby-sentence') || '').toLowerCase() !== 'yes') return;",
            "      var sourceEl = el.querySelector('.vocomipedia-ruby-target');",
            "      var source = sourceEl ? sourceEl.textContent : el.textContent;",
            "      renderRubySource(source, el);",
            "    });",
            "  }",
            "",
            "  if (document.readyState === 'loading') {",
            "    document.addEventListener('DOMContentLoaded', renderAll);",
            "  } else {",
            "    renderAll();",
            "  }",
            "  window.setTimeout(applyScopedSentenceEdit, 500);",
            "  window.setTimeout(applyScopedSentenceEdit, 1500);",
            "  window.setTimeout(arrangeTokenCards, 500);",
            "  window.setTimeout(arrangeTokenCards, 1500);",
            "  window.setTimeout(initDisplayLanguageControl, 500);",
            "  window.setTimeout(initDisplayLanguageControl, 1500);",
            "}());",
            "",
        ]
    )


def abuse_filter_rule() -> str:
    return "\n".join(
        [
            "action == 'edit'",
            "& page_namespace == 3000",
            "& !('sysop' in user_groups)",
            "& !('bot' in user_groups)",
            "& !('moderator' in user_groups)",
            "& !('automoderated' in user_groups)",
            "& (",
            f"  !(new_wikitext rlike '\\\\{{\\\\{{{ITEM_TEMPLATE}')",
            f"  | !(new_wikitext rlike '\\\\{{\\\\{{{SENTENCE_TEMPLATE}')",
            f"  | !(new_wikitext rlike '{JSON_START}')",
            ")",
        ]
    )


def render_abuse_filter_source_page() -> str:
    return "\n".join(
        [
            "= Vocomipedia item structure filter =",
            "",
            "Install this in [[Special:AbuseFilter]] with action `disallow` and warning "
            f"`MediaWiki:{STRUCTURE_WARNING_MESSAGE}`.",
            "",
            "<pre>",
            abuse_filter_rule(),
            "</pre>",
            "",
        ]
    )


def structure_pages(include_interface_pages: bool = False) -> list[tuple[str, str, str]]:
    pages = [
        (f"Template:{ITEM_TEMPLATE}", render_item_template_page(), "Sync Vocomipedia item template"),
        (f"Template:{SENTENCE_TEMPLATE}", render_sentence_template_page(), "Sync Vocomipedia sentence template"),
        (f"Template:{TOKEN_TEMPLATE}", render_token_template_page(), "Sync Vocomipedia token template"),
        (f"Form:{ITEM_FORM}", render_item_form_page(), "Sync Vocomipedia item form"),
        (f"Category:{ITEM_CATEGORY}", render_item_category_page(), "Sync Vocomipedia item category"),
        (f"Category:{SENTENCE_PROPOSAL_CATEGORY}", render_sentence_proposal_category_page(), "Sync Vocomipedia sentence proposal category"),
        ("Vocomipedia:AbuseFilter item structure", render_abuse_filter_source_page(), "Sync Vocomipedia AbuseFilter source"),
    ]
    if include_interface_pages:
        pages.append((f"MediaWiki:{STRUCTURE_WARNING_MESSAGE}", render_structure_warning_message(), "Sync Vocomipedia AbuseFilter warning"))
        pages.append(("MediaWiki:Common.css", render_common_css_page(), "Sync Vocomipedia item and form styles"))
        pages.append(("MediaWiki:Common.js", render_common_js_page(), "Sync Vocomipedia item ruby rendering"))
    return pages


def record_wiki_review(item: dict, title: str, metadata: dict, mark_approved: bool = True) -> dict:
    updated = copy.deepcopy(item)
    review = updated.setdefault("review", {})
    if mark_approved:
        review["status"] = "approved"
        review["last_reviewed_utc"] = metadata.get("revision_timestamp_utc") or utc_now()
        reviewers = review.setdefault("content_reviewers", [])
        if isinstance(reviewers, list) and "mediawiki-visible-revision" not in reviewers:
            reviewers.append("mediawiki-visible-revision")
    review["approval_source"] = "mediawiki_visible_revision"
    review["wiki"] = {
        "title": title,
        "revision_id": metadata.get("revision_id"),
        "parent_revision_id": metadata.get("parent_revision_id"),
        "revision_timestamp_utc": metadata.get("revision_timestamp_utc"),
        "revision_user": metadata.get("revision_user"),
        "revision_comment": metadata.get("revision_comment"),
        "pulled_utc": utc_now(),
    }
    if item_has_sentence_proposals(updated):
        review["status"] = "needs_review"
        review["approval_source"] = "mediawiki_visible_revision_with_sentence_proposals"
    return updated


def generate_pages(pack_dir: Path, out_dir: Path, approved_only: bool) -> int:
    manifest = load_pack_manifest(pack_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for item, _path in iter_pack_items(pack_dir, approved_only=approved_only):
        title = f"Item-{manifest['pack_code']}-{item['id'].split(':')[-1]}.wiki"
        (out_dir / title).write_text(render_item_page(item), encoding="utf-8")
        count += 1
    print(f"Wrote {count} MediaWiki page draft(s) to {out_dir}")
    return count


def push_api(
    pack_dir: Path,
    api_url: str,
    username: str,
    password: str,
    approved_only: bool,
    dry_run: bool,
    skip_index_pages: bool = False,
    admin_pages: bool = True,
    sidebar: bool = False,
    structure: bool = True,
    interface_pages: bool = False,
    entry_images: bool = True,
) -> int:
    manifest = load_pack_manifest(pack_dir)
    client = MediaWikiClient(api_url)
    if not dry_run:
        client.login(username, password)
        token = client.csrf_token()
    else:
        token = ""
    count = 0
    if structure:
        for title, text, summary in structure_pages(include_interface_pages=interface_pages):
            if dry_run:
                print(f"DRY RUN: would edit {title}")
            else:
                client.edit(title, text, summary, token)
    pushed_items: list[dict] = []
    uploaded_images = 0
    with tempfile.TemporaryDirectory(prefix="vocomipedia-entry-images.") as td:
        image_work_dir = Path(td)
        for item, _path in iter_pack_items(pack_dir, approved_only=approved_only):
            title = page_title(manifest["pack_code"], item)
            entry_image = entry_image_reference(pack_dir, item)
            if entry_images:
                prepared = prepare_entry_image(pack_dir, item, image_work_dir)
                if prepared:
                    entry_image, image_path = prepared
                    if dry_run:
                        print(f"DRY RUN: would upload File:{entry_image}")
                    else:
                        client.upload_file(entry_image, image_path, f"Sync low-res Vocomipedia entry image for {item['entry_id']}", token)
                    uploaded_images += 1
            text = render_item_page(item, entry_image=entry_image)
            if dry_run:
                print(f"DRY RUN: would edit {title}")
            else:
                client.edit(title, text, f"Sync {manifest['pack_code']} item {item['entry_id']}", token)
            count += 1
            pushed_items.append(item)
    if pushed_items and not skip_index_pages:
        deck_title = f"Deck:{manifest['pack_code']}"
        deck_text = render_deck_index(manifest["pack_code"], pushed_items)
        if dry_run:
            print(f"DRY RUN: would edit {deck_title}")
            print("DRY RUN: would edit Main Page")
        else:
            client.edit(deck_title, deck_text, f"Sync {manifest['pack_code']} deck index", token)
            deck_codes = [
                normalize_deck_code(title.split(":", 1)[1])
                for title in client.all_pages("Deck:")
                if ":" in title
            ]
            manifest_code = normalize_deck_code(manifest["pack_code"])
            if manifest_code not in deck_codes:
                deck_codes.append(manifest_code)
            main_text = render_main_page(deck_codes)
            client.edit("Main Page", main_text, "Sync Vocomipedia main index", token)
    if admin_pages:
        admin_title = "Vocomipedia:Admin"
        if dry_run:
            print(f"DRY RUN: would edit {admin_title}")
        else:
            client.edit(admin_title, render_admin_page(), "Sync Vocomipedia admin dashboard", token)
    if sidebar:
        sidebar_title = "MediaWiki:Sidebar"
        if dry_run:
            print(f"DRY RUN: would edit {sidebar_title}")
        else:
            client.edit(sidebar_title, render_sidebar_page(), "Sync Vocomipedia sidebar", token)
    image_note = f", {'would upload' if dry_run else 'uploaded'} {uploaded_images} low-res image(s)" if entry_images else ", skipped image uploads"
    print(f"{'Would push' if dry_run else 'Pushed'} {count} page(s){image_note}.")
    return count


def seed_structure_api(
    api_url: str,
    username: str,
    password: str,
    dry_run: bool,
    interface_pages: bool = False,
) -> int:
    client = MediaWikiClient(api_url)
    if not dry_run:
        client.login(username, password)
        token = client.csrf_token()
    else:
        token = ""
    pages = structure_pages(include_interface_pages=interface_pages)
    for title, text, summary in pages:
        if dry_run:
            print(f"DRY RUN: would edit {title}")
        else:
            client.edit(title, text, summary, token)
    print(f"{'Would seed' if dry_run else 'Seeded'} {len(pages)} Vocomipedia structure page(s).")
    return len(pages)


def pull_api(api_url: str, prefix: str, namespace: int | None, out_dir: Path, mark_approved: bool = True) -> int:
    client = MediaWikiClient(api_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for title in client.all_pages(prefix, namespace=namespace):
        raw, metadata = client.raw_page_with_metadata(title)
        item = extract_item_json(raw)
        if not item:
            continue
        item = record_wiki_review(item, title, metadata, mark_approved=mark_approved)
        write_json(out_dir / safe_filename(str(item["id"]), str(item.get("headword", ""))), item)
        count += 1
    print(f"Pulled {count} item JSON file(s) to {out_dir}")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate, push, or pull MediaWiki item pages for Vocomipedia.")
    sub = ap.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Generate local .wiki page drafts.")
    gen.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", metavar="DECK_DIR", required=True, type=Path)
    gen.add_argument("--out-dir", required=True, type=Path)
    gen.add_argument("--approved-only", action="store_true")

    push = sub.add_parser("push-api", help="Push canonical item pages to MediaWiki via API.")
    push.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", metavar="DECK_DIR", required=True, type=Path)
    push.add_argument("--api-url", required=True)
    push.add_argument("--username", default=os.environ.get("MEDIAWIKI_USERNAME", ""))
    push.add_argument("--password", default=os.environ.get("MEDIAWIKI_PASSWORD", ""))
    push.add_argument("--approved-only", action="store_true")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument("--skip-index-pages", action="store_true", help="Push item pages only, without Deck:/Main Page index updates.")
    push.add_argument("--skip-admin-pages", action="store_true", help="Do not update Vocomipedia:Admin.")
    push.add_argument("--skip-structure-pages", action="store_true", help="Do not update Page Forms templates/forms or structure-policy pages.")
    push.add_argument("--push-interface-pages", action="store_true", help="Also update MediaWiki: interface messages. Requires editinterface rights.")
    push.add_argument("--push-sidebar", action="store_true", help="Update MediaWiki:Sidebar. Requires editinterface rights.")
    push.add_argument("--skip-entry-images", action="store_true", help="Do not upload low-res entry images; rendered item pages still reference canonical image filenames.")

    seed = sub.add_parser("seed-structure", help="Push Page Forms templates/forms and optional interface messages only.")
    seed.add_argument("--api-url", required=True)
    seed.add_argument("--username", default=os.environ.get("MEDIAWIKI_USERNAME", ""))
    seed.add_argument("--password", default=os.environ.get("MEDIAWIKI_PASSWORD", ""))
    seed.add_argument("--dry-run", action="store_true")
    seed.add_argument("--push-interface-pages", action="store_true", help="Also update MediaWiki: interface messages. Requires editinterface rights.")

    pull = sub.add_parser("pull-api", help="Pull hidden canonical JSON blocks from MediaWiki pages.")
    pull.add_argument("--api-url", required=True)
    pull.add_argument("--prefix", required=True)
    pull.add_argument("--namespace", type=int, default=None)
    pull.add_argument("--out-dir", required=True, type=Path)
    pull.add_argument("--preserve-review-status", action="store_true", help="Do not mark pulled visible revisions as approved.")

    # Backward-compatible old flags: generate if no subcommand is supplied.
    ap.add_argument("--deck-dir", "--pack-dir", dest="pack_dir", metavar="DECK_DIR", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--approved-only", action="store_true")
    args = ap.parse_args()

    if args.cmd == "generate" or (args.cmd is None and args.pack_dir and args.out_dir):
        generate_pages(args.pack_dir, args.out_dir, args.approved_only)
        return 0
    if args.cmd == "push-api":
        if not args.dry_run and (not args.username or not args.password):
            raise SystemExit("MEDIAWIKI_USERNAME/MEDIAWIKI_PASSWORD or --username/--password are required.")
        push_api(
            args.pack_dir,
            args.api_url,
            args.username,
            args.password,
            args.approved_only,
            args.dry_run,
            args.skip_index_pages,
            admin_pages=not args.skip_admin_pages,
            sidebar=args.push_sidebar,
            structure=not args.skip_structure_pages,
            interface_pages=args.push_interface_pages,
            entry_images=not args.skip_entry_images,
        )
        return 0
    if args.cmd == "seed-structure":
        if not args.dry_run and (not args.username or not args.password):
            raise SystemExit("MEDIAWIKI_USERNAME/MEDIAWIKI_PASSWORD or --username/--password are required.")
        seed_structure_api(args.api_url, args.username, args.password, args.dry_run, interface_pages=args.push_interface_pages)
        return 0
    if args.cmd == "pull-api":
        pull_api(args.api_url, args.prefix, args.namespace, args.out_dir, mark_approved=not args.preserve_review_status)
        return 0
    ap.error("Choose a subcommand, or provide --pack-dir and --out-dir for legacy generate mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
