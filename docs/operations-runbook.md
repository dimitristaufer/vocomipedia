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

1. Add or update the canonical deck under `data/languages`.
2. Add a `catalog/packs.yaml` entry for any new deck code, language, level, and
   combined data-pack code. Keep legacy source paths only when local imports are
   still needed.
3. If importing from a local legacy pack-generation checkout, run a smoke import:

   ```bash
   python3 tools/sync_all_packs.py \
     --decks <deck_code> \
     --limit 5 \
     --copy-media \
     --mark-approved \
     --validate \
     --strict-media \
     --pack-generation-dir ../vocomi_pack_generation \
     --out-root tmp/deck-smoke \
     --backup-dir reports/backups
   ```

4. Validate the canonical deck:

   ```bash
   python3 tools/validate_corpus.py --root data/languages --strict-media --release-ready
   python3 tools/audit_pos_pipeline.py --root data/languages
   ```

5. For full release, run GitHub Actions `Release And Deploy` with:

   ```text
   deck_codes: <deck_code or changed deck group>
   sync_limit: 0
   build_vpack: true
   upload: false
   vps_pack_deploy: true
   mediawiki_push: true
   generate_search_sql: true
   run_remote_reindex: true
   ```

5. Verify public search and representative item pages, including images.

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
- GitHub tokens are repo-scoped and no private app repo checkout is required for
  normal sync/release workflows.
- VPS SSH keys used in GitHub are deploy-only where possible; avoid root keys in
  Actions.
- MediaWiki admin accounts use strong passwords and 2FA.
- MediaWiki bot accounts are scoped to automation and not used interactively.
- Certbot renewal dry run passes.
- UFW allows only SSH/HTTP/HTTPS.
- SSH password login is disabled; root is key-only; `MaxAuthTries` is 3.
- `fail2ban` and `unattended-upgrades` are enabled and active.
- Nginx proxies MediaWiki only through `127.0.0.1:8080`.
- Nginx serves a real `/robots.txt` and rate-limits known AI crawler user
  agents before proxying to MediaWiki.
- Database and image-volume backups are tested, not only configured.
