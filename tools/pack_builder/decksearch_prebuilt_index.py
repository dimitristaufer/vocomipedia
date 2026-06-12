#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build packaged DeckSearch prebuilt SQLite index for a deck.

Generated files under <source>/decksearch/:
  - decksearch.sqlite3
  - index_manifest.json

Schema (v2):
  decksearch_meta(key TEXT PRIMARY KEY, value TEXT)
  decksearch_entries(
      entry_id TEXT PRIMARY KEY,
      word TEXT,
      word_reading TEXT,
      wordtr TEXT,
      head_norm TEXT,
      reading_norm TEXT,
      translation_norm TEXT,
      body_norm TEXT
  )
  decksearch_postings(
      kind TEXT,
      token TEXT,
      ui_lang_id TEXT,  -- "" for language-agnostic postings
      entry_id TEXT,
      PRIMARY KEY(kind, token, ui_lang_id, entry_id)
  ) WITHOUT ROWID
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = 2

STOPS: Dict[str, Set[str]] = {
    "en": {"to", "a", "an", "the", "and", "or", "of", "for", "in", "on", "at", "by", "with", "without", "is", "are", "be", "been", "being"},
    "de": {"der", "die", "das", "ein", "eine", "und", "oder", "von", "fur", "in", "auf", "an", "bei", "mit", "ohne", "ist", "sind", "sein"},
    "es": {"el", "la", "los", "las", "un", "una", "y", "o", "de", "para", "en", "con", "sin", "es", "son", "ser"},
    "fr": {"le", "la", "les", "un", "une", "et", "ou", "de", "des", "pour", "en", "avec", "sans", "est", "sont", "etre"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "una", "e", "o", "di", "per", "in", "con", "senza", "sono", "essere"},
}

PUNCT_SPLIT_RE = re.compile(r"[、。．\.,;；:：\?!？！「」『』\(\)（）【】\[\]〈〉《》…—･・\-]+")
SEP_COLLAPSE_RE = re.compile(r"[ \t\n\r\-–—·‧'’_/]+")
SEP_STRIP_RE = re.compile(r"[ \-–—·‧'’_/]")
NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9 ]+")
SPLIT_PHRASES_RE = re.compile(r"[/;,、，；・]")
DB_VARIANT_RE_TEMPLATE = r"^{prefix}_{level}(?:_(?P<ui>[A-Za-z0-9\-]+))?\.db$"

_NON_UI_LIST_KEYS = {
    "jp",
    "fu",
    "png_files",
    "palette_png_files",
    "pos_analysis",
}


@dataclass
class BuiltIndexInfo:
    ui_lang_id: str
    filename: str
    source_db: str
    entry_count: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kata_to_hira_char(ch: str) -> str:
    code = ord(ch)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return ch


def katakana_to_hiragana(s: str) -> str:
    return "".join(_kata_to_hira_char(ch) for ch in s)


def _remove_diacritics(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def normalize_common(s: str) -> str:
    if not s:
        return ""
    out = unicodedata.normalize("NFKC", s)
    out = _remove_diacritics(out.casefold())
    out = katakana_to_hiragana(out)
    out = SEP_COLLAPSE_RE.sub(" ", out).strip()
    return out


def jp_to_hiragana(s: str) -> str:
    if not s:
        return ""
    out = unicodedata.normalize("NFKC", s)
    out = katakana_to_hiragana(out)
    out = out.casefold()
    return out


def strip_separators(s: str) -> str:
    return SEP_STRIP_RE.sub("", s)


def jp_headword_base(s: str) -> str:
    if not s:
        return ""
    out = s.replace("～", "").replace("〜", "")
    while out.startswith("ー"):
        out = out[1:]
    return out


def looks_latin(s: str) -> bool:
    return any(("a" <= ch <= "z") or ("A" <= ch <= "Z") for ch in s)


def is_hira_or_kata(ch: str) -> bool:
    cp = ord(ch)
    return (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF)


def kanji_stem_normalized(headword: str) -> str:
    if not headword:
        return ""
    stem = "".join(ch for ch in headword if (not is_hira_or_kata(ch) and ch not in {"ー", "～", "〜"}))
    return normalize_common(stem)


def split_phrases(s: str) -> List[str]:
    if not s:
        return []
    out: List[str] = []
    for part in SPLIT_PHRASES_RE.split(s):
        p = normalize_common(part).strip()
        if p:
            out.append(p)
    return out


def stopset(lang: str) -> Set[str]:
    return STOPS.get(lang.lower(), STOPS["en"])


def gloss_tokenize(s: str, ui_lang: str, min_length: int = 2, include_stopwords: bool = False, cap: int = 24) -> Set[str]:
    norm = normalize_common(s)
    cleaned = NON_ALNUM_SPACE_RE.sub(" ", norm)
    tokens: Set[str] = set()
    stops = set() if include_stopwords else stopset(ui_lang)
    for piece in cleaned.split(" "):
        t = piece.strip()
        if not t:
            continue
        if len(t) < max(1, min_length):
            continue
        if not include_stopwords and t in stops:
            continue
        tokens.add(t)
        if len(tokens) >= cap:
            break
    return tokens


def sentence_reading_tokens(entry: Dict, min_len: int = 2) -> Set[str]:
    out: Set[str] = set()

    def add_from(raw: str) -> None:
        hira = jp_to_hiragana(raw)
        if not hira:
            return
        hira = PUNCT_SPLIT_RE.sub(" ", hira)
        hira = re.sub(r"\s+", " ", hira).strip()
        if not hira:
            return
        for tok in hira.split(" "):
            if len(tok) >= min_len:
                out.add(tok)

    fu = entry.get("fu") if isinstance(entry.get("fu"), list) else []
    jp = entry.get("jp") if isinstance(entry.get("jp"), list) else []
    if fu:
        for s in fu:
            if isinstance(s, str):
                add_from(s)
    else:
        for s in jp:
            if isinstance(s, str):
                add_from(s)

    pos = entry.get("pos_analysis") if isinstance(entry.get("pos_analysis"), list) else []
    for panel in pos[:4]:
        if not isinstance(panel, dict):
            continue
        toks = panel.get("tokens") if isinstance(panel.get("tokens"), list) else []
        for tk in toks:
            if not isinstance(tk, dict):
                continue
            for key in ("furigana", "reading", "yomi", "dictionary_form_reading"):
                val = tk.get(key)
                if isinstance(val, str) and val:
                    hira = jp_to_hiragana(val)
                    if hira and len(hira) >= min_len:
                        out.add(hira)
                    break

    return out


def normalize_ui_lang_id(raw: str) -> str:
    return raw.strip().lower().replace("_", "-")


def _translation_list_for_ui(entry: Dict, ui_lang: str) -> List[str]:
    lang = normalize_ui_lang_id(ui_lang)
    candidates = [lang, lang.replace("-", "_")]
    for key in candidates:
        arr = entry.get(key)
        if isinstance(arr, list) and all(isinstance(item, str) for item in arr):
            return arr
    for key, value in entry.items():
        if normalize_ui_lang_id(key) != lang:
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
    return []


def _wordtr_for_ui(entry: Dict, ui_lang: str) -> str:
    lang = normalize_ui_lang_id(ui_lang)
    candidates = [f"word_{lang}", f"word_{lang.replace('-', '_')}"]
    for key in candidates:
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    for key, value in entry.items():
        if not key.startswith("word_"):
            continue
        if normalize_ui_lang_id(key[5:]) != lang:
            continue
        if isinstance(value, str) and value:
            return value
    return ""


def build_gloss_sets(entry: Dict, ui_lang: str) -> Tuple[Set[str], Set[str]]:
    lang = normalize_ui_lang_id(ui_lang)
    wordtr = _wordtr_for_ui(entry, lang)
    if not isinstance(wordtr, str):
        wordtr = entry.get("word_en") if isinstance(entry.get("word_en"), str) else ""

    gloss_head: Set[str] = set()
    for ph in split_phrases(wordtr):
        gloss_head.add(ph)
    whole = normalize_common(wordtr)
    if whole:
        gloss_head.add(whole)
    gloss_head.update(gloss_tokenize(wordtr, ui_lang=lang))

    transl = _translation_list_for_ui(entry, lang)

    gloss_sent: Set[str] = set()
    for t in transl:
        if isinstance(t, str):
            gloss_sent.update(gloss_tokenize(t, ui_lang=lang))

    return set(list(gloss_head)[:96]), set(list(gloss_sent)[:96])


def fuzzy_deletes(s: str) -> List[str]:
    if not s:
        return []
    chars = list(s)
    out: List[str] = []
    for i in range(len(chars)):
        t = chars[:i] + chars[i + 1 :]
        out.append("".join(t))
    return out


def _db_variants(source: Path, lang_prefix: str, lang_level: str) -> Dict[str, Path]:
    rx = re.compile(DB_VARIANT_RE_TEMPLATE.format(prefix=re.escape(lang_prefix), level=re.escape(lang_level)), re.IGNORECASE)
    variants: Dict[str, Path] = {}
    for p in source.glob("*.db"):
        m = rx.match(p.name)
        if not m:
            continue
        ui = m.group("ui")
        key = normalize_ui_lang_id(ui) if ui else ""
        variants[key] = p
    return variants


def _detect_entry_ui_langs(entry: Dict) -> Set[str]:
    out: Set[str] = set()
    for key, value in entry.items():
        if key.startswith("word_") and isinstance(value, str):
            lang = normalize_ui_lang_id(key[5:])
            lang_values = entry.get(lang)
            if not isinstance(lang_values, list):
                lang_values = entry.get(lang.replace("-", "_"))
            if lang and isinstance(lang_values, list) and all(isinstance(item, str) for item in lang_values):
                out.add(lang)
            continue
        if key in _NON_UI_LIST_KEYS:
            continue
        if key.endswith("_audio"):
            continue
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            lang = normalize_ui_lang_id(key)
            if lang:
                out.add(lang)
    return out


def discover_ui_lang_ids(source_db: Path) -> List[str]:
    conn = sqlite3.connect(str(source_db))
    conn.row_factory = sqlite3.Row
    langs: Set[str] = set()
    try:
        cur = conn.cursor()
        cur.execute("SELECT metadata FROM vocab")
        for row in cur:
            raw_meta = row["metadata"]
            if not raw_meta:
                continue
            try:
                obj = json.loads(raw_meta)
            except Exception:
                continue
            if isinstance(obj, dict):
                langs.update(_detect_entry_ui_langs(obj))
    finally:
        conn.close()

    if "en" not in langs:
        langs.add("en")
    return sorted(l for l in langs if l)


def _create_index_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        PRAGMA cache_size=-32768;

        DROP TABLE IF EXISTS decksearch_meta;
        DROP TABLE IF EXISTS decksearch_entries;
        DROP TABLE IF EXISTS decksearch_postings;

        CREATE TABLE decksearch_meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE decksearch_entries(
            entry_id TEXT PRIMARY KEY,
            word TEXT NOT NULL,
            word_reading TEXT NOT NULL,
            wordtr TEXT NOT NULL,
            head_norm TEXT NOT NULL,
            reading_norm TEXT NOT NULL,
            translation_norm TEXT NOT NULL,
            body_norm TEXT NOT NULL
        );

        CREATE TABLE decksearch_postings(
            kind TEXT NOT NULL,
            token TEXT NOT NULL,
            ui_lang_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            PRIMARY KEY(kind, token, ui_lang_id, entry_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_decksearch_postings_kind_token_lang
            ON decksearch_postings(kind, token, ui_lang_id);
        CREATE INDEX idx_decksearch_postings_entry_id
            ON decksearch_postings(entry_id);
        """
    )


def _insert_meta(conn: sqlite3.Connection, meta: Dict[str, str]) -> None:
    rows = list(meta.items())
    conn.executemany("INSERT INTO decksearch_meta(key, value) VALUES (?, ?)", rows)


def _pick_wordtr(entry: Dict, ui_langs: Sequence[str]) -> str:
    en = entry.get("word_en")
    if isinstance(en, str) and en:
        return en
    for ui in ui_langs:
        value = _wordtr_for_ui(entry, ui)
        if value:
            return value
    return ""


def _all_translation_strings(entry: Dict, ui_langs: Sequence[str]) -> List[str]:
    out: List[str] = []
    for ui in ui_langs:
        arr = _translation_list_for_ui(entry, ui)
        for item in arr:
            if isinstance(item, str):
                out.append(item)
    return out


def build_single_index(
    source_db: Path,
    out_db: Path,
    *,
    pack_code: str,
    pack_version: str,
    ui_lang_ids: Sequence[str],
    schema_version: int = SCHEMA_VERSION,
) -> int:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    src = sqlite3.connect(str(source_db))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(out_db))

    try:
        _create_index_schema(dst)

        meta = {
            "schema_version": str(schema_version),
            "pack_code": pack_code,
            "pack_version": pack_version,
            "ui_lang_id": "multi",
            "ui_lang_scope": "multi",
            "supported_ui_lang_ids": ",".join(ui_lang_ids),
            "created_utc": utc_now_iso(),
            "generator": "decksearch_prebuilt_index.py",
        }
        _insert_meta(dst, meta)

        entry_sql = (
            "INSERT OR REPLACE INTO decksearch_entries"
            "(entry_id, word, word_reading, wordtr, head_norm, reading_norm, translation_norm, body_norm)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        post_sql = (
            "INSERT OR IGNORE INTO decksearch_postings(kind, token, ui_lang_id, entry_id)"
            " VALUES (?, ?, ?, ?)"
        )

        cur = src.cursor()
        cur.execute("SELECT id, metadata FROM vocab")

        entry_rows: List[Tuple[str, str, str, str, str, str, str, str]] = []
        post_rows: List[Tuple[str, str, str, str]] = []

        def flush(force: bool = False) -> None:
            nonlocal entry_rows, post_rows
            if entry_rows and (force or len(entry_rows) >= 400):
                dst.executemany(entry_sql, entry_rows)
                entry_rows = []
            if post_rows and (force or len(post_rows) >= 6000):
                dst.executemany(post_sql, post_rows)
                post_rows = []

        def add_post(kind: str, token: str, entry_id: str, ui_lang_id: str = "") -> None:
            if not token:
                return
            post_rows.append((kind, token, ui_lang_id, entry_id))

        count = 0
        for row in cur:
            entry_id = row["id"]
            raw_meta = row["metadata"]
            if not entry_id or not raw_meta:
                continue
            try:
                obj = json.loads(raw_meta)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            word = obj.get("word") if isinstance(obj.get("word"), str) else ""
            if not word:
                continue
            word_reading = obj.get("word_reading") if isinstance(obj.get("word_reading"), str) else ""

            wordtr = _pick_wordtr(obj, ui_lang_ids)
            transl_all = _all_translation_strings(obj, ui_lang_ids)

            jp = obj.get("jp") if isinstance(obj.get("jp"), list) else []
            fu = obj.get("fu") if isinstance(obj.get("fu"), list) else []

            base_head = jp_headword_base(word)
            head_norm = normalize_common(base_head)
            reading_norm = normalize_common(jp_to_hiragana(word_reading))
            translation_norm = normalize_common(wordtr)

            body_parts: List[str] = [word, word_reading, wordtr]
            body_parts += [s for s in jp if isinstance(s, str)]
            body_parts += [s for s in fu if isinstance(s, str)]
            body_parts += transl_all
            body_norm = normalize_common(" ".join(body_parts))

            entry_rows.append(
                (
                    str(entry_id),
                    word,
                    word_reading,
                    wordtr,
                    head_norm,
                    reading_norm,
                    translation_norm,
                    body_norm,
                )
            )

            eid = str(entry_id)

            surfaces: Set[str] = set()
            if head_norm:
                surfaces.add(head_norm)
                stripped = strip_separators(head_norm)
                if stripped and stripped != head_norm:
                    surfaces.add(stripped)

            for srf in surfaces:
                add_post("head_exact", srf, eid, "")
                if len(srf) >= 3:
                    for l in range(3, min(4, len(srf)) + 1):
                        add_post("head_prefix", srf[:l], eid, "")

            reading_terms: Set[str] = set()
            if reading_norm:
                reading_terms.add(reading_norm)
            reading_terms.update(sentence_reading_tokens(obj, min_len=2))

            for rt in reading_terms:
                add_post("reading_exact", rt, eid, "")
                max_l = min(4, len(rt))
                for l in range(1, max_l + 1):
                    add_post("reading_prefix", rt[:l], eid, "")

            stem = kanji_stem_normalized(word)
            if stem:
                for l in range(1, min(3, len(stem)) + 1):
                    add_post("kanji_prefix", stem[:l], eid, "")

            for w in surfaces:
                if 3 <= len(w) <= 6 and looks_latin(w):
                    for d in fuzzy_deletes(w):
                        add_post("fuzzy_delete", d, eid, "")

            for ui in ui_lang_ids:
                gloss_head, gloss_sent = build_gloss_sets(obj, ui)
                for tok in gloss_head:
                    add_post("trans_token", tok, eid, ui)
                    if len(tok) >= 3:
                        for l in range(3, min(4, len(tok)) + 1):
                            add_post("trans_prefix", tok[:l], eid, ui)
                for tok in gloss_sent:
                    add_post("sent_token", tok, eid, ui)

            count += 1
            flush(False)

        flush(True)

        dst.commit()
        dst.execute("PRAGMA optimize")
        dst.execute("VACUUM")
        dst.commit()

        return count
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def build_pack_decksearch_indices(
    source: Path,
    *,
    lang_prefix: str,
    lang_level: str,
    pack_version: str,
    ui_lang_ids: Optional[Sequence[str]] = None,
    schema_version: int = SCHEMA_VERSION,
) -> Dict:
    source = source.resolve()
    pack_code = f"{lang_prefix}_{lang_level}".lower()

    variants = _db_variants(source, lang_prefix, lang_level)
    if not variants:
        raise RuntimeError(f"No deck DB variants found in {source} for {pack_code}")

    canonical_name = f"{lang_prefix}_{lang_level}.db"
    source_db = source / canonical_name
    if not source_db.exists():
        source_db = variants.get("") or variants.get("en") or variants[sorted(variants.keys())[0]]

    discovered = discover_ui_lang_ids(source_db)
    if ui_lang_ids is None:
        effective_ui_langs = discovered
    else:
        requested = [normalize_ui_lang_id(u) for u in ui_lang_ids if u and u.strip()]
        requested_set = set(requested)
        effective_ui_langs = [u for u in discovered if u in requested_set]
        if not effective_ui_langs:
            effective_ui_langs = ["en"]
    if "en" not in effective_ui_langs:
        effective_ui_langs.append("en")
    effective_ui_langs = sorted(set(effective_ui_langs))

    decksearch_dir = source / "decksearch"
    if decksearch_dir.exists():
        shutil.rmtree(decksearch_dir, ignore_errors=True)
    decksearch_dir.mkdir(parents=True, exist_ok=True)

    out_name = "decksearch.sqlite3"
    out_db = decksearch_dir / out_name
    entry_count = build_single_index(
        source_db,
        out_db,
        pack_code=pack_code,
        pack_version=pack_version,
        ui_lang_ids=effective_ui_langs,
        schema_version=schema_version,
    )
    built = [
        BuiltIndexInfo(
            ui_lang_id="multi",
            filename=f"decksearch/{out_name}",
            source_db=source_db.name,
            entry_count=entry_count,
        )
    ]

    manifest = {
        "schema_version": schema_version,
        "pack_code": pack_code,
        "pack_version": pack_version,
        "created_utc": utc_now_iso(),
        "ui_lang_scope": "multi",
        "supported_ui_lang_ids": effective_ui_langs,
        "index_count": len(built),
        "indices": [
            {
                "ui_lang_id": item.ui_lang_id,
                "filename": item.filename,
                "source_db": item.source_db,
                "entry_count": item.entry_count,
            }
            for item in built
        ],
    }

    manifest_path = decksearch_dir / "index_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return manifest
