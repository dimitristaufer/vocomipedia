#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List, Tuple


HIRAGANA_START = ord("ぁ")
HIRAGANA_END = ord("ゖ")
KATAKANA_START = ord("ァ")
KATAKANA_END = ord("ヺ")


def is_kanji(ch: str) -> bool:
    if not ch:
        return False
    v = ord(ch)
    return 0x4E00 <= v <= 0x9FFF or 0x3400 <= v <= 0x4DBF or 0xF900 <= v <= 0xFAFF


def is_kana(ch: str) -> bool:
    if not ch:
        return False
    v = ord(ch)
    return HIRAGANA_START <= v <= HIRAGANA_END or KATAKANA_START <= v <= KATAKANA_END or ch == "ー"


def to_hiragana(text: str) -> str:
    out: List[str] = []
    for ch in text or "":
        v = ord(ch)
        if KATAKANA_START <= v <= KATAKANA_END:
            out.append(chr(v - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def clean_reading(text: str) -> str:
    return to_hiragana(str(text or "")).strip()


def token_reading_kana(token: Dict[str, Any]) -> str:
    for key in ("reading_kana", "furigana", "reading", "yomi"):
        value = token.get(key)
        if isinstance(value, str) and value.strip():
            return clean_reading(value)
    surface = str(token.get("surface") or "")
    if surface and all(is_kana(ch) or not is_kanji(ch) for ch in surface):
        return clean_reading(surface)
    return ""


def parse_ruby_text(ruby_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    surface: List[str] = []
    spans: List[Dict[str, Any]] = []
    i = 0
    text = ruby_text or ""
    while i < len(text):
        bracket = text.find("[", i)
        if bracket < 0:
            surface.append(text[i:])
            break
        close = text.find("]", bracket + 1)
        if close < 0:
            surface.append(text[i:])
            break
        base_start = bracket - 1
        while base_start > i and is_kanji(text[base_start - 1]):
            base_start -= 1
        if base_start < i:
            surface.append(text[i:bracket])
            surface.append(text[bracket : close + 1])
            i = close + 1
            continue
        surface.append(text[i:base_start])
        start = len("".join(surface))
        base = text[base_start:bracket]
        reading = clean_reading(text[bracket + 1 : close])
        surface.append(base)
        spans.append({"base": base, "reading": reading, "start": start, "length": len(base)})
        i = close + 1
    return "".join(surface), spans


def reading_from_ruby_text(ruby_text: str) -> str:
    surface, spans = parse_ruby_text(ruby_text)
    by_start = {int(span["start"]): span for span in spans}
    out: List[str] = []
    i = 0
    while i < len(surface):
        span = by_start.get(i)
        if span:
            out.append(str(span.get("reading") or ""))
            i += int(span.get("length") or 1)
            continue
        out.append(clean_reading(surface[i]))
        i += 1
    return "".join(out)


def ruby_from_surface_reading(surface: str, reading: str) -> Dict[str, Any]:
    surface = str(surface or "")
    reading_kana = clean_reading(reading)
    if not reading_kana:
        reading_kana = clean_reading(surface)

    if not surface or not any(is_kanji(ch) for ch in surface):
        return {
            "reading_kana": reading_kana,
            "ruby_text": surface,
            "ruby_spans": [],
            "ruby_confidence": "high",
        }

    chars = list(surface)
    spans: List[Dict[str, Any]] = []
    ruby_parts: List[str] = []
    i = 0
    j = 0
    matched_anchor_count = 0
    uncertain = False

    while i < len(chars):
        ch = chars[i]
        if not is_kanji(ch):
            ruby_parts.append(ch)
            if j < len(reading_kana) and clean_reading(ch) == reading_kana[j : j + 1]:
                j += 1
            elif ch and not is_kana(ch):
                if j < len(reading_kana) and ch == reading_kana[j : j + 1]:
                    j += 1
            i += 1
            continue

        start = i
        while i < len(chars) and is_kanji(chars[i]):
            i += 1
        base = "".join(chars[start:i])

        next_anchor = ""
        p = i
        while p < len(chars) and not is_kanji(chars[p]):
            if is_kana(chars[p]):
                next_anchor += clean_reading(chars[p])
            p += 1

        if next_anchor:
            anchor_idx = reading_kana.find(next_anchor, j)
            if anchor_idx >= 0:
                rb = reading_kana[j:anchor_idx]
                j = anchor_idx
                matched_anchor_count += 1
            else:
                rb = reading_kana[j:]
                j = len(reading_kana)
                uncertain = True
        else:
            rb = reading_kana[j:]
            j = len(reading_kana)

        if not rb:
            uncertain = True
            rb = clean_reading(base)

        ruby_parts.append(f"{base}[{rb}]")
        spans.append({"base": base, "reading": rb, "start": start, "length": len(base)})

    if uncertain:
        confidence = "needs_review"
    elif len(spans) == 1 and spans[0]["length"] > 1 and matched_anchor_count == 0:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "reading_kana": reading_kana,
        "ruby_text": "".join(ruby_parts),
        "ruby_spans": spans,
        "ruby_confidence": confidence,
    }


def normalize_japanese_token(token: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(token)
    surface = str(out.get("surface") or "")
    ruby_text = out.get("ruby_text")
    if isinstance(ruby_text, str) and ruby_text.strip():
        ruby_surface, spans = parse_ruby_text(ruby_text.strip())
        if ruby_surface:
            out["surface"] = ruby_surface
            surface = ruby_surface
        out["ruby_text"] = ruby_text.strip()
        out["ruby_spans"] = spans
        out["reading_kana"] = reading_from_ruby_text(ruby_text.strip())
        out.setdefault("ruby_confidence", "reviewed")
    else:
        fields = ruby_from_surface_reading(surface, token_reading_kana(out))
        out.update(fields)
    out["furigana"] = out.get("reading_kana", "")
    return out


def sentence_reading_from_tokens(target: str, tokens: List[Dict[str, Any]], fallback: str = "") -> str:
    target = str(target or "")
    if not target:
        return "".join(token_reading_kana(t) for t in tokens) or clean_reading(fallback)
    out: List[str] = []
    cursor = 0
    complete = True
    for token in tokens:
        surface = str(token.get("surface") or "")
        reading = token_reading_kana(token)
        if not surface:
            continue
        found = target.find(surface, cursor)
        if found < 0:
            complete = False
            out.append(reading)
            continue
        if found > cursor:
            gap = target[cursor:found]
            if any(is_kanji(ch) for ch in gap):
                complete = False
            out.append(clean_reading(gap))
        out.append(reading)
        cursor = found + len(surface)
    if cursor < len(target):
        tail = target[cursor:]
        if any(is_kanji(ch) for ch in tail):
            complete = False
        out.append(clean_reading(tail))
    derived = "".join(out).strip()
    if not complete and fallback:
        return clean_reading(fallback)
    return derived or clean_reading(fallback)


def normalize_japanese_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if str(item.get("language") or "") != "ja":
        return item
    out = dict(item)
    sentences = []
    for sentence in out.get("sentences") or []:
        s2 = dict(sentence)
        tokens = [normalize_japanese_token(t) for t in (s2.get("tokens") or []) if isinstance(t, dict)]
        s2["tokens"] = tokens
        if tokens:
            s2["reading"] = sentence_reading_from_tokens(str(s2.get("target") or ""), tokens, str(s2.get("reading") or ""))
        sentences.append(s2)
    out["sentences"] = sentences
    payload = dict(out.get("app_payload") or {})
    pos_analysis = payload.get("pos_analysis")
    if isinstance(pos_analysis, list):
        for idx, sentence in enumerate(sentences):
            if idx >= len(pos_analysis) or not isinstance(pos_analysis[idx], dict):
                continue
            pos_analysis[idx]["sentence"] = sentence.get("target", "")
            pos_analysis[idx]["tokens"] = sentence.get("tokens", [])
            if sentence.get("difficulty") is not None:
                pos_analysis[idx]["difficulty_aggregated"] = sentence.get("difficulty")
    out["app_payload"] = payload
    return out
