#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


def b64url_decode(value: str) -> bytes:
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + pad)


def load_crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as exc:  # pragma: no cover - dependency diagnostic path
        raise SystemExit(
            "validate_vpack.py requires the 'cryptography' package. "
            "Install it with: python3 -m pip install --user cryptography"
        ) from exc
    return hashes, serialization, padding, AESGCM


def decrypt_vpack(vpack_path: Path, private_key_path: Path) -> tuple[dict, bytes]:
    hashes, serialization, padding, AESGCM = load_crypto()
    raw = vpack_path.read_bytes()
    if len(raw) < 4:
        raise RuntimeError("Bad vpack: missing header length")

    header_len = int.from_bytes(raw[:4], "big")
    header_raw = raw[4 : 4 + header_len]
    header = json.loads(header_raw.decode("utf-8"))
    body = memoryview(raw)[4 + header_len :]

    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    content_key = private_key.decrypt(
        b64url_decode(header["wrapped_key_b64"]),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )

    if header.get("format") != "vpack-2" or not header.get("chunked"):
        nonce_b64 = header.get("nonce_b64")
        if not nonce_b64 or len(body) < 12 + 16:
            raise RuntimeError("Unsupported or malformed non-chunked vpack")
        nonce = bytes(body[:12])
        if nonce != b64url_decode(nonce_b64):
            raise RuntimeError("Header nonce does not match body nonce")
        zip_bytes = AESGCM(content_key).decrypt(nonce, bytes(body[12:]), header_raw)
    else:
        chunk_size = int(header["chunk_size"])
        remaining = int(header["plaintext_bytes"])
        offset = 0
        out = bytearray()
        aes = AESGCM(content_key)
        while remaining > 0:
            plain_len = min(chunk_size, remaining)
            record_len = 12 + plain_len + 16
            if offset + record_len > len(body):
                raise RuntimeError("Bad vpack: truncated encrypted chunk")
            nonce = bytes(body[offset : offset + 12])
            ct_tag = bytes(body[offset + 12 : offset + record_len])
            out.extend(aes.decrypt(nonce, ct_tag, header_raw))
            offset += record_len
            remaining -= plain_len
        zip_bytes = bytes(out)

    actual_sha = hashlib.sha256(zip_bytes).hexdigest()
    if actual_sha != header["zip_sha256"]:
        raise RuntimeError(f"ZIP SHA mismatch: {actual_sha} != {header['zip_sha256']}")
    return header, zip_bytes


def main() -> int:
    ap = argparse.ArgumentParser(description="Decrypt and validate a Vocomi .vpack release artifact.")
    ap.add_argument("--vpack", required=True, type=Path)
    ap.add_argument("--private-key", required=True, type=Path)
    ap.add_argument("--require-sqlite", action="store_true")
    args = ap.parse_args()

    header, zip_bytes = decrypt_vpack(args.vpack, args.private_key)
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "payload.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC failed for {bad}")
            names = zf.namelist()
            if "manifest.json" not in names:
                raise RuntimeError("ZIP payload missing manifest.json")
            if args.require_sqlite and not any(n.endswith((".db", ".sqlite", ".sqlite3")) for n in names):
                raise RuntimeError("ZIP payload missing SQLite database")

    print(
        "Validated "
        f"{args.vpack.name}: format={header.get('format')} "
        f"pack={header.get('lang_prefix')}_{header.get('lang_level')} "
        f"kind={header.get('pack_kind')} zip_sha256={header.get('zip_sha256')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

