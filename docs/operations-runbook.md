# Vocomipedia Operations Runbook

## VPS Access

Operational SSH details live outside the repository:

```bash
source ~/.vocomipedia/vps.env
ssh -i "$VPS_SSH_KEY_PATH" -p "${VPS_PORT:-22}" "$VPS_ROOT_USER@$VPS_HOST"
ssh -i "$VPS_SSH_KEY_PATH" -p "${VPS_PORT:-22}" "$VPS_DEPLOY_USER@$VPS_HOST"
```

Do not commit VPS credentials or generated MediaWiki credentials. Local
production credential handoff files are under `~/.vocomipedia/`.

Important server paths:

```text
/srv/vocomipedia                 production Vocomipedia checkout
/srv/vocomipedia/docker/local    generated MediaWiki LocalSettings and secrets
/srv/vocomi-packs/current        active static pack root
/srv/vocomi-packs/releases       retained pack releases
/etc/nginx/conf.d                public Nginx config
```

Versioned Nginx templates live in `infra/nginx/`. After changing those, copy
them into `/etc/nginx/conf.d/`, run `nginx -t`, then reload Nginx.

Useful checks:

```bash
nginx -t
systemctl status nginx --no-pager
systemctl list-timers --all | grep certbot
certbot renew --dry-run
certbot renew --dry-run --no-random-sleep-on-renew
cd /srv/vocomipedia && docker-compose --env-file docker/local/.env -f docker/compose.local.yml ps
sshd -T | egrep '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|maxauthtries)'
fail2ban-client status sshd
```

TLS is handled by Certbot. `certbot.timer` must be enabled and renewal dry runs
must pass after Nginx or DNS changes. Use `--no-random-sleep-on-renew` for
manual validation so Certbot does not wait several minutes before starting.

## Adding Or Updating Decks

1. Add or update the canonical deck JSON under `data/languages`. Commit
   `pack.json` and `items/*.json`; keep `media/` folders on the VPS/local
   release machine, not in Git.
2. Add a `catalog/packs.yaml` entry for any new deck code, language, level, and
   combined data-pack code. Keep legacy source paths only when local imports are
   still needed.
3. If importing from a local legacy pack-generation checkout, run a smoke import:

   ```bash
   python3 tools/sync_all_packs.py \
     --decks <deck_code> \
     --limit 5 \
     --copy-media \
     --auto-pos-analysis \
     --mark-approved \
     --validate \
     --strict-media \
     --pack-generation-dir ../vocomi_pack_generation \
     --out-root tmp/deck-smoke \
     --backup-dir reports/backups
   ```

   New deck scaffolding and source-generation expectations are documented in
   `docs/deck-generation.md`.

4. Validate the canonical deck:

   ```bash
   python3 tools/validate_corpus.py --root data/languages --strict-media --release-ready
   python3 tools/audit_pos_pipeline.py --root data/languages
   ```

5. For full release, run GitHub Actions `Release And Deploy` with:

   ```text
   deck_codes: <deck_code or changed deck group>
   ```

6. Verify public search and representative item pages, including images.

Manual production search projection rebuild:

```bash
cd /srv/vocomipedia
git config --global --add safe.directory /srv/vocomipedia
VOCOMIPEDIA_DOCKER_COMPOSE=docker-compose \
  python3 tools/reindex_mediawiki_search.py --root data/languages --no-drop
```

The search projection script streams SQL to MariaDB. Do not pipe a full
generated SQL file for production-sized corpora unless you explicitly need an
artifact copy.

For new languages, also confirm the offline sentence analyzer supports the
language or add one under `tools/vocomipedia_nlp/` before enabling public
sentence editing for that deck.

Audit regenerated sentence token/POS output against the existing deck
tokenization before enabling a new language or analyzer:

```bash
python3 tools/audit_pos_pipeline.py --root data/languages
```

Use `--json` to capture representative mismatch examples. A merge-aware match
is expected because generated analyzers may split punctuation, particles, or
auxiliaries more finely than the legacy deck tokens.

## Syncing Wiki Edits Back

Run GitHub Actions `Wiki Sync Back` for the affected deck. It pulls approved
wiki edits, auto-applies approved sentence proposals with generated token/POS
data, and opens a Vocomipedia PR against `data/languages`. Merge that PR before
running a production release.

## MediaWiki Backups And Restore

MediaWiki backups are separate from canonical-data workflow artifacts. A real
server backup must include MariaDB, uploaded wiki images, and the generated
Docker/MediaWiki configuration.

Create and verify a production backup:

```bash
cd /srv/vocomipedia
VOCOMIPEDIA_DOCKER_COMPOSE=docker-compose \
  python3 tools/mediawiki_backup.py backup \
    --backup-dir /srv/backups/vocomipedia \
    --latest-symlink \
    --keep-count 14
VOCOMIPEDIA_DOCKER_COMPOSE=docker-compose \
  python3 tools/mediawiki_backup.py verify /srv/backups/vocomipedia/latest.tar.gz
```

The archive contains:

```text
manifest.json
db.sql.gz
images.tar.gz
config.tar.gz
```

`config.tar.gz` includes `docker/local/.env` and the generated
`LocalSettings.php`; treat the backup bundle as secret material. Store copies
off the VPS with encryption and checksum verification.

Install the daily systemd backup timer:

```bash
cd /srv/vocomipedia
sudo python3 tools/mediawiki_backup.py install-systemd \
  --backup-dir /srv/backups/vocomipedia \
  --hour-utc 2
systemctl list-timers --all | grep vocomipedia-mediawiki-backup
```

The timer keeps the newest 14 backup bundles by default.

Run a restore drill on a disposable host or cloned stack, never first on
production:

```bash
cd /srv/vocomipedia
VOCOMIPEDIA_DOCKER_COMPOSE=docker-compose \
  python3 tools/mediawiki_backup.py restore /srv/backups/vocomipedia/latest.tar.gz \
    --confirm 'RESTORE MEDIAWIKI'
```

After restore, validate:

```bash
docker-compose --env-file docker/local/.env -f docker/compose.local.yml ps
python3 tools/mediawiki_security_audit.py --strict
VOCOMIPEDIA_DOCKER_COMPOSE=docker-compose \
  python3 tools/reindex_mediawiki_search.py --root data/languages
```

Then check representative wiki pages, uploaded images, login, moderation,
uploads, and `Special:VocomipediaSearch`.

## Pack Retention

Server deployments should keep the last three static pack releases:

```bash
python3 tools/deploy_packs_to_vps.py ... --keep-releases 3
```

Local stale pack cleanup:

```bash
python3 tools/prune_pack_artifacts.py \
  --packs-dir release/packs \
  --keep 3
```

Review the dry run, then add `--apply`.

## Security Review Checklist

- GitHub `production` environment requires approval.
- `Release And Deploy` and `Wiki Sync Back` have production concurrency groups.
- `Release And Deploy` creates and verifies a MediaWiki DB/images/config backup
  before MediaWiki API mutations.
- GitHub tokens are repo-scoped and no private app repo checkout is required for
  normal sync/release workflows.
- VPS SSH keys used in GitHub are deploy-only where possible; avoid root keys in
  Actions.
- MediaWiki admin accounts use strong passwords and 2FA.
- `MW_REQUIRE_PRIVILEGED_2FA=1` is set only after all privileged users are
  enrolled in 2FA.
- MediaWiki bot accounts are scoped to automation and not used interactively.
- MediaWiki rate limits are not globally disabled.
- Certbot renewal dry run passes.
- UFW allows only SSH/HTTP/HTTPS.
- SSH password login is disabled; root is key-only; `MaxAuthTries` is 3.
- `fail2ban` and `unattended-upgrades` are enabled and active.
- Nginx proxies MediaWiki only through `127.0.0.1:8080`.
- Nginx serves a real `/robots.txt` and rate-limits known AI crawler user
  agents before proxying to MediaWiki.
- Database and image-volume backups are tested, not only configured.

Run the no-usernames production audit:

```bash
cd /srv/vocomipedia
python3 tools/mediawiki_security_audit.py --strict
```
