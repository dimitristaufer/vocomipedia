# GitHub Actions Setup

Vocomipedia has three workflow gates:

- `CI`: validates tools, schemas, unit tests, local MediaWiki config, search,
  release scripts, and offline sentence analyzers.
- `Wiki Sync Back`: pulls approved MediaWiki edits, auto-applies approved
  sentence proposals with offline POS/token generation, writes canonical changes
  to `data/languages`, and opens a PR in this repository.
- `Release And Deploy`: builds `.vpack` artifacts from checked-in canonical
  data, deploys them to the VPS pack host, optionally pushes generated wiki
  pages, and emits search-index SQL.

## Required Secrets

Store these in the protected `production` environment:

```text
MEDIAWIKI_API_URL      https://vocomipedia.com/api.php
MEDIAWIKI_USERNAME     BotUser@BotName
MEDIAWIKI_PASSWORD     bot password
VOCOMI_IOS_PRIVATE_PEM full iOS private PEM; workflow derives the matching public key
```

Optional, but recommended if GitHub Actions is not allowed to create pull
requests with the default repository token:

```text
VOCOMIPEDIA_PR_TOKEN   fine-grained PAT with Contents read/write and Pull requests read/write on this repo
```

For VPS static pack deployment:

```text
VPS_PACK_HOST          VPS IP address or packs.vocomipedia.com
VPS_PACK_PORT          22
VPS_PACK_USER          vocomipedia
VPS_PACK_SSH_KEY       private key for the deploy user
VPS_PACK_ROOT          /srv/vocomi-packs
```

For optional remote search reindex after MediaWiki push:

```text
MEDIAWIKI_SSH_HOST
MEDIAWIKI_SSH_USER
MEDIAWIKI_SSH_PRIVATE_KEY
MEDIAWIKI_REINDEX_COMMAND
```

`VOCOMI_REPO_TOKEN` is no longer required for the current Vocomipedia-owned
sync or release workflows. Azure upload remains available only in legacy/local
tooling; production releases deploy current packs to the VPS.

## Required Environment

Create a protected GitHub environment named:

```text
production
```

Require approval for that environment. `Wiki Sync Back` and `Release And
Deploy` both use it so MediaWiki, private-key, and deployment secrets stay
behind the same manual approval gate.

## Sync Approved Wiki Edits Back

Run:

```text
GitHub -> Actions -> Wiki Sync Back -> Run workflow
```

Typical run:

```text
deck_codes: ja_n5
export_source: true
create_pr: true
```

This pulls approved `Item:<deck>/...` pages from MediaWiki, merges safe visible
fields, converts direct sentence edits into sentence proposals, regenerates
sentence token/POS/readings offline, auto-applies the approved proposals, writes
reports, and opens a Vocomipedia PR when `data/languages` changes. No proposal
IDs are needed in normal operation. If GitHub blocks PR creation, the workflow
still pushes the sync branch and prints the manual PR URL in the run summary.

## Release And Deploy

Run:

```text
GitHub -> Actions -> Release And Deploy -> Run workflow
```

After the sync-back PR is merged, enter only the changed deck codes:

```text
deck_codes: ja_n5
```

The release workflow copies selected canonical JSON decks into a temporary
workspace, hydrates `media/` folders from the VPS, adds sibling decks needed for
combined data packs, validates release readiness, builds single and combined
`.vpack` files with the bundled pack builder, deploys to the VPS, pushes
approved pages back to MediaWiki, emits search-index SQL, and runs the remote
search reindex command.

## Search Index

`Release And Deploy` uploads `reports/search/vocomipedia-search-upsert.sql` as
an artifact. The SQL creates the search projection table if missing and upserts
selected deck rows without dropping the existing table.

For a full rebuild, run `tools/reindex_mediawiki_search.py` on the MediaWiki
server against the production checkout.

## Backups

The Python tools create tar backups before mutating local canonical data. The
workflows upload those backups and reports as artifacts. They do not replace
server-level MediaWiki database and file backups.
