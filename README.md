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
  -> existing Azure deck API
  -> iOS app
```

This directory is not a replacement for MediaWiki. It is the canonical data,
validation, and release layer that MediaWiki should feed. Public wiki pages can
be generated from these files, and approved wiki revisions can later be imported
back into the same format.

## Main Commands

Backup-aware sync all selected latest generated decks from
`vocomi_pack_generation` into canonical Vocomipedia data:

```bash
python3 tools/sync_all_packs.py \
  --decks zh_1 ja_n5 \
  --copy-media \
  --validate \
  --strict-media
```

The sync command always creates a timestamped tar backup before replacing deck
directories. Backups are written to `backups/` by default.

For Japanese decks, revise dictionary-style ruby locally with
SudachiPy/SudachiDict after import:

```bash
python3 -m pip install sudachipy sudachidict_core
python3 tools/sync_all_packs.py \
  --decks ja_n5 ja_n4 \
  --copy-media \
  --mark-approved \
  --revise-japanese-furigana \
  --validate
```

The Sudachi revision creates its own backup before writing and does not require
external API credentials.

Sentence corrections from MediaWiki are moderation proposals. Analyze or apply
them locally with offline token/POS generation:

```bash
python3 tools/apply_sentence_proposals.py \
  --deck-dir data/languages/ja/ja_n5 \
  --apply \
  --diff-report reports/sentence-proposals-ja_n5.diff
```

The analyzer uses local language-specific libraries when installed
(SudachiPy/SudachiDict for Japanese, Kiwi for Korean, spaCy or Stanza where
available) and falls back to deterministic Unicode tokenization so proposals
can still be reviewed without network calls.

Import a current legacy deck into canonical Vocomipedia items:

```bash
python3 tools/import_legacy_pack.py \
  --deck-code zh_1 \
  --input-json vocomi_pack_generation/HSK_1/HSK_1_structure.json \
  --asset-dir vocomi_pack_generation/HSK_1 \
  --out-root data/languages \
  --copy-media
```

Validate canonical data:

```bash
python3 tools/validate_corpus.py --root data/languages
```

Run stricter content and release-policy validation when auditing a deck before
publication:

```bash
python3 tools/validate_corpus.py \
  --root data/languages/ja/ja_n5 \
  --strict-media \
  --release-ready
```

Add `--strict-content` for focused token-alignment QA. That mode is intentionally
stricter than the current release gate and may surface legacy tokenization work.

Revise an already-imported Japanese deck without re-importing from
`vocomi_pack_generation`:

```bash
python3 tools/revise_japanese_furigana.py \
  --root data/languages/ja/ja_n5 \
  --sudachi-dict core \
  --sudachi-mode C
```

Export canonical data back to the flat legacy structure expected by the current
deck builder:

```bash
python3 tools/export_legacy_structure.py \
  --deck-dir data/languages/zh/zh_1 \
  --out-json /tmp/zh_1_structure.json
```

Build current iOS assets and, unless `--skip-vpack` is provided, the encrypted
server deck:

```bash
python3 tools/release_pack.py \
  --deck-dir data/languages/zh/zh_1 \
  --pack-generation-dir vocomi_pack_generation \
  --outdir /tmp/vocomipedia-release
```

Build and upload through the existing Azure-capable deck builder:

```bash
python3 tools/release_pack.py \
  --deck-dir data/languages/zh/zh_1 \
  --pack-generation-dir vocomi_pack_generation \
  --outdir release \
  --upload
```

Build a combined data pack from canonical component decks. For example, this
rebuilds `ja_n5-n4` from the approved contents of `ja_n5` and `ja_n4`:

```bash
python3 tools/release_combined_pack.py \
  --data-pack-code ja_n5-n4 \
  --root data/languages \
  --pack-generation-dir vocomi_pack_generation \
  --outdir release \
  --validate-private-key vocomi_pack_generation/ios_private.pem
```

When `sync_all_packs.py --release` is run for one component deck, affected
combined data packs are rebuilt automatically. For example, releasing either
`ja_n5` or `ja_n4` also rebuilds `ja_n5-n4` unless
`--skip-combined-release` is supplied.

Validate a generated `.vpack` by decrypting it with the iOS private key and
checking ZIP integrity:

```bash
python3 tools/validate_vpack.py \
  --vpack release/packs/<deck>.vpack \
  --private-key vocomi_pack_generation/ios_private.pem \
  --require-sqlite
```

Generate MediaWiki pages:

```bash
python3 tools/sync_mediawiki.py generate \
  --deck-dir data/languages/zh/zh_1 \
  --out-dir reports/mediawiki-pages \
  --approved-only
```

Push pages to MediaWiki with a bot password:

```bash
MEDIAWIKI_USERNAME='BotUser@BotName' \
MEDIAWIKI_PASSWORD='bot-password' \
python3 tools/sync_mediawiki.py push-api \
  --deck-dir data/languages/zh/zh_1 \
  --api-url 'https://vocomipedia.com/w/api.php' \
  --approved-only
```

`push-api` also maintains the Page Forms structure pages by default:
`Template:VocomipediaItem`, `Template:VocomipediaSentence`,
`Template:VocomipediaToken` for backward-compatible rendering, `Form:Vocomipedia item`, and the item category.
For items with a canonical `media.image_filename`, it also uploads a generated
low-res JPEG `File:` and renders it as the entry image on the item page. Use
`--skip-entry-images` for text-only syncs.
To refresh only those pages, run:

```bash
python3 tools/sync_mediawiki.py seed-structure \
  --api-url 'https://vocomipedia.com/w/api.php' \
  --username 'AdminUser' \
  --password 'admin-password'
```

Add `--push-interface-pages` with an account that has `editinterface` to update
the AbuseFilter warning message in `MediaWiki:`.

Pull canonical JSON blocks back from MediaWiki pages:

```bash
python3 tools/sync_mediawiki.py pull-api \
  --api-url 'https://vocomipedia.com/w/api.php' \
  --prefix 'Item:zh_1/' \
  --out-dir tmp/wiki-pull/zh_1
```

Apply pulled JSON into a canonical deck. This creates a backup before writing:

```bash
python3 tools/apply_pulled_items.py \
  --deck-dir data/languages/zh/zh_1 \
  --pulled-dir tmp/wiki-pull/zh_1 \
  --diff-report reports/wiki-apply-zh_1.diff
```

Pulled pages record the visible MediaWiki revision under `review.wiki`.
Applying pulled items refuses stale changed revisions by default and, for
existing items, merges only visible editable fields plus wiki revision metadata
unless `--trust-hidden-json` is supplied.

## Review State

Only items with `review.status` set to `approved` should enter public app
releases. Draft, needs-review, and deprecated entries remain visible to tools
but are excluded from release builds by default.

## MediaWiki Role

MediaWiki should provide accounts, history, discussion, public pages, suggested
edits, and moderation. Vocomipedia JSON remains the release source of truth.
Recommended extensions and launch notes are in `docs/mediawiki-setup.md`.
Japanese ruby/furigana fields are documented in `docs/japanese-ruby.md`.

Generated wiki pages contain a hidden canonical JSON block. That makes the sync
reversible. Human edits should go through `Edit with form`; the raw item page is
generated template storage. The pull tool accepts template field-value edits and
rejects structural tampering such as changed protected IDs, removed templates,
or changed sentence indexes. Contributors edit example sentences and
translations directly in the form. Japanese sentence edits use bracket notation
such as `山[やま]を見る。`, so furigana corrections are captured in the same
review path as sentence corrections. Sentence text or bracket changes are
captured as `review.sentence_proposals[]` instead of changing canonical pack
content.
Accepted replacements are applied by `apply_sentence_proposals.py`, which
auto-generates the replacement sentence tokens/POS/readings and syncs
`app_payload.pos_analysis`.
Legacy wikitable pages can still be pulled as a migration fallback.

The sync push also maintains `Vocomipedia:Admin`, a compact operator dashboard
for moderation, users/roles, AbuseFilter, cleanup, bot passwords, and policy
pages. Real custom namespaces are configured for `Item:`, `Deck:`, and
`Policy:`.

## CI

`.github/workflows/ci.yml` runs backup-aware validation for this pipeline.
`Wiki Sync Back` opens source PRs from approved MediaWiki edits, and
`Release And Deploy` handles protected pack builds, uploads, MediaWiki push,
and search-index artifacts.

Local MediaWiki setup is documented in `docs/local-mediawiki.md`.
GitHub Actions setup and required secrets are documented in
`docs/github-actions.md`.
VPS static pack hosting is documented in `docs/vps-pack-hosting.md`.
# vocomipedia
