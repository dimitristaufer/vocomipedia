# Vocomipedia __v2 collision cleanup

Generated 2026-10-13T13:51:46.389571+00:00. Applied locally; production pages are not yet deleted and release/deployment is not done.

## Findings

- The legacy importer assigns `__v2` when a normalized portable entry identifier occurs a second time. The same-headword rows were already present in the German and Japanese source JSON, but the suffixes were generated during Vocomipedia import. One Korean source row explicitly had `있다__to-be__v2` before import.
- The shared legacy source JSON files were left unchanged. Re-running `sync_all_packs.py` for these decks would recreate generated suffixes from their repeated rows. Keep these reviewed canonical packs authoritative; reconcile the shared source before a future full import.
- Individually reviewed: 256 entries. Merge/remove from canonical deck manifests: 224. Retained as distinct variants: 32.
- Removed canonical rows are merged into the unsuffixed page and their item JSON files are removed from the local pack. `push-api` does not delete wiki pages; the orphaned wiki pages still require a sysop to delete after pending suggestions are resolved.

## Actions by deck

| Deck | Merged/removed | Kept variants |
|---|---:|---:|
| `de_a1` | 2 | 12 |
| `de_a2` | 3 | 2 |
| `de_b1` | 10 | 15 |
| `ja_n4` | 114 | 2 |
| `ja_n5` | 94 | 1 |
| `ko_1` | 1 | 0 |

## Individual decisions

| Deck | Entry | Decision | Action | Fixes |
|---|---|---|---|---|
| `de_a1` | `Bank__v2` | `merge_candidate` | merge into base and remove from pack manifest → `Bank` | — |
| `de_a1` | `Lkw__v2` | `merge_candidate` | merge into base and remove from pack manifest → `LKW` | — |
| `de_a1` | `an__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `an` | — |
| `de_a1` | `bitte__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Bitte` | — |
| `de_a1` | `da__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `da` | — |
| `de_a1` | `einfach__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `einfach` | removed adjective examples; retained adverb sense; localized adverb glosses |
| `de_a1` | `essen__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Essen` | — |
| `de_a1` | `gleich__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `gleich` | — |
| `de_a1` | `ihr__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `ihr` | — |
| `de_a1` | `leben__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Leben` | — |
| `de_a1` | `morgen__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Morgen` | — |
| `de_a1` | `sein__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `sein` | — |
| `de_a1` | `sie__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Sie` | — |
| `de_a1` | `zu__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `zu` | — |
| `de_a2` | `Schloss__v2` | `merge_candidate` | merge into base and remove from pack manifest → `Schloss` | — |
| `de_a2` | `gegenüber__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `gegenüber` | — |
| `de_a2` | `hängen__v2` | `merge_candidate` | merge into base and remove from pack manifest → `hängen` | — |
| `de_a2` | `raten__v2` | `merge_candidate` | merge into base and remove from pack manifest → `raten` | — |
| `de_a2` | `unterhalten__v2` | `keep_variant_needs_repair` | retain stable item ID; fix content/display disambiguation → `unterhalten` | removed chat examples; retained transitive entertain sense; localized entertainment glosses |
| `de_b1` | `Ausdruck__v2` | `merge_candidate` | merge into base and remove from pack manifest → `Ausdruck` | — |
| `de_b1` | `Billett__v2` | `merge_candidate` | merge into base and remove from pack manifest → `Billett` | — |
| `de_b1` | `Glace__v2` | `merge_candidate_fix_gender` | merge into base and remove from pack manifest → `Glace` | gender→feminine; label marks Swiss usage |
| `de_b1` | `Leiter__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Leiter` | — |
| `de_b1` | `Pension__v2` | `merge_candidate` | merge into base and remove from pack manifest → `Pension` | — |
| `de_b1` | `damit__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `damit` | — |
| `de_b1` | `erschrecken__v2` | `merge_candidate` | merge into base and remove from pack manifest → `erschrecken` | — |
| `de_b1` | `gar__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `gar` | — |
| `de_b1` | `halt__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Halt` | — |
| `de_b1` | `heim__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Heim` | — |
| `de_b1` | `noch mal__v2` | `merge_candidate` | merge into base and remove from pack manifest → `noch mal` | — |
| `de_b1` | `nochmal__v2` | `merge_candidate` | merge into base and remove from pack manifest → `nochmal` | — |
| `de_b1` | `original__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Original` | — |
| `de_b1` | `recht__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Recht` | — |
| `de_b1` | `schaden__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Schaden` | — |
| `de_b1` | `schuld__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Schuld` | — |
| `de_b1` | `so viel__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `so viel` | — |
| `de_b1` | `soviel__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `soviel` | — |
| `de_b1` | `stecken__v2` | `merge_candidate` | merge into base and remove from pack manifest → `stecken` | — |
| `de_b1` | `teilweise__v2` | `merge_candidate_fix_pos` | merge into base and remove from pack manifest → `teilweise` | POS→adverb |
| `de_b1` | `vergnügen__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Vergnügen` | — |
| `de_b1` | `verhalten__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Verhalten` | — |
| `de_b1` | `verlassen__v2` | `merge_candidate` | merge into base and remove from pack manifest → `verlassen` | — |
| `de_b1` | `vertrauen__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Vertrauen` | — |
| `de_b1` | `wert__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `Wert` | — |
| `ja_n4` | `〜の方__v2` | `merge_candidate` | merge into base and remove from pack manifest → `〜の方` | — |
| `ja_n4` | `いらっしゃる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `いらっしゃる` | — |
| `ja_n4` | `お宅__v2` | `merge_candidate` | merge into base and remove from pack manifest → `お宅` | — |
| `ja_n4` | `お祝い__v2` | `merge_candidate` | merge into base and remove from pack manifest → `お祝い` | — |
| `ja_n4` | `ご覧になる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ご覧になる` | — |
| `ja_n4` | `ベル__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ベル` | — |
| `ja_n4` | `上がる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `上がる` | — |
| `ja_n4` | `下がる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `下がる` | — |
| `ja_n4` | `下げる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `下げる` | — |
| `ja_n4` | `世話をする__v2` | `merge_candidate` | merge into base and remove from pack manifest → `世話をする` | — |
| `ja_n4` | `乾く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `乾く` | — |
| `ja_n4` | `亡くなる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `亡くなる` | — |
| `ja_n4` | `付く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `付く` | — |
| `ja_n4` | `伝える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `伝える` | — |
| `ja_n4` | `信じる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `信じる` | — |
| `ja_n4` | `倒れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `倒れる` | — |
| `ja_n4` | `入院する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `入院する` | — |
| `ja_n4` | `出す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出す` | — |
| `ja_n4` | `出る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出る` | — |
| `ja_n4` | `出発する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出発する` | — |
| `ja_n4` | `切る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `切る` | — |
| `ja_n4` | `別れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `別れる` | — |
| `ja_n4` | `利用する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `利用する` | — |
| `ja_n4` | `割れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `割れる` | — |
| `ja_n4` | `包む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `包む` | — |
| `ja_n4` | `十分__v2` | `merge_candidate` | merge into base and remove from pack manifest → `十分` | — |
| `ja_n4` | `卒業する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `卒業する` | — |
| `ja_n4` | `危険__v2` | `merge_candidate` | merge into base and remove from pack manifest → `危険` | — |
| `ja_n4` | `参る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `参る` | — |
| `ja_n4` | `参加する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `参加する` | — |
| `ja_n4` | `取り替える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `取り替える` | — |
| `ja_n4` | `受ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `受ける` | — |
| `ja_n4` | `召し上がる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `召し上がる` | — |
| `ja_n4` | `合う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `合う` | — |
| `ja_n4` | `向かう__v2` | `merge_candidate` | merge into base and remove from pack manifest → `向かう` | — |
| `ja_n4` | `君__v2` | `merge_candidate` | merge into base and remove from pack manifest → `君` | corrected reading/gloss to きみ (“you”) |
| `ja_n4` | `噛む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `噛む` | — |
| `ja_n4` | `増える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `増える` | — |
| `ja_n4` | `壊す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `壊す` | — |
| `ja_n4` | `壊れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `壊れる` | — |
| `ja_n4` | `変__v2` | `merge_candidate` | merge into base and remove from pack manifest → `変` | — |
| `ja_n4` | `変わる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `変わる` | — |
| `ja_n4` | `太る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `太る` | — |
| `ja_n4` | `安全__v2` | `merge_candidate` | merge into base and remove from pack manifest → `安全` | — |
| `ja_n4` | `安心__v2` | `merge_candidate` | merge into base and remove from pack manifest → `安心` | — |
| `ja_n4` | `安心する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `安心する` | — |
| `ja_n4` | `届ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `届ける` | — |
| `ja_n4` | `建てる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `建てる` | — |
| `ja_n4` | `復習する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `復習する` | — |
| `ja_n4` | `必要__v2` | `merge_candidate` | merge into base and remove from pack manifest → `必要` | — |
| `ja_n4` | `慣れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `慣れる` | — |
| `ja_n4` | `戻る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `戻る` | — |
| `ja_n4` | `投げる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `投げる` | — |
| `ja_n4` | `折る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `折る` | — |
| `ja_n4` | `折れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `折れる` | — |
| `ja_n4` | `招待する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `招待する` | — |
| `ja_n4` | `拾う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `拾う` | — |
| `ja_n4` | `掛ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `掛ける` | — |
| `ja_n4` | `探す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `探す` | — |
| `ja_n4` | `植える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `植える` | — |
| `ja_n4` | `楽しむ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `楽しむ` | — |
| `ja_n4` | `止める__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `止める` | — |
| `ja_n4` | `死ぬ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `死ぬ` | — |
| `ja_n4` | `残る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `残る` | — |
| `ja_n4` | `汚れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `汚れる` | — |
| `ja_n4` | `決める__v2` | `merge_candidate` | merge into base and remove from pack manifest → `決める` | — |
| `ja_n4` | `沸かす__v2` | `merge_candidate` | merge into base and remove from pack manifest → `沸かす` | — |
| `ja_n4` | `治る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `治る` | — |
| `ja_n4` | `泣く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `泣く` | — |
| `ja_n4` | `注意する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `注意する` | — |
| `ja_n4` | `滑る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `滑る` | — |
| `ja_n4` | `焼く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `焼く` | combined burning, baking, grilling and toasting senses |
| `ja_n4` | `焼ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `焼ける` | — |
| `ja_n4` | `燃える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `燃える` | — |
| `ja_n4` | `特別__v2` | `merge_candidate` | merge into base and remove from pack manifest → `特別` | — |
| `ja_n4` | `用意する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `用意する` | — |
| `ja_n4` | `申す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `申す` | — |
| `ja_n4` | `真っ白__v2` | `merge_candidate` | merge into base and remove from pack manifest → `真っ白` | — |
| `ja_n4` | `眠る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `眠る` | — |
| `ja_n4` | `知らせる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `知らせる` | — |
| `ja_n4` | `私__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `私` | — |
| `ja_n4` | `笑う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `笑う` | — |
| `ja_n4` | `答える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `答える` | — |
| `ja_n4` | `続く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `続く` | — |
| `ja_n4` | `続ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `続ける` | — |
| `ja_n4` | `聞こえる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `聞こえる` | — |
| `ja_n4` | `育てる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `育てる` | — |
| `ja_n4` | `落ちる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `落ちる` | — |
| `ja_n4` | `落とす__v2` | `merge_candidate` | merge into base and remove from pack manifest → `落とす` | — |
| `ja_n4` | `行う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `行う` | — |
| `ja_n4` | `複雑__v2` | `merge_candidate` | merge into base and remove from pack manifest → `複雑` | — |
| `ja_n4` | `褒める__v2` | `merge_candidate` | merge into base and remove from pack manifest → `褒める` | — |
| `ja_n4` | `見える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見える` | — |
| `ja_n4` | `見つかる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見つかる` | — |
| `ja_n4` | `見つける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見つける` | — |
| `ja_n4` | `謝る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `謝る` | — |
| `ja_n4` | `質問する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `質問する` | — |
| `ja_n4` | `走る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `走る` | — |
| `ja_n4` | `起きる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `起きる` | — |
| `ja_n4` | `踊る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `踊る` | — |
| `ja_n4` | `踏む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `踏む` | — |
| `ja_n4` | `込む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `込む` | — |
| `ja_n4` | `逃げる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `逃げる` | — |
| `ja_n4` | `通う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `通う` | — |
| `ja_n4` | `通る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `通る` | — |
| `ja_n4` | `進む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `進む` | — |
| `ja_n4` | `遅れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `遅れる` | — |
| `ja_n4` | `運ぶ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `運ぶ` | — |
| `ja_n4` | `過ぎる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `過ぎる` | — |
| `ja_n4` | `選ぶ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `選ぶ` | — |
| `ja_n4` | `閉じる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `閉じる` | — |
| `ja_n4` | `開く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `開く` | — |
| `ja_n4` | `間に合う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `間に合う` | — |
| `ja_n4` | `集まる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `集まる` | — |
| `ja_n4` | `飾る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `飾る` | — |
| `ja_n4` | `騒ぐ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `騒ぐ` | — |
| `ja_n5` | `いらっしゃる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `いらっしゃる` | — |
| `ja_n5` | `お茶__v2` | `merge_candidate` | merge into base and remove from pack manifest → `お茶` | — |
| `ja_n5` | `お金__v2` | `merge_candidate` | merge into base and remove from pack manifest → `お金` | — |
| `ja_n5` | `する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `する` | — |
| `ja_n5` | `では__v2` | `merge_candidate` | merge into base and remove from pack manifest → `では` | — |
| `ja_n5` | `わかる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `わかる` | — |
| `ja_n5` | `テーブル__v2` | `merge_candidate` | merge into base and remove from pack manifest → `テーブル` | — |
| `ja_n5` | `ドア__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ドア` | — |
| `ja_n5` | `パーティー__v2` | `merge_candidate` | merge into base and remove from pack manifest → `パーティー` | — |
| `ja_n5` | `ベッド__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ベッド` | — |
| `ja_n5` | `ホテル__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ホテル` | — |
| `ja_n5` | `ポスト__v2` | `merge_candidate` | merge into base and remove from pack manifest → `ポスト` | — |
| `ja_n5` | `上手__v2` | `merge_candidate` | merge into base and remove from pack manifest → `上手` | — |
| `ja_n5` | `下手__v2` | `merge_candidate` | merge into base and remove from pack manifest → `下手` | — |
| `ja_n5` | `乗る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `乗る` | — |
| `ja_n5` | `休む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `休む` | — |
| `ja_n5` | `会う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `会う` | — |
| `ja_n5` | `何__v2` | `merge_candidate` | merge into base and remove from pack manifest → `何` | — |
| `ja_n5` | `何時__v2` | `merge_candidate` | merge into base and remove from pack manifest → `何時` | reading→なんじ |
| `ja_n5` | `作る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `作る` | — |
| `ja_n5` | `使う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `使う` | — |
| `ja_n5` | `借りる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `借りる` | — |
| `ja_n5` | `働く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `働く` | — |
| `ja_n5` | `入る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `入る` | — |
| `ja_n5` | `入れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `入れる` | — |
| `ja_n5` | `円__v2` | `merge_candidate` | merge into base and remove from pack manifest → `円` | — |
| `ja_n5` | `出かける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出かける` | — |
| `ja_n5` | `出す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出す` | — |
| `ja_n5` | `出る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `出る` | — |
| `ja_n5` | `切る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `切る` | — |
| `ja_n5` | `吸う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `吸う` | — |
| `ja_n5` | `呼ぶ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `呼ぶ` | — |
| `ja_n5` | `売る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `売る` | — |
| `ja_n5` | `失礼する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `失礼する` | — |
| `ja_n5` | `寝る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `寝る` | — |
| `ja_n5` | `帰る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `帰る` | — |
| `ja_n5` | `座る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `座る` | — |
| `ja_n5` | `引く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `引く` | — |
| `ja_n5` | `弾く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `弾く` | — |
| `ja_n5` | `待つ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `待つ` | — |
| `ja_n5` | `忘れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `忘れる` | — |
| `ja_n5` | `押す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `押す` | — |
| `ja_n5` | `持つ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `持つ` | — |
| `ja_n5` | `掃除する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `掃除する` | — |
| `ja_n5` | `撮る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `撮る` | — |
| `ja_n5` | `教える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `教える` | — |
| `ja_n5` | `曲がる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `曲がる` | — |
| `ja_n5` | `書く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `書く` | — |
| `ja_n5` | `来る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `来る` | — |
| `ja_n5` | `歌う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `歌う` | — |
| `ja_n5` | `歩く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `歩く` | — |
| `ja_n5` | `毎年__v2` | `merge_candidate` | merge into base and remove from pack manifest → `毎年` | reading→まいとし / まいねん, reading includes both accepted forms |
| `ja_n5` | `気をつける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `気をつける` | — |
| `ja_n5` | `泳ぐ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `泳ぐ` | — |
| `ja_n5` | `洗う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `洗う` | — |
| `ja_n5` | `浴びる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `浴びる` | — |
| `ja_n5` | `消す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `消す` | — |
| `ja_n5` | `渡る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `渡る` | — |
| `ja_n5` | `生まれる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `生まれる` | — |
| `ja_n5` | `留学する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `留学する` | — |
| `ja_n5` | `疲れる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `疲れる` | — |
| `ja_n5` | `着く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `着く` | — |
| `ja_n5` | `着る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `着る` | — |
| `ja_n5` | `知る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `知る` | — |
| `ja_n5` | `立つ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `立つ` | — |
| `ja_n5` | `終わる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `終わる` | — |
| `ja_n5` | `置く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `置く` | — |
| `ja_n5` | `習う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `習う` | — |
| `ja_n5` | `聞く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `聞く` | — |
| `ja_n5` | `脱ぐ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `脱ぐ` | — |
| `ja_n5` | `行く__v2` | `merge_candidate` | merge into base and remove from pack manifest → `行く` | — |
| `ja_n5` | `要る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `要る` | — |
| `ja_n5` | `見せる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見せる` | — |
| `ja_n5` | `見る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見る` | — |
| `ja_n5` | `見学する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `見学する` | — |
| `ja_n5` | `覚える__v2` | `merge_candidate` | merge into base and remove from pack manifest → `覚える` | — |
| `ja_n5` | `言う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `言う` | — |
| `ja_n5` | `話す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `話す` | — |
| `ja_n5` | `読む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `読む` | — |
| `ja_n5` | `買い物する__v2` | `merge_candidate` | merge into base and remove from pack manifest → `買い物する` | — |
| `ja_n5` | `買う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `買う` | — |
| `ja_n5` | `貸す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `貸す` | — |
| `ja_n5` | `起きる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `起きる` | — |
| `ja_n5` | `足りる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `足りる` | — |
| `ja_n5` | `返す__v2` | `merge_candidate` | merge into base and remove from pack manifest → `返す` | — |
| `ja_n5` | `遊ぶ__v2` | `merge_candidate` | merge into base and remove from pack manifest → `遊ぶ` | — |
| `ja_n5` | `違う__v2` | `merge_candidate` | merge into base and remove from pack manifest → `違う` | — |
| `ja_n5` | `閉める__v2` | `merge_candidate` | merge into base and remove from pack manifest → `閉める` | — |
| `ja_n5` | `開ける__v2` | `merge_candidate` | merge into base and remove from pack manifest → `開ける` | — |
| `ja_n5` | `降りる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `降りる` | — |
| `ja_n5` | `降る__v2` | `merge_candidate` | merge into base and remove from pack manifest → `降る` | — |
| `ja_n5` | `食べる__v2` | `merge_candidate` | merge into base and remove from pack manifest → `食べる` | — |
| `ja_n5` | `飲む__v2` | `merge_candidate` | merge into base and remove from pack manifest → `飲む` | — |
| `ja_n5` | `～人__v2` | `keep_variant` | retain stable item ID; fix content/display disambiguation → `～人` | — |
| `ja_n5` | `～年__v2` | `merge_candidate` | merge into base and remove from pack manifest → `～年` | reading→～ねん, reading→～ねん |
| `ko_1` | `있다__to-be__v2` | `merge_candidate` | merge into base and remove from pack manifest → `있다__to-be` | — |
| `de_a1` | `sein` | `base_entry_repair` | retain base item ID; repair lexical metadata → `sein` | en-gloss→his; its, corrected localized possessive glosses, POS→Other (possessive determiner) |

## Sentence repairs and exclusions

- `ja_n4/安心__v2`: 安心__v2:子どもが無事に帰ってきて、安心だ。
- `ja_n4/折れる__v2`: 折れる__v2:子どもが枝を強く曲げすぎて、折ってしまった。
- `ja_n4/治る__v2`: 治る:パソコンの故障がやっと治った。
- `ja_n4/泣く__v2`: 泣く__v2:ねこが泣きます。
- `ja_n4/泣く__v2`: 泣く__v2:ねこは泣きません。
- `ja_n4/泣く__v2`: 泣く__v2:ねこが泣いていた。
- `ja_n4/申す__v2`: 申す__v2:失礼を申しますが、もう一度お名前を教えていただけますか？
- `ja_n4/行う__v2`: 行う:彼の行いはみんなに感動を与えた。
- `ja_n4/謝る__v2`: 謝る__v2:どれだけ謝りますと言っても、許せないよ。
- `ja_n4/通う__v2`: 通う:バスは毎朝学校と家を通っている。
- `ja_n5/待つ__v2`: 待つ__v2:電車が遅れています。少々お待ちください。
- `ja_n5/待つ__v2`: 待つ__v2:ご注文のケーキはただいま焼いています。少々お待ちください。
- `ja_n5/待つ__v2`: 待つ__v2:資料を探しますので、少々お待ちください。
- `ja_n5/立つ__v2`: 立つ__v2:目覚まし時計が鳴ったら、私はすぐにベッドから立ちます。
- `ja_n5/立つ__v2`: 立つ__v2:バスが来たので、私はベンチから立ちます。
- `ja_n5/置く__v2`: 置く__v2:猫はエサを玄関に置いています。
- `ja_n5/話す__v2`: 話す__v2:はじめまして。自己紹介を話しますね。
- `ja_n5/足りる__v2`: 足りる__v2:このりょうでおなかが足りますか？

- Exact repeated German sentences were deduplicated during the merge: `de_a1/Bank__v2` (“Ich gehe zur Bank.”), `de_a2/raten__v2` (“Ich kann dir nur raten.”), `de_b1/Pension__v2` (“Mein Vater geht nächstes Jahr in Pension.”), and `de_b1/noch mal__v2` (“Ich frage noch mal nach.”).

- `ja_n5/見せる__v2`: kept one natural polite request (`旅行の写真を見せてください。`) and removed the four other repetitive “show me” requests.

## Pending moderation suggestions

- Suggestions on `折れる__v2` (revision 30548), `謝る__v2` (31514), `話す__v2` (70204), and `足りる__v2` remain pending on the live wiki. Corrected or unsuitable examples were handled in the local merge as recorded above. Do not delete those wiki pages until a sysop checks their pending queue. The `足りる__v2` proposals are `sentprop-fb4523f902a77b35`, `sentprop-17ce384cd90afe57`, and `sentprop-0119cf43f1fd16e4`.
- The three pending `足りる__v2` sentence proposals were reviewed separately: the original stomach/amount sentence was excluded as ungrammatical; the ingredient spelling proposal is a kana-to-kanji normalization; the ticket sentence is understandable as written. The latter two remain on the orphan wiki page for moderation, so defer page deletion until resolved.
- Other pending suggestions previously submitted affect unsuffixed `通う`, `治る`, and `何時`; their canonical contents were reconciled with current live fields where applicable.

## Release / wiki cleanup

- Review the local pack and index-label changes, merge them through the normal sync-back PR, then run the approved release and rebuild the index/search data.
- After the new manifests are deployed, have a sysop delete the pages with a merge action in `cleanup_actions.csv`, except pages whose pending suggestions still need moderation. The CSV includes each exact `Item:<deck>/<stable-id>` title. The release and hold queues are listed in [`id-collision-v2-wiki-deletions.txt`](id-collision-v2-wiki-deletions.txt).
- Source backup: `/Users/dimitristaufer/.vocomipedia/reviews/id-collision-v2-2026-10-13/source-backup-before-cleanup`.
- Complete item-by-item audit: [`id-collision-v2-item-audit.jsonl`](id-collision-v2-item-audit.jsonl).
- Item-by-item cleanup details: [`id-collision-v2-cleanup-actions.csv`](id-collision-v2-cleanup-actions.csv).
