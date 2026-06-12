#!/usr/bin/env python3
# ios_package_assets_combined.py
# -*- coding: utf-8 -*-

"""
Build iOS asset packages by combining two or more language LEVELS
(e.g. N5 + N4 => LANG_LEVEL "n5-n4", or German A1 + A2 + B1 => "a1-b1").

Output structure (matches single-level packs):
- A single top-level folder named like "<root>_<LEVELS>", e.g. "japanese_N5-N4" or "german_A1-B1"
  - Inside it: an "iOS_assets" folder
    - Inside iOS_assets: the images folder named "<langprefix>_<levels>_images"
    - Inside iOS_assets: the per-language SQLite DB files

Safety checks included:
- Ensures you don't mix languages (LANG_PREFIX) across packs.
- Ensures the directory roots (e.g., "japanese_", "german_") match across packs.
- Ensures all LEVELs belong to the same "family" (JLPT N- or CEFR A/B/C-).
- Ensures the per-entry translation keys ("langs") are consistent across packs.
- Warns on duplicate 'word' IDs (first occurrence wins).

Audio fields from older data are **ignored entirely** (not used for detection and not stored in DB).
"""

import argparse
import os
import io
import re
import json
import sqlite3
import shutil
from typing import Dict, List, Tuple, Any, Set, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ──────────────────────────────────────────────────────────────────────────────
# Image compression (same pipeline as your single-level script)
# ──────────────────────────────────────────────────────────────────────────────
def _with_debug_version_overlay(img: Image.Image, debug_version_overlay: Optional[str]) -> Image.Image:
    if not debug_version_overlay:
        return img

    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)
    text = str(debug_version_overlay).strip()
    if not text:
        return base

    font_px = max(14, int(max(base.width, base.height) * 0.028))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_px)
    except Exception:
        font = ImageFont.load_default()

    margin = max(8, int(max(base.width, base.height) * 0.018))
    stroke = max(1, int(round(font_px * 0.11)))
    text_box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    text_w = max(1, text_box[2] - text_box[0])
    x = max(margin, base.width - margin - text_w)
    y = margin

    draw.text(
        (x, y),
        text,
        fill=(255, 0, 0, 255),
        font=font,
        stroke_width=stroke,
        stroke_fill=(255, 255, 255, 230),
    )
    return base


def compress_png_to_bytes(path: str, debug_version_overlay: Optional[str] = None) -> bytes:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Couldn't find '{path}'")

    img = Image.open(path).convert("RGBA")
    img = _with_debug_version_overlay(img, debug_version_overlay)
    # Resize by 1/1.5 ≈ 0.6667 with high-quality Lanczos
    w, h = img.size
    scale = 1.0 / 1.5
    new_size = (int(w * scale), int(h * scale))
    img_small = img.resize(new_size, resample=Image.Resampling.LANCZOS)
    img_small = img_small.filter(
        ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3)
    )
    pal = img_small.quantize(
        method=Image.Quantize.FASTOCTREE,
        colors=256,
        dither=Image.Dither.FLOYDSTEINBERG
    )
    buf = io.BytesIO()
    pal.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()

def compress_preview_jpg_to_bytes(path: str, target_max_bytes: int = 16 * 1024, debug_version_overlay: Optional[str] = None) -> bytes:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Couldn't find '{path}'")

    img = Image.open(path).convert("RGB")
    img = _with_debug_version_overlay(img, debug_version_overlay).convert("RGB")
    w, h = img.size
    longest = max(w, h)
    target_long_edge = max(160, min(320, int(longest * 0.38)))
    scale = target_long_edge / float(longest)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    img_small = img.resize(new_size, resample=Image.Resampling.LANCZOS)

    # Temporary testing mode: disable blur to inspect preview fidelity.
    attempt = img_small

    quality = 46
    while True:
        buf = io.BytesIO()
        attempt.save(
            buf,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            subsampling=2,
        )
        data = buf.getvalue()
        if len(data) <= target_max_bytes:
            return data

        if quality > 28:
            quality = max(28, quality - 4)
            continue

        if min(attempt.size) > 96:
            attempt = attempt.resize(
                (max(96, int(attempt.size[0] * 0.90)), max(96, int(attempt.size[1] * 0.90))),
                resample=Image.Resampling.LANCZOS,
            )
            continue

        return data


# ──────────────────────────────────────────────────────────────────────────────
# CONFIG — Choose which packs to combine. Do NOT mix languages here.
# Each entry: ASSET_DIR, JSON_FILE, LANG_PREFIX, LEVEL
# ──────────────────────────────────────────────────────────────────────────────
COMBINED_PACKS: List[Dict[str, str]] = [
    # --- Japanese N5 + N4 => LANG_LEVEL "n5-n4" and folder "japanese_N5-N4"
    #{"ASSET_DIR": "./language_packs/japanese_N5", "JSON_FILE": "./language_packs/japanese_N5/japanese_N5_structure.json", "LANG_PREFIX": "ja", "LEVEL": "n5"},
    #{"ASSET_DIR": "./language_packs/japanese_N4", "JSON_FILE": "./language_packs/japanese_N4/japanese_N4_structure.json", "LANG_PREFIX": "ja", "LEVEL": "n4"},

    # --- German A1 + A2 + B1 => LANG_LEVEL "a1-b1" and folder "german_A1-B1"
    #{"ASSET_DIR": "./language_packs/german_A1", "JSON_FILE": "./language_packs/german_A1/german_A1_structure.json", "LANG_PREFIX": "de", "LEVEL": "a1"},
    #{"ASSET_DIR": "./language_packs/german_A2", "JSON_FILE": "./language_packs/german_A2/german_A2_structure.json", "LANG_PREFIX": "de", "LEVEL": "a2"},
    #{"ASSET_DIR": "./language_packs/german_B1", "JSON_FILE": "./language_packs/german_B1/german_B1_structure.json", "LANG_PREFIX": "de", "LEVEL": "b1"},

    # --- French
    {"ASSET_DIR": "./language_packs/french_A1", "JSON_FILE": "./language_packs/french_A1/french_A1_structure.json", "LANG_PREFIX": "fr", "LEVEL": "a1"},
    {"ASSET_DIR": "./language_packs/french_A2", "JSON_FILE": "./language_packs/french_A2/french_A2_structure.json", "LANG_PREFIX": "fr", "LEVEL": "a2"},
    {"ASSET_DIR": "./language_packs/french_B1", "JSON_FILE": "./language_packs/french_B1/french_B1_structure.json", "LANG_PREFIX": "fr", "LEVEL": "b1"},
]

# Optional: Override the parent directory where the combined top-level folder is created.
# If None, we place it alongside the first pack's ASSET_DIR (i.e., same parent).
COMBINED_PARENT_DIR_OVERRIDE: Optional[str] = None


def entry_identifier(entry: Dict[str, Any]) -> str:
    vid = entry.get('entry_id') or entry.get('word')
    if not isinstance(vid, str) or not vid:
        raise RuntimeError(f"Entry without valid identifier: {entry!r}")
    return vid


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for level-family detection and label condensation
# ──────────────────────────────────────────────────────────────────────────────

_JLPT_ORDER = ["n5", "n4", "n3", "n2", "n1"]  # ascending difficulty
_CEFR_ORDER = ["a1", "a2", "b1", "b2", "c1", "c2"]  # ascending difficulty

def _family(level: str) -> str:
    """Return 'jlpt' for n1-n5, 'cefr' for a1-c2; raise if unknown."""
    s = level.strip().lower()
    if re.fullmatch(r"n[1-5]", s):
        return "jlpt"
    if re.fullmatch(r"[abc][12]", s):
        return "cefr"
    raise ValueError(f"Unknown level format: {level!r}. Expected JLPT (n1–n5) or CEFR (a1–c2).")

def _order_index(level: str) -> int:
    s = level.strip().lower()
    fam = _family(s)
    if fam == "jlpt":
        return _JLPT_ORDER.index(s)
    return _CEFR_ORDER.index(s)

def condense_levels(levels: List[str]) -> Tuple[str, List[str]]:
    """
    Given e.g. ["n5","n4"] -> ("n5-n4", ["n5","n4"])
         or ["a1","a2","b1"] -> ("a1-b1", ["a1","a2","b1"])
    If non-contiguous within a family, joins with '+' (e.g. "a1+a2+c1").
    Returns (lowercase_label, sorted_unique_levels_lowercase)
    """
    if not levels:
        raise ValueError("No levels provided.")

    levels_norm = [lv.strip().lower() for lv in levels]
    fams = {_family(lv) for lv in levels_norm}
    if len(fams) != 1:
        raise ValueError(f"Mixed level families not allowed (got {sorted(fams)}).")

    unique = sorted(set(levels_norm), key=_order_index)
    idxs = [_order_index(lv) for lv in unique]
    contiguous = (idxs[-1] - idxs[0] + 1 == len(idxs))

    if contiguous:
        label = f"{unique[0]}-{unique[-1]}"
    else:
        label = "+".join(unique)

    return label, unique

def dir_label_from_levels(levels_lower: List[str]) -> str:
    """
    Produce directory label with uppercased family letter, e.g.:
      ["n5","n4"]           -> "N5-N4"
      ["a1","a2","b1"]      -> "A1-B1"   (contiguous range => lowest-highest only)
      ["a1","b1"]           -> "A1+B1"   (non-contiguous => join all with '+')
      ["b2"]                -> "B2"
    """
    def upcase_token(tok: str) -> str:
        return tok[0].upper() + tok[1:]

    if not levels_lower:
        raise ValueError("No levels provided.")

    # levels_lower is already unique + ordered in the caller (ordered_levels_lc),
    # but we keep the logic robust to ordering/duplication.
    unique_sorted = sorted(set(levels_lower), key=_order_index)

    idxs = [_order_index(lv) for lv in unique_sorted]
    contiguous = (idxs[-1] - idxs[0] + 1 == len(idxs))

    if contiguous:
        # For a single level, return just that level (e.g., "A1"), otherwise lowest-highest.
        if len(unique_sorted) == 1:
            return upcase_token(unique_sorted[0])
        return f"{upcase_token(unique_sorted[0])}-{upcase_token(unique_sorted[-1])}"
    else:
        # Non-contiguous: list all with '+'
        return "+".join(upcase_token(lv) for lv in unique_sorted)


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    n = float(num_bytes)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}"


# ──────────────────────────────────────────────────────────────────────────────
# Core logic
# ──────────────────────────────────────────────────────────────────────────────

def main(combined_packs: Optional[List[Dict[str, str]]] = None,
         parent_override: Optional[str] = None,
         clean: bool = False,
         debug_version_overlay: Optional[str] = None) -> None:
    if combined_packs is None:
        combined_packs = COMBINED_PACKS
    if parent_override is None:
        parent_override = COMBINED_PARENT_DIR_OVERRIDE

    # ─── SANITY CHECK PACKS ──────────────────────────────────────────────────
    if not combined_packs:
        raise RuntimeError("COMBINED_PACKS is empty. Configure at least one pack.")

    # Ensure all LANG_PREFIX are the same (no cross-language mixing)
    prefixes = {p["LANG_PREFIX"].strip().lower() for p in combined_packs}
    if len(prefixes) != 1:
        raise RuntimeError(f"Mixed LANG_PREFIX values found: {sorted(prefixes)}. "
                           f"Do not mix languages in one combined pack.")
    lang_prefix = list(prefixes)[0]

    # Validate files and collect levels in order
    levels_in: List[str] = []
    basenames = []
    for p in combined_packs:
        asset_dir = p["ASSET_DIR"]
        json_file = p["JSON_FILE"]
        if not os.path.isdir(asset_dir):
            raise FileNotFoundError(f"Asset directory not found: {asset_dir}")
        if not os.path.isfile(json_file):
            raise FileNotFoundError(f"JSON file not found: {json_file}")
        levels_in.append(p["LEVEL"])
        basenames.append(os.path.basename(asset_dir))

    # Ensure the directory roots match (e.g., always "japanese_*" or always "german_*")
    def root_part(name: str) -> str:
        return name.split("_", 1)[0].lower() if "_" in name else name.lower()
    roots = {root_part(b) for b in basenames}
    if len(roots) != 1:
        raise RuntimeError(f"Mixed asset roots detected from ASSET_DIR names: {sorted(basenames)}. "
                           f"Do not mix different language sets (e.g., 'japanese_*' with 'german_*').")
    root_token_original_case = basenames[0].split("_", 1)[0] if "_" in basenames[0] else basenames[0]

    # Levels must be same family (jlpt or cefr); compute condensed labels
    combined_level_label_lc, ordered_levels_lc = condense_levels(levels_in)  # lowercase for filenames
    combined_level_label_dir = dir_label_from_levels(ordered_levels_lc)      # uppercase family letter for folder

    # Derive combined top-level folder path
    parent_dir = (parent_override
                  if parent_override is not None
                  else os.path.dirname(os.path.abspath(combined_packs[0]["ASSET_DIR"])))
    combined_folder_name = f"{root_token_original_case}_{combined_level_label_dir}"
    combined_root_dir = os.path.join(parent_dir, combined_folder_name)
    os.makedirs(combined_root_dir, exist_ok=True)

    # Inside combined_root_dir: create iOS_assets and IMAGES_DIR under it (matches single-level)
    ios_assets_dir = os.path.join(combined_root_dir, "iOS_assets")
    if clean and os.path.isdir(ios_assets_dir):
        shutil.rmtree(ios_assets_dir, ignore_errors=True)
    os.makedirs(ios_assets_dir, exist_ok=True)
    images_dir = os.path.join(ios_assets_dir, f"{lang_prefix}_{combined_level_label_lc}_images")
    os.makedirs(images_dir, exist_ok=True)

    print(f"Language prefix: {lang_prefix}")
    print(f"Combining levels: {', '.join(ordered_levels_lc)}  ->  LANG_LEVEL = {combined_level_label_lc}")
    print(f"Combined folder: {combined_root_dir}")
    print(f"DB output dir:  {ios_assets_dir}")
    print(f"Images dir:     {images_dir}")
    if debug_version_overlay:
        print(f"Debug image overlay enabled: {debug_version_overlay}")

    # ─── LOAD & PRE-CLEAN ENTRIES FROM ALL LEVELS ────────────────────────────
    FIXED_KEYS: Set[str] = {
        'word', 'jp', 'fu', 'png_files', 'palette_png_files',
        'comic_difficulty', 'pos_analysis',
    }

    all_entries: List[Dict[str, Any]] = []             # deduplicated list (first occurrence wins)
    word_owner_dir: Dict[str, str] = {}                # word id -> ASSET_DIR of first pack containing it
    word_owner_level: Dict[str, str] = {}              # word id -> LEVEL (lowercase) of first occurrence
    duplicate_words: List[Tuple[str, str, str]] = []   # (word, first_level, dup_level)

    reference_langs: Optional[List[str]] = None
    normalized_fields_count = 0

    for p in combined_packs:
        level = p["LEVEL"].strip().lower()
        asset_dir = p["ASSET_DIR"]
        json_file = p["JSON_FILE"]

        with open(json_file, encoding='utf-8') as f:
            entries = json.load(f)

        if not entries:
            print(f"⚠️ No entries in {json_file}")

        # Detect user-language keys for this pack.
        # IMPORTANT: ignore *_audio completely (older data may include e.g. 'jp_audio' lists).
        langs_this: List[str] = []
        if entries:
            sample = entries[0]
            langs_this = sorted(
                key for key, val in sample.items()
                if key not in FIXED_KEYS
                and not key.endswith('_audio')              # drop audio keys from detection
                and isinstance(val, list)
                and all(isinstance(item, str) for item in val)
            )

            # Enforce consistent user language fields (like original script)
            if reference_langs is None:
                reference_langs = langs_this
            else:
                if langs_this != reference_langs:
                    raise RuntimeError(
                        "Inconsistent user language fields between packs.\n"
                        f"Expected langs: {reference_langs}\n"
                        f"Got langs in level {level}: {langs_this}\n"
                        "Refuse to combine structurally different packs."
                    )

        # Normalize semicolons in "word_*" keys and deduplicate by identifier
        for e in entries:
            for k, v in list(e.items()):
                if k.startswith('word_') and isinstance(v, str) and ';' in v:
                    e[k] = v.replace(';', ' /')
                    normalized_fields_count += 1

            vid = entry_identifier(e)

            if vid in word_owner_dir:
                duplicate_words.append((vid, word_owner_level[vid], level))
                continue

            word_owner_dir[vid] = asset_dir
            word_owner_level[vid] = level
            all_entries.append(e)

    if normalized_fields_count:
        print(f"Normalized semicolons in {normalized_fields_count} fields (word_*)")

    if duplicate_words:
        print(f"⚠️ Found {len(duplicate_words)} duplicate word IDs across levels (keeping first occurrence):")
        for vid, first_level, dup_level in duplicate_words[:15]:
            print(f"   - {vid}: first in {first_level}, duplicate in {dup_level}")
        if len(duplicate_words) > 15:
            print(f"   ...and {len(duplicate_words) - 15} more.")

    if not all_entries:
        raise RuntimeError("No entries loaded. Check your COMBINED_PACKS configuration and JSON files.")

    # ─── EXTRACT & COMPRESS IMAGES (one per unique word id) ──────────────────
    missing_images = 0
    images_written_full = 0
    images_written_preview = 0
    for vid, source_dir in word_owner_dir.items():
        original_fname = f"comic_{vid}_blank.png"
        img_path = os.path.join(source_dir, original_fname)
        out_stem = f"{lang_prefix}_{combined_level_label_lc}_{original_fname[:-4]}"
        out_path_full = os.path.join(images_dir, f"{out_stem}.png")
        out_path_preview = os.path.join(images_dir, f"{out_stem}_preview.jpg")

        if os.path.exists(out_path_full) and os.path.exists(out_path_preview):
            continue

        try:
            blob_full = compress_png_to_bytes(path=img_path, debug_version_overlay=debug_version_overlay)
            blob_preview = compress_preview_jpg_to_bytes(path=img_path, debug_version_overlay=debug_version_overlay)
        except FileNotFoundError:
            print(f"⚠️ Missing image: {original_fname} (expected in {source_dir})")
            missing_images += 1
            continue

        with open(out_path_full, 'wb') as out_f:
            out_f.write(blob_full)
        with open(out_path_preview, 'wb') as out_f:
            out_f.write(blob_preview)
        images_written_full += 1
        images_written_preview += 1

    print(f"✅ Extracted and compressed images into {images_dir} "
          f"(new full-res PNGs: {images_written_full}, new preview JPGs: {images_written_preview}, missing: {missing_images})")

    # ─── BUILD ONE CANONICAL METADATA DATABASE ───────────────────────────────
    db_path = os.path.join(ios_assets_dir, f"{lang_prefix}_{combined_level_label_lc}.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE vocab (
            id       TEXT PRIMARY KEY,
            metadata TEXT NOT NULL
        );
    """)

    for entry in all_entries:
        vid = entry_identifier(entry)
        # Exclude image lists and ANY *_audio keys from metadata
        metadata = {
            k: entry[k]
            for k in entry
            if k not in ('png_files', 'palette_png_files')
            and not k.endswith('_audio')
        }
        cur.execute(
            "INSERT OR IGNORE INTO vocab (id, metadata) VALUES (?, ?);",
            (vid, json.dumps(metadata, ensure_ascii=False))
        )

    conn.commit()
    conn.close()
    print(f"✅ built metadata DB {db_path}")

    # ─── Size summary for quick sanity check ─────────────────────────────────
    def _dir_size(path: str, only_ext: Optional[str] = None) -> int:
        total = 0
        for root, _, files in os.walk(path):
            for fn in files:
                if only_ext and not fn.lower().endswith(only_ext.lower()):
                    continue
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    images_bytes_png = _dir_size(images_dir, only_ext=".png")
    images_bytes_preview = _dir_size(images_dir, only_ext=".jpg")
    images_bytes = images_bytes_png + images_bytes_preview
    db_bytes = _dir_size(ios_assets_dir, only_ext=".db")
    total_bytes = images_bytes + db_bytes

    print("\n— Size summary —")
    print(f"Images (full PNG): {_human_size(images_bytes_png)}")
    print(f"Images (preview JPG): {_human_size(images_bytes_preview)}")
    print(f"Images (total): {_human_size(images_bytes)}  in {images_dir}")
    print(f"DBs:    {_human_size(db_bytes)}  in {ios_assets_dir}")
    print(f"Total:  {_human_size(total_bytes)}")
    if missing_images:
        print(f"Note: {missing_images} image(s) were missing across the input packs.")
    print(f"\nAll images are in: {images_dir}")
    print(f"Metadata DB is in: {ios_assets_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build iOS assets for a combined pack.")
    ap.add_argument(
        "--pack",
        action="append",
        nargs=4,
        metavar=("ASSET_DIR", "JSON_FILE", "LANG_PREFIX", "LEVEL"),
        help="Add one pack to the combined build (repeatable)."
    )
    ap.add_argument("--parent-dir", default=None, help="Override output parent directory.")
    ap.add_argument("--clean", action="store_true", help="Delete existing iOS_assets before rebuilding.")
    ap.add_argument("--debug-version-overlay", default=None, help="Red text overlay burned into top-right of each generated image.")
    args = ap.parse_args()

    if args.pack:
        combined = [
            {
                "ASSET_DIR": p[0],
                "JSON_FILE": p[1],
                "LANG_PREFIX": p[2],
                "LEVEL": p[3],
            }
            for p in args.pack
        ]
    else:
        combined = None

    main(
        combined_packs=combined,
        parent_override=args.parent_dir,
        clean=args.clean,
        debug_version_overlay=args.debug_version_overlay,
    )
