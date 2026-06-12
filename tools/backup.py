#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_backup(
    *,
    paths: Iterable[Path],
    backup_dir: Path,
    label: str,
    base_dir: Optional[Path] = None,
) -> Path:
    """
    Create a gzip tar backup before a mutating workflow.

    Missing paths are recorded in the manifest but not added to the archive.
    The archive is always created, even if every target is missing, so callers
    have a durable audit record that the backup gate ran.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    archive = backup_dir / f"{stamp}-{label}.tar.gz"
    manifest = {
        "created_utc": stamp,
        "label": label,
        "base_dir": str(base_dir.resolve()) if base_dir else None,
        "paths": [],
    }

    roots: List[Path] = [p.resolve() for p in paths]
    with tarfile.open(archive, "w:gz") as tf:
        for root in roots:
            exists = root.exists()
            manifest["paths"].append({"path": str(root), "exists": exists})
            if not exists:
                continue
            if base_dir:
                try:
                    arcname = root.relative_to(base_dir.resolve())
                except ValueError:
                    arcname = Path(root.name)
            else:
                arcname = Path(root.name)
            tf.add(root, arcname=str(arcname))
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("backup-manifest.json")
        info.size = len(payload)
        tf.addfile(info, fileobj=__import__("io").BytesIO(payload))
    return archive

