#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import dataclasses
import functools
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from japanese_ruby import (
    clean_reading,
    is_kanji,
    parse_ruby_text,
    reading_from_ruby_text,
    ruby_from_surface_reading,
    sentence_reading_from_tokens,
    token_reading_kana,
)


SPACY_MODELS = {
    "de": "de_core_news_sm",
    "fr": "fr_core_news_sm",
    "es": "es_core_news_sm",
    "zh": "zh_core_web_sm",
}


@dataclasses.dataclass
class AnalysisResult:
    language: str
    sentence: str
    tokens: List[Dict[str, Any]]
    reading: str
    analyzer: str
    warnings: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "sentence": self.sentence,
            "tokens": self.tokens,
            "reading": self.reading,
            "analyzer": self.analyzer,
            "warnings": self.warnings,
        }


class SentenceAnalyzer:
    source = "fallback_unicode"

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        raise NotImplementedError


def _is_hiragana(ch: str) -> bool:
    return "\u3040" <= ch <= "\u309f"


def _is_katakana(ch: str) -> bool:
    return "\u30a0" <= ch <= "\u30ff"


def _is_hangul(ch: str) -> bool:
    return "\uac00" <= ch <= "\ud7af" or "\u1100" <= ch <= "\u11ff" or "\u3130" <= ch <= "\u318f"


def _is_cjk(ch: str) -> bool:
    return is_kanji(ch)


def _is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in {"L", "N"} or ch in {"_", "-"}


def _script_for(language: str, ch: str) -> str:
    if ch.isspace():
        return "space"
    if _is_cjk(ch):
        return "han"
    if _is_hiragana(ch):
        return "hiragana"
    if _is_katakana(ch):
        return "katakana"
    if _is_hangul(ch):
        return "hangul"
    if _is_word_char(ch):
        return "word"
    return "punct"


def _fallback_segments(language: str, text: str) -> Iterable[tuple[str, int, int, str]]:
    i = 0
    while i < len(text):
        ch = text[i]
        script = _script_for(language, ch)
        if script == "space":
            i += 1
            continue
        start = i
        i += 1
        if script == "punct":
            yield ch, start, i, script
            continue
        if language == "ja" and script == "han":
            while i < len(text) and _script_for(language, text[i]) == "han":
                i += 1
            yield text[start:i], start, i, script
            continue
        if language == "zh" and script == "han":
            while i < len(text) and _script_for(language, text[i]) == "han":
                i += 1
            yield text[start:i], start, i, script
            continue
        while i < len(text) and _script_for(language, text[i]) == script:
            i += 1
        yield text[start:i], start, i, script


def _upos_for_script(script: str, surface: str) -> str:
    if script == "punct":
        return "PUNCT"
    if script in {"hiragana", "katakana"} and len(surface) == 1:
        return "PART"
    return "X"


class FallbackAnalyzer(SentenceAnalyzer):
    source = "fallback_unicode_rules"

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        tokens: List[Dict[str, Any]] = []
        warnings: List[str] = ["fallback analyzer used; review token boundaries before release"]
        for surface, start, end, script in _fallback_segments(language, text):
            token: Dict[str, Any] = {
                "surface": surface,
                "lemma": surface.lower() if script == "word" else surface,
                "pos": _upos_for_script(script, surface).lower(),
                "upos": _upos_for_script(script, surface),
                "xpos": "",
                "feats": {},
                "start": start,
                "end": end,
                "analyzer": self.source,
            }
            if language == "ja":
                reading = clean_reading(surface) if not any(is_kanji(ch) for ch in surface) else ""
                ruby_fields = ruby_from_surface_reading(surface, reading)
                token.update(ruby_fields)
                token["furigana"] = token_reading_kana(token)
                if any(is_kanji(ch) for ch in surface) and not reading:
                    token["ruby_confidence"] = "needs_review"
            tokens.append(token)
        reading = sentence_reading_from_tokens(text, tokens, "") if language == "ja" else ""
        return AnalysisResult(language=language, sentence=text, tokens=tokens, reading=reading, analyzer=self.source, warnings=warnings)


def _upos_from_japanese_pos(pos: Any) -> str:
    head = ""
    if isinstance(pos, (list, tuple)) and pos:
        head = str(pos[0])
    else:
        head = str(pos or "")
    mapping = {
        "名詞": "NOUN",
        "代名詞": "PRON",
        "動詞": "VERB",
        "形容詞": "ADJ",
        "形状詞": "ADJ",
        "副詞": "ADV",
        "連体詞": "DET",
        "接続詞": "CCONJ",
        "助詞": "PART",
        "助動詞": "AUX",
        "感動詞": "INTJ",
        "接頭辞": "PREFIX",
        "接尾辞": "SUFFIX",
        "補助記号": "PUNCT",
        "記号": "PUNCT",
    }
    return mapping.get(head, "X")


class SudachiAnalyzer(SentenceAnalyzer):
    def __init__(self) -> None:
        from revise_japanese_furigana import SudachiRubyAnalyzer

        self._inner = SudachiRubyAnalyzer(dict_type="core", split_mode="C")
        self.source = self._inner.source

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        tokens: List[Dict[str, Any]] = []
        for segment in self._inner.analyze(text):
            surface = str(segment.get("surface") or "")
            reading = clean_reading(str(segment.get("furigana") or ""))
            ruby_fields = ruby_from_surface_reading(surface, reading)
            pos = segment.get("pos") or []
            token: Dict[str, Any] = {
                "surface": surface,
                "lemma": segment.get("dictionary_form") or surface,
                "pos": "/".join(str(part) for part in pos if str(part)),
                "upos": _upos_from_japanese_pos(pos),
                "xpos": pos[0] if isinstance(pos, (list, tuple)) and pos else "",
                "feats": {},
                "start": segment.get("start"),
                "end": segment.get("end"),
                "analyzer": self.source,
            }
            token.update(ruby_fields)
            token["furigana"] = token_reading_kana(token)
            tokens.append(token)
        reading = sentence_reading_from_tokens(text, tokens, "")
        return AnalysisResult(language=language, sentence=text, tokens=tokens, reading=reading, analyzer=self.source, warnings=[])


def _upos_from_kiwi_tag(tag: str) -> str:
    tag = str(tag or "")
    if tag.startswith("N"):
        return "NOUN"
    if tag.startswith("V"):
        return "VERB"
    if tag.startswith("J") or tag.startswith("E"):
        return "PART"
    if tag.startswith("M"):
        return "ADV"
    if tag.startswith("S"):
        return "PUNCT"
    return "X"


class KiwiAnalyzer(SentenceAnalyzer):
    source = "kiwipiepy"

    def __init__(self) -> None:
        from kiwipiepy import Kiwi

        self._kiwi = Kiwi()

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        tokens: List[Dict[str, Any]] = []
        for token in self._kiwi.tokenize(text):
            surface = str(getattr(token, "form", "") or "")
            tag = str(getattr(token, "tag", "") or "")
            start = int(getattr(token, "start", 0) or 0)
            length = int(getattr(token, "len", len(surface)) or len(surface))
            tokens.append(
                {
                    "surface": surface,
                    "lemma": surface,
                    "pos": tag,
                    "upos": _upos_from_kiwi_tag(tag),
                    "xpos": tag,
                    "feats": {},
                    "start": start,
                    "end": start + length,
                    "analyzer": self.source,
                }
            )
        return AnalysisResult(language=language, sentence=text, tokens=tokens, reading="", analyzer=self.source, warnings=[])


class SpacyAnalyzer(SentenceAnalyzer):
    def __init__(self, model_name: str) -> None:
        import spacy

        self._nlp = spacy.load(model_name, disable=["ner"])
        self.source = f"spacy_{model_name}"

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        doc = self._nlp(text)
        tokens: List[Dict[str, Any]] = []
        for token in doc:
            if token.is_space:
                continue
            tokens.append(
                {
                    "surface": token.text,
                    "lemma": token.lemma_ or token.text,
                    "pos": token.pos_ or token.tag_ or "X",
                    "upos": token.pos_ or "X",
                    "xpos": token.tag_ or "",
                    "feats": {},
                    "start": token.idx,
                    "end": token.idx + len(token.text),
                    "analyzer": self.source,
                }
            )
        return AnalysisResult(language=language, sentence=text, tokens=tokens, reading="", analyzer=self.source, warnings=[])


class StanzaAnalyzer(SentenceAnalyzer):
    def __init__(self, language: str) -> None:
        import stanza

        self._nlp = stanza.Pipeline(lang=language, processors="tokenize,pos,lemma", use_gpu=False, verbose=False, download_method=None)
        self.source = f"stanza_{language}"

    def analyze(self, language: str, text: str, *, existing_sentence: Optional[Dict[str, Any]] = None, entry: Optional[Dict[str, Any]] = None) -> AnalysisResult:
        doc = self._nlp(text)
        tokens: List[Dict[str, Any]] = []
        for sentence in doc.sentences:
            for word in sentence.words:
                surface = str(word.text or "")
                start = text.find(surface, tokens[-1]["end"] if tokens else 0)
                if start < 0:
                    start = 0
                tokens.append(
                    {
                        "surface": surface,
                        "lemma": word.lemma or surface,
                        "pos": word.upos or "X",
                        "upos": word.upos or "X",
                        "xpos": word.xpos or "",
                        "feats": _parse_feats(word.feats),
                        "start": start,
                        "end": start + len(surface),
                        "analyzer": self.source,
                    }
                )
        return AnalysisResult(language=language, sentence=text, tokens=tokens, reading="", analyzer=self.source, warnings=[])


def _ruby_text_from_spans(surface: str, spans: List[Dict[str, Any]]) -> str:
    by_start = {int(span.get("start") or 0): span for span in spans}
    out: List[str] = []
    i = 0
    while i < len(surface):
        span = by_start.get(i)
        if span:
            base = str(span.get("base") or surface[i : i + int(span.get("length") or 1)])
            reading = clean_reading(str(span.get("reading") or ""))
            out.append(f"{base}[{reading}]" if reading else base)
            i += int(span.get("length") or len(base) or 1)
            continue
        out.append(surface[i])
        i += 1
    return "".join(out)


def apply_ruby_source_hints(result: AnalysisResult, ruby_source: str | None) -> AnalysisResult:
    if result.language != "ja" or not ruby_source:
        return result
    source_surface, source_spans = parse_ruby_text(str(ruby_source or ""))
    if not source_surface or source_surface != result.sentence:
        return result
    for token in result.tokens:
        try:
            start = int(token.get("start"))
            end = int(token.get("end"))
        except (TypeError, ValueError):
            continue
        token_spans: List[Dict[str, Any]] = []
        for span in source_spans:
            span_start = int(span.get("start") or 0)
            span_length = int(span.get("length") or 0)
            span_end = span_start + span_length
            if start <= span_start and span_end <= end:
                rel = dict(span)
                rel["start"] = span_start - start
                token_spans.append(rel)
        if not token_spans:
            continue
        surface = str(token.get("surface") or "")
        ruby_text = _ruby_text_from_spans(surface, token_spans)
        token["ruby_text"] = ruby_text
        token["ruby_spans"] = token_spans
        token["reading_kana"] = reading_from_ruby_text(ruby_text)
        token["furigana"] = token["reading_kana"]
        token["ruby_confidence"] = "reviewed"
        token["ruby_source"] = "mediawiki_sentence_ruby"
    result.reading = sentence_reading_from_tokens(result.sentence, result.tokens, result.reading)
    if "mediawiki ruby hints applied" not in result.warnings:
        result.warnings.append("mediawiki ruby hints applied")
    return result


def _parse_feats(raw: Any) -> Dict[str, str]:
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for part in str(raw).split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key] = value
    return out


@functools.lru_cache(maxsize=16)
def analyzer_for_language(language: str) -> SentenceAnalyzer:
    language = normalize_language(language)
    if language == "ja":
        try:
            return SudachiAnalyzer()
        except Exception:
            return FallbackAnalyzer()
    if language == "ko":
        try:
            return KiwiAnalyzer()
        except Exception:
            return FallbackAnalyzer()
    model = SPACY_MODELS.get(language)
    if model:
        try:
            return SpacyAnalyzer(model)
        except Exception:
            pass
    if language in {"zh", "zh-hans", "zh-hant"}:
        try:
            return StanzaAnalyzer("zh")
        except Exception:
            pass
    return FallbackAnalyzer()


def normalize_language(language: str) -> str:
    language = str(language or "").replace("_", "-").lower()
    if language.startswith("zh"):
        return "zh"
    if "-" in language:
        return language.split("-", 1)[0]
    return language


def analyze_sentence(
    language: str,
    text: str,
    *,
    existing_sentence: Optional[Dict[str, Any]] = None,
    entry: Optional[Dict[str, Any]] = None,
    ruby_source: str | None = None,
) -> AnalysisResult:
    language = normalize_language(language)
    if language == "ja" and ruby_source:
        source_surface, _spans = parse_ruby_text(str(ruby_source or ""))
        if source_surface:
            text = source_surface
    analyzer = analyzer_for_language(language)
    result = analyzer.analyze(language, str(text or ""), existing_sentence=existing_sentence, entry=entry)
    if not result.tokens and text:
        result = FallbackAnalyzer().analyze(language, str(text or ""), existing_sentence=existing_sentence, entry=entry)
    return apply_ruby_source_hints(result, ruby_source)


def generated_pos_analysis_entry(sentence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sentence": sentence.get("target", ""),
        "tokens": copy.deepcopy(sentence.get("tokens") or []),
        "difficulty_aggregated": sentence.get("difficulty"),
    }


def sync_item_pos_analysis(item: Dict[str, Any], *, regenerate: bool = False) -> Dict[str, Any]:
    if regenerate:
        language = normalize_language(str(item.get("language") or ""))
        for sentence in item.get("sentences") or []:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("target") or "")
            if not text:
                sentence["tokens"] = []
                continue
            result = analyze_sentence(language, text, existing_sentence=sentence, entry=item)
            sentence["tokens"] = result.tokens
            if result.reading:
                sentence["reading"] = result.reading
            elif language != "ja":
                sentence["reading"] = sentence.get("reading", "")
    payload = item.setdefault("app_payload", {})
    payload["pos_analysis"] = [generated_pos_analysis_entry(sentence) for sentence in item.get("sentences") or []]
    return item
