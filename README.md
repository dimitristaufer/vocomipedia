# Vocomipedia

Vocomipedia is the reviewed source pipeline for Vocomi prebuilt decks.

The first implementation deliberately keeps the existing app distribution
contract intact:

```text
approved Vocomipedia JSON
  -> legacy Vocomi structure JSON + comic images
  -> vocomi_pack_generation/ios_package_assets.py
  -> vocomi_pack_generation/make_server_language_pack_chunked.py
  -> .vpack + .meta.json + .sha256
  -> existing Azure pack API
  -> iOS app
```

This directory is not a replacement for MediaWiki. It is the canonical data,
validation, and release layer that MediaWiki should feed. Public wiki pages can
be generated from these files, and approved wiki revisions can later be imported
back into the same format.

## Main Commands

Backup-aware sync all selected latest generated packs from
`vocomi_pack_generation` into canonical Vocomipedia data:

```bash
python3 vocomipedia/tools/sync_all_packs.py \
  --packs zh_1 ja_n5 \
  --copy-media \
  --validate \
  --strict-media
```

The sync command always creates a timestamped tar backup before replacing pack
directories. Backups are written to `vocomipedia/backups/` by default.

Import a current legacy pack into canonical Vocomipedia items:

```bash
python3 vocomipedia/tools/import_legacy_pack.py \
  --pack-code zh_1 \
  --input-json vocomi_pack_generation/HSK_1/HSK_1_structure.json \
  --asset-dir vocomi_pack_generation/HSK_1 \
  --out-root vocomipedia/data/languages \
  --copy-media
```

Validate canonical data:

```bash
python3 vocomipedia/tools/validate_corpus.py --root vocomipedia/data/languages
```

Export canonical data back to the flat legacy structure expected by the current
pack builder:

```bash
python3 vocomipedia/tools/export_legacy_structure.py \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --out-json /tmp/zh_1_structure.json
```

Build current iOS assets and, unless `--skip-vpack` is provided, the encrypted
server pack:

```bash
python3 vocomipedia/tools/release_pack.py \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --pack-generation-dir vocomi_pack_generation \
  --outdir /tmp/vocomipedia-release
```

Build and upload through the existing Azure-capable pack builder:

```bash
python3 vocomipedia/tools/release_pack.py \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --pack-generation-dir vocomi_pack_generation \
  --outdir vocomipedia/release \
  --upload
```

Validate a generated `.vpack` by decrypting it with the iOS private key and
checking ZIP integrity:

```bash
python3 vocomipedia/tools/validate_vpack.py \
  --vpack vocomipedia/release/packs/<pack>.vpack \
  --private-key vocomi_pack_generation/ios_private.pem \
  --require-sqlite
```

Generate MediaWiki pages:

```bash
python3 vocomipedia/tools/sync_mediawiki.py generate \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --out-dir vocomipedia/reports/mediawiki-pages \
  --approved-only
```

Push pages to MediaWiki with a bot password:

```bash
MEDIAWIKI_USERNAME='BotUser@BotName' \
MEDIAWIKI_PASSWORD='bot-password' \
python3 vocomipedia/tools/sync_mediawiki.py push-api \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --api-url 'https://vocomipedia.com/w/api.php' \
  --approved-only
```

Pull canonical JSON blocks back from MediaWiki pages:

```bash
python3 vocomipedia/tools/sync_mediawiki.py pull-api \
  --api-url 'https://vocomipedia.com/w/api.php' \
  --prefix 'Item:zh_1/' \
  --out-dir vocomipedia/tmp/wiki-pull/zh_1
```

Apply pulled JSON into a canonical pack. This creates a backup before writing:

```bash
python3 vocomipedia/tools/apply_pulled_items.py \
  --pack-dir vocomipedia/data/languages/zh/zh_1 \
  --pulled-dir vocomipedia/tmp/wiki-pull/zh_1
```

## Review State

Only items with `review.status` set to `approved` should enter public app
releases. Draft, needs-review, and deprecated entries remain visible to tools
but are excluded from release builds by default.

## MediaWiki Role

MediaWiki should provide accounts, history, discussion, public pages, suggested
edits, and moderation. Vocomipedia JSON remains the release source of truth.
Recommended extensions and launch notes are in `docs/mediawiki-setup.md`.

Generated wiki pages contain a hidden canonical JSON block. That makes the sync
reversible: human-visible wikitext can be edited, while tools can still pull the
structured item back for review.

## CI

`.github/workflows/vocomipedia.yml` runs backup-aware validation for this
pipeline. The workflow creates a tar backup before validation and uploads it as
an artifact.
# vocomipedia
