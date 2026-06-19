#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / "docker" / "local" / ".env"
DEFAULT_COMPOSE_PATH = ROOT / "docker" / "compose.local.yml"


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


def run_sql(compose: list[str], env: dict[str, str], sql: str) -> str:
    cmd = [
        *compose,
        "exec",
        "-T",
        "db",
        "mariadb",
        f"-u{env.get('MW_DB_USER', 'mediawiki')}",
        f"-p{env.get('MW_DB_PASSWORD', '')}",
        "--batch",
        "--skip-column-names",
        env.get("MW_DB_NAME", "mediawiki"),
        "-e",
        sql,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"SQL failed: {' '.join(cmd)}")
    return result.stdout.strip()


def int_sql(compose: list[str], env: dict[str, str], sql: str) -> int:
    out = run_sql(compose, env, sql)
    if not out:
        return 0
    return int(out.splitlines()[-1].split("\t")[-1])


def setting_checks(local_settings: Path) -> list[dict]:
    text = local_settings.read_text(encoding="utf-8") if local_settings.exists() else ""
    checks = [
        ("local_settings_exists", local_settings.exists(), f"{local_settings} exists"),
        ("oathauth_loaded", "wfLoadExtension( 'OATHAuth' );" in text, "OATHAuth extension is loaded"),
        ("oath_required_groups", "$wgOATHRequiredForGroups" in text, "Privileged groups are configured to require 2FA"),
        ("strict_file_extensions", "$wgStrictFileExtensions = true;" in text, "Strict upload file extensions are enabled"),
        ("rate_limits_not_disabled", "$wgRateLimits = [];" not in text, "MediaWiki rate limits are not globally disabled"),
        ("bot_noratelimit", "$wgGroupPermissions['bot']['noratelimit'] = true;" in text, "Automation bot group bypasses release-scale API rate limits"),
        ("anonymous_edit_disabled", "$wgGroupPermissions['*']['edit'] = false;" in text, "Anonymous editing is disabled"),
        ("user_upload_disabled", "$wgGroupPermissions['user']['upload'] = false;" in text, "Normal users cannot upload files"),
    ]
    return [{"id": ident, "ok": bool(ok), "detail": detail} for ident, ok, detail in checks]


def audit(*, env_file: Path, compose_file: Path, local_settings: Path) -> dict:
    env = load_env(env_file)
    compose = compose_command(env_file, compose_file)
    privileged_sql = """
SELECT COUNT(DISTINCT ug_user)
FROM user_groups
WHERE ug_group IN ('sysop','bureaucrat','moderator');
"""
    privileged_with_2fa_sql = """
SELECT COUNT(DISTINCT ug.ug_user)
FROM user_groups ug
JOIN oathauth_devices od ON od.oad_user = ug.ug_user
WHERE ug.ug_group IN ('sysop','bureaucrat','moderator');
"""
    bot_sql = "SELECT COUNT(DISTINCT ug_user) FROM user_groups WHERE ug_group = 'bot';"
    out = {
        "privileged_users": int_sql(compose, env, privileged_sql),
        "privileged_users_with_2fa": int_sql(compose, env, privileged_with_2fa_sql),
        "bot_users": int_sql(compose, env, bot_sql),
        "setting_checks": setting_checks(local_settings),
    }
    out["privileged_2fa_ok"] = out["privileged_users"] > 0 and out["privileged_users"] == out["privileged_users_with_2fa"]
    out["settings_ok"] = all(check["ok"] for check in out["setting_checks"])
    out["ok"] = bool(out["privileged_2fa_ok"] and out["settings_ok"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit production MediaWiki security settings without printing secrets or usernames.")
    ap.add_argument("--env-file", default=DEFAULT_ENV_PATH, type=Path)
    ap.add_argument("--compose-file", default=DEFAULT_COMPOSE_PATH, type=Path)
    ap.add_argument("--local-settings", default=ROOT / "docker" / "local" / "LocalSettings.php", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero when any security check fails.")
    args = ap.parse_args()

    result = audit(env_file=args.env_file, compose_file=args.compose_file, local_settings=args.local_settings)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Privileged users with 2FA: {result['privileged_users_with_2fa']}/{result['privileged_users']}")
        for check in result["setting_checks"]:
            status = "ok" if check["ok"] else "FAIL"
            print(f"{status}: {check['detail']}")
    if args.strict and not result["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
