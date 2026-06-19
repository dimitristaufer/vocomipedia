#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / "docker" / "local" / ".env"
DEFAULT_COMPOSE_PATH = ROOT / "docker" / "compose.local.yml"
DEFAULT_BACKUP_DIR = Path("/srv/backups/vocomipedia")
DEFAULT_DB_NAME = "mediawiki"
DEFAULT_DB_USER = "mediawiki"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def compose_command(env_file: Path, compose_file: Path) -> list[str]:
    configured = os.environ.get("VOCOMIPEDIA_DOCKER_COMPOSE")
    if configured:
        compose = shlex.split(configured)
    elif shutil.which("docker"):
        compose = ["docker", "compose"]
    else:
        compose = ["docker-compose"]
    return [*compose, "--env-file", str(env_file), "-f", str(compose_file)]


def printable_cmd(cmd: list[str]) -> str:
    safe = []
    for part in cmd:
        if part.startswith("-p") and len(part) > 2:
            safe.append("-p***")
        else:
            safe.append(part)
    return " ".join(shlex.quote(part) for part in safe)


def run(cmd: list[str], *, cwd: Path = ROOT, stdin=None, stdout=None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + printable_cmd(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd), stdin=stdin, stdout=stdout, check=check, text=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_stream_to_file(cmd: list[str], dest: Path) -> None:
    with dest.open("wb") as out:
        with subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE) as proc:
            assert proc.stdout is not None
            shutil.copyfileobj(proc.stdout, out)
            code = proc.wait()
    if code:
        raise subprocess.CalledProcessError(code, cmd)


def write_gzipped_stream(cmd: list[str], dest: Path) -> None:
    with gzip.open(dest, "wb", compresslevel=6) as out:
        with subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE) as proc:
            assert proc.stdout is not None
            shutil.copyfileobj(proc.stdout, out)
            code = proc.wait()
    if code:
        raise subprocess.CalledProcessError(code, cmd)


def sql_value_count(compose: list[str], env: dict[str, str], sql: str) -> int | None:
    db_user = env.get("MW_DB_USER", DEFAULT_DB_USER)
    db_pass = env.get("MW_DB_PASSWORD", "")
    db_name = env.get("MW_DB_NAME", DEFAULT_DB_NAME)
    cmd = [
        *compose,
        "exec",
        "-T",
        "db",
        "mariadb",
        f"-u{db_user}",
        f"-p{db_pass}",
        "--batch",
        "--skip-column-names",
        db_name,
        "-e",
        sql,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode:
        return None
    try:
        return int((result.stdout.strip().splitlines() or [""])[-1])
    except ValueError:
        return None


def image_file_count(compose: list[str]) -> int | None:
    cmd = [*compose, "exec", "-T", "mediawiki", "sh", "-c", "find /var/www/html/images -type f | wc -l"]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def add_existing(tf: tarfile.TarFile, paths: Iterable[tuple[Path, str]]) -> list[dict]:
    recorded: list[dict] = []
    for path, arcname in paths:
        exists = path.exists()
        recorded.append({"path": str(path), "archive_name": arcname, "exists": exists})
        if exists:
            tf.add(path, arcname=arcname)
    return recorded


def create_backup(
    *,
    backup_dir: Path,
    env_file: Path,
    compose_file: Path,
    label: str,
    include_secrets: bool,
    latest_symlink: bool,
    keep_count: int,
) -> Path:
    env = load_env(env_file)
    compose = compose_command(env_file, compose_file)
    stamp = utc_stamp()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    bundle = backup_dir / f"{stamp}-{label}.tar.gz"

    db_user = env.get("MW_DB_USER", DEFAULT_DB_USER)
    db_pass = env.get("MW_DB_PASSWORD", "")
    db_name = env.get("MW_DB_NAME", DEFAULT_DB_NAME)

    with tempfile.TemporaryDirectory(prefix=".partial-", dir=backup_dir) as td:
        work = Path(td)
        db_dump = work / "db.sql.gz"
        images = work / "images.tar.gz"
        config = work / "config.tar.gz"

        dump_cmd = [
            *compose,
            "exec",
            "-T",
            "db",
            "mariadb-dump",
            "--single-transaction",
            "--quick",
            "--routines",
            "--events",
            f"-u{db_user}",
            f"-p{db_pass}",
            db_name,
        ]
        write_gzipped_stream(dump_cmd, db_dump)

        image_cmd = [*compose, "exec", "-T", "mediawiki", "tar", "-C", "/var/www/html", "-czf", "-", "images"]
        write_stream_to_file(image_cmd, images)

        config_members = [
            (compose_file, "docker/compose.local.yml"),
            (ROOT / "docker" / "LocalSettings.vocomipedia.php", "docker/LocalSettings.vocomipedia.php"),
            (ROOT / "docker" / "mediawiki" / "Dockerfile", "docker/mediawiki/Dockerfile"),
            (ROOT / "infra" / "nginx" / "vocomipedia-wiki.conf", "infra/nginx/vocomipedia-wiki.conf"),
            (ROOT / "infra" / "nginx" / "vocomi-packs.conf", "infra/nginx/vocomi-packs.conf"),
        ]
        if include_secrets:
            config_members.extend(
                [
                    (env_file, "docker/local/.env"),
                    (ROOT / "docker" / "local" / "LocalSettings.php", "docker/local/LocalSettings.php"),
                ]
            )
        with tarfile.open(config, "w:gz") as tf:
            config_paths = add_existing(tf, config_members)

        manifest = {
            "schema_version": "vocomipedia-mediawiki-backup-1",
            "created_utc": stamp,
            "host": socket.gethostname(),
            "label": label,
            "include_secrets": include_secrets,
            "root": str(ROOT),
            "env_file": str(env_file),
            "compose_file": str(compose_file),
            "database": {"name": db_name, "user": db_user},
            "counts": {
                "page": sql_value_count(compose, env, "SELECT COUNT(*) FROM page;"),
                "image": sql_value_count(compose, env, "SELECT COUNT(*) FROM image;"),
                "oldimage": sql_value_count(compose, env, "SELECT COUNT(*) FROM oldimage;"),
                "user": sql_value_count(compose, env, "SELECT COUNT(*) FROM user;"),
                "image_files": image_file_count(compose),
            },
            "config_paths": config_paths,
            "files": {},
        }
        for path in [db_dump, images, config]:
            manifest["files"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}

        manifest_path = work / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with tarfile.open(bundle, "w:gz") as tf:
            for path in [manifest_path, db_dump, images, config]:
                tf.add(path, arcname=path.name)
    bundle.chmod(0o600)
    verify_backup(bundle)
    if latest_symlink:
        latest = backup_dir / "latest.tar.gz"
        tmp_link = backup_dir / "latest.next"
        tmp_link.unlink(missing_ok=True)
        tmp_link.symlink_to(bundle.name)
        tmp_link.replace(latest)
    prune_backups(backup_dir, keep_count=keep_count)
    print(f"Created MediaWiki backup: {bundle}", flush=True)
    return bundle


def prune_backups(backup_dir: Path, *, keep_count: int) -> list[Path]:
    if keep_count <= 0:
        return []
    backups = sorted(
        backup_dir.glob("*-mediawiki.tar.gz"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for stale in backups[keep_count:]:
        stale.unlink()
        removed.append(stale)
    return removed


def member_sha256(tf: tarfile.TarFile, name: str) -> str:
    source = tf.extractfile(name)
    if source is None:
        raise SystemExit(f"missing backup member {name}")
    digest = hashlib.sha256()
    with source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as tf:
        names = set(tf.getnames())
        required = {"manifest.json", "db.sql.gz", "images.tar.gz", "config.tar.gz"}
        missing = required - names
        if missing:
            raise SystemExit(f"{path}: missing backup member(s): {', '.join(sorted(missing))}")
        manifest_file = tf.extractfile("manifest.json")
        if manifest_file is None:
            raise SystemExit(f"{path}: missing manifest.json")
        with manifest_file:
            manifest = json.loads(manifest_file.read().decode("utf-8"))
        if manifest.get("schema_version") != "vocomipedia-mediawiki-backup-1":
            raise SystemExit(f"{path}: unsupported backup schema")
        for name, meta in (manifest.get("files") or {}).items():
            if name not in names:
                raise SystemExit(f"{path}: manifest references missing member {name}")
            actual = member_sha256(tf, name)
            if actual != meta.get("sha256"):
                raise SystemExit(f"{path}: checksum mismatch for {name}")
        db_file = tf.extractfile("db.sql.gz")
        if db_file is None:
            raise SystemExit(f"{path}: missing db.sql.gz")
        with db_file, gzip.GzipFile(fileobj=db_file) as handle:
            handle.read(1)
        image_file = tf.extractfile("images.tar.gz")
        if image_file is None:
            raise SystemExit(f"{path}: missing images.tar.gz")
        has_images = False
        with image_file, tarfile.open(fileobj=image_file, mode="r|gz") as image_tf:
            for member in image_tf:
                if member.name == "images" or member.name.startswith("images/"):
                    has_images = True
                    break
        if not has_images:
            raise SystemExit(f"{path}: images archive does not contain images/")
        config_file = tf.extractfile("config.tar.gz")
        if config_file is None:
            raise SystemExit(f"{path}: missing config.tar.gz")
        with config_file, tarfile.open(fileobj=config_file, mode="r|gz") as config_tf:
            next(iter(config_tf), None)
    print(f"Verified MediaWiki backup: {path}", flush=True)
    return manifest


def import_database(compose: list[str], env: dict[str, str], sql_gz: Path) -> None:
    db_user = env.get("MW_DB_USER", DEFAULT_DB_USER)
    db_pass = env.get("MW_DB_PASSWORD", "")
    db_root_pass = env.get("MW_DB_ROOT_PASSWORD", "")
    db_name = env.get("MW_DB_NAME", DEFAULT_DB_NAME)
    reset_cmd = [
        *compose,
        "exec",
        "-T",
        "db",
        "mariadb",
        "-uroot",
        f"-p{db_root_pass}",
        "-e",
        f"DROP DATABASE IF EXISTS `{db_name}`; CREATE DATABASE `{db_name}` CHARACTER SET binary;",
    ]
    run(reset_cmd)
    import_cmd = [*compose, "exec", "-T", "db", "mariadb", f"-u{db_user}", f"-p{db_pass}", db_name]
    print("+ " + printable_cmd(import_cmd), flush=True)
    with subprocess.Popen(import_cmd, cwd=str(ROOT), stdin=subprocess.PIPE) as proc:
        assert proc.stdin is not None
        with gzip.open(sql_gz, "rb") as source:
            shutil.copyfileobj(source, proc.stdin)
        proc.stdin.close()
        code = proc.wait()
    if code:
        raise subprocess.CalledProcessError(code, import_cmd)


def restore_backup(
    *,
    backup: Path,
    env_file: Path,
    compose_file: Path,
    confirm: str,
    restore_config: bool,
    stop_wiki: bool,
    run_update: bool,
) -> None:
    if confirm != "RESTORE MEDIAWIKI":
        raise SystemExit("Refusing restore without --confirm 'RESTORE MEDIAWIKI'")
    verify_backup(backup)
    env = load_env(env_file)
    compose = compose_command(env_file, compose_file)

    with tempfile.TemporaryDirectory(prefix=".restore-", dir=backup.parent) as td:
        work = Path(td)
        with tarfile.open(backup, "r:gz") as tf:
            tf.extractall(work, filter="data")
        if restore_config:
            with tarfile.open(work / "config.tar.gz", "r:gz") as tf:
                tf.extractall(ROOT)
        if stop_wiki:
            run([*compose, "stop", "mediawiki"])
        import_database(compose, env, work / "db.sql.gz")
        if stop_wiki:
            run([*compose, "start", "mediawiki"])
        run([*compose, "exec", "-T", "mediawiki", "sh", "-c", "find /var/www/html/images -mindepth 1 -maxdepth 1 -exec rm -rf {} +"])
        restore_cmd = [*compose, "exec", "-T", "mediawiki", "tar", "-C", "/var/www/html", "-xzf", "-"]
        with (work / "images.tar.gz").open("rb") as source:
            run(restore_cmd, stdin=source)
        if run_update:
            run([*compose, "exec", "-T", "mediawiki", "php", "maintenance/run.php", "update", "--quick"])
    print("MediaWiki restore completed.", flush=True)


def write_systemd_units(*, service_path: Path, timer_path: Path, root: Path, backup_dir: Path, hour_utc: int) -> None:
    service = f"""[Unit]
Description=Vocomipedia MediaWiki backup
Wants=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart=/usr/bin/python3 {root}/tools/mediawiki_backup.py backup --backup-dir {backup_dir} --latest-symlink --keep-count 14
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
"""
    timer = f"""[Unit]
Description=Run Vocomipedia MediaWiki backup daily

[Timer]
OnCalendar=*-*-* {hour_utc:02d}:17:00 UTC
Persistent=true
RandomizedDelaySec=20m

[Install]
WantedBy=timers.target
"""
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")


def install_systemd(args: argparse.Namespace) -> None:
    service = Path(args.service_path)
    timer = Path(args.timer_path)
    if not args.dry_run and os.geteuid() != 0:
        raise SystemExit("install-systemd must run as root, or use --dry-run")
    if args.dry_run:
        with tempfile.TemporaryDirectory() as td:
            write_systemd_units(
                service_path=Path(td) / service.name,
                timer_path=Path(td) / timer.name,
                root=args.root,
                backup_dir=args.backup_dir,
                hour_utc=args.hour_utc,
            )
            print((Path(td) / service.name).read_text(encoding="utf-8"))
            print((Path(td) / timer.name).read_text(encoding="utf-8"))
        return
    write_systemd_units(
        service_path=service,
        timer_path=timer,
        root=args.root,
        backup_dir=args.backup_dir,
        hour_utc=args.hour_utc,
    )
    run(["systemctl", "daemon-reload"], cwd=Path("/"))
    run(["systemctl", "enable", "--now", timer.name], cwd=Path("/"))
    print(f"Installed and enabled {timer}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup, verify, and restore the Vocomipedia MediaWiki Docker stack.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    backup = sub.add_parser("backup", help="Create a MediaWiki DB/images/config backup bundle.")
    backup.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, type=Path)
    backup.add_argument("--env-file", default=DEFAULT_ENV_PATH, type=Path)
    backup.add_argument("--compose-file", default=DEFAULT_COMPOSE_PATH, type=Path)
    backup.add_argument("--label", default="mediawiki")
    backup.add_argument("--redact-secrets", action="store_true", help="Do not include docker/local/.env or generated LocalSettings.php.")
    backup.add_argument("--latest-symlink", action="store_true")
    backup.add_argument("--keep-count", default=14, type=int, help="Keep this many newest backup bundles in the backup directory.")

    verify = sub.add_parser("verify", help="Validate backup archive checksums and structure.")
    verify.add_argument("backup", type=Path)

    restore = sub.add_parser("restore", help="Restore DB/images from a backup bundle into the configured Docker stack.")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--env-file", default=DEFAULT_ENV_PATH, type=Path)
    restore.add_argument("--compose-file", default=DEFAULT_COMPOSE_PATH, type=Path)
    restore.add_argument("--confirm", default="")
    restore.add_argument("--restore-config", action="store_true")
    restore.add_argument("--no-stop-wiki", action="store_true")
    restore.add_argument("--skip-update", action="store_true")

    systemd = sub.add_parser("install-systemd", help="Install daily backup systemd unit and timer.")
    systemd.add_argument("--service-path", default="/etc/systemd/system/vocomipedia-mediawiki-backup.service")
    systemd.add_argument("--timer-path", default="/etc/systemd/system/vocomipedia-mediawiki-backup.timer")
    systemd.add_argument("--root", default=ROOT, type=Path)
    systemd.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR, type=Path)
    systemd.add_argument("--hour-utc", default=2, type=int)
    systemd.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    if args.cmd == "backup":
        create_backup(
            backup_dir=args.backup_dir,
            env_file=args.env_file,
            compose_file=args.compose_file,
            label=args.label,
            include_secrets=not args.redact_secrets,
            latest_symlink=args.latest_symlink,
            keep_count=args.keep_count,
        )
        return 0
    if args.cmd == "verify":
        verify_backup(args.backup)
        return 0
    if args.cmd == "restore":
        restore_backup(
            backup=args.backup,
            env_file=args.env_file,
            compose_file=args.compose_file,
            confirm=args.confirm,
            restore_config=args.restore_config,
            stop_wiki=not args.no_stop_wiki,
            run_update=not args.skip_update,
        )
        return 0
    if args.cmd == "install-systemd":
        install_systemd(args)
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
