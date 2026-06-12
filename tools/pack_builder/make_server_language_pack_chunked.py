#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Builds a *chunked* encrypted '.vpack' from an iOS package directory.

Format on disk:
    [header_len_be(4)][header_json][ CHUNK_0 ][ CHUNK_1 ] ... [ CHUNK_{N-1} ]

Where each CHUNK_i is:
    [nonce(12)][ciphertext(plain_len_i)][tag(16)]

Header JSON (UTF-8, compact separators):
{
  "format": "vpack-2",                 # new format id
  "chunked": true,                     # reader hint
  "lang_prefix": "...",
  "lang_level": "...",
  "version": "YYYYMMDDThhmmssZ",
  "pack_id": "deadbeef",
  "alg": "AES-256-GCM",
  "chunk_size": <int>,                 # plaintext chunk size (bytes)
  "plaintext_bytes": <int>,            # full ZIP size (bytes)
  "zip_sha256": "<hex of plaintext ZIP>",
  "wrapped_key_b64": "<urlsafe b64 of RSA-OAEP(SHA-256) wrapped 32B key>",
  "created_utc": "..."
}

Usage:
  python make_server_language_pack_chunked.py \
      --source "/path/to/iOS_assets" \
      --lang-prefix de --lang-level a1 \
      --app-pubkey ios_public.pem \
      --outdir ./packs \
      --chunk-mb 16
"""

import argparse, base64, hashlib, io, json, os, sys, time, uuid, zipfile, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from decksearch_prebuilt_index import build_pack_decksearch_indices

ALLOWED_EXTS = {".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".json"}  # expand if needed
PACK_KINDS = {"full", "images", "images_preview", "data"}


# ---------- helpers ----------

def utc_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def base64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

def sha256_file(path: Path, bufsize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(bufsize)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}

def _is_preview_image(path: Path) -> bool:
    n = path.name.lower()
    return n.endswith("_preview.jpg") or n.endswith("_preview.jpeg")

def walk_files(root: Path, pack_kind: str, include_data_files: bool = True) -> List[Path]:
    items = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if pack_kind == "data":
            if p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".json"}:
                items.append(p)
            continue

        # Include DB/index/json payload in non-data packs only when explicitly requested.
        if include_data_files and p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".json"}:
            items.append(p)
            continue

        if not _is_image_file(p):
            continue

        if pack_kind == "images_preview":
            if _is_preview_image(p):
                items.append(p)
            continue

        if pack_kind == "images":
            if not _is_preview_image(p):
                items.append(p)
            continue

        # "full" includes every allowed image asset.
        if p.suffix.lower() in ALLOWED_EXTS:
            items.append(p)
    return items


# ---------- ZIP builder (writes to a temp file on disk; no giant RAM use) ----------

def build_zip_file(root: Path, zip_path: Path, pack_kind: str, include_data_files: bool = True) -> Dict:
    """
    Create zip at zip_path. Returns manifest dict (also embedded in the zip).
    We compute per-file sha256 by streaming, then use ZipFile.write() to avoid
    loading the file into memory.
    """
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "files": []}
    total = 0

    files = walk_files(root, pack_kind, include_data_files=include_data_files)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Put actual files
        for f in files:
            rel = f.relative_to(root).as_posix()

            # streaming sha256 for each file
            fh = open(f, "rb")
            h = hashlib.sha256()
            while True:
                b = fh.read(1024 * 1024)
                if not b: break
                h.update(b)
            fh.close()

            size = f.stat().st_size
            total += size
            manifest["files"].append({"path": rel, "bytes": size, "sha256": h.hexdigest()})

            # write file (ZipFile reads from disk; no RAM spike)
            zf.write(f, arcname=rel)

        # add manifest.json inside the zip
        manifest["total_bytes"] = total
        manifest["file_count"] = len(manifest["files"])
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    return manifest


def load_rsa_public_key(pem_path: Path):
    data = pem_path.read_bytes()
    return serialization.load_pem_public_key(data)


# ---------- header ----------

def make_header_chunked(lang_prefix: str, lang_level: str, version: str, pack_id: str,
                        zip_sha256: str, wrapped_key_b64: str, chunk_size: int,
                        plaintext_bytes: int, pack_kind: str, data_pack_code: Optional[str]) -> Dict:
    return {
        "format": "vpack-2",
        "chunked": True,
        "lang_prefix": lang_prefix,
        "lang_level": lang_level,
        "version": version,
        "pack_id": pack_id,
        "pack_kind": pack_kind,
        "data_pack_code": data_pack_code,
        "alg": "AES-256-GCM",
        "chunk_size": int(chunk_size),
        "plaintext_bytes": int(plaintext_bytes),
        "zip_sha256": zip_sha256,
        "wrapped_key_b64": wrapped_key_b64,
        "created_utc": datetime.now(timezone.utc).isoformat()
    }


# ---------- writer ----------

def write_pack_chunked(outdir: Path, name_base: str, header: Dict,
                       zip_path: Path, content_key: bytes, pack_kind: str,
                       data_pack_code: Optional[str]) -> Tuple[Path, Path, Path]:
    """
    Writes:
      <name_base>.vpack  : [header_len_be(4)][header_json][ (nonce|ciphertext|tag)* ]
      <name_base>.meta.json
      <name_base>.sha256 (streaming; no full-file read into RAM)
    """
    header_json = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header_len = len(header_json)
    if header_len > (1 << 31):
        raise RuntimeError("Header too large")

    vpack_path = outdir / f"{name_base}.vpack"
    enc_hasher = hashlib.sha256()

    with open(vpack_path, "wb") as out_f:
        # header len + header
        out_f.write(header_len.to_bytes(4, "big"))
        out_f.write(header_json)
        enc_hasher.update(header_len.to_bytes(4, "big"))
        enc_hasher.update(header_json)

        # now stream-encrypt the zip by CHUNKs
        CHUNK = int(header["chunk_size"])
        aad = header_json  # bind header to every chunk

        with open(zip_path, "rb") as zf:
            while True:
                plain = zf.read(CHUNK)
                if not plain:
                    break

                nonce = os.urandom(12)
                aes = AESGCM(content_key)
                ct_plus_tag = aes.encrypt(nonce, plain, aad)  # ciphertext || tag(16)

                ct = ct_plus_tag[:-16]
                tag = ct_plus_tag[-16:]

                # write chunk: nonce | ciphertext | tag
                out_f.write(nonce);      enc_hasher.update(nonce)
                out_f.write(ct);         enc_hasher.update(ct)
                out_f.write(tag);        enc_hasher.update(tag)

    # meta for PHP listing
    meta = {
        "name": f"{name_base}.vpack",
        "bytes": vpack_path.stat().st_size,
        "version": header["version"],
        "lang_prefix": header["lang_prefix"],
        "lang_level": header["lang_level"],
        "pack_id": header["pack_id"],
        "zip_sha256": header["zip_sha256"],
        "created_utc": header["created_utc"],
        "pack_kind": pack_kind,
        "data_pack_code": data_pack_code
    }
    meta_path = outdir / f"{name_base}.meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # sha256 (encrypted file) — we already hashed while writing
    sha_path = outdir / f"{name_base}.sha256"
    # NOTE: enc_hasher already contains header + all chunks
    sha_path.write_text(enc_hasher.hexdigest() + "\n", encoding="utf-8")

    return vpack_path, meta_path, sha_path


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Directory with de_a1_*.db and *_images (your iOS_assets)")
    ap.add_argument("--lang-prefix", required=True, help="e.g., de")
    ap.add_argument("--lang-level", required=True, help="e.g., a1")
    ap.add_argument("--app-pubkey", required=True, help="Path to ios_public.pem")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--chunk-mb", type=int, default=16, help="Plaintext chunk size in MB (default: 16)")
    ap.add_argument("--pack-kind", choices=sorted(PACK_KINDS), default="full",
                    help="Pack content type: full (default), images, images_preview, or data")
    ap.add_argument("--data-pack-code", default=None,
                    help="Optional data pack code to embed in header/meta (e.g., de_a1-b1)")
    ap.add_argument("--skip-decksearch-index", action="store_true",
                    help="Skip generating packaged DeckSearch prebuilt indexes.")
    ap.add_argument("--decksearch-ui-langs", default="",
                    help="Optional comma-separated UI language IDs for DeckSearch prebuilt indexes.")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    version = utc_version()
    pack_id = uuid.uuid4().hex[:8]
    name_base = f"{args.lang_prefix}_{args.lang_level}_{version}_{pack_id}"
    include_data_files = args.pack_kind == "data" or not bool(args.data_pack_code)

    if not args.skip_decksearch_index and include_data_files:
        ui_langs = [s.strip() for s in args.decksearch_ui_langs.split(",") if s.strip()] if args.decksearch_ui_langs else None
        print("🧭 Building DeckSearch prebuilt indexes ...")
        manifest = build_pack_decksearch_indices(
            src,
            lang_prefix=args.lang_prefix,
            lang_level=args.lang_level,
            pack_version=version,
            ui_lang_ids=ui_langs
        )
        print(f"   → DeckSearch index files: {manifest.get('index_count', 0)}")
    elif not include_data_files:
        print("🧭 Skipping DeckSearch index build for image-only pack (data provided by mapped data pack).")

    # Build ZIP to disk (temp in outdir to avoid cross-device moves)
    tmp_zip = outdir / f".{name_base}.zip.tmp"
    print(f"📦 Building zip from {src} → {tmp_zip.name} ...")
    manifest = build_zip_file(src, tmp_zip, args.pack_kind, include_data_files=include_data_files)
    zip_size = tmp_zip.stat().st_size
    zip_sha = sha256_file(tmp_zip)
    print(f"   → zip size: {zip_size:,} bytes, files: {manifest['file_count']}")

    # Content key and RSA wrap
    content_key = os.urandom(32)      # AES-256
    pub = load_rsa_public_key(Path(args.app_pubkey))
    wrapped_key = pub.encrypt(
        content_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None)
    )
    wrapped_key_b64 = base64url(wrapped_key)

    # Header (no single nonce; chunks each have their own nonce)
    chunk_bytes = int(args.chunk_mb) * 1024 * 1024
    header = make_header_chunked(
        lang_prefix=args.lang_prefix,
        lang_level=args.lang_level,
        version=version,
        pack_id=pack_id,
        zip_sha256=zip_sha,
        wrapped_key_b64=wrapped_key_b64,
        chunk_size=chunk_bytes,
        plaintext_bytes=zip_size,
        pack_kind=args.pack_kind,
        data_pack_code=args.data_pack_code
    )

    print("🔐 Encrypting (AES-256-GCM, chunked) ...")
    vpack_path, meta_path, sha_path = write_pack_chunked(outdir, name_base, header, tmp_zip, content_key,
                                                         args.pack_kind, args.data_pack_code)

    # Cleanup temp zip
    try: tmp_zip.unlink()
    except Exception: pass

    print(f"✅ Wrote: {vpack_path.name}  ({vpack_path.stat().st_size:,} bytes)")
    print(f"   + meta: {meta_path.name}")
    print(f"   + sha:  {sha_path.name}")

if __name__ == "__main__":
    main()
