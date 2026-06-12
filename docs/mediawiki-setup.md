# MediaWiki Setup Notes

Vocomipedia should use MediaWiki for public collaboration and this repository
for release data. The app should receive only approved release snapshots.

Recommended launch stack:

- MediaWiki LTS or current stable release.
- Moderation for new-user edits and uploads.
- Approved Revs or FlaggedRevs later if we need a separate stable-vs-latest
  reader view; Moderation is the first required gate.
- AbuseFilter for mass deletion, link spam, profanity, suspicious uploads, and
  repeated edit patterns.
- SpamBlacklist for blocked URL and email patterns.
- ConfirmEdit for risky actions, not every edit.
- DiscussionTools for item talk pages.
- Page Forms for structured item editing.
- ParserFunctions for conditional template rendering, including optional entry
  images.
- RevisionDelete for harmful revisions.
- OATHAuth two-factor authentication for administrators and moderators.
- Nuke for cleanup after spam bursts.

The Docker image now installs the launch-critical extensions above except
Approved Revs/FlaggedRevs. `LocalSettings.vocomipedia.php` enables
AbuseFilter, SpamBlacklist, ConfirmEdit/QuestyCaptcha, DiscussionTools, Nuke,
OATHAuth, ParserFunctions, Page Forms, and Moderation. Moderation is loaded
last.

Avoid open image uploads at launch. Start with text corrections and example
sentence improvements. Comic and image contributions should require approved
contributors, explicit license data, and content safety review.

## Suggested Namespaces

- `Item:` public human-readable item pages generated from canonical JSON.
- `Deck:` public deck pages and release notes.
- `Policy:` contributor rules, licensing, takedown, and moderation rules.
- `Vocomipedia:` project documentation.

The Docker config defines real custom namespaces for `Item:`, `Deck:`, and
`Policy:`. `Vocomipedia:` uses MediaWiki's project namespace.

## Stable Export Rule

The exporter should consume only approved page revisions or approved JSON
snapshots. A wiki edit can be visible as a draft, but it must not enter a
Vocomi deck release until it passes automated validation and human review.

## Item Editing Model

`Item:` pages are generated as template-backed Page Forms pages. The item page
contains calls to:

- `Template:VocomipediaItem`
- `Template:VocomipediaSentence`

`Form:Vocomipedia item` is the contributor-facing editor. Contributors should
change field values only: the bracket-annotated headword, example sentence
source, sentence translations, optional sentence edit reason, and item-level
word translations. For Japanese decks, the sentence source is bracket notation
such as `山[やま]を見る。`; for other languages it is plain sentence text.
Token/POS data is not exposed in the editor. When a contributor changes an
example sentence source, pull captures that change under
`review.sentence_proposals[]` and does not mutate canonical sentence text until
the proposal is applied offline.
Protected fields such as `id`, `pack_code`, `entry_id`, generated entry image
fields, and sentence indexes are generated and must not be changed.

If canonical media is present, `sync_mediawiki.py push-api` generates and
uploads a low-res JPEG file named `Vocomipedia_<deck>_<item>_entry.jpg` and
passes it into `Template:VocomipediaItem`. The template renders it as a
right-side `File:` thumbnail, so the item page has a Wikipedia-style entry
image without exposing the full comic asset. Use `--skip-entry-images` for
text-only syncs.

Item-level `glosses` are exposed as `gloss_<language>` template fields and form
inputs for the app's generated language set, including Japanese for non-Japanese
packs. The item template renders every available gloss in the right-side
infobox; `apply_pulled_items.py` merges those visible word translation edits
back into canonical JSON.

Sentence replacement proposals are review metadata, not release data.
`sync_mediawiki.py` attaches an offline token/POS analysis to each proposal. If
a Japanese edit changes only bracketed furigana while the surface sentence stays
the same, the proposal is classified as `ruby_update` and the generated tokens
carry the user-supplied readings. Reviewers apply accepted proposals with
`apply_sentence_proposals.py --apply`; that command replaces the canonical
sentence, writes generated tokens/readings, updates translations, and syncs
`app_payload.pos_analysis`. The proposal stays auditable under
`review.sentence_proposals[]` with status `applied`.

```bash
python3 tools/apply_sentence_proposals.py \
  --deck-dir data/languages/ja/ja_n5 \
  --proposal-id sentprop-... \
  --apply \
  --diff-report reports/sentence-proposal.diff
```

`sync_mediawiki.py push-api` seeds the templates, form, category, and filter
source pages by default. Use `sync_mediawiki.py seed-structure` to refresh only
those support pages. Use `--push-interface-pages` with an interface
administrator to update the AbuseFilter warning message, `MediaWiki:Common.css`,
and `MediaWiki:Common.js`.
The common CSS hides Page Forms reorder/add/remove controls for generated
sentence instances, keeps sentence instances minimized until opened, and styles
the item image plus summary/glosses as a Wikipedia-like side panel. The common
JavaScript renders bracket ruby notation such as `漢字[かんじ]` as native HTML
ruby in item titles and Japanese sentences.

The local bootstrap installs an active AbuseFilter rule named
`Vocomipedia item structure guard`. For production, install the same rule from
`Vocomipedia:AbuseFilter item structure` in `Special:AbuseFilter`, set the
action to `disallow`, and use the seeded warning message.

## Current Moderation Model

The Docker setup installs Extension:Moderation in the MediaWiki image and loads
it last from `LocalSettings.php`, as recommended by the extension docs.

- Anonymous users cannot edit.
- Logged-in users can submit edits, but edits are queued in `Special:Moderation`.
- Users in `sysop`, `moderator`, or `automoderated` are trusted.
- `VocomiBot` is in the `bot` group and bypasses moderation so sync jobs can
  publish generated pages.
- Moderators should approve legitimate edits, reject vandalism, and then the
  deck maintainer can pull approved wiki state into the release pipeline.

## Admin Surface

The sync bot maintains `Vocomipedia:Admin` by default. It links the moderation
queue, recent changes, sentence replacement proposals, user rights, user list,
blocking tools, AbuseFilter, Nuke, bot passwords, item/deck pages, and policy
pages. Run
`sync_mediawiki.py push-api --push-sidebar` only when the bot account has
`editinterface`; otherwise a human interface administrator can copy the sidebar
content from `render_sidebar_page`.

## Pull/Apply Safety

`sync_mediawiki.py pull-api` records the visible MediaWiki revision metadata in
`review.wiki` and marks pulled visible revisions as approved by default. Use
`--preserve-review-status` for audit-only pulls.

`apply_pulled_items.py` refuses to overwrite a canonical item with a pulled wiki
revision that is older than or equal to the currently recorded revision when the
content differs. Use `--diff-report <path>` to capture the unified JSON diff
for every applied item, and `--force-stale` only for explicit operator recovery.
For existing canonical items, the apply step does not trust arbitrary hidden
JSON edits: it merges only the visible editable fields plus wiki revision
metadata. Template-backed pages are strict: changed protected IDs, missing item
templates, and duplicate/missing sentence indexes are rejected before apply.
Direct sentence rewrites are converted into sentence proposals and stay in
review metadata until `apply_sentence_proposals.py` applies them with generated
token/POS data. Legacy wikitable pages remain accepted as a migration fallback.
Use `--trust-hidden-json` only for controlled operator migrations.
