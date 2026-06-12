#!/usr/bin/env python3
# ios_package_assets.py
# -*- coding: utf-8 -*-

import argparse
import os
import json
import sqlite3
import io
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _with_debug_version_overlay(img: Image.Image, debug_version_overlay: str | None) -> Image.Image:
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
    text_h = max(1, text_box[3] - text_box[1])
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


def compress_png_to_bytes(path: str, debug_version_overlay: str | None = None) -> bytes:
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

def compress_preview_jpg_to_bytes(path: str, target_max_bytes: int = 16 * 1024, debug_version_overlay: str | None = None) -> bytes:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Couldn't find '{path}'")

    img = Image.open(path).convert("RGB")
    img = _with_debug_version_overlay(img, debug_version_overlay).convert("RGB")
    w, h = img.size
    longest = max(w, h)
    # Temporarily run larger previews for visual QA.
    target_long_edge = max(160, min(320, int(longest * 0.38)))
    scale = target_long_edge / float(longest)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    img_small = img.resize(new_size, resample=Image.Resampling.LANCZOS)

    # Temporary testing mode: disable blur to inspect preview fidelity.
    blurred = img_small

    quality = 46
    attempt = blurred
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

        # Quality bottomed out: reduce dimensions and retry.
        if min(attempt.size) > 96:
            attempt = attempt.resize(
                (max(96, int(attempt.size[0] * 0.90)), max(96, int(attempt.size[1] * 0.90))),
                resample=Image.Resampling.LANCZOS,
            )
            continue

        return data


def build_assets(asset_dir: str,
                 json_file: str,
                 lang_prefix: str,
                 lang_level: str,
                 output_dir: str | None = None,
                 debug_version_overlay: str | None = None) -> None:
    asset_dir = os.path.abspath(asset_dir)
    json_file = os.path.abspath(json_file)
    if output_dir is None:
        output_dir = os.path.join(asset_dir, "iOS_assets")
    output_dir = os.path.abspath(output_dir)

    if not os.path.isdir(asset_dir):
        raise FileNotFoundError(f"Asset directory not found: {asset_dir}")
    if not os.path.isfile(json_file):
        raise FileNotFoundError(f"JSON file not found: {json_file}")

    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, f"{lang_prefix}_{lang_level}_images")
    os.makedirs(images_dir, exist_ok=True)
    if debug_version_overlay:
        print(f"Debug image overlay enabled: {debug_version_overlay}")

    with open(json_file, encoding='utf-8') as f:
        entries = json.load(f)

    # Replace ";" -> " /" in all translation fields (keys starting with "word_")
    changed_fields = 0
    for e in entries:
        for k, v in e.items():
            if k.startswith('word_') and isinstance(v, str) and ';' in v:
                e[k] = v.replace(';', ' /')
                changed_fields += 1
    if changed_fields:
        print(f"Normalized semicolons in {changed_fields} fields (word_*)")

    def entry_identifier(entry):
        vid = entry.get('entry_id') or entry.get('word')
        if not isinstance(vid, str) or not vid:
            raise RuntimeError(f"Entry without valid identifier: {entry!r}")
        return vid

    # Extract & compress images
    for entry in entries:
        vid = entry_identifier(entry)
        suffix = '_blank.png'
        original_fname = f'comic_{vid}{suffix}'
        img_path = os.path.join(asset_dir, original_fname)
        try:
            blob_full = compress_png_to_bytes(path=img_path, debug_version_overlay=debug_version_overlay)
            blob_preview = compress_preview_jpg_to_bytes(path=img_path, debug_version_overlay=debug_version_overlay)
        except FileNotFoundError:
            print(f"⚠️ Missing image: {original_fname}")
            continue
        out_stem = f"{lang_prefix}_{lang_level}_{original_fname[:-4]}"

        out_path_full = os.path.join(images_dir, f"{out_stem}.png")
        with open(out_path_full, 'wb') as out_f:
            out_f.write(blob_full)

        out_path_preview = os.path.join(images_dir, f"{out_stem}_preview.jpg")
        with open(out_path_preview, 'wb') as out_f:
            out_f.write(blob_preview)
    print(f"✅ Extracted and compressed images into {images_dir}")

    # Build one canonical metadata DB per pack. Legacy per-UI-language DB
    # variants are no longer needed because metadata rows are language-complete.
    db_path = os.path.join(output_dir, f"{lang_prefix}_{lang_level}.db")
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
    for entry in entries:
        vid = entry_identifier(entry)
        metadata = {
            k: entry[k]
            for k in entry
            if k not in ('png_files', 'palette_png_files')
        }
        cur.execute(
            "INSERT OR IGNORE INTO vocab (id, metadata) VALUES (?, ?);",
            (vid, json.dumps(metadata, ensure_ascii=False))
        )
    conn.commit()
    conn.close()
    print(f"✅ built metadata DB {db_path}")
    print(f"\nMetadata DB is in: {output_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build iOS assets for a single pack.")
    ap.add_argument("--asset-dir", default=None)
    ap.add_argument("--json-file", default=None)
    ap.add_argument("--lang-prefix", default=None)
    ap.add_argument("--lang-level", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--debug-version-overlay", default=None)
    args = ap.parse_args()

    # Legacy defaults (preserve current behavior when run without args)
    default_asset_dir = './language_packs/korean_topik_1'
    default_json_file = os.path.join(default_asset_dir, 'korean_topik_1_structure_main_annot.json')
    default_lang_prefix = 'ko'
    default_lang_level = '1'

    use_defaults = not any([args.asset_dir, args.json_file, args.lang_prefix, args.lang_level, args.output_dir])
    if use_defaults:
        asset_dir = default_asset_dir
        json_file = default_json_file
        lang_prefix = default_lang_prefix
        lang_level = default_lang_level
        output_dir = None
    else:
        if not (args.asset_dir and args.json_file and args.lang_prefix and args.lang_level):
            ap.error("--asset-dir, --json-file, --lang-prefix, and --lang-level are required")
        asset_dir = args.asset_dir
        json_file = args.json_file
        lang_prefix = args.lang_prefix
        lang_level = args.lang_level
        output_dir = args.output_dir

    build_assets(
        asset_dir=asset_dir,
        json_file=json_file,
        lang_prefix=lang_prefix,
        lang_level=lang_level,
        output_dir=output_dir,
        debug_version_overlay=args.debug_version_overlay
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
