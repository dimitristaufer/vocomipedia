# Deck Generation Pipeline

Use this flow for new levels such as `de_b2` or `ja_n3`, and for new languages
such as `sv_a1`.

## Source Contract

The generation side should produce:

- source structure JSON with headwords, readings/labels when available,
  glosses, example sentences, and translations
- the same prompt-driven sentence style and image prompt/style assets used by
  existing decks
- generated image/audio assets in a stable asset directory

Do not build a separate heavy POS/token annotation pipeline in new generation
scripts. Vocomipedia can regenerate sentence token/POS analysis offline during
import with `--auto-pos-analysis`, and sentence edits use the same analyzers
after moderation. Keep legacy `pos_analysis` only as a compatibility input for
older source decks.

## Add A Deck

1. Generate the source JSON and assets in `vocomi_pack_generation`. For new
   decks, use the lightweight generator so generation does not create
   POS/token annotations:

   ```bash
   cd ../vocomi_pack_generation
   python3 vocomipedia_source_generator.py \
     --csv german_B2.csv \
     --deck-code de_b2 \
     --language de \
     --level B2 \
     --output-dir language_packs/german_B2
   ```

   Or run generation, scaffold, and import in one command:

   ```bash
   cd ../vocomi_pack_generation
   python3 vocomipedia_source_pipeline.py \
     --csv german_B2.csv \
     --deck-code de_b2 \
     --title "German B2" \
     --language de \
     --level B2 \
     --data-pack-code de_b2 \
     --mark-approved \
     --validate
   ```

   Keep older language-specific generators only for legacy/Azure-compatible
   workflows.
2. Scaffold the Vocomipedia catalog entry:

   ```bash
   python3 tools/scaffold_deck.py \
     --deck-code de_b2 \
     --title "German B2" \
     --language de \
     --level B2 \
     --data-pack-code de_b2 \
     --source-json vocomi_pack_generation/language_packs/german_B2/german_B2_structure.json \
     --source-asset-dir vocomi_pack_generation/language_packs/german_B2
   ```

3. Smoke import the first few entries:

   ```bash
   python3 tools/sync_all_packs.py \
     --decks de_b2 \
     --limit 5 \
     --copy-media \
     --auto-pos-analysis \
     --mark-approved \
     --validate \
     --strict-media \
     --pack-generation-dir ../vocomi_pack_generation \
     --out-root tmp/deck-smoke \
     --backup-dir reports/backups
   ```

4. Import the full deck into canonical data:

   ```bash
   python3 tools/sync_all_packs.py \
     --decks de_b2 \
     --copy-media \
     --auto-pos-analysis \
     --mark-approved \
     --validate \
     --strict-media \
     --pack-generation-dir ../vocomi_pack_generation \
     --backup-dir reports/backups
   ```

5. Validate and inspect:

   ```bash
   python3 tools/validate_corpus.py --root data/languages --strict-media --release-ready
   python3 tools/audit_pos_pipeline.py --root data/languages --langs de
   ```

6. Commit `catalog/packs.yaml`, `data/languages/<lang>/<deck>/pack.json`, and
   `items/*.json`. Keep `media/` off Git; the release job hydrates media from
   the VPS canonical tree.

7. Upload/copy canonical media to the VPS under:

   ```text
   /srv/vocomipedia/data/languages/<lang>/<deck>/media/
   ```

8. Run `Release And Deploy` with:

   ```text
   deck_codes: de_b2
   ```

## New Languages

Before enabling public sentence editing for a new language:

- add or confirm an analyzer in `tools/vocomipedia_nlp/`
- add representative tests in `tests/test_pipeline.py`
- run `tools/audit_pos_pipeline.py` and review substantial tokenization issues
- verify search returns headwords, readings, translations, and examples

Fallback Unicode tokenization is acceptable for a first private import, but not
for a public deck unless the audit output is acceptable for that language.
