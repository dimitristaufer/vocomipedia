#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from sync_mediawiki import GLOSS_LANGUAGES, page_title

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / "docker" / "local" / ".env"
DEFAULT_ROOT = ROOT / "data" / "languages"
DEFAULT_COMPOSE = ROOT / "docker" / "compose.local.yml"
SEARCH_LANGUAGES = {lang for lang, _label in GLOSS_LANGUAGES}


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def sql_quote(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def normalized_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text, flags=re.UNICODE)
    return text.strip()


def collect_search_text(item: dict) -> str:
    values: list[str] = []
    for key in ["headword", "reading", "entry_id", "label", "level", "pack_code", "language"]:
        values.append(str(item.get(key) or ""))
    values.extend(str(part) for part in item.get("part_of_speech") or [])
    values.extend(str(value) for value in (item.get("glosses") or {}).values())

    for sentence in item.get("sentences") or []:
        values.append(str(sentence.get("target") or ""))
        values.append(str(sentence.get("reading") or ""))
        values.extend(str(value) for value in (sentence.get("translations") or {}).values())
        for token in sentence.get("tokens") or []:
            for key in ["surface", "lemma", "surface_en", "explanation", "pos"]:
                values.append(str(token.get(key) or ""))

    return normalized_text(" ".join(value for value in values if value))


def indexed_item(item: dict) -> dict:
    out = {
        "id": item.get("id") or "",
        "headword": item.get("headword") or "",
        "reading": item.get("reading") or "",
        "entry_id": item.get("entry_id") or "",
        "label": item.get("label") or "",
        "pack_code": item.get("pack_code") or "",
        "level": item.get("level") or "",
        "language": item.get("language") or "",
        "order": int(item.get("order") or 0),
        "part_of_speech": item.get("part_of_speech") or [],
        "glosses": {
            lang: value
            for lang, value in (item.get("glosses") or {}).items()
            if lang in SEARCH_LANGUAGES and str(value).strip()
        },
        "sentences": [],
    }
    for sentence in item.get("sentences") or []:
        out_sentence = {
            "target": sentence.get("target") or "",
            "translations": {
                lang: value
                for lang, value in (sentence.get("translations") or {}).items()
                if lang in SEARCH_LANGUAGES and str(value).strip()
            },
            "tokens": [],
        }
        for token in sentence.get("tokens") or []:
            out_sentence["tokens"].append(
                {
                    "surface": token.get("surface") or "",
                    "lemma": token.get("lemma") or "",
                    "surface_en": token.get("surface_en") or "",
                    "explanation": token.get("explanation") or "",
                }
            )
        out["sentences"].append(out_sentence)
    return out


def iter_items(root: Path):
    for pack_path in sorted(root.glob("*/*/pack.json")):
        pack_dir = pack_path.parent
        manifest = json.loads(pack_path.read_text(encoding="utf-8"))
        pack_code = str(manifest.get("pack_code") or pack_dir.name)
        for meta in manifest.get("items") or []:
            item_path = pack_dir / str(meta.get("file") or "")
            if not item_path.exists():
                continue
            item = json.loads(item_path.read_text(encoding="utf-8"))
            yield pack_code, item


def insert_statement(rows: list[tuple[str, str, str, str, str, str, str]]) -> str:
    values = []
    for title, headword, reading, entry_id, label, item_json, search_text in rows:
        values.append(
            "("
            + ",".join(
                [
                    "0",
                    sql_quote(title),
                    sql_quote(headword),
                    sql_quote(reading),
                    sql_quote(entry_id),
                    sql_quote(label),
                    sql_quote(item_json),
                    sql_quote(search_text),
                ]
            )
            + ")"
        )
    return (
        "INSERT INTO vocomipedia_search_item "
        "(vsi_page_id, vsi_page_title, vsi_headword_norm, vsi_reading_norm, vsi_entry_norm, vsi_label_norm, vsi_item_json, vsi_search_text) VALUES\n"
        + ",\n".join(values)
        + "\nON DUPLICATE KEY UPDATE "
        "vsi_page_id=VALUES(vsi_page_id), "
        "vsi_headword_norm=VALUES(vsi_headword_norm), "
        "vsi_reading_norm=VALUES(vsi_reading_norm), "
        "vsi_entry_norm=VALUES(vsi_entry_norm), "
        "vsi_label_norm=VALUES(vsi_label_norm), "
        "vsi_item_json=VALUES(vsi_item_json), "
        "vsi_search_text=VALUES(vsi_search_text);"
    )


def build_sql(root: Path, chunk_size: int, *, drop_existing: bool = True) -> tuple[str, int]:
    statements = []
    if drop_existing:
        statements.append("DROP TABLE IF EXISTS vocomipedia_search_item;")
    create_prefix = (
        "CREATE TABLE vocomipedia_search_item"
        if drop_existing
        else "CREATE TABLE IF NOT EXISTS vocomipedia_search_item"
    )
    statements.extend(
        [
            create_prefix
            + " ("
            "vsi_page_id INT UNSIGNED NOT NULL DEFAULT 0,"
            "vsi_page_title VARBINARY(255) NOT NULL,"
            "vsi_headword_norm VARBINARY(255) NOT NULL,"
            "vsi_reading_norm VARBINARY(255) NOT NULL,"
            "vsi_entry_norm VARBINARY(255) NOT NULL,"
            "vsi_label_norm VARBINARY(255) NOT NULL,"
            "vsi_item_json MEDIUMTEXT NOT NULL,"
            "vsi_search_text MEDIUMTEXT NOT NULL,"
            "PRIMARY KEY (vsi_page_title),"
            "KEY vsi_page_id (vsi_page_id),"
            "KEY vsi_headword_norm (vsi_headword_norm),"
            "KEY vsi_reading_norm (vsi_reading_norm),"
            "KEY vsi_entry_norm (vsi_entry_norm),"
            "KEY vsi_label_norm (vsi_label_norm),"
            "FULLTEXT KEY vsi_search_text_fulltext (vsi_search_text)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
        ]
    )
    chunk: list[tuple[str, str, str, str, str, str, str]] = []
    count = 0
    for pack_code, item in iter_items(root):
        item = indexed_item(item)
        title = page_title(pack_code, item).split(":", 1)[1].replace(" ", "_")
        item_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        chunk.append(
            (
                title,
                normalized_text(item.get("headword") or ""),
                normalized_text(item.get("reading") or ""),
                normalized_text(item.get("entry_id") or ""),
                normalized_text(item.get("label") or ""),
                item_json,
                collect_search_text(item),
            )
        )
        count += 1
        if len(chunk) >= chunk_size:
            statements.append(insert_statement(chunk))
            chunk = []
    if chunk:
        statements.append(insert_statement(chunk))
    return "\n".join(statements) + "\n", count


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the local MediaWiki Vocomipedia search projection table.")
    ap.add_argument("--root", default=DEFAULT_ROOT, type=Path)
    ap.add_argument("--env-file", default=DEFAULT_ENV_PATH, type=Path)
    ap.add_argument("--compose-file", default=DEFAULT_COMPOSE, type=Path)
    ap.add_argument("--chunk-size", default=200, type=int)
    ap.add_argument("--no-drop", action="store_true", help="Upsert selected rows without dropping the existing projection table.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sql, count = build_sql(args.root, args.chunk_size, drop_existing=not args.no_drop)
    if args.dry_run:
        sys.stdout.write(sql)
        print(f"-- indexed {count} item(s)", file=sys.stderr)
        return 0

    env = load_env(args.env_file)
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(args.env_file),
        "-f",
        str(args.compose_file),
        "exec",
        "-T",
        "db",
        "mariadb",
        f"-u{env.get('MW_DB_USER', 'mediawiki')}",
        f"-p{env.get('MW_DB_PASSWORD', 'mediawiki_pass')}",
        env.get("MW_DB_NAME", "mediawiki"),
    ]
    subprocess.run(cmd, cwd=ROOT, input=sql, text=True, check=True)
    print(f"Indexed {count} Vocomipedia item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
