# Local MediaWiki Test Server

This local setup runs MediaWiki and MariaDB through Docker on macOS. It is for
testing the Vocomipedia API workflow before booking or configuring a VPS.

## Start From Scratch

Make sure Docker Desktop is running, then:

```bash
python3 vocomipedia/tools/local_mediawiki.py reset
```

This creates:

```text
vocomipedia/docker/local/.env
vocomipedia/docker/local/LocalSettings.php
```

Both files are ignored by git. The `.env` file contains local admin and bot
credentials.

The local MediaWiki image is built from `vocomipedia/docker/mediawiki/Dockerfile`
and includes Extension:Moderation. Normal logged-in users can submit edits, but
their edits are queued at `Special:Moderation` until an administrator or
moderator approves them. `Admin`, `sysop`, and `VocomiBot` bypass moderation.
The image also includes AbuseFilter, SpamBlacklist, ConfirmEdit/QuestyCaptcha,
DiscussionTools, Nuke, OATHAuth, ParserFunctions, Page Forms, Elastica,
CirrusSearch, and the custom VocomipediaSearch ranker. Local resets create real
`Item:`, `Deck:`, and `Policy:` namespaces.

`local_mediawiki.py init` and `reset` also install the active local AbuseFilter
rule `Vocomipedia item structure guard`, which blocks non-admin edits that
remove generated item templates or change protected item identifiers.

The local wiki is then available at:

```text
http://localhost:8080/
http://localhost:8080/api.php
```

After changing the image or `LocalSettings.php`, rebuild/restart and run schema
updates:

```bash
docker compose --env-file vocomipedia/docker/local/.env \
  -f vocomipedia/docker/compose.local.yml build mediawiki
docker compose --env-file vocomipedia/docker/local/.env \
  -f vocomipedia/docker/compose.local.yml up -d
docker exec docker-mediawiki-1 php /var/www/html/maintenance/run.php update --quick
```

Before schema changes on an existing local wiki, create a database backup:

```bash
docker exec docker-db-1 sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" mediawiki' \
  > vocomipedia/backups/local-mediawiki-before-change.sql
```

## Day-To-Day Commands

```bash
python3 vocomipedia/tools/local_mediawiki.py start
python3 vocomipedia/tools/local_mediawiki.py stop
python3 vocomipedia/tools/local_mediawiki.py status
python3 vocomipedia/tools/local_mediawiki.py refresh-filter
python3 vocomipedia/tools/local_mediawiki.py reindex-search
python3 vocomipedia/tools/local_mediawiki.py destroy
```

`refresh-filter` reinstalls the active local AbuseFilter from the current
`sync_mediawiki.py` source. `start` also runs this automatically, which keeps
local saves aligned with generated template changes.

`reindex-search` rebuilds the local CirrusSearch/Elasticsearch index after bulk
deck pushes or imports. The Vocomipedia search page ranks entries from canonical
item JSON, so it searches headwords, readings, translations, examples, and token
meanings across any language deck. For fast ranked search, rebuild the compact
Vocomipedia item projection after large pushes:

```bash
python3 vocomipedia/tools/reindex_mediawiki_search.py
```

Without this projection table, `Special:VocomipediaSearch` falls back to scanning
item pages directly. The CirrusSearch index remains the fallback for full wiki
text search and should also be rebuilt after large local imports.

`destroy` removes Docker volumes and the generated local `LocalSettings.php`.

## End-To-End API Test

```bash
python3 vocomipedia/tools/local_e2e.py
```

This validates the whole local loop:

```text
legacy fixture
  -> canonical Vocomipedia deck
  -> local MediaWiki API push
  -> local MediaWiki API pull
  -> backup-aware apply into canonical deck
  -> validation
  -> current Vocomi .vpack build
  -> .vpack decrypt/ZIP/SQLite verification
```

## Manual MediaWiki API Usage

Read local credentials:

```bash
cat vocomipedia/docker/local/.env
```

Push a deck:

```bash
MEDIAWIKI_USERNAME='VocomiBot' \
MEDIAWIKI_PASSWORD='from-local-env-file' \
python3 vocomipedia/tools/sync_mediawiki.py push-api \
  --deck-dir /path/to/deck \
  --api-url 'http://localhost:8080/api.php' \
  --approved-only
```

By default, `push-api` generates and uploads low-res JPEG entry images for
items whose canonical media file exists. Add `--skip-entry-images` if you only
want to republish text/template pages.

Refresh only the Page Forms/templates/support pages:

```bash
MEDIAWIKI_USERNAME='Admin' \
MEDIAWIKI_PASSWORD='from-local-env-file' \
python3 vocomipedia/tools/sync_mediawiki.py seed-structure \
  --api-url 'http://localhost:8080/api.php' \
  --push-interface-pages
```

Pull pages back:

```bash
python3 vocomipedia/tools/sync_mediawiki.py pull-api \
  --api-url 'http://localhost:8080/api.php' \
  --prefix 'Item:ja_n5/' \
  --out-dir /tmp/vocomipedia-pulled
```

Apply pulled pages back into a canonical deck:

```bash
python3 vocomipedia/tools/apply_pulled_items.py \
  --deck-dir /path/to/deck \
  --pulled-dir /tmp/vocomipedia-pulled \
  --diff-report /tmp/vocomipedia-apply.diff
```

`pull-api` stores the visible wiki revision in `review.wiki`, and
`apply_pulled_items.py` refuses stale changed revisions unless `--force-stale`
is supplied.
