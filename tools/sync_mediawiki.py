#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from common import iter_pack_items, load_pack_manifest, safe_filename, write_json

JSON_START = "VOCOMIPEDIA_ITEM_JSON_START"
JSON_END = "VOCOMIPEDIA_ITEM_JSON_END"


def render_item_page(item: dict) -> str:
    canonical_json = json.dumps(item, ensure_ascii=False, indent=2)
    lines = [
        f"= {item.get('headword', item.get('entry_id'))} =",
        "",
        f"* ID: `{item.get('id')}`",
        f"* Pack: `{item.get('pack_code')}`",
        f"* Language: `{item.get('language')}`",
        f"* Review: `{(item.get('review') or {}).get('status')}`",
        "",
        "== Glosses ==",
    ]
    for lang, text in sorted((item.get("glosses") or {}).items()):
        lines.append(f"* {lang}: {text}")
    lines.extend(["", "== Sentences =="])
    for idx, sentence in enumerate(item.get("sentences") or [], start=1):
        lines.append(f"# {sentence.get('target', '')}")
        if sentence.get("reading"):
            lines.append(f"#* Reading: {sentence['reading']}")
        en = (sentence.get("translations") or {}).get("en")
        if en:
            lines.append(f"#* English: {en}")
    lines.extend(
        [
            "",
            f"<!-- {JSON_START}",
            canonical_json,
            f"{JSON_END} -->",
            "",
        ]
    )
    return "\n".join(lines)


def extract_item_json(source: str) -> dict | None:
    pattern = rf"<!--\s*{re.escape(JSON_START)}\s*(.*?)\s*{re.escape(JSON_END)}\s*-->"
    match = re.search(pattern, source, flags=re.S)
    if not match:
        return None
    return json.loads(match.group(1))


class MediaWikiClient:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, params: dict, method: str = "POST") -> dict:
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        if method == "GET":
            url = self.api_url + "?" + encoded.decode("utf-8")
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(self.api_url, data=encoded)
        with self.opener.open(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

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

    def all_pages(self, prefix: str, namespace: int = 0) -> list[str]:
        titles: list[str] = []
        cont: dict = {}
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apprefix": prefix,
                "apnamespace": str(namespace),
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

    def raw_page(self, title: str) -> str:
        resp = self.request(
            {
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "content",
                "rvslots": "main",
                "formatversion": "2",
                "format": "json",
            },
            method="GET",
        )
        pages = resp.get("query", {}).get("pages", [])
        if not pages or "missing" in pages[0]:
            return ""
        revs = pages[0].get("revisions", [])
        if not revs:
            return ""
        return revs[0].get("slots", {}).get("main", {}).get("content", "")


def page_title(pack_code: str, item: dict) -> str:
    return f"Item:{pack_code}/{item['id'].split(':')[-1]}"


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


def push_api(pack_dir: Path, api_url: str, username: str, password: str, approved_only: bool, dry_run: bool) -> int:
    manifest = load_pack_manifest(pack_dir)
    client = MediaWikiClient(api_url)
    if not dry_run:
        client.login(username, password)
        token = client.csrf_token()
    else:
        token = ""
    count = 0
    for item, _path in iter_pack_items(pack_dir, approved_only=approved_only):
        title = page_title(manifest["pack_code"], item)
        text = render_item_page(item)
        if dry_run:
            print(f"DRY RUN: would edit {title}")
        else:
            client.edit(title, text, f"Sync {manifest['pack_code']} item {item['entry_id']}", token)
        count += 1
    print(f"{'Would push' if dry_run else 'Pushed'} {count} page(s).")
    return count


def pull_api(api_url: str, prefix: str, namespace: int, out_dir: Path) -> int:
    client = MediaWikiClient(api_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for title in client.all_pages(prefix, namespace=namespace):
        raw = client.raw_page(title)
        item = extract_item_json(raw)
        if not item:
            continue
        write_json(out_dir / safe_filename(str(item["id"]), str(item.get("headword", ""))), item)
        count += 1
    print(f"Pulled {count} item JSON file(s) to {out_dir}")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate, push, or pull MediaWiki item pages for Vocomipedia.")
    sub = ap.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Generate local .wiki page drafts.")
    gen.add_argument("--pack-dir", required=True, type=Path)
    gen.add_argument("--out-dir", required=True, type=Path)
    gen.add_argument("--approved-only", action="store_true")

    push = sub.add_parser("push-api", help="Push canonical item pages to MediaWiki via API.")
    push.add_argument("--pack-dir", required=True, type=Path)
    push.add_argument("--api-url", required=True)
    push.add_argument("--username", default=os.environ.get("MEDIAWIKI_USERNAME", ""))
    push.add_argument("--password", default=os.environ.get("MEDIAWIKI_PASSWORD", ""))
    push.add_argument("--approved-only", action="store_true")
    push.add_argument("--dry-run", action="store_true")

    pull = sub.add_parser("pull-api", help="Pull hidden canonical JSON blocks from MediaWiki pages.")
    pull.add_argument("--api-url", required=True)
    pull.add_argument("--prefix", required=True)
    pull.add_argument("--namespace", type=int, default=0)
    pull.add_argument("--out-dir", required=True, type=Path)

    # Backward-compatible old flags: generate if no subcommand is supplied.
    ap.add_argument("--pack-dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--approved-only", action="store_true")
    args = ap.parse_args()

    if args.cmd == "generate" or (args.cmd is None and args.pack_dir and args.out_dir):
        generate_pages(args.pack_dir, args.out_dir, args.approved_only)
        return 0
    if args.cmd == "push-api":
        if not args.dry_run and (not args.username or not args.password):
            raise SystemExit("MEDIAWIKI_USERNAME/MEDIAWIKI_PASSWORD or --username/--password are required.")
        push_api(args.pack_dir, args.api_url, args.username, args.password, args.approved_only, args.dry_run)
        return 0
    if args.cmd == "pull-api":
        pull_api(args.api_url, args.prefix, args.namespace, args.out_dir)
        return 0
    ap.error("Choose a subcommand, or provide --pack-dir and --out-dir for legacy generate mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
