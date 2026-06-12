#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
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
    patterns = ["*.vpack", "*.meta.json", "*.sha256"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(packs_dir.glob(pattern)))
    unique = sorted({path.resolve() for path in files})
    if not unique:
        raise SystemExit(f"No .vpack artifacts found in {packs_dir}")
    if not any(path.suffix == ".vpack" for path in unique):
        raise SystemExit(f"No .vpack files found in {packs_dir}")
    return unique


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
tar -xzf "$root/incoming/$name.tar.gz" -C "$root/incoming/$name"
rm -f "$root/incoming/$name.tar.gz"
cd "$root/incoming/$name"
if compgen -G "*.sha256" >/dev/null; then
  for checksum in *.sha256; do
    sha256sum -c "$checksum"
  done
fi
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
    ap.add_argument("--keep-releases", default=8, type=int)
    args = ap.parse_args()

    packs_dir = args.packs_dir.resolve()
    key = args.ssh_key.expanduser().resolve()
    if not packs_dir.is_dir():
        raise SystemExit(f"packs dir does not exist: {packs_dir}")
    if not key.exists():
        raise SystemExit(f"ssh key does not exist: {key}")

    name = release_name(args.release_name)
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
