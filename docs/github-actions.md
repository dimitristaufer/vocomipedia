# GitHub Actions Setup

The workflow is defined at:

```text
.github/workflows/vocomipedia.yml
```

It always runs backup-aware validation on pull requests and pushes in the
standalone Vocomipedia repository.

Manual workflow runs can also:

- sync selected decks from `vocomi_pack_generation`
- revise Japanese ruby with SudachiPy/SudachiDict
- build `.vpack` artifacts
- rebuild affected combined data packs such as `ja_n5-n4` when a component
  deck such as `ja_n5` or `ja_n4` is selected
- optionally upload to Azure Blob Storage
- optionally push generated item pages to MediaWiki
- update the generated `Deck:` pages, `Main Page`, and `Vocomipedia:Admin`

## Required Repository Secrets

Add these in GitHub:

```text
Repository -> Settings -> Secrets and variables -> Actions -> New repository secret
```

For MediaWiki push:

```text
MEDIAWIKI_API_URL      https://vocomipedia.com/w/api.php
MEDIAWIKI_USERNAME     BotUser@BotName
MEDIAWIKI_PASSWORD     bot password
```

For Azure deck upload:

```text
AZURE_STORAGE_ACCOUNT
AZURE_STORAGE_KEY
PACKS_CONTAINER        packs
```

`PACKS_CONTAINER` is optional; if omitted, the tooling uses `packs`.

For release jobs, the workflow checks out `dimitristaufer/Vocomi` beside this
repo to access `vocomi_pack_generation`. If that repository is private, add a
fine-scoped token that can read it:

```text
VOCOMI_REPO_TOKEN
```

## Create A MediaWiki Bot Password

In MediaWiki:

```text
Special:BotPasswords
```

Create a bot password for the sync account with rights to edit/create pages.
Use the generated bot username and password as `MEDIAWIKI_USERNAME` and
`MEDIAWIKI_PASSWORD`.

## Manual Workflow Inputs

Run:

```text
GitHub -> Actions -> Vocomipedia -> Run workflow
```

Inputs:

```text
deck_codes       Space-separated deck codes, e.g. "zh_1 ja_n5"
sync_limit       Use 2 for smoke, 0 for full deck
release          Build .vpack artifacts
upload           Upload built artifacts to Azure
mediawiki_push   Push generated item pages to MediaWiki
revise_japanese_furigana
                 Run Sudachi-backed dictionary-style ruby revision for ja_* decks
```

Recommended first production-safe run:

```text
deck_codes: zh_1
sync_limit: 2
release: true
upload: false
mediawiki_push: false
```

Then inspect the uploaded workflow artifact `vocomipedia-manual-run`.

Recommended first MediaWiki API run:

```text
deck_codes: zh_1
sync_limit: 2
release: false
upload: false
mediawiki_push: true
```

The MediaWiki push uses the configured custom namespaces. It updates
`Vocomipedia:Admin` by default. Sidebar updates are intentionally not part of
the workflow because `MediaWiki:Sidebar` requires `editinterface`; use
`sync_mediawiki.py push-api --push-sidebar` only with an account that has that
right.

Recommended full upload run only after smoke checks:

```text
deck_codes: ja_n5 ja_n4
sync_limit: 0
revise_japanese_furigana: true
release: true
upload: true
mediawiki_push: true
```

For combined packs, keep listing the component decks in `deck_codes`; the
workflow derives the shared `data_pack_code` from `catalog/packs.yaml`.
For example, `deck_codes: ja_n5` or `deck_codes: ja_n4` rebuilds the affected
`ja_n5-n4` data pack. During workflow runs, newly synced decks in
`tmp/actions-data` override checked-in canonical data, while unchanged sibling
decks are read from `data/languages`.

## Backups

The workflow creates tar backups before mutating sync/apply steps and uploads
them as artifacts.

The workflow does not back up the remote MediaWiki database. The server still
needs its own daily database/files backup.
