#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import sync_mediawiki


ROOT = Path(__file__).resolve().parents[1]
DOCKER_DIR = ROOT / "docker"
LOCAL_DIR = DOCKER_DIR / "local"
ENV_PATH = LOCAL_DIR / ".env"
LOCAL_SETTINGS = LOCAL_DIR / "LocalSettings.php"


DEFAULT_ENV = {
    "MW_PORT": "8080",
    "MW_SITE_NAME": "Vocomipedia Local",
    "MW_SERVER": "http://localhost:8080",
    "MW_DB_NAME": "mediawiki",
    "MW_DB_USER": "mediawiki",
    "MW_DB_PASSWORD": "mediawiki_pass",
    "MW_DB_ROOT_PASSWORD": "mediawiki_root_pass",
    "MW_ADMIN_USER": "Admin",
    "MW_ADMIN_PASSWORD": "ChangeMeAdmin123!",
    "MW_BOT_USER": "VocomiBot",
    "MW_BOT_PASSWORD": "ChangeMeBot123!",
}


def load_env() -> dict[str, str]:
    env = dict(DEFAULT_ENV)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def ensure_env() -> dict[str, str]:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        env = dict(DEFAULT_ENV)
        env["MW_ADMIN_PASSWORD"] = "Admin-" + secrets.token_urlsafe(18)
        env["MW_BOT_PASSWORD"] = "Bot-" + secrets.token_urlsafe(18)
        text = "\n".join(f"{k}={v}" for k, v in env.items()) + "\n"
        ENV_PATH.write_text(text, encoding="utf-8")
        print(f"Created {ENV_PATH}")
    return load_env()


def compose_files(install: bool = False) -> list[str]:
    filename = "compose.local.install.yml" if install else "compose.local.yml"
    return ["docker", "compose", "--env-file", str(ENV_PATH), "-f", str(DOCKER_DIR / filename)]


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        env=env,
        input=input_text,
    )


def wait_http(url: str, timeout: int = 120) -> None:
    import urllib.request

    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def wait_db() -> None:
    run(compose_files(install=True) + ["up", "-d", "db"])
    deadline = time.time() + 120
    while time.time() < deadline:
        result = run(compose_files(install=True) + ["ps", "--format", "json", "db"], check=False, capture=True)
        if "healthy" in (result.stdout or ""):
            return
        time.sleep(2)
    raise RuntimeError("Timed out waiting for MariaDB health check")


def maintenance(
    script: str,
    args: list[str],
    *,
    install: bool = False,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    return run(
        compose_files(install=install) + ["exec", "-T", "mediawiki", "php", f"maintenance/{script}", *args],
        check=check,
        capture=capture,
    )


def install_mediawiki(env: dict[str, str], reset: bool = False) -> None:
    if reset:
        run(compose_files(install=True) + ["down", "-v"])
        if LOCAL_SETTINGS.exists():
            LOCAL_SETTINGS.unlink()

    wait_db()

    if not LOCAL_SETTINGS.exists():
        run(compose_files(install=True) + ["up", "-d", "mediawiki"])
        wait_http(env["MW_SERVER"])
        install_args = [
            "--dbtype", "mysql",
            "--dbserver", "db",
            "--dbname", env["MW_DB_NAME"],
            "--dbuser", env["MW_DB_USER"],
            "--dbpass", env["MW_DB_PASSWORD"],
            "--server", env["MW_SERVER"],
            "--scriptpath", "",
            "--pass", env["MW_ADMIN_PASSWORD"],
            "--confpath", "/tmp",
            env["MW_SITE_NAME"],
            env["MW_ADMIN_USER"],
        ]
        result = maintenance("install.php", install_args, install=True, check=False)
        if result.returncode != 0 and "already exists" not in (result.stdout or "") and "already contain" not in (result.stdout or ""):
            print(result.stdout or "", file=sys.stderr)
            raise SystemExit(result.returncode)
        run(compose_files(install=True) + ["cp", "mediawiki:/tmp/LocalSettings.php", str(LOCAL_SETTINGS)])
        append_local_settings(env)
        run(compose_files(install=True) + ["down"])

    run(compose_files() + ["up", "-d"])
    wait_http(env["MW_SERVER"])
    maintenance("update.php", ["--quick"])
    ensure_bot_user(env)
    ensure_local_structure_filter(env)
    print_summary(env)


def append_local_settings(env: dict[str, str]) -> None:
    extra = f"""

# Vocomipedia local-development settings.
$wgServer = "{env['MW_SERVER']}";
$wgMetaNamespace = "Vocomipedia";
$wgLogos = [
    '1x' => "$wgResourceBasePath/resources/assets/vocomi-logo-135.png",
    'icon' => "$wgResourceBasePath/resources/assets/vocomi-logo-135.png",
];
$wgLogo = "$wgResourceBasePath/resources/assets/vocomi-logo-135.png";
$wgEnableEmail = false;
error_reporting( E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED );

defined( 'NS_VOCOMIPEDIA_ITEM' ) || define( 'NS_VOCOMIPEDIA_ITEM', 3000 );
defined( 'NS_VOCOMIPEDIA_ITEM_TALK' ) || define( 'NS_VOCOMIPEDIA_ITEM_TALK', 3001 );
defined( 'NS_VOCOMIPEDIA_DECK' ) || define( 'NS_VOCOMIPEDIA_DECK', 3002 );
defined( 'NS_VOCOMIPEDIA_DECK_TALK' ) || define( 'NS_VOCOMIPEDIA_DECK_TALK', 3003 );
defined( 'NS_VOCOMIPEDIA_POLICY' ) || define( 'NS_VOCOMIPEDIA_POLICY', 3004 );
defined( 'NS_VOCOMIPEDIA_POLICY_TALK' ) || define( 'NS_VOCOMIPEDIA_POLICY_TALK', 3005 );

$wgExtraNamespaces[NS_VOCOMIPEDIA_ITEM] = 'Item';
$wgExtraNamespaces[NS_VOCOMIPEDIA_ITEM_TALK] = 'Item_talk';
$wgExtraNamespaces[NS_VOCOMIPEDIA_DECK] = 'Deck';
$wgExtraNamespaces[NS_VOCOMIPEDIA_DECK_TALK] = 'Deck_talk';
$wgExtraNamespaces[NS_VOCOMIPEDIA_POLICY] = 'Policy';
$wgExtraNamespaces[NS_VOCOMIPEDIA_POLICY_TALK] = 'Policy_talk';
$wgContentNamespaces[] = NS_VOCOMIPEDIA_ITEM;
$wgContentNamespaces[] = NS_VOCOMIPEDIA_DECK;
$wgContentNamespaces[] = NS_VOCOMIPEDIA_POLICY;
$wgNamespacesToBeSearchedDefault[NS_MAIN] = false;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_ITEM] = true;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_DECK] = true;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_POLICY] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_ITEM] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_ITEM_TALK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_DECK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_DECK_TALK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_POLICY] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_POLICY_TALK] = true;

$wgGroupPermissions['*']['edit'] = false;
$wgGroupPermissions['*']['createaccount'] = true;
$wgGroupPermissions['user']['edit'] = true;
$wgGroupPermissions['user']['move'] = false;
$wgGroupPermissions['user']['move-subpages'] = false;
$wgGroupPermissions['user']['movefile'] = false;
$wgGroupPermissions['bot']['bot'] = true;
$wgGroupPermissions['bot']['edit'] = true;
$wgGroupPermissions['bot']['createpage'] = true;
$wgGroupPermissions['bot']['createtalk'] = true;
$wgGroupPermissions['bot']['upload'] = true;
$wgGroupPermissions['bot']['move'] = true;
$wgGroupPermissions['bot']['editinterface'] = true;
$wgGroupPermissions['bot']['editsitecss'] = true;
$wgGroupPermissions['bot']['editsitejs'] = true;
$wgGroupPermissions['bot']['skip-moderation'] = true;
$wgGroupPermissions['bot']['skip-move-moderation'] = true;
$wgGroupPermissions['sysop']['moderation'] = true;
$wgGroupPermissions['sysop']['move'] = true;
$wgGroupPermissions['sysop']['move-subpages'] = true;
$wgGroupPermissions['sysop']['movefile'] = true;
$wgGroupPermissions['sysop']['editinterface'] = true;
$wgGroupPermissions['sysop']['editsitecss'] = true;
$wgGroupPermissions['sysop']['editsitejs'] = true;
$wgGroupPermissions['sysop']['skip-moderation'] = true;
$wgGroupPermissions['sysop']['skip-move-moderation'] = true;
$wgGroupPermissions['sysop']['abusefilter-modify'] = true;
$wgGroupPermissions['sysop']['abusefilter-view-private'] = true;
$wgGroupPermissions['sysop']['abusefilter-log-detail'] = true;
$wgGroupPermissions['sysop']['abusefilter-revert'] = true;
$wgGroupPermissions['sysop']['nuke'] = true;
$wgGroupPermissions['sysop']['deletedhistory'] = true;
$wgGroupPermissions['sysop']['deletedtext'] = true;
$wgGroupPermissions['sysop']['deleterevision'] = true;
$wgGroupPermissions['sysop']['oathauth-disable-for-user'] = true;
$wgGroupPermissions['sysop']['oathauth-view-log'] = true;
$wgGroupPermissions['automoderated']['skip-moderation'] = true;
$wgGroupPermissions['automoderated']['skip-move-moderation'] = false;
$wgGroupPermissions['automoderated']['upload'] = true;
$wgGroupPermissions['moderator']['moderation'] = true;
$wgGroupPermissions['moderator']['abusefilter-log'] = true;
$wgGroupPermissions['moderator']['abusefilter-log-detail'] = true;
$wgGroupPermissions['bureaucrat']['userrights'] = true;
$wgModerationEnable = true;
$wgModerationPreviewLink = true;
$wgLogRestrictions["newusers"] = 'moderation';
$wgMainCacheType = CACHE_NONE;
$wgEnableUploads = true;
$wgGroupPermissions['user']['upload'] = false;
$wgGroupPermissions['sysop']['upload'] = true;
$wgFileExtensions = [ 'png', 'jpg', 'jpeg', 'webp' ];
$wgRateLimits = [];

wfLoadExtension( 'AbuseFilter' );
wfLoadExtension( 'SpamBlacklist' );
wfLoadExtension( 'ConfirmEdit' );
wfLoadExtension( 'ConfirmEdit/QuestyCaptcha' );
wfLoadExtension( 'Linter' );
wfLoadExtension( 'VisualEditor' );
wfLoadExtension( 'DiscussionTools' );
wfLoadExtension( 'Nuke' );
wfLoadExtension( 'OATHAuth' );
wfLoadExtension( 'ParserFunctions' );
wfLoadExtension( 'PageForms' );
wfLoadExtension( 'VocomipediaSearch' );

if ( file_exists( "$IP/extensions/Elastica/extension.json" ) && file_exists( "$IP/extensions/CirrusSearch/extension.json" ) ) {{
    wfLoadExtension( 'Elastica' );
    wfLoadExtension( 'CirrusSearch' );
    $wgSearchType = 'CirrusSearch';
    $wgCirrusSearchServers = [ [ 'host' => 'elasticsearch', 'port' => 9200 ] ];
    $wgCirrusSearchConnectionAttempts = 3;
}}

$wgCaptchaQuestions = [
    'What app is this wiki for?' => 'Vocomi',
];
$wgCaptchaTriggers['createaccount'] = true;
$wgCaptchaTriggers['addurl'] = true;
$wgCaptchaTriggers['badlogin'] = true;
$wgCaptchaTriggers['create'] = true;
$wgCaptchaTriggers['edit'] = false;
$wgGroupPermissions['*']['viewedittab'] = true;
$wgGroupPermissions['user']['viewedittab'] = true;
$wgGroupPermissions['user']['createclass'] = false;
$wgGroupPermissions['user']['multipageedit'] = false;
$wgGroupPermissions['sysop']['createclass'] = true;
$wgGroupPermissions['sysop']['multipageedit'] = true;
$wgPageFormsRenameEditTabs = true;
$wgPageFormsRenameMainEditTab = true;

$wgHooks['SpecialPageBeforeExecute'][] = static function ( $special, $subPage ) {{
    if ( strtolower( $special->getName() ) !== 'specialpages' ) {{
        return true;
    }}
    $groups = \\MediaWiki\\MediaWikiServices::getInstance()
        ->getUserGroupManager()
        ->getUserEffectiveGroups( $special->getUser() );
    if ( array_intersect( [ 'sysop', 'moderator', 'bureaucrat', 'bot' ], $groups ) ) {{
        return true;
    }}
    $out = $special->getOutput();
    $out->setStatusCode( 403 );
    $out->showErrorPage( 'permissionserrors', 'badaccess' );
    return false;
}};

# Must be loaded last: the extension intercepts save hooks.
wfLoadExtension( 'Moderation' );
"""
    LOCAL_SETTINGS.write_text(LOCAL_SETTINGS.read_text(encoding="utf-8") + extra, encoding="utf-8")


def ensure_bot_user(env: dict[str, str]) -> None:
    result = maintenance("createAndPromote.php", [
        "--force",
        "--custom-groups", "bot",
        env["MW_BOT_USER"],
        env["MW_BOT_PASSWORD"],
    ], check=False)
    output = result.stdout or ""
    if result.returncode != 0 and "already exists" not in output:
        print(output, file=sys.stderr)
        raise SystemExit(result.returncode)


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def php_serialize_disallow_action(message_key: str) -> str:
    return f'a:1:{{s:8:"disallow";a:1:{{i:0;s:{len(message_key)}:"{message_key}";}}}}'


def ensure_local_structure_filter(env: dict[str, str]) -> None:
    public_comment = "Vocomipedia item structure guard"
    message_key = sync_mediawiki.STRUCTURE_WARNING_MESSAGE
    pattern = sync_mediawiki.abuse_filter_rule()
    actions = php_serialize_disallow_action(message_key)
    sql = f"""
SET @public_comment := {sql_quote(public_comment)};
SET @pattern := {sql_quote(pattern)};
SET @message_key := {sql_quote(message_key)};
SET @history_actions := {sql_quote(actions)};
SET @actor_id := (SELECT actor_id FROM actor WHERE actor_name = {sql_quote(env['MW_ADMIN_USER'])} ORDER BY actor_id LIMIT 1);
DELETE afa FROM abuse_filter_action afa JOIN abuse_filter af ON af.af_id = afa.afa_filter WHERE af.af_public_comments = @public_comment;
DELETE FROM abuse_filter_history WHERE afh_public_comments = @public_comment;
DELETE FROM abuse_filter WHERE af_public_comments = @public_comment;
INSERT INTO abuse_filter (
    af_pattern, af_actor, af_timestamp, af_enabled, af_comments, af_public_comments,
    af_hidden, af_hit_count, af_throttled, af_deleted, af_actions, af_global, af_group
) VALUES (
    @pattern, COALESCE(@actor_id, 0), DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s'), 1,
    'Installed by vocomipedia/tools/local_mediawiki.py', @public_comment,
    0, 0, 0, 0, 'disallow', 0, 'default'
);
SET @filter_id := LAST_INSERT_ID();
INSERT INTO abuse_filter_action (afa_filter, afa_consequence, afa_parameters)
VALUES (@filter_id, 'disallow', @message_key);
INSERT INTO abuse_filter_history (
    afh_filter, afh_actor, afh_timestamp, afh_pattern, afh_comments, afh_flags,
    afh_public_comments, afh_actions, afh_deleted, afh_changed_fields, afh_group
) VALUES (
    @filter_id, COALESCE(@actor_id, 0), DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s'),
    @pattern, 'Installed by vocomipedia/tools/local_mediawiki.py', 'enabled',
    @public_comment, @history_actions, 0, 'new', 'default'
);
"""
    run(
        compose_files()
        + [
            "exec",
            "-T",
            "db",
            "mariadb",
            f"-u{env['MW_DB_USER']}",
            f"-p{env['MW_DB_PASSWORD']}",
            env["MW_DB_NAME"],
        ],
        input_text=sql,
    )


def reindex_search(env: dict[str, str]) -> None:
    run(compose_files() + ["up", "-d"])
    wait_http(env["MW_SERVER"])
    maintenance("run.php", ["CirrusSearch:UpdateSearchIndexConfig", "--startOver"], capture=False)
    maintenance(
        "run.php",
        ["CirrusSearch:ForceSearchIndex", "--skipLinks", "--indexOnSkip"],
        capture=False,
    )
    maintenance(
        "run.php",
        ["runJobs", "--memory-limit", "max", "--type", "cirrusSearchElasticaWrite", "--maxjobs", "30000"],
        capture=False,
    )


def print_summary(env: dict[str, str]) -> None:
    print("\nLocal Vocomipedia MediaWiki is ready.")
    print(f"Wiki: {env['MW_SERVER']}/")
    print(f"API:  {env['MW_SERVER']}/api.php")
    print(f"Admin user: {env['MW_ADMIN_USER']}")
    print(f"Admin password: {env['MW_ADMIN_PASSWORD']}")
    print(f"Bot user: {env['MW_BOT_USER']}")
    print(f"Bot password: {env['MW_BOT_PASSWORD']}")
    print(f"Credentials file: {ENV_PATH}")


def status() -> None:
    env = ensure_env()
    run(compose_files() + ["ps"], check=False)
    print_summary(env)


def down(volumes: bool = False) -> None:
    cmd = compose_files() + ["down"]
    if volumes:
        cmd.append("-v")
    run(cmd, check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage the local Docker MediaWiki used for Vocomipedia API testing.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Create local env, install MediaWiki, and start the stack.")
    reset = sub.add_parser("reset", help="Destroy local DB/images and reinstall.")
    sub.add_parser("start", help="Start the local stack.")
    sub.add_parser("stop", help="Stop the local stack.")
    sub.add_parser("status", help="Show local stack status and credentials.")
    sub.add_parser("refresh-filter", help="Reinstall the active local AbuseFilter from sync_mediawiki.py.")
    sub.add_parser("reindex-search", help="Rebuild the local CirrusSearch index after bulk wiki changes.")
    sub.add_parser("destroy", help="Stop and remove local volumes.")
    args = ap.parse_args()

    env = ensure_env()
    if args.cmd == "init":
        install_mediawiki(env, reset=False)
    elif args.cmd == "reset":
        install_mediawiki(env, reset=True)
    elif args.cmd == "start":
        run(compose_files() + ["up", "-d"])
        wait_http(env["MW_SERVER"])
        ensure_local_structure_filter(env)
        print_summary(env)
    elif args.cmd == "stop":
        down(volumes=False)
    elif args.cmd == "destroy":
        down(volumes=True)
        if LOCAL_SETTINGS.exists():
            LOCAL_SETTINGS.unlink()
    elif args.cmd == "status":
        status()
    elif args.cmd == "refresh-filter":
        run(compose_files() + ["up", "-d"])
        wait_http(env["MW_SERVER"])
        ensure_local_structure_filter(env)
    elif args.cmd == "reindex-search":
        reindex_search(env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
