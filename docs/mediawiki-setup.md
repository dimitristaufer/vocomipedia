# MediaWiki Setup Notes

Vocomipedia should use MediaWiki for public collaboration and this repository
for release data. The app should receive only approved release snapshots.

Recommended launch stack:

- MediaWiki LTS or current stable release.
- Approved Revs for selecting the approved public revision of item pages.
- Moderation for new-user edits and uploads.
- AbuseFilter for mass deletion, link spam, profanity, suspicious uploads, and
  repeated edit patterns.
- SpamBlacklist for blocked URL and email patterns.
- ConfirmEdit for risky actions, not every edit.
- DiscussionTools for item talk pages.
- RevisionDelete for harmful revisions.
- TwoFactorAuthentication for administrators and moderators.
- Nuke for cleanup after spam bursts.

Avoid open image uploads at launch. Start with text corrections and example
sentence improvements. Comic and image contributions should require approved
contributors, explicit license data, and content safety review.

## Suggested Namespaces

- `Item:` public human-readable item pages generated from canonical JSON.
- `Pack:` public deck pages and release notes.
- `Policy:` contributor rules, licensing, takedown, and moderation rules.
- `Vocomipedia:` project documentation.

## Stable Export Rule

The exporter should consume only approved page revisions or approved JSON
snapshots. A wiki edit can be visible as a draft, but it must not enter a
Vocomi deck release until it passes automated validation and human review.

