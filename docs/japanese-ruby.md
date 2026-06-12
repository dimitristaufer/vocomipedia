# Japanese Ruby Fields

Japanese Vocomipedia items use schema `vocomipedia-item-2`.

Token readings have one editable source of truth:

```json
{
  "surface": "見つけた",
  "reading_kana": "みつけた",
  "ruby_text": "見[み]つけた",
  "ruby_spans": [
    { "base": "見", "reading": "み", "start": 0, "length": 1 }
  ],
  "ruby_source": "sudachipy_sudachidict_core_c",
  "furigana": "みつけた"
}
```

- `ruby_text` is the moderator-facing, dictionary-style value.
- `ruby_spans` is the structured equivalent of `ruby_text`.
- `reading_kana` is the full token reading used for search and legacy export.
- `furigana` is kept as a derived legacy alias for current app compatibility.
- `ruby_source` describes the pipeline that produced the value.

For kana-only tokens, `ruby_text` is just the token surface and `ruby_spans` is
empty.

Dictionary-style means we annotate meaningful kanji chunks, not the whole mixed
kanji/kana token. Okurigana and kana-only parts remain visible text:

```text
見[み]つけた
かな交[ま]じり
振[ふ]る
```

For compounds where the reading belongs to the compound rather than safely to
individual kanji, annotate the compound as one unit, matching dictionary/jukugo
ruby style:

```text
両立[りょうりつ]
今日[きょう]
子供[こども]たち
```

The MediaWiki editor does not expose token meanings or POS fields. For Japanese
decks, contributors edit the example sentence as bracket notation, e.g.
`山[やま]を見る。`, so they can correct both the sentence text and the displayed
furigana in one place. Pull stores sentence-text or bracket-only changes as a
sentence proposal and attaches offline token/POS analysis. Accepted proposals
are applied with `apply_sentence_proposals.py --apply`, which writes the
generated token readings back to `sentences[].tokens[]` and
`app_payload.pos_analysis[]`.

## Sudachi Revision

Existing and newly imported Japanese decks can be revised with SudachiPy and
SudachiDict. This runs locally, so it does not need an API key or network access
after dependencies are installed:

```bash
python3 -m pip install sudachipy sudachidict_core
python3 vocomipedia/tools/revise_japanese_furigana.py \
  --root vocomipedia/data/languages/ja/ja_n5 \
  --sudachi-dict core \
  --sudachi-mode C
```

The tool creates a backup before writing and updates both canonical
`sentences[].tokens[]` and legacy
`app_payload.pos_analysis[].tokens[]`.

For future imports, run the backup-aware sync with:

```bash
python3 vocomipedia/tools/sync_all_packs.py \
  --decks ja_n5 ja_n4 \
  --copy-media \
  --mark-approved \
  --revise-japanese-furigana \
  --validate
```
