# Vocomipedia

Vocomipedia is the reviewed source pipeline for Vocomi language decks.

MediaWiki is the public editing and moderation UI. This repo stores canonical
deck JSON, validates edits, generates wiki pages, syncs approved wiki changes
back, and builds signed `.vpack` releases for the app.

## Layout

- `data/languages/` canonical Vocomipedia deck JSON. Media folders are kept
  out of Git and hydrated from the VPS for release jobs.
- `catalog/packs.yaml` deck metadata and combined-pack rules.
- `tools/` import, validation, wiki sync, POS analysis, release, and deploy tools.
- `docker/` local/production MediaWiki assets and the Vocomipedia search extension.
- `infra/nginx/` versioned production Nginx templates.
- `docs/` operational details.

## Setup

```bash
python3 -m pip install -r requirements.txt
```

Secrets live outside the repo. Local production handoff files are under
`~/.vocomipedia/`.

## Validate

```bash
python3 tools/ci_validate.py --skip-smoke-release
python3 tools/validate_corpus.py --root data/languages
python3 tools/audit_pos_pipeline.py --root data/languages
```

Use stricter media validation before release:

```bash
python3 tools/validate_corpus.py --root data/languages --strict-media --release-ready
```

## Import Or Update Decks

Canonical decks live in `data/languages/`. For new or refreshed source decks,
import from a local legacy pack-generation checkout:

```bash
python3 tools/sync_all_packs.py \
  --decks ja_n5 ja_n4 \
  --copy-media \
  --mark-approved \
  --validate \
  --strict-media \
  --pack-generation-dir ../vocomi_pack_generation
```

For Japanese decks, add `--revise-japanese-furigana` to regenerate ruby with
Sudachi before validation.

For a new deck, add it to `catalog/packs.yaml`, sync it locally, run validation,
then use the release workflow.

## MediaWiki Sync

Generate pages locally:

```bash
python3 tools/sync_mediawiki.py generate \
  --deck-dir data/languages/ja/ja_n5 \
  --out-dir reports/mediawiki-pages \
  --approved-only
```

Push approved pages and images to production:

```bash
MEDIAWIKI_USERNAME='BotUser@BotName' \
MEDIAWIKI_PASSWORD='bot-password' \
python3 tools/sync_mediawiki.py push-api \
  --deck-dir data/languages/ja/ja_n5 \
  --api-url 'https://vocomipedia.com/api.php' \
  --approved-only
```

Pull edited pages back for review:

```bash
python3 tools/sync_mediawiki.py pull-api \
  --api-url 'https://vocomipedia.com/api.php' \
  --prefix 'Item:ja_n5/' \
  --out-dir tmp/wiki-pull/ja_n5
```

Apply approved pulled changes:

```bash
python3 tools/apply_pulled_items.py \
  --deck-dir data/languages/ja/ja_n5 \
  --pulled-dir tmp/wiki-pull/ja_n5 \
  --diff-report reports/wiki-apply-ja_n5.diff
```

Sentence edits create moderation proposals. `Wiki Sync Back` auto-applies
approved sentence proposals after regenerating tokens/POS/readings offline:

```bash
python3 tools/apply_sentence_proposals.py \
  --deck-dir data/languages/ja/ja_n5 \
  --apply \
  --diff-report reports/sentence-proposals-ja_n5.diff
```

Japanese sentence edits use bracket ruby such as `山[やま]を見る。`.

## Build And Deploy Packs

Build a deck:

```bash
python3 tools/release_pack.py \
  --deck-dir data/languages/ja/ja_n5 \
  --outdir release \
  --validate-private-key /path/to/ios_private.pem
```

Build affected combined packs:

```bash
python3 tools/release_combined_pack.py \
  --changed-decks ja_n5 ja_n4 \
  --root data/languages \
  --catalog catalog/packs.yaml \
  --outdir release \
  --validate-private-key /path/to/ios_private.pem
```

Deploy static pack artifacts to the VPS:

```bash
python3 tools/deploy_packs_to_vps.py \
  --packs-dir release/packs \
  --release-name "$(git rev-parse --short HEAD)" \
  --host "$VPS_PACK_HOST" \
  --port "${VPS_PACK_PORT:-22}" \
  --user "$VPS_PACK_USER" \
  --ssh-key "$VPS_SSH_KEY_PATH" \
  --remote-root /srv/vocomi-packs \
  --keep-releases 3
```

Azure upload support remains in the code for older app versions, but current
production deployment serves packs from `packs.vocomipedia.com`.

## GitHub Actions

- `CI`: validates tools and tests.
- `Wiki Sync Back`: imports approved MediaWiki edits into canonical data and
  opens Vocomipedia PRs.
- `Release And Deploy`: builds packs from canonical data, deploys to VPS, pushes wiki
  pages, and reindexes search.

Run the production workflow with only the changed deck codes:

```text
deck_codes: ja_n5
```

Required secrets and environment setup are documented in
`docs/github-actions.md`.

## Operations

VPS access is documented in the parent repo `AGENTS.md`. Day-to-day checks,
TLS renewal, security notes, deck rollout steps, wiki sync-back, and pack
retention are in `docs/operations-runbook.md`.

Clean stale local `.vpack` artifacts with a dry run first:

```bash
python3 tools/prune_pack_artifacts.py \
  --packs-dir release/packs \
  --keep 3
```

Add `--apply` only after reviewing the output.

## References

- Local MediaWiki: `docs/local-mediawiki.md`
- GitHub Actions: `docs/github-actions.md`
- VPS pack hosting: `docs/vps-pack-hosting.md`
- Operations runbook: `docs/operations-runbook.md`
- Japanese ruby: `docs/japanese-ruby.md`
