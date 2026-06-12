# GitHub Actions Setup

Vocomipedia now has three workflow gates:

- `CI`: validates tools, schemas, and unit tests on every push/PR.
- `Wiki Sync Back`: pulls approved MediaWiki edits, analyzes sentence proposals,
  exports accepted source changes back into `vocomi_pack_generation`, and opens
  a PR in `dimitristaufer/Vocomi`.
- `Release And Deploy`: imports current Vocomi source decks, validates release
  content, builds `.vpack` artifacts, optionally uploads them, optionally pushes
  generated pages to MediaWiki, and emits search-index SQL.

## Required Secrets

For any workflow that checks out or opens PRs against the private Vocomi repo:

```text
VOCOMI_REPO_TOKEN
```

The token needs read access for release jobs. For `Wiki Sync Back`, it also
needs permission to push branches and open pull requests in `dimitristaufer/Vocomi`.

For MediaWiki pull/push:

```text
MEDIAWIKI_API_URL      https://vocomipedia.com/w/api.php
MEDIAWIKI_USERNAME     BotUser@BotName
MEDIAWIKI_PASSWORD     bot password
```

`Wiki Sync Back` only requires `MEDIAWIKI_API_URL`; `Release And Deploy` needs
the username/password when `mediawiki_push` is enabled.

For Azure upload:

```text
AZURE_STORAGE_ACCOUNT
AZURE_STORAGE_KEY
PACKS_CONTAINER        packs
```

For vpack validation, prefer storing the private key as an environment secret:

```text
VOCOMI_IOS_PRIVATE_PEM
```

If that secret is absent, release jobs fall back to
`vocomi_pack_generation/ios_private.pem` from the checked-out Vocomi repo.

For optional remote search reindex after MediaWiki push:

```text
MEDIAWIKI_SSH_HOST
MEDIAWIKI_SSH_USER
MEDIAWIKI_SSH_PRIVATE_KEY
MEDIAWIKI_REINDEX_COMMAND
```

`MEDIAWIKI_REINDEX_COMMAND` should be the exact server-side command, for
example a command that updates the deployed Vocomipedia checkout and runs the
search projection rebuild.

## Required Environment

Create a protected GitHub environment named:

```text
production
```

Require approval for that environment. `Release And Deploy` always uses it, so
build/upload/wiki-push runs are gated even when the workflow is manually
started.

## Sync Approved Wiki Edits Back

Run:

```text
GitHub -> Actions -> Wiki Sync Back -> Run workflow
```

Typical safe run:

```text
deck_codes: ja_n5
export_source: true
create_pr: true
apply_all_sentence_proposals: false
proposal_ids:
```

This imports the current deck from `dimitristaufer/Vocomi`, pulls approved
`Item:<deck>/...` pages from MediaWiki, applies safe visible fields, analyzes
sentence proposals, writes reports, exports accepted non-proposal changes back
to the source JSON, and opens a Vocomi PR if the source changed.

To apply specific reviewed sentence proposals:

```text
proposal_ids: sentprop-abc123 sentprop-def456
```

Only use `apply_all_sentence_proposals: true` for a controlled deck where every
active proposal has already been reviewed.

## Release And Deploy

Run:

```text
GitHub -> Actions -> Release And Deploy -> Run workflow
```

Smoke build:

```text
deck_codes: zh_1
sync_limit: 2
build_vpack: true
upload: false
mediawiki_push: false
```

Production release after the sync-back PR is merged into Vocomi:

```text
deck_codes: ja_n5 ja_n4
source_ref: main
sync_limit: 0
revise_japanese_furigana: true
build_vpack: true
upload: true
mediawiki_push: true
generate_search_sql: true
```

The release workflow automatically imports sibling decks needed for combined
data packs. For example, selecting `ja_n5` includes `ja_n4` in the temporary
canonical workspace so `ja_n5-n4` can be rebuilt.

## Search Index

`Release And Deploy` uploads `reports/search/vocomipedia-search-upsert.sql` as
an artifact when `generate_search_sql` is enabled. The SQL creates the search
projection table if missing and upserts the selected deck rows without dropping
the existing table.

For a full rebuild, run `tools/reindex_mediawiki_search.py` on the MediaWiki
server against a full canonical data checkout. For deployment automation, set
the optional SSH secrets and enable `run_remote_reindex`.

## Backups

The Python tools create tar backups before mutating local canonical data. The
workflows upload those backups and reports as artifacts. They do not replace
server-level MediaWiki database and file backups.
