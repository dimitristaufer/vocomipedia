#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def release_name(value: str | None) -> str:
    raw = value or ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    if not name:
        raise SystemExit("--release-name must contain at least one safe character")
    return name[:120]


def ssh_base(host: str, user: str, port: int, key: Path) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key),
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
    ]


def scp_base(host: str, user: str, port: int, key: Path) -> list[str]:
    return [
        "scp",
        "-i",
        str(key),
        "-P",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]


def collect_artifacts(packs_dir: Path) -> list[Path]:
    patterns = ["*.vpack", "*.meta.json", "*.sha256", "packs.json", "packs-images.json"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(packs_dir.glob(pattern)))
    unique = sorted({path.resolve() for path in files})
    if not unique:
        raise SystemExit(f"No .vpack artifacts found in {packs_dir}")
    if not any(path.suffix == ".vpack" for path in unique):
        raise SystemExit(f"No .vpack files found in {packs_dir}")
    return unique


def pack_manifest(packs_dir: Path, *, include_data: bool) -> dict:
    packs: list[dict] = []
    for meta_path in sorted(packs_dir.glob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{meta_path}: invalid JSON: {exc}") from exc
        name = str(meta.get("name") or meta_path.name.removesuffix(".meta.json") + ".vpack")
        if not re.match(r"^[A-Za-z0-9._-]+\.vpack$", name):
            raise SystemExit(f"{meta_path}: unsafe pack name {name!r}")
        if not (packs_dir / name).is_file():
            raise SystemExit(f"{meta_path}: referenced pack is missing: {name}")
        if not include_data and str(meta.get("pack_kind") or "").lower() == "data":
            continue
        meta["name"] = name
        meta["download_name"] = str(meta.get("download_name") or name)
        packs.append(meta)
    packs.sort(key=lambda item: str(item.get("version") or ""), reverse=True)
    return {
        "packs": packs,
        "server_time_utc": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "require_signed": False,
        "rate": {"max": 50, "window_sec": 3600},
    }


def write_manifest(packs_dir: Path) -> Path:
    manifest_path = packs_dir / "packs.json"
    manifest_path.write_text(
        json.dumps(pack_manifest(packs_dir, include_data=True), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (packs_dir / "packs-images.json").write_text(
        json.dumps(pack_manifest(packs_dir, include_data=False), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def make_archive(files: list[Path], packs_dir: Path, dest: Path) -> None:
    with tarfile.open(dest, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(packs_dir)))


def remote_deploy_script(root: str, name: str, keep_releases: int) -> str:
    return f"""
set -euo pipefail
root={root!r}
name={name!r}
keep={keep_releases}
umask 022
mkdir -p "$root/incoming" "$root/releases"
rm -rf "$root/incoming/$name"
mkdir -p "$root/incoming/$name"
if [ -e "$root/current" ]; then
  find -L "$root/current" -maxdepth 1 -type f \\( -name '*.vpack' -o -name '*.meta.json' -o -name '*.sha256' \\) -exec cp -al -t "$root/incoming/$name" {{}} +
fi
tar -xzf "$root/incoming/$name.tar.gz" -C "$root/incoming/$name"
rm -f "$root/incoming/$name.tar.gz"
cd "$root/incoming/$name"
rm -f packs.json packs-images.json
if compgen -G "*.sha256" >/dev/null; then
  for checksum in *.sha256; do
    if sha256sum -c "$checksum" >/dev/null 2>&1; then
      sha256sum -c "$checksum"
      continue
    fi
    target="${{checksum%.sha256}}.vpack"
    expected="$(tr -d '[:space:]' < "$checksum")"
    if ! [[ "$expected" =~ ^[0-9A-Fa-f]{{64}}$ ]]; then
      echo "$checksum: unsupported checksum format" >&2
      exit 1
    fi
    if [ ! -f "$target" ]; then
      echo "$checksum: expected artifact $target is missing" >&2
      exit 1
    fi
    actual="$(sha256sum "$target" | awk '{{print $1}}')"
    if [ "${{actual,,}}" != "${{expected,,}}" ]; then
      echo "$target: FAILED" >&2
      echo "$checksum: expected $expected, got $actual" >&2
      exit 1
    fi
    echo "$target: OK"
  done
fi
python3 - <<'PY'
import datetime as dt
import json
import re
from pathlib import Path

root = Path(".")

def build_manifest(include_data):
    packs = []
    for meta_path in sorted(root.glob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{{meta_path}}: invalid JSON: {{exc}}") from exc
        name = str(meta.get("name") or meta_path.name.removesuffix(".meta.json") + ".vpack")
        if not re.match(r"^[A-Za-z0-9._-]+\\.vpack$", name):
            raise SystemExit(f"{{meta_path}}: unsafe pack name {{name!r}}")
        if not (root / name).is_file():
            raise SystemExit(f"{{meta_path}}: referenced pack is missing: {{name}}")
        if not include_data and str(meta.get("pack_kind") or "").lower() == "data":
            continue
        meta["name"] = name
        meta["download_name"] = str(meta.get("download_name") or name)
        packs.append(meta)
    packs.sort(key=lambda item: str(item.get("version") or ""), reverse=True)
    return {{
        "packs": packs,
        "server_time_utc": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "require_signed": False,
        "rate": {{"max": 50, "window_sec": 3600}},
    }}

(root / "packs.json").write_text(
    json.dumps(build_manifest(True), ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
(root / "packs-images.json").write_text(
    json.dumps(build_manifest(False), ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
PY
find . -type f -exec chmod 0644 {{}} +
find . -type d -exec chmod 0755 {{}} +
rm -rf "$root/releases/$name"
mv "$root/incoming/$name" "$root/releases/$name"
ln -sfn "releases/$name" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
if [ "$keep" -gt 0 ]; then
  find "$root/releases" -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\\n' | sort -rn | awk -v keep="$keep" 'NR>keep {{print $2}}' | xargs -r rm -rf
fi
find "$root/current" -maxdepth 1 -type f -printf '%f\\n' | sort
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Atomically deploy built Vocomi .vpack artifacts to a VPS static pack root.")
    ap.add_argument("--packs-dir", required=True, type=Path)
    ap.add_argument("--release-name", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--port", default=22, type=int)
    ap.add_argument("--ssh-key", required=True, type=Path)
    ap.add_argument("--remote-root", default="/srv/vocomi-packs")
    ap.add_argument("--keep-releases", default=3, type=int)
    args = ap.parse_args()

    packs_dir = args.packs_dir.resolve()
    key = args.ssh_key.expanduser().resolve()
    if not packs_dir.is_dir():
        raise SystemExit(f"packs dir does not exist: {packs_dir}")
    if not key.exists():
        raise SystemExit(f"ssh key does not exist: {key}")

    name = release_name(args.release_name)
    write_manifest(packs_dir)
    files = collect_artifacts(packs_dir)
    with tempfile.TemporaryDirectory(prefix="vocomipedia-pack-deploy.") as td:
        archive = Path(td) / f"{name}.tar.gz"
        make_archive(files, packs_dir, archive)
        remote_archive = f"{args.remote_root}/incoming/{name}.tar.gz"
        run([*ssh_base(args.host, args.user, args.port, key), f"mkdir -p {args.remote_root}/incoming {args.remote_root}/releases"])
        run([*scp_base(args.host, args.user, args.port, key), str(archive), f"{args.user}@{args.host}:{remote_archive}"])
        run([*ssh_base(args.host, args.user, args.port, key), remote_deploy_script(args.remote_root, name, max(0, args.keep_releases))])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
